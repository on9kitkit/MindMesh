from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID

from alembic import command
from alembic.config import Config
from httpx import Response
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.auth import FakeAuthVerifier
from app.db.models.membership import RoomMembershipModel
from app.db.models.room import RoomModel
from app.db.models.user import UserModel
from app.db.session import Database, DatabaseConfigurationError, DatabaseSettings
from app.domain.errors import (
    DuplicateMembershipError,
    RoomApplicationError,
    RoomCreationError,
    RoomFullError,
    UserAlreadyInAnotherRoomError,
)
from app.domain.member import RoomMember
from app.main import create_app
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.services.rooms import RoomService
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


SECOND_USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
THIRD_USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
FOURTH_USER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _create_room(
    client: TestClient,
    *,
    token: str = OWNER_TOKEN,
    name: str = "Physics Sprint",
    maximum_members: int = 8,
) -> dict[str, object]:
    response = client.post(
        "/rooms",
        json={"name": name, "maximum_members": maximum_members},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def _join_room(
    client: TestClient,
    room_id: UUID,
    *,
    token: str,
    body: object | None = None,
) -> Response:
    request: dict[str, object] = {"headers": auth_headers(token)}
    if body is not None:
        request["json"] = body
    return client.post(f"/rooms/{room_id}/members", **request)


def _room_id(room: dict[str, object]) -> UUID:
    return UUID(cast(str, room["id"]))


def _register_user(
    user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
    *,
    token: str,
    user_id: UUID,
    display_name: str,
) -> None:
    auth_verifier.register(token, user_id)
    user_repository.upsert_profile(user_id, display_name)


@contextmanager
def _new_postgres_client(
    database: Database,
    user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> Iterator[TestClient]:
    app = create_app(
        repository=PostgresRoomRepository(database.session_factory),
        membership_repository=PostgresMembershipRepository(
            database.session_factory
        ),
        user_repository=user_repository,
        auth_verifier=auth_verifier,
    )
    with TestClient(app) as client:
        yield client


def _migration_config(database_url: str) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def test_postgres_room_survives_application_restart(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    with _new_postgres_client(
        postgres_database,
        postgres_user_repository,
        auth_verifier,
    ) as first_client:
        created = _create_room(first_client)
        room_id = _room_id(created)

    with _new_postgres_client(
        postgres_database,
        postgres_user_repository,
        auth_verifier,
    ) as second_client:
        response = second_client.get(
            f"/rooms/{room_id}", headers=auth_headers()
        )

    assert response.status_code == 200
    assert response.json() == created


def test_postgres_membership_and_profile_survive_restart(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="second-user-token",
        user_id=SECOND_USER_ID,
        display_name="Second User",
    )
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="third-user-token",
        user_id=THIRD_USER_ID,
        display_name="Third User",
    )
    with _new_postgres_client(
        postgres_database,
        postgres_user_repository,
        auth_verifier,
    ) as first_client:
        room_id = _room_id(_create_room(first_client))
        joined = _join_room(first_client, room_id, token="second-user-token")
        assert joined.status_code == 201

    with _new_postgres_client(
        postgres_database,
        postgres_user_repository,
        auth_verifier,
    ) as second_client:
        response = second_client.get(
            f"/rooms/{room_id}/members", headers=auth_headers()
        )

    assert response.status_code == 200
    assert response.json()["members"] == [
        {"user_id": str(OWNER_ID), "display_name": "Room Owner"},
        {"user_id": str(SECOND_USER_ID), "display_name": "Second User"},
    ]


def test_postgres_room_owner_is_server_derived(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
    postgres_client: TestClient,
) -> None:
    room_id = _room_id(_create_room(postgres_client))

    with postgres_database.session_factory() as session:
        owner_id = session.scalar(
            select(RoomModel.owner_id).where(RoomModel.id == room_id)
        )

    assert owner_id == OWNER_ID


def test_postgres_users_and_owner_foreign_keys_exist(postgres_database: Database) -> None:
    with postgres_database.engine.connect() as connection:
        foreign_keys = {
            (foreign_key["name"], tuple(foreign_key["constrained_columns"]))
            for foreign_key in inspect(connection).get_foreign_keys("rooms")
        }
        membership_foreign_keys = {
            (foreign_key["name"], tuple(foreign_key["constrained_columns"]))
            for foreign_key in inspect(connection).get_foreign_keys(
                "room_memberships"
            )
        }

    assert (
        "fk_rooms_owner_id_users",
        ("owner_id",),
    ) in foreign_keys
    assert (
        "fk_room_memberships_user_id_users",
        ("user_id",),
    ) in membership_foreign_keys


def test_postgres_duplicate_membership_is_stable(
    postgres_client: TestClient,
) -> None:
    room_id = _room_id(_create_room(postgres_client))

    first = _join_room(postgres_client, room_id, token=OWNER_TOKEN)

    assert first.status_code == 409
    assert first.json()["error"]["code"] == "already_room_member"


def test_postgres_room_capacity_is_enforced(
    postgres_client: TestClient,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="second-user-token",
        user_id=SECOND_USER_ID,
        display_name="Second User",
    )
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="third-user-token",
        user_id=THIRD_USER_ID,
        display_name="Third User",
    )
    room_id = _room_id(_create_room(postgres_client, maximum_members=2))

    joined = _join_room(postgres_client, room_id, token="second-user-token")
    full = _join_room(postgres_client, room_id, token="third-user-token")

    assert joined.status_code == 201
    assert full.status_code == 409
    assert full.json()["error"]["code"] == "room_full"


def test_postgres_cross_room_restriction_is_enforced(
    postgres_client: TestClient,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="second-user-token",
        user_id=SECOND_USER_ID,
        display_name="Second User",
    )
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="third-user-token",
        user_id=THIRD_USER_ID,
        display_name="Third User",
    )
    first_room = _room_id(_create_room(postgres_client))
    second_room = _room_id(
        _create_room(postgres_client, token="third-user-token", name="Second Room")
    )

    first = _join_room(postgres_client, first_room, token="second-user-token")
    second = _join_room(postgres_client, second_room, token="second-user-token")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "user_already_in_another_room"


