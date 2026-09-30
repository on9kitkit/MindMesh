from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    CurrentUser,
    get_current_identity,
    get_current_user,
    get_user_repository,
)
from app.repositories.users import UserRepository
from app.schemas.rooms import ProfileRequest, ProfileResponse, RoomResponse
from app.services.rooms import RoomService

router = APIRouter(prefix="/me", tags=["profile"])


def get_room_service(request: Request) -> RoomService:
    return request.app.state.room_service


@router.get("", response_model=ProfileResponse)
def get_profile(
    current_user: CurrentUser = Depends(get_current_user),
) -> ProfileResponse:
    profile = current_user.profile
    if profile is None:
        raise RuntimeError("get_current_user must provide a profile")
    return ProfileResponse(id=profile.id, display_name=profile.display_name)


@router.put("/profile", response_model=ProfileResponse)
def update_profile(
    payload: ProfileRequest,
    current_user: CurrentUser = Depends(get_current_identity),
    user_repository: UserRepository = Depends(get_user_repository),
) -> ProfileResponse:
    profile = user_repository.upsert_profile(current_user.id, payload.display_name)
    return ProfileResponse(id=profile.id, display_name=profile.display_name)


@router.get("/active-room", response_model=RoomResponse | None)
def get_active_room(
    current_user: CurrentUser = Depends(get_current_user),
    room_service: RoomService = Depends(get_room_service),
) -> RoomResponse | None:
    room = room_service.get_active_room_for_user(current_user.id)
    if room is None:
        return None
    return RoomResponse.from_domain(
        room,
        member_count=room_service.count_room_members(room.id),
    )
