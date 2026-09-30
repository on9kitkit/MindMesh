from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuestionModel(Base):
    """Canonical question bank content."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint(
            "bank_key",
            "stable_key",
            name="uq_questions_bank_stable_key",
        ),
        UniqueConstraint(
            "bank_key",
            "position",
            name="uq_questions_bank_position",
        ),
        CheckConstraint("position >= 0", name="ck_questions_position"),
        CheckConstraint(
            "duration_seconds BETWEEN 5 AND 120",
            name="ck_questions_duration_seconds",
        ),
        CheckConstraint(
            "jsonb_typeof(options) = 'array' "
            "AND jsonb_array_length(options) BETWEEN 2 AND 6",
            name="ck_questions_options_array_length",
        ),
        Index(
            "ix_questions_active_bank_position",
            "bank_key",
            "is_active",
            "position",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    bank_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    correct_option_id: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
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
