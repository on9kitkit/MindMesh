from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.db.models.membership import RoomMembershipModel
from app.db.models.room import RoomModel
from app.db.models.safety_report import SafetyReportModel
from app.db.models.user import UserModel
from app.domain.errors import SafetyReportNotAllowedError
from app.domain.room import Room
from app.repositories.members import LifecycleMembershipRepository
from app.repositories.rooms import RoomRepository
from app.repositories.users import UserRepository
from app.schemas.safety_reports import (
    SafetyReportCreateRequest,
    SafetyReportResponse,
)


class SafetyReportOperations(Protocol):
    """Request-facing seam for the minimal safety-report contract."""

    def submit_report(
        self,
        *,
        reporter_id: UUID,
        payload: SafetyReportCreateRequest,
    ) -> SafetyReportResponse:
        """Create or safely deduplicate one report."""


SafetyReportStatus = Literal["OPEN", "RESOLVED", "DISMISSED"]
_FINAL_REPORT_STATUSES: tuple[SafetyReportStatus, SafetyReportStatus] = (
    "RESOLVED",
    "DISMISSED",
)


class SafetyReportOperatorError(RuntimeError):
    """A generic, non-user-facing operator workflow failure."""


@dataclass(frozen=True, slots=True)
class SafetyReportOperatorRecord:
    """Persisted report evidence exposed only to the local operator CLI."""

    id: UUID
    reporter_user_id: UUID | None
    reported_user_id: UUID | None
    room_id: UUID | None
    reported_display_name_snapshot: str
    reason: str
    details: str | None
    status: SafetyReportStatus
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class InMemorySafetyReport:
    id: UUID
    reporter_user_id: UUID
    reported_user_id: UUID
    room_id: UUID
    reported_display_name_snapshot: str
    reason: str
    details: str | None
    status: str
    created_at: datetime


class InMemorySafetyReportService:
    """Small local seam used by non-PostgreSQL API tests."""

    def __init__(
        self,
        *,
        room_repository: RoomRepository,
        membership_repository: LifecycleMembershipRepository,
        user_repository: UserRepository,
    ) -> None:
        self._room_repository = room_repository
        self._membership_repository = membership_repository
        self._user_repository = user_repository
        self.records: list[InMemorySafetyReport] = []

    def submit_report(
        self,
        *,
        reporter_id: UUID,
        payload: SafetyReportCreateRequest,
    ) -> SafetyReportResponse:
        reporter = self._user_repository.get_by_id(reporter_id)
        target = self._user_repository.get_by_id(payload.reported_user_id)
        room = self._room_repository.get_by_id(payload.room_id)
        if not _valid_report_context(
            reporter_id=reporter_id,
            reported_user_id=payload.reported_user_id,
            reporter_is_deleted=reporter is None or reporter.is_deleted,
            target_is_deleted=target is None or target.is_deleted,
            room=room,
            shared_context=(
                self._membership_repository.has_membership_history(
                    payload.room_id,
                    reporter_id,
                )
                and self._membership_repository.has_membership_history(
                    payload.room_id,
                    payload.reported_user_id,
                )
            ),
        ):
            raise SafetyReportNotAllowedError
        if target is None:
            raise SafetyReportNotAllowedError

        if _has_duplicate_report(
            self.records,
            reporter_id=reporter_id,
            reported_user_id=payload.reported_user_id,
            room_id=payload.room_id,
            reason=payload.reason,
        ):
            return _report_received()

        self.records.append(
            InMemorySafetyReport(
                id=uuid4(),
                reporter_user_id=reporter_id,
                reported_user_id=payload.reported_user_id,
                room_id=payload.room_id,
                reported_display_name_snapshot=target.display_name,
                reason=payload.reason,
                details=payload.details,
                status="OPEN",
                created_at=datetime.now(timezone.utc),
            )
        )
        return _report_received()


