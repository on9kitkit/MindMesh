"""Solo service fake-provider tests for shared admission and marking."""

import asyncio
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import UUID, uuid4

import pytest

from app.generator.admission import GenerationAdmission
from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.verification.fixtures import FakeQuizContentVerifier
from app.grading.fake_grader import FakeWrittenAnswerGrader
from app.learning_companions.contracts import SoloAttemptStatus, SoloCreateRequest
from app.learning_companions.solo_domain import ClaimedSoloGrade, PreparationClaim, SoloAttemptState, SoloError
from app.learning_companions.solo_grading_admission import GradingAdmission
from app.learning_companions.solo_service import SoloService


OWNER = UUID("11111111-1111-4111-8111-111111111111")


def _request() -> SoloCreateRequest:
    return SoloCreateRequest(request_id=uuid4(), subject="physics", topic="forces", total_marks=5)


def _state(request: SoloCreateRequest, status: SoloAttemptStatus) -> SoloAttemptState:
    return SoloAttemptState(
        id=uuid4(), request_id=request.request_id, status=status,
        state_version=1, subject=request.subject, topic=request.topic,
        total_marks=request.total_marks, current_question_position=0,
        created_at=datetime.now(timezone.utc), started_at=None, terminal_at=None,
    )


class _MemoryPreparationRepository:
    def __init__(self) -> None:
        self.states: dict[UUID, SoloAttemptState] = {}
        self.proof = None
        self.failures: list[str] = []
        self.claim_calls = 0

    def get_by_request(self, owner_id: UUID, request_id: UUID):
        return self.states.get(request_id)

    def claim_or_create(self, owner_id: UUID, request: SoloCreateRequest, *, model_id: str, lease_seconds: int):
        assert owner_id == OWNER and model_id == "gpt-6-luna" and lease_seconds == 75
        self.claim_calls += 1
        state = _state(request, SoloAttemptStatus.PREPARING)
        self.states[request.request_id] = state
        return PreparationClaim(state, uuid4(), uuid4(), 1, datetime.now(timezone.utc) + timedelta(seconds=75), True)

    def get_recent_exclusion_prompts(self, owner_id: UUID, subject: str, topic: str):
        assert (owner_id, subject, topic) == (OWNER, "physics", "forces")
        return ()

    def renew_preparation_lease(self, *_args, **_kwargs):
        return True

    def store_verified_set_cas(self, owner_id, attempt_id, preparation_id, claim_token, generation_attempt, verified, deadline_at):
        assert owner_id == OWNER and generation_attempt == 1
        self.proof = verified
        old = next(state for state in self.states.values() if state.id == attempt_id)
        self.states[old.request_id] = SoloAttemptState(
            id=old.id, request_id=old.request_id, status=SoloAttemptStatus.READY,
            state_version=old.state_version + 1, subject=old.subject, topic=old.topic,
            total_marks=old.total_marks, current_question_position=0,
            created_at=old.created_at, started_at=None, terminal_at=None,
        )
        return True

    def fail_preparation_cas(self, owner_id, attempt_id, preparation_id, claim_token, error_category):
        self.failures.append(error_category)
        return True

    def get_state(self, owner_id: UUID, attempt_id: UUID):
        assert owner_id == OWNER
        return next(state for state in self.states.values() if state.id == attempt_id)


def test_explicit_create_uses_verified_proof_and_idempotent_saved_state() -> None:
    async def run() -> None:
        repository = _MemoryPreparationRepository()
        generator = FakeQuizContentGenerator()
        verifier = FakeQuizContentVerifier()
        service = SoloService(
            repository, generator, verifier, FakeWrittenAnswerGrader(),
            admission=GenerationAdmission(),
        )
        request = _request()
        ready = await service.create(OWNER, request, wait_for_completion=True)
        assert ready.status is SoloAttemptStatus.READY
        assert repository.proof is not None
        assert generator.call_count == 1 and len(verifier.calls) == 1
        assert repository.claim_calls == 1
        assert (await service.create(OWNER, request)).id == ready.id
        assert generator.call_count == 1
        await service.shutdown()

    asyncio.run(run())


