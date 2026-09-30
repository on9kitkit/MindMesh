import asyncio
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, status

from app.api.dependencies import CurrentUser, get_current_user
from app.domain.errors import (
    AiGenerationUnavailableError,
    AlreadyRoomMemberError,
    PreparationFailedError,
    RoomClosedError,
    RoomFullError,
    RoomJoinRateLimitedError,
    RoomJoinUnavailableError,
    RoomNotFoundError,
    SessionAlreadyActiveError,
    UserAlreadyInAnotherRoomError,
)
from app.realtime.publisher import RealtimePublisher
from app.schemas.rooms import (
    CreateRoomRequest,
    HealthResponse,
    JoinByCodeRequest,
    JoinByCodeResponse,
    JoinRoomRequest,
    MemberResponse,
    PrepareQuizRequest,
    QuizPreparationResponse,
    RoomMemberListItem,
    RoomMembersResponse,
    RoomResponse,
)
from app.services.quiz_preparation_service import QuizPreparationService
from app.services.rooms import RoomService
from app.services.join_throttle import JoinFailureThrottle

router = APIRouter()


def get_room_service(request: Request) -> RoomService:
    return request.app.state.room_service


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["rooms"],
)
def create_room(
    payload: CreateRoomRequest,
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> RoomResponse:
    quiz_mode = "LEGACY_PHYSICS"
    education_level = None
    quiz_subject = None
    quiz_topic = None
    target_total_marks = None

    if payload.quiz_settings is not None:
        quiz_mode = "ADAPTIVE"
        education_level = payload.quiz_settings.level.upper()
        quiz_subject = payload.quiz_settings.subject
        quiz_topic = payload.quiz_settings.topic
        target_total_marks = payload.quiz_settings.total_marks

    room = service.create_room(
        name=payload.name,
        maximum_members=payload.maximum_members,
        owner_id=current_user.id,
        owner_display_name=current_user.display_name,
        quiz_mode=quiz_mode,
        education_level=education_level,
        quiz_subject=quiz_subject,
        quiz_topic=quiz_topic,
        target_total_marks=target_total_marks,
    )
    return RoomResponse.from_domain(
        room,
        member_count=service.count_room_members(room.id),
    )


def get_quiz_preparation_service(request: Request) -> QuizPreparationService:
    service = getattr(request.app.state, "quiz_preparation_service", None)
    if service is None:
        raise AiGenerationUnavailableError
    return service


@router.post(
    "/rooms/{room_id}/quiz-preparations",
    response_model=QuizPreparationResponse,
    status_code=status.HTTP_200_OK,
    tags=["rooms"],
)
async def prepare_quiz(
    request: Request,
    room_id: UUID,
    payload: PrepareQuizRequest,
    service: QuizPreparationService = Depends(get_quiz_preparation_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> QuizPreparationResponse:
    try:
        prep = await service.prepare_quiz(
            room_id=room_id,
            request_id=payload.request_id,
            user_id=current_user.id,
        )
    except (AiGenerationUnavailableError, PreparationFailedError):
        # Terminal failure must still become observable to room sockets:
        # broadcast durable state when a publisher is wired, then re-raise
        # for the mapped safe HTTP error. Snapshots re-read durable truth.
        publisher = getattr(request.app.state, "realtime_publisher", None)
        if isinstance(publisher, RealtimePublisher):
            try:
                await publisher.send_room_state_to_all(room_id)
            except Exception:
                pass
        raise
    publisher = getattr(request.app.state, "realtime_publisher", None)
    if isinstance(publisher, RealtimePublisher):
        try:
            await publisher.send_room_state_to_all(room_id)
        except Exception:
            pass
    return QuizPreparationResponse(
        id=prep.id,
        room_id=prep.room_id,
        request_id=prep.request_id,
        status=prep.status.value,
        state_version=prep.state_version,
        error_category=prep.error_category,
    )

@router.post(
    "/rooms/join",
    response_model=JoinByCodeResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["rooms"],
)
async def join_room_by_code(
    request: Request,
    payload: JoinByCodeRequest,
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> JoinByCodeResponse:
    throttle = getattr(request.app.state, "join_failure_throttle", None)
    if not isinstance(throttle, JoinFailureThrottle):
        raise RuntimeError("join throttle is not configured")
    allowed, retry_after_seconds = throttle.allow(current_user.id)
    if not allowed:
        raise RoomJoinRateLimitedError(retry_after_seconds or 1)
    try:
        member = await asyncio.to_thread(
            service.join_room_by_code,
            join_code=payload.join_code,
            user_id=current_user.id,
            display_name=current_user.display_name,
        )
    except _NON_ENUMERATING_JOIN_FAILURES:
        throttle.record_failure(current_user.id)
        raise RoomJoinUnavailableError from None
    throttle.record_success(current_user.id)
    room = await asyncio.to_thread(service.get_room, member.room_id)
    response = JoinByCodeResponse(
        room=RoomResponse.from_domain(
            room,
            member_count=await asyncio.to_thread(service.count_room_members, room.id),
        ),
        member=MemberResponse.from_domain(member),
    )
    await _publish_room_state(request, member.room_id)
    return response


_NON_ENUMERATING_JOIN_FAILURES = (
    AlreadyRoomMemberError,
    RoomClosedError,
    RoomFullError,
    RoomNotFoundError,
    SessionAlreadyActiveError,
    UserAlreadyInAnotherRoomError,
)


@router.get("/rooms/{room_id}", response_model=RoomResponse, tags=["rooms"])
def get_room(
    room_id: UUID,
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> RoomResponse:
    service.require_active_room_member(room_id=room_id, user_id=current_user.id)
    room = service.get_open_room(room_id)
    return RoomResponse.from_domain(
        room,
        member_count=service.count_room_members(room.id),
    )


@router.post(
    "/rooms/{room_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["members"],
)
async def join_room(
    request: Request,
    room_id: UUID,
    payload: JoinRoomRequest | None = Body(default=None),
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> MemberResponse:
    member = await asyncio.to_thread(
        service.join_room,
        room_id=room_id,
        user_id=current_user.id,
        display_name=current_user.display_name,
    )
    await _publish_room_state(request, room_id)
    return MemberResponse.from_domain(member)


@router.post(
    "/rooms/{room_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["rooms"],
)
async def leave_room(
    request: Request,
    room_id: UUID,
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    await asyncio.to_thread(
        service.leave_room,
        room_id=room_id,
        user_id=current_user.id,
    )
    publisher = getattr(request.app.state, "realtime_publisher", None)
    if isinstance(publisher, RealtimePublisher):
        try:
            await publisher.publish_member_left(room_id, current_user.id)
        except Exception:
            pass


@router.post(
    "/rooms/{room_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["rooms"],
)
async def close_room(
    request: Request,
    room_id: UUID,
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    await asyncio.to_thread(
        service.close_room,
        room_id=room_id,
        user_id=current_user.id,
    )
    publisher = getattr(request.app.state, "realtime_publisher", None)
    if isinstance(publisher, RealtimePublisher):
        try:
            await publisher.publish_room_closed(room_id)
        except Exception:
            pass


async def _publish_room_state(request: Request, room_id: UUID) -> None:
    publisher = getattr(request.app.state, "realtime_publisher", None)
    if isinstance(publisher, RealtimePublisher):
        try:
            await publisher.send_room_state_to_all(room_id)
        except Exception:
            return


@router.get(
    "/rooms/{room_id}/members",
    response_model=RoomMembersResponse,
    tags=["members"],
)
def list_room_members(
    room_id: UUID,
    service: RoomService = Depends(get_room_service),
    current_user: CurrentUser = Depends(get_current_user),
) -> RoomMembersResponse:
    room = service.get_room(room_id)
    service.require_active_room_member(
        room_id=room_id,
        user_id=current_user.id,
    )
    members = service.list_room_members(room_id)
    return RoomMembersResponse(
        room_id=room.id,
        members=[RoomMemberListItem.from_domain(member) for member in members],
        member_count=len(members),
        maximum_members=room.maximum_members,
    )
