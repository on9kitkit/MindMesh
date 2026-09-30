"""Abstract repository contract for quiz preparations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Sequence
from uuid import UUID

from app.domain.quiz_preparation import QuizPreparation
from app.generator.protocol import GeneratedQuestionData
from app.generator.verification.protocol import VerifiedQuizSet


class QuizPreparationRepository(ABC):
    """Manage durable quiz preparations and generated question definitions."""

    @abstractmethod
    def get_by_id(self, preparation_id: UUID) -> QuizPreparation | None:
        """Fetch preparation by ID with its generated questions."""
        raise NotImplementedError

    @abstractmethod
    def get_by_room_and_request_id(
        self,
        room_id: UUID,
        request_id: UUID,
    ) -> QuizPreparation | None:
        """Fetch preparation by room and client request ID."""
        raise NotImplementedError

    @abstractmethod
    def get_active_for_room(self, room_id: UUID) -> QuizPreparation | None:
        """Fetch active (GENERATING or READY) preparation for a room."""
        raise NotImplementedError

    @abstractmethod
    def claim_or_create_preparation(
        self,
        room_id: UUID,
        request_id: UUID,
        model_id: str,
        lease_seconds: int = 75,
    ) -> tuple[QuizPreparation, bool]:
        """Claim existing preparation or atomically create one under room lock.

        Returns (preparation, claim_acquired). claim_acquired is True only
        for a create or an expired-lease reclaim, i.e. exactly when the
        caller owns the fresh claim token and may launch provider work.
        Live observers and terminal states return False and the caller must
        never use another claimant's token.
        """
        raise NotImplementedError

    @abstractmethod
    def store_generated_questions_cas(
        self,
        preparation_id: UUID,
        request_id: UUID,
        claim_token: UUID,
        attempt: int,
        verified_quiz_set: VerifiedQuizSet,
        operation_deadline: datetime,
    ) -> bool:
        """Persist verified quiz questions and transition to READY under CAS check.

        Requires a validated, typed VerifiedQuizSet. Rejects forged or mismatched proofs
        and enforces that the authoritative database clock has not exceeded operation_deadline.
        """
        raise NotImplementedError
    @abstractmethod
    def mark_preparation_failed_cas(
        self,
        preparation_id: UUID,
        request_id: UUID,
        claim_token: UUID,
        error_category: str,
    ) -> bool:
        """Transition preparation to FAILED under CAS check."""
        raise NotImplementedError

    @abstractmethod
    def renew_preparation_lease_cas(
        self,
        preparation_id: UUID,
        request_id: UUID,
        claim_token: UUID,
        lease_seconds: int = 75,
    ) -> bool:
        """Extend a live GENERATING lease so a second provider call stays covered."""
        raise NotImplementedError

    @abstractmethod
    def fail_expired_generating_preparations(
        self,
        limit: int = 20,
    ) -> tuple[QuizPreparation, ...]:
        """CAS-mark expired GENERATING leases FAILED with a retryable category."""
        raise NotImplementedError

    @abstractmethod
    def get_recent_exclusion_prompts(
        self,
        host_id: UUID,
        quiz_subject: str,
        quiz_topic: str,
        exclude_preparation_id: UUID | None = None,
    ) -> tuple[str, ...]:
        """Fetch up to 50 recent question prompts from last 3 completed quizzes for this host/topic."""
        raise NotImplementedError
