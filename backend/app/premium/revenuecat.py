from threading import Lock
from typing import Literal, Never, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.errors import PremiumVerificationUnavailableError
from app.premium.config import RevenueCatServerConfiguration


REVENUECAT_API_BASE_URL = "https://api.revenuecat.com/v2/"
REVENUECAT_HTTP_TIMEOUT = httpx.Timeout(
    connect=2.0,
    read=3.0,
    write=3.0,
    pool=2.0,
)
_PAGE_LIMIT = 100
_MAX_PAGES = 10
_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class _ProjectEntitlement(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    object: Literal["entitlement"]
    id: str = Field(min_length=1, max_length=255)
    lookup_key: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1)


class _ProjectEntitlementList(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    object: Literal["list"]
    items: list[_ProjectEntitlement]
    next_page: str | None = None


class _ActiveEntitlement(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    object: Literal["customer.active_entitlement"]
    entitlement_id: str = Field(min_length=1, max_length=255)


class _ActiveEntitlementList(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    object: Literal["list"]
    items: list[_ActiveEntitlement]
    next_page: str | None = None


class RevenueCatEntitlementVerifier:
    """Read-only RevenueCat REST API v2 entitlement verifier."""

    def __init__(
        self,
        configuration: RevenueCatServerConfiguration,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._configuration = configuration
        self._entitlement_ids: dict[str, str] = {}
        self._entitlement_resolution_lock = Lock()
        self._client = httpx.Client(
            base_url=REVENUECAT_API_BASE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": (
                    "Bearer "
                    f"{configuration.secret_api_key.get_secret_value()}"
                ),
            },
            timeout=REVENUECAT_HTTP_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )

    def has_entitlement(
        self,
        customer_id: UUID,
        entitlement_lookup_key: str,
    ) -> bool:
        entitlement_id = self._resolve_entitlement_id(entitlement_lookup_key)
        path = (
            f"projects/{self._configuration.project_id}/customers/"
            f"{customer_id}/active_entitlements"
        )
        cursor: str | None = None
        seen_cursors: set[str] = set()

        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {"limit": _PAGE_LIMIT}
            if cursor is not None:
                params["starting_after"] = cursor
            response = self._safe_get(path, params=params)
            if response.status_code == 404:
                return False
            if response.status_code != 200:
                _verification_unavailable()
            payload = self._parse(response, _ActiveEntitlementList)
            if any(
                item.entitlement_id == entitlement_id for item in payload.items
            ):
                return True
            if payload.next_page is None:
                return False
            if not payload.items:
                _verification_unavailable()
            cursor = payload.items[-1].entitlement_id
            if cursor in seen_cursors:
                _verification_unavailable()
            seen_cursors.add(cursor)

        _verification_unavailable()

    def close(self) -> None:
        self._client.close()

    def _resolve_entitlement_id(self, lookup_key: str) -> str:
        cached = self._entitlement_ids.get(lookup_key)
        if cached is not None:
            return cached

        with self._entitlement_resolution_lock:
            cached = self._entitlement_ids.get(lookup_key)
            if cached is not None:
                return cached
            resolved = self._load_entitlement_ids()
            entitlement_id = resolved.get(lookup_key)
            if entitlement_id is None:
                _verification_unavailable()
            self._entitlement_ids.update(resolved)
            return entitlement_id

    def _load_entitlement_ids(self) -> dict[str, str]:
        path = f"projects/{self._configuration.project_id}/entitlements"
        cursor: str | None = None
        seen_cursors: set[str] = set()
        resolved: dict[str, str] = {}

        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {"limit": _PAGE_LIMIT}
            if cursor is not None:
                params["starting_after"] = cursor
            response = self._safe_get(path, params=params)
            if response.status_code != 200:
                _verification_unavailable()
            payload = self._parse(response, _ProjectEntitlementList)
            for item in payload.items:
                if item.state != "active":
                    continue
                existing = resolved.get(item.lookup_key)
                if existing is not None and existing != item.id:
                    _verification_unavailable()
                resolved[item.lookup_key] = item.id
            if payload.next_page is None:
                return resolved
            if not payload.items:
                _verification_unavailable()
            cursor = payload.items[-1].id
            if cursor in seen_cursors:
                _verification_unavailable()
            seen_cursors.add(cursor)

        _verification_unavailable()

    def _safe_get(
        self,
        path: str,
        *,
        params: dict[str, str | int],
    ) -> httpx.Response:
        try:
            return self._client.get(path, params=params)
        except httpx.HTTPError:
            _verification_unavailable()

    @staticmethod
    def _parse(
        response: httpx.Response,
        model: type[_ResponseModel],
    ) -> _ResponseModel:
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError):
            _verification_unavailable()


def _verification_unavailable() -> Never:
    raise PremiumVerificationUnavailableError from None
