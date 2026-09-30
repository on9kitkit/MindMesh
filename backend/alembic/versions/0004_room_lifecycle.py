"""Add durable room closure state.

Revision ID: 0004_room_lifecycle
Revises: 0003_authoritative_quiz
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004_room_lifecycle"
down_revision: str | None = "0003_authoritative_quiz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_rooms_closed_at_not_before_created_at",
        "rooms",
        "closed_at IS NULL OR closed_at >= created_at",
    )
    op.create_index("ix_rooms_closed_at", "rooms", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_rooms_closed_at", table_name="rooms")
    op.drop_constraint(
        "ck_rooms_closed_at_not_before_created_at",
        "rooms",
        type_="check",
    )
    op.drop_column("rooms", "closed_at")
