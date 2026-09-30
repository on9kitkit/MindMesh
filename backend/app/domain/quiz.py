"""Authoritative quiz domain models, status transitions, and scoring rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID
QUESTION_DURATION_SECONDS = 20
REVEAL_DURATION_SECONDS = 3
CORRECT_POINTS = 100
INCORRECT_POINTS = 0
from app.domain.question import QuestionOption
from app.domain.room import Room


class QuizSessionStatus(str, Enum):
    """Persisted server-authoritative quiz session states."""

    QUESTION_OPEN = "QUESTION_OPEN"
    QUESTION_GRADING = "QUESTION_GRADING"
    QUESTION_REVEAL = "QUESTION_REVEAL"
    FINISHED = "FINISHED"


class ViewerRole(str, Enum):
    """The authenticated viewer's role within the room."""

    HOST = "host"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class QuizSession:
    """Durable session state returned by authoritative service operations."""

    id: UUID
    room_id: UUID
    question_bank_key: str
    status: QuizSessionStatus
    current_question_position: int
    state_version: int
    started_at: datetime
    reveal_ends_at: datetime | None
    finished_at: datetime | None
    preparation_id: UUID | None = None
    quiz_mode: str = "LEGACY_PHYSICS"
    education_level: str | None = None
    quiz_subject: str | None = None
    quiz_topic: str | None = None
    total_available_marks: int = 5

    @property
    def is_adaptive(self) -> bool:
        return self.quiz_mode == "ADAPTIVE"


@dataclass(frozen=True, slots=True)
class SessionParticipant:
    """A session-local participant with an immutable display snapshot."""

    id: UUID
    session_id: UUID
    user_id: UUID
    room_membership_id: UUID
    display_name_snapshot: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionQuestion:
    """Question content copied into a session for historical stability."""

    id: UUID
    session_id: UUID
    source_question_id: UUID | None
    position: int
    prompt_snapshot: str
    options_snapshot: tuple[QuestionOption, ...]
    correct_option_id: str | None
    duration_seconds: int
    opened_at: datetime | None
    closes_at: datetime | None
    revealed_at: datetime | None
    generated_question_id: UUID | None = None
    question_type: str = "MULTIPLE_CHOICE"
    max_marks: int = 1
    grading_rubric_snapshot: dict[str, Any] = field(default_factory=dict)
    worked_explanation_snapshot: str = ""
    original_extract: str | None = None
    content_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class AnswerSubmission:
    """One participant's immutable answer for one session question."""

    id: UUID
    session_id: UUID
    session_question_id: UUID
    participant_id: UUID
    selected_option_id: str | None
    submitted_at: datetime
    response_time_ms: int
    is_correct: bool | None
    points: int | None
    answer_text: str | None = None
    earned_marks: int | None = None
    grading_method: str = "LEGACY_OPTION"
    grading_status: str = "GRADED"
    attempt_cycle: int = 1
    attempt_count: int = 1
    claim_token: UUID | None = None
    lease_expires_at: datetime | None = None
    next_attempt_at: datetime | None = None
    last_error_category: str | None = None
    awarded_criterion_ids: tuple[str, ...] = ()
    feedback: dict[str, Any] = field(default_factory=dict)
    graded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """Leaderboard row derived from answer submissions."""

    rank: int
    participant_id: UUID
    user_id: UUID
    display_name: str
    points: int
    correct_count: int
    total_response_time_ms: int
    earned_marks: int = 0
    total_available_marks: int = 5

    @property
    def total_points(self) -> int:
        return self.points

    @property
    def correct_answers(self) -> int:
        return self.correct_count

    @property
    def display_name_snapshot(self) -> str:
        return self.display_name


@dataclass(frozen=True, slots=True)
class ReadyState:
    """The persisted desired readiness state for one active member."""

    room_id: UUID
    user_id: UUID
    ready: bool
    ready_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParticipantSnapshot:
    """A participant plus current lobby readiness for an authoritative view."""

    user_id: UUID
    display_name: str
    ready: bool


@dataclass(frozen=True, slots=True)
class PublicQuestion:
    """Question data safe to expose before reveal."""

    id: UUID
    prompt: str
    options: tuple[QuestionOption, ...]
    question_number: int
    total_questions: int
    closes_at: datetime
    question_type: str = "MULTIPLE_CHOICE"
    max_marks: int = 1
    original_extract: str | None = None


@dataclass(frozen=True, slots=True)
class RevealedQuestion:
    """Question data exposed after its reveal begins."""

    id: UUID
    prompt: str
    options: tuple[QuestionOption, ...]
    question_number: int
    total_questions: int
    closes_at: datetime
    correct_option_id: str | None = None
    question_type: str = "MULTIPLE_CHOICE"
    max_marks: int = 1
    worked_explanation: str = ""
    original_extract: str | None = None


@dataclass(frozen=True, slots=True)
class ViewerSubmission:
    """The viewer's answer, with private result fields gated by visibility."""

    session_question_id: UUID
    selected_option_id: str | None
    is_correct: bool | None
    points: int | None
    answer_text: str | None = None
    earned_marks: int | None = None
    max_marks: int | None = None
    grading_status: str = "GRADED"
    feedback: dict[str, Any] = field(default_factory=dict)
    awarded_criterion_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerAcknowledgement:
    """Safe answer acknowledgement returned before reveal."""

    submission_id: UUID
    session_id: UUID
    session_question_id: UUID
    selected_option_id: str | None
    accepted_at: datetime
    answer_text: str | None = None
    grading_status: str = "GRADED"


@dataclass(frozen=True, slots=True)
class AuthoritativeSnapshot:
    """Complete server-derived room/session view for one authenticated member."""

    server_time: datetime
    room: Room
    viewer_role: ViewerRole
    participants: tuple[ParticipantSnapshot, ...]
    viewer_ready: bool
    session: QuizSession | None
    viewer_participated: bool
    state_version: int
    current_question_number: int | None
    total_question_count: int
    question: PublicQuestion | RevealedQuestion | None
    closes_at: datetime | None
    reveal_ends_at: datetime | None
    viewer_submission: ViewerSubmission | None
    leaderboard: tuple[LeaderboardEntry, ...]
    finished_at: datetime | None
    active_preparation_status: str | None = None
    active_preparation_version: int | None = None
    active_preparation_error_category: str | None = None
    grading_retry_needed: bool = False


def score_answer(selected_option_id: str, correct_option_id: str) -> tuple[bool, int]:
    """Apply the locked no-speed-bonus scoring rule without accepting an answer."""
    is_correct = selected_option_id == correct_option_id
    return is_correct, CORRECT_POINTS if is_correct else INCORRECT_POINTS