def test_same_generation_admission_blocks_second_mode_owner_work() -> None:
    class _BlockingGenerator(FakeQuizContentGenerator):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def generate_quiz_questions(self, request):
            self.entered.set()
            await self.release.wait()
            return await super().generate_quiz_questions(request)

    async def run() -> None:
        admission = GenerationAdmission(capacity=1)
        generator = _BlockingGenerator()
        repository = _MemoryPreparationRepository()
        service = SoloService(repository, generator, FakeQuizContentVerifier(), FakeWrittenAnswerGrader(), admission=admission)
        first = await service.create(OWNER, _request())
        await asyncio.wait_for(generator.entered.wait(), 2)
        with pytest.raises(SoloError) as error:
            await service.create(uuid4(), _request())
        assert error.value.code == "solo_generation_unavailable"
        generator.release.set()
        await service.shutdown()
        assert first.status is SoloAttemptStatus.PREPARING

    asyncio.run(run())


def test_concurrent_same_request_id_with_changed_marks_conflicts_before_claim_ack() -> None:
    class _BlockedClaimRepository(_MemoryPreparationRepository):
        def __init__(self) -> None:
            super().__init__()
            self.claim_started = Event()
            self.release_claim = Event()
            self.second_lookup = Event()
            self.lookup_count = 0

        def get_by_request(self, owner_id: UUID, request_id: UUID):
            self.lookup_count += 1
            if self.lookup_count == 2:
                self.second_lookup.set()
            return super().get_by_request(owner_id, request_id)

        def claim_or_create(self, owner_id, request, *, model_id, lease_seconds):
            self.claim_started.set()
            if not self.release_claim.wait(2):
                raise AssertionError("Blocked claim was not released")
            return super().claim_or_create(
                owner_id, request, model_id=model_id, lease_seconds=lease_seconds,
            )

    async def run() -> None:
        repository = _BlockedClaimRepository()
        service = SoloService(
            repository, FakeQuizContentGenerator(), FakeQuizContentVerifier(),
            FakeWrittenAnswerGrader(), admission=GenerationAdmission(),
        )
        first_request = _request()
        changed_request = SoloCreateRequest(
            request_id=first_request.request_id, subject="physics", topic="forces", total_marks=6,
        )
        first = asyncio.create_task(service.create(OWNER, first_request))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(repository.claim_started.wait, 2), 3)
            second = asyncio.create_task(service.create(OWNER, changed_request))
            assert await asyncio.wait_for(asyncio.to_thread(repository.second_lookup.wait, 2), 3)
            await asyncio.sleep(0)
            with pytest.raises(SoloError) as error:
                await asyncio.wait_for(second, 1)
            assert error.value.code == "solo_conflict"
        finally:
            repository.release_claim.set()
            await first
            await service.shutdown()

    asyncio.run(run())


def test_admission_refusal_reread_rejects_mismatched_existing_request() -> None:
    class _AppearingAttemptRepository(_MemoryPreparationRepository):
        def __init__(self, existing: SoloAttemptState) -> None:
            super().__init__()
            self.existing = existing
            self.lookups = 0

        def get_by_request(self, owner_id: UUID, request_id: UUID):
            self.lookups += 1
            return None if self.lookups == 1 else self.existing

    async def run() -> None:
        request = _request()
        existing_request = SoloCreateRequest(
            request_id=request.request_id, subject="physics", topic="forces", total_marks=6,
        )
        repository = _AppearingAttemptRepository(_state(existing_request, SoloAttemptStatus.PREPARING))
        admission = GenerationAdmission(capacity=1)
        assert admission.acquire(OWNER)
        service = SoloService(
            repository, FakeQuizContentGenerator(), FakeQuizContentVerifier(),
            FakeWrittenAnswerGrader(), admission=admission,
        )
        with pytest.raises(SoloError) as error:
            await service.create(OWNER, request)
        assert error.value.code == "solo_conflict"
        assert repository.lookups == 2 and repository.claim_calls == 0
        admission.release(OWNER)
        await service.shutdown()

    asyncio.run(run())


class _GradeRepository:
    def __init__(self, claim: ClaimedSoloGrade) -> None:
        self.claim = claim
        self.claim_calls = 0
        self.stored: list[dict] = []
        self.failed: list[str] = []

    def claim_due_ai(self, *, limit: int, lease_seconds: int):
        self.claim_calls += 1
        assert limit == 4 and lease_seconds == 30
        return (self.claim,)

    def finish_ai_cas(self, claim: ClaimedSoloGrade, **kwargs):
        assert claim == self.claim
        self.stored.append(kwargs)
        return True

    def fail_ai_cas(self, claim: ClaimedSoloGrade, error_category: str):
        assert claim == self.claim
        self.failed.append(error_category)
        return True


