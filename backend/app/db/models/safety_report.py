from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SafetyReportModel(Base):
    """Minimal server-side safety report evidence."""

    __tablename__ = "safety_reports"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('inappropriate_display_name', "
            "'disruptive_room_behaviour', 'other_safety_concern')",
            name="ck_safety_reports_reason",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'RESOLVED', 'DISMISSED')",
            name="ck_safety_reports_status",
        ),
        CheckConstraint(
            "details IS NULL OR char_length(details) <= 500",
            name="ck_safety_reports_details_length",
        ),
        Index("ix_safety_reports_reporter", "reporter_user_id"),
        Index("ix_safety_reports_reported", "reported_user_id"),
        Index("ix_safety_reports_room_created", "room_id", "created_at"),
        Index("ix_safety_reports_status_created", "status", "created_at"),
        Index(
            "uq_safety_reports_open_duplicate",
            "reporter_user_id",
            "reported_user_id",
            "room_id",
            "reason",
            unique=True,
            postgresql_where=text(
                "status = 'OPEN' AND reporter_user_id IS NOT NULL "
                "AND reported_user_id IS NOT NULL AND room_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    reporter_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reported_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    room_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="SET NULL"),
        nullable=True,
    )
    reported_display_name_snapshot: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'OPEN'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
