from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionParticipantModel(Base):
    """Session-local participant identity and display snapshot."""

    __tablename__ = "session_participants"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "user_id",
            name="uq_session_participants_session_user",
        ),
        UniqueConstraint(
            "session_id",
            "room_membership_id",
            name="uq_session_participants_session_membership",
        ),
        Index("ix_session_participants_session", "session_id"),
        UniqueConstraint("session_id", "id", name="uq_session_participants_session_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quiz_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    room_membership_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("room_memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_name_snapshot: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
