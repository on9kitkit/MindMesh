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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GeneratedQuizQuestionModel(Base):
    """Immutable definition of a generated quiz question attached to a preparation."""

    __tablename__ = "generated_quiz_questions"
    __table_args__ = (
        UniqueConstraint(
            "preparation_id",
            "position",
            name="uq_generated_quiz_questions_prep_position",
        ),
        UniqueConstraint(
            "preparation_id",
            "content_fingerprint",
            name="uq_generated_quiz_questions_prep_fingerprint",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_generated_quiz_questions_position",
        ),
        CheckConstraint(
            "question_type IN ('MULTIPLE_CHOICE', 'NUMERICAL', 'WRITTEN')",
            name="ck_generated_quiz_questions_type",
        ),
        CheckConstraint(
            "max_marks BETWEEN 1 AND 6",
            name="ck_generated_quiz_questions_max_marks",
        ),
        CheckConstraint(
            "duration_seconds BETWEEN 30 AND 180",
            name="ck_generated_quiz_questions_duration_seconds",
        ),
        CheckConstraint(
            "jsonb_typeof(grading_rubric) = 'object' AND length(trim(worked_explanation)) > 0",
            name="ck_generated_quiz_questions_rubric_explanation",
        ),
        CheckConstraint(
            """
            (
                question_type = 'MULTIPLE_CHOICE'
                AND max_marks = 1
                AND jsonb_typeof(options) = 'array'
                AND jsonb_array_length(options) BETWEEN 2 AND 6
                AND correct_option_id IS NOT NULL
            ) OR (
                question_type IN ('NUMERICAL', 'WRITTEN')
                AND jsonb_typeof(options) = 'array'
                AND jsonb_array_length(options) = 0
                AND correct_option_id IS NULL
            )
            """,
            name="ck_generated_quiz_questions_type_consistency",
        ),
        Index("ix_generated_quiz_questions_prep", "preparation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    preparation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quiz_preparations.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_type: Mapped[str] = mapped_column(String(24), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    max_marks: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    correct_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grading_rubric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    worked_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    original_extract: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
