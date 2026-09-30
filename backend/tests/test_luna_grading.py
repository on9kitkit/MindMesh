"""Tests for Luna written-answer rubric grading: Responses contract, coordinator, v2 protocol, v2 socket."""

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.auth import FakeAuthVerifier
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.session_question import SessionQuestionModel
from app.domain.adaptive_quiz import WrittenCriterion, WrittenRubric
from app.domain.errors import InvalidAnswerTextError, RoomOwnerRequiredError
from app.domain.member import RoomMember
from app.domain.room import Room
from app.domain.quiz import QuizSession
from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.verification import FakeQuizContentVerifier
from app.grading.coordinator import GradingCoordinator
from app.grading.fake_grader import FakeWrittenAnswerGrader
from app.grading.openai_grader import OPENAI_API_URL, OpenAiWrittenAnswerGrader
from app.grading.protocol import (
    MAX_GRADING_LEASE_SECONDS,
    GradingAuthError,
    GradingMalformedError,
    GradingRateLimitedError,
    GradingRefusalError,
    GradingRequest,
    GradingResult,
    GradingTimeoutError,
    GradingUnavailableError,
)
from app.main import create_app
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_preparations import (
    PostgresQuizPreparationRepository,
)
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.realtime.protocol_v2 import (
    ClientCommandV2,
    PROTOCOL_VERSION_V2,
    ProtocolV2Error,
    error_event_v2,
    parse_client_command_v2,
    serialize_event_v2,
)
from app.services.quiz_preparation_service import QuizPreparationService
from app.services.rooms import RoomService
from app.services.sessions import SessionService
from app.schemas.quiz import SubmitAnswerRequest
from tests.conftest import OWNER_ID, OWNER_TOKEN

OTHER_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
OTHER_TOKEN = "test-other-token"

MODEL_ID = "gpt-6-luna"
RESPONSES_URL = "https://api.openai.com/v1/responses"


def test_http_preparation_fallback_broadcasts_generating_then_ready_to_peer(postgres_database, auth_verifier):
    from fastapi.testclient import TestClient
    from tests.conftest import auth_headers
    app, service = _v2_app(postgres_database, auth_verifier)
    room_id = _make_v2_room(service, PostgresRoomRepository(postgres_database.session_factory))
    PostgresMembershipRepository(postgres_database.session_factory).add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Peer"))
    with TestClient(app) as client, client.websocket_connect(f"/ws/rooms/{room_id}") as peer:
        peer.send_json({"protocol_version": 2, "type": "AUTHENTICATE", "payload": {"access_token": OTHER_TOKEN}})
        assert peer.receive_json()["type"] == "CONNECTED"
        assert peer.receive_json()["type"] == "STATE_SNAPSHOT"
        assert peer.receive_json()["type"] == "ROOM_STATE"
        response = client.post(f"/rooms/{room_id}/quiz-preparations", json={"request_id": str(uuid4())}, headers=auth_headers())
        assert response.status_code == 200
        assert response.json()["status"] == "GENERATING"
        generating = peer.receive_json()
        assert generating["type"] == "ROOM_STATE"
        assert generating["payload"]["active_preparation_status"] == "GENERATING"
        ready = None
        for _ in range(4):
            frame = peer.receive_json()
            assert frame["type"] == "ROOM_STATE"
            if frame["payload"]["active_preparation_status"] == "READY":
                ready = frame
                break
        assert ready is not None
        assert ready["payload"]["active_preparation_version"] > generating["payload"]["active_preparation_version"]


def _rubric() -> WrittenRubric:
    return WrittenRubric(
        criteria=(
            WrittenCriterion(
                id="c1",
                marks=2,
                marking_point="Object remains at rest or uniform velocity",
                accepted_meaning="Constant velocity without resultant force",
                spelling_sensitive=False,
                explanation="Must mention constant velocity.",
            ),
            WrittenCriterion(
                id="c2",
                marks=1,
                marking_point="Names the unit Newton",
                accepted_meaning="Newton",
                spelling_sensitive=True,
                explanation="Must spell Newton correctly.",
            ),
        )
    )


def _grading_request(answer: str = "Constant velocity without resultant force, measured in Newton.") -> GradingRequest:
    return GradingRequest(
        question_prompt="State Newton's first law.",
        original_extract=None,
        student_answer=answer,
        max_marks=3,
        rubric=_rubric(),
    )


def _responses_envelope(text_payload: str) -> dict:
    return {
        "id": "resp_test_1",
        "status": "completed",
        "error": None,
        "output": [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text_payload}],
            }
        ],
    }


# --- Grader Responses API contract ---


@pytest.mark.anyio
async def test_grader_missing_key_is_unavailable() -> None:
    grader = OpenAiWrittenAnswerGrader(api_key="")
    assert grader.is_available is False
    with pytest.raises(GradingUnavailableError, match="OPENAI_API_KEY is not configured"):
        await grader.grade_written_answer(_grading_request())


def test_grader_api_key_never_leaks_via_repr_or_wrapper() -> None:
    canary = "sk-CANARY-GRADING-KEY-1a2b3c"
    grader = OpenAiWrittenAnswerGrader(api_key=canary)
    assert grader.is_available is True
    assert canary not in repr(grader)
    assert canary not in repr(grader._api_key)
    assert canary not in str(grader._api_key)


@pytest.mark.anyio
async def test_grader_uses_responses_contract_without_identity_or_tools() -> None:
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        captured.update(data)
        captured["_url"] = str(request.url)
        captured["_auth"] = request.headers.get("authorization", "")
        body = json.dumps(
            {"awarded_criterion_ids": ["c1"], "feedback": "Good effort."}
        )
        return httpx.Response(200, json=_responses_envelope(body))

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
    result = await grader.grade_written_answer(_grading_request())

    assert captured["_url"] == RESPONSES_URL
    assert OPENAI_API_URL == RESPONSES_URL
    assert captured["model"] == MODEL_ID
    assert captured["store"] is False
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert isinstance(captured.get("input"), list)
    assert captured.get("max_output_tokens") == 1024
    for forbidden in (
        "messages",
        "response_format",
        "tools",
        "tool_choice",
        "previous_response_id",
        "conversation",
        "max_completion_tokens",
    ):
        assert forbidden not in captured
    # Privacy: identity-free request body carries no profile/room/session IDs.
    serialized = json.dumps(captured)
    assert "11111111" not in serialized
    assert str(OTHER_USER_ID) not in serialized
    assert "Bearer" not in serialized or captured["_auth"].startswith("Bearer ")
    assert result.awarded_criterion_ids == ("c1",)


@pytest.mark.anyio
async def test_grader_rejects_unknown_and_duplicate_ids_as_malformed() -> None:
    for awarded in (["c1", "unknown-id"], ["c1", "c1"], ["c1", 42]):
        def mock_handler(request: httpx.Request, awarded=awarded) -> httpx.Response:
            body = json.dumps(
                {"awarded_criterion_ids": awarded, "feedback": "Well done."}
            )
            return httpx.Response(200, json=_responses_envelope(body))

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
        with pytest.raises(GradingMalformedError):
            await grader.grade_written_answer(_grading_request())


@pytest.mark.anyio
async def test_grader_rejects_invalid_feedback_shape_as_malformed() -> None:
    for feedback in (None, 123, {"text": "hi"}, ["hi"]):
        def mock_handler(request: httpx.Request, feedback=feedback) -> httpx.Response:
            body = json.dumps(
                {"awarded_criterion_ids": ["c1"], "feedback": feedback}
            )
            return httpx.Response(200, json=_responses_envelope(body))

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
        with pytest.raises(GradingMalformedError):
            await grader.grade_written_answer(_grading_request())


