"""Authenticated earned reward, daily entry and pet endpoints.

The integrator registers this router and provides reward_service/pet_service
on app.state. The room-first app-entry flow stays in the mobile integration.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from app.api.dependencies import CurrentUser, get_current_user
from app.learning_companions.contracts import CompletionSource, HomeZoneSelectionRequest
from app.learning_companions.pet_service import (
    PetService,
    UnknownCatalogItem,
)
from app.learning_companions.reward_service import (
    LearningAccountUnavailable,
    RewardSourceNotFound,
    RewardService,
)
from app.schemas.learning_companions import (
    DailyInvitationResponse,
    EquipmentRequest,
    EquipmentResponse,
    HomeZoneResponse,
    PetCatalogItemResponse,
    PetPurchaseRequest,
    PetPurchaseResponse,
    PetStateResponse,
    RewardOverviewResponse,
    RewardSourceStatusResponse,
    StarterChoiceRequest,
    StarterChoiceResponse,
)


router = APIRouter(prefix="/me", tags=["learning companions"])


def get_reward_service(request: Request) -> RewardService:
    return request.app.state.reward_service


def get_pet_service(request: Request) -> PetService:
    return request.app.state.pet_service


def _error(error: ValueError) -> HTTPException:
    if isinstance(error, RewardSourceNotFound):
        status = 404
    elif isinstance(error, LearningAccountUnavailable):
        status = 403
    elif isinstance(error, UnknownCatalogItem) or type(error) is ValueError:
        status = 422
    else:
        status = 409
    return HTTPException(status_code=status, detail=str(error))


@router.post("/learning-settings/home-zone", response_model=HomeZoneResponse)
def select_home_zone(
    payload: HomeZoneSelectionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
) -> HomeZoneResponse:
    try:
        selection = service.select_home_zone(current_user.id, payload.home_timezone)
    except ValueError as error:
        raise _error(error) from error
    return HomeZoneResponse(
        home_timezone=selection.home_timezone,
        home_zone_version=selection.home_zone_version,
        selected_at=selection.selected_at,
    )


@router.post("/daily-invitation", response_model=DailyInvitationResponse)
def claim_daily_invitation(
    current_user: CurrentUser = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
) -> DailyInvitationResponse:
    try:
        result = service.claim_daily_invitation(current_user.id)
    except ValueError as error:
        raise _error(error) from error
    return DailyInvitationResponse(
        study_date=result.study_date,
        should_open=result.should_open,
        reason=result.reason,
    )


@router.post("/daily-invitation/dismiss", response_model=DailyInvitationResponse)
def dismiss_daily_invitation(
    study_date: date = Body(embed=True),
    current_user: CurrentUser = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
) -> DailyInvitationResponse:
    try:
        result = service.dismiss_daily_invitation(current_user.id, study_date)
    except ValueError as error:
        raise _error(error) from error
    return DailyInvitationResponse(
        study_date=result.study_date,
        should_open=result.should_open,
        reason=result.reason,
    )


@router.post("/daily-invitation/acknowledge", response_model=DailyInvitationResponse)
def acknowledge_daily_invitation(
    study_date: date = Body(embed=True),
    current_user: CurrentUser = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
) -> DailyInvitationResponse:
    try:
        result = service.acknowledge_daily_invitation(current_user.id, study_date)
    except ValueError as error:
        raise _error(error) from error
    return DailyInvitationResponse(
        study_date=result.study_date,
        should_open=result.should_open,
        reason=result.reason,
    )


@router.get("/rewards", response_model=RewardOverviewResponse)
def get_rewards(
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
) -> RewardOverviewResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        result = service.get_overview(current_user.id)
    except ValueError as error:
        raise _error(error) from error
    streak = result.streak
    return RewardOverviewResponse(
        home_timezone=result.home_timezone,
        study_date=result.study_date,
        balance=result.balance,
        day_coins=result.day_coins,
        qualifying_count=result.qualifying_count,
        active_streak_days=streak.active_days,
        best_streak_days=streak.best_days,
        last_qualified_day=streak.last_qualified_day,
        qualified_today=streak.qualified_today,
        pending_receipt_count=result.pending_receipt_count,
        delayed_receipt_count=result.delayed_receipt_count,
    )


@router.get(
    "/rewards/sources/{source_kind}/{source_id}",
    response_model=RewardSourceStatusResponse,
)
def get_reward_source_status(
    source_kind: CompletionSource,
    source_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
) -> RewardSourceStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        result = service.get_source_status(current_user.id, source_kind, source_id)
    except ValueError as error:
        raise _error(error) from error
    return RewardSourceStatusResponse(
        source_kind=result.source_kind,
        source_id=result.source_id,
        status=result.status,
    )


@router.get("/pets", response_model=PetStateResponse)
def get_pets(
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    service: PetService = Depends(get_pet_service),
) -> PetStateResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        state = service.get_state(current_user.id)
    except ValueError as error:
        raise _error(error) from error
    return PetStateResponse(
        catalog=[
            PetCatalogItemResponse(id=item.id, kind=item.kind, coin_price=item.coin_price)
            for item in state.catalog
        ],
        owned_item_ids=list(state.owned_item_ids),
        starter_pet_id=state.starter_pet_id,
        equipment=(
            EquipmentResponse(
                pet_id=state.equipment.pet_id,
                cosmetic_id=state.equipment.cosmetic_id,
                animation_id=state.equipment.animation_id,
            )
            if state.equipment is not None
            else None
        ),
        balance=state.balance,
    )


@router.post("/pets/starter", response_model=StarterChoiceResponse)
def choose_starter(
    payload: StarterChoiceRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: PetService = Depends(get_pet_service),
) -> StarterChoiceResponse:
    try:
        choice = service.choose_starter(current_user.id, payload.item_id)
    except ValueError as error:
        raise _error(error) from error
    return StarterChoiceResponse(item_id=choice.item_id, created=choice.created)


@router.post("/pets/purchases", response_model=PetPurchaseResponse)
def purchase_item(
    payload: PetPurchaseRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: PetService = Depends(get_pet_service),
) -> PetPurchaseResponse:
    try:
        purchase = service.purchase(current_user.id, payload.request_id, payload.item_id)
    except ValueError as error:
        raise _error(error) from error
    return PetPurchaseResponse(
        purchase_id=purchase.purchase_id,
        request_id=purchase.request_id,
        item_id=purchase.item_id,
        price_charged=purchase.price_charged,
        balance_after=purchase.balance_after,
        replayed=purchase.replayed,
    )


@router.put("/pets/equipment", response_model=EquipmentResponse)
def equip_items(
    payload: EquipmentRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: PetService = Depends(get_pet_service),
) -> EquipmentResponse:
    try:
        equipment = service.equip(
            current_user.id,
            pet_id=payload.pet_id,
            cosmetic_id=payload.cosmetic_id,
            animation_id=payload.animation_id,
        )
    except ValueError as error:
        raise _error(error) from error
    return EquipmentResponse(
        pet_id=equipment.pet_id,
        cosmetic_id=equipment.cosmetic_id,
        animation_id=equipment.animation_id,
    )
