from collections.abc import Mapping
from dataclasses import dataclass
import os

import uvicorn


class ServerConfigurationError(RuntimeError):
    """Raised when the HTTP server launch configuration is unusable."""


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """The intentionally single-process StudyRoom HTTP server contract."""

    host: str
    port: int
    workers: int = 1
    reload: bool = False
    access_log: bool = True

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ServerSettings":
        values = os.environ if environ is None else environ
        environment = values.get("STUDYROOM_ENV", "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ServerConfigurationError(
                "STUDYROOM_ENV must be development, test, or production."
            )
        default_host = "0.0.0.0" if environment == "production" else "127.0.0.1"
        host = values.get("HOST", default_host).strip() or default_host

        raw_port = values.get("PORT", "8000").strip()
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ServerConfigurationError("PORT must be an integer.") from error
        if not 1 <= port <= 65535:
            raise ServerConfigurationError("PORT must be between 1 and 65535.")

        return cls(
            host=host,
            port=port,
            access_log=environment != "production",
        )


def main() -> None:
    settings = ServerSettings.from_environment()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        proxy_headers=False,
        access_log=settings.access_log,
    )


if __name__ == "__main__":
    main()
