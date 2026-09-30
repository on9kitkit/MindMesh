from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import Database


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASE_STUDYROOM_TABLES = (
    "users",
    "rooms",
    "room_memberships",
    "questions",
    "quiz_sessions",
    "session_participants",
    "session_questions",
    "answer_submissions",
)
STUDYROOM_TABLES = (
    *BASE_STUDYROOM_TABLES,
    "safety_reports",
)
BASE_SECURED_TABLES = (*BASE_STUDYROOM_TABLES, "alembic_version")
SECURED_TABLES = (*STUDYROOM_TABLES, "alembic_version")
SUPABASE_DATA_API_ROLES = ("anon", "authenticated", "service_role")
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)


def migration_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def _security_snapshot(
    database: Database,
    table_names: tuple[str, ...] = SECURED_TABLES,
) -> dict[str, tuple[bool, bool, int, bool]]:
    snapshot: dict[str, tuple[bool, bool, int, bool]] = {}
    with database.engine.connect() as connection:
        for table_name in table_names:
            row = connection.execute(
                text(
                    """
                    SELECT
                        relation.relrowsecurity,
                        relation.relforcerowsecurity,
                        (
                            SELECT count(*)
                            FROM pg_policy AS policy
                            WHERE policy.polrelid = relation.oid
                        ) AS policy_count,
                        COALESCE(
                            (
                                SELECT bool_or(acl.grantee = 0)
                                FROM aclexplode(relation.relacl) AS acl
                            ),
                            false
                        ) AS public_acl
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = :table_name
                    """
                ),
                {"table_name": table_name},
            ).one()
            snapshot[table_name] = (
                bool(row.relrowsecurity),
                bool(row.relforcerowsecurity),
                int(row.policy_count),
                bool(row.public_acl),
            )
    return snapshot


def _assert_backend_access(
    database: Database,
    table_names: tuple[str, ...] = SECURED_TABLES,
) -> None:
    with database.engine.connect() as connection:
        backend_role = str(connection.scalar(text("SELECT current_user")))
        for table_name in table_names:
            table_identifier = f"public.{table_name}"
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                allowed = connection.scalar(
                    text(
                        "SELECT has_table_privilege(:role_name, :table_name, :privilege)"
                    ),
                    {
                        "role_name": backend_role,
                        "table_name": table_identifier,
                        "privilege": privilege,
                    },
                )
                assert allowed is True


def _assert_data_api_roles_have_no_privileges(
    database: Database,
    *,
    data_api_roles: tuple[str, ...],
    include_public_probe: str | None,
    table_names: tuple[str, ...] = SECURED_TABLES,
) -> None:
    with database.engine.connect() as connection:
        for role_name in (*data_api_roles, include_public_probe):
            if role_name is None:
                continue
            for table_name in table_names:
                for privilege in TABLE_PRIVILEGES:
                    allowed = connection.scalar(
                        text(
                            "SELECT has_table_privilege(:role_name, :table_name, :privilege)"
                        ),
                        {
                            "role_name": role_name,
                            "table_name": f"public.{table_name}",
                            "privilege": privilege,
                        },
                    )
                    assert allowed is False, (role_name, table_name, privilege)


def _assert_isolated(
    database: Database,
    *,
    data_api_roles: tuple[str, ...] = (),
    probe_role: str | None = None,
    secured_tables: tuple[str, ...] = SECURED_TABLES,
) -> None:
    security = _security_snapshot(database, secured_tables)
    assert set(security) == set(secured_tables)
    for table_name, (rls, force_rls, policy_count, public_acl) in security.items():
        assert rls is True, table_name
        assert force_rls is False, table_name
        assert policy_count == 0, table_name
        assert public_acl is False, table_name
    _assert_data_api_roles_have_no_privileges(
        database,
        data_api_roles=data_api_roles,
        include_public_probe=probe_role,
        table_names=secured_tables,
    )
    _assert_backend_access(database, secured_tables)


