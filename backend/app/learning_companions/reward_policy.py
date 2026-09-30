"""Pure streak reconstruction from server-owned qualifying study dates.

The completion contract owns reward amounts, date attribution, and catalog
prices. This module derives displayable streak lengths from posted study-day
evidence without trusting completion arrival order or a mutable counter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class StreakSnapshot:
    """Consecutive-day summary as of one home-zone calendar date."""

    active_days: int
    best_days: int
    last_qualified_day: date | None
    qualified_today: bool


def reconstruct_streak(
    qualified_dates: Iterable[date], *, today: date
) -> StreakSnapshot:
    """Rebuild a streak after any order of delayed qualifying-day postings.

    A run ending yesterday remains active while today's study is still due.
    Older runs are historical; future dates do not affect an as-of view.
    Duplicate dates never lengthen a run.
    """

    eligible_dates = sorted(day for day in set(qualified_dates) if day <= today)
    yesterday = today - timedelta(days=1) if today > date.min else None
    active_days = 0
    best_days = 0
    run_days = 0
    previous_day: date | None = None

    for day in eligible_dates:
        if previous_day is not None and day - previous_day == timedelta(days=1):
            run_days += 1
        else:
            run_days = 1
        best_days = max(best_days, run_days)
        if day == today or day == yesterday:
            active_days = run_days
        previous_day = day

    return StreakSnapshot(
        active_days=active_days,
        best_days=best_days,
        last_qualified_day=previous_day,
        qualified_today=previous_day == today,
    )
