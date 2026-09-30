"""Tests for quiz content generation validation, adapters, preparation lifecycle, and repeat exclusions."""

from decimal import Decimal
import json
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.adaptive_quiz import (
    MultipleChoiceOption,
    NumericalRubric,
    QuestionType,
    UnitDependency,
    WrittenCriterion,
    WrittenRubric,
    compute_content_fingerprint,
    grade_numerical,
    normalize_numerical_unit,
)
from app.domain.errors import (
    AiGenerationUnavailableError,
    PreparationConflictError,
    PreparationFailedError,
    RoomClosedError,
    RoomNotFoundError,
    RoomOwnerRequiredError,
)
from app.domain.member import RoomMember
from app.domain.quiz_preparation import QuizPreparation
from app.domain.room import Room
from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.openai_adapter import OpenAiQuizContentGenerator
from app.generator.protocol import (
    GeneratedQuestionData,
    GenerationRequest,
    MODEL_ID_GPT_6_LUNA,
    GeneratorAuthError,
    GeneratorMalformedError,
    GeneratorRateLimitedError,
    GeneratorRefusalError,
    GeneratorTimeoutError,
    GeneratorUnavailableError,
    GeneratorValidationError,
)
from app.generator.validation import (
    validate_generated_quiz_set,
    validate_repeat_exclusions,
    validate_single_question,
)
from app.generator.verification import FakeQuizContentVerifier
from app.repositories.postgres_quiz_preparations import (
    PostgresQuizPreparationRepository,
    _interleave_recent_exclusion_prompts,
)
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.services.quiz_preparation_service import QuizPreparationService
from tests.conftest import OWNER_ID


# --- Validation Tests ---


