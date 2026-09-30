from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.account_deletion.ports import AccountDeletionProviderError
from app.account_deletion.providers import (
    REVENUECAT_DELETION_VERIFICATION_INITIAL_DELAY_SECONDS,
    REVENUECAT_DELETION_VERIFICATION_MAX_ELAPSED_SECONDS,
    REVENUECAT_DELETION_VERIFICATION_MAX_ATTEMPTS,
    AccountDeletionProviderConfiguration,
    RevenueCatCustomerAdminDeletionProvider,
    build_deletion_providers,
    close_deletion_providers,
)


CUSTOMER_ID = UUID("11111111-1111-4111-8111-111111111111")
DELETION_KEY = "unit-test-deletion-key"
READ_KEY = "unit-test-read-key"


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    sleeps: list[float] | None = None,
) -> RevenueCatCustomerAdminDeletionProvider:
    return RevenueCatCustomerAdminDeletionProvider(
        "project-id",
        SecretStr(DELETION_KEY),
        SecretStr(READ_KEY),
        transport=httpx.MockTransport(handler),
        sleep=(
            (lambda _seconds: None)
            if sleeps is None
            else sleeps.append
        ),
    )


@pytest.mark.parametrize("status_code", [200, 404])
def test_delete_customer_accepts_final_or_already_absent_response(
    status_code: int,
) -> None:
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(status_code, request=request)

    provider = _provider(respond)
    try:
        provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert methods == ["DELETE"]


def test_queued_delete_confirms_absence_with_separate_read_credential() -> None:
    requests: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.headers["Authorization"]))
        status_code = 202 if request.method == "DELETE" else 404
        return httpx.Response(status_code, request=request)

    provider = _provider(respond)
    try:
        provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert requests == [
        ("DELETE", f"Bearer {DELETION_KEY}"),
        ("GET", f"Bearer {READ_KEY}"),
    ]


def test_queued_delete_retries_existing_customer_until_absent() -> None:
    get_statuses = iter([200, 404])
    sleeps: list[float] = []
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        status_code = 202 if request.method == "DELETE" else next(get_statuses)
        return httpx.Response(status_code, request=request)

    provider = _provider(respond, sleeps=sleeps)
    try:
        provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert methods == ["DELETE", "GET", "GET"]
    assert sleeps == [
        REVENUECAT_DELETION_VERIFICATION_INITIAL_DELAY_SECONDS,
        REVENUECAT_DELETION_VERIFICATION_INITIAL_DELAY_SECONDS * 2,
    ]


def test_queued_delete_that_remains_present_is_retryable() -> None:
    get_count = 0
    sleeps: list[float] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "DELETE":
            return httpx.Response(202, request=request)
        get_count += 1
        return httpx.Response(200, request=request)

    provider = _provider(respond, sleeps=sleeps)
    try:
        with pytest.raises(AccountDeletionProviderError) as caught:
            provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert caught.value.category == "queued_not_confirmed"
    assert get_count == REVENUECAT_DELETION_VERIFICATION_MAX_ATTEMPTS
    assert len(sleeps) == REVENUECAT_DELETION_VERIFICATION_MAX_ATTEMPTS


def test_queued_verification_stops_when_elapsed_window_is_exhausted() -> None:
    now = 0.0
    get_count = 0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal get_count, now
        if request.method == "DELETE":
            return httpx.Response(202, request=request)
        get_count += 1
        now = REVENUECAT_DELETION_VERIFICATION_MAX_ELAPSED_SECONDS
        return httpx.Response(200, request=request)

    provider = RevenueCatCustomerAdminDeletionProvider(
        "project-id",
        SecretStr(DELETION_KEY),
        SecretStr(READ_KEY),
        transport=httpx.MockTransport(respond),
        sleep=sleep,
        monotonic=monotonic,
    )
    try:
        with pytest.raises(AccountDeletionProviderError) as caught:
            provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert caught.value.category == "queued_not_confirmed"
    assert get_count == 1


