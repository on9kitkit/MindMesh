from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.db.models.safety_report import SafetyReportModel
from app.db.session import Database
from app.domain.errors import SafetyReportNotAllowedError
from app.repositories.users import UserRepository
from app.schemas.safety_reports import SafetyReportCreateRequest
from app.services.safety_reports import PostgresSafetyReportService
from app.auth import FakeAuthVerifier
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


TARGET_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TARGET_TOKEN = "safety-target-token"
UNRELATED_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
UNRELATED_TOKEN = "safety-unrelated-token"


def _register_user(
    auth_verifier: FakeAuthVerifier,
    user_repository: UserRepository,
    *,
    token: str,
    user_id: UUID,
    display_name: str,
) -> None:
    auth_verifier.register(token, user_id)
    user_repository.upsert_profile(user_id, display_name)


def _shared_room(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: UserRepository,
) -> UUID:
    _register_user(
        auth_verifier,
        user_repository,
        token=TARGET_TOKEN,
        user_id=TARGET_ID,
        display_name="Reported Player",
    )
    room = client.post(
        "/rooms",
        json={"name": "Safety Room", "maximum_members": 8},
        headers=auth_headers(),
    )
    assert room.status_code == 201
    room_id = UUID(room.json()["id"])
    joined = client.post(
        f"/rooms/{room_id}/members",
        headers=auth_headers(TARGET_TOKEN),
    )
    assert joined.status_code == 201
    return room_id


def test_shared_room_report_is_server_authorized_and_idempotent(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_user_repository: UserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _shared_room(postgres_client, auth_verifier, postgres_user_repository)
    payload = {
        "reported_user_id": str(TARGET_ID),
        "room_id": str(room_id),
        "reason": "disruptive_room_behaviour",
        "details": "  Repeatedly disrupted the room.  ",
    }

    first = postgres_client.post(
        "/safety-reports",
        json=payload,
        headers=auth_headers(OWNER_TOKEN),
    )
    second = postgres_client.post(
        "/safety-reports",
        json=payload,
        headers=auth_headers(OWNER_TOKEN),
    )

    assert first.status_code == 202
    assert first.json() == {"status": "report_received"}
    assert second.status_code == 202
    with postgres_database.session_factory() as session:
        assert session.scalar(select(func.count(SafetyReportModel.id))) == 1
        report = session.scalar(select(SafetyReportModel))
        assert report is not None
        assert report.details == "Repeatedly disrupted the room."
        assert report.reported_display_name_snapshot == "Reported Player"


def test_report_rejects_self_and_unrelated_targets_without_enumeration(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_user_repository: UserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _shared_room(postgres_client, auth_verifier, postgres_user_repository)
    _register_user(
        auth_verifier,
        postgres_user_repository,
        token=UNRELATED_TOKEN,
        user_id=UNRELATED_ID,
        display_name="Unrelated Player",
    )

    for target_id in (OWNER_ID, UNRELATED_ID):
        response = postgres_client.post(
            "/safety-reports",
            json={
                "reported_user_id": str(target_id),
                "room_id": str(room_id),
                "reason": "other_safety_concern",
            },
            headers=auth_headers(OWNER_TOKEN),
        )
        assert response.status_code == 403
        assert response.json() == {
            "error": {
                "code": "safety_report_not_allowed",
                "message": "This safety report could not be submitted.",
            }
        }

    with postgres_database.session_factory() as session:
        assert session.scalar(select(func.count(SafetyReportModel.id))) == 0


def test_report_details_are_bounded_and_control_characters_are_rejected(
    postgres_client: TestClient,
    auth_verifier: FakeAuthVerifier,
    postgres_user_repository: UserRepository,
) -> None:
    room_id = _shared_room(postgres_client, auth_verifier, postgres_user_repository)
    base = {
        "reported_user_id": str(TARGET_ID),
        "room_id": str(room_id),
        "reason": "other_safety_concern",
    }
    for details in ("x" * 501, "visible\u200btext"):
        response = postgres_client.post(
            "/safety-reports",
            json={**base, "details": details},
            headers=auth_headers(OWNER_TOKEN),
        )
        assert response.status_code == 422


def test_report_survives_target_account_tombstone(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_user_repository: UserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _shared_room(postgres_client, auth_verifier, postgres_user_repository)
    response = postgres_client.post(
        "/safety-reports",
        json={
            "reported_user_id": str(TARGET_ID),
            "room_id": str(room_id),
            "reason": "inappropriate_display_name",
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert response.status_code == 202

    result = PostgresAccountDeletionRepository(
        postgres_database.session_factory
    ).delete_local_account(TARGET_ID)
    assert result.already_deleted is False

    with postgres_database.session_factory() as session:
        report = session.scalar(select(SafetyReportModel))
        assert report is not None
        assert report.reported_display_name_snapshot == "Reported Player"


def test_postgres_service_rejects_deleted_reporter_without_leaking_context(
    postgres_database: Database,
    postgres_user_repository: UserRepository,
) -> None:
    PostgresAccountDeletionRepository(
        postgres_database.session_factory
    ).delete_local_account(OWNER_ID)
    service = PostgresSafetyReportService(postgres_database.session_factory)
    payload = SafetyReportCreateRequest(
        reported_user_id=TARGET_ID,
        room_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        reason="other_safety_concern",
    )
    try:
        service.submit_report(reporter_id=OWNER_ID, payload=payload)
    except SafetyReportNotAllowedError:
        pass
    else:
        raise AssertionError("an unrelated or missing context must be rejected")