def _ai_claim() -> ClaimedSoloGrade:
    return ClaimedSoloGrade(
        attempt_id=uuid4(), answer_id=uuid4(), question_id=uuid4(),
        claim_token=uuid4(), attempt_count=1, attempt_cycle=1,
        answer_text="The force is 10N due to acceleration.", prompt="Explain the force.",
        original_extract=None, max_marks=5,
        grading_rubric={"criteria": [
            {"id": "principle", "marks": 3, "marking_point": "Principle", "accepted_meaning": "force",
             "spelling_sensitive": False, "explanation": "State force."},
            {"id": "application", "marks": 2, "marking_point": "Application", "accepted_meaning": "acceleration",
             "spelling_sensitive": False, "explanation": "Apply acceleration."},
        ]},
    )


def test_long_written_uses_shared_grader_and_server_weighted_result() -> None:
    async def run() -> None:
        claim = _ai_claim()
        repo = _GradeRepository(claim)
        grader = FakeWrittenAnswerGrader(always_award_all=True)
        service = SoloService(repo, FakeQuizContentGenerator(), FakeQuizContentVerifier(), grader)
        assert await service.process_due_ai() == 1
        assert grader.call_count == 1
        assert repo.stored[0]["earned_marks"] == 5
        assert set(repo.stored[0]["awarded_criterion_ids"]) == {"principle", "application"}
        assert not repo.failed
        assert not hasattr(grader.last_request, "user_id")
        await service.shutdown()

    asyncio.run(run())


def test_shared_grading_slots_prevent_solo_claim_behind_room_and_cover_cas() -> None:
    class _BlockingCASRepository(_GradeRepository):
        def __init__(self, claim: ClaimedSoloGrade) -> None:
            super().__init__(claim)
            self.cas_started = Event()
            self.release_cas = Event()

        def finish_ai_cas(self, claim: ClaimedSoloGrade, **kwargs):
            self.cas_started.set()
            if not self.release_cas.wait(2):
                raise AssertionError("Solo grading CAS was not released")
            return super().finish_ai_cas(claim, **kwargs)

    async def run() -> None:
        permits = GradingAdmission(capacity=4)
        repo = _BlockingCASRepository(_ai_claim())
        service = SoloService(
            repo, FakeQuizContentGenerator(), FakeQuizContentVerifier(),
            FakeWrittenAnswerGrader(always_award_all=True), grading_permits=permits,
        )
        # Four near-deadline room calls already own all shared slots. Solo
        # must not start an answer lease while waiting for provider capacity.
        room_slots = permits.reserve_up_to(4)
        assert room_slots == 4
        assert await service.process_due_ai() == 0
        assert repo.claim_calls == 0 and permits.available == 0
        permits.release(room_slots)

        task = asyncio.create_task(service.process_due_ai())
        try:
            assert await asyncio.wait_for(asyncio.to_thread(repo.cas_started.wait, 2), 3)
            assert repo.claim_calls == 1 and permits.available == 3
            # A room batch can now claim only the three other slots. Solo's
            # permit stays held until the durable grading CAS completes.
            other_room_slots = permits.reserve_up_to(4)
            assert other_room_slots == 3
            permits.release(other_room_slots)
        finally:
            repo.release_cas.set()
        assert await task == 1
        assert permits.available == 4
        assert len(repo.stored) == 1 and not repo.failed
        await service.shutdown()

    asyncio.run(run())


def test_long_written_unavailable_stays_pending_without_invented_marks() -> None:
    async def run() -> None:
        repo = _GradeRepository(_ai_claim())
        grader = FakeWrittenAnswerGrader(is_available=False)
        service = SoloService(repo, FakeQuizContentGenerator(), FakeQuizContentVerifier(), grader)
        assert await service.process_due_ai() == 1
        assert repo.failed == ["ai_grading_unavailable"]
        assert not repo.stored
        await service.shutdown()

    asyncio.run(run())
