from urllib.parse import quote

import pytest
from sqlalchemy.engine import make_url

from app.db.session import DatabaseConfigurationError, DatabaseSettings


LOCAL_DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/studyroom"


def _settings(**environment_values: str) -> DatabaseSettings:
    environment = {"DATABASE_URL": LOCAL_DATABASE_URL}
    environment.update(environment_values)
    return DatabaseSettings.from_environment(environ=environment)


def test_database_url_has_no_implicit_secret_default() -> None:
    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL is required"):
        DatabaseSettings.from_environment(environ={})


def test_local_database_url_gets_fixed_public_search_path_without_tls() -> None:
    settings = _settings(STUDYROOM_ENV="development")
    parsed = make_url(settings.url)

    assert parsed.query["options"] == "-csearch_path=public"
    assert "sslmode" not in parsed.query
    assert "sslrootcert" not in parsed.query


def test_ca_path_without_ssl_mode_selects_verify_full() -> None:
    settings = _settings(
        DATABASE_SSL_ROOT_CERT="/etc/secrets/supabase-ca.crt",
    )
    parsed = make_url(settings.url)

    assert parsed.query["sslmode"] == "verify-full"
    assert parsed.query["sslrootcert"] == "/etc/secrets/supabase-ca.crt"


def test_production_requires_verify_full_and_ca_path() -> None:
    with pytest.raises(DatabaseConfigurationError, match="Production PostgreSQL"):
        _settings(STUDYROOM_ENV="production")

    with pytest.raises(DatabaseConfigurationError, match="Production PostgreSQL"):
        _settings(
            STUDYROOM_ENV="production",
            DATABASE_SSL_MODE="require",
        )

    settings = _settings(
        STUDYROOM_ENV="production",
        DATABASE_SSL_MODE="verify-full",
        DATABASE_SSL_ROOT_CERT="/etc/secrets/supabase-ca.crt",
    )
    parsed = make_url(settings.url)
    assert parsed.query["options"] == "-csearch_path=public"
    assert parsed.query["sslmode"] == "verify-full"
    assert parsed.query["sslrootcert"] == "/etc/secrets/supabase-ca.crt"


@pytest.mark.parametrize(
    ("database_url", "environment_values", "message"),
    [
        (
            LOCAL_DATABASE_URL,
            {"DATABASE_SSL_MODE": "not-a-mode"},
            "DATABASE_SSL_MODE is not supported",
        ),
        (
            LOCAL_DATABASE_URL,
            {"DATABASE_SSL_MODE": "verify-full"},
            "CA path is required",
        ),
        (
            LOCAL_DATABASE_URL,
            {"DATABASE_SSL_ROOT_CERT": "relative-ca.crt"},
            "absolute path",
        ),
        (
            LOCAL_DATABASE_URL
            + "?sslrootcert="
            + quote("/etc/secrets/two.crt", safe=""),
            {
                "DATABASE_SSL_MODE": "verify-full",
                "DATABASE_SSL_ROOT_CERT": "/etc/secrets/one.crt",
            },
            "conflicts",
        ),
    ],
)
def test_malformed_tls_configuration_fails_without_connecting(
    database_url: str,
    environment_values: dict[str, str],
    message: str,
) -> None:
    environment = {"DATABASE_URL": database_url}
    environment.update(environment_values)

    with pytest.raises(DatabaseConfigurationError, match=message):
        DatabaseSettings.from_environment(environ=environment)


def test_non_public_search_path_is_rejected() -> None:
    unsafe_url = LOCAL_DATABASE_URL + "?options=-csearch_path%3Dother"

    with pytest.raises(DatabaseConfigurationError, match="search_path"):
        DatabaseSettings.from_environment(environ={"DATABASE_URL": unsafe_url})
