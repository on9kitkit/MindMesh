import re
import secrets
from collections.abc import Callable
from uuid import UUID, uuid4

from app.domain.constants import (
    FREE_ROOM_MAXIMUM_MEMBERS,
    ROOM_MAXIMUM_MEMBERS,
    ROOM_MINIMUM_MEMBERS,
)
from app.domain.errors import (
    AlreadyRoomMemberError,
    DuplicateMembershipError,
    DuplicateRoomIdError,
    InvalidRoomDataError,
    JoinCodeGenerationError,
    NotRoomMemberError,
    PremiumVerificationUnavailableError,
    ProRequiredError,
    RoomClosedError,
    RoomOwnerRequiredError,
    RoomNotFoundError,
)
from app.domain.adaptive_quiz import validate_subject_and_topic
from app.domain.member import RoomMember
from app.domain.room import Room
from app.domain.room_lifecycle import RoomCloseOutcome, RoomLeaveOutcome
from app.repositories.members import (
    InMemoryMembershipRepository,
    MembershipRepository,
)
from app.repositories.rooms import RoomRepository
from app.premium.verifier import PremiumEntitlementVerifier

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 6
JOIN_CODE_RETRY_LIMIT = 10
ROOM_ID_RETRY_LIMIT = 3
JOIN_CODE_PATTERN = re.compile(
    rf"^[{re.escape(JOIN_CODE_ALPHABET)}]{{{JOIN_CODE_LENGTH}}}$"
)


def generate_join_code() -> str:
    return "".join(
        secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH)
    )


