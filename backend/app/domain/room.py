from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Room:
    """Immutable room state owned by the room service."""

    id: UUID
    owner_id: UUID
    name: str
    join_code: str
    maximum_members: int
    closed_at: datetime | None = None
    quiz_mode: str = "LEGACY_PHYSICS"
    education_level: str | None = None
    quiz_subject: str | None = None
    quiz_topic: str | None = None
    target_total_marks: int | None = None
    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None
