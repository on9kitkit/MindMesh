"""Offline integration tests for content-verification gate service wiring and tamper checks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.domain.adaptive_quiz import (
    MultipleChoiceOption,
    PreparationStatus,
    QuestionType,
)
from app.domain.errors import (
    AiGenerationUnavailableError,
    PreparationConflictError,
    QuizNotReadyError,
)
from app.domain.quiz_preparation import GeneratedQuestion, QuizPreparation
from app.domain.room import Room
from app.generator.protocol import GeneratedQuestionData, GenerationRequest
from app.generator.verification import (
    VERIFICATION_REVISION,
    ConsistencyRejectionReason,
    ConsistencyVerdict,
    FakeBlindQuizSolver,
    FakeQuizConsistencyAssessor,
    FakeQuizContentVerifier,
    QuestionConsistencyVerdict,
    QuizContentVerificationService,
    VerificationInvalidError,
    VerificationRejectedError,
    VerificationTimeoutError,
    VerificationUnavailableError,
    VerifiedQuizSet,
    compute_verified_content_digest,
    make_sample_consistent_quiz_set,
)
from app.repositories.quiz_preparations import QuizPreparationRepository
from app.repositories.rooms import RoomRepository
from app.services.quiz_preparation_service import QuizPreparationService


def _sample_room(room_id: Any = None, owner_id: Any = None) -> Room:
    return Room(
        id=room_id or uuid4(),
        owner_id=owner_id or uuid4(),
        name="Verification Test Room",
        join_code="VRF234",
        maximum_members=8,
        closed_at=None,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="mathematics",
        quiz_topic="algebra",
        target_total_marks=5,
    )


def _sample_prep(room: Room, request_id: Any = None) -> QuizPreparation:
    now = datetime.now(timezone.utc)
    return QuizPreparation(
        id=uuid4(),
        room_id=room.id,
        request_id=request_id or uuid4(),
        status=PreparationStatus.GENERATING,
        state_version=1,
        generation_attempt=1,
        claim_token=uuid4(),
        lease_expires_at=now + timedelta(seconds=75),
        model_id="gpt-5.6-luna",
        error_category=None,
        created_at=now,
        updated_at=now,
        ready_at=None,
        consumed_at=None,
    )


@pytest.mark.anyio
async def test_quiz_preparation_service_verification_success() -> None:
    """Verify QuizPreparationService runs verifier, passes revision/digest, and commits READY."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.renew_preparation_lease_cas.return_value = True
    prep_repo.store_generated_questions_cas.return_value = True

    ready_prep = replace(
        prep,
        status=PreparationStatus.READY,
        verification_revision=VERIFICATION_REVISION,
        verified_content_digest=compute_verified_content_digest(questions),
    )
    prep_repo.get_by_id.return_value = ready_prep

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    verifier = FakeQuizContentVerifier()
    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=verifier,
    )

    result = await service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True)
    assert result.is_ready
    assert result.verification_revision == VERIFICATION_REVISION

    # Verify store_generated_questions_cas was called with verified quiz set
    prep_repo.store_generated_questions_cas.assert_called_once()
    kwargs = prep_repo.store_generated_questions_cas.call_args.kwargs
    assert kwargs["verified_quiz_set"].verification_revision == VERIFICATION_REVISION
    assert kwargs["verified_quiz_set"].verified_content_digest == compute_verified_content_digest(questions)


