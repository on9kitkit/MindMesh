"""Strict protocol-v1 command and event models for the room WebSocket."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, TypeAdapter
from pydantic_core import ValidationError

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 16 * 1024
MAX_ACCESS_TOKEN_LENGTH = 8192


class ProtocolModel(BaseModel):
    """Base model that keeps the wire contract closed and strict."""

    model_config = ConfigDict(extra="forbid", strict=True)


class AuthenticatePayload(ProtocolModel):
    access_token: StrictStr = Field(
        min_length=1,
        max_length=MAX_ACCESS_TOKEN_LENGTH,
    )


class SetReadyPayload(ProtocolModel):
    ready: StrictBool


class EmptyPayload(ProtocolModel):
    """Payload for commands whose presence is required but has no fields."""


class AuthenticateCommand(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["AUTHENTICATE"]
    payload: AuthenticatePayload


class SetReadyCommand(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["SET_READY"]
    payload: SetReadyPayload


class StartSessionCommand(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["START_SESSION"]
    payload: EmptyPayload


class SubmitAnswerPayload(ProtocolModel):
    session_question_id: UUID
    selected_option_id: StrictStr = Field(min_length=1, max_length=64)


class SubmitAnswerCommand(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["SUBMIT_ANSWER"]
    payload: SubmitAnswerPayload


class RequestStateCommand(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["REQUEST_STATE"]
    payload: EmptyPayload


ClientCommand: TypeAlias = (
    AuthenticateCommand
    | SetReadyCommand
    | StartSessionCommand
    | SubmitAnswerCommand
    | RequestStateCommand
)

_CLIENT_COMMAND_ADAPTER = TypeAdapter(ClientCommand)
_COMMAND_TYPES = frozenset(
    {
        "AUTHENTICATE",
        "SET_READY",
        "START_SESSION",
        "SUBMIT_ANSWER",
        "REQUEST_STATE",
    }
)


class ProtocolError(ValueError):
    """Safe parse error that can be returned over the realtime protocol."""

    def __init__(self, code: str = "protocol_error") -> None:
        super().__init__(code)
        self.code = code


def parse_client_command(message: str | bytes) -> ClientCommand:
    """Parse one bounded, versioned, strictly shaped client command."""

    raw_bytes = message if isinstance(message, bytes) else message.encode("utf-8")
    if len(raw_bytes) > MAX_MESSAGE_BYTES:
        raise ProtocolError
    try:
        raw_value: object = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError from error
    if not isinstance(raw_value, dict):
        raise ProtocolError

    raw_version = raw_value.get("protocol_version")
    if type(raw_version) is not int or raw_version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol_version")
    raw_type = raw_value.get("type")
    if not isinstance(raw_type, str) or raw_type not in _COMMAND_TYPES:
        raise ProtocolError

    try:
        return _CLIENT_COMMAND_ADAPTER.validate_json(raw_bytes)
    except ValidationError as error:
        raise ProtocolError from error


class ConnectedPayload(ProtocolModel):
    server_time: datetime


class RoomStateParticipant(ProtocolModel):
    user_id: UUID
    display_name: StrictStr
    role: Literal["host", "member"]
    ready: StrictBool
    online: StrictBool


class RoomStatePayload(ProtocolModel):
    room_id: UUID
    name: StrictStr
    join_code: StrictStr
    maximum_members: int
    viewer_role: Literal["host", "member"]
    participants: list[RoomStateParticipant]
    viewer_ready: StrictBool


class QuestionOptionPayload(ProtocolModel):
    id: StrictStr
    label: StrictStr


class OpenQuestionPayload(ProtocolModel):
    session_question_id: UUID
    prompt: StrictStr
    options: list[QuestionOptionPayload]
    question_number: int
    total_questions: int
    closes_at: datetime
    server_time: datetime


class OpenOwnSubmissionPayload(ProtocolModel):
    session_question_id: UUID
    selected_option_id: StrictStr


class RevealedOwnSubmissionPayload(ProtocolModel):
    session_question_id: UUID
    selected_option_id: StrictStr
    is_correct: StrictBool
    points: int


class RevealedQuestionPayload(ProtocolModel):
    session_question_id: UUID
    prompt: StrictStr
    options: list[QuestionOptionPayload]
    question_number: int
    total_questions: int
    closes_at: datetime
    server_time: datetime
    correct_option_id: StrictStr


class LeaderboardPayload(ProtocolModel):
    user_id: UUID
    display_name: StrictStr
    total_points: int
    correct_answers: int
    rank: int


class StateSnapshotPayload(ProtocolModel):
    server_time: datetime
    room_state: RoomStatePayload
    session_id: UUID | None
    viewer_participated: StrictBool
    state_version: int
    status: Literal["QUESTION_OPEN", "QUESTION_REVEAL", "FINISHED"] | None
    current_question_number: int | None
    total_question_count: int
    question: OpenQuestionPayload | RevealedQuestionPayload | None
    closes_at: datetime | None
    reveal_ends_at: datetime | None
    viewer_submission: OpenOwnSubmissionPayload | RevealedOwnSubmissionPayload | None
    leaderboard: list[LeaderboardPayload]
    finished_at: datetime | None


class SessionReferencePayload(ProtocolModel):
    session_id: UUID
    state_version: int


class QuestionOpenedPayload(ProtocolModel):
    session_id: UUID
    state_version: int
    question: OpenQuestionPayload


class AnswerAcceptedPayload(ProtocolModel):
    session_id: UUID
    state_version: int
    session_question_id: UUID
    selected_option_id: StrictStr
    accepted_at: datetime


class QuestionRevealedPayload(ProtocolModel):
    session_id: UUID
    state_version: int
    question: RevealedQuestionPayload
    viewer_submission: RevealedOwnSubmissionPayload | None
    leaderboard: list[LeaderboardPayload]


class SessionFinishedPayload(ProtocolModel):
    session_id: UUID
    state_version: int
    leaderboard: list[LeaderboardPayload]
    finished_at: datetime


class ErrorPayload(ProtocolModel):
    code: StrictStr = Field(min_length=1)
    message: StrictStr = Field(min_length=1)


class ConnectedEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["CONNECTED"]
    payload: ConnectedPayload


class RoomStateEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["ROOM_STATE"]
    payload: RoomStatePayload


class StateSnapshotEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["STATE_SNAPSHOT"]
    payload: StateSnapshotPayload


class SessionStartedEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["SESSION_STARTED"]
    payload: SessionReferencePayload


class QuestionOpenedEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["QUESTION_OPENED"]
    payload: QuestionOpenedPayload


class AnswerAcceptedEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["ANSWER_ACCEPTED"]
    payload: AnswerAcceptedPayload


class QuestionRevealedEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["QUESTION_REVEALED"]
    payload: QuestionRevealedPayload


class SessionFinishedEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["SESSION_FINISHED"]
    payload: SessionFinishedPayload


class ErrorEvent(ProtocolModel):
    protocol_version: Literal[1]
    type: Literal["ERROR"]
    payload: ErrorPayload


ServerEvent: TypeAlias = (
    ConnectedEvent
    | RoomStateEvent
    | StateSnapshotEvent
    | SessionStartedEvent
    | QuestionOpenedEvent
    | AnswerAcceptedEvent
    | QuestionRevealedEvent
    | SessionFinishedEvent
    | ErrorEvent
)


def serialize_event(event: ServerEvent) -> str:
    """Serialize a validated event without adding wire fields implicitly."""

    return json.dumps(
        event.model_dump(mode="json"),
        separators=(",", ":"),
    )


def error_event(code: str, message: str) -> str:
    """Build a safe ERROR event for a known application error."""

    return serialize_event(
        ErrorEvent(
            protocol_version=PROTOCOL_VERSION,
            type="ERROR",
            payload=ErrorPayload(code=code, message=message),
        )
    )
