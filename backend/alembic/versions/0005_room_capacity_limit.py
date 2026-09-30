"""Set the absolute room capacity limit to twenty.

Revision ID: 0005_room_capacity
Revises: 0004_room_lifecycle
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005_room_capacity"
down_revision: str | None = "0004_room_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    violating_room_exists = connection.scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM rooms WHERE maximum_members NOT BETWEEN 2 AND 20"
            ")"
        )
    )
    if violating_room_exists:
        raise RuntimeError(
            "Cannot enforce the twenty-member room limit while violating "
            "rooms exist."
        )

    op.drop_constraint(
        "ck_rooms_maximum_members",
        "rooms",
        type_="check",
    )
    op.create_check_constraint(
        "ck_rooms_maximum_members",
        "rooms",
        "maximum_members BETWEEN 2 AND 20",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_rooms_maximum_members",
        "rooms",
        type_="check",
    )
    op.create_check_constraint(
        "ck_rooms_maximum_members",
        "rooms",
        "maximum_members BETWEEN 2 AND 50",
    )