@pytest.mark.anyio
async def test_quiz_preparation_service_verification_rejection_marks_failed() -> None:
    """Verify that verifier rejection marks preparation FAILED with 'verification_rejected'."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.mark_preparation_failed_cas.return_value = True

    failed_prep = replace(prep, status=PreparationStatus.FAILED, error_category="verification_rejected")
    prep_repo.get_by_id.return_value = failed_prep

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    verifier = Mock()
    verifier.verify_quiz_content = AsyncMock(
        side_effect=VerificationRejectedError(
            "Rejected.",
            reasons=(ConsistencyRejectionReason.KEY_MISMATCH,),
            rejected_positions=(0,),
        )
    )

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=verifier,
    )

    result = await service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True)
    assert result.is_failed

    # store_generated_questions_cas must NOT be called on rejection
    prep_repo.store_generated_questions_cas.assert_not_called()
    prep_repo.mark_preparation_failed_cas.assert_called_once()
    kwargs = prep_repo.mark_preparation_failed_cas.call_args.kwargs
    assert kwargs["error_category"] == "verification_rejected"


@pytest.mark.anyio
async def test_quiz_preparation_service_verification_timeout_marks_failed() -> None:
    """Verify that verifier timeout marks preparation FAILED with 'timeout'."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.mark_preparation_failed_cas.return_value = True

    failed_prep = replace(prep, status=PreparationStatus.FAILED, error_category="timeout")
    prep_repo.get_by_id.return_value = failed_prep

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    verifier = Mock()
    verifier.verify_quiz_content = AsyncMock(
        side_effect=VerificationTimeoutError("Blind solve timed out.")
    )

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=verifier,
    )

    result = await service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True)
    assert result.is_failed

    prep_repo.store_generated_questions_cas.assert_not_called()
    prep_repo.mark_preparation_failed_cas.assert_called_once()
    kwargs = prep_repo.mark_preparation_failed_cas.call_args.kwargs
    assert kwargs["error_category"] == "timeout"


@pytest.mark.anyio
async def test_quiz_preparation_service_verification_unavailable_raises_api_error() -> None:
    """Verify that verifier unavailability marks FAILED and raises AiGenerationUnavailableError."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.mark_preparation_failed_cas.return_value = True
    prep_repo.get_by_id.return_value = replace(
        prep,
        status=PreparationStatus.FAILED,
        error_category="ai_generation_unavailable",
    )

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    verifier = Mock()
    verifier.verify_quiz_content = AsyncMock(
        side_effect=VerificationUnavailableError("API key not configured.")
    )

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=verifier,
    )

    with pytest.raises(AiGenerationUnavailableError):
        await service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True)
    prep_repo.store_generated_questions_cas.assert_not_called()
    prep_repo.mark_preparation_failed_cas.assert_called_once()
    kwargs = prep_repo.mark_preparation_failed_cas.call_args.kwargs
    assert kwargs["error_category"] == "ai_generation_unavailable"


@pytest.mark.anyio
async def test_quiz_preparation_service_caller_disconnect_preserves_task_and_admission() -> None:
    """Verify that cancelling caller wait does NOT cancel background preparation task, holding admission."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.store_generated_questions_cas.return_value = True

    ready_prep = replace(prep, status=PreparationStatus.READY, verification_revision=VERIFICATION_REVISION, verified_content_digest="digest")
    prep_repo.get_by_id.return_value = ready_prep

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    gen_started = asyncio.Event()
    slow_event = asyncio.Event()

    async def slow_generate(request: Any) -> tuple[GeneratedQuestionData, ...]:
        gen_started.set()
        await slow_event.wait()
        return questions

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(side_effect=slow_generate)

    admission = Mock()
    admission.acquire.return_value = True
    admission.release = Mock()
    terminal_broadcasts: list[tuple[Any, Any]] = []

    async def terminal_hook(room_id: Any, finished_prep: Any) -> None:
        terminal_broadcasts.append((room_id, finished_prep))

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
        admission=admission,
        on_terminal=terminal_hook,
    )

    # Launch prepare_quiz with wait_for_completion=True so caller is actively awaiting completion
    caller_task = asyncio.create_task(service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True))
    await gen_started.wait()

    # Verify background task is running in service._running
    assert len(service._running) == 1
    bg_task = next(iter(service._running))

    # Cancel caller wait
    caller_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller_task

    # Background task must NOT be cancelled!
    assert not bg_task.cancelled()
    assert admission.release.call_count == 0  # Admission slot still held

    # Allow generation to finish
    slow_event.set()
    await bg_task

    # Task finishes, store_generated_questions_cas is called, and admission is released
    assert bg_task.done()
    assert admission.release.call_count == 1
    prep_repo.store_generated_questions_cas.assert_called_once()
    assert terminal_broadcasts == [(room.id, ready_prep)]


