"""Public, typed earned-reward and pet responses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.learning_companions.contracts import (
    CatalogKind,
    CompletionSource,
    RewardDisplayStatus,
)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HomeZoneResponse(BaseModel):
    home_timezone: str
    home_zone_version: int
    selected_at: datetime


class DailyInvitationResponse(BaseModel):
    study_date: date
    should_open: bool
    reason: Literal["first_entry", "already_invited", "already_qualified", "dismissed"]


class RewardOverviewResponse(BaseModel):
    home_timezone: str | None
    study_date: date | None
    balance: int
    day_coins: int
    qualifying_count: int
    active_streak_days: int
    best_streak_days: int
    last_qualified_day: date | None
    qualified_today: bool
    pending_receipt_count: int
    delayed_receipt_count: int


class RewardSourceStatusResponse(BaseModel):
    source_kind: CompletionSource
    source_id: UUID
    status: RewardDisplayStatus


class PetCatalogItemResponse(BaseModel):
    id: str
    kind: CatalogKind
    coin_price: int


class EquipmentResponse(BaseModel):
    pet_id: str
    cosmetic_id: str | None
    animation_id: str | None


class PetStateResponse(BaseModel):
    catalog: list[PetCatalogItemResponse]
    owned_item_ids: list[str]
    starter_pet_id: str | None
    equipment: EquipmentResponse | None
    balance: int


class StarterChoiceRequest(_StrictRequest):
    item_id: str = Field(min_length=1, max_length=64)


class StarterChoiceResponse(BaseModel):
    item_id: str
    created: bool


class PetPurchaseRequest(_StrictRequest):
    request_id: UUID = Field(strict=False)
    item_id: str = Field(min_length=1, max_length=64)


class PetPurchaseResponse(BaseModel):
    purchase_id: UUID
    request_id: UUID
    item_id: str
    price_charged: int
    balance_after: int
    replayed: bool


class EquipmentRequest(_StrictRequest):
    pet_id: str = Field(min_length=1, max_length=64)
    cosmetic_id: str | None = Field(default=None, max_length=64)
    animation_id: str | None = Field(default=None, max_length=64)
