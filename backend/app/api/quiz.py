from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
import asyncio

from app.api.dependencies import CurrentUser, get_current_user
from app.schemas.quiz import (
    AnswerAcknowledgementResponse,
    ReadyRequest,
    ReadyResponse,
    SessionReviewResponse,
    SessionStateResponse,
    SubmitAnswerRequest,
)
from app.services.sessions import SessionService

router = APIRouter(tags=["quiz"])


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if not isinstance(service, SessionService):
        raise RuntimeError("SessionService is not configured")
    return service


@router.post(
    "/rooms/{room_id}/ready",
    response_model=ReadyResponse,
    status_code=status.HTTP_200_OK,
)
def set_ready(
    room_id: UUID,
    payload: ReadyRequest,
    service: SessionService = Depends(get_session_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> ReadyResponse:
    return ReadyResponse.from_domain(
        service.set_ready(room_id, current_user.id, payload.ready)
    )


@router.post(
    "/rooms/{room_id}/start",
    response_model=SessionStateResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_session(
    room_id: UUID,
    service: SessionService = Depends(get_session_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SessionStateResponse:
    service.start_session(room_id, current_user.id)
    return SessionStateResponse.from_domain(
        service.get_state_snapshot(room_id, current_user.id)
    )


@router.post(
    "/rooms/{room_id}/answers",
    response_model=AnswerAcknowledgementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_answer(
    request: Request,
    room_id: UUID,
    payload: SubmitAnswerRequest,
    service: SessionService = Depends(get_session_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> AnswerAcknowledgementResponse:
    # Synchronous repository work runs in a thread; only the advisory
    # grading wakeup below awaits on the event loop.
    acknowledgement = await asyncio.to_thread(
        service.submit_answer,
        room_id=room_id,
        user_id=current_user.id,
        session_question_id=payload.session_question_id,
        selected_option_id=payload.selected_option_id,
        answer_text=payload.text,
    )
    if acknowledgement.grading_status == "PENDING":
        coordinator = getattr(request.app.state, "grading_coordinator", None)
        schedule = getattr(coordinator, "schedule_grading", None)
        if schedule is not None:
            try:
                await schedule()
            except Exception:
                pass
    return AnswerAcknowledgementResponse.from_domain(acknowledgement)


@router.get(
    "/rooms/{room_id}/state",
    response_model=SessionStateResponse,
)
def get_state_snapshot(
    room_id: UUID,
    service: SessionService = Depends(get_session_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SessionStateResponse:
    return SessionStateResponse.from_domain(
        service.get_state_snapshot(room_id, current_user.id)
    )


@router.get(
    "/rooms/{room_id}/sessions/{session_id}/review",
    response_model=SessionReviewResponse,
    status_code=status.HTTP_200_OK,
)
def get_session_review(
    room_id: UUID,
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> SessionReviewResponse:
    review = service.get_session_review(
        room_id=room_id,
        session_id=session_id,
        user_id=current_user.id,
    )
    return SessionReviewResponse.from_domain(review)
