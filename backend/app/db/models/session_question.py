from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionQuestionModel(Base):
    """Immutable question snapshot attached to one quiz session."""

    __tablename__ = "session_questions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "position",
            name="uq_session_questions_session_position",
        ),
        UniqueConstraint(
            "session_id",
            "source_question_id",
            name="uq_session_questions_session_source",
        ),
        UniqueConstraint("session_id", "id", name="uq_session_questions_session_id"),
        CheckConstraint("position >= 0", name="ck_session_questions_position"),
        CheckConstraint(
            "duration_seconds BETWEEN 5 AND 180",
            name="ck_session_questions_duration_seconds",
        ),
        CheckConstraint(
            "(opened_at IS NULL AND closes_at IS NULL) "
            "OR (opened_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND closes_at > opened_at)",
            name="ck_session_questions_open_close_consistency",
        ),
        CheckConstraint(
            """
            (source_question_id IS NOT NULL AND generated_question_id IS NULL)
            OR (source_question_id IS NULL AND generated_question_id IS NOT NULL)
            """,
            name="ck_session_questions_exactly_one_source",
        ),
        CheckConstraint(
            """
            (
                question_type = 'MULTIPLE_CHOICE'
                AND max_marks = 1
                AND correct_option_id IS NOT NULL
            ) OR (
                question_type IN ('NUMERICAL', 'WRITTEN')
                AND correct_option_id IS NULL
            )
            """,
            name="ck_session_questions_type_consistency",
        ),
        Index("ix_session_questions_session", "session_id"),
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
    source_question_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    generated_question_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("generated_quiz_questions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=text("'MULTIPLE_CHOICE'"),
    )
    max_marks: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("1"),
    )
    prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    options_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
    )
    correct_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grading_rubric_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    worked_explanation_snapshot: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )
    original_extract: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text("''"),
    )
    duration_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