@pytest.mark.anyio
async def test_quiz_preparation_service_lease_renewal_failure_aborts_verification() -> None:
    """Verify that failing lease renewal during verification aborts without paid calls."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    # Lease renewal fails (e.g. room closed or expired)
    prep_repo.renew_preparation_lease_cas.return_value = False
    prep_repo.mark_preparation_failed_cas.return_value = True

    failed_prep = replace(prep, status=PreparationStatus.FAILED, error_category="ai_generation_unavailable")
    prep_repo.get_by_id.return_value = failed_prep

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    # Verifier with real service wrapper to exercise before_paid_phase callback
    solver = FakeBlindQuizSolver()
    assessor = FakeQuizConsistencyAssessor()
    verifier = QuizContentVerificationService(solver, assessor)

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=verifier,
    )

    with pytest.raises(AiGenerationUnavailableError):
        await service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True)

    # Provider solver was never called because callback failed before blind solve!
    assert len(solver.calls) == 0
    prep_repo.store_generated_questions_cas.assert_not_called()
    prep_repo.mark_preparation_failed_cas.assert_called_once()
    kwargs = prep_repo.mark_preparation_failed_cas.call_args.kwargs
    assert kwargs["error_category"] == "ai_generation_unavailable"


def test_start_session_tamper_evidence_digest_check() -> None:
    """Verify that start_session rejects tampered questions or mismatched digests."""
    questions = make_sample_consistent_quiz_set()
    valid_digest = compute_verified_content_digest(questions, VERIFICATION_REVISION)

    # 1. Digest mismatch detection: tampered prompt produces different digest
    tampered_questions = (replace(questions[0], prompt="Tampered prompt in database"), questions[1], questions[2])
    tampered_digest = compute_verified_content_digest(tampered_questions, VERIFICATION_REVISION)
    assert tampered_digest != valid_digest
    # 2. Revision mismatch detection
    assert compute_verified_content_digest(questions, "old_revision") != valid_digest
@pytest.mark.anyio
async def test_quiz_preparation_service_early_claim_ack_returns_generating_within_10s() -> None:
    """Verify default prepare_quiz returns early durable claim acknowledgment in GENERATING state immediately."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.store_generated_questions_cas.return_value = True

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    # Simulate slow generator: caller must not block on generation
    gen_started = asyncio.Event()
    async def slow_gen(req: Any) -> Any:
        gen_started.set()
        await asyncio.sleep(0.5)
        return questions

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(side_effect=slow_gen)

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
    )

    # Default call without wait_for_completion returns early ACK within 10s
    ack_result = await service.prepare_quiz(room.id, prep.request_id, room.owner_id)
    assert ack_result.is_generating
    assert ack_result.id == prep.id
    assert ack_result.status == PreparationStatus.GENERATING

    # Clean up background task
    await gen_started.wait()
    await service.shutdown()


@pytest.mark.anyio
async def test_quiz_preparation_service_pre_ack_cancel_late_claim_never_pays() -> None:
    """A pre-ACK disconnect and late claim fail closed before any provider call."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None

    claim_entered = Event()
    release_claim = Event()

    def blocking_claim(*args: Any, **kwargs: Any) -> tuple[QuizPreparation, bool]:
        claim_entered.set()
        assert release_claim.wait(1)
        return prep, True

    prep_repo.claim_or_create_preparation = Mock(side_effect=blocking_claim)
    prep_repo.mark_preparation_failed_cas.return_value = True

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
    )

    try:
        # Use the real wait_for/cancellation path, shortening only this test's
        # deadline so the independent monotonic guard is deterministic.
        with patch("app.services.quiz_preparation_service.CLAIM_ACK_TIMEOUT_SECONDS", 0.05):
            caller = asyncio.create_task(
                service.prepare_quiz(room.id, prep.request_id, room.owner_id)
            )
            assert await asyncio.to_thread(claim_entered.wait, 1)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            await asyncio.sleep(0.06)
            release_claim.set()
            background = next(iter(service._running))
            await asyncio.wait_for(asyncio.shield(background), timeout=1)

        assert generator.generate_quiz_questions.await_count == 0
        prep_repo.mark_preparation_failed_cas.assert_called_once()
        assert (
            prep_repo.mark_preparation_failed_cas.call_args.kwargs["error_category"]
            == "claim_ack_timeout"
        )
    finally:
        release_claim.set()
        await service.shutdown()


@pytest.mark.anyio
async def test_quiz_preparation_service_timely_ack_survives_slow_claimed_hook() -> None:
    """A timely ACK keeps the 165s pipeline valid after the 10s ACK window passes."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.store_generated_questions_cas.return_value = True
    prep_repo.get_by_id.return_value = replace(
        prep,
        status=PreparationStatus.READY,
        verification_revision=VERIFICATION_REVISION,
        verified_content_digest="digest",
    )

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)
    claimed = asyncio.Event()

    async def slow_claimed_hook(room_id: Any, claimed_prep: Any) -> None:
        claimed.set()
        await asyncio.sleep(0.06)

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
        on_claimed=slow_claimed_hook,
    )

    try:
        with patch("app.services.quiz_preparation_service.CLAIM_ACK_TIMEOUT_SECONDS", 0.05):
            result = await service.prepare_quiz(
                room.id,
                prep.request_id,
                room.owner_id,
                wait_for_completion=True,
            )
    finally:
        await service.shutdown()

    assert claimed.is_set()
    assert generator.generate_quiz_questions.await_count == 1
    assert result.is_ready


