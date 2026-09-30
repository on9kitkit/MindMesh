from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID


SUSPENSION_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"safety_review", "abuse_prevention", "policy_violation"}
)


@dataclass(frozen=True, slots=True)
class User:
    """StudyRoom-owned profile data for one verified auth identity."""

    id: UUID
    display_name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    suspended_at: datetime | None = None
    suspension_reason_code: str | None = None

    @property
    def is_deleted(self) -> bool:
        """Whether this row is the permanent local tombstone for the identity."""

        return self.deleted_at is not None

    @property
    def is_suspended(self) -> bool:
        """Whether normal StudyRoom actions are currently restricted."""

        return self.suspended_at is not None and not self.is_deleted
