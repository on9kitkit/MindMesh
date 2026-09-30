from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuizSessionModel(Base):
    """Durable authoritative quiz session state."""

    __tablename__ = "quiz_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUESTION_OPEN', 'QUESTION_GRADING', 'QUESTION_REVEAL', 'FINISHED')",
            name="ck_quiz_sessions_status",
        ),
        CheckConstraint(
            "current_question_position >= 0",
            name="ck_quiz_sessions_question_position",
        ),
        CheckConstraint(
            "state_version >= 1",
            name="ck_quiz_sessions_state_version",
        ),
        CheckConstraint(
            "(status = 'FINISHED' AND finished_at IS NOT NULL) "
            "OR (status <> 'FINISHED' AND finished_at IS NULL)",
            name="ck_quiz_sessions_finished_at",
        ),
        CheckConstraint(
            """
            (
                quiz_mode = 'LEGACY_PHYSICS'
                AND preparation_id IS NULL
                AND education_level IS NULL
                AND quiz_subject IS NULL
                AND quiz_topic IS NULL
                AND total_available_marks = 5
            ) OR (
                quiz_mode = 'ADAPTIVE'
                AND preparation_id IS NOT NULL
                AND education_level = 'GCSE'
                AND quiz_subject IS NOT NULL
                AND quiz_topic IS NOT NULL
                AND total_available_marks BETWEEN 5 AND 40
            )
            """,
            name="ck_quiz_sessions_mode_configuration",
        ),
        Index(
            "uq_quiz_sessions_active_room",
            "room_id",
            unique=True,
            postgresql_where=text(
                "status IN ('QUESTION_OPEN', 'QUESTION_GRADING', 'QUESTION_REVEAL')"
            ),
        ),
        Index("ix_quiz_sessions_room_started_at", "room_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    room_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    preparation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quiz_preparations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    question_bank_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quiz_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=text("'LEGACY_PHYSICS'"),
    )
    education_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quiz_subject: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quiz_topic: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_available_marks: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("5"),
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    current_question_position: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("0"),
    )
    state_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    reveal_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
