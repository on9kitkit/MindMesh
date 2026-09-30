from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol, cast
from uuid import UUID

from app.domain.errors import (
    DuplicateJoinCodeError,
    DuplicateRoomIdError,
    NotRoomMemberError,
    RoomClosedError,
    RoomCreationError,
    RoomNotFoundError,
    RoomOwnerMustCloseError,
    RoomOwnerRequiredError,
)
from app.domain.member import RoomMember
from app.domain.room import Room
from app.domain.room_lifecycle import RoomCloseOutcome, RoomLeaveOutcome
from app.repositories.members import (
    LifecycleMembershipRepository,
    MembershipRepository,
)


class RoomRepository(Protocol):
    def add(self, room: Room) -> None:
        """Store a room or raise a duplicate constraint error."""

    def create_with_owner(self, room: Room, owner: RoomMember) -> None:
        """Persist a room and its owner membership atomically."""

    def get_by_id(self, room_id: UUID) -> Room | None:
        """Return a room by ID without exposing mutable repository state."""

    def get_by_join_code(self, join_code: str) -> Room | None:
        """Return a room by join code."""

    def leave_member(self, room_id: UUID, user_id: UUID) -> RoomLeaveOutcome:
        """Atomically end one non-owner membership when the room is inactive."""

    def close_room(self, room_id: UUID, owner_id: UUID) -> RoomCloseOutcome:
        """Atomically close a room and end every active membership."""

    def clear(self) -> None:
        """Remove all rooms, primarily for deterministic tests."""


class InMemoryRoomRepository:
    """Process-local room storage with ID and join-code uniqueness."""

    def __init__(self) -> None:
        self._rooms_by_id: dict[UUID, Room] = {}
        self._room_ids_by_join_code: dict[str, UUID] = {}
        self._membership_repository: LifecycleMembershipRepository | None = None

    def bind_membership_repository(
        self,
        membership_repository: MembershipRepository,
    ) -> None:
        self._membership_repository = cast(
            LifecycleMembershipRepository,
            membership_repository,
        )

    def add(self, room: Room) -> None:
        if room.id in self._rooms_by_id:
            raise DuplicateRoomIdError
        if room.join_code in self._room_ids_by_join_code:
            raise DuplicateJoinCodeError

        self._rooms_by_id[room.id] = room
        self._room_ids_by_join_code[room.join_code] = room.id

    def create_with_owner(self, room: Room, owner: RoomMember) -> None:
        if self._membership_repository is None:
            raise RoomCreationError
        self.add(room)
        try:
            self._membership_repository.join(owner, room.maximum_members)
        except Exception:
            self._rooms_by_id.pop(room.id, None)
            self._room_ids_by_join_code.pop(room.join_code, None)
            raise

    def get_by_id(self, room_id: UUID) -> Room | None:
        return self._rooms_by_id.get(room_id)

    def get_by_join_code(self, join_code: str) -> Room | None:
        room_id = self._room_ids_by_join_code.get(join_code)
        if room_id is None:
            return None
        return self._rooms_by_id.get(room_id)

    def leave_member(self, room_id: UUID, user_id: UUID) -> RoomLeaveOutcome:
        room = self.get_by_id(room_id)
        if room is None:
            raise RoomNotFoundError
        if room.owner_id == user_id:
            raise RoomOwnerMustCloseError
        memberships = self._require_memberships()
        if not memberships.has_membership_history(room_id, user_id):
            raise NotRoomMemberError

        active = memberships.get_by_room_and_user(room_id, user_id)
        if active is None:
            left_at = memberships.latest_left_at(room_id, user_id)
            if left_at is None:
                raise NotRoomMemberError
            return RoomLeaveOutcome(room_id, user_id, left_at, True)
        if room.is_closed:
            raise RoomClosedError

        left_at = datetime.now(timezone.utc)
        if not memberships.end_active_membership(room_id, user_id, left_at):
            raise NotRoomMemberError
        return RoomLeaveOutcome(room_id, user_id, left_at, False)

    def close_room(self, room_id: UUID, owner_id: UUID) -> RoomCloseOutcome:
        room = self.get_by_id(room_id)
        if room is None:
            raise RoomNotFoundError
        if room.owner_id != owner_id:
            raise RoomOwnerRequiredError
        if room.closed_at is not None:
            return RoomCloseOutcome(room_id, room.closed_at, True)

        closed_at = datetime.now(timezone.utc)
        self._rooms_by_id[room_id] = replace(room, closed_at=closed_at)
        self._require_memberships().end_all_active_memberships(
            room_id,
            closed_at,
        )
        return RoomCloseOutcome(room_id, closed_at, False)

    def _require_memberships(self) -> LifecycleMembershipRepository:
        if self._membership_repository is None:
            raise RoomCreationError
        return self._membership_repository

    def clear(self) -> None:
        self._rooms_by_id.clear()
        self._room_ids_by_join_code.clear()
