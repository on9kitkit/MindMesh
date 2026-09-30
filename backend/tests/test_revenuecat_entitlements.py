from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

import httpx
import pytest

from app.domain.errors import PremiumVerificationUnavailableError
from app.premium.config import (
    RevenueCatConfigurationError,
    RevenueCatServerConfiguration,
)
from app.premium.revenuecat import RevenueCatEntitlementVerifier


CUSTOMER_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_CUSTOMER_ID = UUID("22222222-2222-4222-8222-222222222222")
PRO_ENTITLEMENT_ID = "entl_internal_pro"
OTHER_ENTITLEMENT_ID = "entl_internal_other"
TEST_SECRET = "fixture-secret-api-key"


def configuration() -> RevenueCatServerConfiguration:
    return RevenueCatServerConfiguration.from_environment(
        {
            "REVENUECAT_PROJECT_ID": "proj_fixture",
            "REVENUECAT_SECRET_API_KEY": TEST_SECRET,
            "REVENUECAT_ENTITLEMENT_LOOKUP_KEY": "pro",
        }
    )


def project_entitlements(
    *,
    include_pro: bool = True,
) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {
            "object": "entitlement",
            "id": OTHER_ENTITLEMENT_ID,
            "lookup_key": "other",
            "state": "active",
        }
    ]
    if include_pro:
        items.append(
            {
                "object": "entitlement",
                "id": PRO_ENTITLEMENT_ID,
                "lookup_key": "pro",
                "state": "active",
            }
        )
    return {"object": "list", "items": items, "next_page": None}


def active_entitlements(*ids: str) -> dict[str, object]:
    return {
        "object": "list",
        "items": [
            {
                "object": "customer.active_entitlement",
                "entitlement_id": entitlement_id,
                "expires_at": 1_800_000_000_000,
            }
            for entitlement_id in ids
        ],
        "next_page": None,
    }


class RevenueCatHttpHarness:
    def __init__(self) -> None:
        self.project_status = 200
        self.customer_status = 200
        self.project_payload: object = project_entitlements()
        self.customer_payload: object = active_entitlements(PRO_ENTITLEMENT_ID)
        self.customer_not_found = False
        self.requests: list[httpx.Request] = []
        self.project_requests = 0
        self.customer_requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/entitlements") and "/customers/" not in request.url.path:
            self.project_requests += 1
            return httpx.Response(
                self.project_status,
                json=self.project_payload,
                request=request,
            )
        if request.url.path.endswith("/active_entitlements"):
            self.customer_requests += 1
            if self.customer_not_found:
                return httpx.Response(404, json={"object": "error"}, request=request)
            return httpx.Response(
                self.customer_status,
                json=self.customer_payload,
                request=request,
            )
        return httpx.Response(404, json={"object": "error"}, request=request)


