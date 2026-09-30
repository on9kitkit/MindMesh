import os
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.models.room import RoomModel
from app.db.session import Database
from app.repositories.postgres_users import PostgresUserRepository
from tests.conftest import OWNER_ID


BACKEND_ROOT = Path(__file__).resolve().parents[1]
OVERSIZED_ROOM_ID = UUID("88888888-8888-4888-8888-888888888888")


def migration_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def room_capacity_constraint(database: Database) -> str:
    with database.engine.connect() as connection:
        constraints = inspect(connection).get_check_constraints("rooms")
    match = next(
        constraint
        for constraint in constraints
        if constraint["name"] == "ck_rooms_maximum_members"
    )
    return str(match["sqltext"])


def test_head_database_rejects_capacity_above_twenty(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    RoomModel(
                        id=OVERSIZED_ROOM_ID,
                        owner_id=OWNER_ID,
                        name="Oversized Room",
                        join_code="SIZE21",
                        maximum_members=21,
                    )
                )

    assert "20" in room_capacity_constraint(postgres_database)


def test_capacity_migration_downgrades_and_reupgrades_cleanly(
    postgres_database: Database,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required")
    config = migration_config(database_url)

    command.downgrade(config, "0004_room_lifecycle")
    assert "50" in room_capacity_constraint(postgres_database)

    command.upgrade(config, "head")
    assert "20" in room_capacity_constraint(postgres_database)


def test_capacity_migration_stops_without_destroying_violating_data(
    postgres_database: Database,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required")
    config = migration_config(database_url)
    command.downgrade(config, "0004_room_lifecycle")

    try:
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, display_name) "
                    "VALUES (:user_id, :display_name)"
                ),
                {"user_id": OWNER_ID, "display_name": "Room Owner"},
            )
            connection.execute(
                text(
                    "INSERT INTO rooms "
                    "(id, owner_id, name, join_code, maximum_members) "
                    "VALUES (:room_id, :owner_id, :name, :join_code, 21)"
                ),
                {
                    "room_id": OVERSIZED_ROOM_ID,
                    "owner_id": OWNER_ID,
                    "name": "Existing Oversized Room",
                    "join_code": "OLD021",
                },
            )

        with pytest.raises(RuntimeError, match="twenty-member room limit"):
            command.upgrade(config, "head")

        with postgres_database.engine.connect() as connection:
            capacity = connection.scalar(
                text(
                    "SELECT maximum_members FROM rooms WHERE id = :room_id"
                ),
                {"room_id": OVERSIZED_ROOM_ID},
            )
        assert capacity == 21
    finally:
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM rooms WHERE id = :room_id"),
                {"room_id": OVERSIZED_ROOM_ID},
            )
            connection.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": OWNER_ID},
            )
        command.upgrade(config, "head")

    assert "20" in room_capacity_constraint(postgres_database)
