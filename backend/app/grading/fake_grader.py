"""Deterministic fake written answer grader for tests."""

from __future__ import annotations

import re
from typing import Sequence

from app.domain.adaptive_quiz import WrittenRubric
from app.grading.openai_grader import check_spelling_sensitive_criterion
from app.grading.protocol import (
    GradingAuthError,
    GradingError,
    GradingMalformedError,
    GradingRateLimitedError,
    GradingRefusalError,
    GradingRequest,
    GradingResult,
    GradingTimeoutError,
    GradingUnavailableError,
    WrittenAnswerGrader,
)


class FakeWrittenAnswerGrader(WrittenAnswerGrader):
    """Deterministic fake rubric grader for unit and integration tests."""

    def __init__(
        self,
        *,
        is_available: bool = True,
        simulate_timeout: bool = False,
        simulate_refusal: bool = False,
        simulate_rate_limit: bool = False,
        simulate_auth_error: bool = False,
        simulate_malformed: bool = False,
        always_award_all: bool = False,
        never_award_any: bool = False,
    ) -> None:
        self._is_available = is_available
        self._simulate_timeout = simulate_timeout
        self._simulate_refusal = simulate_refusal
        self._simulate_rate_limit = simulate_rate_limit
        self._simulate_auth_error = simulate_auth_error
        self._simulate_malformed = simulate_malformed
        self._always_award_all = always_award_all
        self._never_award_any = never_award_any
        self.call_count = 0
        self.last_request: GradingRequest | None = None

    async def grade_written_answer(self, request: GradingRequest) -> GradingResult:
        self.call_count += 1
        self.last_request = request

        if not self._is_available:
            raise GradingUnavailableError("AI grading unavailable.")
        if self._simulate_timeout:
            raise GradingTimeoutError("Simulated grading timeout.")
        if self._simulate_refusal:
            raise GradingRefusalError("Simulated model refusal.")
        if self._simulate_rate_limit:
            raise GradingRateLimitedError("Simulated rate limit.")
        if self._simulate_auth_error:
            raise GradingAuthError("Simulated auth failure.")
        if self._simulate_malformed:
            raise GradingMalformedError("Simulated malformed output.")

        if self._never_award_any:
            return GradingResult(
                awarded_criterion_ids=(),
                feedback={"summary": "No criteria met."},
            )

        if self._always_award_all:
            # Still respect spelling sensitive check on server!
            awarded = [
                c.id
                for c in request.rubric.criteria
                if check_spelling_sensitive_criterion(c, request.student_answer)
            ]
            return GradingResult(
                awarded_criterion_ids=tuple(awarded),
                feedback={"summary": "All criteria met."},
            )

        # Keyword matching heuristic for deterministic testing:
        # If student answer contains at least one meaningful word from marking_point or accepted_meaning
        student_words = set(re.findall(r"\w+", request.student_answer.lower()))
        awarded_ids: list[str] = []

        for criterion in request.rubric.criteria:
            if not check_spelling_sensitive_criterion(criterion, request.student_answer):
                continue

            target_words = set(re.findall(r"\w+", (criterion.accepted_meaning or criterion.marking_point).lower()))
            # Remove common stop words
            target_words -= {"the", "a", "an", "is", "of", "in", "and", "or", "to", "for", "by", "on"}

            if not target_words or bool(target_words & student_words):
                awarded_ids.append(criterion.id)

        feedback = {
            "summary": f"Awarded {len(awarded_ids)} out of {len(request.rubric.criteria)} marking points.",
        }
        return GradingResult(
            awarded_criterion_ids=tuple(awarded_ids),
            feedback=feedback,
        )