def _schema_signature(database: Database) -> dict[str, object]:
    signature: dict[str, object] = {}
    with database.engine.connect() as connection:
        inspector = inspect(connection)
        for table_name in STUDYROOM_TABLES:
            signature[table_name] = {
                "columns": tuple(
                    (
                        column["name"],
                        str(column["type"]),
                        bool(column["nullable"]),
                        column["default"],
                    )
                    for column in inspector.get_columns(table_name)
                ),
                "indexes": tuple(
                    sorted(
                        (
                            index["name"],
                            bool(index["unique"]),
                            tuple(index["column_names"]),
                        )
                        for index in inspector.get_indexes(table_name)
                    )
                ),
                "foreign_keys": tuple(
                    sorted(
                        (
                            foreign_key["name"],
                            tuple(foreign_key["constrained_columns"]),
                            foreign_key["referred_table"],
                            tuple(foreign_key["referred_columns"]),
                            foreign_key["options"].get("ondelete"),
                        )
                        for foreign_key in inspector.get_foreign_keys(table_name)
                    )
                ),
                "checks": tuple(
                    sorted(
                        (check["name"], check["sqltext"])
                        for check in inspector.get_check_constraints(table_name)
                    )
                ),
                "unique_constraints": tuple(
                    sorted(
                        (
                            constraint["name"],
                            tuple(constraint["column_names"]),
                        )
                        for constraint in inspector.get_unique_constraints(table_name)
                    )
                ),
                "primary_key": inspector.get_pk_constraint(table_name),
            }
    return signature


def test_0006_is_local_compatible_and_preserves_schema_and_data(
    postgres_database: Database,
) -> None:
    database_url = _database_url_or_skip()
    with postgres_database.engine.connect() as connection:
        existing_roles = set(
            connection.scalars(
                text(
                    "SELECT rolname FROM pg_roles "
                    "WHERE rolname IN ('anon', 'authenticated', 'service_role')"
                )
            )
        )
    if existing_roles:
        pytest.skip("Supabase role simulation is covered separately")

    before = _schema_signature(postgres_database)
    command.downgrade(migration_config(database_url), "0005_room_capacity")
    with postgres_database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, display_name) "
                "VALUES ('11111111-1111-4111-8111-111111111111', 'Security User')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO rooms "
                "(id, owner_id, name, join_code, maximum_members) "
                "VALUES "
                "('22222222-2222-4222-8222-222222222222', "
                "'11111111-1111-4111-8111-111111111111', "
                "'Security Room', 'SEC001', 2)"
            )
        )

    _assert_isolated(postgres_database, secured_tables=BASE_SECURED_TABLES)
    command.upgrade(migration_config(database_url), "head")

    assert _schema_signature(postgres_database) == before
    _assert_isolated(postgres_database)
    with postgres_database.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM users "
                "WHERE id = '11111111-1111-4111-8111-111111111111'"
            )
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM rooms "
                "WHERE id = '22222222-2222-4222-8222-222222222222'"
            )
        ) == 1

    command.downgrade(migration_config(database_url), "0005_room_capacity")
    _assert_isolated(postgres_database, secured_tables=BASE_SECURED_TABLES)
    command.upgrade(migration_config(database_url), "head")
    _assert_isolated(postgres_database)


def test_0006_revokes_simulated_supabase_roles_without_revoking_backend(
    postgres_database: Database,
) -> None:
    database_url = _database_url_or_skip()
    created_roles: list[str] = []
    try:
        try:
            with postgres_database.engine.begin() as connection:
                existing_roles = set(
                    connection.scalars(
                        text(
                            "SELECT rolname FROM pg_roles "
                            "WHERE rolname IN ('anon', 'authenticated', 'service_role')"
                        )
                    )
                )
                if existing_roles:
                    pytest.skip("Supabase role names already exist locally")
                for role_name in SUPABASE_DATA_API_ROLES:
                    connection.execute(
                        text(f'CREATE ROLE "{role_name}" NOLOGIN')
                    )
                    created_roles.append(role_name)
                connection.execute(
                    text('CREATE ROLE "data_api_probe" NOLOGIN')
                )
                created_roles.append("data_api_probe")
        except SQLAlchemyError as error:
            pytest.skip(f"local role simulation unavailable: {type(error).__name__}")

        command.downgrade(migration_config(database_url), "0005_room_capacity")
        command.upgrade(migration_config(database_url), "head")
        _assert_isolated(
            postgres_database,
            data_api_roles=SUPABASE_DATA_API_ROLES,
            probe_role="data_api_probe",
        )
    finally:
        if created_roles:
            with postgres_database.engine.begin() as connection:
                for role_name in reversed(created_roles):
                    connection.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))


def _database_url_or_skip() -> str:
    import os

    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required")
    return database_url
