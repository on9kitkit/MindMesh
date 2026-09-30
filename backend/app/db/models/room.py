from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.constants import ROOM_MAXIMUM_MEMBERS, ROOM_MINIMUM_MEMBERS


class RoomModel(Base):
    """SQLAlchemy representation of durable room configuration."""

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("join_code", name="uq_rooms_join_code"),
        CheckConstraint(
            (
                "maximum_members BETWEEN "
                f"{ROOM_MINIMUM_MEMBERS} AND {ROOM_MAXIMUM_MEMBERS}"
            ),
            name="ck_rooms_maximum_members",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= created_at",
            name="ck_rooms_closed_at_not_before_created_at",
        ),
        CheckConstraint(
            "quiz_mode IN ('LEGACY_PHYSICS', 'ADAPTIVE')",
            name="ck_rooms_quiz_mode",
        ),
        CheckConstraint(
            """
            (
                quiz_mode = 'LEGACY_PHYSICS'
                AND education_level IS NULL
                AND quiz_subject IS NULL
                AND quiz_topic IS NULL
                AND target_total_marks IS NULL
            ) OR (
                quiz_mode = 'ADAPTIVE'
                AND education_level = 'GCSE'
                AND target_total_marks BETWEEN 5 AND 40
                AND (
                    (quiz_subject = 'physics' AND quiz_topic IN ('energy', 'electricity', 'forces'))
                    OR (quiz_subject = 'mathematics' AND quiz_topic IN ('number', 'algebra', 'geometry'))
                    OR (quiz_subject = 'biology' AND quiz_topic IN ('cells', 'organisation', 'ecology'))
                    OR (quiz_subject = 'chemistry' AND quiz_topic IN ('atomic_structure', 'bonding', 'chemical_reactions'))
                    OR (quiz_subject = 'english_language' AND quiz_topic IN ('reading_comprehension', 'language_analysis', 'writing_techniques'))
                    OR (quiz_subject = 'english_literature' AND quiz_topic IN ('literary_devices', 'character_and_theme', 'poetry_analysis'))
                )
            )
            """,
            name="ck_rooms_adaptive_configuration",
        ),
        Index("ix_rooms_closed_at", "closed_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    join_code: Mapped[str] = mapped_column(String(6), nullable=False)
    maximum_members: Mapped[int] = mapped_column(Integer, nullable=False)
    quiz_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=text("'LEGACY_PHYSICS'"),
    )
    education_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quiz_subject: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quiz_topic: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_total_marks: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