@pytest.mark.anyio
async def test_grader_rejects_non_object_payload_as_malformed() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_responses_envelope(json.dumps(["c1"])))

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
    with pytest.raises(GradingMalformedError):
        await grader.grade_written_answer(_grading_request())


@pytest.mark.anyio
async def test_grader_enforces_spelling_sensitive_criterion_on_server() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps(
            {"awarded_criterion_ids": ["c1", "c2"], "feedback": "Well done."}
        )
        return httpx.Response(200, json=_responses_envelope(body))

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
    # Misspelled "Newtun": Luna cannot waive the spelling-sensitive criterion.
    with pytest.raises(GradingMalformedError):
        await grader.grade_written_answer(
            _grading_request("Constant velocity without resultant force, unit Newtun.")
        )


@pytest.mark.anyio
async def test_grader_refusal_is_explicit() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_r",
                "status": "completed",
                "error": None,
                "output": [{"type": "refusal", "refusal": "Cannot assess this."}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
    with pytest.raises(GradingRefusalError, match="refused"):
        await grader.grade_written_answer(_grading_request())


def _grading_envelope(output: object, status: object = "completed") -> dict:
    return {"id": "resp_x", "status": status, "error": None, "output": output}


@pytest.mark.anyio
async def test_grader_envelope_refusal_wins_and_ambiguity_rejected() -> None:
    good_text = json.dumps({"awarded_criterion_ids": ["c1"], "feedback": "Good."})
    good_message = {
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": good_text}],
    }

    async def _grade(body: object) -> object:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))
        )
        return await OpenAiWrittenAnswerGrader(
            api_key="test_key", client=client
        ).grade_written_answer(_grading_request())

    # Refusal alongside output is still a refusal; refusal content never surfaces.
    with pytest.raises(GradingRefusalError):
        await _grade(
            _grading_envelope(
                [
                    {"type": "refusal", "refusal": "CANARY_REFUSAL_TEXT"},
                    good_message,
                ]
            )
        )
    # Two output texts are ambiguous and rejected.
    with pytest.raises(GradingMalformedError):
        await _grade(
            _grading_envelope(
                [
                    good_message,
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": good_text}],
                    },
                ]
            )
        )
    # Missing/unknown statuses are malformed even when output exists.
    with pytest.raises(GradingMalformedError):
        await _grade({"id": "r", "error": None, "output": [good_message]})
    with pytest.raises(GradingMalformedError):
        await _grade(
            {"id": "r", "status": "queued", "error": None, "output": [good_message]}
        )
    # Malformed containers are rejected.
    with pytest.raises(GradingMalformedError):
        await _grade(_grading_envelope(["not-an-object"]))
    with pytest.raises(GradingMalformedError):
        await _grade(
            _grading_envelope(
                [
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": "not-a-list",
                    }
                ]
            )
        )


@pytest.mark.anyio
async def test_grader_incomplete_and_failed_statuses() -> None:
    incomplete = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"id": "r", "status": "incomplete", "error": None, "output": []},
            )
        )
    )
    with pytest.raises(GradingMalformedError, match="incomplete"):
        await OpenAiWrittenAnswerGrader(api_key="k", client=incomplete).grade_written_answer(
            _grading_request()
        )

    failed = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "id": "r",
                    "status": "failed",
                    "error": {"code": "server_error", "message": "boom"},
                    "output": [],
                },
            )
        )
    )
    with pytest.raises(Exception):
        await OpenAiWrittenAnswerGrader(api_key="k", client=failed).grade_written_answer(
            _grading_request()
        )

    empty = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"id": "r", "status": "completed", "error": None, "output": []},
            )
        )
    )
    with pytest.raises(GradingMalformedError, match="empty"):
        await OpenAiWrittenAnswerGrader(api_key="k", client=empty).grade_written_answer(
            _grading_request()
        )


@pytest.mark.anyio
async def test_grader_http_and_transport_failures() -> None:
    auth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(401, json={}))
    )
    with pytest.raises(GradingAuthError):
        await OpenAiWrittenAnswerGrader(api_key="k", client=auth_client).grade_written_answer(
            _grading_request()
        )

    rate_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(429, json={}))
    )
    with pytest.raises(GradingRateLimitedError):
        await OpenAiWrittenAnswerGrader(api_key="k", client=rate_client).grade_written_answer(
            _grading_request()
        )

    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    timeout_client = httpx.AsyncClient(transport=httpx.MockTransport(_timeout))
    with pytest.raises(GradingTimeoutError):
        await OpenAiWrittenAnswerGrader(api_key="k", client=timeout_client).grade_written_answer(
            _grading_request()
        )


@pytest.mark.anyio
async def test_fake_grader_covers_failure_modes_deterministically() -> None:
    assert (await FakeWrittenAnswerGrader(always_award_all=True).grade_written_answer(
        _grading_request()
    )).awarded_criterion_ids == ("c1", "c2")
    assert (await FakeWrittenAnswerGrader(never_award_any=True).grade_written_answer(
        _grading_request()
    )).awarded_criterion_ids == ()
    for kwargs, error in (
        ({"is_available": False}, GradingUnavailableError),
        ({"simulate_timeout": True}, GradingTimeoutError),
        ({"simulate_refusal": True}, GradingRefusalError),
        ({"simulate_rate_limit": True}, GradingRateLimitedError),
        ({"simulate_auth_error": True}, GradingAuthError),
        ({"simulate_malformed": True}, GradingMalformedError),
    ):
        with pytest.raises(error):
            await FakeWrittenAnswerGrader(**kwargs).grade_written_answer(
                _grading_request()
            )


# --- Coordinator, leases, CAS, UNAVAILABLE, retry, recovery (PostgreSQL) ---


@pytest.fixture
def grading_setup(postgres_database, postgres_user_repository: PostgresUserRepository):
    postgres_user_repository.upsert_profile(OTHER_USER_ID, "Other Student")
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    session_repo = PostgresQuizSessionRepository(postgres_database.session_factory)
    generator = FakeQuizContentGenerator()
    prep_service = QuizPreparationService(
        prep_repo, room_repo, generator, verifier=FakeQuizContentVerifier()
    )
    session_service = SessionService(session_repo)
    return {
        "database": postgres_database,
        "room_repo": room_repo,
        "session_service": session_service,
        "prep_service": prep_service,
    }


def _force_close_current(db, session_id: UUID) -> None:
    now = datetime.now(timezone.utc)
    with db.session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, session_id)
            assert sm is not None
            sq = s.scalar(
                select(SessionQuestionModel).where(
                    SessionQuestionModel.session_id == session_id,
                    SessionQuestionModel.position == sm.current_question_position,
                )
            )
            assert sq is not None
            sq.opened_at = now - timedelta(seconds=10)
            sq.closes_at = now - timedelta(seconds=1)


def _force_reveal_expired(db, session_id: UUID) -> None:
    with db.session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, session_id)
            assert sm is not None
            sm.reveal_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)


