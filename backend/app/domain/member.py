from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RoomMember:
    """Immutable membership record for one user in one room."""

    user_id: UUID
    display_name: str
    room_id: UUID
