from typing import Protocol
from uuid import UUID

from app.domain.question import Question


class QuestionRepository(Protocol):
    """Read-only question-bank operations for future session orchestration."""

    def list_active_by_bank(self, bank_key: str) -> tuple[Question, ...]:
        """Return active canonical questions in deterministic position order."""

    def get_by_id(self, question_id: UUID) -> Question | None:
        """Return one canonical question by its durable ID."""

    def get_by_bank_and_stable_key(
        self,
        bank_key: str,
        stable_key: str,
    ) -> Question | None:
        """Return one canonical question by its bank-owned stable key."""
