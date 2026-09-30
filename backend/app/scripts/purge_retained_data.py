"""Explicit local operator entry point for bounded StudyRoom retention."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from app.db.session import Database, DatabaseConfigurationError
from app.retention import (
    DEFAULT_BATCH_LIMIT,
    RETENTION_MAX_BATCH_LIMIT,
    PostgresRetentionRepository,
    RetentionConfigurationError,
    RetentionPolicy,
    RetentionService,
)
from app.retention.summary import RetentionRunSummary


def _positive_bounded_limit(raw_value: str) -> int:
    try:
        value = int(raw_value, 10)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be a positive integer") from None
    if value < 1 or value > RETENTION_MAX_BATCH_LIMIT:
        raise argparse.ArgumentTypeError(
            f"limit must be between 1 and {RETENTION_MAX_BATCH_LIMIT}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview bounded StudyRoom retention; use --execute-purge only "
            "for an explicit destructive local operation."
        )
    )
    parser.add_argument(
        "--execute-purge",
        action="store_true",
        help="destructively delete one bounded eligible batch",
    )
    parser.add_argument(
        "--limit",
        type=_positive_bounded_limit,
        default=DEFAULT_BATCH_LIMIT,
        help=f"per-category batch limit (1-{RETENTION_MAX_BATCH_LIMIT})",
    )
    return parser


def _print_summary(summary: RetentionRunSummary) -> None:
    print(f"mode={summary.mode.value}")
    print(f"eligible_safety_reports={summary.eligible.safety_reports}")
    print(f"eligible_closed_rooms={summary.eligible.closed_rooms}")
    print(f"eligible_solo_attempts={summary.eligible.solo_attempts}")
    print(f"eligible_deletion_outbox_rows={summary.eligible.deletion_outbox_rows}")
    print(f"protected_rooms={summary.eligible.protected_rooms}")
    print(f"deleted_safety_reports={summary.deleted.safety_reports}")
    print(f"deleted_closed_rooms={summary.deleted.closed_rooms}")
    print(f"deleted_solo_attempts={summary.deleted.solo_attempts}")
    print(f"deleted_deletion_outbox_rows={summary.deleted.deletion_outbox_rows}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        policy = RetentionPolicy.from_environment(batch_limit=arguments.limit)
    except RetentionConfigurationError as error:
        parser.error(str(error))

    database: Database | None = None
    try:
        database = Database.from_environment()
        service = RetentionService(
            PostgresRetentionRepository(database.session_factory)
        )
        summary = service.run(policy, execute=arguments.execute_purge)
    except (DatabaseConfigurationError, RetentionConfigurationError):
        print(
            "Retention purge could not start because configuration is invalid.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except Exception:
        print(
            "Retention purge failed; no changes were committed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    finally:
        if database is not None:
            database.dispose()

    _print_summary(summary)


if __name__ == "__main__":
    main()