@pytest.mark.anyio
async def test_quiz_preparation_service_monotonic_outer_timeout_fails_closed() -> None:
    """The operation deadline is measured from admission, not reset per phase."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.mark_preparation_failed_cas.return_value = True
    prep_repo.get_by_id.return_value = replace(
        prep, status=PreparationStatus.FAILED, error_category="timeout"
    )
    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    async def overlong_generation(request: Any) -> tuple[GeneratedQuestionData, ...]:
        await asyncio.sleep(1)
        return questions

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(side_effect=overlong_generation)
    admission = Mock()
    admission.acquire.return_value = True
    admission.release = Mock()
    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
        admission=admission,
    )

    # Shrink only this test's deadline while exercising the real monotonic
    # asyncio.timeout_at path; the production value remains 165 seconds.
    with patch(
        "app.services.quiz_preparation_service.TOTAL_PIPELINE_DEADLINE_SECONDS",
        0.03,
    ):
        ack = await service.prepare_quiz(room.id, prep.request_id, room.owner_id)
        assert ack.is_generating
        background = next(iter(service._running))
        await asyncio.wait_for(asyncio.shield(background), timeout=1)

    # With the deliberately tiny budget, admission/preflight consumes the
    # operation before provider work can begin; the outer deadline fails
    # closed instead of granting a fresh per-phase budget.
    assert generator.generate_quiz_questions.await_count == 0
    prep_repo.mark_preparation_failed_cas.assert_called_once()
    assert admission.release.call_count == 1
    await service.shutdown()


@pytest.mark.anyio
async def test_quiz_preparation_service_shutdown_drains_cancelled_claim_thread() -> None:
    """Admission remains held until a cancelled DB worker actually returns."""
    room = _sample_room()
    prep = _sample_prep(room)
    claim_entered = Event()
    release_claim = Event()

    def blocking_claim(*args: Any, **kwargs: Any) -> tuple[QuizPreparation, bool]:
        claim_entered.set()
        assert release_claim.wait(1)
        return prep, True

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.side_effect = blocking_claim
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room
    admission = Mock()
    admission.acquire.return_value = True
    admission.release = Mock()
    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=Mock(),
        verifier=FakeQuizContentVerifier(),
        admission=admission,
    )

    caller = asyncio.create_task(
        service.prepare_quiz(
            room.id,
            prep.request_id,
            room.owner_id,
            wait_for_completion=True,
        )
    )
    await asyncio.to_thread(claim_entered.wait, 1)
    background = next(iter(service._running))
    background.cancel()
    await asyncio.sleep(0)
    background.cancel()
    await asyncio.sleep(0.01)
    assert not background.done()
    assert admission.release.call_count == 0
    release_claim.set()
    await asyncio.gather(background, return_exceptions=True)
    caller.cancel()
    await asyncio.gather(caller, return_exceptions=True)
    assert admission.release.call_count == 1


@pytest.mark.anyio
async def test_quiz_preparation_service_lost_final_cas_never_broadcasts_ready() -> None:
    """A lost final CAS is not a READY result or a terminal broadcast."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()
    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.store_generated_questions_cas.return_value = False
    prep_repo.get_by_id.return_value = prep
    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room
    broadcasts: list[tuple[Any, Any]] = []

    async def terminal_hook(room_id: Any, finished_prep: Any) -> None:
        broadcasts.append((room_id, finished_prep))

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)
    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
        on_terminal=terminal_hook,
    )

    with pytest.raises(PreparationConflictError):
        await service.prepare_quiz(
            room.id, prep.request_id, room.owner_id, wait_for_completion=True
        )
    assert broadcasts == []
    prep_repo.store_generated_questions_cas.assert_called_once()


