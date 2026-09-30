"""Application-facing retention service with an explicit execution boundary."""

from datetime import datetime

from app.retention.policy import RetentionPolicy
from app.retention.repository import PostgresRetentionRepository
from app.retention.summary import RetentionRunSummary


class RetentionService:
    """Expose preview and destructive purge as separate named operations."""

    def __init__(self, repository: PostgresRetentionRepository) -> None:
        self._repository = repository

    def preview(
        self,
        policy: RetentionPolicy,
        *,
        as_of: datetime | None = None,
    ) -> RetentionRunSummary:
        return self._repository.preview(policy, as_of=as_of)

    def purge(
        self,
        policy: RetentionPolicy,
        *,
        as_of: datetime | None = None,
    ) -> RetentionRunSummary:
        return self._repository.purge(policy, as_of=as_of)

    def run(
        self,
        policy: RetentionPolicy,
        *,
        execute: bool = False,
        as_of: datetime | None = None,
    ) -> RetentionRunSummary:
        if execute:
            return self.purge(policy, as_of=as_of)
        return self.preview(policy, as_of=as_of)
