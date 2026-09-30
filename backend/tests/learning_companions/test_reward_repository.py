"""Offline transaction-boundary checks; PostgreSQL races need the DB gate."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.learning_companions.contracts import CompletionEvidence, CompletionSource, ReceiptStatus
from app.learning_companions.models import (
    CoinLedgerModel,
    CoinWalletModel,
    CompletionReceiptModel,
    QualifiedStudyDayModel,
)
from app.learning_companions.reward_repository import (
    MAX_CLAIM_ATTEMPTS,
    ReceiptClaim,
    ReceiptConflictError,
    RewardRepository,
    claimable_receipts_statement,
    insert_completion_receipt,
)
from app.learning_companions.reward_worker import RewardWorker


NOW = datetime(2026, 3, 31, 12, tzinfo=timezone.utc)
USER_ID = uuid4()


class FakeSession:
    def __init__(self, *, scalars: tuple[object, ...] = (), rows: tuple[object, ...] = ()):
        self.results = list(scalars)
        self.rows = rows
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.statements: list[object] = []

    def scalar(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: list(self.rows))

    def add(self, item):
        self.added.append(item)

    def delete(self, item):
        self.deleted.append(item)


class FakeSessionFactory:
    def __init__(self, *sessions: FakeSession):
        self.sessions = list(sessions)

    @contextmanager
    def begin(self):
        yield self.sessions.pop(0)


def _receipt(*, study_date: date = date(2026, 3, 28)) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=USER_ID,
        status=ReceiptStatus.LEASED.value,
        lease_token=uuid4(),
        lease_expires_at=NOW + timedelta(seconds=60),
        attempt_count=1,
        reward_rule_version=1,
        home_zone_version=1,
        terminal_state="FINISHED",
        canonical_question_count=4,
        accepted_answer_count=4,
        latest_accepted_at=datetime(2026, 3, 28, 23, 30, tzinfo=timezone.utc),
        completed_at=datetime(2026, 3, 31, 11, tzinfo=timezone.utc),
        home_timezone_snapshot="Europe/London",
        study_date=study_date,
        created_at=NOW,
        posting_order=None,
        posted_at=None,
        next_attempt_at=None,
        last_error_category=None,
    )


def _claim(receipt: SimpleNamespace) -> ReceiptClaim:
    return ReceiptClaim(receipt.id, receipt.user_id, receipt.lease_token, receipt.attempt_count)


def test_claim_sql_uses_skip_locked_and_unposted_predecessor() -> None:
    sql = str(
        claimable_receipts_statement(NOW, 1).compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE OF learning_completion_receipts SKIP LOCKED" in sql
    assert "EXISTS (SELECT" in sql
    assert "learning_completion_receipts_1.status !=" in sql
    with pytest.raises(ValueError):
        claimable_receipts_statement(NOW, 2)


def test_receipt_schema_is_source_independent_for_content_purge() -> None:
    table = CompletionReceiptModel.__table__
    assert not table.foreign_keys
    assert "answer_text" not in table.columns
    assert "question_text" not in table.columns


def test_claim_reclaims_expired_and_blocks_exhausted(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.learning_companions.reward_repository._database_now", lambda _session: NOW
    )
    expired = _receipt()
    previous_token = expired.lease_token
    expired.lease_expires_at = NOW - timedelta(seconds=1)
    exhausted = _receipt()
    exhausted.attempt_count = MAX_CLAIM_ATTEMPTS
    exhausted.lease_expires_at = NOW - timedelta(seconds=1)
    repository = RewardRepository(
        FakeSessionFactory(FakeSession(rows=(expired,)), FakeSession(rows=(exhausted,)))
    )
    claims = repository.claim_due(limit=1)
    assert len(claims) == 1
    assert claims[0].receipt_id == expired.id
    assert expired.attempt_count == 2
    assert expired.lease_token != previous_token
    assert expired.lease_token == claims[0].lease_token
    assert expired.lease_expires_at == NOW + timedelta(seconds=60)
    assert repository.claim_due(limit=1) == ()
    assert exhausted.status == ReceiptStatus.BLOCKED.value
    assert exhausted.lease_token is None
    with pytest.raises(ValueError):
        repository.claim_due(limit=2)


def test_receipt_insert_is_source_transaction_only_and_detects_conflict() -> None:
    evidence = CompletionEvidence(
        user_id=USER_ID,
        source_kind=CompletionSource.SOLO,
        source_id=uuid4(),
        terminal_state="FINISHED",
        canonical_question_count=4,
        distinct_accepted_answer_count=4,
        latest_original_accepted_at_utc=datetime(
            2026, 3, 28, 23, 30, tzinfo=timezone.utc
        ),
        home_timezone_snapshot="Europe/London",
        home_zone_version=1,
        completed_at_utc=NOW,
        completion_state_version=3,
    )
    inserted_id = uuid4()
    source_session = FakeSession(scalars=(inserted_id,))
    inserted = insert_completion_receipt(source_session, evidence)
    assert inserted.created and inserted.receipt_id == inserted_id
    insert_sql = str(source_session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_learning_receipts_source DO NOTHING" in insert_sql
    existing = SimpleNamespace(
        id=inserted_id,
        user_id=USER_ID,
        source_kind="solo",
        source_id=evidence.source_id,
        terminal_state="FINISHED",
        canonical_question_count=4,
        accepted_answer_count=4,
        latest_accepted_at=evidence.latest_original_accepted_at_utc,
        home_timezone_snapshot="Europe/London",
        home_zone_version=1,
        study_date=evidence.study_date,
        completed_at=NOW,
        completion_state_version=3,
        reward_rule_version=1,
    )
    replay = insert_completion_receipt(FakeSession(scalars=(None, existing)), evidence)
    assert not replay.created and replay.receipt_id == inserted_id
    existing.accepted_answer_count = 3
    with pytest.raises(ReceiptConflictError):
        insert_completion_receipt(FakeSession(scalars=(None, existing)), evidence)


def test_late_marking_posts_to_original_answer_day_and_caps_at_100(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.learning_companions.reward_repository._database_now", lambda _session: NOW
    )
    monkeypatch.setattr(
        "app.learning_companions.reward_repository._has_unposted_predecessor",
        lambda _session, _receipt: False,
    )
    user = SimpleNamespace(id=USER_ID, deleted_at=None)
    wallet = None
    day = None
    totals: list[int] = []
    quiz_grants: list[int] = []
    for expected_order in range(1, 6):
        receipt = _receipt()
        session = FakeSession(scalars=(user, receipt, wallet, day))
        result = RewardRepository(FakeSessionFactory(session)).post_claim(_claim(receipt))
        assert result is not None
        assert result.study_date == date(2026, 3, 28)
        assert result.posting_order == expected_order
        assert receipt.status == ReceiptStatus.POSTED.value
        assert receipt.lease_token is None
        wallet = next(
            (row for row in session.added if isinstance(row, CoinWalletModel)), wallet
        )
        day = next((row for row in session.added if isinstance(row, QualifiedStudyDayModel)), day)
        assert wallet is not None and day is not None
        totals.append(day.total_coins)
        quiz_grants.append(result.quiz_coins)
        ledger = [row for row in session.added if isinstance(row, CoinLedgerModel)]
        assert len(ledger) == (2 if expected_order == 1 else 0 if expected_order == 5 else 1)
    assert totals == [50, 70, 90, 100, 100]
    assert quiz_grants == [20, 20, 20, 10, 0]
    assert wallet.balance == 100


@pytest.mark.parametrize("missing_user", [True, False])
def test_tombstone_or_missing_user_discards_receipt_without_wallet(
    missing_user: bool,
) -> None:
    receipt = _receipt()
    user = None if missing_user else SimpleNamespace(id=USER_ID, deleted_at=NOW)
    session = FakeSession(scalars=(user, receipt))
    result = RewardRepository(FakeSessionFactory(session)).post_claim(_claim(receipt))
    assert result is None
    assert session.deleted == [receipt]
    assert session.added == []


def test_stale_or_already_posted_lease_cannot_mutate_wallet(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.learning_companions.reward_repository._database_now", lambda _session: NOW
    )
    receipt = _receipt()
    receipt.status = ReceiptStatus.POSTED.value
    session = FakeSession(scalars=(SimpleNamespace(id=USER_ID, deleted_at=None), receipt))
    result = RewardRepository(FakeSessionFactory(session)).post_claim(_claim(receipt))
    assert result is None
    assert session.added == []


def test_failed_claim_retries_with_delay_then_blocks_at_five(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.learning_companions.reward_repository._database_now", lambda _session: NOW
    )
    first = _receipt()
    session = FakeSession(scalars=(first,))
    assert RewardRepository(FakeSessionFactory(session)).fail_claim(
        _claim(first), category="posting_failed"
    )
    assert first.status == ReceiptStatus.RETRY_WAIT.value
    assert first.next_attempt_at == NOW + timedelta(seconds=2)
    assert first.lease_token is None

    final = _receipt()
    final.attempt_count = MAX_CLAIM_ATTEMPTS
    session = FakeSession(scalars=(final,))
    assert RewardRepository(FakeSessionFactory(session)).fail_claim(
        _claim(final), category="posting_failed"
    )
    assert final.status == ReceiptStatus.BLOCKED.value
    assert final.next_attempt_at is None

    stale = _receipt()
    wrong = ReceiptClaim(stale.id, USER_ID, uuid4(), stale.attempt_count)
    session = FakeSession(scalars=(stale,))
    assert not RewardRepository(FakeSessionFactory(session)).fail_claim(
        wrong, category="posting_failed"
    )
    assert stale.status == ReceiptStatus.LEASED.value


class FakeWorkerStore:
    def __init__(self, *, crash_after_commit: bool = False):
        self.receipts = [uuid4() for _ in range(5)]
        self.index = 0
        self.in_flight: ReceiptClaim | None = None
        self.amounts: list[int] = []
        self.crash_after_commit = crash_after_commit
        self.failures = 0

    def claim_due(self, *, limit: int) -> tuple[ReceiptClaim, ...]:
        if limit < 1 or self.index >= len(self.receipts):
            return ()
        claim = ReceiptClaim(self.receipts[self.index], USER_ID, uuid4(), 1)
        self.in_flight = claim
        return (claim,)

    def post_claim(self, claim: ReceiptClaim):
        assert claim == self.in_flight
        self.amounts.append((50, 20, 20, 10, 0)[self.index])
        self.index += 1
        self.in_flight = None
        if self.crash_after_commit and self.index == 1:
            raise RuntimeError("simulated acknowledgement loss after commit")
        return None

    def fail_claim(self, claim: ReceiptClaim, *, category: str) -> bool:
        self.failures += 1
        # Posting already committed, so the old token cannot schedule a retry.
        return self.in_flight == claim


def test_worker_reopens_ordered_day_and_ack_loss_cannot_double_credit() -> None:
    store = FakeWorkerStore(crash_after_commit=True)
    assert asyncio.run(RewardWorker(store).run_once()) == 5
    assert store.amounts == [50, 20, 20, 10, 0]
    assert sum(store.amounts) == 100
    assert store.failures == 1
    assert asyncio.run(RewardWorker(store).run_once()) == 0


def test_worker_failure_before_commit_can_retry_without_credit() -> None:
    class PreCommitFailureStore:
        def __init__(self):
            self.receipt_id = uuid4()
            self.attempts = 0
            self.credits = 0
            self.waiting = False
            self.posted = False

        def claim_due(self, *, limit: int) -> tuple[ReceiptClaim, ...]:
            if self.waiting or self.posted:
                return ()
            self.attempts += 1
            return (ReceiptClaim(self.receipt_id, USER_ID, uuid4(), self.attempts),)

        def post_claim(self, claim: ReceiptClaim):
            if claim.attempt_count == 1:
                raise RuntimeError("simulated transaction rollback")
            self.credits += 50
            self.posted = True
            return None

        def fail_claim(self, claim: ReceiptClaim, *, category: str) -> bool:
            self.waiting = True
            return True

    store = PreCommitFailureStore()
    assert asyncio.run(RewardWorker(store).run_once()) == 1
    assert store.credits == 0 and store.waiting
    store.waiting = False  # Represents the persisted retry delay becoming due.
    assert asyncio.run(RewardWorker(store).run_once()) == 1
    assert store.credits == 50 and store.posted


def test_slow_fifty_receipts_are_claimed_just_before_posting() -> None:
    class SlowReceiptStore:
        def __init__(self):
            self.now_seconds = 0
            self.rows = [
                SimpleNamespace(
                    id=uuid4(), status="pending", attempts=0, token=None, lease_until=None
                )
                for _ in range(50)
            ]
            self.claim_limits: list[int] = []

        def claim_due(self, *, limit: int) -> tuple[ReceiptClaim, ...]:
            self.claim_limits.append(limit)
            due = [
                row for row in self.rows
                if row.status == "pending"
                or (row.status == "leased" and row.lease_until <= self.now_seconds)
            ][:limit]
            claims = []
            for row in due:
                row.attempts += 1
                if row.attempts > MAX_CLAIM_ATTEMPTS:
                    row.status = "blocked"
                    continue
                row.status = "leased"
                row.token = uuid4()
                row.lease_until = self.now_seconds + 60
                claims.append(ReceiptClaim(row.id, USER_ID, row.token, row.attempts))
            return tuple(claims)

        def post_claim(self, claim: ReceiptClaim):
            self.now_seconds += 2  # No wall-clock delay, but 100s across the scan.
            row = next(item for item in self.rows if item.id == claim.receipt_id)
            if row.token != claim.lease_token or self.now_seconds >= row.lease_until:
                return None
            row.status = "posted"
            return None

        def fail_claim(self, claim: ReceiptClaim, *, category: str) -> bool:
            raise AssertionError("No valid receipt should fail because it waited in a queue.")

    store = SlowReceiptStore()
    assert asyncio.run(RewardWorker(store).run_once()) == 50
    assert store.now_seconds == 100
    assert all(row.status == "posted" and row.attempts == 1 for row in store.rows)
    assert store.claim_limits == [1] * 50
