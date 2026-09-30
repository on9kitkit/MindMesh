from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoomMembershipModel(Base):
    """SQLAlchemy representation of current and historical room membership."""

    __tablename__ = "room_memberships"
    __table_args__ = (
        CheckConstraint(
            "left_at IS NULL OR ready_at IS NULL",
            name="ck_room_memberships_ready_only_active",
        ),
        Index(
            "ix_room_memberships_active_room",
            "room_id",
            postgresql_where=text("left_at IS NULL"),
        ),
        Index(
            "uq_room_memberships_active_room_user",
            "room_id",
            "user_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        Index(
            "uq_room_memberships_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    room_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
