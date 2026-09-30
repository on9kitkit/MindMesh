from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import os
import re
import time
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import SecretStr

from app.account_deletion.ports import (
    AccountDeletionProviderError,
    RevenueCatCustomerDeletionProvider,
    SupabaseAuthDeletionProvider,
)


ACCOUNT_DELETION_HTTP_TIMEOUT = httpx.Timeout(
    connect=2.0,
    read=5.0,
    write=3.0,
    pool=2.0,
)
REVENUECAT_API_BASE_URL = "https://api.revenuecat.com/v2/"
REVENUECAT_DELETION_VERIFICATION_MAX_ATTEMPTS = 4
REVENUECAT_DELETION_VERIFICATION_INITIAL_DELAY_SECONDS = 0.25
REVENUECAT_DELETION_VERIFICATION_BACKOFF_MULTIPLIER = 2.0
REVENUECAT_DELETION_VERIFICATION_MAX_DELAY_SECONDS = 1.0
REVENUECAT_DELETION_VERIFICATION_MAX_ELAPSED_SECONDS = 12.0
REVENUECAT_DELETION_VERIFICATION_HTTP_TIMEOUT = httpx.Timeout(
    connect=2.0,
    read=2.0,
    write=2.0,
    pool=2.0,
)
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


@dataclass(frozen=True, slots=True)
class AccountDeletionProviderConfiguration:
    """Optional backend-only provider credentials; secrets stay non-repr."""

    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = field(default=None, repr=False)
    revenuecat_project_id: str | None = None
    revenuecat_read_secret_api_key: SecretStr | None = field(
        default=None,
        repr=False,
    )
    revenuecat_deletion_secret_api_key: SecretStr | None = field(
        default=None,
        repr=False,
    )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "AccountDeletionProviderConfiguration":
        values = os.environ if environ is None else environ
        supabase_url = values.get("SUPABASE_URL", "").strip().rstrip("/") or None
        supabase_key = values.get("SUPABASE_SECRET_KEY", "").strip() or None
        project_id = values.get("REVENUECAT_PROJECT_ID", "").strip() or None
        revenuecat_read_key = (
            values.get("REVENUECAT_SECRET_API_KEY", "").strip() or None
        )
        revenuecat_key = (
            values.get("REVENUECAT_DELETION_SECRET_API_KEY", "").strip()
            or None
        )

        if supabase_url is not None and not _is_http_url(supabase_url):
            raise ValueError("SUPABASE_URL must be an absolute HTTP(S) URL.")
        if project_id is not None and not _PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ValueError("REVENUECAT_PROJECT_ID is invalid.")

        return cls(
            supabase_url=supabase_url,
            supabase_secret_key=(
                None if supabase_key is None else SecretStr(supabase_key)
            ),
            revenuecat_project_id=project_id,
            revenuecat_read_secret_api_key=(
                None
                if revenuecat_read_key is None
                else SecretStr(revenuecat_read_key)
            ),
            revenuecat_deletion_secret_api_key=(
                None if revenuecat_key is None else SecretStr(revenuecat_key)
            ),
        )


class SupabaseAuthAdminDeletionProvider:
    """Minimal official Supabase Auth Admin delete adapter."""

    def __init__(
        self,
        supabase_url: str,
        secret_key: SecretStr,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=f"{supabase_url.rstrip('/')}/",
            headers={
                "Accept": "application/json",
                "apikey": secret_key.get_secret_value(),
                "Authorization": f"Bearer {secret_key.get_secret_value()}",
            },
            timeout=ACCOUNT_DELETION_HTTP_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )

    def delete_identity(self, user_id: UUID) -> None:
        try:
            response = self._client.delete(f"auth/v1/admin/users/{user_id}")
        except httpx.HTTPError as error:
            raise AccountDeletionProviderError("transport_error") from error
        if response.status_code in {200, 204, 404}:
            return
        raise AccountDeletionProviderError(
            _provider_error_category(response.status_code)
        )

    def close(self) -> None:
        self._client.close()


