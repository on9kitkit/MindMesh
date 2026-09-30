from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserModel(Base):
    """SQLAlchemy representation of a StudyRoom application profile."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "suspension_reason_code IS NULL OR suspension_reason_code IN "
            "('safety_review', 'abuse_prevention', 'policy_violation')",
            name="ck_users_suspension_reason_code",
        ),
        Index("ix_users_deleted_at", "deleted_at"),
        Index("ix_users_suspended_at", "suspended_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
    )
    display_name: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    suspension_reason_code: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
