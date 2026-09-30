"""Owner-only, solution-safe solo practice state passed between layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.learning_companions.contracts import MarkProvenance, SoloAttemptStatus


class SoloError(Exception):
    """A safe, closed solo API failure without private source content."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


NOT_FOUND = SoloError("solo_not_found", "This solo attempt is unavailable.", 404)
ACTIVE_ROOM = SoloError("solo_active_room", "Return to or leave your active room first.")
ACTIVE_ATTEMPT = SoloError("solo_active_attempt", "Resume or abandon your active solo quiz first.")
ZONE_REQUIRED = SoloError("solo_home_zone_required", "Choose your home timezone before starting a quiz.")
NOT_READY = SoloError("solo_not_ready", "This solo quiz is not ready yet.")
CONFLICT = SoloError("solo_conflict", "This solo action conflicts with saved progress.")
MARKING_PENDING = SoloError("solo_marking_pending", "Marking is still in progress.")
GENERATION_UNAVAILABLE = SoloError("solo_generation_unavailable", "Quiz preparation is temporarily unavailable.", 503)


@dataclass(frozen=True, slots=True)
class SoloOption:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class PublicSoloQuestion:
    id: UUID
    position: int
    question_type: str
    max_marks: int
    prompt: str
    options: tuple[SoloOption, ...]
    original_extract: str | None


@dataclass(frozen=True, slots=True)
class SoloAnswerState:
    question_id: UUID
    selected_option_id: str | None
    answer_text: str | None
    accepted_at: datetime
    grading_status: str
    mark_provenance: MarkProvenance
    earned_marks: int | None
    feedback: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SoloAttemptState:
    id: UUID
    request_id: UUID
    status: SoloAttemptStatus
    state_version: int
    subject: str
    topic: str
    total_marks: int
    current_question_position: int
    created_at: datetime
    started_at: datetime | None
    terminal_at: datetime | None
    questions: tuple[PublicSoloQuestion, ...] = ()
    answers: tuple[SoloAnswerState, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparationClaim:
    attempt: SoloAttemptState
    preparation_id: UUID
    claim_token: UUID | None
    generation_attempt: int
    lease_expires_at: datetime | None
    claimed: bool


@dataclass(frozen=True, slots=True)
class ClaimedSoloGrade:
    attempt_id: UUID
    answer_id: UUID
    question_id: UUID
    claim_token: UUID
    attempt_count: int
    attempt_cycle: int
    answer_text: str
    prompt: str
    original_extract: str | None
    max_marks: int
    grading_rubric: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SoloReviewQuestion:
    question: PublicSoloQuestion
    answer: SoloAnswerState
    correct_option_id: str | None
    intended_answer: str


@dataclass(frozen=True, slots=True)
class SoloReview:
    attempt: SoloAttemptState
    questions: tuple[SoloReviewQuestion, ...]
