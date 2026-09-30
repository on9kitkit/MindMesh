from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import Depends, Header, Request

from app.auth import AuthenticatedIdentity, AuthVerifier, require_bearer_token
from app.domain.errors import (
    AccountDeletedError,
    AccountSuspendedError,
    UserProfileRequiredError,
)
from app.domain.user import User
from app.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Verified auth identity plus its optional StudyRoom profile."""

    id: UUID
    profile: User | None
    authenticated_at: datetime | None = None

    @property
    def display_name(self) -> str:
        if self.profile is None:
            raise UserProfileRequiredError
        return self.profile.display_name


def get_auth_verifier(request: Request) -> AuthVerifier:
    return request.app.state.auth_verifier


def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.user_repository


def get_current_identity(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    return _resolve_current_identity(request, authorization, allow_suspended=False)


def get_current_identity_for_account_deletion(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """Allow the existing deletion contract to operate on suspended accounts."""

    return _resolve_current_identity(request, authorization, allow_suspended=True)


def _resolve_current_identity(
    request: Request,
    authorization: str | None,
    *,
    allow_suspended: bool,
) -> CurrentUser:
    token = require_bearer_token(authorization)
    identity: AuthenticatedIdentity = get_auth_verifier(request).verify(token)
    profile = get_user_repository(request).get_by_id(identity.user_id)
    if profile is not None and profile.is_deleted:
        raise AccountDeletedError
    if profile is not None and profile.is_suspended and not allow_suspended:
        raise AccountSuspendedError
    return CurrentUser(
        id=identity.user_id,
        profile=profile,
        authenticated_at=identity.authenticated_at,
    )


def get_current_user(
    current_identity: CurrentUser = Depends(get_current_identity),
) -> CurrentUser:
    """Require a verified identity with an application-owned profile."""

    if current_identity.profile is None:
        raise UserProfileRequiredError
    return current_identity


def get_current_user_for_account_deletion(
    current_identity: CurrentUser = Depends(
        get_current_identity_for_account_deletion
    ),
) -> CurrentUser:
    """Require a profile while preserving deletion for suspended users."""

    if current_identity.profile is None:
        raise UserProfileRequiredError
    return current_identity
