"""Add application users, UUID identities, and room ownership.

Revision ID: 0002_supabase_identity
Revises: 0001_initial
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_supabase_identity"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column(
        "rooms",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.drop_index(
        "uq_room_memberships_active_user",
        table_name="room_memberships",
    )
    op.drop_index(
        "uq_room_memberships_active_room_user",
        table_name="room_memberships",
    )
    op.alter_column(
        "room_memberships",
        "user_id",
        existing_type=sa.String(length=64),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="user_id::uuid",
    )
    op.drop_column("room_memberships", "display_name")

    op.create_foreign_key(
        "fk_rooms_owner_id_users",
        "rooms",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_room_memberships_user_id_users",
        "room_memberships",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column(
        "rooms",
        "owner_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
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

    op.add_column(
        "room_memberships",
        sa.Column("display_name", sa.String(length=40), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE room_memberships AS memberships
            SET display_name = users.display_name
            FROM users
            WHERE memberships.user_id = users.id
            """
        )
    )
    op.alter_column(
        "room_memberships",
        "display_name",
        existing_type=sa.String(length=40),
        nullable=False,
    )

    op.drop_constraint(
        "fk_room_memberships_user_id_users",
        "room_memberships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_rooms_owner_id_users",
        "rooms",
        type_="foreignkey",
    )
    op.alter_column(
        "room_memberships",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=64),
        postgresql_using="user_id::text",
    )
    op.drop_column("rooms", "owner_id")
    op.drop_table("users")

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
