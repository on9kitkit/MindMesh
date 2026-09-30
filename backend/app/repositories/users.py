from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from app.domain.errors import AccountDeletedError, AccountSuspendedError, UserNotFoundError
from app.domain.display_name import normalize_display_name
from app.domain.user import SUSPENSION_REASON_CODES, User


def validate_suspension_reason_code(reason_code: str) -> str:
    if reason_code not in SUSPENSION_REASON_CODES:
        raise ValueError("unsupported suspension reason")
    return reason_code


class UserRepository(Protocol):
    def get_by_id(self, user_id: UUID) -> User | None:
        """Return an application profile by its verified auth UUID."""

    def upsert_profile(self, user_id: UUID, display_name: str) -> User:
        """Create or update the StudyRoom-owned profile."""

    def suspend(self, user_id: UUID, reason_code: str) -> User:
        """Suspend an existing non-deleted profile idempotently."""

    def unsuspend(self, user_id: UUID) -> User:
        """Remove suspension from an existing non-deleted profile idempotently."""

    def clear(self) -> None:
        """Remove profiles; intended for isolated tests only."""


class InMemoryUserRepository:
    """Process-local user profiles for isolated API tests."""

    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    def upsert_profile(self, user_id: UUID, display_name: str) -> User:
        display_name = normalize_display_name(display_name)
        now = datetime.now(timezone.utc)
        existing = self._users.get(user_id)
        if existing is not None and existing.is_suspended:
            raise AccountSuspendedError
        user = User(
            id=user_id,
            display_name=display_name,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            deleted_at=None if existing is None else existing.deleted_at,
            suspended_at=None if existing is None else existing.suspended_at,
            suspension_reason_code=(
                None if existing is None else existing.suspension_reason_code
            ),
        )
        if user.is_deleted:
            raise AccountDeletedError
        self._users[user_id] = user
        return user

    def suspend(self, user_id: UUID, reason_code: str) -> User:
        reason_code = validate_suspension_reason_code(reason_code)
        existing = self._users.get(user_id)
        if existing is None:
            raise UserNotFoundError
        if existing.is_deleted:
            raise AccountDeletedError
        if (
            existing.suspended_at is not None
            and existing.suspension_reason_code == reason_code
        ):
            return existing
        now = datetime.now(timezone.utc)
        updated = User(
            id=existing.id,
            display_name=existing.display_name,
            created_at=existing.created_at,
            updated_at=now,
            deleted_at=existing.deleted_at,
            suspended_at=existing.suspended_at or now,
            suspension_reason_code=reason_code,
        )
        self._users[user_id] = updated
        return updated

    def unsuspend(self, user_id: UUID) -> User:
        existing = self._users.get(user_id)
        if existing is None:
            raise UserNotFoundError
        if existing.is_deleted:
            raise AccountDeletedError
        if existing.suspended_at is None:
            return existing
        updated = User(
            id=existing.id,
            display_name=existing.display_name,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
            deleted_at=existing.deleted_at,
        )
        self._users[user_id] = updated
        return updated

    def clear(self) -> None:
        self._users.clear()
