from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.account_deletion.ports import (
    OUTBOX_COMPLETED,
    OUTBOX_IN_PROGRESS,
    OUTBOX_PENDING,
    REVENUECAT_PROVIDER,
    SUPABASE_AUTH_PROVIDER,
)
from app.db.models.account_deletion_outbox import AccountDeletionOutboxModel
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.user import UserModel
from app.domain.errors import (
    AccountDeletionBlockedActiveQuizError,
    UserProfileRequiredError,
)
from app.domain.quiz import QuizSessionStatus
from app.learning_companions.models import (
    CoinLedgerModel,
    CoinWalletModel,
    CompletionReceiptModel,
    LearningSettingsModel,
    PetEquipmentModel,
    PetOwnershipModel,
    PetPurchaseModel,
    QualifiedStudyDayModel,
    RoomRewardEnrollmentModel,
    SoloAttemptModel,
)


DELETED_USER_DISPLAY_NAME = "Deleted user"
DELETED_ROOM_NAME = "Deleted room"
_ACTIVE_SESSION_STATUSES = (
    QuizSessionStatus.QUESTION_OPEN.value,
    QuizSessionStatus.QUESTION_GRADING.value,
    QuizSessionStatus.QUESTION_REVEAL.value,
)


@dataclass(frozen=True, slots=True)
class AccountDeletionLocalResult:
    """Committed local deletion outcome without provider details."""

    user_id: UUID
    already_deleted: bool
    affected_room_ids: tuple[UUID, ...] = ()
    closed_room_ids: tuple[UUID, ...] = ()
    left_room_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimedDeletionJob:
    id: UUID
    user_id: UUID
    provider: str
    attempts: int