def test_validate_generated_quiz_set_valid_mixture():
    questions = [
        {
            "question_type": "MULTIPLE_CHOICE",
            "prompt": "What is unit of force?",
            "max_marks": 1,
            "options": [{"id": "a", "label": "Newton"}, {"id": "b", "label": "Joule"}],
            "correct_option_id": "a",
            "grading_rubric": {
                "criteria": [],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
            "worked_explanation": "Force is measured in Newtons.",
            "original_extract": None,
        },
        {
            "question_type": "NUMERICAL",
            "prompt": "Calculate weight of 2kg mass on Earth.",
            "max_marks": 2,
            "options": [],
            "correct_option_id": None,
            "grading_rubric": {
                "expected_value": "19.6",
                "criteria": [],
                "absolute_tolerance": "0.5",
                "allowed_units": ["n"],
                "value_marks": 1,
                "unit_marks": 1,
                "unit_dependency": "REQUIRES_VALUE",
            },
            "worked_explanation": "W = m * g = 2 * 9.8 = 19.6 N.",
            "original_extract": None,
        },
        {
            "question_type": "WRITTEN",
            "prompt": "State Newton's first law of motion.",
            "max_marks": 2,
            "options": [],
            "correct_option_id": None,
        "grading_rubric": {
            "criteria": [
                {
                    "id": "c1",
                    "marks": 2,
                    "marking_point": "Object remains at rest or uniform velocity unless acted on by resultant force",
                    "accepted_meaning": "Constant velocity without resultant force",
                    "spelling_sensitive": False,
                    "explanation": "Must mention constant velocity or at rest without external resultant force.",
                }
            ],
            "expected_value": None,
            "absolute_tolerance": None,
            "allowed_units": [],
            "value_marks": 0,
            "unit_marks": 0,
            "unit_dependency": "REQUIRES_VALUE",
        },
            "worked_explanation": "An object remains at rest or constant velocity unless acted upon by a resultant force.",
            "original_extract": None,
        },
    ]

    validated = validate_generated_quiz_set(questions, target_total_marks=5)
    assert len(validated) == 3
    assert sum(q.max_marks for q in validated) == 5
    assert validated[0].question_type == QuestionType.MULTIPLE_CHOICE
    assert validated[1].question_type == QuestionType.NUMERICAL
    assert validated[2].question_type == QuestionType.WRITTEN


def test_validate_generated_quiz_set_rejects_marks_sum_mismatch():
    questions = [
        {
            "question_type": "MULTIPLE_CHOICE",
            "prompt": "Q1?",
            "max_marks": 1,
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "correct_option_id": "a",
            "grading_rubric": {
                "criteria": [],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
            "worked_explanation": "Exp",
            "original_extract": None,
        }
    ]
    with pytest.raises(GeneratorValidationError, match="marks sum.*does not equal target budget"):
        validate_generated_quiz_set(questions, target_total_marks=5)


def test_validate_generated_quiz_set_rejects_budget_out_of_bounds():
    with pytest.raises(GeneratorValidationError, match="target_total_marks.*must be between 5 and 40"):
        validate_generated_quiz_set([], target_total_marks=4)
    with pytest.raises(GeneratorValidationError, match="target_total_marks.*must be between 5 and 40"):
        validate_generated_quiz_set([], target_total_marks=45)


def test_validate_repeat_exclusions_exact_match():
    with pytest.raises(GeneratorValidationError, match="exact duplicate"):
        validate_repeat_exclusions(
            prompt="What is kinetic energy?",
            exclusion_prompts=["What is kinetic energy?", "Other prompt"],
        )


def test_validate_repeat_exclusions_token_similarity():
    with pytest.raises(GeneratorValidationError, match="too similar"):
        validate_repeat_exclusions(
            prompt="Explain the formula for kinetic energy in physics",
            exclusion_prompts=["Explain the exact formula for kinetic energy in GCSE physics"],
        )


def test_recent_exclusion_prompts_round_robin_within_selected_preparations() -> None:
    newer, middle, older, outside_window = uuid4(), uuid4(), uuid4(), uuid4()
    rows = (
        (newer, 1, "newer question 2"),
        (middle, 0, "middle question 1"),
        (older, 1, "older question 2"),
        (newer, 0, "newer question 1"),
        (older, 0, "older question 1"),
        (outside_window, 0, "outside the selected three preparations"),
        (middle, 1, "middle question 2"),
    )

    assert _interleave_recent_exclusion_prompts(
        (newer, middle, older), rows
    ) == (
        "newer question 1",
        "middle question 1",
        "older question 1",
        "newer question 2",
        "middle question 2",
        "older question 2",
    )


# --- OpenAI Adapter Tests ---


@pytest.mark.anyio
async def test_openai_adapter_missing_api_key():
    adapter = OpenAiQuizContentGenerator(api_key="")
    assert adapter.is_available is False
    with pytest.raises(GeneratorUnavailableError, match="OPENAI_API_KEY is not configured"):
        await adapter.generate_quiz_questions(
            GenerationRequest("GCSE", "physics", "energy", 20)
        )


def test_generation_api_key_never_leaks_via_repr_or_wrapper() -> None:
    canary = "sk-CANARY-GENERATION-KEY-9f8e7d"
    adapter = OpenAiQuizContentGenerator(api_key=canary)
    assert adapter.is_available is True
    assert canary not in repr(adapter)
    assert canary not in repr(adapter._api_key)
    assert canary not in str(adapter._api_key)


@pytest.mark.anyio
async def test_openai_adapter_model_and_store_configuration():
    captured_request = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        captured_request.update(data)
        # Return valid Responses API structured output
        content_payload = {
            "questions": [
                {
                    "question_type": "MULTIPLE_CHOICE",
                    "prompt": "Test prompt?",
                    "max_marks": 1,
                    "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "correct_option_id": "a",
                    "grading_rubric": {
                "criteria": [],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
                    "worked_explanation": "Exp",
                    "original_extract": None,
                }
                for _ in range(5)
            ]
        }
        # Update each prompt to be unique
        for idx, q in enumerate(content_payload["questions"]):
            q["prompt"] = f"Test prompt {idx}?"

        return httpx.Response(
            200,
            json={
                "id": "resp_test_123",
                "status": "completed",
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(content_payload),
                            }
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenAiQuizContentGenerator(api_key="test_key", client=client)

    result = await adapter.generate_quiz_questions(
        GenerationRequest("GCSE", "physics", "energy", 5)
    )
    assert len(result) == 5
    assert captured_request["model"] == MODEL_ID_GPT_6_LUNA == "gpt-6-luna"
    assert captured_request["store"] is False
    assert captured_request["text"]["format"]["type"] == "json_schema"
    assert captured_request["text"]["format"]["strict"] is True
    # True Responses API contract: input items, no chat-completions fields,
    # no tools, no conversation linkage.
    assert isinstance(captured_request.get("input"), list)
    assert "messages" not in captured_request
    assert "response_format" not in captured_request
    assert "tools" not in captured_request
    assert "previous_response_id" not in captured_request
    assert "conversation" not in captured_request
    generation_instructions = captured_request["input"][0]["content"]
    assert "A name, number, or setting swap alone is not a new question" in generation_instructions
    assert "do not force novelty or drift off-topic" in generation_instructions
    assert "plain text/Unicode only" in generation_instructions
    assert "Do not emit TeX/LaTeX, HTML, MathML, Markdown formatting" in generation_instructions
    assert "Show multi-step working on separate lines" in generation_instructions
    assert "Do not claim alignment to any exam board" in generation_instructions


@pytest.mark.anyio
async def test_openai_adapter_uses_responses_endpoint_and_token_budget():
    seen: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        data = json.loads(request.content.decode("utf-8"))
        seen.update(data)
        content_payload = {
            "questions": [
                {
                    "question_type": "MULTIPLE_CHOICE",
                    "prompt": f"Endpoint probe {idx}?",
                    "max_marks": 1,
                    "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "correct_option_id": "a",
                    "grading_rubric": {
                "criteria": [],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
                    "worked_explanation": "Exp",
                    "original_extract": None,
                }
                for idx in range(5)
            ]
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_test_456",
                "status": "completed",
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": json.dumps(content_payload)}
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenAiQuizContentGenerator(api_key="test_key", client=client)
    await adapter.generate_quiz_questions(
        GenerationRequest("GCSE", "physics", "energy", 5)
    )
    assert seen["url"] == "https://api.openai.com/v1/responses"
    # Scaled ceiling: 8,192 + 1,500 per mark for a 5-mark budget.
    assert seen["max_output_tokens"] == 8192 + 1500 * 5
    assert "max_completion_tokens" not in seen


@pytest.mark.anyio
async def test_openai_adapter_handles_incomplete_status():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "resp_inc", "status": "incomplete", "error": None, "output": []},
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenAiQuizContentGenerator(api_key="test_key", client=client)

    with pytest.raises(GeneratorMalformedError, match="incomplete"):
        await adapter.generate_quiz_questions(
            GenerationRequest("GCSE", "physics", "energy", 5)
        )


def _generation_envelope(output: object, status: object = "completed") -> dict:
    return {"id": "resp_x", "status": status, "error": None, "output": output}


@pytest.mark.anyio
async def test_generation_envelope_refusal_wins_and_ambiguity_rejected() -> None:
    body = json.dumps({"questions": [_mcq_payload(idx) for idx in range(5)]})
    good_message = {
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": body}],
    }

    async def _generate(envelope: object) -> object:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json=envelope)
            )
        )
        return await OpenAiQuizContentGenerator(
            api_key="test_key", client=client
        ).generate_quiz_questions(GenerationRequest("GCSE", "physics", "energy", 5))

    with pytest.raises(GeneratorRefusalError):
        await _generate(
            _generation_envelope(
                [{"type": "refusal", "refusal": "CANARY_REFUSAL_TEXT"}, good_message]
            )
        )
    with pytest.raises(GeneratorMalformedError):
        await _generate(_generation_envelope([good_message, good_message]))
    with pytest.raises(GeneratorMalformedError):
        await _generate({"id": "r", "error": None, "output": [good_message]})
    with pytest.raises(GeneratorMalformedError):
        await _generate(
            {"id": "r", "status": "in_progress", "error": None, "output": [good_message]}
        )
    result = await _generate(_generation_envelope([good_message]))
    assert len(result) == 5


@pytest.mark.anyio
async def test_openai_adapter_handles_refusal():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_refusal",
                "status": "completed",
                "error": None,
                "output": [
                    {
                        "type": "refusal",
                        "refusal": "I cannot generate questions on this topic.",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenAiQuizContentGenerator(api_key="test_key", client=client)

    with pytest.raises(GeneratorRefusalError, match="Model refused"):
        await adapter.generate_quiz_questions(
            GenerationRequest("GCSE", "physics", "energy", 5)
        )


@pytest.mark.anyio
async def test_openai_adapter_handles_rate_limit_and_auth_error():
    transport_401 = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "auth"}))
    client_401 = httpx.AsyncClient(transport=transport_401)
    adapter_401 = OpenAiQuizContentGenerator(api_key="test_key", client=client_401)
    with pytest.raises(GeneratorAuthError):
        await adapter_401.generate_quiz_questions(
            GenerationRequest("GCSE", "physics", "energy", 5)
        )

    transport_429 = httpx.MockTransport(lambda req: httpx.Response(429, json={"error": "rate"}))
    client_429 = httpx.AsyncClient(transport=transport_429)
    adapter_429 = OpenAiQuizContentGenerator(api_key="test_key", client=client_429)
    with pytest.raises(GeneratorRateLimitedError):
        await adapter_429.generate_quiz_questions(
            GenerationRequest("GCSE", "physics", "energy", 5)
        )


# --- Fake Adapter Tests ---


@pytest.mark.anyio
async def test_fake_generator_sums_to_exact_target():
    fake = FakeQuizContentGenerator()
    for budget in (5, 10, 20, 35, 40):
        req = GenerationRequest("GCSE", "physics", "forces", budget)
        questions = await fake.generate_quiz_questions(req)
        assert sum(q.max_marks for q in questions) == budget
        for q in questions:
            assert 1 <= q.max_marks <= 6


# --- Preparation Repository & Service Integration Tests ---


@pytest.mark.anyio
async def test_quiz_preparation_service_lifecycle_and_idempotence(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
):
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    generator = FakeQuizContentGenerator()
    service = QuizPreparationService(
        prep_repo, room_repo, generator, verifier=FakeQuizContentVerifier()
    )

    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Adaptive Room",
        join_code="ADAP99",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="physics",
        quiz_topic="energy",
        target_total_marks=10,
    )
    owner_member = RoomMember(
        room_id=room_id,
        user_id=OWNER_ID,
        display_name="Owner",
    )
    room_repo.create_with_owner(room, owner_member)

    request_id = uuid4()

    # 1. First preparation: completes generation and transitions to READY
    prep = await service.prepare_quiz(
        room_id=room_id,
        request_id=request_id,
        user_id=OWNER_ID,
        wait_for_completion=True,
    )
    assert prep.is_ready is True
    assert len(prep.questions) > 0
    assert sum(q.max_marks for q in prep.questions) == 10
    assert generator.call_count == 1

    # 2. Idempotent retry with same request_id: returns same READY preparation without re-generating
    prep_retry = await service.prepare_quiz(
        room_id=room_id,
        request_id=request_id,
        user_id=OWNER_ID,
    )
    assert prep_retry.id == prep.id
    assert prep_retry.is_ready is True
    assert generator.call_count == 1  # Generator was NOT called again


