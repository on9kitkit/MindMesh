import os
import re
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, make_url

from app.auth import FakeAuthVerifier
from app.db.session import Database
from app.main import create_app
from app.repositories.members import InMemoryMembershipRepository
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.repositories.rooms import InMemoryRoomRepository
from app.repositories.users import InMemoryUserRepository
from app.services.rooms import RoomService
from app.services.safety_reports import PostgresSafetyReportService
from app.services.sessions import SessionService

BACKEND_ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
OWNER_TOKEN = "test-owner-token"


@pytest.fixture(autouse=True)
def deny_live_openai_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests may use MockTransport, but never the paid OpenAI network transport."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    async_handler = httpx.AsyncHTTPTransport.handle_async_request
    sync_handler = httpx.HTTPTransport.handle_request

    async def guarded_async(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openai.com":
            raise httpx.ConnectError("Live OpenAI transport disabled in tests", request=request)
        return await async_handler(self, request)

    def guarded_sync(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openai.com":
            raise httpx.ConnectError("Live OpenAI transport disabled in tests", request=request)
        return sync_handler(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)


def auth_headers(token: str = OWNER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_verifier() -> FakeAuthVerifier:
    return FakeAuthVerifier({OWNER_TOKEN: OWNER_ID})


@pytest.fixture
def user_repository() -> InMemoryUserRepository:
    repository = InMemoryUserRepository()
    repository.upsert_profile(OWNER_ID, "Room Owner")
    return repository


@pytest.fixture
def client(
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> Iterator[TestClient]:
    membership_repository = InMemoryMembershipRepository()
    app = create_app(
        repository=InMemoryRoomRepository(),
        membership_repository=membership_repository,
        user_repository=user_repository,
        auth_verifier=auth_verifier,
    )
    with TestClient(app) as test_client:
        yield test_client


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def _clear_database(database: Database) -> None:
    with database.engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        _clear_tables(connection, tables)


def _clear_tables(connection: Connection, tables: set[str]) -> None:
    """Clear known tables in foreign-key dependency order."""

    for table_name in (
        "pet_equipment",
        "pet_ownership",
        "pet_purchases",
        "coin_ledger",
        "qualified_study_days",
        "coin_wallets",
        "learning_completion_receipts",
        "room_reward_enrollments",
        "solo_self_checks",
        "solo_answers",
        "solo_questions",
        "solo_preparations",
        "solo_attempts",
        "learning_settings",
        "safety_reports",
        "account_deletion_outbox",
        "answer_submissions",
        "session_questions",
        "session_participants",
        "quiz_sessions",
        "generated_quiz_questions",
        "quiz_preparations",
        "questions",
        "room_memberships",
        "rooms",
        "users",
    ):
        if table_name in tables:
            connection.execute(text(f"DELETE FROM {table_name}"))


def _clear_database_if_present(database: Database) -> None:
    with database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
    with database.engine.begin() as connection:
        _clear_tables(connection, tables)


@pytest.fixture(scope="session")
def migrated_test_database() -> Iterator[Database]:
    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    parsed_url = make_url(database_url)
    approved_name = os.environ.get("TEST_DATABASE_NAME", "").strip()
    if (
        not re.fullmatch(r"studyroom_companions_pgcheck_[0-9]{8}", approved_name)
        or parsed_url.database != approved_name
        or parsed_url.host not in {"127.0.0.1", "localhost"}
        or parsed_url.port != 5432
    ):
        pytest.fail("TEST_DATABASE_URL must target the explicitly named isolated local test database")
    pre_migration_engine = create_engine(database_url)
    with pre_migration_engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        _clear_tables(connection, tables)
    pre_migration_engine.dispose()
    command.upgrade(_alembic_config(database_url), "head")
    database = Database.from_url(database_url)
    _clear_database(database)
    try:
        yield database
    finally:
        _clear_database_if_present(database)
        database.dispose()


@pytest.fixture
def postgres_database(migrated_test_database: Database) -> Iterator[Database]:
    _clear_database(migrated_test_database)
    try:
        yield migrated_test_database
    finally:
        _clear_database_if_present(migrated_test_database)


@pytest.fixture
def postgres_user_repository(postgres_database: Database) -> PostgresUserRepository:
    repository = PostgresUserRepository(postgres_database.session_factory)
    repository.upsert_profile(OWNER_ID, "Room Owner")
    return repository


@pytest.fixture
def postgres_service(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> RoomService:
    """Provide a room service with the fixed owner profile available."""

    return RoomService(
        PostgresRoomRepository(postgres_database.session_factory),
        membership_repository=PostgresMembershipRepository(
            postgres_database.session_factory
        ),
    )


@pytest.fixture
def postgres_session_service(postgres_database: Database) -> SessionService:
    return SessionService(
        PostgresQuizSessionRepository(postgres_database.session_factory)
    )


@pytest.fixture
def postgres_client(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
    postgres_session_service: SessionService,
    auth_verifier: FakeAuthVerifier,
) -> Iterator[TestClient]:
    app = create_app(
        repository=PostgresRoomRepository(postgres_database.session_factory),
        membership_repository=PostgresMembershipRepository(
            postgres_database.session_factory
        ),
        user_repository=postgres_user_repository,
        auth_verifier=auth_verifier,
        session_service=postgres_session_service,
        safety_report_service=PostgresSafetyReportService(
            postgres_database.session_factory
        ),
    )
    with TestClient(app) as test_client:
        yield test_client
