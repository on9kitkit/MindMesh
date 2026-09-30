from datetime import datetime
from uuid import UUID

from app.domain.quiz import (
    AnswerAcknowledgement,
    AuthoritativeSnapshot,
    QuizSession,
    ReadyState,
    SessionQuestion,
)
from app.domain.quiz_review import SessionReview
from app.repositories.quiz_sessions import ClaimedSubmission, QuizSessionRepository


class SessionService:
    """Application boundary for transactional authoritative quiz operations."""

    def __init__(self, repository: QuizSessionRepository) -> None:
        self._repository = repository

    def set_ready(self, room_id: UUID, user_id: UUID, ready: bool) -> ReadyState:
        """Set readiness to the requested value; this is not a toggle."""

        return self._repository.set_ready(room_id, user_id, ready)

    def start_session(
        self,
        room_id: UUID,
        requesting_user_id: UUID,
    ) -> QuizSession:
        """Start one session and create its durable snapshots atomically."""

        return self._repository.start_session(room_id, requesting_user_id)

    def get_session(self, session_id: UUID) -> QuizSession | None:
        """Load durable session metadata for recovery coordination."""

        return self._repository.get_by_id(session_id)

    def get_active_session(self, room_id: UUID) -> QuizSession | None:
        """Load the room's current non-finished session without reconciling."""

        return self._repository.get_active_by_room(room_id)

    def list_active_sessions(self) -> tuple[QuizSession, ...]:
        """Load all active sessions for startup recovery."""

        return self._repository.list_active()

    def get_session_deadline(self, session_id: UUID) -> datetime | None:
        """Load the current durable wake-up deadline."""

        return self._repository.get_deadline(session_id)
    def list_questions(self, session_id: UUID) -> tuple[SessionQuestion, ...]:
        """List session questions in position order."""

        return self._repository.list_questions(session_id)


    def submit_answer(
        self,
        room_id: UUID,
        user_id: UUID,
        session_question_id: UUID,
        selected_option_id: str | None = None,
        answer_text: str | None = None,
    ) -> AnswerAcknowledgement:
        """Submit an answer and expose only safe acknowledgement data."""

        answer = self._repository.submit_answer(
            room_id=room_id,
            user_id=user_id,
            session_question_id=session_question_id,
            selected_option_id=selected_option_id,
            answer_text=answer_text,
        )
        return AnswerAcknowledgement(
            submission_id=answer.id,
            session_id=answer.session_id,
            session_question_id=answer.session_question_id,
            selected_option_id=answer.selected_option_id,
            accepted_at=answer.submitted_at,
            answer_text=answer.answer_text,
            grading_status=answer.grading_status,
        )
    def reconcile_session(
        self,
        *,
        session_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> QuizSession | None:
        """Reconcile by explicit session ID or by the room's active session."""

        if (session_id is None) == (room_id is None):
            raise ValueError("provide exactly one of session_id or room_id")
        if session_id is not None:
            return self._repository.reconcile_session(session_id)
        return self._repository.reconcile_active_for_room(room_id)

    def get_state_snapshot(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> AuthoritativeSnapshot:
        """Authorize the viewer, reconcile once, then load safe state."""

        # Do not let an unauthorized request trigger a durable deadline
        # transition. The second load returns the post-reconciliation view.
        self._repository.load_snapshot(room_id, user_id)
        self._repository.reconcile_active_for_room(room_id)
        return self._repository.load_snapshot(room_id, user_id)

    def load_state_snapshot(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> AuthoritativeSnapshot:
        """Load without a second implicit transition after explicit reconciliation."""

        return self._repository.load_snapshot(room_id, user_id)

    def get_session_review(
        self,
        room_id: UUID,
        session_id: UUID,
        user_id: UUID,
    ) -> SessionReview:
        """Load durable private participant review for a finished session."""

        return self._repository.get_session_review(room_id, session_id, user_id)

    def claim_due_written_submissions(
        self,
        limit: int = 10,
        lease_seconds: int = 30,
    ) -> tuple[ClaimedSubmission, ...]:
        """Claim due written submissions for Luna rubric assessment."""

        return self._repository.claim_due_written_submissions(limit, lease_seconds)

    def reset_expired_grading_claims(self) -> tuple[UUID, ...]:
        """Recover expired claims; return affected session IDs for reconcile."""

        return self._repository.reset_expired_grading_claims()

    def store_written_grading_result_cas(
        self,
        submission_id: UUID,
        claim_token: UUID,
        earned_marks: int,
        is_correct: bool,
        points: int,
        awarded_criterion_ids: list[str],
        feedback: dict,
    ) -> bool:
        """Store final written grading result under attempt token CAS check."""

        return self._repository.store_written_grading_result_cas(
            submission_id=submission_id,
            claim_token=claim_token,
            earned_marks=earned_marks,
            is_correct=is_correct,
            points=points,
            awarded_criterion_ids=awarded_criterion_ids,
            feedback=feedback,
        )

    def mark_written_grading_retryable_or_unavailable(
        self,
        submission_id: UUID,
        claim_token: UUID,
        error_category: str,
        backoff_seconds: int = 5,
    ) -> bool:
        """Mark written grading retryable or unavailable upon attempt exhaustion."""

        return self._repository.mark_written_grading_retryable_or_unavailable(
            submission_id=submission_id,
            claim_token=claim_token,
            error_category=error_category,
            backoff_seconds=backoff_seconds,
        )

    def retry_grading_for_room(
        self,
        room_id: UUID,
        requesting_user_id: UUID,
    ) -> int:
        """Host-only command to restart a grading cycle for UNAVAILABLE submissions."""

        return self._repository.retry_grading_for_room(room_id, requesting_user_id)