@contextmanager
def verifier_for(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Iterator[RevenueCatEntitlementVerifier]:
    verifier = RevenueCatEntitlementVerifier(
        configuration(),
        transport=httpx.MockTransport(handler),
    )
    try:
        yield verifier
    finally:
        verifier.close()


def test_active_pro_entitlement_is_verified() -> None:
    harness = RevenueCatHttpHarness()
    with verifier_for(harness) as verifier:
        assert verifier.has_entitlement(CUSTOMER_ID, "pro") is True


@pytest.mark.parametrize(
    "payload",
    [
        active_entitlements(),
        active_entitlements(OTHER_ENTITLEMENT_ID),
    ],
)
def test_missing_or_different_entitlement_is_free(payload: object) -> None:
    harness = RevenueCatHttpHarness()
    harness.customer_payload = payload
    with verifier_for(harness) as verifier:
        assert verifier.has_entitlement(CUSTOMER_ID, "pro") is False


def test_final_page_may_omit_next_page() -> None:
    harness = RevenueCatHttpHarness()
    project_payload = project_entitlements()
    customer_payload = active_entitlements(PRO_ENTITLEMENT_ID)
    project_payload.pop("next_page")
    customer_payload.pop("next_page")
    harness.project_payload = project_payload
    harness.customer_payload = customer_payload

    with verifier_for(harness) as verifier:
        assert verifier.has_entitlement(CUSTOMER_ID, "pro") is True


def test_customer_not_found_is_free() -> None:
    harness = RevenueCatHttpHarness()
    harness.customer_not_found = True
    with verifier_for(harness) as verifier:
        assert verifier.has_entitlement(CUSTOMER_ID, "pro") is False


def test_lookup_key_resolves_to_internal_id_and_is_cached() -> None:
    harness = RevenueCatHttpHarness()
    with verifier_for(harness) as verifier:
        assert verifier.has_entitlement(CUSTOMER_ID, "pro") is True
        assert verifier.has_entitlement(SECOND_CUSTOMER_ID, "pro") is True

    assert harness.project_requests == 1
    assert harness.customer_requests == 2


def test_every_request_uses_the_secret_bearer_header() -> None:
    harness = RevenueCatHttpHarness()
    with verifier_for(harness) as verifier:
        verifier.has_entitlement(CUSTOMER_ID, "pro")

    assert harness.requests
    assert {
        request.headers.get("authorization") for request in harness.requests
    } == {f"Bearer {TEST_SECRET}"}
    assert {request.method for request in harness.requests} == {"GET"}
    assert {request.url.scheme for request in harness.requests} == {"https"}


def test_secret_never_appears_in_config_or_verification_errors() -> None:
    config = configuration()
    assert TEST_SECRET not in repr(config)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"unsafe detail containing {TEST_SECRET}",
            request=request,
        )

    with verifier_for(failing_handler) as verifier:
        with pytest.raises(PremiumVerificationUnavailableError) as captured:
            verifier.has_entitlement(CUSTOMER_ID, "pro")
    assert TEST_SECRET not in str(captured.value)


def test_timeout_becomes_verification_unavailable() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unsafe timeout detail", request=request)

    with verifier_for(timeout_handler) as verifier:
        with pytest.raises(PremiumVerificationUnavailableError):
            verifier.has_entitlement(CUSTOMER_ID, "pro")


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_revenuecat_failures_become_verification_unavailable(
    status_code: int,
) -> None:
    harness = RevenueCatHttpHarness()
    harness.project_status = status_code
    with verifier_for(harness) as verifier:
        with pytest.raises(PremiumVerificationUnavailableError):
            verifier.has_entitlement(CUSTOMER_ID, "pro")


def test_malformed_json_becomes_verification_unavailable() -> None:
    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-json",
            headers={"Content-Type": "application/json"},
            request=request,
        )

    with verifier_for(malformed_handler) as verifier:
        with pytest.raises(PremiumVerificationUnavailableError):
            verifier.has_entitlement(CUSTOMER_ID, "pro")


def test_unresolved_project_entitlement_is_unavailable_and_not_cached() -> None:
    harness = RevenueCatHttpHarness()
    harness.project_payload = project_entitlements(include_pro=False)
    with verifier_for(harness) as verifier:
        with pytest.raises(PremiumVerificationUnavailableError):
            verifier.has_entitlement(CUSTOMER_ID, "pro")
        with pytest.raises(PremiumVerificationUnavailableError):
            verifier.has_entitlement(CUSTOMER_ID, "pro")

    assert harness.project_requests == 2
    assert harness.customer_requests == 0


def test_missing_configuration_error_names_fields_without_values() -> None:
    with pytest.raises(RevenueCatConfigurationError) as captured:
        RevenueCatServerConfiguration.from_environment({})
    message = str(captured.value)
    assert "REVENUECAT_PROJECT_ID" in message
    assert "REVENUECAT_SECRET_API_KEY" in message
    assert TEST_SECRET not in message
