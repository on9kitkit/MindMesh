from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.constants import ROOM_MAXIMUM_MEMBERS, ROOM_MINIMUM_MEMBERS
from app.domain.display_name import normalize_display_name
from app.domain.errors import InvalidDisplayNameError, InvalidRoomDataError
from app.services.rooms import normalize_join_code
from app.domain.member import RoomMember
from app.domain.room import Room


class QuizSettingsRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    mode: Literal["adaptive"]
    level: Literal["gcse"]
    subject: str = Field(min_length=1, max_length=32)
    topic: str = Field(min_length=1, max_length=40)
    total_marks: int = Field(default=20, ge=5, le=40)


class CreateRoomRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=3, max_length=60)
    maximum_members: int = Field(
        ge=ROOM_MINIMUM_MEMBERS,
        le=ROOM_MAXIMUM_MEMBERS,
    )
    quiz_settings: QuizSettingsRequest | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("name must not be blank")
        return value


class HealthResponse(BaseModel):
    status: Literal["ok"]


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    join_code: str
    maximum_members: int
    member_count: int
    quiz_mode: str = "LEGACY_PHYSICS"
    education_level: str | None = None
    quiz_subject: str | None = None
    quiz_topic: str | None = None
    target_total_marks: int | None = None

    @classmethod
    def from_domain(cls, room: Room, *, member_count: int) -> "RoomResponse":
        return cls(
            id=room.id,
            name=room.name,
            join_code=room.join_code,
            maximum_members=room.maximum_members,
            member_count=member_count,
            quiz_mode=room.quiz_mode,
            education_level=room.education_level,
            quiz_subject=room.quiz_subject,
            quiz_topic=room.quiz_topic,
            target_total_marks=room.target_total_marks,
        )


class PrepareQuizRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: UUID = Field(strict=False)


class QuizPreparationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    request_id: UUID
    status: str
    state_version: int
    error_category: str | None = None

class JoinRoomRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    """Empty request boundary; identity and profile are server-derived."""


class JoinByCodeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    join_code: str = Field(min_length=6, max_length=6)

    @field_validator("join_code")
    @classmethod
    def normalize_join_code(cls, value: str) -> str:
        try:
            return normalize_join_code(value)
        except InvalidRoomDataError:
            raise ValueError("join_code must contain six letters or digits") from None


class ProfileRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    display_name: str

    @field_validator("display_name")
    @classmethod
    def normalize_and_validate_display_name(cls, value: str) -> str:
        try:
            return normalize_display_name(value)
        except InvalidDisplayNameError:
            raise ValueError("Choose a different display name.") from None


class ProfileResponse(BaseModel):
    id: UUID
    display_name: str


class MemberResponse(BaseModel):
    user_id: UUID
    display_name: str
    room_id: UUID

    @classmethod
    def from_domain(cls, member: RoomMember) -> "MemberResponse":
        return cls(
            user_id=member.user_id,
            display_name=member.display_name,
            room_id=member.room_id,
        )


class JoinByCodeResponse(BaseModel):
    room: RoomResponse
    member: MemberResponse


class RoomMemberListItem(BaseModel):
    user_id: UUID
    display_name: str

    @classmethod
    def from_domain(cls, member: RoomMember) -> "RoomMemberListItem":
        return cls(
            user_id=member.user_id,
            display_name=member.display_name,
        )


class RoomMembersResponse(BaseModel):
    room_id: UUID
    members: list[RoomMemberListItem]
    member_count: int
    maximum_members: int
