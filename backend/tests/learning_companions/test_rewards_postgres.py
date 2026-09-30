"""Isolated PostgreSQL checks for durable earned rewards and pet ownership.

These tests require the explicitly allowlisted disposable database in
``tests.conftest.postgres_database``. They never reconstruct completion from
room or solo content; each synthetic receipt carries answer-free proof.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.db.models.user import UserModel
from app.db.session import Database
from app.learning_companions.contracts import (
    CoinLedgerKind,
    CompletionEvidence,
    CompletionSource,
    ReceiptStatus,
)
from app.learning_companions.models import (
    CoinLedgerModel,
    CoinWalletModel,
    CompletionReceiptModel,
    PetEquipmentModel,
    PetOwnershipModel,
    PetPurchaseModel,
    QualifiedStudyDayModel,
)
from app.learning_companions.pet_service import PetService
from app.learning_companions.reward_repository import (
    RewardRepository,
    insert_completion_receipt,
)
from app.repositories.postgres_users import PostgresUserRepository


ACCEPTED_AT = datetime(2026, 3, 28, 23, 30, tzinfo=timezone.utc)
COMPLETED_AT = datetime(2026, 3, 31, 12, tzinfo=timezone.utc)
ORDER_BASE = datetime(2026, 3, 31, 13, tzinfo=timezone.utc)
STUDY_DATE = date(2026, 3, 28)


def _user(database: Database) -> UUID:
    user_id = uuid4()
    PostgresUserRepository(database.session_factory).upsert_profile(
        user_id, "Reward Test Student"
    )
    return user_id


def _receipts(
    database: Database, user_id: UUID, count: int
) -> list[tuple[UUID, CompletionEvidence]]:
    inserted: list[tuple[UUID, CompletionEvidence]] = []
    with database.session_factory.begin() as session:
        for position in range(count):
            evidence = CompletionEvidence(
                user_id=user_id,
                source_kind=(
                    CompletionSource.SOLO if position % 2 == 0 else CompletionSource.ROOM
                ),
                source_id=uuid4(),
                terminal_state="FINISHED",
                canonical_question_count=4,
                distinct_accepted_answer_count=4,
                latest_original_accepted_at_utc=ACCEPTED_AT,
                home_timezone_snapshot="Europe/London",
                home_zone_version=1,
                completed_at_utc=COMPLETED_AT,
                completion_state_version=1,
            )
            receipt = insert_completion_receipt(session, evidence)
            assert receipt.created
            # Explicit order avoids transaction-stable now() tying all rows.
            session.execute(
                update(CompletionReceiptModel)
                .where(CompletionReceiptModel.id == receipt.receipt_id)
                .values(created_at=ORDER_BASE + timedelta(seconds=position))
            )
            inserted.append((receipt.receipt_id, evidence))
    return inserted


def _count_user_rows(database: Database, model: type, user_id: UUID) -> int:
    with database.session_factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.user_id == user_id)
            )
            or 0
        )


def test_two_workers_claim_one_receipt_once(postgres_database: Database) -> None:
    user_id = _user(postgres_database)
    receipt_id, _ = _receipts(postgres_database, user_id, 1)[0]
    barrier = Barrier(2)

    def claim() -> tuple:
        repository = RewardRepository(postgres_database.session_factory)
        barrier.wait(timeout=10)
        return repository.claim_due(limit=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim)
        second = executor.submit(claim)
        claims = first.result(timeout=15) + second.result(timeout=15)

    assert len(claims) == 1
    assert claims[0].receipt_id == receipt_id
    assert claims[0].attempt_count == 1
    posted = RewardRepository(postgres_database.session_factory).post_claim(claims[0])
    assert posted is not None and posted.balance_after == 50
    assert _count_user_rows(postgres_database, CoinLedgerModel, user_id) == 2


def test_expired_claim_retry_preserves_order_cap_and_source_idempotence(
    postgres_database: Database,
) -> None:
    user_id = _user(postgres_database)
    receipts = _receipts(postgres_database, user_id, 5)
    repository = RewardRepository(postgres_database.session_factory)

    crashed_claim = repository.claim_due(limit=1)[0]
    assert crashed_claim.receipt_id == receipts[0][0]
    assert repository.claim_due(limit=1) == ()
    with postgres_database.session_factory.begin() as session:
        database_now = session.scalar(select(func.clock_timestamp()))
        assert database_now is not None
        session.execute(
            update(CompletionReceiptModel)
            .where(CompletionReceiptModel.id == crashed_claim.receipt_id)
            .values(lease_expires_at=database_now - timedelta(seconds=1))
        )

    retried_claim = repository.claim_due(limit=1)[0]
    assert retried_claim.receipt_id == crashed_claim.receipt_id
    assert retried_claim.lease_token != crashed_claim.lease_token
    assert retried_claim.attempt_count == 2
    assert repository.post_claim(crashed_claim) is None

    first_post = repository.post_claim(retried_claim)
    assert first_post is not None
    postings = [first_post]
    for expected_receipt_id, _ in receipts[1:]:
        claim = repository.claim_due(limit=1)[0]
        assert claim.receipt_id == expected_receipt_id
        posting = repository.post_claim(claim)
        assert posting is not None
        postings.append(posting)

    assert [post.study_date for post in postings] == [STUDY_DATE] * 5
    assert [post.posting_order for post in postings] == [1, 2, 3, 4, 5]
    assert [post.day_total for post in postings] == [50, 70, 90, 100, 100]
    assert [post.quiz_coins for post in postings] == [20, 20, 20, 10, 0]
    assert [post.daily_bonus for post in postings] == [30, 0, 0, 0, 0]
    assert repository.claim_due(limit=1) == ()
    assert repository.post_claim(retried_claim) is None

    with postgres_database.session_factory.begin() as session:
        replay = insert_completion_receipt(session, receipts[0][1])
    assert replay.receipt_id == receipts[0][0] and not replay.created

    with postgres_database.session_factory() as session:
        wallet = session.get(CoinWalletModel, user_id)
        day = session.get(QualifiedStudyDayModel, (user_id, STUDY_DATE))
        rows = session.scalars(
            select(CompletionReceiptModel)
            .where(CompletionReceiptModel.user_id == user_id)
            .order_by(CompletionReceiptModel.created_at)
        ).all()
        ledger = session.scalars(
            select(CoinLedgerModel).where(CoinLedgerModel.user_id == user_id)
        ).all()

    assert wallet is not None and wallet.balance == 100
    assert day is not None and (day.total_coins, day.qualifying_count) == (100, 5)
    assert [row.id for row in rows] == [receipt_id for receipt_id, _ in receipts]
    assert [row.posting_order for row in rows] == [1, 2, 3, 4, 5]
    assert all(row.status == ReceiptStatus.POSTED.value for row in rows)
    assert sorted(
        row.amount for row in ledger if row.kind == CoinLedgerKind.DAILY_BONUS.value
    ) == [30]
    assert sorted(
        row.amount for row in ledger if row.kind == CoinLedgerKind.QUIZ_REWARD.value
    ) == [10, 20, 20, 20]
    assert len(ledger) == 5


def test_pet_purchase_replay_and_composite_ownership_fk_flush(
    postgres_database: Database,
) -> None:
    user_id = _user(postgres_database)
    with postgres_database.session_factory.begin() as session:
        session.add(CoinWalletModel(user_id=user_id, balance=150, state_version=1))

    service = PetService(postgres_database.session_factory)
    starter = service.choose_starter(user_id, "pet.owl")
    assert starter.created
    request_id = uuid4()
    barrier = Barrier(2)

    def purchase():
        barrier.wait(timeout=10)
        return PetService(postgres_database.session_factory).purchase(
            user_id, request_id, "pet.fox"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(purchase)
        second = executor.submit(purchase)
        purchases = [first.result(timeout=15), second.result(timeout=15)]

    assert sorted(result.replayed for result in purchases) == [False, True]
    assert len({result.purchase_id for result in purchases}) == 1
    assert all(result.balance_after == 30 for result in purchases)
    with postgres_database.session_factory() as session:
        wallet = session.get(CoinWalletModel, user_id)
        ownership = session.get(PetOwnershipModel, (user_id, "pet.fox"))
        equipment = session.get(PetEquipmentModel, user_id)
        purchases_db = session.scalars(
            select(PetPurchaseModel).where(PetPurchaseModel.user_id == user_id)
        ).all()
        debits = session.scalars(
            select(CoinLedgerModel).where(
                CoinLedgerModel.user_id == user_id,
                CoinLedgerModel.kind == CoinLedgerKind.PET_PURCHASE.value,
            )
        ).all()

    assert wallet is not None and wallet.balance == 30
    assert equipment is not None and equipment.equipped_pet_id == "pet.owl"
    assert ownership is not None and ownership.purchase_id == purchases[0].purchase_id
    assert len(purchases_db) == len(debits) == 1
    assert debits[0].amount == -120
    assert debits[0].source_id == purchases_db[0].id

    # A purchase for one item cannot be used as ownership proof for another.
    with pytest.raises(IntegrityError) as mismatch:
        with postgres_database.session_factory.begin() as session:
            session.add(
                PetOwnershipModel(
                    user_id=user_id,
                    item_id="cosmetic.study_scarf",
                    acquisition_kind="purchase",
                    purchase_id=purchases_db[0].id,
                )
            )
            session.flush()
    assert getattr(mismatch.value.orig.diag, "constraint_name", None) == (
        "fk_pet_ownership_matching_purchase"
    )


def test_account_deletion_serializes_with_reward_posting(
    postgres_database: Database,
) -> None:
    user_id = _user(postgres_database)
    _receipts(postgres_database, user_id, 1)
    reward_repository = RewardRepository(postgres_database.session_factory)
    claim = reward_repository.claim_due(limit=1)[0]
    barrier = Barrier(2)

    def post():
        barrier.wait(timeout=10)
        return reward_repository.post_claim(claim)

    def delete():
        barrier.wait(timeout=10)
        return PostgresAccountDeletionRepository(
            postgres_database.session_factory
        ).delete_local_account(user_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        posting = executor.submit(post)
        deleting = executor.submit(delete)
        post_result = posting.result(timeout=15)
        deletion_result = deleting.result(timeout=15)

    assert deletion_result.already_deleted is False
    assert post_result is None or post_result.balance_after == 50
    assert reward_repository.post_claim(claim) is None
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, user_id)
    assert user is not None and user.deleted_at is not None
    for model in (
        CompletionReceiptModel,
        CoinWalletModel,
        QualifiedStudyDayModel,
        CoinLedgerModel,
        PetPurchaseModel,
        PetOwnershipModel,
        PetEquipmentModel,
    ):
        assert _count_user_rows(postgres_database, model, user_id) == 0
