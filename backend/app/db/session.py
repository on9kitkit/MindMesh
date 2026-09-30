from collections.abc import Mapping
from dataclasses import dataclass
import os

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(RuntimeError):
    """Raised when PostgreSQL configuration is missing or unusable."""


PUBLIC_SEARCH_PATH_OPTION = "-csearch_path=public"
_SUPPORTED_SSL_MODES = {
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
}


def _query_value(query: Mapping[str, object], key: str) -> str | None:
    value = query.get(key)
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        if len(value) != 1:
            raise DatabaseConfigurationError(
                f"Database URL query parameter {key} must have one value."
            )
        value = value[0]
    if not isinstance(value, str):
        raise DatabaseConfigurationError(
            f"Database URL query parameter {key} must be text."
        )
    return value.strip() or None


def _environment_value(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name, "").strip()
    return value or None


def _matching_setting(
    *,
    query_value: str | None,
    environment_value: str | None,
    name: str,
) -> str | None:
    if (
        query_value is not None
        and environment_value is not None
        and query_value != environment_value
    ):
        raise DatabaseConfigurationError(
            f"{name} conflicts between the database URL and environment."
        )
    return environment_value or query_value


def _normalise_database_url(
    parsed_url: URL,
    *,
    environment: Mapping[str, str],
) -> str:
    query = dict(parsed_url.query)
    existing_options = _query_value(query, "options")
    if existing_options is not None and " ".join(existing_options.split()) not in {
        PUBLIC_SEARCH_PATH_OPTION,
        "-c search_path=public",
    }:
        raise DatabaseConfigurationError(
            "DATABASE_URL options must pin search_path to public."
        )
    if _query_value(query, "search_path") is not None:
        raise DatabaseConfigurationError(
            "DATABASE_URL must use the fixed public search_path option."
        )

    ssl_mode = _matching_setting(
        query_value=_query_value(query, "sslmode"),
        environment_value=_environment_value(environment, "DATABASE_SSL_MODE"),
        name="DATABASE_SSL_MODE",
    )
    ssl_root_cert = _matching_setting(
        query_value=_query_value(query, "sslrootcert"),
        environment_value=_environment_value(
            environment,
            "DATABASE_SSL_ROOT_CERT",
        ),
        name="DATABASE_SSL_ROOT_CERT",
    )
    if ssl_mode is not None and ssl_mode not in _SUPPORTED_SSL_MODES:
        raise DatabaseConfigurationError("DATABASE_SSL_MODE is not supported.")
    if ssl_root_cert is not None and not os.path.isabs(ssl_root_cert):
        raise DatabaseConfigurationError(
            "DATABASE_SSL_ROOT_CERT must be an absolute path."
        )
    if ssl_root_cert is not None and ssl_mode is None:
        ssl_mode = "verify-full"
    if ssl_mode in {"verify-ca", "verify-full"} and ssl_root_cert is None:
        raise DatabaseConfigurationError(
            "A CA path is required for certificate-verifying PostgreSQL TLS."
        )

    environment_name = environment.get("STUDYROOM_ENV", "development").strip().lower()
    if environment_name == "production" and (
        ssl_mode != "verify-full" or ssl_root_cert is None
    ):
        raise DatabaseConfigurationError(
            "Production PostgreSQL requires sslmode=verify-full and a CA path."
        )

    query["options"] = PUBLIC_SEARCH_PATH_OPTION
    if ssl_mode is not None:
        query["sslmode"] = ssl_mode
    if ssl_root_cert is not None:
        query["sslrootcert"] = ssl_root_cert
    return parsed_url.set(query=query).render_as_string(hide_password=False)


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Validated database connection settings without exposing credentials."""

    url: str

    @classmethod
    def from_environment(
        cls,
        variable_name: str = "DATABASE_URL",
        environ: Mapping[str, str] | None = None,
    ) -> "DatabaseSettings":
        environment = os.environ if environ is None else environ
        raw_url = environment.get(variable_name, "").strip()
        if not raw_url:
            raise DatabaseConfigurationError(
                f"{variable_name} is required for PostgreSQL mode."
            )

        try:
            parsed_url = make_url(raw_url)
        except Exception as error:
            raise DatabaseConfigurationError(
                f"{variable_name} is not a valid PostgreSQL URL."
            ) from error

        if parsed_url.drivername != "postgresql+psycopg":
            raise DatabaseConfigurationError(
                f"{variable_name} must use the postgresql+psycopg driver."
            )
        if not parsed_url.host or not parsed_url.database:
            raise DatabaseConfigurationError(
                f"{variable_name} must include a PostgreSQL host and database."
            )

        return cls(
            url=_normalise_database_url(parsed_url, environment=environment)
        )


class Database:
    """Owns the SQLAlchemy engine and session factory lifecycle."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    @classmethod
    def from_url(cls, database_url: str) -> "Database":
        environment = dict(os.environ)
        environment["DATABASE_URL"] = database_url
        settings = DatabaseSettings.from_environment(environ=environment)
        engine = create_engine(
            settings.url,
            pool_pre_ping=True,
        )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as error:
            engine.dispose()
            raise DatabaseConfigurationError(
                "Unable to connect to the configured PostgreSQL database."
            ) from error
        return cls(engine)

    @classmethod
    def from_environment(
        cls,
        variable_name: str = "DATABASE_URL",
    ) -> "Database":
        settings = DatabaseSettings.from_environment(variable_name)
        engine = create_engine(
            settings.url,
            pool_pre_ping=True,
        )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as error:
            engine.dispose()
            raise DatabaseConfigurationError(
                "Unable to connect to the configured PostgreSQL database."
            ) from error
        return cls(engine)

    def dispose(self) -> None:
        self.engine.dispose()


def database_url_from_environment(
    variable_name: str = "DATABASE_URL",
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return a validated URL for Alembic and other startup tooling."""

    return DatabaseSettings.from_environment(variable_name, environ).url
