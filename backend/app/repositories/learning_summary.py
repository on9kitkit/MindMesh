"""Repository contract for viewer-owned learning summaries."""

from typing import Protocol
from uuid import UUID

from app.domain.learning_summary import LearningSummaryResult


class LearningSummaryRepository(Protocol):
    def get_learning_summary(self, viewer_id: UUID) -> LearningSummaryResult:
        """Return a bounded summary for the authenticated viewer only."""
