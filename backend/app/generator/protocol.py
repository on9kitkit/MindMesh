"""Protocols, schemas, and error types for AI quiz content generation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol
from uuid import UUID

from app.domain.adaptive_quiz import (
    MultipleChoiceOption,
    NumericalRubric,
    QuestionType,
    UnitDependency,
    WrittenCriterion,
    WrittenRubric,
)

MODEL_ID_GPT_6_LUNA = "gpt-6-luna"
# Keep the historical symbol import-compatible for consumers that have not
# yet switched to the current canonical name.
MODEL_ID_GPT_5_6_LUNA = MODEL_ID_GPT_6_LUNA
GENERATION_LEASE_SECONDS = 75
GENERATION_TIMEOUT_SECONDS = 45
MAX_EXCLUSION_PROMPTS = 50
MAX_EXCLUSION_BYTES = 8192


class GeneratorError(Exception):
    """Base error for content generation failures."""
    category: str = "generation_failed"


class GeneratorUnavailableError(GeneratorError):
    category: str = "ai_generation_unavailable"


class GeneratorTimeoutError(GeneratorError):
    category: str = "timeout"


class GeneratorRefusalError(GeneratorError):
    category: str = "refusal"


class GeneratorRateLimitedError(GeneratorError):
    category: str = "rate_limited"


class GeneratorAuthError(GeneratorError):
    category: str = "authentication_failed"


class GeneratorMalformedError(GeneratorError):
    category: str = "malformed_output"


class GeneratorValidationError(GeneratorError):
    category: str = "validation_failed"


@dataclass(frozen=True, slots=True)
class GeneratedQuestionData:
    """Validated question structure from generator output."""

    position: int
    question_type: QuestionType
    prompt: str
    max_marks: int
    duration_seconds: int
    options: tuple[MultipleChoiceOption, ...]
    correct_option_id: str | None
    grading_rubric: dict[str, Any]
    worked_explanation: str
    original_extract: str | None
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Parameters passed to the quiz content generator."""

    education_level: str
    quiz_subject: str
    quiz_topic: str
    target_total_marks: int
    exclusion_prompts: tuple[str, ...] = ()


class QuizContentGenerator(Protocol):
    """Protocol for server-only AI quiz content generation."""

    async def generate_quiz_questions(
        self,
        request: GenerationRequest,
    ) -> tuple[GeneratedQuestionData, ...]:
        """Generate questions whose marks sum exactly to target_total_marks."""
        ...
