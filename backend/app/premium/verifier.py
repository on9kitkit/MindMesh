from typing import Protocol
from uuid import UUID


class PremiumEntitlementVerifier(Protocol):
    """Read-only authority used before a server-owned premium operation."""

    def has_entitlement(
        self,
        customer_id: UUID,
        entitlement_lookup_key: str,
    ) -> bool:
        """Return whether the customer has the requested active entitlement."""

