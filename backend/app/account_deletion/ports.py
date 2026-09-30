from typing import Protocol
from uuid import UUID


SUPABASE_AUTH_PROVIDER = "supabase_auth"
REVENUECAT_PROVIDER = "revenuecat"
OUTBOX_PENDING = "pending"
OUTBOX_IN_PROGRESS = "in_progress"
OUTBOX_COMPLETED = "completed"


class SupabaseAuthDeletionProvider(Protocol):
    """The narrow server-side operation needed to remove Auth data."""

    def delete_identity(self, user_id: UUID) -> None:
        """Delete one Supabase Auth identity, or accept that it is absent."""


class RevenueCatCustomerDeletionProvider(Protocol):
    """The narrow server-side operation needed to remove one RC customer."""

    def delete_customer(self, customer_id: str) -> None:
        """Delete one RevenueCat customer, or accept that it is absent."""


class AccountDeletionProviderError(Exception):
    """Sanitized provider failure safe to retain as an outbox category."""

    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category