def _advance_to_open_written(session_service: SessionService, db, session_id: UUID):
    """Move a 7-mark fake session (MCQ/NUMERICAL/WRITTEN) to the open written question."""
    _force_close_current(db, session_id)
    session_service.reconcile_session(session_id=session_id)
    _force_reveal_expired(db, session_id)
    session_service.reconcile_session(session_id=session_id)
    _force_close_current(db, session_id)
    session_service.reconcile_session(session_id=session_id)
    _force_reveal_expired(db, session_id)
    updated = session_service.reconcile_session(session_id=session_id)
    assert updated.status.value == "QUESTION_OPEN"
    assert updated.current_question_position == 2
    written = next(
        q
        for q in session_service.list_questions(session_id)
        if q.question_type == "WRITTEN"
    )
    assert written.position == 2
    return written


def _make_room(
    room_repo: PostgresRoomRepository,
    suffix: str,
    join_code: str,
    owner_id: UUID = OWNER_ID,
) -> UUID:
    room_id = uuid4()
    room_repo.create_with_owner(
        Room(
            id=room_id,
            owner_id=owner_id,
            name=f"Grading {suffix}",
            join_code=join_code,
            maximum_members=8,
            quiz_mode="ADAPTIVE",
            education_level="GCSE",
            quiz_subject="physics",
            quiz_topic="forces",
            target_total_marks=7,
        ),
        RoomMember(room_id=room_id, user_id=owner_id, display_name="Host"),
    )
    return room_id


@pytest.mark.anyio
async def test_coordinator_grades_pending_written(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "award", "LG0001")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle of forces applied to forces scenario.",
    )
    assert ack.grading_status == "PENDING"

    coordinator = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(always_award_all=True)
    )
    assert await coordinator.process_due_submissions() == 1

    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "GRADED"
        assert sub.earned_marks == written.max_marks
        assert sub.is_correct is True
        assert sub.points == 100
        assert set(sub.awarded_criterion_ids) == {
            c.id for c in WrittenRubric.from_dict(written.grading_rubric_snapshot).criteria
        }
        assert sub.graded_at is not None
        assert sub.claim_token is None


@pytest.mark.anyio
async def test_coordinator_two_attempts_then_unavailable(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "unavail", "LG0002")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Some answer text.",
    )

    coordinator = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(simulate_timeout=True)
    )
    assert await coordinator.process_due_submissions() == 1
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        # One bounded transient retry: first failure is RETRYABLE, never zero.
        assert sub.grading_status == "RETRYABLE"
        assert sub.earned_marks is None
        assert sub.is_correct is None
        assert sub.points is None

    # Make the retryable row due again and exhaust the single retry.
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await coordinator.process_due_submissions() == 1
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "UNAVAILABLE"
        assert sub.earned_marks is None
        assert sub.is_correct is None


@pytest.mark.anyio
async def test_coordinator_cas_discards_stale_result(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "casmis", "LG0003")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Some answer text.",
    )
    claimed = session_service.claim_due_written_submissions()
    assert len(claimed) == 1
    # Stale token (retry cycle / superseded claim) must not write.
    assert (
        session_service.store_written_grading_result_cas(
            submission_id=ack.submission_id,
            claim_token=uuid4(),
            earned_marks=written.max_marks,
            is_correct=True,
            points=100,
            awarded_criterion_ids=[],
            feedback={},
        )
        is False
    )
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "IN_PROGRESS"


@pytest.mark.anyio
async def test_startup_recovery_resets_expired_claims(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "restart", "LG0004")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle of forces applied to forces scenario.",
    )
    claimed = session_service.claim_due_written_submissions()
    assert len(claimed) == 1
    # Simulate a crash: claim lease expires while the worker is gone.
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            assert sub.grading_status == "IN_PROGRESS"
            sub.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    coordinator = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(always_award_all=True)
    )
    await coordinator.startup_recovery()
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        # Accepted answer survives restart and reaches a final grade.
        assert sub.grading_status == "GRADED"
        assert sub.earned_marks == written.max_marks


@pytest.mark.anyio
async def test_retry_grading_host_only_and_new_cycle(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "retrycy", "LG0005")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Some answer text.",
    )
    # Move the session into QUESTION_GRADING with the written answer pending.
    _force_close_current(db, sess.id)
    assert session_service.reconcile_session(session_id=sess.id).status.value == "QUESTION_GRADING"

    failing = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(simulate_timeout=True)
    )
    assert await failing.process_due_submissions() == 1
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await failing.process_due_submissions() == 1
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "UNAVAILABLE"

    with pytest.raises(RoomOwnerRequiredError):
        session_service.retry_grading_for_room(room_id, OTHER_USER_ID)

    assert session_service.retry_grading_for_room(room_id, OWNER_ID) == 1
    succeeding = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(always_award_all=True)
    )
    assert await succeeding.process_due_submissions() == 1
    assert (
        session_service.reconcile_session(session_id=sess.id).status.value
        == "QUESTION_REVEAL"
    )


# --- Protocol v2 backend parsing ---


def test_v2_strict_parsing_rejects_unknown_shapes() -> None:
    import json as _json

    def _send(payload: dict) -> ClientCommandV2:
        return parse_client_command_v2(_json.dumps(payload))

    auth = _send(
        {"protocol_version": 2, "type": "AUTHENTICATE", "payload": {"access_token": "t"}}
    )
    assert auth.type == "AUTHENTICATE"
    prepare = _send(
        {
            "protocol_version": 2,
            "type": "PREPARE_QUIZ",
            "payload": {"request_id": str(uuid4())},
        }
    )
    assert prepare.type == "PREPARE_QUIZ"
    choice = _send(
        {
            "protocol_version": 2,
            "type": "SUBMIT_ANSWER",
            "payload": {"session_question_id": str(uuid4()), "type": "choice", "option_id": "a"},
        }
    )
    assert choice.type == "SUBMIT_ANSWER"
    assert choice.payload.option_id == "a"
    assert choice.payload.text is None
    text = _send(
        {
            "protocol_version": 2,
            "type": "SUBMIT_ANSWER",
            "payload": {"session_question_id": str(uuid4()), "type": "text", "text": "42 J"},
        }
    )
    assert text.type == "SUBMIT_ANSWER"
    assert text.payload.text == "42 J"

    with pytest.raises(ProtocolV2Error):
        _send({"protocol_version": 1, "type": "AUTHENTICATE", "payload": {"access_token": "t"}})
    with pytest.raises(ProtocolV2Error):
        _send({"protocol_version": 2, "type": "NOPE", "payload": {}})
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {
                    "session_question_id": str(uuid4()),
                    "type": "choice",
                    "option_id": "a",
                    "text": "both",
                },
            }
        )
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SET_READY",
                "payload": {"ready": True, "injected": "field"},
            }
        )


def test_v2_submit_requires_type_and_forbids_legacy_field() -> None:
    import json as _json

    def _send(payload: dict) -> ClientCommandV2:
        return parse_client_command_v2(_json.dumps(payload))

    qid = str(uuid4())
    # Missing type is rejected.
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {"session_question_id": qid, "option_id": "a"},
            }
        )
    # Legacy selected_option_id does not exist in v2.
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {"session_question_id": qid, "selected_option_id": "a"},
            }
        )
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {
                    "session_question_id": qid,
                    "type": "text",
                    "text": "hi",
                    "selected_option_id": "a",
                },
            }
        )
    # Blank text, overlong text, overlong option are rejected, never coerced.
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {"session_question_id": qid, "type": "text", "text": "   "},
            }
        )
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {"session_question_id": qid, "type": "text", "text": "x" * 1001},
            }
        )
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {"session_question_id": qid, "type": "choice", "option_id": "o" * 65},
            }
        )
    with pytest.raises(ProtocolV2Error):
        _send(
            {
                "protocol_version": 2,
                "type": "SUBMIT_ANSWER",
                "payload": {"session_question_id": qid, "type": "choice"},
            }
        )
    # Boundary values are accepted and stripped text is normalized.
    padded = _send(
        {
            "protocol_version": 2,
            "type": "SUBMIT_ANSWER",
            "payload": {"session_question_id": qid, "type": "text", "text": "  42 J  "},
        }
    )
    assert padded.type == "SUBMIT_ANSWER"
    assert padded.payload.text == "42 J"
    boundary = _send(
        {
            "protocol_version": 2,
            "type": "SUBMIT_ANSWER",
            "payload": {"session_question_id": qid, "type": "text", "text": "y" * 1000},
        }
    )
    assert boundary.type == "SUBMIT_ANSWER"
    assert boundary.payload.text == "y" * 1000