@pytest.mark.anyio
async def test_quiz_preparation_service_conflicts_on_different_request(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
):
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    generator = FakeQuizContentGenerator()
    service = QuizPreparationService(
        prep_repo, room_repo, generator, verifier=FakeQuizContentVerifier()
    )

    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Conflict Room",
        join_code="CONF01",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="biology",
        quiz_topic="cells",
        target_total_marks=5,
    )
    owner_member = RoomMember(
        room_id=room_id,
        user_id=OWNER_ID,
        display_name="Owner",
    )
    room_repo.create_with_owner(room, owner_member)

    req1 = uuid4()
    prep1 = await service.prepare_quiz(
        room_id=room_id,
        request_id=req1,
        user_id=OWNER_ID,
        wait_for_completion=True,
    )
    assert prep1.is_ready is True

    # Attempting another preparation with a DIFFERENT request_id while prep1 is READY conflicts
    req2 = uuid4()
    with pytest.raises(PreparationConflictError):
        await service.prepare_quiz(room_id=room_id, request_id=req2, user_id=OWNER_ID)


@pytest.mark.anyio
async def test_quiz_preparation_repeat_exclusions_across_rooms(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
):
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    generator = FakeQuizContentGenerator()
    service = QuizPreparationService(
        prep_repo, room_repo, generator, verifier=FakeQuizContentVerifier()
    )

    # Room 1 by OWNER_ID for Chemistry / Bonding
    r1_id = uuid4()
    r1 = Room(
        id=r1_id,
        owner_id=OWNER_ID,
        name="Room 1",
        join_code="R1BOND",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="chemistry",
        quiz_topic="bonding",
        target_total_marks=5,
    )
    room_repo.create_with_owner(
        r1,
        RoomMember(room_id=r1_id, user_id=OWNER_ID, display_name="Owner"),
    )
    prep1 = await service.prepare_quiz(
        room_id=r1_id,
        request_id=uuid4(),
        user_id=OWNER_ID,
        wait_for_completion=True,
    )
    prompts_from_room_1 = {q.prompt for q in prep1.questions}
    room_repo.close_room(r1_id, OWNER_ID)


    # Room 2 reuses the owner after Room 1 is closed; its prior prompts remain
    # bounded repeat-exclusion history for the same host/topic.
    r2_id = uuid4()
    r2 = Room(
        id=r2_id,
        owner_id=OWNER_ID,
        name="Room 2",
        join_code="R2BOND",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="chemistry",
        quiz_topic="bonding",
        target_total_marks=5,
    )
    room_repo.create_with_owner(
        r2,
        RoomMember(room_id=r2_id, user_id=OWNER_ID, display_name="Owner"),
    )
    prep2 = await service.prepare_quiz(
        room_id=r2_id,
        request_id=uuid4(),
        user_id=OWNER_ID,
        wait_for_completion=True,
    )
    assert prep2.is_ready is True

    # Verify that generator was invoked with exclusion prompts from Room 1!
    assert generator.last_request is not None
    assert len(generator.last_request.exclusion_prompts) > 0
    for prompt in prompts_from_room_1:
        assert prompt in generator.last_request.exclusion_prompts