class RoomService:
    def __init__(
        self,
        repository: RoomRepository,
        *,
        membership_repository: MembershipRepository | None = None,
        room_id_factory: Callable[[], UUID] = uuid4,
        join_code_factory: Callable[[], str] = generate_join_code,
        room_id_retry_limit: int = ROOM_ID_RETRY_LIMIT,
        join_code_retry_limit: int = JOIN_CODE_RETRY_LIMIT,
        premium_entitlement_verifier: PremiumEntitlementVerifier | None = None,
        premium_entitlement_lookup_key: str | None = None,
    ) -> None:
        if room_id_retry_limit < 1 or join_code_retry_limit < 1:
            raise ValueError("retry limits must be positive")

        self._repository = repository
        self._membership_repository = (
            membership_repository or InMemoryMembershipRepository()
        )
        bind_membership_repository = getattr(
            self._repository,
            "bind_membership_repository",
            None,
        )
        if callable(bind_membership_repository):
            bind_membership_repository(self._membership_repository)
        self._room_id_factory = room_id_factory
        self._join_code_factory = join_code_factory
        self._room_id_retry_limit = room_id_retry_limit
        self._join_code_retry_limit = join_code_retry_limit
        self._premium_entitlement_verifier = premium_entitlement_verifier
        self._premium_entitlement_lookup_key = premium_entitlement_lookup_key

    def create_room(
        self,
        *,
        name: str,
        maximum_members: int,
        owner_id: UUID,
        owner_display_name: str,
        quiz_mode: str = "LEGACY_PHYSICS",
        education_level: str | None = None,
        quiz_subject: str | None = None,
        quiz_topic: str | None = None,
        target_total_marks: int | None = None,
    ) -> Room:
        normalized_name = name.strip()
        if not 3 <= len(normalized_name) <= 60:
            raise InvalidRoomDataError(
                "room name must contain between 3 and 60 characters"
            )
        if not ROOM_MINIMUM_MEMBERS <= maximum_members <= ROOM_MAXIMUM_MEMBERS:
            raise InvalidRoomDataError(
                "maximum_members must be between 2 and 20"
            )
        self._require_capacity_access(
            owner_id=owner_id,
            maximum_members=maximum_members,
        )
        if quiz_mode == "ADAPTIVE":
            if education_level != "GCSE":
                raise InvalidRoomDataError("education_level must be 'GCSE'")
            if not quiz_subject or not quiz_topic:
                raise InvalidRoomDataError("quiz_subject and quiz_topic are required for adaptive mode")
            try:
                norm_subject, norm_topic = validate_subject_and_topic(quiz_subject, quiz_topic)
            except ValueError as err:
                raise InvalidRoomDataError(str(err)) from err
            if target_total_marks is None or not (5 <= target_total_marks <= 40):
                raise InvalidRoomDataError("target_total_marks must be between 5 and 40")
            quiz_subject = norm_subject
            quiz_topic = norm_topic
        elif quiz_mode == "LEGACY_PHYSICS":
            education_level = None
            quiz_subject = None
            quiz_topic = None
            target_total_marks = None
        else:
            # Unknown modes are rejected, never silently mapped to legacy:
            # service authority must not turn typos into another product.
            raise InvalidRoomDataError(
                f"quiz_mode must be 'LEGACY_PHYSICS' or 'ADAPTIVE', got {quiz_mode!r}."
            )

        room_id = self._generate_unique_room_id()
        join_code = self._generate_unique_join_code()
        room = Room(
            id=room_id,
            owner_id=owner_id,
            name=normalized_name,
            join_code=join_code,
            maximum_members=maximum_members,
            quiz_mode=quiz_mode,
            education_level=education_level,
            quiz_subject=quiz_subject,
            quiz_topic=quiz_topic,
            target_total_marks=target_total_marks,
        )
        owner = RoomMember(
            user_id=owner_id,
            display_name=owner_display_name,
            room_id=room.id,
        )
        self._repository.create_with_owner(room, owner)
        return room

    def _require_capacity_access(
        self,
        *,
        owner_id: UUID,
        maximum_members: int,
    ) -> None:
        if maximum_members <= FREE_ROOM_MAXIMUM_MEMBERS:
            return
        verifier = self._premium_entitlement_verifier
        lookup_key = self._premium_entitlement_lookup_key
        if verifier is None or lookup_key is None:
            raise PremiumVerificationUnavailableError
        try:
            has_entitlement = verifier.has_entitlement(owner_id, lookup_key)
        except PremiumVerificationUnavailableError:
            raise
        except Exception:
            raise PremiumVerificationUnavailableError from None
        if not has_entitlement:
            raise ProRequiredError

    def get_room(self, room_id: UUID) -> Room:
        room = self._repository.get_by_id(room_id)
        if room is None:
            raise RoomNotFoundError
        return room

    def get_room_by_join_code(self, join_code: str) -> Room:
        normalized_code = normalize_join_code(join_code)
        room = self._repository.get_by_join_code(normalized_code)
        if room is None:
            raise RoomNotFoundError
        return room

    def get_open_room(self, room_id: UUID) -> Room:
        room = self.get_room(room_id)
        if room.is_closed:
            raise RoomClosedError
        return room

    def join_room(
        self,
        *,
        room_id: UUID,
        user_id: UUID,
        display_name: str,
    ) -> RoomMember:
        room = self.get_open_room(room_id)
        member = RoomMember(
            user_id=user_id,
            display_name=display_name,
            room_id=room_id,
        )
        try:
            self._membership_repository.join(member, room.maximum_members)
        except DuplicateMembershipError as error:
            raise AlreadyRoomMemberError from error
        return member

    def join_room_by_code(
        self,
        *,
        join_code: str,
        user_id: UUID,
        display_name: str,
    ) -> RoomMember:
        room = self.get_room_by_join_code(join_code)
        return self.join_room(
            room_id=room.id,
            user_id=user_id,
            display_name=display_name,
        )

    def require_active_room_member(
        self,
        *,
        room_id: UUID,
        user_id: UUID,
    ) -> RoomMember:
        self.get_open_room(room_id)
        member = self._membership_repository.get_by_room_and_user(
            room_id,
            user_id,
        )
        if member is None:
            raise NotRoomMemberError
        return member

    def get_active_room_for_user(self, user_id: UUID) -> Room | None:
        room_id = self._membership_repository.get_active_room_for_user(user_id)
        if room_id is None:
            return None
        room = self.get_room(room_id)
        return None if room.is_closed else room

    def require_room_owner(self, *, room_id: UUID, user_id: UUID) -> Room:
        room = self.get_room(room_id)
        if room.owner_id != user_id:
            raise RoomOwnerRequiredError
        return room

    def list_room_members(self, room_id: UUID) -> tuple[RoomMember, ...]:
        self.get_open_room(room_id)
        return self._membership_repository.list_by_room(room_id)

    def count_room_members(self, room_id: UUID) -> int:
        self.get_open_room(room_id)
        return self._membership_repository.count_active_by_room(room_id)

    def leave_room(self, *, room_id: UUID, user_id: UUID) -> RoomLeaveOutcome:
        return self._repository.leave_member(room_id, user_id)

    def close_room(self, *, room_id: UUID, user_id: UUID) -> RoomCloseOutcome:
        return self._repository.close_room(room_id, user_id)

    def _generate_unique_room_id(self) -> UUID:
        for _ in range(self._room_id_retry_limit):
            room_id = self._room_id_factory()
            if self._repository.get_by_id(room_id) is None:
                return room_id
        raise DuplicateRoomIdError

    def _generate_unique_join_code(self) -> str:
        for _ in range(self._join_code_retry_limit):
            join_code = self._join_code_factory()
            if not JOIN_CODE_PATTERN.fullmatch(join_code):
                continue
            if self._repository.get_by_join_code(join_code) is None:
                return join_code
        raise JoinCodeGenerationError


def normalize_join_code(join_code: str) -> str:
    normalized_code = join_code.strip().upper()
    if not JOIN_CODE_PATTERN.fullmatch(normalized_code):
        raise InvalidRoomDataError("join code must contain six letters or digits")
    return normalized_code