def test_v2_error_event_shape() -> None:
    import json as _json

    raw = error_event_v2("quiz_not_ready", "Quiz content is still preparing.")
    decoded = _json.loads(raw)
    assert decoded["protocol_version"] == PROTOCOL_VERSION_V2
    assert decoded["type"] == "ERROR"
    assert decoded["payload"]["code"] == "quiz_not_ready"


# --- WebSocket v2 backend commands ---


def _v2_app(postgres_database, auth_verifier: FakeAuthVerifier):
    user_repo = PostgresUserRepository(postgres_database.session_factory)
    user_repo.upsert_profile(OWNER_ID, "Room Owner")
    user_repo.upsert_profile(OTHER_USER_ID, "Other Student")
    auth_verifier.register(OTHER_TOKEN, OTHER_USER_ID)
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    session_service = SessionService(
        PostgresQuizSessionRepository(postgres_database.session_factory)
    )
    prep_service = QuizPreparationService(
        PostgresQuizPreparationRepository(postgres_database.session_factory),
        room_repo,
        FakeQuizContentGenerator(),
        verifier=FakeQuizContentVerifier(),
    )
    app = create_app(
        repository=room_repo,
        membership_repository=PostgresMembershipRepository(
            postgres_database.session_factory
        ),
        user_repository=user_repo,
        auth_verifier=auth_verifier,
        session_service=session_service,
        quiz_preparation_service=prep_service,
    )
    return app, session_service


def _make_v2_room(session_service: SessionService, room_repo, marks: int = 5) -> UUID:
    room_id = uuid4()
    room_repo.create_with_owner(
        Room(
            id=room_id,
            owner_id=OWNER_ID,
            name="V2 Room",
            join_code="V2ROOM",
            maximum_members=8,
            quiz_mode="ADAPTIVE",
            education_level="GCSE",
            quiz_subject="physics",
            quiz_topic="energy",
            target_total_marks=marks,
        ),
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"),
    )
    return room_id


def test_v2_socket_prepare_start_and_choice_submit(
    postgres_database, auth_verifier: FakeAuthVerifier
) -> None:
    from fastapi.testclient import TestClient

    app, session_service = _v2_app(postgres_database, auth_verifier)
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    room_id = _make_v2_room(session_service, room_repo)
    mem_repo = PostgresMembershipRepository(postgres_database.session_factory)
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/rooms/{room_id}") as ws:
            ws.send_json(
                {
                    "protocol_version": 2,
                    "type": "AUTHENTICATE",
                    "payload": {"access_token": OWNER_TOKEN},
                }
            )
            assert ws.receive_json()["type"] == "CONNECTED"
            snapshot = ws.receive_json()
            assert snapshot["type"] == "STATE_SNAPSHOT"
            assert snapshot["protocol_version"] == 2
            assert ws.receive_json()["type"] == "ROOM_STATE"

            request_id = str(uuid4())
            ws.send_json(
                {
                    "protocol_version": 2,
                    "type": "PREPARE_QUIZ",
                    "payload": {"request_id": request_id},
                }
            )
            generating = ws.receive_json()
            assert generating["type"] == "ROOM_STATE"
            assert generating["payload"]["active_preparation_status"] == "GENERATING"
            terminal_ready = None
            for _ in range(4):
                frame = ws.receive_json()
                frame_state = (
                    frame["payload"]
                    if frame["type"] == "ROOM_STATE"
                    else frame["payload"].get("room_state", {})
                )
                if frame_state.get("active_preparation_status") == "READY":
                    terminal_ready = frame_state
                    break
            assert terminal_ready is not None
            assert terminal_ready["active_preparation_version"] >= 1

            ws.send_json(
                {"protocol_version": 2, "type": "START_SESSION", "payload": {}}
            )
            assert ws.receive_json()["type"] == "SESSION_STARTED"
            opened = ws.receive_json()
            assert opened["type"] == "QUESTION_OPENED"
            assert opened["payload"]["question"]["max_marks"] >= 1
            assert ws.receive_json()["type"] == "STATE_SNAPSHOT"

            snapshot_now = session_service.get_state_snapshot(room_id, OWNER_ID)
            assert snapshot_now.question is not None
            current_mcq = next(
                q
                for q in session_service.list_questions(snapshot_now.session.id)
                if q.id == snapshot_now.question.id
            )
            assert current_mcq.correct_option_id is not None
            ws.send_json(
                {
                    "protocol_version": 2,
                    "type": "SUBMIT_ANSWER",
                    "payload": {
                        "session_question_id": str(snapshot_now.question.id),
                        "type": "choice",
                        "option_id": current_mcq.correct_option_id,
                    },
                }
            )
            ack = ws.receive_json()
            assert ack["type"] == "ANSWER_ACCEPTED"
            assert ack["payload"]["grading_status"] == "GRADED"


def test_v2_socket_retry_grading_is_host_only_and_version_strict(
    postgres_database, auth_verifier: FakeAuthVerifier
) -> None:
    from fastapi.testclient import TestClient

    app, session_service = _v2_app(postgres_database, auth_verifier)
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    room_id = _make_v2_room(session_service, room_repo)
    mem_repo = PostgresMembershipRepository(postgres_database.session_factory)
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/rooms/{room_id}") as ws:
            ws.send_json(
                {
                    "protocol_version": 2,
                    "type": "AUTHENTICATE",
                    "payload": {"access_token": OTHER_TOKEN},
                }
            )
            assert ws.receive_json()["type"] == "CONNECTED"
            assert ws.receive_json()["type"] == "STATE_SNAPSHOT"
            assert ws.receive_json()["type"] == "ROOM_STATE"

            # Non-host retry is rejected without touching durable state.
            ws.send_json(
                {"protocol_version": 2, "type": "RETRY_GRADING", "payload": {}}
            )
            error = ws.receive_json()
            assert error["type"] == "ERROR"
            assert error["protocol_version"] == 2
            assert error["payload"]["code"] == "room_owner_required"

            # Strict wire separation: v1 frames never apply on a v2 socket.
            ws.send_json(
                {
                    "protocol_version": 1,
                    "type": "REQUEST_STATE",
                    "payload": {},
                }
            )
            mismatch = ws.receive_json()
            assert mismatch["type"] == "ERROR"
            assert mismatch["payload"]["code"] == "protocol_error"

            # v2 request-state still works afterwards on the same socket.
            ws.send_json(
                {"protocol_version": 2, "type": "REQUEST_STATE", "payload": {}}
            )
            assert ws.receive_json()["type"] == "STATE_SNAPSHOT"


