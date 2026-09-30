from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    SECP256R1,
    generate_private_key,
)
import pytest

from app.auth import (
    FakeAuthVerifier,
    SupabaseAuthSettings,
    SupabaseJWKSAuthVerifier,
    require_bearer_token,
)
from app.domain.errors import (
    AuthenticationConfigurationError,
    AuthenticationRequiredError,
    InvalidAuthTokenError,
)


ISSUER = "https://project.supabase.co/auth/v1"
USER_ID = UUID("12345678-1234-4234-8234-123456789012")


class StaticSigningKey:
    algorithm_name = "ES256"

    def __init__(self, key: object) -> None:
        self.key = key


def _verifier(private_key: EllipticCurvePrivateKey) -> SupabaseJWKSAuthVerifier:
    verifier = SupabaseJWKSAuthVerifier(
        SupabaseAuthSettings(
            supabase_url="https://project.supabase.co",
            issuer=ISSUER,
            jwks_url="https://project.supabase.co/auth/v1/.well-known/jwks.json",
        )
    )
    verifier._jwks_client.get_signing_key_from_jwt = lambda token: StaticSigningKey(
        private_key.public_key()
    )
    return verifier


def _token(
    private_key: EllipticCurvePrivateKey,
    *,
    subject: str = str(USER_ID),
    issuer: str = ISSUER,
    expires_at: datetime | None = None,
    amr: list[dict[str, object]] | None = None,
) -> str:
    claims: dict[str, object] = {
        "sub": subject,
        "iss": issuer,
        "aud": "authenticated",
        "exp": expires_at
        or datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    if amr is not None:
        claims["amr"] = amr
    return jwt.encode(
        claims,
        private_key,
        algorithm="ES256",
    )


def test_supabase_settings_derive_issuer_and_jwks_url() -> None:
    settings = SupabaseAuthSettings.from_environment(
        {"SUPABASE_URL": "https://project.supabase.co/"}
    )

    assert settings.issuer == ISSUER
    assert settings.jwks_url.endswith("/auth/v1/.well-known/jwks.json")


def test_supabase_settings_reject_missing_or_invalid_url() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        SupabaseAuthSettings.from_environment({})
    with pytest.raises(AuthenticationConfigurationError):
        SupabaseAuthSettings.from_environment(
            {"SUPABASE_URL": "not-a-project-url"}
        )


def test_valid_signed_token_returns_uuid_from_verified_subject() -> None:
    private_key = generate_private_key(SECP256R1())

    identity = _verifier(private_key).verify(_token(private_key))

    assert identity.user_id == USER_ID


def test_valid_signed_token_exposes_only_genuine_recent_auth_method_timestamp() -> None:
    private_key = generate_private_key(SECP256R1())
    authenticated_at = datetime.now(timezone.utc) - timedelta(minutes=2)

    identity = _verifier(private_key).verify(
        _token(
            private_key,
            amr=[
                {
                    "method": "password",
                    "timestamp": authenticated_at.timestamp(),
                },
                {
                    "method": "token_refresh",
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
            ],
        )
    )

    assert identity.authenticated_at is not None
    assert abs(
        (identity.authenticated_at - authenticated_at).total_seconds()
    ) < 1


def test_expired_token_is_rejected() -> None:
    private_key = generate_private_key(SECP256R1())
    expired = _token(
        private_key,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    with pytest.raises(InvalidAuthTokenError):
        _verifier(private_key).verify(expired)


def test_wrong_issuer_token_is_rejected() -> None:
    private_key = generate_private_key(SECP256R1())

    with pytest.raises(InvalidAuthTokenError):
        _verifier(private_key).verify(
            _token(private_key, issuer="https://other.supabase.co/auth/v1")
        )


def test_wrong_signature_token_is_rejected() -> None:
    trusted_key = generate_private_key(SECP256R1())
    untrusted_key = generate_private_key(SECP256R1())

    with pytest.raises(InvalidAuthTokenError):
        _verifier(trusted_key).verify(_token(untrusted_key))


def test_fake_verifier_is_deterministic_and_rejects_unknown_token() -> None:
    verifier = FakeAuthVerifier({"known": USER_ID})

    assert verifier.verify("known").user_id == USER_ID
    with pytest.raises(InvalidAuthTokenError):
        verifier.verify("unknown")


def test_bearer_extraction_distinguishes_missing_and_malformed_headers() -> None:
    with pytest.raises(AuthenticationRequiredError):
        require_bearer_token(None)
    with pytest.raises(InvalidAuthTokenError):
        require_bearer_token("Basic token")
    with pytest.raises(InvalidAuthTokenError):
        require_bearer_token("Bearer")
    assert require_bearer_token("bearer token-value") == "token-value"
