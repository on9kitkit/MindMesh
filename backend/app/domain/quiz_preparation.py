"""Durable domain entity for quiz preparations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.adaptive_quiz import PreparationStatus, QuestionType


@dataclass(frozen=True, slots=True)
class GeneratedQuestion:
    """Immutable domain representation of a generated question."""

    id: UUID
    preparation_id: UUID
    position: int
    question_type: QuestionType
    prompt: str
    max_marks: int
    duration_seconds: int
    options: tuple[dict[str, Any], ...]
    correct_option_id: str | None
    grading_rubric: dict[str, Any]
    worked_explanation: str
    original_extract: str | None
    content_fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QuizPreparation:
    """Durable domain representation of an adaptive quiz preparation."""

    id: UUID
    room_id: UUID
    request_id: UUID
    status: PreparationStatus
    state_version: int
    generation_attempt: int
    claim_token: UUID | None
    lease_expires_at: datetime | None
    model_id: str
    error_category: str | None
    created_at: datetime
    updated_at: datetime
    ready_at: datetime | None
    consumed_at: datetime | None
    verification_revision: str | None = None
    verified_content_digest: str | None = None
    questions: tuple[GeneratedQuestion, ...] = ()

    @property
    def is_ready(self) -> bool:
        return self.status == PreparationStatus.READY

    @property
    def is_generating(self) -> bool:
        return self.status == PreparationStatus.GENERATING

    @property
    def is_failed(self) -> bool:
        return self.status == PreparationStatus.FAILED

    @property
    def is_consumed(self) -> bool:
        return self.status == PreparationStatus.CONSUMED