def test_v1_socket_rejects_v2_prepare_frame(
    postgres_database, auth_verifier: FakeAuthVerifier
) -> None:
    from fastapi.testclient import TestClient

    app, session_service = _v2_app(postgres_database, auth_verifier)
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    room_id = _make_v2_room(session_service, room_repo)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/rooms/{room_id}") as ws:
            ws.send_json(
                {
                    "protocol_version": 1,
                    "type": "AUTHENTICATE",
                    "payload": {"access_token": OWNER_TOKEN},
                }
            )
            assert ws.receive_json()["type"] == "CONNECTED"
            assert ws.receive_json()["type"] == "STATE_SNAPSHOT"
            assert ws.receive_json()["type"] == "ROOM_STATE"

            ws.send_json(
                {
                    "protocol_version": 2,
                    "type": "PREPARE_QUIZ",
                    "payload": {"request_id": str(uuid4())},
                }
            )
            error = ws.receive_json()
            assert error["type"] == "ERROR"
            assert error["protocol_version"] == 1


def test_http_submit_legacy_and_typed_shapes() -> None:
    from pydantic import ValidationError

    qid = uuid4()
    legacy = SubmitAnswerRequest(session_question_id=qid, selected_option_id="opt_a")
    assert legacy.selected_option_id == "opt_a"
    assert legacy.type is None
    choice = SubmitAnswerRequest(
        session_question_id=qid, type="choice", option_id="opt_a"
    )
    assert choice.selected_option_id == "opt_a"
    text = SubmitAnswerRequest(
        session_question_id=qid, type="text", text="  42 J "
    )
    assert text.text == "42 J"
    invalid_payloads = [
        # Typed payloads must not carry the legacy field.
        {"session_question_id": qid, "type": "choice", "option_id": "a",
         "selected_option_id": "a"},
        {"session_question_id": qid, "type": "text", "text": "hi",
         "selected_option_id": "a"},
        # Type-less text is not a legacy shape.
        {"session_question_id": qid, "text": "hi"},
        {"session_question_id": qid},
        {"session_question_id": qid, "selected_option_id": "   "},
        {"session_question_id": qid, "type": "choice", "option_id": "a", "text": "x"},
        {"session_question_id": qid, "type": "text", "text": "x", "option_id": "a"},
        {"session_question_id": qid, "type": "text", "text": "   "},
        {"session_question_id": qid, "type": "text", "text": "x" * 1001},
        {"session_question_id": qid, "type": "choice", "option_id": "o" * 65},
        {"session_question_id": qid, "selected_option_id": "o" * 65},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            SubmitAnswerRequest(**payload)


@pytest.mark.anyio
async def test_repository_rejects_blank_and_overlong_text(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "bounds", "LG0100")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)

    with pytest.raises(InvalidAnswerTextError):
        session_service.submit_answer(
            room_id=room_id,
            user_id=OWNER_ID,
            session_question_id=written.id,
            answer_text="   ",
        )
    with pytest.raises(InvalidAnswerTextError):
        session_service.submit_answer(
            room_id=room_id,
            user_id=OWNER_ID,
            session_question_id=written.id,
            answer_text="x" * 1001,
        )
    # Boundary length is stored exactly, never truncated.
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="y" * 1000,
    )
    assert ack.grading_status == "PENDING"
    assert ack.answer_text == "y" * 1000


@pytest.mark.anyio
async def test_enriched_feedback_awarded_missing_and_prereveal_secrecy(
    grading_setup,
) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "feedback", "LG0101")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)

    # "Primary principle" matches only the first fake criterion's wording.
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle",
    )
    coordinator = GradingCoordinator(session_service, FakeWrittenAnswerGrader())
    assert await coordinator.process_due_submissions() == 1

    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "GRADED"
        feedback = dict(sub.feedback)
        assert feedback["awarded_count"] == 1
        assert feedback["total_criteria"] == 2
        assert [a["id"] for a in feedback["awarded"]] == ["c_2_1"]
        assert [m["id"] for m in feedback["missing"]] == ["c_2_2"]
        for entry in (*feedback["awarded"], *feedback["missing"]):
            assert entry["marks"] >= 1
            assert entry["explanation"].strip() != ""
        assert len(feedback["summary"]) <= 1000

    # Pre-reveal snapshots expose no marks, feedback, or awarded IDs.
    snapshot = session_service.get_state_snapshot(room_id, OWNER_ID)
    assert snapshot.viewer_submission is not None
    assert snapshot.viewer_submission.feedback == {}
    assert snapshot.viewer_submission.awarded_criterion_ids == ()
    assert snapshot.viewer_submission.earned_marks is None

    # After reveal the viewer sees their own enriched feedback.
    _force_close_current(db, sess.id)
    session_service.reconcile_session(session_id=sess.id)
    revealed = session_service.get_state_snapshot(room_id, OWNER_ID)
    assert revealed.viewer_submission is not None
    assert revealed.viewer_submission.feedback["missing"][0]["id"] == "c_2_2"
    assert revealed.viewer_submission.earned_marks == 2


def test_spelling_requires_exact_phrase_not_single_word() -> None:
    from app.grading.openai_grader import check_spelling_sensitive_criterion

    single = WrittenCriterion(
        id="s1",
        marks=1,
        marking_point="Names the unit Newton",
        accepted_meaning="Newton",
        spelling_sensitive=True,
        explanation="Must spell Newton.",
    )
    assert check_spelling_sensitive_criterion(single, "measured in Newton") is True
    assert check_spelling_sensitive_criterion(single, "measured in NEWTON.") is True
    # Shared letters or sub-words do not satisfy the rule.
    assert check_spelling_sensitive_criterion(single, "measured in Newtun") is False
    assert check_spelling_sensitive_criterion(single, "Newtonian force") is False
    assert check_spelling_sensitive_criterion(single, "new town") is False

    phrase = WrittenCriterion(
        id="s2",
        marks=2,
        marking_point="Constant velocity without resultant force",
        accepted_meaning="constant velocity",
        spelling_sensitive=True,
        explanation="Must phrase constant velocity.",
    )
    assert check_spelling_sensitive_criterion(
        phrase, "it keeps a constant   velocity"
    ) is True
    # Same words in another order are not the accepted phrase.
    assert check_spelling_sensitive_criterion(
        phrase, "velocity is constant"
    ) is False

    lax = WrittenCriterion(
        id="s3",
        marks=1,
        marking_point="Anything",
        accepted_meaning="Anything",
        spelling_sensitive=False,
        explanation="Lenient.",
    )
    assert check_spelling_sensitive_criterion(lax, "unrelated words") is True


THIRD_USER_ID = UUID("33333333-3333-4333-8333-333333333333")


