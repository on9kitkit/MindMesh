"""Create durable rooms and room memberships.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("join_code", sa.String(length=6), nullable=False),
        sa.Column("maximum_members", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "maximum_members BETWEEN 2 AND 50",
            name="ck_rooms_maximum_members",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("join_code", name="uq_rooms_join_code"),
    )
    op.create_table(
        "room_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name="fk_room_memberships_room_id_rooms",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_room_memberships_active_room",
        "room_memberships",
        ["room_id"],
        postgresql_where=sa.text("left_at IS NULL"),
    )
    op.create_index(
        "uq_room_memberships_active_room_user",
        "room_memberships",
        ["room_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("left_at IS NULL"),
    )
    op.create_index(
        "uq_room_memberships_active_user",
        "room_memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("left_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_room_memberships_active_user",
        table_name="room_memberships",
    )
    op.drop_index(
        "uq_room_memberships_active_room_user",
        table_name="room_memberships",
    )
    op.drop_index(
        "ix_room_memberships_active_room",
        table_name="room_memberships",
    )
    op.drop_table("room_memberships")
    op.drop_table("rooms")
