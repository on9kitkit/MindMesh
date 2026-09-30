"""Domain models for durable private participant review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.question import QuestionOption


@dataclass(frozen=True, slots=True)
class ReviewQuestionItem:
    """One question in a finished session with that viewer's private outcome."""

    session_question_id: UUID
    position: int
    question_type: str
    prompt: str
    max_marks: int
    options: tuple[QuestionOption, ...]
    correct_option_id: str | None
    worked_explanation: str
    original_extract: str | None
    selected_option_id: str | None
    answer_text: str | None
    earned_marks: int
    feedback: dict[str, Any] = field(default_factory=dict)
    awarded_criterion_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionReview:
    """Private review payload for one participant in a finished session."""

    session_id: UUID
    room_id: UUID
    viewer_user_id: UUID
    total_earned_marks: int
    total_available_marks: int
    questions: tuple[ReviewQuestionItem, ...]