@pytest.mark.anyio
async def test_coordinator_claims_at_most_concurrent_slots(grading_setup) -> None:
    """Claimed leases must never queue behind the grading semaphore (R13)."""
    import asyncio as _asyncio

    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)
    users = PostgresUserRepository(db.session_factory)
    users.upsert_profile(THIRD_USER_ID, "Third Student")

    room_id = _make_room(room_repo, "bounded", "LG0102")
    for member_id, name in (
        (OTHER_USER_ID, "Other"),
        (THIRD_USER_ID, "Third"),
    ):
        mem_repo.add(RoomMember(room_id=room_id, user_id=member_id, display_name=name))
        session_service.set_ready(room_id, member_id, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)

    for member_id in (OWNER_ID, OTHER_USER_ID, THIRD_USER_ID):
        ack = session_service.submit_answer(
            room_id=room_id,
            user_id=member_id,
            session_question_id=written.id,
            answer_text="Primary principle of forces applied to forces scenario.",
        )
        assert ack.grading_status == "PENDING"

    in_flight = 0
    max_observed = 0

    class GatedGrader(FakeWrittenAnswerGrader):
        async def grade_written_answer(
            self, request: GradingRequest
        ) -> GradingResult:
            nonlocal in_flight, max_observed
            in_flight += 1
            max_observed = max(max_observed, in_flight)
            try:
                await _asyncio.sleep(0.05)
                return await super().grade_written_answer(request)
            finally:
                in_flight -= 1

    coordinator = GradingCoordinator(
        session_service,
        GatedGrader(always_award_all=True),
        max_concurrent=2,
    )
    # First batch claims exactly two; the third stays PENDING with no lease.
    assert await coordinator.process_due_submissions() == 2
    assert max_observed <= 2
    with db.session_factory() as s:
        pending = s.scalars(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.session_question_id == written.id,
                AnswerSubmissionModel.grading_status == "PENDING",
            )
        ).all()
        assert len(pending) == 1
        assert pending[0].claim_token is None
        assert pending[0].lease_expires_at is None
    # Second batch drains the remainder.
    assert await coordinator.process_due_submissions() == 1
    assert max_observed <= 2
    with db.session_factory() as s:
        graded = s.scalars(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.session_question_id == written.id,
                AnswerSubmissionModel.grading_status == "GRADED",
            )
        ).all()
        assert len(graded) == 3


@pytest.mark.anyio
async def test_expired_first_claim_returns_to_pending(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "exp1", "LG0103")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle of forces.",
    )
    claimed = session_service.claim_due_written_submissions()
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 1
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    affected = session_service.reset_expired_grading_claims()
    assert affected == (sess.id,)
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "PENDING"
        # Attempt count preserved: the resumed claim is the second call, not a third.
        assert sub.attempt_count == 1
    assert len(session_service.claim_due_written_submissions()) == 1


@pytest.mark.anyio
async def test_expired_second_claim_becomes_unavailable_and_stays_grading(
    grading_setup,
) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "exp2", "LG0104")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle of forces.",
    )
    _force_close_current(db, sess.id)
    assert session_service.reconcile_session(session_id=sess.id).status.value == "QUESTION_GRADING"

    failing = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(simulate_timeout=True)
    )
    assert await failing.process_due_submissions() == 1
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            assert sub.grading_status == "RETRYABLE"
            sub.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    # Second claim, then the worker crashes with the lease held.
    claimed = session_service.claim_due_written_submissions()
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 2
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    affected = session_service.reset_expired_grading_claims()
    assert affected == (sess.id,)
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        # No third provider call: exhausted work becomes UNAVAILABLE.
        assert sub.grading_status == "UNAVAILABLE"
    assert session_service.claim_due_written_submissions() == ()
    # Honest phase: the session remains GRADING awaiting explicit retry.
    assert session_service.reconcile_session(session_id=sess.id).status.value == "QUESTION_GRADING"


@pytest.mark.anyio
async def test_malformed_stored_rubric_never_strands_claim(grading_setup) -> None:
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "rubric", "LG0105")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle of forces.",
    )
    with db.session_factory() as s:
        with s.begin():
            sq = s.get(SessionQuestionModel, written.id)
            assert sq is not None
            sq.grading_rubric_snapshot = {"criteria": "not-a-list"}

    coordinator = GradingCoordinator(session_service, FakeWrittenAnswerGrader())
    assert await coordinator.process_due_submissions() == 1
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "RETRYABLE"
        assert sub.last_error_category == "malformed_rubric"
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await coordinator.process_due_submissions() == 1
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "UNAVAILABLE"


@pytest.mark.anyio
async def test_grading_cas_rejects_expiry_closure_and_stale_question(
    grading_setup,
) -> None:
    from app.domain.quiz import (
        AnswerAcknowledgement,
        QuizSession,
        SessionQuestion,
    )
    from app.repositories.quiz_sessions import ClaimedSubmission

    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)
    users = PostgresUserRepository(db.session_factory)

    async def _claimed_pair(
        tag: str, code: str, owner_id: UUID, member_id: UUID
    ) -> tuple[UUID, QuizSession, SessionQuestion, AnswerAcknowledgement, ClaimedSubmission]:
        users.upsert_profile(owner_id, f"Host {tag}")
        users.upsert_profile(member_id, f"Member {tag}")
        room_id = _make_room(room_repo, tag, code, owner_id=owner_id)
        mem_repo.add(
            RoomMember(room_id=room_id, user_id=member_id, display_name="Other")
        )
        session_service.set_ready(room_id, member_id, True)
        await prep_service.prepare_quiz(
            room_id, uuid4(), owner_id, wait_for_completion=True
        )
        sess = session_service.start_session(room_id, owner_id)
        written = _advance_to_open_written(session_service, db, sess.id)
        ack = session_service.submit_answer(
            room_id=room_id,
            user_id=owner_id,
            session_question_id=written.id,
            answer_text="Primary principle of forces.",
        )
        claimed = session_service.claim_due_written_submissions()
        assert len(claimed) == 1
        return room_id, sess, written, ack, claimed[0]

    def _store(
        ack: AnswerAcknowledgement, token: UUID, marks: int
    ) -> bool:
        return session_service.store_written_grading_result_cas(
            submission_id=ack.submission_id,
            claim_token=token,
            earned_marks=marks,
            is_correct=False,
            points=0,
            awarded_criterion_ids=[],
            feedback={"summary": "Late."},
        )

    # Expired lease: the late provider result is discarded.
    owner_a = UUID("a0a0a0a0-0000-4000-8000-000000000001")
    member_a = UUID("a0a0a0a0-0000-4000-8000-000000000002")
    owner_b = UUID("b0b0b0b0-0000-4000-8000-000000000001")
    member_b = UUID("b0b0b0b0-0000-4000-8000-000000000002")
    owner_c = UUID("c0c0c0c0-0000-4000-8000-000000000001")
    member_c = UUID("c0c0c0c0-0000-4000-8000-000000000002")
    _, _, _, ack, claim = await _claimed_pair("exp", "LG0106", owner_a, member_a)
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert _store(ack, claim.claim_token, 0) is False

    # Closed room: late grading cannot land after close. The close is
    # applied directly because close_room guards active sessions; the CAS
    # must reject on room state regardless of how the race interleaved.
    room_id_b, _, _, ack_b, claim_b = await _claimed_pair("cls", "LG0107", owner_b, member_b)
    from app.db.models.room import RoomModel as _RoomModel

    with db.session_factory() as s:
        with s.begin():
            rm = s.get(_RoomModel, room_id_b)
            assert rm is not None
            rm.closed_at = datetime.now(timezone.utc)
    assert _store(ack_b, claim_b.claim_token, 0) is False

    # Current question moved on: success write rejected.
    _, _, _, ack_c, claim_c = await _claimed_pair("stq", "LG0108", owner_c, member_c)
    with db.session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, claim_c.session_id)
            assert sm is not None
            sm.current_question_position = 0
    assert _store(ack_c, claim_c.claim_token, 0) is False


