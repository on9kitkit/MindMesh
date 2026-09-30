from collections.abc import Mapping
from dataclasses import dataclass
import os


class AccountDeletionConfigurationError(RuntimeError):
    """Raised when account-deletion runtime settings are unusable."""


@dataclass(frozen=True, slots=True)
class AccountDeletionSettings:
    """Bounded local policy and retry settings for the deletion saga."""

    recent_auth_window_seconds: int = 600
    max_jobs_per_run: int = 100
    retry_base_seconds: int = 5
    retry_max_seconds: int = 3600
    claim_lease_seconds: int = 600

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "AccountDeletionSettings":
        values = os.environ if environ is None else environ
        recent_auth_window_seconds = _positive_int(
            values,
            "ACCOUNT_DELETION_RECENT_AUTH_SECONDS",
            600,
        )
        if recent_auth_window_seconds > 3600:
            raise AccountDeletionConfigurationError(
                "ACCOUNT_DELETION_RECENT_AUTH_SECONDS must not exceed one hour."
            )
        return cls(recent_auth_window_seconds=recent_auth_window_seconds)


def _positive_int(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = values.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise AccountDeletionConfigurationError(
            f"{name} must be a positive integer."
        ) from error
    if value < 1:
        raise AccountDeletionConfigurationError(
            f"{name} must be a positive integer."
        )
    return value