# --- Strict Structured Outputs schema invariants (offline) ---


def _assert_strict_object_schema(node: object, path: str = "$") -> None:
    """Every object schema must list all properties as required (strict mode)."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            properties = node.get("properties", {})
            required = node.get("required", [])
            assert isinstance(properties, dict), f"{path}: properties must be an object"
            assert set(required) == set(properties), (
                f"{path}: strict mode requires every property in required; "
                f"properties={sorted(properties)} required={sorted(required)}"
            )
            assert node.get("additionalProperties") is False, (
                f"{path}: strict mode requires additionalProperties=false"
            )
            for key, child in properties.items():
                _assert_strict_object_schema(child, f"{path}.{key}")
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), dict):
                _assert_strict_object_schema(node[key], f"{path}.{key}")
        for key, value in node.items():
            if isinstance(value, (dict, list)) and key not in ("properties", "items"):
                _assert_strict_object_schema(value, f"{path}.{key}")
    elif isinstance(node, list):
        for idx, child in enumerate(node):
            _assert_strict_object_schema(child, f"{path}[{idx}]")


def test_generation_schema_is_strict_valid() -> None:
    from app.generator.openai_adapter import _GENERATION_SCHEMA

    _assert_strict_object_schema(_GENERATION_SCHEMA)


def test_grading_schema_is_strict_valid() -> None:
    from app.grading.openai_grader import _GRADING_RESPONSE_SCHEMA

    _assert_strict_object_schema(_GRADING_RESPONSE_SCHEMA)


# --- Malformed-output validation battery (R11) ---


def _valid_written_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "question_type": "WRITTEN",
        "prompt": "Explain the theme.",
        "max_marks": 2,
        "options": [],
        "correct_option_id": None,
        "grading_rubric": {
            "criteria": [
                {
                    "id": "c1",
                    "marks": 2,
                    "marking_point": "Names the theme",
                    "accepted_meaning": "Theme identified",
                    "spelling_sensitive": False,
                    "explanation": "Must name the theme.",
                }
            ],
            "expected_value": None,
            "absolute_tolerance": None,
            "allowed_units": [],
            "value_marks": 0,
            "unit_marks": 0,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "The theme is contrast, shown step by step.",
        "original_extract": None,
    }
    payload.update(overrides)
    return payload


def _valid_numerical_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "question_type": "NUMERICAL",
        "prompt": "Calculate the force.",
        "max_marks": 2,
        "options": [],
        "correct_option_id": None,
        "grading_rubric": {
            "criteria": [],
            "expected_value": "10.0",
            "absolute_tolerance": "0.5",
            "allowed_units": ["n"],
            "value_marks": 1,
            "unit_marks": 1,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "F = m a = 2 x 5 = 10 N.",
        "original_extract": None,
    }
    payload.update(overrides)
    return payload


def test_synthetic_physics_speed_example_is_validator_backed() -> None:
    # Synthetic teaching example only; it is not a frozen simulator or acceptance fixture.
    question = {
        "question_type": "NUMERICAL",
        "prompt": "A cyclist travels 100 m in 5 s. What is the average speed? Give your answer in m/s.",
        "max_marks": 2,
        "options": [],
        "correct_option_id": None,
        "grading_rubric": {
            "criteria": [],
            "expected_value": "20",
            "absolute_tolerance": "0",
            "allowed_units": ["m/s"],
            "value_marks": 1,
            "unit_marks": 1,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": (
            "Speed = distance ÷ time\n"
            "Speed = 100 m ÷ 5 s\n"
            "Speed = 20 m/s."
        ),
        "original_extract": None,
    }

    validated = validate_single_question(question, position=0)
    rubric = NumericalRubric.from_dict(validated.grading_rubric)

    assert validated.prompt == question["prompt"]
    assert validated.worked_explanation == question["worked_explanation"]
    assert grade_numerical("20 m/s", rubric)[:2] == (2, True)


def _payload_with_display_markup(display_field: str, markup: str) -> dict[str, Any]:
    if display_field == "options":
        payload = _valid_written_payload(
            question_type="MULTIPLE_CHOICE",
            max_marks=1,
            options=[{"id": "a", "label": "plain"}, {"id": "b", "label": "plain"}],
            correct_option_id="a",
            grading_rubric={
                "criteria": [],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
        )
        payload["options"][0]["label"] = markup
        return payload

    if display_field in ("marking_point", "accepted_meaning", "explanation"):
        payload = _valid_written_payload()
        payload["grading_rubric"]["criteria"][0][display_field] = markup
        return payload

    return _valid_numerical_payload(**{display_field: markup})


_HTML_VOID_TAG_NAMES = (
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
)
_HTML_VOID_TAG_DISPLAY_SAMPLES = tuple(
    f"Choose<{tag}>the positive number." for tag in _HTML_VOID_TAG_NAMES
) + (
    "Choose<br/>the positive number.",
    'Choose<img src="diagram.png">the positive number.',
)
_HTML_MULTILETTER_TAG_DISPLAY_SAMPLES = tuple(
    f"Choose<{tag}>the positive number."
    for tag in ("div", "span", "script", "strong", "em", "table")
) + ('Choose<div class="example">the positive number.',)


@pytest.mark.parametrize(
    "display_field",
    (
        "prompt",
        "options",
        "worked_explanation",
        "original_extract",
        "marking_point",
        "accepted_meaning",
        "explanation",
    ),
)
@pytest.mark.parametrize(
    "markup",
    (
        "<span>formatted</span>",
        "<math><mi>x</mi></math>",
        r"\frac{1}{2}",
        r"\(x^2 + 1\)",
        "$x^2$",
        "**formatted**",
        "# Heading",
        "`code`",
        "```\ncode\n```",
        "[answer](https://example.test)",
        "&lt;",
        *_HTML_VOID_TAG_DISPLAY_SAMPLES,
        *_HTML_MULTILETTER_TAG_DISPLAY_SAMPLES,
    ),
)
def test_validator_rejects_unsupported_markup_in_each_display_string(
    display_field: str, markup: str
) -> None:
    payload = _payload_with_display_markup(display_field, markup)

    with pytest.raises(GeneratorValidationError, match="unsupported display markup") as error:
        validate_single_question(payload, position=0)

    assert markup not in str(error.value)


def test_validator_accepts_plain_unicode_math_and_comparison_symbols() -> None:
    payload = _valid_numerical_payload(
        prompt="For x = 3, evaluate x² + 1. Is x < 5? Check 0 < x < 5.",
        worked_explanation="x² + 1 = 3² + 1\n= 9 + 1\n= 10.",
    )

    validated = validate_single_question(payload, position=0)

    assert "x² + 1" in validated.prompt
    assert "x < 5" in validated.prompt
    assert "0 < x < 5" in validated.prompt


@pytest.mark.parametrize(
    "prompt",
    (
        "Given 0<x and y>0, which listed value can x take?",
        "Given 0 < x and y > 0, which listed value can x take?",
        "Given 0<x and y > 0, which listed value can x take?",
        "For a<b and c>d, choose the valid ordered pair.",
        "Given 0<x≤3 and y≥0, select the interval that fits.",
    ),
)
def test_validator_preserves_compact_spaced_and_mixed_inequalities(prompt: str) -> None:
    validated = validate_single_question(
        _valid_numerical_payload(prompt=prompt), position=0
    )

    assert validated.prompt == prompt


def test_validate_rejects_malformed_primitives_and_shapes() -> None:
    cases = [
        "not-a-dict",
        42,
        None,
        {**_valid_written_payload(), "max_marks": 2.0},
        {**_valid_written_payload(), "max_marks": True},
        {**_valid_written_payload(), "max_marks": "2"},
        {**_valid_written_payload(), "prompt": 123},
        {**_valid_written_payload(), "question_type": "ESSAY"},
        {**_valid_written_payload(), "question_type": 7},
        {**_valid_written_payload(), "options": {}},
        {**_valid_written_payload(), "options": [{"id": "a"}]},
        {**_valid_written_payload(), "options": [{"id": 1, "label": "x"}]},
        {**_valid_written_payload(), "grading_rubric": []},
        {**_valid_written_payload(), "grading_rubric": {"criteria": {}}},
        {**_valid_written_payload(), "grading_rubric": {"criteria": ["c1"]}},
        {**_valid_written_payload(), "worked_explanation": "   "},
        {**_valid_written_payload(), "prompt": "Bad\x00prompt"},
        {**_valid_written_payload(), "worked_explanation": "Bad\x1bexplanation"},
    ]
    for idx, payload in enumerate(cases):
        with pytest.raises(GeneratorValidationError):
            validate_single_question(payload, position=0)


def test_validate_rejects_malformed_numerical_rubrics() -> None:
    def _rubric(**overrides: Any) -> dict[str, Any]:
        rubric = {
            "criteria": [],
            "expected_value": "10.0",
            "absolute_tolerance": "0.5",
            "allowed_units": ["n"],
            "value_marks": 1,
            "unit_marks": 1,
            "unit_dependency": "REQUIRES_VALUE",
        }
        rubric.update(overrides)
        return rubric

    cases = [
        _rubric(expected_value="NaN"),
        _rubric(expected_value="Infinity"),
        _rubric(expected_value=""),
        _rubric(expected_value=10.5),
        _rubric(expected_value=True),
        _rubric(absolute_tolerance="-0.5"),
        _rubric(absolute_tolerance="unbounded"),
        _rubric(value_marks=0),
        _rubric(value_marks="1"),
        _rubric(value_marks=True),
        _rubric(unit_marks=-1),
        _rubric(unit_marks="0"),
        _rubric(unit_marks=1, allowed_units=[]),
        _rubric(unit_marks=1, allowed_units=["  "]),
        _rubric(unit_marks=1, allowed_units=["n", 5]),
        _rubric(unit_dependency="SOMETIMES"),
        _rubric(unit_dependency=3),
        {k: v for k, v in _rubric().items() if k != "unit_dependency"},
        # Exact total: 1 + 1 != max_marks 3.
        _rubric(),
    ]
    for idx, rubric in enumerate(cases):
        payload = _valid_numerical_payload(grading_rubric=rubric)
        if idx == len(cases) - 1:
            payload["max_marks"] = 3
        with pytest.raises(GeneratorValidationError):
            validate_single_question(payload, position=0)


@pytest.mark.parametrize(
    "bad_unit",
    [
        "e",
        "E",
        "×2",
        "300×2",
        "or",
        "and",
        "2N/4",
        "m/or",
        "N/and²",
        "e^2",
        "N/e",
    ],
)
def test_validate_rejects_unsupported_unit_aliases(bad_unit: str) -> None:
    rubric = {
        "criteria": [],
        "expected_value": "10",
        "absolute_tolerance": "0.5",
        "allowed_units": [bad_unit],
        "value_marks": 1,
        "unit_marks": 1,
        "unit_dependency": "REQUIRES_VALUE",
    }
    payload = _valid_numerical_payload(grading_rubric=rubric)
    with pytest.raises(GeneratorValidationError, match="contains an unsupported unit alias"):
        validate_single_question(payload, position=0)


@pytest.mark.parametrize(
    "good_unit",
    [
        "×",
        "x",
        "times",
        "m/s^2",
        "m/s²",
        "N/kg",
        "Ω",
        "ω",
        "µs",
        "kg",
        "m",
        "s",
        "deg",
        "ev",
        "%",
    ],
)
def test_validate_accepts_supported_unit_aliases(good_unit: str) -> None:
    rubric = {
        "criteria": [],
        "expected_value": "10",
        "absolute_tolerance": "0.5",
        "allowed_units": [good_unit],
        "value_marks": 1,
        "unit_marks": 1,
        "unit_dependency": "REQUIRES_VALUE",
    }
    payload = _valid_numerical_payload(grading_rubric=rubric)
    validated = validate_single_question(payload, position=0)
    assert validated.grading_rubric["allowed_units"] == [good_unit]

def test_validate_rejects_malformed_written_criteria() -> None:
    def _criteria(entries: list[dict[str, Any]]) -> dict[str, Any]:
        return _valid_written_payload(
            grading_rubric={
                "criteria": entries,
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            }
        )

    good = {
        "id": "c1",
        "marks": 2,
        "marking_point": "Names the theme",
        "accepted_meaning": "Theme identified",
        "spelling_sensitive": False,
        "explanation": "Must name the theme.",
    }
    cases = [
        [{**good, "id": 7}],
        [{**good, "id": "  "}],
        [{**good, "id": "x" * 65}],
        [{**good, "marks": "2"}],
        [{**good, "marks": True}],
        [{**good, "marks": 2.0}],
        [{**good, "spelling_sensitive": "yes"}],
        [{**good, "spelling_sensitive": 1}],
        [{**good, "marking_point": 42}],
        [{**good, "accepted_meaning": None}],
        [{**good, "explanation": ""}],
        [{**good, "explanation": "x" * 2001}],
        [{**good, "marking_point": "ok\x00"}],
        [good, {**good, "id": "c1"}],
    ]
    for idx, payload in enumerate(cases):
        with pytest.raises(GeneratorValidationError):
            validate_single_question(_criteria(payload), position=0)
    # Criteria sum 2 != max_marks 3 is rejected as an exact-total violation.
    with pytest.raises(GeneratorValidationError):
        validate_single_question(
            _valid_written_payload(
                max_marks=3,
                grading_rubric={
                    "criteria": [
                        {**good, "id": "c1", "marks": 1},
                        {**good, "id": "c2", "marks": 1},
                    ],
                    "expected_value": None,
                    "absolute_tolerance": None,
                    "allowed_units": [],
                    "value_marks": 0,
                    "unit_marks": 0,
                    "unit_dependency": "REQUIRES_VALUE",
                },
            ),
            position=0,
        )


def _canonical_sentinels(**overrides: Any) -> dict[str, Any]:
    rubric: dict[str, Any] = {
        "criteria": [],
        "expected_value": None,
        "absolute_tolerance": None,
        "allowed_units": [],
        "value_marks": 0,
        "unit_marks": 0,
        "unit_dependency": "REQUIRES_VALUE",
    }
    rubric.update(overrides)
    return rubric


def test_cross_variant_rubric_pollution_rejected() -> None:
    """MCQ/WRITTEN must carry canonical unused sentinels; NUMERICAL no criteria."""
    mcq_base = {
        "question_type": "MULTIPLE_CHOICE",
        "prompt": "Pick the device.",
        "max_marks": 1,
        "options": [{"id": "a", "label": "Metaphor"}, {"id": "b", "label": "Spoon"}],
        "correct_option_id": "a",
        "worked_explanation": "A is correct.",
        "original_extract": None,
    }
    polluted_mcq = [
        _canonical_sentinels(expected_value="10.0"),
        _canonical_sentinels(absolute_tolerance="0.5"),
        _canonical_sentinels(allowed_units=["n"]),
        _canonical_sentinels(value_marks=1),
        _canonical_sentinels(unit_marks=1),
        _canonical_sentinels(unit_dependency="BOGUS"),
        {k: v for k, v in _canonical_sentinels().items() if k != "unit_dependency"},
    ]
    for rubric in polluted_mcq:
        with pytest.raises(GeneratorValidationError):
            validate_single_question(
                {**mcq_base, "grading_rubric": rubric}, position=0
            )

    written_base = _valid_written_payload()
    for rubric in polluted_mcq:
        criteria = _canonical_sentinels()["criteria"]
        with pytest.raises(GeneratorValidationError):
            validate_single_question(
                {
                    **written_base,
                    "grading_rubric": {**rubric, "criteria": written_base["grading_rubric"]["criteria"]},
                },
                position=0,
            )

    numerical_base = _valid_numerical_payload()
    with pytest.raises(GeneratorValidationError):
        validate_single_question(
            {
                **numerical_base,
                "grading_rubric": {
                    **numerical_base["grading_rubric"],
                    "criteria": [
                        {
                            "id": "c1",
                            "marks": 1,
                            "marking_point": "x",
                            "accepted_meaning": "x",
                            "spelling_sensitive": False,
                            "explanation": "x",
                        }
                    ],
                },
            },
            position=0,
        )
    # Canonical shapes validate on every variant.
    validate_single_question(
        {**mcq_base, "grading_rubric": _canonical_sentinels()}, position=0
    )
    validate_single_question(written_base, position=0)
    validate_single_question(numerical_base, position=0)


def test_validate_rejects_mcq_rubric_mismatch() -> None:
    base = {
        "question_type": "MULTIPLE_CHOICE",
        "prompt": "Pick the device.",
        "max_marks": 1,
        "options": [{"id": "a", "label": "Metaphor"}, {"id": "b", "label": "Spoon"}],
        "correct_option_id": "a",
        "worked_explanation": "A is correct.",
        "original_extract": None,
    }
    with pytest.raises(GeneratorValidationError):
        validate_single_question(
            {**base, "grading_rubric": {"criteria": [{"id": "c1"}]}}, position=0
        )
    with pytest.raises(GeneratorValidationError):
        validate_single_question(
            {**base, "grading_rubric": {"expected_value": "10"}}, position=0
        )
    # Canonical empty MCQ rubric validates.
    validated = validate_single_question({**base, "grading_rubric": {
        "criteria": [],
        "expected_value": None,
        "absolute_tolerance": None,
        "allowed_units": [],
        "value_marks": 0,
        "unit_marks": 0,
        "unit_dependency": "REQUIRES_VALUE",
    }}, position=0)
    assert validated.question_type == QuestionType.MULTIPLE_CHOICE


@pytest.mark.anyio
async def test_provider_refusal_content_never_logged(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Refusal text is untrusted output: logs keep category + local IDs only."""
    import logging

    from app.generator.protocol import GeneratorRefusalError

    canary = "CANARY_PROVIDER_REFUSAL_7q9z"

    class RefusingGenerator:
        async def generate_quiz_questions(self, request: GenerationRequest) -> tuple[GeneratedQuestionData, ...]:
            raise GeneratorRefusalError(f"Model refused: {canary}")

    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    service = QuizPreparationService(
        prep_repo,
        room_repo,
        RefusingGenerator(),
        verifier=FakeQuizContentVerifier(),
    )

    room_id = uuid4()
    room_repo.create_with_owner(
        Room(
            id=room_id,
            owner_id=OWNER_ID,
            name="Canary Room",
            join_code="CANARY",
            maximum_members=8,
            quiz_mode="ADAPTIVE",
            education_level="GCSE",
            quiz_subject="physics",
            quiz_topic="energy",
            target_total_marks=5,
        ),
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Owner"),
    )
    request_id = uuid4()
    with caplog.at_level(logging.WARNING):
        prep = await service.prepare_quiz(
            room_id=room_id,
            request_id=request_id,
            user_id=OWNER_ID,
            wait_for_completion=True,
        )
    assert prep.is_failed is True
    assert prep.error_category == "refusal"
    assert canary not in caplog.text