@pytest.mark.anyio
async def test_unavailable_visible_to_all_viewers_and_retry_broadcasts(
    grading_setup,
) -> None:
    """R16: grading-state changes version and publish viewer-specific snapshots."""
    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "multiview", "LG0113")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    for member_id in (OWNER_ID, OTHER_USER_ID):
        session_service.submit_answer(
            room_id=room_id,
            user_id=member_id,
            session_question_id=written.id,
            answer_text="Primary principle of forces.",
        )
    baseline_session = session_service.get_session(sess.id)
    assert baseline_session is not None
    baseline_version = baseline_session.state_version

    published: list[tuple[UUID, int]] = []

    async def _publish(
        published_room_id: UUID,
        previous: object,
        current: QuizSession,
    ) -> bool:
        published.append((current.id, current.state_version))
        return True

    failing = GradingCoordinator(
        session_service,
        FakeWrittenAnswerGrader(simulate_timeout=True),
        publish_transition=_publish,
    )
    assert await failing.process_due_submissions() == 2
    _force_close_current(db, sess.id)
    assert session_service.reconcile_session(session_id=sess.id).status.value == "QUESTION_GRADING"
    with db.session_factory() as s:
        with s.begin():
            subs = s.scalars(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.session_question_id == written.id
                )
            ).all()
            for sub in subs:
                sub.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await failing.process_due_submissions() == 2
    # Both UNAVAILABLE transitions published from an older baseline version.
    assert len(published) >= 2
    versions = [version for _, version in published]
    assert versions == sorted(versions)
    assert versions[0] > baseline_version

    for viewer_id, own_text in (
        (OWNER_ID, "Primary principle of forces."),
        (OTHER_USER_ID, "Primary principle of forces."),
    ):
        snapshot = session_service.get_state_snapshot(room_id, viewer_id)
        assert snapshot.grading_retry_needed is True
        assert snapshot.session is not None
        assert snapshot.session.state_version > baseline_version
        assert snapshot.viewer_submission is not None
        assert snapshot.viewer_submission.grading_status == "UNAVAILABLE"
        # Own response visible; another participant's exact answer never leaks.
        assert snapshot.viewer_submission.answer_text == own_text
        assert snapshot.viewer_submission.feedback == {}

    # Host retry resets the cycle, bumps the version, and clears the signal.
    before_session = session_service.get_session(sess.id)
    assert before_session is not None
    before_retry = before_session.state_version
    assert session_service.retry_grading_for_room(room_id, OWNER_ID) == 2
    after_session = session_service.get_session(sess.id)
    assert after_session is not None
    after_retry = after_session.state_version
    assert after_retry > before_retry
    for viewer_id in (OWNER_ID, OTHER_USER_ID):
        snapshot = session_service.get_state_snapshot(room_id, viewer_id)
        assert snapshot.grading_retry_needed is False
        assert snapshot.session is not None
        assert snapshot.session.state_version == after_retry

    succeeding = GradingCoordinator(
        session_service, FakeWrittenAnswerGrader(always_award_all=True)
    )
    assert await succeeding.process_due_submissions() == 2
    assert (
        session_service.reconcile_session(session_id=sess.id).status.value
        == "QUESTION_REVEAL"
    )
    for viewer_id in (OWNER_ID, OTHER_USER_ID):
        revealed = session_service.get_state_snapshot(room_id, viewer_id)
        assert revealed.viewer_submission is not None
        assert revealed.viewer_submission.feedback["awarded_count"] == 2
        assert revealed.viewer_submission.earned_marks == written.max_marks


def test_retry_broadcast_reaches_every_participant_socket(
    postgres_database, auth_verifier: FakeAuthVerifier
) -> None:
    """R16: host RETRY_GRADING publishes snapshots to all participants."""
    from fastapi.testclient import TestClient

    app, session_service = _v2_app(postgres_database, auth_verifier)
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    room_id = _make_v2_room(session_service, room_repo, marks=10)
    mem_repo = PostgresMembershipRepository(postgres_database.session_factory)
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/rooms/{room_id}") as host_ws:
            host_ws.send_json(
                {
                    "protocol_version": 2,
                    "type": "AUTHENTICATE",
                    "payload": {"access_token": OWNER_TOKEN},
                }
            )
            assert host_ws.receive_json()["type"] == "CONNECTED"
            assert host_ws.receive_json()["type"] == "STATE_SNAPSHOT"
            assert host_ws.receive_json()["type"] == "ROOM_STATE"
            with client.websocket_connect(f"/ws/rooms/{room_id}") as member_ws:
                member_ws.send_json(
                    {
                        "protocol_version": 2,
                        "type": "AUTHENTICATE",
                        "payload": {"access_token": OTHER_TOKEN},
                    }
                )
                assert member_ws.receive_json()["type"] == "CONNECTED"
                assert member_ws.receive_json()["type"] == "STATE_SNAPSHOT"
                assert member_ws.receive_json()["type"] == "ROOM_STATE"

                # Drive an UNAVAILABLE grading state directly through services.
                from app.generator.fake_adapter import FakeQuizContentGenerator as _Fake
                from app.services.quiz_preparation_service import (
                    QuizPreparationService as _PrepService,
                )
                from app.repositories.postgres_quiz_preparations import (
                    PostgresQuizPreparationRepository as _PrepRepo,
                )

                prep_service = _PrepService(
                    _PrepRepo(postgres_database.session_factory),
                    room_repo,
                    _Fake(),
                    verifier=FakeQuizContentVerifier(),
                )
                import anyio as _anyio

                request_id = uuid4()

                async def _prepare() -> None:
                    await prep_service.prepare_quiz(
                        room_id,
                        request_id,
                        OWNER_ID,
                        wait_for_completion=True,
                    )

                _anyio.run(_prepare)
                sess = session_service.start_session(room_id, OWNER_ID)
                written = _advance_to_open_written(session_service, postgres_database, sess.id)
                session_service.submit_answer(
                    room_id=room_id,
                    user_id=OTHER_USER_ID,
                    session_question_id=written.id,
                    answer_text="Member answer text.",
                )
                with postgres_database.session_factory() as s:
                    with s.begin():
                        from app.db.models.session_question import (
                            SessionQuestionModel as _SQ,
                        )

                        sq = s.get(_SQ, written.id)
                        assert sq is not None
                        sq.opened_at = datetime.now(timezone.utc) - timedelta(seconds=10)
                        sq.closes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                assert (
                    session_service.reconcile_session(session_id=sess.id).status.value
                    == "QUESTION_GRADING"
                )
                # Exhaust the written grade to UNAVAILABLE so retry has work.
                from app.grading.fake_grader import (
                    FakeWrittenAnswerGrader as _FakeGrader,
                )
                from app.grading.coordinator import GradingCoordinator as _Coordinator

                async def _exhaust() -> None:
                    coordinator = _Coordinator(
                        session_service, _FakeGrader(simulate_timeout=True)
                    )
                    await coordinator.process_due_submissions()
                    with postgres_database.session_factory() as _s:
                        with _s.begin():
                            from app.db.models.answer_submission import (
                                AnswerSubmissionModel as _Sub,
                            )

                            for row in _s.scalars(select(_Sub)).all():
                                row.next_attempt_at = datetime.now(timezone.utc) - timedelta(
                                    seconds=1
                                )
                    await coordinator.process_due_submissions()

                _anyio.run(_exhaust)
                assert (
                    session_service.get_state_snapshot(room_id, OWNER_ID).grading_retry_needed
                    is True
                )

                host_version_before = session_service.get_state_snapshot(
                    room_id, OWNER_ID
                ).state_version
                host_ws.send_json(
                    {"protocol_version": 2, "type": "RETRY_GRADING", "payload": {}}
                )
                host_snapshot = host_ws.receive_json()
                while host_snapshot["type"] == "ROOM_STATE":
                    host_snapshot = host_ws.receive_json()
                assert host_snapshot["type"] == "STATE_SNAPSHOT"
                # Member socket observes the same authoritative snapshot.
                member_snapshot = member_ws.receive_json()
                while member_snapshot["type"] == "ROOM_STATE":
                    member_snapshot = member_ws.receive_json()
                assert member_snapshot["type"] == "STATE_SNAPSHOT"
                assert (
                    member_snapshot["payload"]["state_version"]
                    == host_snapshot["payload"]["state_version"]
                )
                assert host_snapshot["payload"]["state_version"] >= host_version_before


