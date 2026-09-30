from uuid import UUID

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import func, select

from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.db.models.account_deletion_outbox import AccountDeletionOutboxModel
from app.db.models.user import UserModel
from app.domain.errors import AccountDeletedError, AccountSuspendedError
from app.services.rooms import RoomService
from tests.conftest import OWNER_ID, auth_headers


SUSPENDED_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SUSPENDED_TOKEN = "suspension-postgres-token"


def test_postgres_suspension_is_reversible_and_retains_local_history(
    postgres_database,
    postgres_user_repository,
) -> None:
    user = postgres_user_repository.upsert_profile(SUSPENDED_ID, "Retained Student")
    suspended = postgres_user_repository.suspend(
        SUSPENDED_ID,
        "safety_review",
    )

    assert suspended.is_suspended
    assert suspended.display_name == user.display_name
    with pytest.raises(AccountSuspendedError):
        postgres_user_repository.upsert_profile(SUSPENDED_ID, "Updated Student")

    with postgres_database.session_factory() as session:
        model = session.get(UserModel, SUSPENDED_ID)
        pending_jobs = session.scalar(
            select(func.count(AccountDeletionOutboxModel.id)).where(
                AccountDeletionOutboxModel.user_id == SUSPENDED_ID
            )
        )
    assert model is not None
    assert model.display_name == "Retained Student"
    assert model.suspended_at is not None
    assert model.suspension_reason_code == "safety_review"
    assert pending_jobs == 0

    unsuspended = postgres_user_repository.unsuspend(SUSPENDED_ID)
    assert not unsuspended.is_suspended
    assert unsuspended.display_name == "Retained Student"


def test_postgres_suspension_denies_http_and_websocket_until_unsuspended(
    postgres_client,
    postgres_service: RoomService,
    postgres_user_repository,
    auth_verifier,
) -> None:
    auth_verifier.register(SUSPENDED_TOKEN, SUSPENDED_ID)
    postgres_user_repository.upsert_profile(SUSPENDED_ID, "Suspended Student")
    postgres_user_repository.suspend(SUSPENDED_ID, "abuse_prevention")

    headers = auth_headers(SUSPENDED_TOKEN)
    create = postgres_client.post(
        "/rooms",
        headers=headers,
        json={"name": "Blocked Room", "maximum_members": 8},
    )
    profile = postgres_client.put(
        "/me/profile",
        headers=headers,
        json={"display_name": "New Student"},
    )
    assert create.status_code == 403
    assert profile.status_code == 403
    assert create.json()["error"]["code"] == "account_suspended"
    assert profile.json()["error"]["code"] == "account_suspended"

    room = postgres_service.create_room(
        name="Available Room",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    with postgres_client.websocket_connect(f"/ws/rooms/{room.id}") as socket:
        socket.send_json(
            {
                "protocol_version": 1,
                "type": "AUTHENTICATE",
                "payload": {"access_token": SUSPENDED_TOKEN},
            }
        )
        error = socket.receive_json()
        assert error["payload"]["code"] == "account_suspended"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4403

    postgres_user_repository.unsuspend(SUSPENDED_ID)
    restored = postgres_client.post(
        "/rooms",
        headers=headers,
        json={"name": "Restored Room", "maximum_members": 8},
    )
    assert restored.status_code == 201


def test_suspended_identity_can_use_the_existing_secure_deletion_contract(
    postgres_database,
    postgres_user_repository,
) -> None:
    postgres_user_repository.upsert_profile(SUSPENDED_ID, "Delete Me Later")
    postgres_user_repository.suspend(SUSPENDED_ID, "policy_violation")

    result = PostgresAccountDeletionRepository(
        postgres_database.session_factory
    ).delete_local_account(SUSPENDED_ID)

    assert result.already_deleted is False
    deleted = postgres_user_repository.get_by_id(SUSPENDED_ID)
    assert deleted is not None
    assert deleted.is_deleted
    assert not deleted.is_suspended
    with pytest.raises(AccountDeletedError):
        postgres_user_repository.unsuspend(SUSPENDED_ID)
