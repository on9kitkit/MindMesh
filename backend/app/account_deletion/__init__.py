"""Backend-only account deletion and provider-cleanup boundary."""

from app.account_deletion.ports import (
    REVENUECAT_PROVIDER,
    SUPABASE_AUTH_PROVIDER,
    AccountDeletionProviderError,
    RevenueCatCustomerDeletionProvider,
    SupabaseAuthDeletionProvider,
)
from app.account_deletion.repository import (
    AccountDeletionLocalResult,
    PostgresAccountDeletionRepository,
)
from app.account_deletion.service import (
    AccountDeletionOperations,
    AccountDeletionService,
)
from app.account_deletion.settings import AccountDeletionSettings

__all__ = [
    "AccountDeletionLocalResult",
    "AccountDeletionOperations",
    "AccountDeletionProviderError",
    "AccountDeletionService",
    "AccountDeletionSettings",
    "PostgresAccountDeletionRepository",
    "REVENUECAT_PROVIDER",
    "RevenueCatCustomerDeletionProvider",
    "SUPABASE_AUTH_PROVIDER",
    "SupabaseAuthDeletionProvider",
]