@pytest.mark.anyio
async def test_grader_rejects_blank_and_overlong_feedback() -> None:
    for feedback in ("", "   ", "\t\n ", "x" * 1001):
        def mock_handler(request: httpx.Request, feedback=feedback) -> httpx.Response:
            body = json.dumps(
                {"awarded_criterion_ids": ["c1"], "feedback": feedback}
            )
            return httpx.Response(200, json=_responses_envelope(body))

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        grader = OpenAiWrittenAnswerGrader(api_key="test_key", client=client)
        with pytest.raises(GradingMalformedError):
            await grader.grade_written_answer(_grading_request())

    # Boundary feedback is accepted exactly, never truncated.
    def mock_ok(request: httpx.Request) -> httpx.Response:
        body = json.dumps(
            {"awarded_criterion_ids": ["c1"], "feedback": "z" * 1000}
        )
        return httpx.Response(200, json=_responses_envelope(body))

    ok_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_ok))
    result = await OpenAiWrittenAnswerGrader(
        api_key="test_key", client=ok_client
    ).grade_written_answer(_grading_request())
    assert result.feedback == {"summary": "z" * 1000}


@pytest.mark.anyio
async def test_grading_refusal_and_answer_content_never_logged(
    grading_setup, caplog: pytest.LogCaptureFixture
) -> None:
    """Provider refusal text and student answers stay out of logs and categories."""
    import logging

    from app.grading.protocol import GradingRefusalError as _Refusal

    canary = "CANARY_GRADING_REFUSAL_3m8p"
    answer_canary = "CANARY_STUDENT_ANSWER_6k2q"

    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "logcanary", "LG0114")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text=f"Primary principle of forces {answer_canary}.",
    )

    class RefusingGrader(FakeWrittenAnswerGrader):
        async def grade_written_answer(
            self, request: GradingRequest
        ) -> GradingResult:
            raise _Refusal(f"Model refused: {canary}")

    with caplog.at_level(logging.WARNING):
        coordinator = GradingCoordinator(session_service, RefusingGrader())
        assert await coordinator.process_due_submissions() == 1
    assert canary not in caplog.text
    assert answer_canary not in caplog.text
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "RETRYABLE"
        assert sub.last_error_category == "refusal"
        assert canary not in (sub.last_error_category or "")


@pytest.mark.anyio
async def test_malformed_grading_enters_retry_path_without_persisting_grade(
    grading_setup,
) -> None:
    """Unknown criterion IDs must not persist a partial grade (clarification)."""
    from app.grading.protocol import GradingMalformedError as _Malformed

    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = _make_room(room_repo, "malformed", "LG0109")
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)
    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    written = _advance_to_open_written(session_service, db, sess.id)
    ack = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=written.id,
        answer_text="Primary principle of forces.",
    )

    class LyingGrader(FakeWrittenAnswerGrader):
        async def grade_written_answer(
            self, request: GradingRequest
        ) -> GradingResult:
            raise _Malformed("unknown criterion ID")

    coordinator = GradingCoordinator(session_service, LyingGrader())
    assert await coordinator.process_due_submissions() == 1
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "RETRYABLE"
        assert sub.earned_marks is None
        assert sub.graded_at is None


@pytest.mark.anyio
async def test_failure_cas_rejects_expiry_closure_and_stale_question(
    grading_setup,
) -> None:
    from app.domain.quiz import AnswerAcknowledgement as _Ack
    from app.domain.quiz import QuizSession as _QuizSession
    from app.repositories.quiz_sessions import ClaimedSubmission as _Claim

    db = grading_setup["database"]
    room_repo = grading_setup["room_repo"]
    prep_service = grading_setup["prep_service"]
    session_service = grading_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    async def _claimed(
        tag: str, code: str, owner_id: UUID, member_id: UUID
    ) -> tuple[UUID, _QuizSession, _Ack, _Claim]:
        users = PostgresUserRepository(db.session_factory)
        users.upsert_profile(owner_id, f"Host {tag}")
        users.upsert_profile(member_id, f"Member {tag}")
        room_id = _make_room(room_repo, tag, code, owner_id=owner_id)
        mem_repo.add(
            RoomMember(room_id=room_id, user_id=member_id, display_name="Other")
        )
        session_service.set_ready(room_id, member_id, True)
        await prep_service.prepare_quiz(
            room_id, uuid4(), owner_id, wait_for_completion=True
        )
        sess = session_service.start_session(room_id, owner_id)
        written = _advance_to_open_written(session_service, db, sess.id)
        ack = session_service.submit_answer(
            room_id=room_id,
            user_id=owner_id,
            session_question_id=written.id,
            answer_text="Primary principle of forces.",
        )
        claimed = session_service.claim_due_written_submissions()
        assert len(claimed) == 1
        return room_id, sess, ack, claimed[0]

    def _fail(ack: _Ack, token: UUID) -> bool:
        return session_service.mark_written_grading_retryable_or_unavailable(
            submission_id=ack.submission_id,
            claim_token=token,
            error_category="timeout",
            backoff_seconds=5,
        )

    # Expired lease: the failure write is rejected, row stays IN_PROGRESS.
    owner_d = UUID("d0d0d0d0-0000-4000-8000-000000000001")
    member_d = UUID("d0d0d0d0-0000-4000-8000-000000000002")
    owner_e = UUID("e0e0e0e0-0000-4000-8000-000000000001")
    member_e = UUID("e0e0e0e0-0000-4000-8000-000000000002")
    owner_f = UUID("f0f0f0f0-0000-4000-8000-000000000001")
    member_f = UUID("f0f0f0f0-0000-4000-8000-000000000002")
    _, _, ack, claim = await _claimed("fexp", "LG0110", owner_d, member_d)
    with db.session_factory() as s:
        with s.begin():
            sub = s.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.id == ack.submission_id
                )
            )
            assert sub is not None
            sub.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert _fail(ack, claim.claim_token) is False
    with db.session_factory() as s:
        sub = s.scalar(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.id == ack.submission_id
            )
        )
        assert sub is not None
        assert sub.grading_status == "IN_PROGRESS"

    # Closed room: failure write rejected.
    room_id_b, _, ack_b, claim_b = await _claimed("fcls", "LG0111", owner_e, member_e)
    from app.db.models.room import RoomModel as _RoomModel2

    with db.session_factory() as s:
        with s.begin():
            rm = s.get(_RoomModel2, room_id_b)
            assert rm is not None
            rm.closed_at = datetime.now(timezone.utc)
    assert _fail(ack_b, claim_b.claim_token) is False

    # Current question moved on: failure write rejected.
    _, _, ack_c, claim_c = await _claimed("fstq", "LG0112", owner_f, member_f)
    with db.session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, claim_c.session_id)
            assert sm is not None
            sm.current_question_position = 0
    assert _fail(ack_c, claim_c.claim_token) is False