class RevenueCatCustomerAdminDeletionProvider:
    """Delete one customer and prove final absence after queued responses."""

    def __init__(
        self,
        project_id: str,
        deletion_secret_api_key: SecretStr,
        read_secret_api_key: SecretStr,
        *,
        transport: httpx.BaseTransport | None = None,
        read_transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._project_id = project_id
        self._sleep = sleep
        self._monotonic = monotonic
        self._deletion_client = httpx.Client(
            base_url=REVENUECAT_API_BASE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": (
                    "Bearer "
                    f"{deletion_secret_api_key.get_secret_value()}"
                ),
            },
            timeout=ACCOUNT_DELETION_HTTP_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )
        self._read_client = httpx.Client(
            base_url=REVENUECAT_API_BASE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": (
                    "Bearer " f"{read_secret_api_key.get_secret_value()}"
                ),
            },
            timeout=REVENUECAT_DELETION_VERIFICATION_HTTP_TIMEOUT,
            follow_redirects=False,
            transport=(transport if read_transport is None else read_transport),
        )

    def delete_customer(self, customer_id: str) -> None:
        path = f"projects/{self._project_id}/customers/{customer_id}"
        try:
            response = self._deletion_client.delete(path)
        except httpx.TimeoutException as error:
            raise AccountDeletionProviderError("provider_timeout") from error
        except httpx.HTTPError as error:
            raise AccountDeletionProviderError("provider_unavailable") from error
        if response.status_code in {200, 404}:
            return
        if response.status_code == 202:
            self._verify_customer_absent(path)
            return
        raise AccountDeletionProviderError(
            _revenuecat_error_category(response.status_code)
        )

    def close(self) -> None:
        self._deletion_client.close()
        self._read_client.close()

    def _verify_customer_absent(self, path: str) -> None:
        started_at = self._monotonic()
        delay_seconds = REVENUECAT_DELETION_VERIFICATION_INITIAL_DELAY_SECONDS
        last_error_category = "queued_not_confirmed"

        for _ in range(REVENUECAT_DELETION_VERIFICATION_MAX_ATTEMPTS):
            elapsed_seconds = self._monotonic() - started_at
            remaining_seconds = (
                REVENUECAT_DELETION_VERIFICATION_MAX_ELAPSED_SECONDS
                - elapsed_seconds
            )
            if remaining_seconds <= 0:
                break
            self._sleep(min(delay_seconds, remaining_seconds))
            if (
                self._monotonic() - started_at
                >= REVENUECAT_DELETION_VERIFICATION_MAX_ELAPSED_SECONDS
            ):
                break

            try:
                response = self._read_client.get(path)
            except httpx.TimeoutException:
                last_error_category = "provider_timeout"
            except httpx.HTTPError:
                last_error_category = "provider_unavailable"
            else:
                if response.status_code == 404:
                    return
                if response.status_code == 200:
                    last_error_category = "queued_not_confirmed"
                else:
                    category = _revenuecat_error_category(response.status_code)
                    if category in {
                        "provider_auth_error",
                        "provider_rejected_request",
                    }:
                        raise AccountDeletionProviderError(category)
                    last_error_category = category

            delay_seconds = min(
                delay_seconds
                * REVENUECAT_DELETION_VERIFICATION_BACKOFF_MULTIPLIER,
                REVENUECAT_DELETION_VERIFICATION_MAX_DELAY_SECONDS,
            )

        raise AccountDeletionProviderError(last_error_category)


def build_deletion_providers(
    configuration: AccountDeletionProviderConfiguration,
) -> tuple[
    SupabaseAuthDeletionProvider | None,
    RevenueCatCustomerDeletionProvider | None,
]:
    supabase_provider: SupabaseAuthDeletionProvider | None = None
    if (
        configuration.supabase_url is not None
        and configuration.supabase_secret_key is not None
    ):
        supabase_provider = SupabaseAuthAdminDeletionProvider(
            configuration.supabase_url,
            configuration.supabase_secret_key,
        )

    revenuecat_provider: RevenueCatCustomerDeletionProvider | None = None
    if (
        configuration.revenuecat_project_id is not None
        and configuration.revenuecat_read_secret_api_key is not None
        and configuration.revenuecat_deletion_secret_api_key is not None
    ):
        revenuecat_provider = RevenueCatCustomerAdminDeletionProvider(
            configuration.revenuecat_project_id,
            configuration.revenuecat_deletion_secret_api_key,
            configuration.revenuecat_read_secret_api_key,
        )
    return supabase_provider, revenuecat_provider


def close_deletion_providers(
    providers: tuple[
        SupabaseAuthDeletionProvider | None,
        RevenueCatCustomerDeletionProvider | None,
    ],
) -> None:
    for provider in providers:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _provider_error_category(status_code: int) -> str:
    if status_code in {401, 403}:
        return "provider_authentication_failed"
    if status_code in {408, 409, 423, 429} or status_code >= 500:
        return "provider_temporarily_unavailable"
    return "provider_rejected_request"


def _revenuecat_error_category(status_code: int) -> str:
    if status_code in {401, 403}:
        return "provider_auth_error"
    if status_code == 408:
        return "provider_timeout"
    if status_code == 429:
        return "provider_rate_limited"
    if status_code in {409, 423} or status_code >= 500:
        return "provider_unavailable"
    return "provider_rejected_request"
