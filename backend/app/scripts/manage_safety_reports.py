"""Local operator control for reviewing and closing safety reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import cast
from uuid import UUID

from app.db.session import Database
from app.services.safety_reports import (
    PostgresSafetyReportService,
    SafetyReportOperatorError,
    SafetyReportOperatorRecord,
    SafetyReportStatus,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review and close existing StudyRoom safety reports locally."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "list",
        help="list OPEN reports without free-text details",
    )

    show = commands.add_parser(
        "show",
        help="show one report without details by default",
    )
    show.add_argument("--report-id", required=True, type=UUID)
    show.add_argument(
        "--include-details",
        action="store_true",
        help="display the stored free-text details in the trusted terminal",
    )

    close = commands.add_parser(
        "close",
        help="close one OPEN report as RESOLVED or DISMISSED",
    )
    close.add_argument("--report-id", required=True, type=UUID)
    close.add_argument(
        "--status",
        required=True,
        choices=("RESOLVED", "DISMISSED"),
    )
    return parser


def _format_timestamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "-"


def _print_list_record(report: SafetyReportOperatorRecord) -> None:
    print(
        " ".join(
            (
                f"id={report.id}",
                f"status={report.status}",
                f"reason={report.reason}",
                f"created_at={_format_timestamp(report.created_at)}",
                f"reported_name={report.reported_display_name_snapshot!r}",
            )
        )
    )


def _print_detail_record(
    report: SafetyReportOperatorRecord,
    *,
    include_details: bool,
) -> None:
    print(f"id={report.id}")
    print(f"status={report.status}")
    print(f"reporter_user_id={report.reporter_user_id}")
    print(f"reported_user_id={report.reported_user_id}")
    print(f"room_id={report.room_id}")
    print(f"reported_name={report.reported_display_name_snapshot!r}")
    print(f"reason={report.reason}")
    print(f"created_at={_format_timestamp(report.created_at)}")
    print(f"resolved_at={_format_timestamp(report.resolved_at)}")
    if include_details:
        print(f"details={report.details!r}")


def _run(arguments: argparse.Namespace) -> None:
    database = Database.from_environment()
    try:
        service = PostgresSafetyReportService(database.session_factory)
        if arguments.command == "list":
            for report in service.list_open_reports():
                _print_list_record(report)
            return
        if arguments.command == "show":
            report = service.get_report(arguments.report_id)
            _print_detail_record(
                report,
                include_details=arguments.include_details,
            )
            return

        status = cast(SafetyReportStatus, arguments.status)
        report = service.close_report(
            report_id=arguments.report_id,
            status=status,
        )
        print(f"id={report.id} status={report.status}")
        return
    finally:
        database.dispose()


def main() -> None:
    arguments = _build_parser().parse_args()
    try:
        _run(arguments)
    except SafetyReportOperatorError:
        print("Safety report operation was not completed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
