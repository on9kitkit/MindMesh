from collections.abc import Mapping
from dataclasses import dataclass
import os
from urllib.parse import urlsplit


LOCAL_DEVELOPMENT_ORIGINS = (
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:8082",
    "http://127.0.0.1:8082",
    "http://127.0.0.1:8000",
)


class RuntimeConfigurationError(RuntimeError):
    """Raised when deployment-owned runtime configuration is unusable."""


def _normalise_origin(raw_origin: str, variable_name: str) -> str:
    if "*" in raw_origin:
        raise RuntimeConfigurationError(
            f"{variable_name} must contain explicit HTTP(S) origins; wildcards are not allowed."
        )

    try:
        parsed = urlsplit(raw_origin)
        hostname = parsed.hostname
        parsed.port
    except ValueError as error:
        raise RuntimeConfigurationError(
            f"{variable_name} contains an invalid origin."
        ) from error

    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        raise RuntimeConfigurationError(
            f"{variable_name} must contain explicit HTTP(S) origins."
        )
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeConfigurationError(
            f"{variable_name} origins must not contain credentials."
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RuntimeConfigurationError(
            f"{variable_name} origins must not contain a path, query, or fragment."
        )

    return f"{parsed.scheme}://{parsed.netloc}"


def _origins_from_environment(
    variable_name: str,
    *,
    environment: str,
    environ: Mapping[str, str],
) -> tuple[str, ...]:
    raw_origins = environ.get(variable_name)
    if raw_origins is None:
        if environment == "production":
            raise RuntimeConfigurationError(
                f"{variable_name} is required in production."
            )
        return LOCAL_DEVELOPMENT_ORIGINS

    if not raw_origins.strip():
        return ()

    origins: list[str] = []
    for raw_origin in raw_origins.split(","):
        candidate = raw_origin.strip()
        if not candidate:
            raise RuntimeConfigurationError(
                f"{variable_name} must not contain an empty origin entry."
            )
        normalised = _normalise_origin(candidate, variable_name)
        if environment == "production" and not normalised.startswith("https://"):
            raise RuntimeConfigurationError(
                f"{variable_name} must use HTTPS origins in production."
            )
        if normalised not in origins:
            origins.append(normalised)
    return tuple(origins)


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated deployment settings that do not contain credentials."""

    environment: str
    allowed_http_origins: tuple[str, ...]
    allowed_websocket_origins: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeSettings":
        values = os.environ if environ is None else environ
        environment = values.get("STUDYROOM_ENV", "development").strip().lower()
        if not environment:
            environment = "development"
        if environment not in {"development", "test", "production"}:
            raise RuntimeConfigurationError(
                "STUDYROOM_ENV must be development, test, or production."
            )

        return cls(
            environment=environment,
            allowed_http_origins=_origins_from_environment(
                "ALLOWED_HTTP_ORIGINS",
                environment=environment,
                environ=values,
            ),
            allowed_websocket_origins=_origins_from_environment(
                "ALLOWED_WEBSOCKET_ORIGINS",
                environment=environment,
                environ=values,
            ),
        )