class PostgresSafetyReportService:
    """Transactional PostgreSQL implementation of safety reporting."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def submit_report(
        self,
        *,
        reporter_id: UUID,
        payload: SafetyReportCreateRequest,
    ) -> SafetyReportResponse:
        try:
            with self._session_factory() as session:
                with session.begin():
                    target = self._authorize_context(
                        session,
                        reporter_id=reporter_id,
                        payload=payload,
                    )
                    if self._duplicate_exists(
                        session,
                        reporter_id=reporter_id,
                        payload=payload,
                    ):
                        return _report_received()
                    session.add(
                        SafetyReportModel(
                            id=uuid4(),
                            reporter_user_id=reporter_id,
                            reported_user_id=payload.reported_user_id,
                            room_id=payload.room_id,
                            reported_display_name_snapshot=target.display_name,
                            reason=payload.reason,
                            details=payload.details,
                            status="OPEN",
                        )
                    )
                    session.flush()
                    return _report_received()
        except IntegrityError:
            if self._duplicate_exists_after_race(
                reporter_id=reporter_id,
                payload=payload,
            ):
                return _report_received()
            raise

    def list_open_reports(self) -> tuple[SafetyReportOperatorRecord, ...]:
        """Return open reports in deterministic oldest-first order."""

        with self._session_factory() as session:
            reports = session.scalars(
                select(SafetyReportModel)
                .where(SafetyReportModel.status == "OPEN")
                .order_by(
                    SafetyReportModel.created_at.asc(),
                    SafetyReportModel.id.asc(),
                )
            ).all()
            return tuple(_operator_record(report) for report in reports)

    def get_report(self, report_id: UUID) -> SafetyReportOperatorRecord:
        """Return one report, including tombstone-tolerant evidence."""

        with self._session_factory() as session:
            report = session.get(SafetyReportModel, report_id)
            if report is None:
                raise SafetyReportOperatorError("report_not_found")
            return _operator_record(report)

    def close_report(
        self,
        *,
        report_id: UUID,
        status: SafetyReportStatus,
    ) -> SafetyReportOperatorRecord:
        """Close one open report without overwriting a final decision."""

        if status not in _FINAL_REPORT_STATUSES:
            raise SafetyReportOperatorError("invalid_final_status")

        with self._session_factory() as session:
            with session.begin():
                report = session.scalar(
                    select(SafetyReportModel)
                    .where(SafetyReportModel.id == report_id)
                    .with_for_update()
                )
                if report is None:
                    raise SafetyReportOperatorError("report_not_found")
                if report.status == status:
                    return _operator_record(report)
                if report.status != "OPEN":
                    raise SafetyReportOperatorError("report_already_closed")

                report.status = status
                report.resolved_at = datetime.now(timezone.utc)
                session.flush()
                return _operator_record(report)

    def _authorize_context(
        self,
        session: Session,
        *,
        reporter_id: UUID,
        payload: SafetyReportCreateRequest,
    ) -> UserModel:
        reporter = session.scalar(
            select(UserModel).where(
                UserModel.id == reporter_id,
                UserModel.deleted_at.is_(None),
            )
        )
        target = session.scalar(
            select(UserModel).where(
                UserModel.id == payload.reported_user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        room_exists = session.scalar(
            select(RoomModel.id).where(RoomModel.id == payload.room_id)
        )
        if not _valid_report_context(
            reporter_id=reporter_id,
            reported_user_id=payload.reported_user_id,
            reporter_is_deleted=reporter is None,
            target_is_deleted=target is None,
            room=room_exists,
            shared_context=self._shared_room_context(
                session,
                reporter_id=reporter_id,
                reported_user_id=payload.reported_user_id,
                room_id=payload.room_id,
            ),
        ):
            raise SafetyReportNotAllowedError
        if target is None:
            raise SafetyReportNotAllowedError
        return target

    @staticmethod
    def _shared_room_context(
        session: Session,
        *,
        reporter_id: UUID,
        reported_user_id: UUID,
        room_id: UUID,
    ) -> bool:
        reporter_membership = aliased(RoomMembershipModel)
        reported_membership = aliased(RoomMembershipModel)
        membership_id = session.scalar(
            select(reporter_membership.id)
            .join(
                reported_membership,
                and_(
                    reported_membership.room_id == reporter_membership.room_id,
                    reported_membership.user_id == reported_user_id,
                ),
            )
            .where(
                reporter_membership.room_id == room_id,
                reporter_membership.user_id == reporter_id,
            )
            .limit(1)
        )
        return membership_id is not None

    @staticmethod
    def _duplicate_exists(
        session: Session,
        *,
        reporter_id: UUID,
        payload: SafetyReportCreateRequest,
    ) -> bool:
        return (
            session.scalar(
                select(SafetyReportModel.id)
                .where(
                    SafetyReportModel.reporter_user_id == reporter_id,
                    SafetyReportModel.reported_user_id == payload.reported_user_id,
                    SafetyReportModel.room_id == payload.room_id,
                    SafetyReportModel.reason == payload.reason,
                    SafetyReportModel.status == "OPEN",
                )
                .limit(1)
            )
            is not None
        )

    def _duplicate_exists_after_race(
        self,
        *,
        reporter_id: UUID,
        payload: SafetyReportCreateRequest,
    ) -> bool:
        with self._session_factory() as session:
            return self._duplicate_exists(
                session,
                reporter_id=reporter_id,
                payload=payload,
            )


def _valid_report_context(
    *,
    reporter_id: UUID,
    reported_user_id: UUID,
    reporter_is_deleted: bool,
    target_is_deleted: bool,
    room: Room | UUID | None,
    shared_context: bool,
) -> bool:
    return (
        reporter_id != reported_user_id
        and not reporter_is_deleted
        and not target_is_deleted
        and room is not None
        and shared_context
    )


def _has_duplicate_report(
    records: Sequence[InMemorySafetyReport],
    *,
    reporter_id: UUID,
    reported_user_id: UUID,
    room_id: UUID,
    reason: str,
) -> bool:
    return any(
        record.status == "OPEN"
        and record.reporter_user_id == reporter_id
        and record.reported_user_id == reported_user_id
        and record.room_id == room_id
        and record.reason == reason
        for record in records
    )


def _report_received() -> SafetyReportResponse:
    return SafetyReportResponse(status="report_received")


def _operator_record(report: SafetyReportModel) -> SafetyReportOperatorRecord:
    status = report.status
    if status not in {"OPEN", "RESOLVED", "DISMISSED"}:
        raise SafetyReportOperatorError("invalid_persisted_status")
    return SafetyReportOperatorRecord(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        reported_user_id=report.reported_user_id,
        room_id=report.room_id,
        reported_display_name_snapshot=report.reported_display_name_snapshot,
        reason=report.reason,
        details=report.details,
        status=cast(SafetyReportStatus, status),
        created_at=report.created_at,
        resolved_at=report.resolved_at,
    )
