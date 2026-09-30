from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import ForeignKeyConstraint

from app.db.base import Base


class AnswerSubmissionModel(Base):
    """Immutable answer and server-derived score for one participant."""

    __tablename__ = "answer_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "session_question_id"],
            ["session_questions.session_id", "session_questions.id"],
            name="fk_answer_submissions_session_question",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["session_id", "participant_id"],
            ["session_participants.session_id", "session_participants.id"],
            name="fk_answer_submissions_session_participant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "session_question_id",
            "participant_id",
            name="uq_answer_submissions_question_participant",
        ),
        CheckConstraint(
            "response_time_ms >= 0",
            name="ck_answer_submissions_response_time_ms",
        ),
        CheckConstraint(
            """
            (selected_option_id IS NOT NULL AND answer_text IS NULL)
            OR (selected_option_id IS NULL AND answer_text IS NOT NULL)
            """,
            name="ck_answer_submissions_input_present",
        ),
        CheckConstraint(
            "grading_status IN ('PENDING', 'IN_PROGRESS', 'RETRYABLE', 'UNAVAILABLE', 'GRADED')",
            name="ck_answer_submissions_grading_status",
        ),
        CheckConstraint(
            """
            grading_status = 'GRADED'
            OR (is_correct IS NULL AND points IS NULL AND earned_marks IS NULL AND graded_at IS NULL
                AND awarded_criterion_ids = '[]'::jsonb AND feedback = '{}'::jsonb)
            """,
            name="ck_answer_submissions_ungraded_nulls",
        ),
        CheckConstraint(
            """
            jsonb_typeof(awarded_criterion_ids) = 'array'
            AND jsonb_typeof(feedback) = 'object'
            """,
            name="ck_answer_submissions_feedback_json_types",
        ),
        CheckConstraint(
            """
            grading_status <> 'GRADED'
            OR (
                is_correct IS NOT NULL
                AND points IS NOT NULL
                AND earned_marks IS NOT NULL
                AND earned_marks BETWEEN 0 AND 6
                AND graded_at IS NOT NULL
            )
            """,
            name="ck_answer_submissions_graded_fields",
        ),
        CheckConstraint(
            "points IS NULL OR points IN (0, 100)",
            name="ck_answer_submissions_legacy_points_invariant",
        ),
        CheckConstraint(
            """
            points IS NULL
            OR ((is_correct AND points = 100) OR ((NOT is_correct) AND points = 0))
            """,
            name="ck_answer_submissions_legacy_correctness_points",
        ),
        CheckConstraint(
            "grading_method IN ('LEGACY_OPTION', 'DETERMINISTIC_OPTION', 'DETERMINISTIC_NUMERICAL', 'LUNA_RUBRIC')",
            name="ck_answer_submissions_grading_method",
        ),
        Index(
            "ix_answer_submissions_session_participant",
            "session_id",
            "participant_id",
        ),
        Index(
            "ix_answer_submissions_pending_grading",
            "grading_status",
            "next_attempt_at",
            postgresql_where=text("grading_status IN ('PENDING', 'RETRYABLE')"),
        ),
    )

    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("grading_status", "GRADED") == "GRADED":
            if kwargs.get("is_correct") is not None:
                if "earned_marks" not in kwargs or kwargs["earned_marks"] is None:
                    kwargs["earned_marks"] = 1 if kwargs["is_correct"] else 0
                if "graded_at" not in kwargs or kwargs["graded_at"] is None:
                    kwargs["graded_at"] = kwargs.get("submitted_at") or func.now()
        super().__init__(**kwargs)

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
    session_question_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    participant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    selected_option_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    answer_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    earned_marks: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    grading_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'LEGACY_OPTION'"),
    )
    grading_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=text("'GRADED'"),
    )
    attempt_cycle: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    attempt_count: Mapped[int] = mapped_column(
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
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    awarded_criterion_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    feedback: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
