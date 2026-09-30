from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from app.account_deletion.ports import (
    AccountDeletionProviderError,
    REVENUECAT_PROVIDER,
    SUPABASE_AUTH_PROVIDER,
    RevenueCatCustomerDeletionProvider,
    SupabaseAuthDeletionProvider,
)
from app.account_deletion.repository import (
    AccountDeletionLocalResult,
    ClaimedDeletionJob,
    PostgresAccountDeletionRepository,
)
from app.account_deletion.settings import AccountDeletionSettings


@dataclass(frozen=True, slots=True)
class AccountDeletionProviderSummary:
    attempted_jobs: int
    pending: bool


class AccountDeletionOperations(Protocol):
    """Request-facing seam that ordinary API tests can replace with a fake."""

    def delete_local_account(self, user_id: UUID) -> AccountDeletionLocalResult:
        """Commit local deletion and its provider outbox."""

    def process_user_jobs(self, user_id: UUID) -> AccountDeletionProviderSummary:
        """Attempt provider work after the local transaction commits."""

    def has_pending_jobs(self, user_id: UUID) -> bool:
        """Report whether provider cleanup remains pending."""


class AccountDeletionService:
    """Coordinate local deletion and the post-commit provider saga."""

    def __init__(
        self,
        repository: PostgresAccountDeletionRepository,
        *,
        supabase_provider: SupabaseAuthDeletionProvider | None = None,
        revenuecat_provider: RevenueCatCustomerDeletionProvider | None = None,
        settings: AccountDeletionSettings | None = None,
    ) -> None:
        self._repository = repository
        self._supabase_provider = supabase_provider
        self._revenuecat_provider = revenuecat_provider
        self._settings = settings or AccountDeletionSettings()

    @property
    def settings(self) -> AccountDeletionSettings:
        return self._settings

    def delete_local_account(self, user_id: UUID) -> AccountDeletionLocalResult:
        """Commit only local state and outbox rows; never call a provider here."""

        return self._repository.delete_local_account(user_id)

    def process_user_jobs(self, user_id: UUID) -> AccountDeletionProviderSummary:
        return self._process_jobs(user_id=user_id)

    def retry_pending(self) -> AccountDeletionProviderSummary:
        """Operator/startup recovery entry point for pending saga work."""

        self._repository.recover_interrupted_jobs()
        return self._process_jobs(user_id=None)

    def has_pending_jobs(self, user_id: UUID) -> bool:
        return self._repository.has_pending_jobs(user_id)

    def close(self) -> None:
        for provider in (self._supabase_provider, self._revenuecat_provider):
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def _process_jobs(self, user_id: UUID | None) -> AccountDeletionProviderSummary:
        jobs = self._repository.claim_due_jobs(
            user_id=user_id,
            limit=self._settings.max_jobs_per_run,
            claim_lease_seconds=self._settings.claim_lease_seconds,
        )
        for job in jobs:
            self._process_one(job)
        pending = False
        if user_id is not None:
            pending = self._repository.has_pending_jobs(user_id)
        else:
            pending = self._repository.has_any_pending_jobs()
        return AccountDeletionProviderSummary(
            attempted_jobs=len(jobs),
            pending=pending,
        )

    def _process_one(self, job: ClaimedDeletionJob) -> None:
        try:
            self._call_provider(job)
        except AccountDeletionProviderError as error:
            self._mark_failed(job, error.category)
        except Exception:
            # Fakes and unexpected adapter failures cannot put provider details
            # into the database or into an API response.
            self._mark_failed(job, "provider_error")
        else:
            self._repository.mark_completed(job.id)

    def _call_provider(self, job: ClaimedDeletionJob) -> None:
        if job.provider == SUPABASE_AUTH_PROVIDER:
            if self._supabase_provider is None:
                raise AccountDeletionProviderError("provider_unavailable")
            self._supabase_provider.delete_identity(job.user_id)
            return
        if job.provider == REVENUECAT_PROVIDER:
            if self._revenuecat_provider is None:
                raise AccountDeletionProviderError("provider_unavailable")
            self._revenuecat_provider.delete_customer(str(job.user_id))
            return
        raise AccountDeletionProviderError("unknown_provider")

    def _mark_failed(self, job: ClaimedDeletionJob, category: str) -> None:
        delay_seconds = min(
            self._settings.retry_max_seconds,
            self._settings.retry_base_seconds * (2 ** min(job.attempts - 1, 10)),
        )
        next_attempt_at = datetime.now(timezone.utc) + timedelta(
            seconds=delay_seconds
        )
        self._repository.mark_failed(
            job.id,
            error_category=category,
            next_attempt_at=next_attempt_at,
        )


def retry_pending_account_deletions(
    service: AccountDeletionService,
) -> AccountDeletionProviderSummary:
    """Explicit operator function used by the one-process retry command."""

    return service.retry_pending()
