"""PostgreSQL selectors and one-transaction retention execution."""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import ColumnElement, delete, exists, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select

from app.account_deletion.ports import OUTBOX_COMPLETED
from app.db.models.account_deletion_outbox import AccountDeletionOutboxModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.safety_report import SafetyReportModel
from app.learning_companions.models import SoloAttemptModel
from app.retention.policy import RetentionCutoffs, RetentionPolicy
from app.retention.summary import RetentionCounts, RetentionMode, RetentionRunSummary


ReportIdSelect = Select[tuple[UUID]]


def build_eligible_safety_report_ids(
    cutoffs: RetentionCutoffs,
    policy: RetentionPolicy,
) -> ReportIdSelect:
    """Build the bounded terminal-report selector used by preview and purge."""

    return (
        select(SafetyReportModel.id)
        .where(
            SafetyReportModel.status.in_(("RESOLVED", "DISMISSED")),
            SafetyReportModel.resolved_at.is_not(None),
            SafetyReportModel.resolved_at <= cutoffs.safety_report,
        )
        .order_by(SafetyReportModel.resolved_at, SafetyReportModel.id)
        .limit(policy.batch_limit)
    )


def _room_candidate_predicate(
    cutoffs: RetentionCutoffs,
    retained_report_exists: ColumnElement[bool],
) -> tuple[ColumnElement[bool], ...]:
    return (
        RoomModel.closed_at.is_not(None),
        RoomModel.closed_at <= cutoffs.closed_room,
        ~retained_report_exists,
    )


def _retained_report_exists_for_selection(
    selected_report_ids: ReportIdSelect,
) -> ColumnElement[bool]:
    return exists(
        select(1).where(
            SafetyReportModel.room_id == RoomModel.id,
            SafetyReportModel.id.not_in(selected_report_ids),
        )
    )


def _retained_report_exists_for_ids(
    selected_report_ids: Sequence[UUID],
) -> ColumnElement[bool]:
    conditions: list[ColumnElement[bool]] = [
        SafetyReportModel.room_id == RoomModel.id,
    ]
    if selected_report_ids:
        conditions.append(SafetyReportModel.id.not_in(tuple(selected_report_ids)))
    return exists(select(1).where(*conditions))


def _build_eligible_closed_room_ids(
    cutoffs: RetentionCutoffs,
    policy: RetentionPolicy,
    retained_report_exists: ColumnElement[bool],
) -> Select[tuple[UUID]]:
    return (
        select(RoomModel.id)
        .where(*_room_candidate_predicate(cutoffs, retained_report_exists))
        .order_by(RoomModel.closed_at, RoomModel.id)
        .limit(policy.batch_limit)
    )


def build_eligible_closed_room_ids(
    cutoffs: RetentionCutoffs,
    policy: RetentionPolicy,
    *,
    selected_report_ids: ReportIdSelect,
) -> Select[tuple[UUID]]:
    """Build the room selector for a report selection subquery."""

    return _build_eligible_closed_room_ids(
        cutoffs,
        policy,
        _retained_report_exists_for_selection(selected_report_ids),
    )


def build_eligible_closed_room_ids_for_ids(
    cutoffs: RetentionCutoffs,
    policy: RetentionPolicy,
    *,
    selected_report_ids: Sequence[UUID],
) -> Select[tuple[UUID]]:
    """Build the room selector for materialized destructive report IDs."""

    return _build_eligible_closed_room_ids(
        cutoffs,
        policy,
        _retained_report_exists_for_ids(selected_report_ids),
    )


def build_eligible_completed_outbox_ids(
    cutoffs: RetentionCutoffs,
    policy: RetentionPolicy,
) -> Select[tuple[UUID]]:
    """Build the bounded, completed-only provider-outbox selector."""

    return (
        select(AccountDeletionOutboxModel.id)
        .where(
            AccountDeletionOutboxModel.status == OUTBOX_COMPLETED,
            AccountDeletionOutboxModel.completed_at.is_not(None),
            AccountDeletionOutboxModel.completed_at <= cutoffs.completed_outbox,
            # These fields are cleared by the completion transition. Keeping
            # malformed terminal rows is safer than treating them as complete.
            AccountDeletionOutboxModel.claimed_at.is_(None),
            AccountDeletionOutboxModel.last_error_category.is_(None),
        )
        .order_by(AccountDeletionOutboxModel.completed_at, AccountDeletionOutboxModel.id)
        .limit(policy.batch_limit)
    )


