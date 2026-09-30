from datetime import datetime, timezone
import sys
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.db.models.room import RoomModel
from app.db.models.safety_report import SafetyReportModel
from app.db.models.user import UserModel
from app.db.session import Database
from app.scripts import manage_safety_reports
from app.services.safety_reports import (
    PostgresSafetyReportService,
    SafetyReportOperatorError,
    SafetyReportOperatorRecord,
    SafetyReportStatus,
)
from tests.conftest import OWNER_ID


TARGET_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ROOM_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _insert_report(
    postgres_database: Database,
    *,
    report_id: UUID | None = None,
    created_at: datetime,
    status: str = "OPEN",
    details: str | None = "Sensitive report details",
    reason: str = "other_safety_concern",
) -> UUID:
    report_id = report_id or uuid4()
    with postgres_database.session_factory() as session:
        with session.begin():
            session.merge(UserModel(id=OWNER_ID, display_name="Room Owner"))
            session.merge(UserModel(id=TARGET_ID, display_name="Reported Player"))
            session.merge(
                RoomModel(
                    id=ROOM_ID,
                    owner_id=OWNER_ID,
                    name="Operator Room",
                    join_code="OPR001",
                    maximum_members=8,
                )
            )
            session.add(
                SafetyReportModel(
                    id=report_id,
                    reporter_user_id=OWNER_ID,
                    reported_user_id=TARGET_ID,
                    room_id=ROOM_ID,
                    reported_display_name_snapshot="Reported Player",
                    reason=reason,
                    details=details,
                    status=status,
                    created_at=created_at,
                )
            )
    return report_id


def _service(postgres_database: Database) -> PostgresSafetyReportService:
    return PostgresSafetyReportService(postgres_database.session_factory)


def test_operator_lists_open_reports_oldest_first_without_details(
    postgres_database: Database,
) -> None:
    newest = _insert_report(
        postgres_database,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    oldest = _insert_report(
        postgres_database,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reason="inappropriate_display_name",
    )
    _insert_report(
        postgres_database,
        created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        status="RESOLVED",
    )

    reports = _service(postgres_database).list_open_reports()

    assert tuple(report.id for report in reports) == (oldest, newest)
    assert all(report.status == "OPEN" for report in reports)
    assert all(report.details == "Sensitive report details" for report in reports)


def test_operator_cli_omits_details_unless_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = SafetyReportOperatorRecord(
        id=uuid4(),
        reporter_user_id=OWNER_ID,
        reported_user_id=TARGET_ID,
        room_id=ROOM_ID,
        reported_display_name_snapshot="Reported Player",
        reason="other_safety_concern",
        details="Sensitive report details",
        status="OPEN",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        resolved_at=None,
    )

    class _FakeDatabase:
        session_factory = object()

        def dispose(self) -> None:
            pass

    class _FakeService:
        def __init__(self, _session_factory: object) -> None:
            pass

        def get_report(self, _report_id: UUID) -> SafetyReportOperatorRecord:
            return report

    monkeypatch.setattr(
        manage_safety_reports.Database,
        "from_environment",
        lambda: _FakeDatabase(),
    )
    monkeypatch.setattr(
        manage_safety_reports,
        "PostgresSafetyReportService",
        _FakeService,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["manage_safety_reports", "show", "--report-id", str(report.id)],
    )
    manage_safety_reports.main()
    output = capsys.readouterr().out
    assert "details=" not in output

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "manage_safety_reports",
            "show",
            "--report-id",
            str(report.id),
            "--include-details",
        ],
    )
    manage_safety_reports.main()
    output = capsys.readouterr().out
    assert "details='Sensitive report details'" in output


