import pytest
from fastapi.testclient import TestClient

from app.auth import FakeAuthVerifier
from app.config import (
    LOCAL_DEVELOPMENT_ORIGINS,
    RuntimeConfigurationError,
    RuntimeSettings,
)
from app.main import create_app
from app.repositories.members import InMemoryMembershipRepository
from app.repositories.rooms import InMemoryRoomRepository
from app.repositories.users import InMemoryUserRepository


def test_development_runtime_keeps_the_exact_local_origin_contract() -> None:
    settings = RuntimeSettings.from_environment(
        {"STUDYROOM_ENV": "development"}
    )

    assert settings.allowed_http_origins == LOCAL_DEVELOPMENT_ORIGINS
    assert settings.allowed_websocket_origins == LOCAL_DEVELOPMENT_ORIGINS
    assert not settings.is_production


def test_production_requires_explicit_http_and_websocket_origins() -> None:
    with pytest.raises(RuntimeConfigurationError, match="ALLOWED_HTTP_ORIGINS"):
        RuntimeSettings.from_environment({"STUDYROOM_ENV": "production"})


def test_production_origins_are_explicit_and_normalised() -> None:
    settings = RuntimeSettings.from_environment(
        {
            "STUDYROOM_ENV": "production",
            "ALLOWED_HTTP_ORIGINS": "https://studyroom.example, https://studyroom.example/",
            "ALLOWED_WEBSOCKET_ORIGINS": (
                "https://studyroom.example,https://admin.studyroom.example"
            ),
        }
    )

    assert settings.allowed_http_origins == ("https://studyroom.example",)
    assert settings.allowed_websocket_origins == (
        "https://studyroom.example",
        "https://admin.studyroom.example",
    )
    assert settings.is_production


def test_app_uses_separate_configured_http_and_websocket_origins() -> None:
    settings = RuntimeSettings.from_environment(
        {
            "STUDYROOM_ENV": "production",
            "ALLOWED_HTTP_ORIGINS": "https://web.studyroom.example",
            "ALLOWED_WEBSOCKET_ORIGINS": "https://socket.studyroom.example",
        }
    )
    app = create_app(
        repository=InMemoryRoomRepository(),
        membership_repository=InMemoryMembershipRepository(),
        user_repository=InMemoryUserRepository(),
        auth_verifier=FakeAuthVerifier(),
        runtime_settings=settings,
    )

    with TestClient(app) as client:
        response = client.options(
            "/rooms",
            headers={
                "Origin": "https://web.studyroom.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.headers["access-control-allow-origin"] == (
        "https://web.studyroom.example"
    )
    assert app.state.websocket_allowed_origins == (
        "https://socket.studyroom.example",
    )


@pytest.mark.parametrize(
    "origins",
    (
        "*",
        "ws://studyroom.example",
        "http://studyroom.example",
        "https://studyroom.example/path",
        "https://user:password@studyroom.example",
        "https://studyroom.example?token=unexpected",
    ),
)
def test_origin_configuration_rejects_unsafe_or_non_origin_values(
    origins: str,
) -> None:
    with pytest.raises(RuntimeConfigurationError):
        RuntimeSettings.from_environment(
            {
                "STUDYROOM_ENV": "production",
                "ALLOWED_HTTP_ORIGINS": origins,
                "ALLOWED_WEBSOCKET_ORIGINS": "https://studyroom.example",
            }
        )
