"""Strict protocol-v2 command and event models for adaptive multiplayer quizzes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, TypeAdapter, model_validator
from pydantic_core import ValidationError

PROTOCOL_VERSION_V2 = 2
MAX_MESSAGE_BYTES = 16 * 1024
MAX_ACCESS_TOKEN_LENGTH = 8192


class ProtocolModel(BaseModel):
    """Base model keeping the wire contract closed and strict."""
    model_config = ConfigDict(extra="forbid", strict=True)


# --- Commands ---


class AuthenticatePayload(ProtocolModel):
    access_token: StrictStr = Field(
        min_length=1,
        max_length=MAX_ACCESS_TOKEN_LENGTH,
    )


class SetReadyPayload(ProtocolModel):
    ready: StrictBool


class PrepareQuizPayload(ProtocolModel):
    request_id: UUID


class SubmitAnswerPayload(ProtocolModel):
    session_question_id: UUID
    type: Literal["choice", "text"]
    option_id: StrictStr | None = Field(default=None, max_length=64)
    text: StrictStr | None = None

    @model_validator(mode="after")
    def validate_submission_shape(self) -> "SubmitAnswerPayload":
        # Discriminated v2 contract: `type` is required and carries only
        # `option_id` OR bounded nonblank `text`. The legacy
        # `selected_option_id` field does not exist here (extra="forbid").
        if self.type == "choice":
            if self.option_id is None or not self.option_id.strip():
                raise ValueError("Choice answers require a nonblank option_id.")
            if len(self.option_id.strip()) > 64:
                raise ValueError("option_id exceeds 64 characters.")
            if self.text is not None:
                raise ValueError("Provide either choice option or text answer, not both.")
            self.option_id = self.option_id.strip()
        else:
            if self.option_id is not None:
                raise ValueError("Provide either choice option or text answer, not both.")
            if self.text is None:
                raise ValueError("Text answers require nonblank text.")
            stripped = self.text.strip()
            if not stripped:
                raise ValueError("Text answers require nonblank text.")
            if len(stripped) > 1000:
                raise ValueError("Text answers exceed 1000 characters.")
            self.text = stripped
        return self


class EmptyPayload(ProtocolModel):
    """Payload for commands whose presence is required but has no fields."""


class AuthenticateCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["AUTHENTICATE"]
    payload: AuthenticatePayload


class SetReadyCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["SET_READY"]
    payload: SetReadyPayload


class StartSessionCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["START_SESSION"]
    payload: EmptyPayload


class PrepareQuizCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["PREPARE_QUIZ"]
    payload: PrepareQuizPayload


class RetryGradingCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["RETRY_GRADING"]
    payload: EmptyPayload


class SubmitAnswerCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["SUBMIT_ANSWER"]
    payload: SubmitAnswerPayload


class RequestStateCommandV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["REQUEST_STATE"]
    payload: EmptyPayload


ClientCommandV2: TypeAlias = (
    AuthenticateCommandV2
    | SetReadyCommandV2
    | StartSessionCommandV2
    | PrepareQuizCommandV2
    | RetryGradingCommandV2
    | SubmitAnswerCommandV2
    | RequestStateCommandV2
)

_CLIENT_COMMAND_ADAPTER_V2 = TypeAdapter(ClientCommandV2)
_COMMAND_TYPES_V2 = frozenset(
    {
        "AUTHENTICATE",
        "SET_READY",
        "START_SESSION",
        "PREPARE_QUIZ",
        "RETRY_GRADING",
        "SUBMIT_ANSWER",
        "REQUEST_STATE",
    }
)


class ProtocolV2Error(ValueError):
    def __init__(self, code: str = "protocol_error") -> None:
        super().__init__(code)
        self.code = code


def parse_client_command_v2(message: str | bytes) -> ClientCommandV2:
    raw_bytes = message if isinstance(message, bytes) else message.encode("utf-8")
    if len(raw_bytes) > MAX_MESSAGE_BYTES:
        raise ProtocolV2Error("payload_too_large")
    try:
        raw_value: object = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolV2Error("invalid_json") from error
    if not isinstance(raw_value, dict):
        raise ProtocolV2Error("invalid_payload")

    raw_version = raw_value.get("protocol_version")
    if type(raw_version) is not int or raw_version != PROTOCOL_VERSION_V2:
        raise ProtocolV2Error("unsupported_protocol_version")
    raw_type = raw_value.get("type")
    if not isinstance(raw_type, str) or raw_type not in _COMMAND_TYPES_V2:
        raise ProtocolV2Error("unknown_command_type")

    try:
        return _CLIENT_COMMAND_ADAPTER_V2.validate_json(raw_bytes)
    except ValidationError as error:
        raise ProtocolV2Error("validation_error") from error


# --- Server Events ---


class ConnectedPayload(ProtocolModel):
    server_time: datetime


class RoomStateParticipant(ProtocolModel):
    user_id: UUID
    display_name: StrictStr
    role: Literal["host", "member"]
    ready: StrictBool
    online: StrictBool


class RoomStatePayloadV2(ProtocolModel):
    room_id: UUID
    name: StrictStr
    join_code: StrictStr
    maximum_members: int
    viewer_role: Literal["host", "member"]
    participants: list[RoomStateParticipant]
    viewer_ready: StrictBool
    quiz_mode: StrictStr = "LEGACY_PHYSICS"
    education_level: StrictStr | None = None
    quiz_subject: StrictStr | None = None
    quiz_topic: StrictStr | None = None
    target_total_marks: int | None = None
    active_preparation_status: StrictStr | None = None
    active_preparation_version: int | None = None
    active_preparation_error_category: StrictStr | None = None


class QuestionOptionPayload(ProtocolModel):
    id: StrictStr
    label: StrictStr


class OpenQuestionPayloadV2(ProtocolModel):
    session_question_id: UUID
    prompt: StrictStr
    options: list[QuestionOptionPayload]
    question_number: int
    total_questions: int
    closes_at: datetime
    server_time: datetime
    question_type: StrictStr = "MULTIPLE_CHOICE"
    max_marks: int = 1
    original_extract: StrictStr | None = None


class RevealedQuestionPayloadV2(ProtocolModel):
    session_question_id: UUID
    prompt: StrictStr
    options: list[QuestionOptionPayload]
    question_number: int
    total_questions: int
    closes_at: datetime
    server_time: datetime
    correct_option_id: StrictStr | None = None
    question_type: StrictStr = "MULTIPLE_CHOICE"
    max_marks: int = 1
    worked_explanation: StrictStr = ""
    original_extract: StrictStr | None = None


class OpenOwnSubmissionPayloadV2(ProtocolModel):
    session_question_id: UUID
    selected_option_id: StrictStr | None = None
    answer_text: StrictStr | None = None
    grading_status: StrictStr = "GRADED"


class RevealedOwnSubmissionPayloadV2(ProtocolModel):
    session_question_id: UUID
    selected_option_id: StrictStr | None = None
    answer_text: StrictStr | None = None
    is_correct: StrictBool | None = None
    points: int | None = None
    earned_marks: int | None = None
    max_marks: int = 1
    grading_status: StrictStr = "GRADED"
    feedback: dict[str, Any] = Field(default_factory=dict)
    awarded_criterion_ids: list[str] = Field(default_factory=list)


class LeaderboardPayloadV2(ProtocolModel):
    user_id: UUID
    display_name: StrictStr
    total_points: int
    correct_answers: int
    rank: int
    earned_marks: int = 0
    total_available_marks: int = 5


class StateSnapshotPayloadV2(ProtocolModel):
    server_time: datetime
    room_state: RoomStatePayloadV2
    session_id: UUID | None
    viewer_participated: StrictBool
    state_version: int
    status: Literal["QUESTION_OPEN", "QUESTION_GRADING", "QUESTION_REVEAL", "FINISHED"] | None
    current_question_number: int | None
    total_question_count: int
    question: OpenQuestionPayloadV2 | RevealedQuestionPayloadV2 | None
    closes_at: datetime | None
    reveal_ends_at: datetime | None
    viewer_submission: OpenOwnSubmissionPayloadV2 | RevealedOwnSubmissionPayloadV2 | None
    leaderboard: list[LeaderboardPayloadV2]
    finished_at: datetime | None
    quiz_mode: StrictStr = "LEGACY_PHYSICS"
    total_available_marks: int = 5
    grading_retry_needed: StrictBool = False


class SessionReferencePayload(ProtocolModel):
    session_id: UUID
    state_version: int


class QuestionOpenedPayloadV2(ProtocolModel):
    session_id: UUID
    state_version: int
    question: OpenQuestionPayloadV2


class AnswerAcceptedPayloadV2(ProtocolModel):
    session_id: UUID
    state_version: int
    session_question_id: UUID
    selected_option_id: StrictStr | None = None
    answer_text: StrictStr | None = None
    grading_status: StrictStr = "GRADED"
    accepted_at: datetime


class QuestionRevealedPayloadV2(ProtocolModel):
    session_id: UUID
    state_version: int
    question: RevealedQuestionPayloadV2
    viewer_submission: RevealedOwnSubmissionPayloadV2 | None
    leaderboard: list[LeaderboardPayloadV2]


class SessionFinishedPayloadV2(ProtocolModel):
    session_id: UUID
    state_version: int
    leaderboard: list[LeaderboardPayloadV2]
    finished_at: datetime


class ErrorPayload(ProtocolModel):
    code: StrictStr = Field(min_length=1)
    message: StrictStr = Field(min_length=1)


# Event structures for V2
class ConnectedEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["CONNECTED"]
    payload: ConnectedPayload


class RoomStateEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["ROOM_STATE"]
    payload: RoomStatePayloadV2


class StateSnapshotEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["STATE_SNAPSHOT"]
    payload: StateSnapshotPayloadV2


class SessionStartedEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["SESSION_STARTED"]
    payload: SessionReferencePayload


class QuestionOpenedEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["QUESTION_OPENED"]
    payload: QuestionOpenedPayloadV2


class AnswerAcceptedEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["ANSWER_ACCEPTED"]
    payload: AnswerAcceptedPayloadV2


class QuestionRevealedEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["QUESTION_REVEALED"]
    payload: QuestionRevealedPayloadV2


class SessionFinishedEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["SESSION_FINISHED"]
    payload: SessionFinishedPayloadV2


class ErrorEventV2(ProtocolModel):
    protocol_version: Literal[2]
    type: Literal["ERROR"]
    payload: ErrorPayload


ServerEventV2: TypeAlias = (
    ConnectedEventV2
    | RoomStateEventV2
    | StateSnapshotEventV2
    | SessionStartedEventV2
    | QuestionOpenedEventV2
    | AnswerAcceptedEventV2
    | QuestionRevealedEventV2
    | SessionFinishedEventV2
    | ErrorEventV2
)


def serialize_event_v2(event: ServerEventV2) -> str:
    return json.dumps(
        event.model_dump(mode="json"),
        separators=(",", ":"),
    )


def error_event_v2(code: str, message: str) -> str:
    return serialize_event_v2(
        ErrorEventV2(
            protocol_version=PROTOCOL_VERSION_V2,
            type="ERROR",
            payload=ErrorPayload(code=code, message=message),
        )
    )
