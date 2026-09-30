"""Isolate StudyRoom tables from Supabase Data API roles.

Revision ID: 0006_supabase_data_api_isolation
Revises: 0005_room_capacity
Create Date: 2026-08-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_supabase_data_api_isolation"
down_revision: str | None = "0005_room_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STUDYROOM_TABLES = (
    "users",
    "rooms",
    "room_memberships",
    "questions",
    "quiz_sessions",
    "session_participants",
    "session_questions",
    "answer_submissions",
    "alembic_version",
)
_SUPABASE_DATA_API_ROLES = ("anon", "authenticated", "service_role")


def _revoke_optional_role(table_name: str, role_name: str) -> None:
    """Revoke a Supabase role only when this PostgreSQL role exists."""

    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = '{role_name}'
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I',
                        '{table_name}',
                        '{role_name}'
                    );
                END IF;
            END $$;
            """
        )
    )


def _isolate_table(table_name: str) -> None:
    """Keep one StudyRoom table inaccessible through Supabase Data API roles."""

    op.execute(
        sa.text(
            f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY"
        )
    )
    op.execute(
        sa.text(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM PUBLIC")
    )
    for role_name in _SUPABASE_DATA_API_ROLES:
        _revoke_optional_role(table_name, role_name)


def upgrade() -> None:
    for table_name in _STUDYROOM_TABLES:
        _isolate_table(table_name)


def downgrade() -> None:
    # Security is intentionally asymmetric. Removing this revision must not
    # reopen a table to Data API roles or disable its RLS boundary.
    for table_name in _STUDYROOM_TABLES:
        _isolate_table(table_name)
