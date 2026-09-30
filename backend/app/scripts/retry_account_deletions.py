"""Explicit operator retry for account-deletion provider cleanup."""

from app.account_deletion import AccountDeletionService, AccountDeletionSettings
from app.account_deletion.providers import (
    AccountDeletionProviderConfiguration,
    build_deletion_providers,
)
from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.db.session import Database


def main() -> None:
    database = Database.from_environment()
    providers = build_deletion_providers(
        AccountDeletionProviderConfiguration.from_environment()
    )
    service = AccountDeletionService(
        PostgresAccountDeletionRepository(database.session_factory),
        supabase_provider=providers[0],
        revenuecat_provider=providers[1],
        settings=AccountDeletionSettings.from_environment(),
    )
    try:
        summary = service.retry_pending()
        print(f"processed account-deletion jobs: {summary.attempted_jobs}")
    finally:
        service.close()
        database.dispose()


if __name__ == "__main__":
    main()