@pytest.mark.parametrize("transient", ["response", "timeout"])
def test_queued_delete_recovers_from_transient_get_before_absence(
    transient: str,
) -> None:
    get_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "DELETE":
            return httpx.Response(202, request=request)
        get_count += 1
        if get_count == 1:
            if transient == "timeout":
                raise httpx.ReadTimeout("simulated", request=request)
            return httpx.Response(503, request=request)
        return httpx.Response(404, request=request)

    provider = _provider(respond)
    try:
        provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert get_count == 2


@pytest.mark.parametrize(
    ("transient", "expected_category"),
    [
        ("rate_limit", "provider_rate_limited"),
        ("unavailable", "provider_unavailable"),
        ("timeout", "provider_timeout"),
    ],
)
def test_persistent_transient_verification_failure_is_sanitized_and_retryable(
    transient: str,
    expected_category: str,
) -> None:
    get_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "DELETE":
            return httpx.Response(202, request=request)
        get_count += 1
        if transient == "timeout":
            raise httpx.ReadTimeout("simulated", request=request)
        status_code = 429 if transient == "rate_limit" else 503
        return httpx.Response(status_code, request=request)

    provider = _provider(respond)
    try:
        with pytest.raises(AccountDeletionProviderError) as caught:
            provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert caught.value.category == expected_category
    assert get_count == REVENUECAT_DELETION_VERIFICATION_MAX_ATTEMPTS


@pytest.mark.parametrize("status_code", [401, 403])
def test_delete_auth_failure_is_sanitized(
    status_code: int,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_body = "raw-provider-customer-data"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=raw_body, request=request)

    provider = _provider(respond)
    try:
        with pytest.raises(AccountDeletionProviderError) as caught:
            provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert caught.value.category == "provider_auth_error"
    assert str(caught.value) == ""
    captured = capsys.readouterr()
    emitted = captured.out + captured.err + "".join(
        record.getMessage() for record in caplog.records
    )
    for sensitive_value in (
        raw_body,
        str(CUSTOMER_ID),
        DELETION_KEY,
        READ_KEY,
    ):
        assert sensitive_value not in emitted


def test_read_auth_failure_after_queued_delete_is_sanitized() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        status_code = 202 if request.method == "DELETE" else 403
        return httpx.Response(status_code, request=request)

    provider = _provider(respond)
    try:
        with pytest.raises(AccountDeletionProviderError) as caught:
            provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert caught.value.category == "provider_auth_error"
    assert str(caught.value) == ""


def test_lost_delete_response_is_safe_to_retry_as_already_absent() -> None:
    delete_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal delete_count
        assert request.method == "DELETE"
        delete_count += 1
        if delete_count == 1:
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(404, request=request)

    provider = _provider(respond)
    try:
        with pytest.raises(AccountDeletionProviderError) as caught:
            provider.delete_customer(str(CUSTOMER_ID))
        assert caught.value.category == "provider_timeout"
        provider.delete_customer(str(CUSTOMER_ID))
    finally:
        provider.close()

    assert delete_count == 2


def test_deletion_configuration_requires_separate_read_authority() -> None:
    configuration = AccountDeletionProviderConfiguration.from_environment(
        {
            "REVENUECAT_PROJECT_ID": "project-id",
            "REVENUECAT_SECRET_API_KEY": READ_KEY,
            "REVENUECAT_DELETION_SECRET_API_KEY": DELETION_KEY,
        }
    )
    assert READ_KEY not in repr(configuration)
    assert DELETION_KEY not in repr(configuration)

    providers = build_deletion_providers(configuration)
    try:
        assert providers[1] is not None
    finally:
        close_deletion_providers(providers)

    without_read_authority = AccountDeletionProviderConfiguration(
        revenuecat_project_id="project-id",
        revenuecat_deletion_secret_api_key=SecretStr(DELETION_KEY),
    )
    assert build_deletion_providers(without_read_authority)[1] is None
