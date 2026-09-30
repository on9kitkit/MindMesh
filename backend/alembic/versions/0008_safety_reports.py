"""Add isolated minimal safety reports."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008_safety_reports"
down_revision: str | None = "0007_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SUPABASE_DATA_API_ROLES = ("anon", "authenticated", "service_role")


def _revoke_optional_role(table_name: str, role_name: str) -> None:
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
    op.execute(
        sa.text(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
    )
    op.execute(
        sa.text(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM PUBLIC")
    )
    for role_name in _SUPABASE_DATA_API_ROLES:
        _revoke_optional_role(table_name, role_name)


def upgrade() -> None:
    op.create_table(
        "safety_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reported_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "reported_display_name_snapshot",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'OPEN'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('inappropriate_display_name', "
            "'disruptive_room_behaviour', 'other_safety_concern')",
            name="ck_safety_reports_reason",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED', 'DISMISSED')",
            name="ck_safety_reports_status",
        ),
        sa.CheckConstraint(
            "details IS NULL OR char_length(details) <= 500",
            name="ck_safety_reports_details_length",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"],
            ["users.id"],
            name="fk_safety_reports_reporter_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reported_user_id"],
            ["users.id"],
            name="fk_safety_reports_reported_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name="fk_safety_reports_room_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_reports_reporter",
        "safety_reports",
        ["reporter_user_id"],
    )
    op.create_index(
        "ix_safety_reports_reported",
        "safety_reports",
        ["reported_user_id"],
    )
    op.create_index(
        "ix_safety_reports_room_created",
        "safety_reports",
        ["room_id", "created_at"],
    )
    op.create_index(
        "ix_safety_reports_status_created",
        "safety_reports",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_safety_reports_open_duplicate",
        "safety_reports",
        ["reporter_user_id", "reported_user_id", "room_id", "reason"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'OPEN' AND reporter_user_id IS NOT NULL "
            "AND reported_user_id IS NOT NULL AND room_id IS NOT NULL"
        ),
    )
    _isolate_table("safety_reports")


def downgrade() -> None:
    op.drop_index(
        "uq_safety_reports_open_duplicate",
        table_name="safety_reports",
    )
    op.drop_index("ix_safety_reports_status_created", table_name="safety_reports")
    op.drop_index("ix_safety_reports_room_created", table_name="safety_reports")
    op.drop_index("ix_safety_reports_reported", table_name="safety_reports")
    op.drop_index("ix_safety_reports_reporter", table_name="safety_reports")
    op.drop_table("safety_reports")
