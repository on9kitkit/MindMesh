"""Add reversible minimal account suspension state."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_account_suspension"
down_revision: str | None = "0008_safety_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("suspension_reason_code", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_suspension_reason_code",
        "users",
        "suspension_reason_code IS NULL OR suspension_reason_code IN "
        "('safety_review', 'abuse_prevention', 'policy_violation')",
    )
    op.create_index("ix_users_suspended_at", "users", ["suspended_at"])


def downgrade() -> None:
    op.drop_index("ix_users_suspended_at", table_name="users")
    op.drop_constraint(
        "ck_users_suspension_reason_code",
        "users",
        type_="check",
    )
    op.drop_column("users", "suspension_reason_code")
    op.drop_column("users", "suspended_at")