def test_operator_cli_list_shows_safe_selection_fields_without_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = SafetyReportOperatorRecord(
        id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        reporter_user_id=OWNER_ID,
        reported_user_id=TARGET_ID,
        room_id=ROOM_ID,
        reported_display_name_snapshot="Reported Player",
        reason="other_safety_concern",
        details="Do not print this sensitive detail",
        status="OPEN",
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        resolved_at=None,
    )

    class _FakeDatabase:
        session_factory = object()

        def dispose(self) -> None:
            pass

    class _FakeService:
        def __init__(self, _session_factory: object) -> None:
            pass

        def list_open_reports(self) -> tuple[SafetyReportOperatorRecord, ...]:
            return (report,)

    monkeypatch.setattr(
        manage_safety_reports.Database,
        "from_environment",
        lambda: _FakeDatabase(),
    )
    monkeypatch.setattr(
        manage_safety_reports,
        "PostgresSafetyReportService",
        _FakeService,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["manage_safety_reports", "list"],
    )

    manage_safety_reports.main()
    output = capsys.readouterr().out

    assert f"id={report.id}" in output
    assert "status=OPEN" in output
    assert "reason=other_safety_concern" in output
    assert "created_at=2026-01-02T03:04:05+00:00" in output
    assert "reported_name='Reported Player'" in output
    assert "Do not print this sensitive detail" not in output


@pytest.mark.parametrize("status", ["RESOLVED", "DISMISSED"])
def test_operator_close_sets_resolved_at_and_preserves_evidence(
    postgres_database: Database,
    status: SafetyReportStatus,
) -> None:
    report_id = _insert_report(
        postgres_database,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    before = _service(postgres_database).get_report(report_id)

    closed = _service(postgres_database).close_report(
        report_id=report_id,
        status=status,
    )

    assert closed.status == status
    assert closed.resolved_at is not None
    assert closed.resolved_at >= before.created_at
    assert closed.id == before.id
    assert closed.reporter_user_id == before.reporter_user_id
    assert closed.reported_user_id == before.reported_user_id
    assert closed.room_id == before.room_id
    assert closed.reported_display_name_snapshot == before.reported_display_name_snapshot
    assert closed.reason == before.reason
    assert closed.details == before.details


def test_operator_close_is_idempotent_and_rejects_conflicts_reopen_and_unknown(
    postgres_database: Database,
) -> None:
    report_id = _insert_report(
        postgres_database,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    service = _service(postgres_database)
    first = service.close_report(report_id=report_id, status="RESOLVED")
    repeated = service.close_report(report_id=report_id, status="RESOLVED")

    assert repeated.resolved_at == first.resolved_at
    with pytest.raises(SafetyReportOperatorError):
        service.close_report(report_id=report_id, status="DISMISSED")
    with pytest.raises(SafetyReportOperatorError):
        service.close_report(
            report_id=report_id,
            status=cast(SafetyReportStatus, "OPEN"),
        )
    with pytest.raises(SafetyReportOperatorError):
        service.close_report(report_id=uuid4(), status="RESOLVED")

    with postgres_database.session_factory() as session:
        persisted = session.get(SafetyReportModel, report_id)
    assert persisted is not None
    assert persisted.status == "RESOLVED"
    assert persisted.resolved_at == first.resolved_at


def test_tombstoned_report_remains_visible_and_closable(
    postgres_database: Database,
    postgres_user_repository,
) -> None:
    postgres_user_repository.upsert_profile(TARGET_ID, "Reported Player")
    report_id = _insert_report(
        postgres_database,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    deletion = PostgresAccountDeletionRepository(
        postgres_database.session_factory
    ).delete_local_account(TARGET_ID)
    assert deletion.already_deleted is False

    service = _service(postgres_database)
    visible = service.get_report(report_id)
    closed = service.close_report(report_id=report_id, status="DISMISSED")

    assert visible.reported_user_id in {TARGET_ID, None}
    assert visible.reported_display_name_snapshot == "Reported Player"
    assert closed.status == "DISMISSED"
    assert closed.reported_display_name_snapshot == "Reported Player"
    assert postgres_user_repository.get_by_id(TARGET_ID).is_deleted

    with postgres_database.session_factory() as session:
        persisted = session.scalar(
            select(SafetyReportModel).where(SafetyReportModel.id == report_id)
        )
    assert persisted is not None
    assert persisted.reported_user_id in {TARGET_ID, None}
