import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


SafetyReportReason = Literal[
    "inappropriate_display_name",
    "disruptive_room_behaviour",
    "other_safety_concern",
]


class SafetyReportCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    reported_user_id: UUID
    room_id: UUID
    reason: SafetyReportReason
    details: str | None = Field(default=None, max_length=500)

    @field_validator("details")
    @classmethod
    def normalize_details(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if any(
            unicodedata.category(character) in {"Cc", "Cf"}
            for character in normalized
        ):
            raise ValueError("details must not contain control characters")
        return normalized


class SafetyReportResponse(BaseModel):
    status: Literal["report_received"]
