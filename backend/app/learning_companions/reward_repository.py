"""Transactional, PostgreSQL-backed earned-coin receipt handoff and posting.

Source transactions call ``insert_completion_receipt`` while holding their own
attempt/session lock. It never reads or locks a user. The worker claims a
receipt in a short transaction, releases that lock, then posts under the user
lock so account deletion and wallet writes use the same lock order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.db.models.user import UserModel
from app.learning_companions.contracts import (
    CoinLedgerKind,
    CompletionEvidence,
    HOME_ZONE_VERSION,
    REWARD_RULE_VERSION,
    ReceiptStatus,
    calculate_reward_amounts,
    study_date_for,
)
from app.learning_companions.models import (
    CoinLedgerModel,
    CoinWalletModel,
    CompletionReceiptModel,
    QualifiedStudyDayModel,
)


LEASE_SECONDS = 60
MAX_CLAIM_ATTEMPTS = 5
MAX_CLAIM_BATCH = 50


class ReceiptConflictError(ValueError):
    """A source key was reused with different immutable completion proof."""


class InvalidReceiptError(ValueError):
    """A persisted receipt cannot be credited under the frozen rule."""


@dataclass(frozen=True, slots=True)
class ReceiptInsertion:
    receipt_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class ReceiptClaim:
    receipt_id: UUID
    user_id: UUID
    lease_token: UUID
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ReceiptPosting:
    receipt_id: UUID
    study_date: date
    posting_order: int
    daily_bonus: int
    quiz_coins: int
    day_total: int
    balance_after: int


def _utc(instant: datetime) -> datetime:
    return instant.astimezone(timezone.utc)


def _database_now(session: Session) -> datetime:
    """Use the database clock rather than a worker host or client clock."""
    now = session.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise RuntimeError("A timezone-aware database clock is required.")
    return now


def insert_completion_receipt(session: Session, evidence: CompletionEvidence) -> ReceiptInsertion:
    """Stage an answer-free receipt in the caller's terminal source transaction.

    The caller must have proved FINISHED and every-question accepted coverage
    from locked, immutable source rows. This function does not commit and must
    not be called in an after-commit reconstruction path. A duplicate source
    key with identical proof is a no-op; conflicting proof is rejected.
    """
    accepted_at = _utc(evidence.latest_original_accepted_at_utc)
    completed_at = _utc(evidence.completed_at_utc)
    values = {
        "id": uuid4(),
        "user_id": evidence.user_id,
        "source_kind": evidence.source_kind.value,
        "source_id": evidence.source_id,
        "terminal_state": evidence.terminal_state,
        "canonical_question_count": evidence.canonical_question_count,
        "accepted_answer_count": evidence.distinct_accepted_answer_count,
        "latest_accepted_at": accepted_at,
        "home_timezone_snapshot": evidence.home_timezone_snapshot,
        "home_zone_version": evidence.home_zone_version,
        "study_date": evidence.study_date,
        "completed_at": completed_at,
        "completion_state_version": evidence.completion_state_version,
        "reward_rule_version": evidence.reward_rule_version,
        "status": ReceiptStatus.PENDING.value,
        "attempt_count": 0,
    }
    inserted_id = session.scalar(
        pg_insert(CompletionReceiptModel)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_learning_receipts_source")
        .returning(CompletionReceiptModel.id)
    )
    if inserted_id is not None:
        return ReceiptInsertion(receipt_id=inserted_id, created=True)

    existing = session.scalar(
        select(CompletionReceiptModel).where(
            CompletionReceiptModel.user_id == evidence.user_id,
            CompletionReceiptModel.source_kind == evidence.source_kind.value,
            CompletionReceiptModel.source_id == evidence.source_id,
        )
    )
    if existing is None or any(
        (
            getattr(existing, key).astimezone(timezone.utc)
            if key in {"latest_accepted_at", "completed_at"}
            else getattr(existing, key)
        )
        != expected
        for key, expected in values.items()
        if key not in {"id", "status", "attempt_count"}
    ):
        raise ReceiptConflictError("Completion source has conflicting reward evidence.")
    return ReceiptInsertion(receipt_id=existing.id, created=False)


def claimable_receipts_statement(now: datetime, limit: int):
    """One oldest unfinished receipt; an earlier block prevents leapfrog.

    The worker may process 50 receipts per scan, but must claim each directly
    before posting it so queued work cannot consume its 60-second lease.
    """
    if limit != 1:
        raise ValueError("Claim exactly one receipt immediately before posting.")
    earlier = aliased(CompletionReceiptModel)
    due = or_(
        CompletionReceiptModel.status == ReceiptStatus.PENDING.value,
        and_(
            CompletionReceiptModel.status == ReceiptStatus.RETRY_WAIT.value,
            CompletionReceiptModel.next_attempt_at <= now,
        ),
        and_(
            CompletionReceiptModel.status == ReceiptStatus.LEASED.value,
            CompletionReceiptModel.lease_expires_at <= now,
        ),
    )
    precedes = or_(
        earlier.created_at < CompletionReceiptModel.created_at,
        and_(
            earlier.created_at == CompletionReceiptModel.created_at,
            earlier.id < CompletionReceiptModel.id,
        ),
    )
    unfinished_before = exists(
        select(1).where(
            earlier.user_id == CompletionReceiptModel.user_id,
            earlier.study_date == CompletionReceiptModel.study_date,
            earlier.status != ReceiptStatus.POSTED.value,
            precedes,
        )
    )
    return (
        select(CompletionReceiptModel)
        .where(due, ~unfinished_before)
        .order_by(CompletionReceiptModel.created_at, CompletionReceiptModel.id)
        .limit(limit)
        .with_for_update(of=CompletionReceiptModel, skip_locked=True)
    )


def _has_unposted_predecessor(session: Session, receipt: CompletionReceiptModel) -> bool:
    earlier = aliased(CompletionReceiptModel)
    return bool(
        session.scalar(
            select(
                exists(
                    select(1).where(
                        earlier.user_id == receipt.user_id,
                        earlier.study_date == receipt.study_date,
                        earlier.status != ReceiptStatus.POSTED.value,
                        or_(
                            earlier.created_at < receipt.created_at,
                            and_(earlier.created_at == receipt.created_at, earlier.id < receipt.id),
                        ),
                    )
                )
            )
        )
    )


def _clear_lease(receipt: CompletionReceiptModel) -> None:
    receipt.lease_token = None
    receipt.lease_expires_at = None


class RewardRepository:
    """All methods own their transaction except source receipt insertion above."""

    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def claim_due(self, *, limit: int = 1) -> tuple[ReceiptClaim, ...]:
        if limit != 1:
            raise ValueError("Claim exactly one receipt immediately before posting.")
        claims: list[ReceiptClaim] = []
        with self._session_factory.begin() as session:
            now = _database_now(session)
            rows = session.scalars(claimable_receipts_statement(now, limit)).all()
            for receipt in rows:
                if receipt.attempt_count >= MAX_CLAIM_ATTEMPTS:
                    receipt.status = ReceiptStatus.BLOCKED.value
                    receipt.last_error_category = "attempts_exhausted"
                    receipt.next_attempt_at = None
                    _clear_lease(receipt)
                    continue
                token = uuid4()
                receipt.status = ReceiptStatus.LEASED.value
                receipt.attempt_count += 1
                receipt.lease_token = token
                receipt.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
                receipt.next_attempt_at = None
                receipt.last_error_category = None
                claims.append(
                    ReceiptClaim(receipt.id, receipt.user_id, token, receipt.attempt_count)
                )
        return tuple(claims)

    def post_claim(self, claim: ReceiptClaim) -> ReceiptPosting | None:
        """Atomically post ledger, wallet, day and receipt after locking user first."""
        with self._session_factory.begin() as session:
            user = session.scalar(
                select(UserModel).where(UserModel.id == claim.user_id).with_for_update()
            )
            receipt = session.scalar(
                select(CompletionReceiptModel)
                .where(CompletionReceiptModel.id == claim.receipt_id)
                .with_for_update()
            )
            if receipt is None:
                return None
            if user is None or user.deleted_at is not None:
                # The source-independent receipt has no FK, so a stale worker
                # must discard it rather than recreate deleted account state.
                session.delete(receipt)
                return None
            now = _database_now(session)
            if (
                receipt.user_id != claim.user_id
                or receipt.status != ReceiptStatus.LEASED.value
                or receipt.lease_token != claim.lease_token
                or receipt.lease_expires_at is None
                or receipt.lease_expires_at <= now
            ):
                return None
            if _has_unposted_predecessor(session, receipt):
                # A source transaction with an earlier timestamp may commit
                # after claim. Requeue without burning an attempt.
                receipt.status = ReceiptStatus.PENDING.value
                receipt.attempt_count -= 1
                _clear_lease(receipt)
                return None
            if (
                receipt.reward_rule_version != REWARD_RULE_VERSION
                or receipt.home_zone_version != HOME_ZONE_VERSION
                or receipt.terminal_state != "FINISHED"
                or receipt.canonical_question_count < 1
                or receipt.accepted_answer_count != receipt.canonical_question_count
                or receipt.study_date
                != study_date_for(receipt.latest_accepted_at, receipt.home_timezone_snapshot)
                or receipt.latest_accepted_at > receipt.completed_at
            ):
                raise InvalidReceiptError("Persisted completion proof is invalid.")

            wallet = session.scalar(
                select(CoinWalletModel)
                .where(CoinWalletModel.user_id == claim.user_id)
                .with_for_update()
            )
            wallet_missing = wallet is None
            if wallet is None:
                wallet = CoinWalletModel(
                    user_id=claim.user_id, balance=0, state_version=1, updated_at=now
                )
                session.add(wallet)
            day = session.scalar(
                select(QualifiedStudyDayModel)
                .where(
                    QualifiedStudyDayModel.user_id == claim.user_id,
                    QualifiedStudyDayModel.study_date == receipt.study_date,
                )
                .with_for_update()
            )
            first = day is None
            if wallet_missing and day is not None:
                raise InvalidReceiptError("Qualified day exists without its wallet.")
            if day is not None and not day.bonus_awarded:
                raise InvalidReceiptError("Existing qualified day has no bonus proof.")
            prior_total = day.total_coins if day is not None else 0
            amounts = calculate_reward_amounts(
                prior_study_day_coins=prior_total, first_qualification=first
            )
            order = 1 if day is None else day.qualifying_count + 1
            if day is None:
                day = QualifiedStudyDayModel(
                    user_id=claim.user_id,
                    study_date=receipt.study_date,
                    total_coins=amounts.total,
                    bonus_awarded=True,
                    qualifying_count=1,
                    first_qualified_at=now,
                    updated_at=now,
                )
                session.add(day)
            else:
                day.total_coins += amounts.total
                day.qualifying_count += 1
                day.updated_at = now

            for kind, amount in (
                (CoinLedgerKind.DAILY_BONUS, amounts.daily_bonus),
                (CoinLedgerKind.QUIZ_REWARD, amounts.quiz_coins),
            ):
                if amount == 0:
                    continue  # The ledger's grant rows require positive amounts.
                wallet.balance += amount
                session.add(
                    CoinLedgerModel(
                        id=uuid4(),
                        user_id=claim.user_id,
                        kind=kind.value,
                        source_id=receipt.id,
                        amount=amount,
                        balance_after=wallet.balance,
                        study_date=receipt.study_date,
                        created_at=now,
                    )
                )
            wallet.state_version += 1
            wallet.updated_at = now
            receipt.status = ReceiptStatus.POSTED.value
            receipt.posting_order = order
            receipt.posted_at = now
            receipt.next_attempt_at = None
            receipt.last_error_category = None
            _clear_lease(receipt)
            return ReceiptPosting(
                receipt.id,
                receipt.study_date,
                order,
                amounts.daily_bonus,
                amounts.quiz_coins,
                day.total_coins,
                wallet.balance,
            )

    def fail_claim(self, claim: ReceiptClaim, *, category: str = "posting_failed") -> bool:
        """Schedule bounded retry only if this token still owns an unposted row."""
        if category not in {"posting_failed", "invalid_receipt"}:
            raise ValueError("Unsupported receipt failure category.")
        with self._session_factory.begin() as session:
            receipt = session.scalar(
                select(CompletionReceiptModel)
                .where(CompletionReceiptModel.id == claim.receipt_id)
                .with_for_update()
            )
            if (
                receipt is None
                or receipt.status != ReceiptStatus.LEASED.value
                or receipt.lease_token != claim.lease_token
            ):
                return False
            now = _database_now(session)
            _clear_lease(receipt)
            receipt.last_error_category = category
            if receipt.attempt_count >= MAX_CLAIM_ATTEMPTS:
                receipt.status = ReceiptStatus.BLOCKED.value
                receipt.next_attempt_at = None
            else:
                receipt.status = ReceiptStatus.RETRY_WAIT.value
                receipt.next_attempt_at = now + timedelta(
                    seconds=min(60, 2 ** receipt.attempt_count)
                )
            return True
