from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from app.domain.errors import (
    DuplicateMembershipError,
    RoomFullError,
    UserAlreadyInAnotherRoomError,
)
from app.domain.member import RoomMember


class MembershipRepository(Protocol):
    def add(self, member: RoomMember) -> None:
        """Store a membership or raise a duplicate constraint error."""

    def join(self, member: RoomMember, maximum_members: int) -> None:
        """Atomically add an active membership under room capacity rules."""

    def list_by_room(self, room_id: UUID) -> tuple[RoomMember, ...]:
        """Return an immutable snapshot of a room's memberships."""

    def get_by_room_and_user(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> RoomMember | None:
        """Return a membership for a room/user pair, if present."""

    def get_active_room_for_user(self, user_id: UUID) -> UUID | None:
        """Return the user's active room, if one exists."""

    def count_by_room(self, room_id: UUID) -> int:
        """Count memberships from stored records."""

    def count_active_by_room(self, room_id: UUID) -> int:
        """Count active memberships from stored records."""

    def clear(self) -> None:
        """Remove all memberships, primarily for deterministic tests."""


class LifecycleMembershipRepository(MembershipRepository, Protocol):
    """Extra mutation surface used by the in-memory room aggregate seam."""

    def has_membership_history(self, room_id: UUID, user_id: UUID) -> bool:
        """Return whether any current or ended membership exists."""

    def latest_left_at(self, room_id: UUID, user_id: UUID) -> datetime | None:
        """Return the latest ended membership timestamp, if one exists."""

    def end_active_membership(
        self,
        room_id: UUID,
        user_id: UUID,
        ended_at: datetime,
    ) -> bool:
        """End one active membership without deleting its history."""

    def end_all_active_memberships(
        self,
        room_id: UUID,
        ended_at: datetime,
    ) -> tuple[UUID, ...]:
        """End all active room memberships and return affected user IDs."""


@dataclass(slots=True)
class _StoredMembership:
    member: RoomMember
    joined_at: datetime
    left_at: datetime | None = None


class InMemoryMembershipRepository:
    """Process-local authoritative membership storage."""

    def __init__(self) -> None:
        self._memberships: list[_StoredMembership] = []

    def add(self, member: RoomMember) -> None:
        if self.get_by_room_and_user(member.room_id, member.user_id) is not None:
            raise DuplicateMembershipError
        self._memberships.append(
            _StoredMembership(
                member=member,
                joined_at=datetime.now(timezone.utc),
            )
        )

    def join(self, member: RoomMember, maximum_members: int) -> None:
        if self.get_by_room_and_user(member.room_id, member.user_id) is not None:
            raise DuplicateMembershipError
        existing_room_id = self.get_active_room_for_user(member.user_id)
        if existing_room_id is not None and existing_room_id != member.room_id:
            raise UserAlreadyInAnotherRoomError
        if self.count_active_by_room(member.room_id) >= maximum_members:
            raise RoomFullError
        self.add(member)

    def list_by_room(self, room_id: UUID) -> tuple[RoomMember, ...]:
        return tuple(
            stored.member
            for stored in self._memberships
            if stored.member.room_id == room_id and stored.left_at is None
        )

    def get_by_room_and_user(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> RoomMember | None:
        return next(
            (
                stored.member
                for stored in reversed(self._memberships)
                if stored.member.room_id == room_id
                and stored.member.user_id == user_id
                and stored.left_at is None
            ),
            None,
        )

    def get_active_room_for_user(self, user_id: UUID) -> UUID | None:
        for stored in reversed(self._memberships):
            if stored.member.user_id == user_id and stored.left_at is None:
                return stored.member.room_id
        return None

    def get_room_for_user(self, user_id: UUID) -> UUID | None:
        """Backward-compatible alias for the active-room lookup."""

        return self.get_active_room_for_user(user_id)

    def count_by_room(self, room_id: UUID) -> int:
        return self.count_active_by_room(room_id)

    def count_active_by_room(self, room_id: UUID) -> int:
        return sum(
            1
            for stored in self._memberships
            if stored.member.room_id == room_id and stored.left_at is None
        )

    def has_membership_history(self, room_id: UUID, user_id: UUID) -> bool:
        return any(
            stored.member.room_id == room_id and stored.member.user_id == user_id
            for stored in self._memberships
        )

    def latest_left_at(self, room_id: UUID, user_id: UUID) -> datetime | None:
        for stored in reversed(self._memberships):
            if (
                stored.member.room_id == room_id
                and stored.member.user_id == user_id
                and stored.left_at is not None
            ):
                return stored.left_at
        return None

    def end_active_membership(
        self,
        room_id: UUID,
        user_id: UUID,
        ended_at: datetime,
    ) -> bool:
        for stored in reversed(self._memberships):
            if (
                stored.member.room_id == room_id
                and stored.member.user_id == user_id
                and stored.left_at is None
            ):
                stored.left_at = ended_at
                return True
        return False

    def end_all_active_memberships(
        self,
        room_id: UUID,
        ended_at: datetime,
    ) -> tuple[UUID, ...]:
        ended_user_ids: list[UUID] = []
        for stored in self._memberships:
            if stored.member.room_id == room_id and stored.left_at is None:
                stored.left_at = ended_at
                ended_user_ids.append(stored.member.user_id)
        return tuple(ended_user_ids)

    def clear(self) -> None:
        self._memberships.clear()
