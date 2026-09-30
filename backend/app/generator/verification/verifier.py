"""Composite verification orchestrator coordinating blind solving, pre-checks, and consistency assessment."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import logging
from typing import Sequence

from app.domain.adaptive_quiz import MAX_MARK_BUDGET
from app.generator.protocol import GeneratedQuestionData, GenerationRequest
from app.generator.verification.protocol import (
    BLIND_SOLVE_TIMEOUT_SECONDS,
    CONSISTENCY_ASSESSMENT_TIMEOUT_SECONDS,
    VERIFICATION_REVISION,
    BlindQuizSolver,
    BlindSolution,
    BlindSolveQuestionInput,
    BlindSolveRequest,
    BlindSolveResult,
    BlindSolveStatus,
    ConsistencyAssessmentRequest,
    ConsistencyAssessmentResult,
    ConsistencyQuestionInput,
    ConsistencyRejectionReason,
    ConsistencyVerdict,
    QuestionConsistencyVerdict,
    QuizConsistencyAssessor,
    QuizContentVerifier,
    VerificationInvalidError,
    VerificationRejectedError,
    VerificationTimeoutError,
    VerifiedQuizSet,
    _deserialize_candidate_questions_canonical_json,
    _serialize_candidate_questions_canonical_json,
    compute_verified_content_digest,
    validate_deterministic_agreement,
)

logger = logging.getLogger(__name__)


class QuizContentVerificationService(QuizContentVerifier):
    """Orchestrate the content-verification gate pipeline.

    Enforces:
    - Defensive candidate freezing before any await to guarantee in-flight caller mutation
      cannot affect the verified set or content digest.
    - Local candidate validation against GenerationRequest (marks sum equals target budget).
    - Zero-based contiguous question positions (0..N-1) within mark budget limits (1..40).
    - Strict deadline checking before AND after each before_paid_phase callback, and before AND after
      each provider await. If a callback consumes the remaining deadline, no provider call is spent.
    - Provider call timeouts bounded by the remaining pipeline deadline.
    - Strict position, type, and enum checks on all injected solver/assessor results (no bool or raw strings).
    - Deterministic pre-checks (MCQ key agreement and numerical rubric grading); disagreement
      terminates immediately with VerificationRejectedError without invoking consistency assessment.
    - Fresh consistency assessment for surviving candidates; all verdicts must be PASS/CONSISTENT.
    - Final revalidation and certification of VerifiedQuizSet with full content digest.
    """

    def __init__(
        self,
        solver: BlindQuizSolver,
        assessor: QuizConsistencyAssessor,
        *,
        revision: str = VERIFICATION_REVISION,
    ) -> None:
        self._solver = solver
        self._assessor = assessor
        self._revision = revision

    async def verify_quiz_content(
        self,
        questions: tuple[GeneratedQuestionData, ...],
        request: GenerationRequest,
        *,
        before_paid_phase: Callable[[], Awaitable[None]] | None = None,
        deadline_at: datetime | None = None,
    ) -> VerifiedQuizSet:
        # 1. Synchronous validation and defensive freezing BEFORE any await
        if not questions:
            raise VerificationInvalidError("Cannot verify empty question set.")
        if not (1 <= len(questions) <= MAX_MARK_BUDGET):
            raise VerificationInvalidError(f"Question count ({len(questions)}) out of bounds (1..{MAX_MARK_BUDGET}).")

        # Validate contiguous zero-based positions (0..N-1) and integer types
        expected_positions = tuple(range(len(questions)))
        actual_positions = tuple(q.position for q in questions)
        if actual_positions != expected_positions or any(type(p) is not int for p in actual_positions):
            raise VerificationInvalidError("Questions must have contiguous zero-based integer positions 0..N-1.")

        # Validate candidate questions against GenerationRequest
        marks_sum = sum(q.max_marks for q in questions)
        if marks_sum != request.target_total_marks:
            raise VerificationInvalidError(
                f"Candidate questions marks sum ({marks_sum}) does not equal target budget ({request.target_total_marks})."
            )

        # Defensively freeze candidate questions into an immutable serialized snapshot
        canonical_snapshot_bytes = _serialize_candidate_questions_canonical_json(questions)
        frozen_questions = _deserialize_candidate_questions_canonical_json(canonical_snapshot_bytes)
        initial_digest = compute_verified_content_digest(frozen_questions, self._revision)

        def _check_deadline() -> None:
            if deadline_at is not None:
                if datetime.now(timezone.utc) >= deadline_at:
                    raise VerificationTimeoutError("Verification deadline exceeded.")

        def _remaining_timeout(phase_cap: float) -> float:
            if deadline_at is None:
                return phase_cap
            rem = (deadline_at - datetime.now(timezone.utc)).total_seconds()
            if rem <= 0:
                raise VerificationTimeoutError("Verification deadline exceeded.")
            return min(phase_cap, rem)

        # --- Phase 1: Blind Solve ---
        _check_deadline()
        if before_paid_phase is not None:
            await before_paid_phase()
            # Recheck deadline immediately AFTER callback: if callback consumed deadline, do not spend provider call
            _check_deadline()

        blind_inputs = tuple(BlindSolveQuestionInput.from_candidate(q) for q in frozen_questions)
        solve_request = BlindSolveRequest(
            education_level=request.education_level,
            quiz_subject=request.quiz_subject,
            quiz_topic=request.quiz_topic,
            questions=blind_inputs,
        )

        blind_timeout = _remaining_timeout(BLIND_SOLVE_TIMEOUT_SECONDS)
        try:
            async with asyncio.timeout(blind_timeout):
                solve_result: BlindSolveResult = await self._solver.solve_blind(solve_request)
        except TimeoutError as exc:
            raise VerificationTimeoutError("Blind solve deadline exceeded.") from exc

        _check_deadline()

        # Validate blind solver solutions
        if len(solve_result.solutions) != len(frozen_questions):
            raise VerificationInvalidError("Blind solve solution count does not match question count.")

        solutions_by_pos: dict[int, BlindSolution] = {}
        for s in solve_result.solutions:
            if type(s.position) is not int:
                raise VerificationInvalidError("Blind solution position must be an integer.")
            if s.position in solutions_by_pos:
                raise VerificationInvalidError("Blind solve returned duplicate question positions.")
            if type(s.solve_status) is not BlindSolveStatus:
                raise VerificationInvalidError("Blind solution solve_status must be BlindSolveStatus enum.")
            solutions_by_pos[s.position] = s

        # --- Phase 2: Deterministic Pre-Checks ---
        rejections: list[ConsistencyRejectionReason] = []
        rejected_positions: list[int] = []

        for q in frozen_questions:
            blind_sol = solutions_by_pos.get(q.position)
            if blind_sol is None:
                raise VerificationInvalidError("Blind solve missing solution for question position.")
            passed, reason, _ = validate_deterministic_agreement(q, blind_sol)
            if not passed:
                rejections.append(reason or ConsistencyRejectionReason.OTHER_REJECT)
                rejected_positions.append(q.position)

        if rejections:
            # Deterministic disagreement terminates immediately without invoking consistency audit
            raise VerificationRejectedError(
                "Deterministic agreement failed for one or more questions.",
                reasons=rejections,
                rejected_positions=rejected_positions,
            )

        # --- Phase 3: Consistency Assessment ---
        _check_deadline()
        if before_paid_phase is not None:
            await before_paid_phase()
            # Recheck deadline immediately AFTER callback
            _check_deadline()

        assessment_inputs = tuple(
            ConsistencyQuestionInput(
                position=q.position,
                candidate_question=q,
                blind_solution=solutions_by_pos[q.position],
            )
            for q in frozen_questions
        )
        assessment_request = ConsistencyAssessmentRequest(
            education_level=request.education_level,
            quiz_subject=request.quiz_subject,
            quiz_topic=request.quiz_topic,
            assessments=assessment_inputs,
        )

        audit_timeout = _remaining_timeout(CONSISTENCY_ASSESSMENT_TIMEOUT_SECONDS)
        try:
            async with asyncio.timeout(audit_timeout):
                assessment_result: ConsistencyAssessmentResult = await self._assessor.assess_consistency(assessment_request)
        except TimeoutError as exc:
            raise VerificationTimeoutError("Consistency assessment deadline exceeded.") from exc

        _check_deadline()

        # Validate consistency assessment verdicts
        if len(assessment_result.verdicts) != len(frozen_questions):
            raise VerificationInvalidError("Consistency verdict count does not match question count.")

        verdicts_by_pos: dict[int, QuestionConsistencyVerdict] = {}
        for v in assessment_result.verdicts:
            if type(v.position) is not int:
                raise VerificationInvalidError("Consistency verdict position must be an integer.")
            if v.position in verdicts_by_pos:
                raise VerificationInvalidError("Consistency assessment returned duplicate positions.")
            if type(v.verdict) is not ConsistencyVerdict:
                raise VerificationInvalidError("Consistency verdict must be ConsistencyVerdict enum.")
            if type(v.reason) is not ConsistencyRejectionReason:
                raise VerificationInvalidError("Consistency reason must be ConsistencyRejectionReason enum.")
            verdicts_by_pos[v.position] = v

        for q in frozen_questions:
            v = verdicts_by_pos.get(q.position)
            if v is None:
                raise VerificationInvalidError("Consistency assessment missing verdict for question position.")
            if v.verdict != ConsistencyVerdict.PASS or v.reason != ConsistencyRejectionReason.CONSISTENT:
                rejections.append(v.reason)
                rejected_positions.append(q.position)

        if rejections:
            raise VerificationRejectedError(
                "Consistency assessment rejected one or more questions.",
                reasons=rejections,
                rejected_positions=rejected_positions,
            )

        # Revalidate content integrity before certifying proof
        final_digest = compute_verified_content_digest(frozen_questions, self._revision)
        if final_digest != initial_digest:
            raise VerificationInvalidError("Candidate content altered during verification.")

        sorted_verdicts = tuple(verdicts_by_pos[q.position] for q in sorted(frozen_questions, key=lambda x: x.position))
        return VerifiedQuizSet(
            candidate_questions=frozen_questions,
            verdicts=sorted_verdicts,
            verification_revision=self._revision,
            verified_content_digest=final_digest,
        )