def build_eligible_terminal_solo_ids(
    cutoffs: RetentionCutoffs,
    policy: RetentionPolicy,
) -> Select[tuple[UUID]]:
    """Select only terminal educational attempts aged from server terminal_at.

    Receipts, wallet, qualified days and pet ownership have no source FK and
    are intentionally outside this selector. Pending marking has no approved
    inactivity expiry.
    """
    return (
        select(SoloAttemptModel.id)
        .where(
            SoloAttemptModel.status.in_(("FINISHED", "ABANDONED", "FAILED")),
            SoloAttemptModel.terminal_at.is_not(None),
            SoloAttemptModel.terminal_at <= cutoffs.solo_terminal,
        )
        .order_by(SoloAttemptModel.terminal_at, SoloAttemptModel.id)
        .limit(policy.batch_limit)
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _database_clock(session: Session) -> datetime:
    value = session.scalar(select(func.current_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("database clock unavailable")
    return _as_utc(value)


def _count(session: Session, statement: Select[tuple[UUID]]) -> int:
    value = session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    if not isinstance(value, int):
        raise RuntimeError("retention count unavailable")
    return value


def _delete_count(result_rowcount: int | None) -> int:
    if result_rowcount is None:
        raise RuntimeError("retention delete count unavailable")
    return result_rowcount


class PostgresRetentionRepository:
    """Own the local PostgreSQL retention transaction and selectors."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def preview(
        self,
        policy: RetentionPolicy,
        *,
        as_of: datetime | None = None,
    ) -> RetentionRunSummary:
        """Count eligible rows without taking locks or writing rows."""

        with self._session_factory() as session:
            with session.begin():
                cutoffs = policy.cutoffs(
                    _database_clock(session) if as_of is None else as_of
                )
                selected_reports = build_eligible_safety_report_ids(cutoffs, policy)
                selected_rooms = build_eligible_closed_room_ids(
                    cutoffs,
                    policy,
                    selected_report_ids=selected_reports,
                )
                selected_outbox = build_eligible_completed_outbox_ids(cutoffs, policy)
                selected_solo = build_eligible_terminal_solo_ids(cutoffs, policy)
                eligible = RetentionCounts(
                    safety_reports=_count(session, selected_reports),
                    closed_rooms=_count(session, selected_rooms),
                    deletion_outbox_rows=_count(session, selected_outbox),
                    solo_attempts=_count(session, selected_solo),
                )
                return RetentionRunSummary(
                    mode=RetentionMode.DRY_RUN,
                    eligible=eligible,
                    deleted=RetentionCounts(),
                )

    def purge(
        self,
        policy: RetentionPolicy,
        *,
        as_of: datetime | None = None,
    ) -> RetentionRunSummary:
        """Delete one bounded, FK-safe batch atomically."""

        with self._session_factory() as session:
            with session.begin():
                cutoffs = policy.cutoffs(
                    _database_clock(session) if as_of is None else as_of
                )
                report_selector = build_eligible_safety_report_ids(cutoffs, policy)
                selected_report_ids = list(
                    session.scalars(
                        report_selector.with_for_update(skip_locked=True)
                    ).all()
                )

                room_selector = build_eligible_closed_room_ids_for_ids(
                    cutoffs,
                    policy,
                    selected_report_ids=selected_report_ids,
                )
                selected_room_ids = list(
                    session.scalars(
                        room_selector.with_for_update(skip_locked=True)
                    ).all()
                )
                safe_room_ids = self._recheck_room_report_context(
                    session,
                    selected_room_ids,
                    selected_report_ids,
                )

                outbox_selector = build_eligible_completed_outbox_ids(cutoffs, policy)
                selected_outbox_ids = list(
                    session.scalars(
                        outbox_selector.with_for_update(skip_locked=True)
                    ).all()
                )
                solo_selector = build_eligible_terminal_solo_ids(cutoffs, policy)
                selected_solo_ids = list(
                    session.scalars(
                        solo_selector.with_for_update(skip_locked=True)
                    ).all()
                )

                deleted_reports = _delete_count(
                    session.execute(
                        delete(SafetyReportModel).where(
                            SafetyReportModel.id.in_(selected_report_ids)
                        )
                    ).rowcount
                ) if selected_report_ids else 0
                if safe_room_ids:
                    session.execute(
                        delete(QuizSessionModel).where(
                            QuizSessionModel.room_id.in_(safe_room_ids)
                        )
                    )
                deleted_rooms = _delete_count(
                    session.execute(
                        delete(RoomModel).where(RoomModel.id.in_(safe_room_ids))
                    ).rowcount
                ) if safe_room_ids else 0
                deleted_outbox = _delete_count(
                    session.execute(
                        delete(AccountDeletionOutboxModel).where(
                            AccountDeletionOutboxModel.id.in_(selected_outbox_ids)
                        )
                    ).rowcount
                ) if selected_outbox_ids else 0
                deleted_solo = _delete_count(
                    session.execute(
                        delete(SoloAttemptModel).where(
                            SoloAttemptModel.id.in_(selected_solo_ids),
                            SoloAttemptModel.status.in_(("FINISHED", "ABANDONED", "FAILED")),
                            SoloAttemptModel.terminal_at.is_not(None),
                            SoloAttemptModel.terminal_at <= cutoffs.solo_terminal,
                        )
                    ).rowcount
                ) if selected_solo_ids else 0

                eligible = RetentionCounts(
                    safety_reports=len(selected_report_ids),
                    closed_rooms=len(selected_room_ids),
                    deletion_outbox_rows=len(selected_outbox_ids),
                    solo_attempts=len(selected_solo_ids),
                    protected_rooms=len(selected_room_ids) - len(safe_room_ids),
                )
                deleted = RetentionCounts(
                    safety_reports=deleted_reports,
                    closed_rooms=deleted_rooms,
                    deletion_outbox_rows=deleted_outbox,
                    solo_attempts=deleted_solo,
                )
                return RetentionRunSummary(
                    mode=RetentionMode.EXECUTE_PURGE,
                    eligible=eligible,
                    deleted=deleted,
                )

    @staticmethod
    def _recheck_room_report_context(
        session: Session,
        room_ids: Sequence[UUID],
        selected_report_ids: Sequence[UUID],
    ) -> tuple[UUID, ...]:
        """Recheck after room locks so newly retained reports protect context."""

        if not room_ids:
            return ()
        protected_conditions: list[ColumnElement[bool]] = [
            SafetyReportModel.room_id.in_(tuple(room_ids)),
        ]
        if selected_report_ids:
            protected_conditions.append(
                SafetyReportModel.id.not_in(tuple(selected_report_ids))
            )
        protected_room_ids = set(
            session.scalars(
                select(SafetyReportModel.room_id)
                .where(*protected_conditions)
                .distinct()
            ).all()
        )
        return tuple(room_id for room_id in room_ids if room_id not in protected_room_ids)
