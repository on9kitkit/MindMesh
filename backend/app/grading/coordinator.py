"""Asynchronous coordinator scheduling and processing written answer grading outside DB locks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import logging
from typing import Any
from uuid import UUID

from app.domain.adaptive_quiz import UNSAFE_CONTROL_RE, WrittenRubric
from app.domain.quiz import QuizSession
from app.grading.openai_grader import check_spelling_sensitive_criterion
from app.grading.protocol import (
    MAX_CONCURRENT_GRADING_CALLS,
    MAX_GRADING_LEASE_SECONDS,
    GradingError,
    GradingMalformedError,
    GradingRequest,
    GradingResult,
    WrittenAnswerGrader,
)
from app.learning_companions.solo_grading_admission import GradingAdmission
from app.repositories.quiz_sessions import ClaimedSubmission
from app.services.sessions import SessionService

logger = logging.getLogger(__name__)

TransitionPublisher = Callable[[UUID, QuizSession | None, QuizSession], Coroutine[Any, Any, bool]]


class GradingCoordinator:
    """Supervise due written submission processing, leases, retries, and state transitions."""

    def __init__(
        self,
        session_service: SessionService,
        grader: WrittenAnswerGrader,
        publish_transition: TransitionPublisher | None = None,
        max_concurrent: int = MAX_CONCURRENT_GRADING_CALLS,
        grading_permits: GradingAdmission | None = None,
    ) -> None:
        self._session_service = session_service
        self._grader = grader
        self._publish_transition = publish_transition
        self._max_concurrent = max(1, max_concurrent)
        self._grading_permits = grading_permits or GradingAdmission(self._max_concurrent)
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._is_running = False
        self._wake_event = asyncio.Event()

    async def schedule_grading(self) -> None:
        """Advisory wake-up signal that due submissions may be ready."""
        self._wake_event.set()

    async def process_due_submissions(self) -> int:
        """Claim and evaluate one batch of due written submissions.

        At most max_concurrent rows are claimed per batch so no claimed
        lease waits behind the semaphore longer than its provider call:
        with a 20s provider deadline inside a 30s lease, a pre-claim queue
        would let leases expire before their call starts.
        """
        reserved = self._grading_permits.reserve_up_to(self._max_concurrent)
        if reserved == 0:
            return 0
        held = reserved
        try:
            claimed = await asyncio.to_thread(
                self._session_service.claim_due_written_submissions,
                limit=reserved,
                lease_seconds=MAX_GRADING_LEASE_SECONDS,
            )
            if len(claimed) > reserved:
                raise RuntimeError("Room repository claimed more grading work than reserved slots.")
            unused = reserved - len(claimed)
            self._grading_permits.release(unused)
            held -= unused
            if not claimed:
                return 0

            tasks = [self._evaluate_and_commit_submission(sub) for sub in claimed]
            await asyncio.gather(*tasks, return_exceptions=True)
            return len(claimed)
        finally:
            self._grading_permits.release(held)

    async def _evaluate_and_commit_submission(self, sub: ClaimedSubmission) -> None:
        async with self._semaphore:
            try:
                rubric = WrittenRubric.from_dict(sub.grading_rubric)
            except Exception:
                rubric = None
            if rubric is None or not rubric.criteria:
                # Malformed stored rubric: never strand IN_PROGRESS forever;
                # route through the bounded retry/UNAVAILABLE path instead.
                logger.warning(
                    "Malformed stored rubric; marking grading attempt %d retryable",
                    sub.attempt_count,
                )
                await asyncio.to_thread(
                    self._session_service.mark_written_grading_retryable_or_unavailable,
                    submission_id=sub.submission_id,
                    claim_token=sub.claim_token,
                    error_category="malformed_rubric",
                    backoff_seconds=5,
                )
                await self._reconcile_and_publish(sub)
                return
            request = GradingRequest(
                question_prompt=sub.question_prompt,
                original_extract=sub.original_extract,
                student_answer=sub.answer_text,
                max_marks=sub.max_marks,
                rubric=rubric,
            )

            result: GradingResult | None = None
            error_category = "grading_failed"

            try:
                result = await self._grader.grade_written_answer(request)
                if result is not None:
                    _validate_grader_result(rubric, sub.max_marks, result, sub.answer_text)
            except GradingError as exc:
                result = None
                error_category = exc.category
                logger.warning(
                    "Written answer grading failed with category %s on attempt %d",
                    exc.category,
                    sub.attempt_count,
                )
            except Exception:
                result = None
                error_category = "internal_error"
                logger.warning(
                    "Unexpected provider-boundary failure on attempt %d",
                    sub.attempt_count,
                )

            if result is not None:
                # Compute marks on the server from validated awarded criteria
                valid_criteria_map = {c.id: c.marks for c in rubric.criteria}
                earned_marks = sum(
                    valid_criteria_map.get(c_id, 0)
                    for c_id in result.awarded_criterion_ids
                )
                is_correct = (earned_marks == sub.max_marks)
                points = 100 if is_correct else 0

                stored = await asyncio.to_thread(
                    self._session_service.store_written_grading_result_cas,
                    submission_id=sub.submission_id,
                    claim_token=sub.claim_token,
                    earned_marks=earned_marks,
                    is_correct=is_correct,
                    points=points,
                    awarded_criterion_ids=list(result.awarded_criterion_ids),
                    feedback=_build_enriched_feedback(
                        rubric, result.awarded_criterion_ids, result.feedback
                    ),
                )
                if not stored:
                    logger.info(
                        "Discarded late grading result after CAS mismatch on attempt %d",
                        sub.attempt_count,
                    )
            else:
                # Failure: retryable or unavailable
                await asyncio.to_thread(
                    self._session_service.mark_written_grading_retryable_or_unavailable,
                    submission_id=sub.submission_id,
                    claim_token=sub.claim_token,
                    error_category=error_category,
                    backoff_seconds=5,
                )

            # Reconcile session after grade/failure
            await self._reconcile_and_publish(sub)

    async def _reconcile_and_publish(self, sub: ClaimedSubmission) -> None:
        previous = await asyncio.to_thread(self._session_service.get_session, sub.session_id)
        reconciled = await asyncio.to_thread(
            self._session_service.reconcile_session,
            session_id=sub.session_id,
        )
        if (
            reconciled is not None
            and self._publish_transition is not None
            # Grading mutations advance the session version even when the
            # phase stays GRADING; publish from the pre-claim baseline so a
            # same-version `previous` cannot suppress the snapshot.
            and reconciled.state_version != sub.session_state_version
        ):
            await self._publish_transition(reconciled.room_id, previous, reconciled)

    async def _reset_expired_and_reconcile(self) -> None:
        """Periodically recover crashed claims and publish honest grading state."""
        affected = await asyncio.to_thread(
            self._session_service.reset_expired_grading_claims
        )
        for session_id in affected:
            previous = await asyncio.to_thread(
                self._session_service.get_session, session_id
            )
            if previous is None:
                continue
            baseline_version = previous.state_version - 1
            reconciled = await asyncio.to_thread(
                self._session_service.reconcile_session,
                session_id=session_id,
            )
            if (
                reconciled is not None
                and self._publish_transition is not None
                and reconciled.state_version != baseline_version
            ):
                await self._publish_transition(reconciled.room_id, previous, reconciled)

    async def startup_recovery(self) -> None:
        """Reset expired claims and resume durable PENDING/RETRYABLE work."""
        logger.info("GradingCoordinator running startup recovery")
        # A crash may leave IN_PROGRESS rows with dead leases; recover them
        # first so the batch below resumes accepted answers.
        await self._reset_expired_and_reconcile()
        # Process any currently due submissions
        await self.process_due_submissions()

    async def run_loop(self) -> None:
        """Long-running background task listening for grading work."""
        self._is_running = True
        while self._is_running:
            try:
                # Periodic crash recovery: claims whose worker died without
                # releasing the lease must not wait for a process restart.
                await self._reset_expired_and_reconcile()
                processed = await self.process_due_submissions()
                if processed > 0:
                    # Check for more immediately
                    continue
                # Wait for next wake-up or poll interval
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=2.0)
                    self._wake_event.clear()
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in GradingCoordinator run loop")
                await asyncio.sleep(1.0)
        self._is_running = False

    def stop(self) -> None:
        self._is_running = False
        self._wake_event.set()


def _validate_grader_result(
    rubric: WrittenRubric,
    max_marks: int,
    result: GradingResult,
    student_answer: str,
) -> None:
    """Revalidate an untrusted grader result against the immutable rubric.

    Any grader implementation (including fakes and alternates) must produce
    a fully valid unique subset: invalid feedback shape, unknown/duplicate
    IDs, spelling-gate violations, rubric-total drift, or out-of-range
    earned marks are malformed and enter the bounded retry/UNAVAILABLE path
    instead of attempting final storage.
    """
    feedback = result.feedback
    if not isinstance(feedback, dict):
        raise GradingMalformedError("Grading feedback was not an object.")
    # Exact protocol boundary: only {'summary'} is accepted; extra keys
    # are rejected rather than silently dropped.
    if set(feedback.keys()) != {"summary"}:
        raise GradingMalformedError("Grading feedback has unexpected keys.")
    summary = feedback.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise GradingMalformedError("Grading feedback summary was blank.")
    if len(summary.strip()) > 1000:
        raise GradingMalformedError("Grading feedback summary exceeds 1000 characters.")
    if UNSAFE_CONTROL_RE.search(summary):
        raise GradingMalformedError("Grading feedback contains unsafe controls.")
    awarded = result.awarded_criterion_ids
    if not isinstance(awarded, (tuple, list)):
        raise GradingMalformedError("Grading awarded IDs were not a list.")
    criteria_map = {c.id: c for c in rubric.criteria}
    seen: set[str] = set()
    for c_id in awarded:
        if not isinstance(c_id, str) or c_id not in criteria_map:
            raise GradingMalformedError("Grading awarded an unknown criterion ID.")
        if c_id in seen:
            raise GradingMalformedError("Grading awarded a duplicate criterion ID.")
        if not check_spelling_sensitive_criterion(criteria_map[c_id], student_answer):
            raise GradingMalformedError("Grading waived a spelling-sensitive criterion.")
        seen.add(c_id)
    if rubric.total_marks() != max_marks:
        raise GradingMalformedError("Stored rubric total does not match question marks.")
    earned = sum(c.marks for c in rubric.criteria if c.id in seen)
    if not (0 <= earned <= max_marks):
        raise GradingMalformedError("Grading awarded marks out of range.")


def _build_enriched_feedback(    rubric: WrittenRubric,
    awarded_criterion_ids: tuple[str, ...] | list[str],
    model_feedback: dict[str, Any],
) -> dict[str, Any]:
    """Combine the bounded model summary with server-derived marking points.

    Awarded and missing points carry each criterion's explanation and marks
    so learners see exactly what earned credit and what is still missing.
    """
    awarded_set = set(awarded_criterion_ids)
    summary = model_feedback.get("summary", "") if isinstance(model_feedback, dict) else ""
    if not isinstance(summary, str):
        summary = ""
    awarded = [
        {"id": c.id, "marks": c.marks, "explanation": c.explanation}
        for c in rubric.criteria
        if c.id in awarded_set
    ]
    missing = [
        {"id": c.id, "marks": c.marks, "explanation": c.explanation}
        for c in rubric.criteria
        if c.id not in awarded_set
    ]
    # The summary arrives already validated (nonblank, bounded) by the
    # grader boundary; it is stored as-is, never truncated here.
    return {
        "summary": summary.strip(),
        "awarded": awarded,
        "missing": missing,
        "awarded_count": len(awarded),
        "total_criteria": len(rubric.criteria),
    }
