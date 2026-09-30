"""Authenticated owner-only solo routes, mounted by the application integrator."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.dependencies import CurrentUser, get_current_user
from app.learning_companions.contracts import (
    SoloAnswerRequest,
    SoloCreateRequest,
    SoloSelfCheckRequest,
)
from app.learning_companions.solo_domain import SoloError
from app.learning_companions.solo_service import SoloService
from app.schemas.solo import (
    LockedSelfCheckResponse,
    RetryMarkingResponse,
    SoloAnswerResponse,
    SoloAttemptResponse,
    SoloReviewResponse,
)

router = APIRouter(prefix="/me/solo-attempts", tags=["solo"])


def get_solo_service(request: Request) -> SoloService:
    service = getattr(request.app.state, "solo_service", None)
    if not isinstance(service, SoloService):
        raise RuntimeError("SoloService is not configured")
    return service


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _error(error: SoloError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
        headers={"Cache-Control": "no-store"},
    )


@router.post("", response_model=SoloAttemptResponse, status_code=status.HTTP_201_CREATED)
async def create_solo_attempt(
    payload: SoloCreateRequest,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAttemptResponse | JSONResponse:
    _no_store(response)
    try:
        return SoloAttemptResponse.from_domain(await service.create(current_user.id, payload))
    except SoloError as error:
        return _error(error)


@router.get("/active", response_model=SoloAttemptResponse | None)
def get_active_solo_attempt(
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAttemptResponse | None:
    _no_store(response)
    active = service.get_active(current_user.id)
    return SoloAttemptResponse.from_domain(active) if active is not None else None


@router.get("/{attempt_id}", response_model=SoloAttemptResponse)
def get_solo_attempt(
    attempt_id: UUID,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAttemptResponse | JSONResponse:
    _no_store(response)
    try:
        return SoloAttemptResponse.from_domain(service.get_state(current_user.id, attempt_id))
    except SoloError as error:
        return _error(error)


@router.post("/{attempt_id}/start", response_model=SoloAttemptResponse)
def start_solo_attempt(
    attempt_id: UUID,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAttemptResponse | JSONResponse:
    _no_store(response)
    try:
        return SoloAttemptResponse.from_domain(service.start(current_user.id, attempt_id))
    except SoloError as error:
        return _error(error)


@router.post("/{attempt_id}/answers", response_model=SoloAnswerResponse, status_code=status.HTTP_201_CREATED)
async def submit_solo_answer(
    attempt_id: UUID,
    payload: SoloAnswerRequest,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAnswerResponse | JSONResponse:
    _no_store(response)
    try:
        answer = await asyncio.to_thread(
            service.submit_answer,
            current_user.id, attempt_id, payload.question_id,
            payload.selected_option_id, payload.text,
        )
        if answer.grading_status == "PENDING":
            await service.schedule_grading()
        return SoloAnswerResponse.from_domain(answer)
    except SoloError as error:
        return _error(error)


@router.get("/{attempt_id}/questions/{question_id}/self-check", response_model=LockedSelfCheckResponse)
def get_solo_self_check(
    attempt_id: UUID,
    question_id: UUID,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> LockedSelfCheckResponse | JSONResponse:
    _no_store(response)
    try:
        return LockedSelfCheckResponse.from_domain(
            service.get_self_check(current_user.id, attempt_id, question_id)
        )
    except SoloError as error:
        return _error(error)


@router.post("/{attempt_id}/questions/{question_id}/self-check", response_model=SoloAnswerResponse)
def finalize_solo_self_check(
    attempt_id: UUID,
    question_id: UUID,
    payload: SoloSelfCheckRequest,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAnswerResponse | JSONResponse:
    _no_store(response)
    try:
        return SoloAnswerResponse.from_domain(service.finalize_self_check(
            current_user.id, attempt_id, question_id, tuple(payload.selected_criterion_ids)
        ))
    except SoloError as error:
        return _error(error)


@router.post("/{attempt_id}/retry-marking", response_model=RetryMarkingResponse)
async def retry_solo_marking(
    attempt_id: UUID,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> RetryMarkingResponse | JSONResponse:
    _no_store(response)
    try:
        return RetryMarkingResponse(queued_answers=await service.retry_marking(current_user.id, attempt_id))
    except SoloError as error:
        return _error(error)


@router.post("/{attempt_id}/abandon", response_model=SoloAttemptResponse)
def abandon_solo_attempt(
    attempt_id: UUID,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloAttemptResponse | JSONResponse:
    _no_store(response)
    try:
        return SoloAttemptResponse.from_domain(service.abandon(current_user.id, attempt_id))
    except SoloError as error:
        return _error(error)


@router.get("/{attempt_id}/review", response_model=SoloReviewResponse)
def get_solo_review(
    attempt_id: UUID,
    response: Response,
    service: SoloService = Depends(get_solo_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SoloReviewResponse | JSONResponse:
    _no_store(response)
    try:
        return SoloReviewResponse.from_domain(service.get_review(current_user.id, attempt_id))
    except SoloError as error:
        return _error(error)