@pytest.mark.anyio
async def test_validation_ids_never_logged_verbatim(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Model-supplied IDs in validation errors must not reach logs verbatim."""
    import logging

    canary = "CANARY_OPTION_ID_xq42"

    class PollutingGenerator:
        async def generate_quiz_questions(self, request: GenerationRequest) -> tuple[GeneratedQuestionData, ...]:
            return (
                GeneratedQuestionData(
                    position=0,
                    question_type=QuestionType.MULTIPLE_CHOICE,
                    prompt="Pick one.",
                    max_marks=1,
                    duration_seconds=30,
                    options=(
                        MultipleChoiceOption(id="a", label="A"),
                        MultipleChoiceOption(id="b", label="B"),
                    ),
                    correct_option_id=canary,
                    grading_rubric={
                        "criteria": [],
                        "expected_value": None,
                        "absolute_tolerance": None,
                        "allowed_units": [],
                        "value_marks": 0,
                        "unit_marks": 0,
                        "unit_dependency": "REQUIRES_VALUE",
                    },
                    worked_explanation="Exp.",
                    original_extract=None,
                    content_fingerprint="fp-canary",
                ),
            )

    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    service = QuizPreparationService(
        prep_repo,
        room_repo,
        PollutingGenerator(),
        verifier=FakeQuizContentVerifier(),
    )

    room_id = uuid4()
    room_repo.create_with_owner(
        Room(
            id=room_id,
            owner_id=OWNER_ID,
            name="Canary Room Two",
            join_code="CANAR2",
            maximum_members=8,
            quiz_mode="ADAPTIVE",
            education_level="GCSE",
            quiz_subject="physics",
            quiz_topic="energy",
            target_total_marks=5,
        ),
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Owner"),
    )
    with caplog.at_level(logging.WARNING):
        prep = await service.prepare_quiz(
            room_id=room_id,
            request_id=uuid4(),
            user_id=OWNER_ID,
            wait_for_completion=True,
        )
    # Unknown correct_option_id fails trust-boundary validation twice → FAILED.
    assert prep.is_failed is True
    assert canary not in caplog.text


@pytest.mark.anyio
async def test_content_validation_failure_triggers_single_retry_only(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    calls = {"count": 0}

    class FlakyOnceGenerator:
        async def generate_quiz_questions(
            self, request: GenerationRequest
        ) -> tuple[GeneratedQuestionData, ...]:
            calls["count"] += 1
            if calls["count"] == 1:
                # Malformed first attempt: wrong primitive types.
                return validate_generated_quiz_set(
                    [_valid_written_payload(max_marks="two")],
                    target_total_marks=request.target_total_marks,
                )
            fake = FakeQuizContentGenerator()
            return await fake.generate_quiz_questions(request)

    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    service = QuizPreparationService(
        prep_repo,
        room_repo,
        FlakyOnceGenerator(),
        verifier=FakeQuizContentVerifier(),
    )

    room_id = uuid4()
    room_repo.create_with_owner(
        Room(
            id=room_id,
            owner_id=OWNER_ID,
            name="Retry Room",
            join_code="RETRY1",
            maximum_members=8,
            quiz_mode="ADAPTIVE",
            education_level="GCSE",
            quiz_subject="physics",
            quiz_topic="energy",
            target_total_marks=5,
        ),
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Owner"),
    )
    prep = await service.prepare_quiz(
        room_id=room_id,
        request_id=uuid4(),
        user_id=OWNER_ID,
        wait_for_completion=True,
    )
    assert prep.is_ready is True
    # Exactly one content-only regeneration: no more, no fewer.
    assert calls["count"] == 2
    assert sum(q.max_marks for q in prep.questions) == 5


# --- 40-mark output ceiling (R18, offline, no live call) ---


def _mcq_payload(idx: int) -> dict:
    return {
        "question_type": "MULTIPLE_CHOICE",
        "prompt": f"Identify the correct statement about forces item {idx}.",
        "max_marks": 1,
        "options": [
            {"id": "opt_a", "label": "Correct statement"},
            {"id": "opt_b", "label": "Distractor one"},
            {"id": "opt_c", "label": "Distractor two"},
        ],
        "correct_option_id": "opt_a",
        "grading_rubric": {
            "criteria": [],
            "expected_value": None,
            "absolute_tolerance": None,
            "allowed_units": [],
            "value_marks": 0,
            "unit_marks": 0,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": (
            f"Option A is correct because the definition of forces item {idx} "
            f"matches the marking point step by step."
        ),
        "original_extract": None,
    }


def test_forty_unique_one_mark_questions_validate() -> None:
    validated = validate_generated_quiz_set(
        [_mcq_payload(idx) for idx in range(40)], target_total_marks=40
    )
    assert len(validated) == 40
    assert sum(q.max_marks for q in validated) == 40
    assert len({q.content_fingerprint for q in validated}) == 40


def test_compact_longer_question_mix_sums_to_forty() -> None:
    payloads = []
    for idx in range(10):
        payload = _valid_written_payload(
            prompt=f"Discuss forces theme {idx}.",
            max_marks=4,
            grading_rubric={
                "criteria": [
                    {
                        "id": f"c{idx}a",
                        "marks": 2,
                        "marking_point": "States the principle",
                        "accepted_meaning": "Principle stated",
                        "spelling_sensitive": False,
                        "explanation": "Must state the principle.",
                    },
                    {
                        "id": f"c{idx}b",
                        "marks": 2,
                        "marking_point": "Applies the principle",
                        "accepted_meaning": "Application shown",
                        "spelling_sensitive": False,
                        "explanation": "Must apply the principle.",
                    },
                ],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
        )
        payloads.append(payload)
    validated = validate_generated_quiz_set(payloads, target_total_marks=40)
    assert len(validated) == 10
    assert sum(q.max_marks for q in validated) == 40


@pytest.mark.anyio
async def test_adapter_token_ceiling_covers_forty_marks() -> None:
    import json as _json

    seen: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        seen.update(_json.loads(request.content.decode("utf-8")))
        body = _json.dumps({"questions": [_mcq_payload(idx) for idx in range(40)]})
        return httpx.Response(
            200,
            json={
                "id": "resp_40",
                "status": "completed",
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": body}],
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = OpenAiQuizContentGenerator(api_key="test_key", client=client)
    result = await adapter.generate_quiz_questions(
        GenerationRequest("GCSE", "physics", "forces", 40)
    )
    assert len(result) == 40
    assert seen["max_output_tokens"] == 8192 + 1500 * 40
    assert seen["max_output_tokens"] <= 128_000
