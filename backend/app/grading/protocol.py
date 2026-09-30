"""Protocols, data contracts, and errors for rubric-based written answer assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.adaptive_quiz import WrittenRubric

GRADING_TIMEOUT_SECONDS = 20.0
MAX_CONCURRENT_GRADING_CALLS = 4
MAX_GRADING_LEASE_SECONDS = 30


class GradingError(Exception):
    """Base exception for written answer rubric grading failures."""
    category: str = "grading_failed"


class GradingUnavailableError(GradingError):
    category: str = "ai_grading_unavailable"


class GradingTimeoutError(GradingError):
    category: str = "timeout"


class GradingRefusalError(GradingError):
    category: str = "refusal"


class GradingRateLimitedError(GradingError):
    category: str = "rate_limited"


class GradingAuthError(GradingError):
    category: str = "authentication_failed"


class GradingMalformedError(GradingError):
    category: str = "malformed_output"


@dataclass(frozen=True, slots=True)
class GradingRequest:
    """Safe, identity-free grading request sent to the model."""

    question_prompt: str
    original_extract: str | None
    student_answer: str
    max_marks: int
    rubric: WrittenRubric


@dataclass(frozen=True, slots=True)
class GradingResult:
    """Validated rubric assessment outcome."""

    awarded_criterion_ids: tuple[str, ...]
    feedback: dict[str, Any] = field(default_factory=dict)


class WrittenAnswerGrader(Protocol):
    """Protocol for server-side semantic rubric assessment of student answers."""

    async def grade_written_answer(self, request: GradingRequest) -> GradingResult:
        """Evaluate a student's answer against a hidden rubric."""
        ...