class PostgresAccountDeletionRepository:
    """Own the one-transaction local deletion and durable outbox boundary."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def delete_local_account(self, user_id: UUID) -> AccountDeletionLocalResult:
        with self._session_factory() as session:
            with session.begin():
                user = session.scalar(
                    select(UserModel)
                    .where(UserModel.id == user_id)
                    .with_for_update()
                )
                if user is None:
                    raise UserProfileRequiredError
                if user.deleted_at is not None:
                    return AccountDeletionLocalResult(
                        user_id=user_id,
                        already_deleted=True,
                    )

                room_ids = _relevant_room_ids(session, user_id)
                rooms = _lock_rooms(session, room_ids)
                _lock_and_check_active_sessions(session, rooms, user_id)
                now = _database_clock(session)

                owned_room_ids = {
                    room.id
                    for room in rooms.values()
                    if room.owner_id == user_id
                }
                active_membership_room_ids = set(
                    session.scalars(
                        select(RoomMembershipModel.room_id).where(
                            RoomMembershipModel.user_id == user_id,
                            RoomMembershipModel.left_at.is_(None),
                        )
                    ).all()
                )
                closed_room_ids = {
                    room.id
                    for room in rooms.values()
                    if room.owner_id == user_id and room.closed_at is None
                }
                left_room_ids = {
                    room.id
                    for room in rooms.values()
                    if room.owner_id != user_id
                    and room.closed_at is None
                    and room.id in active_membership_room_ids
                }

                if owned_room_ids:
                    session.execute(
                        update(RoomMembershipModel)
                        .where(
                            RoomMembershipModel.room_id.in_(owned_room_ids),
                            RoomMembershipModel.left_at.is_(None),
                        )
                        .values(left_at=now, ready_at=None)
                    )
                    session.execute(
                        update(RoomModel)
                        .where(RoomModel.id.in_(owned_room_ids))
                        .values(
                            name=DELETED_ROOM_NAME,
                            closed_at=func.coalesce(RoomModel.closed_at, now),
                        )
                    )

                # The user lock above serializes this removal with reward
                # posting. Receipts deliberately have no user/source FK, so
                # account deletion must erase them explicitly. Solo children
                # cascade from the owner attempt; answer-free reward history
                # is separate from its educational content until deletion.
                session.execute(
                    delete(PetEquipmentModel).where(PetEquipmentModel.user_id == user_id)
                )
                session.execute(
                    delete(PetOwnershipModel).where(PetOwnershipModel.user_id == user_id)
                )
                session.execute(
                    delete(PetPurchaseModel).where(PetPurchaseModel.user_id == user_id)
                )
                session.execute(
                    delete(CoinLedgerModel).where(CoinLedgerModel.user_id == user_id)
                )
                session.execute(
                    delete(QualifiedStudyDayModel).where(
                        QualifiedStudyDayModel.user_id == user_id
                    )
                )
                session.execute(
                    delete(CoinWalletModel).where(CoinWalletModel.user_id == user_id)
                )
                session.execute(
                    delete(CompletionReceiptModel).where(
                        CompletionReceiptModel.user_id == user_id
                    )
                )
                session.execute(
                    delete(RoomRewardEnrollmentModel).where(
                        RoomRewardEnrollmentModel.user_id == user_id
                    )
                )
                session.execute(
                    delete(SoloAttemptModel).where(SoloAttemptModel.owner_id == user_id)
                )
                session.execute(
                    delete(LearningSettingsModel).where(
                        LearningSettingsModel.user_id == user_id
                    )
                )

                participant_ids = select(SessionParticipantModel.id).where(
                    SessionParticipantModel.user_id == user_id
                )
                session.execute(
                    delete(AnswerSubmissionModel).where(
                        AnswerSubmissionModel.participant_id.in_(participant_ids)
                    )
                )
                session.execute(
                    delete(SessionParticipantModel).where(
                        SessionParticipantModel.user_id == user_id
                    )
                )
                session.execute(
                    delete(RoomMembershipModel).where(
                        RoomMembershipModel.user_id == user_id
                    )
                )

                user.display_name = DELETED_USER_DISPLAY_NAME
                user.deleted_at = now
                user.suspended_at = None
                user.suspension_reason_code = None
                user.updated_at = now
                session.add_all(
                    [
                        AccountDeletionOutboxModel(
                            id=uuid4(),
                            user_id=user_id,
                            provider=SUPABASE_AUTH_PROVIDER,
                            status=OUTBOX_PENDING,
                            attempts=0,
                            next_attempt_at=now,
                            created_at=now,
                            updated_at=now,
                        ),
                        AccountDeletionOutboxModel(
                            id=uuid4(),
                            user_id=user_id,
                            provider=REVENUECAT_PROVIDER,
                            status=OUTBOX_PENDING,
                            attempts=0,
                            next_attempt_at=now,
                            created_at=now,
                            updated_at=now,
                        ),
                    ]
                )
                session.flush()
                return AccountDeletionLocalResult(
                    user_id=user_id,
                    already_deleted=False,
                    affected_room_ids=tuple(sorted(room_ids)),
                    closed_room_ids=tuple(sorted(closed_room_ids)),
                    left_room_ids=tuple(sorted(left_room_ids)),
                )

    def recover_interrupted_jobs(self) -> None:
        """Make work claimed by a process that stopped eligible again."""

        with self._session_factory() as session:
            with session.begin():
                session.execute(
                    update(AccountDeletionOutboxModel)
                    .where(AccountDeletionOutboxModel.status == OUTBOX_IN_PROGRESS)
                    .values(
                        status=OUTBOX_PENDING,
                        claimed_at=None,
                    )
                )

    def claim_due_jobs(
        self,
        *,
        now: datetime | None = None,
        user_id: UUID | None = None,
        limit: int = 100,
        claim_lease_seconds: int = 600,
    ) -> tuple[ClaimedDeletionJob, ...]:
        if limit < 1:
            return ()
        claimed_at = _utc_now() if now is None else _as_utc(now)
        with self._session_factory() as session:
            with session.begin():
                stale_before = claimed_at - timedelta(seconds=claim_lease_seconds)
                session.execute(
                    update(AccountDeletionOutboxModel)
                    .where(
                        AccountDeletionOutboxModel.status == OUTBOX_IN_PROGRESS,
                        or_(
                            AccountDeletionOutboxModel.claimed_at.is_(None),
                            AccountDeletionOutboxModel.claimed_at <= stale_before,
                        ),
                    )
                    .values(status=OUTBOX_PENDING, claimed_at=None)
                )
                statement = (
                    select(AccountDeletionOutboxModel)
                    .where(
                        AccountDeletionOutboxModel.status == OUTBOX_PENDING,
                        AccountDeletionOutboxModel.next_attempt_at <= claimed_at,
                    )
                    .order_by(
                        AccountDeletionOutboxModel.next_attempt_at,
                        AccountDeletionOutboxModel.id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                if user_id is not None:
                    statement = statement.where(
                        AccountDeletionOutboxModel.user_id == user_id
                    )
                models = list(session.scalars(statement).all())
                jobs: list[ClaimedDeletionJob] = []
                for model in models:
                    model.status = OUTBOX_IN_PROGRESS
                    model.attempts += 1
                    model.claimed_at = claimed_at
                    model.updated_at = claimed_at
                    jobs.append(
                        ClaimedDeletionJob(
                            id=model.id,
                            user_id=model.user_id,
                            provider=model.provider,
                            attempts=model.attempts,
                        )
                    )
                session.flush()
                return tuple(jobs)

    def mark_completed(self, job_id: UUID, *, completed_at: datetime | None = None) -> None:
        timestamp = _utc_now() if completed_at is None else _as_utc(completed_at)
        with self._session_factory() as session:
            with session.begin():
                model = session.scalar(
                    select(AccountDeletionOutboxModel)
                    .where(AccountDeletionOutboxModel.id == job_id)
                    .with_for_update()
                )
                if model is None or model.status == OUTBOX_COMPLETED:
                    return
                model.status = OUTBOX_COMPLETED
                model.completed_at = timestamp
                model.claimed_at = None
                model.updated_at = timestamp
                model.last_error_category = None

    def mark_failed(
        self,
        job_id: UUID,
        *,
        error_category: str,
        next_attempt_at: datetime,
    ) -> None:
        timestamp = _as_utc(next_attempt_at)
        safe_category = _safe_error_category(error_category)
        with self._session_factory() as session:
            with session.begin():
                model = session.scalar(
                    select(AccountDeletionOutboxModel)
                    .where(AccountDeletionOutboxModel.id == job_id)
                    .with_for_update()
                )
                if model is None or model.status == OUTBOX_COMPLETED:
                    return
                model.status = OUTBOX_PENDING
                model.claimed_at = None
                model.next_attempt_at = timestamp
                model.updated_at = timestamp
                model.last_error_category = safe_category

    def has_pending_jobs(self, user_id: UUID) -> bool:
        with self._session_factory() as session:
            return session.scalar(
                select(AccountDeletionOutboxModel.id)
                .where(
                    AccountDeletionOutboxModel.user_id == user_id,
                    AccountDeletionOutboxModel.status != OUTBOX_COMPLETED,
                )
                .limit(1)
            ) is not None

    def has_any_pending_jobs(self) -> bool:
        with self._session_factory() as session:
            return session.scalar(
                select(AccountDeletionOutboxModel.id)
                .where(AccountDeletionOutboxModel.status != OUTBOX_COMPLETED)
                .limit(1)
            ) is not None

    def list_jobs(self, user_id: UUID) -> tuple[AccountDeletionOutboxModel, ...]:
        """Read operational job state for tests/operator tooling only."""

        with self._session_factory() as session:
            return tuple(
                session.scalars(
                    select(AccountDeletionOutboxModel)
                    .where(AccountDeletionOutboxModel.user_id == user_id)
                    .order_by(AccountDeletionOutboxModel.provider)
                ).all()
            )


def _relevant_room_ids(session: Session, user_id: UUID) -> set[UUID]:
    room_ids = set(
        session.scalars(
            select(RoomModel.id).where(RoomModel.owner_id == user_id)
        ).all()
    )
    room_ids.update(
        session.scalars(
            select(RoomMembershipModel.room_id).where(
                RoomMembershipModel.user_id == user_id
            )
        ).all()
    )
    room_ids.update(
        session.scalars(
            select(QuizSessionModel.room_id)
            .join(
                SessionParticipantModel,
                SessionParticipantModel.session_id == QuizSessionModel.id,
            )
            .where(SessionParticipantModel.user_id == user_id)
        ).all()
    )
    return room_ids


def _lock_rooms(session: Session, room_ids: set[UUID]) -> dict[UUID, RoomModel]:
    rooms: dict[UUID, RoomModel] = {}
    for room_id in sorted(room_ids):
        room = session.scalar(
            select(RoomModel)
            .where(RoomModel.id == room_id)
            .with_for_update()
        )
        if room is not None:
            rooms[room_id] = room
    return rooms


def _lock_and_check_active_sessions(
    session: Session,
    rooms: dict[UUID, RoomModel],
    user_id: UUID,
) -> None:
    for room_id in sorted(rooms):
        active_sessions = list(
            session.scalars(
                select(QuizSessionModel)
                .where(
                    QuizSessionModel.room_id == room_id,
                    QuizSessionModel.status.in_(_ACTIVE_SESSION_STATUSES),
                )
                .order_by(QuizSessionModel.started_at, QuizSessionModel.id)
                .with_for_update()
            ).all()
        )
        for active_session in active_sessions:
            is_participant = session.scalar(
                select(SessionParticipantModel.id).where(
                    SessionParticipantModel.session_id == active_session.id,
                    SessionParticipantModel.user_id == user_id,
                )
            )
            if is_participant is not None:
                raise AccountDeletionBlockedActiveQuizError


def _database_clock(session: Session) -> datetime:
    value = session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("database clock unavailable")
    return _as_utc(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_error_category(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in value.lower()
    ).strip("_")
    return (normalized or "provider_error")[:64]
