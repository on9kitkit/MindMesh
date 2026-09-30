"""Deliberate local operator control for one StudyRoom profile."""

from __future__ import annotations

import argparse
from uuid import UUID

from app.db.session import Database
from app.domain.errors import AccountDeletedError, UserNotFoundError
from app.repositories.postgres_users import PostgresUserRepository


_REASON_CODES = ("safety_review", "abuse_prevention", "policy_violation")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suspend or unsuspend one existing StudyRoom profile."
    )
    parser.add_argument("--user-id", required=True, type=UUID)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--suspend", action="store_true")
    action.add_argument("--unsuspend", action="store_true")
    parser.add_argument("--reason", choices=_REASON_CODES)
    arguments = parser.parse_args()
    if arguments.suspend and arguments.reason is None:
        parser.error("--reason is required with --suspend")
    if arguments.unsuspend and arguments.reason is not None:
        parser.error("--reason is only valid with --suspend")

    database = Database.from_environment()
    try:
        repository = PostgresUserRepository(database.session_factory)
        if arguments.suspend:
            repository.suspend(arguments.user_id, arguments.reason)
            print("StudyRoom account suspended.")
        else:
            repository.unsuspend(arguments.user_id)
            print("StudyRoom account unsuspended.")
    except (AccountDeletedError, UserNotFoundError, ValueError):
        print("StudyRoom account suspension operation was not completed.")
        raise SystemExit(1) from None
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
