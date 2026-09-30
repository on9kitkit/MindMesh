from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RoomLeaveOutcome:
    """Durable result of ending one member's active room membership."""

    room_id: UUID
    user_id: UUID
    left_at: datetime
    already_left: bool


@dataclass(frozen=True, slots=True)
class RoomCloseOutcome:
    """Durable result of closing a room and ending its active memberships."""

    room_id: UUID
    closed_at: datetime
    already_closed: bool
