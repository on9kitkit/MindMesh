"""Fake-only service admission, transport sharing and cancellation regressions."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.domain.adaptive_quiz import PreparationStatus
from app.domain.errors import (
    AiGenerationUnavailableError,
    PreparationConflictError,
    PreparationFailedError,
    RoomClosedError,
)
from app.domain.quiz_preparation import QuizPreparation
from app.domain.room import Room
from app.generator.admission import GenerationAdmission, generation_admission
from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.protocol import GeneratorTimeoutError, GeneratorValidationError
from app.generator.verification import FakeQuizContentVerifier
from app.repositories.quiz_preparations import QuizPreparationRepository
from app.repositories.rooms import RoomRepository
from app.services.quiz_preparation_service import QuizPreparationService


class MemoryHarness:
    """Small thread-safe repository double; no real database/provider access."""

    def __init__(self, generator, admission=None):
        self.rooms = {}
        self.preparations = {}
        self.lock = Lock()
        self.claims = 0
        self.renewals = 0
        self.lose_cas = False
        self.repo = Mock(spec=QuizPreparationRepository)
        self.room_repo = Mock(spec=RoomRepository)
        self.room_repo.get_by_id.side_effect = self.rooms.get
        self.repo.get_by_room_and_request_id.side_effect = self.find
        self.repo.get_by_id.side_effect = self.preparations.get
        self.repo.claim_or_create_preparation.side_effect = self.claim
        self.repo.get_recent_exclusion_prompts.return_value = ()
        self.repo.renew_preparation_lease_cas.side_effect = self.renew
        self.repo.store_generated_questions_cas.side_effect = self.store
        self.repo.mark_preparation_failed_cas.side_effect = self.fail
        self.service = QuizPreparationService(self.repo, self.room_repo, generator,
            verifier=FakeQuizContentVerifier(),
            admission=admission if admission is not None else generation_admission)

    def room(self, host=None):
        room = Room(id=uuid4(), owner_id=host or uuid4(), name="Synthetic",
                    join_code="TEST42", maximum_members=8, quiz_mode="ADAPTIVE",
                    education_level="GCSE", quiz_subject="physics", quiz_topic="energy",
                    target_total_marks=7)
        self.rooms[room.id] = room
        return room

    def find(self, room_id, request_id):
        return next((p for p in self.preparations.values()
                     if p.room_id == room_id and p.request_id == request_id), None)

    def claim(self, room_id, request_id, model_id, lease_seconds):
        with self.lock:
            current = self.find(room_id, request_id)
            if current is not None:
                return current, False
            self.claims += 1
            now = datetime.now(timezone.utc)
            prep = QuizPreparation(id=uuid4(), room_id=room_id, request_id=request_id,
                status=PreparationStatus.GENERATING, state_version=1, generation_attempt=1,
                claim_token=uuid4(), lease_expires_at=now + timedelta(seconds=lease_seconds),
                model_id=model_id, error_category=None, created_at=now, updated_at=now,
                ready_at=None, consumed_at=None)
            self.preparations[prep.id] = prep
            return prep, True

    def renew(self, **kwargs):
        self.renewals += 1
        return True

    def store(self, preparation_id, **kwargs):
        prep = self.preparations[preparation_id]
        if self.lose_cas or self.rooms[prep.room_id].closed_at is not None:
            return False
        self.preparations[prep.id] = replace(prep, status=PreparationStatus.READY,
                                           state_version=2, claim_token=None)
        return True

    def fail(self, preparation_id, error_category, **kwargs):
        prep = self.preparations[preparation_id]
        self.preparations[prep.id] = replace(prep, status=PreparationStatus.FAILED,
            state_version=2, claim_token=None, error_category=error_category)
        return True

    async def prepare(self, room, request_id=None):
        # These admission tests assert the complete lifecycle.  The transport
        # early-ACK contract is covered by the verification-gate integration
        # tests; opting in here keeps the legacy helper's return semantics
        # explicit now that production defaults to an early durable ACK.
        return await self.service.prepare_quiz(
            room.id,
            request_id or uuid4(),
            room.owner_id,
            wait_for_completion=True,
        )


class BlockingGenerator:
    def __init__(self, *, resist_cancel=False):
        self.entered = asyncio.Queue()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls = 0
        self.resist_cancel = resist_cancel

    async def generate_quiz_questions(self, request):
        self.calls += 1
        self.entered.put_nowait(self.calls)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if not self.resist_cancel:
                raise
            await self.release.wait()
        return await FakeQuizContentGenerator().generate_quiz_questions(request)


def test_process_cap_is_four_and_host_cap_follows_close_recreate():
    async def scenario():
        generator = BlockingGenerator()
        harness = MemoryHarness(generator, GenerationAdmission())
        rooms = [harness.room() for _ in range(5)]
        tasks = [asyncio.create_task(harness.prepare(room)) for room in rooms[:4]]
        try:
            for _ in tasks:
                await asyncio.wait_for(generator.entered.get(), 2)
            with pytest.raises(AiGenerationUnavailableError):
                await harness.prepare(rooms[4])
            assert harness.claims == 4
            harness.rooms[rooms[0].id] = replace(rooms[0], closed_at=datetime.now(timezone.utc))
            recreated = harness.room(rooms[0].owner_id)
            with pytest.raises(AiGenerationUnavailableError):
                await harness.prepare(recreated)
            assert generator.calls == 4
        finally:
            generator.release.set()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert isinstance(outcomes[0], RoomClosedError)
        assert (await harness.prepare(recreated)).is_ready
        assert (await harness.prepare(rooms[4])).is_ready
    asyncio.run(scenario())


def test_same_request_observations_and_ready_do_not_admit_or_call_again():
    async def scenario():
        generator = BlockingGenerator()
        admission = GenerationAdmission(capacity=1)
        harness = MemoryHarness(generator, admission)
        room, request_id = harness.room(), uuid4()
        task = asyncio.create_task(harness.prepare(room, request_id))
        try:
            await asyncio.wait_for(generator.entered.get(), 2)
            assert (await harness.prepare(room, request_id)).is_generating
            assert harness.claims == generator.calls == 1
        finally:
            generator.release.set()
            await task
        other_host = uuid4()
        assert admission.acquire(other_host)
        try:
            assert (await harness.prepare(room, request_id)).is_ready
            assert generator.calls == 1
        finally:
            admission.release(other_host)
    asyncio.run(scenario())


@pytest.mark.parametrize("resist_cancel", [False, True])
def test_cancellation_releases_only_after_actual_local_provider_task_ends(resist_cancel):
    async def scenario():
        generator = BlockingGenerator(resist_cancel=resist_cancel)
        admission = GenerationAdmission()
        harness = MemoryHarness(generator, admission)
        room = harness.room()
        task = asyncio.create_task(harness.prepare(room))
        await asyncio.wait_for(generator.entered.get(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Caller cancellation is deliberately detached from the retained
        # provider pipeline; the provider must not be cancelled here.
        await asyncio.sleep(0)
        assert not generator.cancelled.is_set()
        running = tuple(harness.service._running)
        if resist_cancel:
            with pytest.raises(AiGenerationUnavailableError):
                await harness.prepare(harness.room(room.owner_id))
        generator.release.set()
        await asyncio.gather(*running, return_exceptions=True)
        assert admission.acquire(room.owner_id)
        admission.release(room.owner_id)
    asyncio.run(scenario())


def test_content_retry_holds_same_slot_and_failures_and_lost_cas_release_it():
    async def scenario():
        admission = GenerationAdmission()
        calls = 0
        room_holder = []

        class RetryGenerator:
            async def generate_quiz_questions(self, request):
                nonlocal calls
                calls += 1
                assert not admission.acquire(room_holder[0].owner_id)
                if calls == 1:
                    raise GeneratorValidationError("Synthetic invalid content")
                return await FakeQuizContentGenerator().generate_quiz_questions(request)

        harness = MemoryHarness(RetryGenerator(), admission)
        room = harness.room()
        room_holder.append(room)
        assert (await harness.prepare(room)).is_ready
        # One renewal covers the content-only retry and one bounds the paid
        # verification phase within the same operation budget.
        assert calls == 2 and harness.claims == 1 and harness.renewals == 2
        assert admission.acquire(room.owner_id)
        admission.release(room.owner_id)

        for generator, lost in [(FakeQuizContentGenerator(simulate_timeout=True), False),
                                (FakeQuizContentGenerator(), True)]:
            other = MemoryHarness(generator, admission)
            other.lose_cas = lost
            next_room = other.room(room.owner_id)
            if lost:
                with pytest.raises(PreparationConflictError):
                    await other.prepare(next_room)
            else:
                assert (await other.prepare(next_room)).is_failed
            assert admission.acquire(room.owner_id)
            admission.release(room.owner_id)
    asyncio.run(scenario())


def test_http_and_v2_handlers_share_default_process_admission():
    from app.api.rooms import prepare_quiz as http_prepare
    from app.api.websocket import _handle_command
    from app.realtime.protocol_v2 import PrepareQuizCommandV2
    from app.schemas.rooms import PrepareQuizRequest

    async def scenario():
        generator = BlockingGenerator()
        http = MemoryHarness(generator)
        websocket_harness = MemoryHarness(generator)
        room = http.room()
        second_room = websocket_harness.room(room.owner_id)
        request_id = uuid4()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        task = asyncio.create_task(http_prepare(request, room.id,
            PrepareQuizRequest(request_id=request_id), http.service, SimpleNamespace(id=room.owner_id)))
        try:
            await asyncio.wait_for(generator.entered.get(), 2)
            websocket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                quiz_preparation_service=websocket_harness.service)))
            connection = SimpleNamespace(room_id=second_room.id, user_id=room.owner_id,
                                         connection_id=uuid4())
            command = PrepareQuizCommandV2.model_validate_json(json.dumps({"protocol_version": 2,
                "type": "PREPARE_QUIZ", "payload": {"request_id": str(uuid4())}}))
            with pytest.raises(AiGenerationUnavailableError):
                await _handle_command(command, connection, Mock(), AsyncMock(), Mock(), Mock(), websocket)
            assert websocket_harness.claims == 0
            assert generator.calls == 1
        finally:
            result = await task
            generator.release.set()
            await asyncio.gather(*tuple(http.service._running), return_exceptions=True)
            assert result.status == "GENERATING"
    asyncio.run(scenario())


@pytest.mark.parametrize("failure_stage", ["claim", "exclusions", "store", "unavailable"])
def test_admission_releases_on_repository_errors_and_provider_unavailability(failure_stage):
    async def scenario():
        admission = GenerationAdmission()
        generator = FakeQuizContentGenerator(is_available=failure_stage != "unavailable")
        harness = MemoryHarness(generator, admission)
        room = harness.room()
        if failure_stage == "claim":
            harness.repo.claim_or_create_preparation.side_effect = RuntimeError("Synthetic failure")
        elif failure_stage == "exclusions":
            harness.repo.get_recent_exclusion_prompts.side_effect = RuntimeError("Synthetic failure")
        elif failure_stage == "store":
            harness.repo.store_generated_questions_cas.side_effect = RuntimeError("Synthetic failure")
        if failure_stage == "claim":
            with pytest.raises(PreparationFailedError):
                await harness.prepare(room)
        elif failure_stage == "unavailable":
            with pytest.raises(AiGenerationUnavailableError):
                await harness.prepare(room)
        else:
            result = await harness.prepare(room)
            assert result.is_failed
        assert admission.acquire(room.owner_id)
        admission.release(room.owner_id)
    asyncio.run(scenario())


@pytest.mark.parametrize("failure_stage, expected_messages", [
    ("hook", ["Preparation claimed hook failed"]),
    ("renewal", ["Generated questions failed validation on attempt 1",
                 "Generation lease renewal failed; aborting"]),
    ("adapter_validation", ["Generated questions failed validation on attempt 1",
                            "Generated questions failed validation on attempt 2"]),
    ("service_validation", ["Generated questions failed validation on attempt 1",
                            "Generated questions failed validation on attempt 2"]),
    ("unexpected", ["Unexpected error in quiz generation"]),
    ("provider", ["Generator failed at provider boundary"]),
])
def test_preparation_warnings_exclude_identifiers_content_and_exception_details(
    caplog, monkeypatch, failure_stage, expected_messages,
):
    canary_content = "SYNTHETIC_PRIVATE_CONTENT_CANARY"
    canary_key = "SYNTHETIC_PROVIDER_KEY_CANARY"
    sensitive_values = [canary_content, canary_key]

    async def scenario():
        class CanaryGenerator:
            async def generate_quiz_questions(self, request):
                assert canary_content in request.exclusion_prompts
                detail = " ".join(sensitive_values)
                if failure_stage in ("adapter_validation", "renewal"):
                    raise GeneratorValidationError(detail)
                if failure_stage == "unexpected":
                    raise RuntimeError(detail)
                if failure_stage == "provider":
                    raise GeneratorTimeoutError(detail)
                questions = await FakeQuizContentGenerator().generate_quiz_questions(request)
                if failure_stage == "service_validation":
                    return (replace(questions[0], prompt=canary_content, max_marks=0), *questions[1:])
                return questions

        harness = MemoryHarness(CanaryGenerator(), GenerationAdmission())
        room, request_id = harness.room(), uuid4()
        sensitive_values.extend(map(str, (room.id, room.owner_id, request_id)))
        harness.repo.get_recent_exclusion_prompts.return_value = (canary_content,)
        if failure_stage == "renewal":
            harness.repo.renew_preparation_lease_cas.side_effect = None
            harness.repo.renew_preparation_lease_cas.return_value = False

        async def claimed_hook(room_id, preparation):
            sensitive_values.extend(map(str, (preparation.id, preparation.claim_token)))
            if failure_stage == "hook":
                raise RuntimeError(" ".join(sensitive_values))

        harness.service.set_claimed_hook(claimed_hook)
        result = await harness.prepare(room, request_id)
        assert result.is_ready if failure_stage == "hook" else result.is_failed

    # Alembic's fileConfig may have disabled existing loggers while an earlier
    # migration test ran. Explicitly re-enable only this named service logger
    # for the canary, and let pytest restore the prior state afterwards.
    service_logger = logging.getLogger("app.services.quiz_preparation_service")
    monkeypatch.setattr(service_logger, "disabled", False)
    with caplog.at_level(logging.WARNING, logger="app.services.quiz_preparation_service"):
        asyncio.run(scenario())
    records = [record for record in caplog.records
               if record.name == "app.services.quiz_preparation_service"]
    assert [record.getMessage() for record in records] == expected_messages
    assert all(record.exc_info is None and record.stack_info is None for record in records)
    captured = caplog.text + repr([(record.msg, record.args) for record in records])
    assert all(value not in captured for value in sensitive_values)
