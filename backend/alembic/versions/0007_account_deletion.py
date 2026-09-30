"""Add local account tombstones and provider-cleanup outbox."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_account_deletion"
down_revision: str | None = "0006_supabase_data_api_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    """Apply the migration-0006 Data API boundary to the new table."""

    op.execute(
        sa.text(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
    )
    op.execute(
        sa.text(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM PUBLIC")
    )
    for role_name in _SUPABASE_DATA_API_ROLES:
        _revoke_optional_role(table_name, role_name)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    op.create_table(
        "account_deletion_outbox",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_error_category",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_account_deletion_outbox_user_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_account_deletion_outbox_user_provider",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_account_deletion_outbox_attempts_nonnegative",
        ),
    )
    op.create_index(
        "ix_account_deletion_outbox_due",
        "account_deletion_outbox",
        ["status", "next_attempt_at"],
    )
    _isolate_table("account_deletion_outbox")


def downgrade() -> None:
    # The tombstone and outbox are intentionally removed only when the whole
    # revision is explicitly rolled back. Migration 0006's isolation remains
    # in force for the tables it owns.
    op.drop_index(
        "ix_account_deletion_outbox_due",
        table_name="account_deletion_outbox",
    )
    op.drop_table("account_deletion_outbox")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")