def test_postgres_failed_atomic_room_creation_leaves_no_rows(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    unknown_user_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")

    with pytest.raises(RoomCreationError):
        postgres_service.create_room(
            name="Failed Atomic Room",
            maximum_members=2,
            owner_id=unknown_user_id,
            owner_display_name="Unknown User",
        )

    with postgres_database.session_factory() as session:
        room_count = session.scalar(
            select(RoomModel.id).where(RoomModel.name == "Failed Atomic Room")
        )
        membership_count = session.scalar(
            select(RoomMembershipModel.id).join(RoomModel).where(
                RoomModel.name == "Failed Atomic Room"
            )
        )

    assert room_count is None
    assert membership_count is None


def test_postgres_profile_update_is_the_membership_display_name_source(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    _register_user(
        postgres_user_repository,
        auth_verifier,
        token="second-user-token",
        user_id=SECOND_USER_ID,
        display_name="Before Update",
    )
    room_id = _room_id(_create_room(postgres_client))
    assert _join_room(postgres_client, room_id, token="second-user-token").status_code == 201

    profile = postgres_client.put(
        "/me/profile",
        json={"display_name": "After Update"},
        headers=auth_headers("second-user-token"),
    )
    members = postgres_client.get(
        f"/rooms/{room_id}/members", headers=auth_headers()
    )

    assert profile.status_code == 200
    assert members.json()["members"][1]["display_name"] == "After Update"
    assert "display_name" not in RoomMembershipModel.__table__.columns


def test_postgres_active_history_allows_rejoin_after_left_at(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    _register_direct_user(
        postgres_user_repository,
        THIRD_USER_ID,
        "History User",
    )
    room = postgres_service.create_room(
        name="History Room",
        maximum_members=2,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    membership_repository = PostgresMembershipRepository(
        postgres_database.session_factory
    )
    member = RoomMember(
        user_id=THIRD_USER_ID,
        display_name="History User",
        room_id=room.id,
    )
    membership_repository.join(member, room.maximum_members)

    from datetime import datetime, timezone

    with postgres_database.session_factory() as session:
        with session.begin():
            model = session.scalar(
                select(RoomMembershipModel).where(
                    RoomMembershipModel.user_id == THIRD_USER_ID,
                    RoomMembershipModel.room_id == room.id,
                )
            )
            assert model is not None
            model.left_at = datetime.now(timezone.utc)

    membership_repository.join(member, room.maximum_members)
    assert membership_repository.count_active_by_room(room.id) == 2


def _register_direct_user(
    user_repository: PostgresUserRepository,
    user_id: UUID,
    display_name: str,
) -> None:
    user_repository.upsert_profile(user_id, display_name)


def test_postgres_join_transaction_locks_final_slot(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    _register_direct_user(postgres_user_repository, SECOND_USER_ID, "Second User")
    _register_direct_user(postgres_user_repository, THIRD_USER_ID, "Third User")
    room = postgres_service.create_room(
        name="Concurrent Room",
        maximum_members=2,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    barrier = Barrier(2)

    def attempt(user_id: UUID) -> str:
        repository = PostgresMembershipRepository(postgres_database.session_factory)
        barrier.wait(timeout=10)
        try:
            repository.join(
                RoomMember(
                    user_id=user_id,
                    display_name="Concurrent User",
                    room_id=room.id,
                ),
                room.maximum_members,
            )
        except RoomFullError:
            return "full"
        except (DuplicateMembershipError, UserAlreadyInAnotherRoomError):
            return "conflict"
        return "joined"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [SECOND_USER_ID, THIRD_USER_ID]))

    assert sorted(results) == ["full", "joined"]
    assert postgres_service.count_room_members(room.id) == 2


def test_postgres_schema_rejects_orphan_user_membership(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    _register_direct_user(postgres_user_repository, OWNER_ID, "Room Owner")
    room = postgres_service.create_room(
        name="Foreign Key Room",
        maximum_members=2,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    repository = PostgresMembershipRepository(postgres_database.session_factory)

    with pytest.raises(RoomApplicationError):
        repository.add(
            RoomMember(
                user_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
                display_name="Orphan",
                room_id=room.id,
            )
        )


def test_postgres_database_settings_reject_non_postgres_url() -> None:
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_environment(
            environ={"DATABASE_URL": "sqlite:///studyroom.db"}
        )


def test_postgres_migration_round_trip(
    migrated_test_database: Database,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required")

    config = _migration_config(database_url)
    command.downgrade(config, "0002_supabase_identity")
    with migrated_test_database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "users" in tables
        assert "questions" not in tables
        membership_columns = {
            column["name"]
            for column in inspect(connection).get_columns("room_memberships")
        }
        assert "ready_at" not in membership_columns
        assert "closed_at" not in {
            column["name"] for column in inspect(connection).get_columns("rooms")
        }

    command.upgrade(config, "head")
    with migrated_test_database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "users" in tables
        assert {
            "questions",
            "quiz_sessions",
            "session_participants",
            "session_questions",
            "answer_submissions",
        }.issubset(tables)
        assert "ready_at" in {
            column["name"]
            for column in inspect(connection).get_columns("room_memberships")
        }
        assert "owner_id" in {
            column["name"]
            for column in inspect(connection).get_columns("rooms")
        }
        assert "closed_at" in {
            column["name"]
            for column in inspect(connection).get_columns("rooms")
        }
        assert "ix_rooms_closed_at" in {
            index["name"] for index in inspect(connection).get_indexes("rooms")
        }

    command.downgrade(config, "0001_initial")
    with migrated_test_database.engine.connect() as connection:
        assert "users" not in inspect(connection).get_table_names()
        room_columns = {
            column["name"] for column in inspect(connection).get_columns("rooms")
        }
        assert "owner_id" not in room_columns

    command.upgrade(config, "head")
