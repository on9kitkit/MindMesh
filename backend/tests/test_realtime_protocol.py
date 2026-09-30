import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.domain.question import QuestionOption
from app.domain.quiz import PublicQuestion
from app.realtime.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    QuestionOpenedEvent,
    QuestionOpenedPayload,
    serialize_event,
    parse_client_command,
)
from app.realtime.controls import origin_is_allowed
from app.realtime.publisher import open_question_payload


ROOM_ID = UUID("11111111-1111-4111-8111-111111111111")
QUESTION_ID = UUID("22222222-2222-4222-8222-222222222222")


def _command(command_type: str, payload: object) -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "type": command_type,
            "payload": payload,
        }
    )


def test_protocol_v1_accepts_strict_commands() -> None:
    authenticate = parse_client_command(
        _command("AUTHENTICATE", {"access_token": "opaque-test-token"})
    )
    ready = parse_client_command(_command("SET_READY", {"ready": True}))
    start = parse_client_command(_command("START_SESSION", {}))
    answer = parse_client_command(
        _command(
            "SUBMIT_ANSWER",
            {
                "session_question_id": str(QUESTION_ID),
                "selected_option_id": "newton",
            },
        )
    )
    state = parse_client_command(_command("REQUEST_STATE", {}))

    assert authenticate.type == "AUTHENTICATE"
    assert ready.payload.ready is True
    assert start.type == "START_SESSION"
    assert answer.payload.session_question_id == QUESTION_ID
    assert state.type == "REQUEST_STATE"


@pytest.mark.parametrize(
    ("message", "code"),
    (
        (_command("REQUEST_STATE", {"user_id": str(ROOM_ID)}), "protocol_error"),
        (
            json.dumps(
                {
                    "protocol_version": 2,
                    "type": "REQUEST_STATE",
                    "payload": {},
                }
            ),
            "unsupported_protocol_version",
        ),
        (_command("UNKNOWN", {}), "protocol_error"),
        (_command("SET_READY", {"ready": True, "user_id": str(ROOM_ID)}), "protocol_error"),
        (_command("SET_READY", {}), "protocol_error"),
        (
            _command(
                "SUBMIT_ANSWER",
                {"session_question_id": "not-a-uuid", "selected_option_id": "a"},
            ),
            "protocol_error",
        ),
        (
            _command(
                "SUBMIT_ANSWER",
                {"session_question_id": str(QUESTION_ID), "selected_option_id": 1},
            ),
            "protocol_error",
        ),
    ),
)
def test_invalid_commands_are_rejected_without_details(
    message: str,
    code: str,
) -> None:
    with pytest.raises(ProtocolError) as error:
        parse_client_command(message)

    assert error.value.code == code


def test_malformed_and_oversized_messages_are_rejected() -> None:
    with pytest.raises(ProtocolError):
        parse_client_command("{")
    with pytest.raises(ProtocolError):
        parse_client_command("x" * (MAX_MESSAGE_BYTES + 1))


def test_origin_policy_allows_native_and_configured_web_origins_only() -> None:
    allowed = (
        "http://localhost:8081",
        "http://localhost:8082",
        "http://127.0.0.1:8000",
    )

    assert origin_is_allowed(None, allowed)
    assert origin_is_allowed("http://localhost:8081", allowed)
    assert origin_is_allowed("http://127.0.0.1:8000", allowed)
    assert not origin_is_allowed("http://example.test", allowed)


def test_open_question_event_cannot_leak_answer_fields() -> None:
    question = PublicQuestion(
        id=QUESTION_ID,
        prompt="What is the SI unit of force?",
        options=(
            QuestionOption(id="joule", label="Joule"),
            QuestionOption(id="newton", label="Newton"),
        ),
        question_number=1,
        total_questions=5,
        closes_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    event = QuestionOpenedEvent(
        protocol_version=1,
        type="QUESTION_OPENED",
        payload=QuestionOpenedPayload(
            session_id=ROOM_ID,
            state_version=1,
            question=open_question_payload(
                question,
                server_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
            ),
        ),
    )

    encoded = json.loads(serialize_event(event))
    assert encoded["payload"]["question"]["session_question_id"] == str(QUESTION_ID)
    assert "correct_option_id" not in encoded["payload"]["question"]
    assert "is_correct" not in encoded["payload"]["question"]
    assert "points" not in encoded["payload"]["question"]
