import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import SecretStr


_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_REQUIRED_VARIABLES = (
    "REVENUECAT_PROJECT_ID",
    "REVENUECAT_SECRET_API_KEY",
    "REVENUECAT_ENTITLEMENT_LOOKUP_KEY",
)


class RevenueCatConfigurationError(RuntimeError):
    """Raised without secret-bearing values when server config is unusable."""


@dataclass(frozen=True, slots=True)
class RevenueCatServerConfiguration:
    project_id: str
    secret_api_key: SecretStr = field(repr=False)
    entitlement_lookup_key: str

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RevenueCatServerConfiguration":
        source = os.environ if environ is None else environ
        values = {
            name: source.get(name, "").strip() for name in _REQUIRED_VARIABLES
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            names = ", ".join(missing)
            raise RevenueCatConfigurationError(
                f"Missing RevenueCat server configuration: {names}."
            )

        project_id = values["REVENUECAT_PROJECT_ID"]
        secret_api_key = values["REVENUECAT_SECRET_API_KEY"]
        entitlement_lookup_key = values["REVENUECAT_ENTITLEMENT_LOOKUP_KEY"]

        if not _PROJECT_ID_PATTERN.fullmatch(project_id):
            raise RevenueCatConfigurationError(
                "REVENUECAT_PROJECT_ID is not a valid project identifier."
            )
        if len(secret_api_key) > 4096 or _contains_control_character(
            secret_api_key
        ):
            raise RevenueCatConfigurationError(
                "REVENUECAT_SECRET_API_KEY is not valid."
            )
        if (
            len(entitlement_lookup_key) > 200
            or _contains_control_character(entitlement_lookup_key)
        ):
            raise RevenueCatConfigurationError(
                "REVENUECAT_ENTITLEMENT_LOOKUP_KEY is not valid."
            )

        return cls(
            project_id=project_id,
            secret_api_key=SecretStr(secret_api_key),
            entitlement_lookup_key=entitlement_lookup_key,
        )


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)
