"""Solo generation, grading and owner actions without room or timer semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

from app.domain.adaptive_quiz import WrittenRubric
from app.generator.admission import GenerationAdmission, generation_admission
from app.generator.protocol import (
    GENERATION_LEASE_SECONDS,
    GenerationRequest,
    MODEL_ID_GPT_6_LUNA,
    QuizContentGenerator,
)
from app.generator.verified_runner import VerifiedGenerationFailure, generate_verified_quiz
from app.generator.verification.protocol import TOTAL_PIPELINE_DEADLINE_SECONDS, QuizContentVerifier
from app.grading.coordinator import _build_enriched_feedback, _validate_grader_result
from app.grading.protocol import (
    MAX_CONCURRENT_GRADING_CALLS,
    MAX_GRADING_LEASE_SECONDS,
    GradingError,
    GradingRequest,
    WrittenAnswerGrader,
)
from app.learning_companions.contracts import (
    LockedSelfCheck,
    SoloCreateRequest,
)
from app.learning_companions.solo_domain import (
    CONFLICT,
    GENERATION_UNAVAILABLE,
    ClaimedSoloGrade,
    PreparationClaim,
    SoloAnswerState,
    SoloAttemptState,
    SoloReview,
)
from app.learning_companions.solo_grading_admission import GradingAdmission, grading_admission
from app.learning_companions.solo_repository import PostgresSoloRepository

logger = logging.getLogger(__name__)
CLAIM_ACK_TIMEOUT_SECONDS = 10.0
RoomExclusions = Callable[[UUID, str, str], tuple[str, ...]]


class SoloService:
    """Owns solo provider work; the repository remains the state authority."""

    def __init__(
        self,
        repository: PostgresSoloRepository,
        generator: QuizContentGenerator,
        verifier: QuizContentVerifier,
        grader: WrittenAnswerGrader,
        *,
        admission: GenerationAdmission = generation_admission,
        grading_permits: GradingAdmission = grading_admission,
        room_exclusions: RoomExclusions | None = None,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._verifier = verifier
        self._grader = grader
        self._admission = admission
        self._grading_permits = grading_permits
        self._room_exclusions = room_exclusions
        self._running: set[asyncio.Task[Any]] = set()
        self._active_db_futures: set[asyncio.Future[Any]] = set()
        self._pending_claims: dict[
            tuple[UUID, UUID], tuple[tuple[str, str, int], asyncio.Future[PreparationClaim]]
        ] = {}
        self._grading_wakeup = asyncio.Event()
        self._grading_running = False

    async def _run_in_thread(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, lambda: function(*args, **kwargs))
        self._active_db_futures.add(future)
        future.add_done_callback(self._active_db_futures.discard)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError as cancellation:
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise cancellation
        finally:
            if future.done() and not future.cancelled():
                future.exception()

    async def create(
        self, owner_id: UUID, request: SoloCreateRequest, *, wait_for_completion: bool = False
    ) -> SoloAttemptState:
        """Explicit confirmation creates one durable claim; opening Home does not."""
        requested = (request.subject, request.topic, request.total_marks)
        existing = await self._run_in_thread(
            self._repository.get_by_request, owner_id, request.request_id
        )
        if existing is not None:
            if (existing.subject, existing.topic, existing.total_marks) != requested:
                raise CONFLICT
            if existing.status != "PREPARING":
                return existing
        key = (owner_id, request.request_id)
        pending = self._pending_claims.get(key)
        if pending is not None:
            prior_request, pending_ack = pending
            if prior_request != requested:
                raise CONFLICT
            try:
                claim = await asyncio.wait_for(asyncio.shield(pending_ack), CLAIM_ACK_TIMEOUT_SECONDS)
            except (TimeoutError, asyncio.TimeoutError):
                raise GENERATION_UNAVAILABLE from None
            if (claim.attempt.subject, claim.attempt.topic, claim.attempt.total_marks) != requested:
                raise CONFLICT
            return claim.attempt
        if not self._admission.acquire(owner_id):
            existing = await self._run_in_thread(
                self._repository.get_by_request, owner_id, request.request_id
            )
            if existing is not None:
                if (existing.subject, existing.topic, existing.total_marks) != requested:
                    raise CONFLICT
                return existing
            raise GENERATION_UNAVAILABLE

        loop = asyncio.get_running_loop()
        claim_ack_deadline = loop.time() + CLAIM_ACK_TIMEOUT_SECONDS
        deadline_monotonic = loop.time() + TOTAL_PIPELINE_DEADLINE_SECONDS
        deadline_at = datetime.now(timezone.utc) + timedelta(seconds=TOTAL_PIPELINE_DEADLINE_SECONDS)
        ack: asyncio.Future[PreparationClaim] = loop.create_future()
        ack.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        abandoned = asyncio.Event()
        self._pending_claims[key] = (requested, ack)
        task = asyncio.create_task(self._prepare_admitted(
            owner_id, request, ack, abandoned, claim_ack_deadline,
            deadline_monotonic, deadline_at,
        ))
        self._running.add(task)

        def finished(completed: asyncio.Task[Any]) -> None:
            self._running.discard(completed)
            current_pending = self._pending_claims.get(key)
            if current_pending is not None and current_pending[1] is ack:
                self._pending_claims.pop(key, None)
            self._admission.release(owner_id)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        try:
            claim = await asyncio.wait_for(
                asyncio.shield(ack), max(0.0, claim_ack_deadline - loop.time())
            )
        except (TimeoutError, asyncio.TimeoutError):
            abandoned.set()
            raise GENERATION_UNAVAILABLE from None
        except asyncio.CancelledError:
            if not ack.done():
                abandoned.set()
            raise
        if wait_for_completion:
            await asyncio.shield(task)
            return await self._run_in_thread(self._repository.get_state, owner_id, claim.attempt.id)
        return claim.attempt

    async def _prepare_admitted(
        self, owner_id: UUID, request: SoloCreateRequest,
        ack: asyncio.Future[PreparationClaim], abandoned: asyncio.Event,
        claim_ack_deadline: float, deadline_monotonic: float, deadline_at: datetime,
    ) -> None:
        claim: PreparationClaim | None = None
        try:
            async with asyncio.timeout_at(deadline_monotonic):
                claim = await self._run_in_thread(
                    self._repository.claim_or_create, owner_id, request,
                    model_id=MODEL_ID_GPT_6_LUNA, lease_seconds=GENERATION_LEASE_SECONDS,
                )
                acknowledged_on_time = asyncio.get_running_loop().time() < claim_ack_deadline
                if not ack.done():
                    ack.set_result(claim)
                if not claim.claimed or claim.claim_token is None:
                    return
                if abandoned.is_set() or not acknowledged_on_time:
                    await self._run_in_thread(
                        self._repository.fail_preparation_cas,
                        owner_id, claim.attempt.id, claim.preparation_id,
                        claim.claim_token, "claim_ack_timeout",
                    )
                    return
                exclusions = await self._run_in_thread(
                    self._repository.get_recent_exclusion_prompts,
                    owner_id, request.subject, request.topic,
                )
                if self._room_exclusions is not None:
                    room_exclusions = await self._run_in_thread(
                        self._room_exclusions, owner_id, request.subject, request.topic,
                    )
                    exclusions = tuple(dict.fromkeys((*exclusions, *room_exclusions)))[:50]
                generation_request = GenerationRequest(
                    education_level="GCSE", quiz_subject=request.subject,
                    quiz_topic=request.topic, target_total_marks=request.total_marks,
                    exclusion_prompts=exclusions,
                )

                async def renew(seconds: int) -> bool:
                    return await self._run_in_thread(
                        self._repository.renew_preparation_lease,
                        owner_id, claim.attempt.id, claim.preparation_id,
                        claim.claim_token, lease_seconds=seconds,
                    )

                try:
                    verified = await generate_verified_quiz(
                        request=generation_request, generator=self._generator,
                        verifier=self._verifier, deadline_at=deadline_at,
                        deadline_monotonic=deadline_monotonic, renew_lease=renew,
                    )
                except VerifiedGenerationFailure as failure:
                    await self._run_in_thread(
                        self._repository.fail_preparation_cas,
                        owner_id, claim.attempt.id, claim.preparation_id,
                        claim.claim_token, failure.category,
                    )
                    return
                await self._run_in_thread(
                    self._repository.store_verified_set_cas,
                    owner_id, claim.attempt.id, claim.preparation_id,
                    claim.claim_token, claim.generation_attempt, verified, deadline_at,
                )
        except (TimeoutError, asyncio.TimeoutError):
            if not ack.done():
                ack.set_exception(GENERATION_UNAVAILABLE)
            if claim is not None and claim.claimed and claim.claim_token is not None:
                await self._run_in_thread(
                    self._repository.fail_preparation_cas,
                    owner_id, claim.attempt.id, claim.preparation_id,
                    claim.claim_token, "timeout",
                )
        except Exception as error:
            if not ack.done():
                ack.set_exception(error if hasattr(error, "code") else GENERATION_UNAVAILABLE)
            if claim is not None and claim.claimed and claim.claim_token is not None:
                await self._run_in_thread(
                    self._repository.fail_preparation_cas,
                    owner_id, claim.attempt.id, claim.preparation_id,
                    claim.claim_token, "internal_error",
                )
            logger.warning("Solo preparation failed with category internal_error")

    def get_active(self, owner_id: UUID) -> SoloAttemptState | None:
        return self._repository.get_active(owner_id)

    def get_state(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        return self._repository.get_state(owner_id, attempt_id)

    def start(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        return self._repository.start(owner_id, attempt_id)

    def submit_answer(
        self, owner_id: UUID, attempt_id: UUID, question_id: UUID,
        selected_option_id: str | None, answer_text: str | None,
    ) -> SoloAnswerState:
        return self._repository.submit_answer(
            owner_id, attempt_id, question_id, selected_option_id, answer_text
        )

    def get_self_check(self, owner_id: UUID, attempt_id: UUID, question_id: UUID) -> LockedSelfCheck:
        return self._repository.get_self_check(owner_id, attempt_id, question_id)

    def finalize_self_check(
        self, owner_id: UUID, attempt_id: UUID, question_id: UUID,
        selected_criterion_ids: tuple[str, ...],
    ) -> SoloAnswerState:
        return self._repository.finalize_self_check(
            owner_id, attempt_id, question_id, selected_criterion_ids
        )

    def abandon(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        return self._repository.abandon(owner_id, attempt_id)

    def get_review(self, owner_id: UUID, attempt_id: UUID) -> SoloReview:
        return self._repository.get_review(owner_id, attempt_id)

    async def schedule_grading(self) -> None:
        self._grading_wakeup.set()

    async def retry_marking(self, owner_id: UUID, attempt_id: UUID) -> int:
        count = await self._run_in_thread(self._repository.retry_ai, owner_id, attempt_id)
        if count:
            self._grading_wakeup.set()
        return count

    async def process_due_ai(self) -> int:
        reserved = self._grading_permits.reserve_up_to(MAX_CONCURRENT_GRADING_CALLS)
        if reserved == 0:
            return 0
        held = reserved
        try:
            claims = await self._run_in_thread(
                self._repository.claim_due_ai,
                limit=reserved,
                lease_seconds=MAX_GRADING_LEASE_SECONDS,
            )
            if len(claims) > reserved:
                raise RuntimeError("Solo repository claimed more grading work than reserved slots.")
            unused = reserved - len(claims)
            self._grading_permits.release(unused)
            held -= unused
            if not claims:
                return 0
            await asyncio.gather(*(self._grade_one(claim) for claim in claims), return_exceptions=True)
            return len(claims)
        finally:
            self._grading_permits.release(held)

    async def _grade_one(self, claim: ClaimedSoloGrade) -> None:
        try:
            rubric = WrittenRubric.from_dict(claim.grading_rubric)
            if not rubric.criteria:
                raise ValueError("Empty stored written rubric.")
            request = GradingRequest(
                question_prompt=claim.prompt,
                original_extract=claim.original_extract,
                student_answer=claim.answer_text,
                max_marks=claim.max_marks,
                rubric=rubric,
            )
            result = await self._grader.grade_written_answer(request)
            _validate_grader_result(rubric, claim.max_marks, result, claim.answer_text)
        except GradingError as error:
            await self._run_in_thread(
                self._repository.fail_ai_cas, claim, error.category,
            )
            return
        except Exception:
            logger.warning("Solo grading failed with category internal_error")
            await self._run_in_thread(
                self._repository.fail_ai_cas, claim, "internal_error",
            )
            return
        weights = {criterion.id: criterion.marks for criterion in rubric.criteria}
        marks = sum(weights[criterion_id] for criterion_id in result.awarded_criterion_ids)
        await self._run_in_thread(
            self._repository.finish_ai_cas, claim,
            earned_marks=marks,
            awarded_criterion_ids=result.awarded_criterion_ids,
            feedback=_build_enriched_feedback(rubric, result.awarded_criterion_ids, result.feedback),
        )

    async def startup_recovery(self) -> None:
        await self._run_in_thread(self._repository.fail_expired_preparations)
        await self._run_in_thread(self._repository.reset_expired_ai)
        await self.process_due_ai()

    async def run_grading_loop(self) -> None:
        self._grading_running = True
        try:
            await self.startup_recovery()
            while self._grading_running:
                try:
                    await asyncio.wait_for(self._grading_wakeup.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                self._grading_wakeup.clear()
                await self._run_in_thread(self._repository.fail_expired_preparations)
                await self._run_in_thread(self._repository.reset_expired_ai)
                await self.process_due_ai()
        finally:
            self._grading_running = False

    async def shutdown(self) -> None:
        self._grading_running = False
        self._grading_wakeup.set()
        tasks = tuple(self._running)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._active_db_futures:
            await asyncio.gather(*tuple(self._active_db_futures), return_exceptions=True)