@pytest.mark.anyio
async def test_quiz_preparation_service_no_fake_default_fails_unavailable() -> None:
    """Verify that QuizPreparationService with verifier=None fails unavailable without fail-open fake."""
    room = _sample_room()
    prep = _sample_prep(room)

    prep_repo = Mock(spec=QuizPreparationRepository)
    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    # verifier explicitly None
    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=Mock(),
        verifier=None,
    )

    with pytest.raises(AiGenerationUnavailableError, match="no verifier configured"):
        await service.prepare_quiz(room.id, prep.request_id, room.owner_id)


@pytest.mark.anyio
async def test_quiz_preparation_service_terminal_broadcast_hook_wired_for_http_and_ws() -> None:
    """Verify that terminal completion broadcast hook is notified when background pipeline completes."""
    room = _sample_room()
    prep = _sample_prep(room)
    questions = make_sample_consistent_quiz_set()

    prep_repo = Mock(spec=QuizPreparationRepository)
    prep_repo.get_by_room_and_request_id.return_value = None
    prep_repo.claim_or_create_preparation.return_value = (prep, True)
    prep_repo.get_recent_exclusion_prompts.return_value = ()
    prep_repo.store_generated_questions_cas.return_value = True

    ready_prep = replace(
        prep,
        status=PreparationStatus.READY,
        verification_revision=VERIFICATION_REVISION,
        verified_content_digest=compute_verified_content_digest(questions),
    )
    prep_repo.get_by_id.return_value = ready_prep

    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    generator = Mock()
    generator.generate_quiz_questions = AsyncMock(return_value=questions)

    terminal_broadcasts: list[tuple[Any, Any]] = []

    async def terminal_hook(room_id: Any, finished_prep: Any) -> None:
        terminal_broadcasts.append((room_id, finished_prep))

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=generator,
        verifier=FakeQuizContentVerifier(),
        on_terminal=terminal_hook,
    )

    # Wait for completion
    await service.prepare_quiz(room.id, prep.request_id, room.owner_id, wait_for_completion=True)

    assert len(terminal_broadcasts) == 1
    broadcast_room_id, broadcast_prep = terminal_broadcasts[0]
    assert broadcast_room_id == room.id
    assert broadcast_prep.is_ready
    assert broadcast_prep.verification_revision == VERIFICATION_REVISION


@pytest.mark.anyio
async def test_quiz_preparation_service_shutdown_drains_db_thread_and_holds_admission() -> None:
    """Verify shutdown awaits running database thread futures before completing."""
    room = _sample_room()
    prep = _sample_prep(room)

    prep_repo = Mock(spec=QuizPreparationRepository)
    room_repo = Mock(spec=RoomRepository)
    room_repo.get_by_id.return_value = room

    service = QuizPreparationService(
        preparation_repository=prep_repo,
        room_repository=room_repo,
        generator=Mock(),
        verifier=FakeQuizContentVerifier(),
    )

    # Simulate an active DB thread future tracked in service._active_db_futures
    loop = asyncio.get_running_loop()
    thread_done = False

    def slow_db_work() -> None:
        import time
        time.sleep(0.04)
        nonlocal thread_done
        thread_done = True

    fut = loop.run_in_executor(None, slow_db_work)
    service._active_db_futures.add(fut)

    # Calling shutdown must drain the DB future
    await service.shutdown()
    assert thread_done is True
    assert len(service._active_db_futures) == 0
