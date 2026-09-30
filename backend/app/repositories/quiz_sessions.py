"""Transactional repository contract for authoritative quiz sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.domain.quiz import (
    AnswerSubmission,
    AuthoritativeSnapshot,
    LeaderboardEntry,
    QuizSession,
    ReadyState,
    SessionParticipant,
    SessionQuestion,
)
from app.domain.quiz_review import SessionReview


@dataclass(frozen=True, slots=True)
class ClaimedSubmission:
    """A written submission claimed for rubric assessment outside DB transaction."""

    submission_id: UUID
    session_id: UUID
    session_question_id: UUID
    participant_id: UUID
    claim_token: UUID
    attempt_count: int
    attempt_cycle: int
    answer_text: str
    question_prompt: str
    original_extract: str | None
    max_marks: int
    grading_rubric: dict[str, Any]
    session_state_version: int


class QuizSessionRepository(Protocol):
    """Transactional repository boundary for authoritative quiz sessions."""

    def get_active_by_room(self, room_id: UUID) -> QuizSession | None:
        """Return the room's current non-finished session, if any."""
        ...

    def get_by_id(self, session_id: UUID) -> QuizSession | None:
        """Return one persisted quiz session."""
        ...

    def list_active(self) -> tuple[QuizSession, ...]:
        """Return all non-finished sessions for recovery scheduling."""
        ...

    def get_deadline(self, session_id: UUID) -> datetime | None:
        """Return the current durable deadline for one active session."""
        ...

    def list_questions(self, session_id: UUID) -> tuple[SessionQuestion, ...]:
        """Return session question snapshots in position order."""
        ...

    def list_participants(self, session_id: UUID) -> tuple[SessionParticipant, ...]:
        """Return session participants in creation order."""
        ...

    def list_submissions(self, session_id: UUID) -> tuple[AnswerSubmission, ...]:
        """Return answer submissions in submission order."""
        ...

    def derive_leaderboard(
        self,
        session_id: UUID,
        *,
        revealed_only: bool = False,
    ) -> tuple[LeaderboardEntry, ...]:
        """Derive leaderboard rows from submissions without a score table."""
        ...

    def set_ready(self, room_id: UUID, user_id: UUID, ready: bool) -> ReadyState:
        """Persist desired readiness under the room lock."""
        ...

    def start_session(self, room_id: UUID, requesting_user_id: UUID) -> QuizSession:
        """Atomically validate the lobby and create all session snapshots."""
        ...

    def submit_answer(
        self,
        room_id: UUID,
        user_id: UUID,
        session_question_id: UUID,
        selected_option_id: str | None = None,
        answer_text: str | None = None,
    ) -> AnswerSubmission:
        """Accept one authoritative answer under the active-session lock."""
        ...

    def reconcile_session(self, session_id: UUID) -> QuizSession:
        """Reconcile at most one persisted session transition atomically."""
        ...

    def reconcile_active_for_room(self, room_id: UUID) -> QuizSession | None:
        """Reconcile the room's active session, if one exists."""
        ...

    def load_snapshot(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> AuthoritativeSnapshot:
        """Load a safe authoritative snapshot for an active room member."""
        ...

    def get_session_review(
        self,
        room_id: UUID,
        session_id: UUID,
        user_id: UUID,
    ) -> SessionReview:
        """Load private question-by-question review for a participant in a FINISHED session."""
        ...

    def claim_due_written_submissions(
        self,
        limit: int = 10,
        lease_seconds: int = 30,
    ) -> tuple[ClaimedSubmission, ...]:
        """Claim due PENDING/RETRYABLE written submissions with FOR UPDATE SKIP LOCKED."""
        ...

    def reset_expired_grading_claims(self) -> tuple[UUID, ...]:
        """Return expired IN_PROGRESS claims; exhausted cycles become UNAVAILABLE."""
        ...

    def store_written_grading_result_cas(
        self,
        submission_id: UUID,
        claim_token: UUID,
        earned_marks: int,
        is_correct: bool,
        points: int,
        awarded_criterion_ids: Sequence[str],
        feedback: dict[str, Any],
    ) -> bool:
        """Persist final rubric grading result under attempt token CAS check."""
        ...

    def mark_written_grading_retryable_or_unavailable(
        self,
        submission_id: UUID,
        claim_token: UUID,
        error_category: str,
        backoff_seconds: int = 5,
    ) -> bool:
        """Increment attempt and set RETRYABLE or UNAVAILABLE upon cycle exhaustion."""
        ...

    def retry_grading_for_room(
        self,
        room_id: UUID,
        requesting_user_id: UUID,
    ) -> int:
        """Host-only command resetting UNAVAILABLE submissions to PENDING for a new cycle."""
        ...
