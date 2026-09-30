from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import urljoin, urlparse
from uuid import UUID

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.domain.errors import (
    AuthenticationConfigurationError,
    AuthenticationRequiredError,
    InvalidAuthTokenError,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Identity claims that are safe to use after token verification."""

    user_id: UUID
    expires_at: datetime | None = None
    authenticated_at: datetime | None = None


class AuthVerifier(Protocol):
    def verify(self, token: str) -> AuthenticatedIdentity:
        """Verify a bearer token and return its server-trusted identity."""


@dataclass(frozen=True, slots=True)
class SupabaseAuthSettings:
    """Public Supabase project endpoints used for JWT verification."""

    supabase_url: str
    issuer: str
    jwks_url: str
    audience: str = "authenticated"

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "SupabaseAuthSettings":
        environment = os.environ if environ is None else environ
        raw_url = environment.get("SUPABASE_URL", "").strip().rstrip("/")
        if not raw_url:
            raise AuthenticationConfigurationError(
                "SUPABASE_URL is required for JWT verification."
            )

        parsed_url = urlparse(raw_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise AuthenticationConfigurationError(
                "SUPABASE_URL must be an absolute HTTP or HTTPS URL."
            )

        issuer = urljoin(f"{raw_url}/", "auth/v1")
        return cls(
            supabase_url=raw_url,
            issuer=issuer,
            jwks_url=f"{issuer}/.well-known/jwks.json",
        )


class SupabaseJWKSAuthVerifier:
    """Verify Supabase access JWTs using the project's cached public JWKS."""

    def __init__(self, settings: SupabaseAuthSettings) -> None:
        self._settings = settings
        self._jwks_client = PyJWKClient(settings.jwks_url)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "SupabaseJWKSAuthVerifier":
        return cls(SupabaseAuthSettings.from_environment(environ))

    def verify(self, token: str) -> AuthenticatedIdentity:
        if not token.strip() or any(character.isspace() for character in token):
            raise InvalidAuthTokenError

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            algorithm = signing_key.algorithm_name
            if algorithm not in {"ES256", "RS256"}:
                raise InvalidAuthTokenError

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={
                    "require": ["exp", "iss", "sub"],
                    "verify_exp": True,
                    "verify_iss": True,
                },
            )
        except InvalidAuthTokenError:
            raise
        except (PyJWTError, ValueError, TypeError) as error:
            raise InvalidAuthTokenError from error
        except Exception as error:
            # Network and key-fetch failures must not leak implementation details
            # or become unauthenticated requests.
            raise InvalidAuthTokenError from error

        raw_subject = claims.get("sub")
        if not isinstance(raw_subject, str):
            raise InvalidAuthTokenError
        raw_expiry = claims.get("exp")
        if isinstance(raw_expiry, bool) or not isinstance(raw_expiry, (int, float)):
            raise InvalidAuthTokenError
        try:
            user_id = UUID(raw_subject)
            expires_at = datetime.fromtimestamp(raw_expiry, tz=timezone.utc)
        except (ValueError, OverflowError, OSError) as error:
            raise InvalidAuthTokenError from error
        return AuthenticatedIdentity(
            user_id=user_id,
            expires_at=expires_at,
            authenticated_at=_latest_authentication_at(claims.get("amr")),
        )


class FakeAuthVerifier:
    """Deterministic verifier used by backend tests without Supabase network calls."""

    def __init__(self, identities: Mapping[str, UUID] | None = None) -> None:
        self._identities = dict(identities or {})
        self._expires_at: dict[str, datetime | None] = {}
        self._authenticated_at: dict[str, datetime | None] = {}

    def register(
        self,
        token: str,
        user_id: UUID,
        *,
        expires_at: datetime | None = None,
        authenticated_at: datetime | None = None,
    ) -> None:
        self._identities[token] = user_id
        self._expires_at[token] = expires_at
        self._authenticated_at[token] = authenticated_at

    def verify(self, token: str) -> AuthenticatedIdentity:
        user_id = self._identities.get(token)
        if user_id is None:
            raise InvalidAuthTokenError
        expires_at = self._expires_at.get(token)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise InvalidAuthTokenError
        return AuthenticatedIdentity(
            user_id=user_id,
            expires_at=expires_at,
            authenticated_at=self._authenticated_at.get(token),
        )


def require_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise AuthenticationRequiredError
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise InvalidAuthTokenError
    return parts[1]


# These are the authentication methods currently used by StudyRoom's native
# email/password flow. Refresh events are deliberately excluded: a refreshed
# access token must not turn an old sign-in into recent-auth proof.
_RECENT_AUTH_METHODS = frozenset({"password", "email/signup"})


def _latest_authentication_at(raw_amr: object) -> datetime | None:
    if not isinstance(raw_amr, list):
        return None

    latest: datetime | None = None
    for entry in raw_amr:
        if not isinstance(entry, dict):
            continue
        method = entry.get("method")
        timestamp = entry.get("timestamp")
        if method not in _RECENT_AUTH_METHODS:
            continue
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            continue
        if not math.isfinite(float(timestamp)):
            continue
        try:
            candidate = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        if latest is None or candidate > latest:
            latest = candidate
    return latest
