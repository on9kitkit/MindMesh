from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuizPreparationModel(Base):
    """Durable lifecycle for adaptive quiz question generation."""

    __tablename__ = "quiz_preparations"
    __table_args__ = (
        UniqueConstraint(
            "room_id",
            "request_id",
            name="uq_quiz_preparations_room_request",
        ),
        CheckConstraint(
            "status IN ('GENERATING', 'READY', 'FAILED', 'CONSUMED', 'SUPERSEDED')",
            name="ck_quiz_preparations_status",
        ),
        CheckConstraint(
            "state_version >= 1",
            name="ck_quiz_preparations_state_version",
        ),
        CheckConstraint(
            "generation_attempt >= 1",
            name="ck_quiz_preparations_generation_attempt",
        ),
        CheckConstraint(
            "(status != 'READY') OR (verification_revision IS NOT NULL AND verified_content_digest IS NOT NULL)",
            name="ck_quiz_preparations_verification_proof",
        ),
        Index(
            "uq_quiz_preparations_active_room",
            "room_id",
            unique=True,
            postgresql_where=text("status IN ('GENERATING', 'READY')"),
        ),
        Index("ix_quiz_preparations_room_id", "room_id"),
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
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=text("'GENERATING'"),
    )
    state_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    generation_attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    claim_token: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verification_revision: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    verified_content_digest: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
