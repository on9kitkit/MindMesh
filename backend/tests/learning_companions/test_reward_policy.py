"""Pure reward arithmetic, home-zone attribution, catalog, and streak checks."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.learning_companions.contracts import (
    CatalogKind,
    CompletionEvidence,
    CompletionSource,
    PET_CATALOG,
    STARTER_PET_IDS,
    calculate_reward_amounts,
    study_date_for,
)
from app.learning_companions.reward_policy import reconstruct_streak


@pytest.mark.parametrize(
    ("prior", "first", "bonus", "quiz", "day_total"),
    (
        (0, True, 30, 20, 50),
        (50, False, 0, 20, 70),
        (70, False, 0, 20, 90),
        (90, False, 0, 10, 100),
        (100, False, 0, 0, 100),
    ),
)
def test_approved_reward_sequence(prior, first, bonus, quiz, day_total):
    amounts = calculate_reward_amounts(
        prior_study_day_coins=prior, first_qualification=first
    )
    assert (amounts.daily_bonus, amounts.quiz_coins) == (bonus, quiz)
    assert prior + amounts.total == day_total


def test_reward_arithmetic_preserves_cap_for_every_prior_total():
    for prior in range(101):
        amounts = calculate_reward_amounts(
            prior_study_day_coins=prior, first_qualification=False
        )
        assert amounts.daily_bonus == 0
        assert 0 <= amounts.quiz_coins <= 20
        assert prior + amounts.total <= 100

    for invalid_prior in (-1, 101):
        with pytest.raises(ValueError):
            calculate_reward_amounts(
                prior_study_day_coins=invalid_prior, first_qualification=False
            )
    with pytest.raises(ValueError):
        calculate_reward_amounts(
            prior_study_day_coins=1, first_qualification=True
        )


def test_latest_original_answer_attributes_delayed_completion_to_home_day():
    accepted_at = datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc)
    evidence = CompletionEvidence(
        user_id=UUID(int=1),
        source_kind=CompletionSource.SOLO,
        source_id=UUID(int=2),
        terminal_state="FINISHED",
        canonical_question_count=5,
        distinct_accepted_answer_count=5,
        latest_original_accepted_at_utc=accepted_at,
        home_timezone_snapshot="Europe/London",
        home_zone_version=1,
        completed_at_utc=datetime(2026, 4, 3, 12, tzinfo=timezone.utc),
        completion_state_version=7,
    )

    # London has entered daylight saving time: 23:30 UTC is the next day.
    assert evidence.study_date == date(2026, 3, 30)
    assert study_date_for(accepted_at, "America/Los_Angeles") == date(2026, 3, 29)


@pytest.mark.parametrize("accepted_count", (0, 4, 6))
def test_completion_evidence_rejects_missing_or_inconsistent_answer_coverage(
    accepted_count,
):
    with pytest.raises(ValueError, match="one accepted answer for every question"):
        CompletionEvidence(
            user_id=UUID(int=1),
            source_kind=CompletionSource.ROOM,
            source_id=UUID(int=2),
            terminal_state="FINISHED",
            canonical_question_count=5,
            distinct_accepted_answer_count=accepted_count,
            latest_original_accepted_at_utc=datetime(
                2026, 9, 27, 12, tzinfo=timezone.utc
            ),
            home_timezone_snapshot="Europe/London",
            home_zone_version=1,
            completed_at_utc=datetime(2026, 9, 27, 13, tzinfo=timezone.utc),
            completion_state_version=2,
        )


def test_home_day_uses_iana_dst_not_a_fixed_utc_offset():
    before_spring = datetime(2026, 3, 28, 23, 30, tzinfo=timezone.utc)
    after_spring = datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc)
    assert study_date_for(before_spring, "Europe/London") == date(2026, 3, 28)
    assert study_date_for(after_spring, "Europe/London") == date(2026, 3, 30)

    # Both repeated local 01:30 times on the autumn change remain one day.
    before_fall = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    after_fall = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    assert study_date_for(before_fall, "Europe/London") == date(2026, 10, 25)
    assert study_date_for(after_fall, "Europe/London") == date(2026, 10, 25)


def test_catalog_is_finite_earned_only_and_has_approved_prices():
    assert STARTER_PET_IDS == {"pet.owl", "pet.tortoise", "pet.fox"}
    assert {item_id: item.coin_price for item_id, item in PET_CATALOG.items()} == {
        "pet.owl": 120,
        "pet.tortoise": 120,
        "pet.fox": 120,
        "cosmetic.study_scarf": 40,
        "animation.earned_celebration": 80,
    }
    assert all(PET_CATALOG[item_id].kind is CatalogKind.PET for item_id in STARTER_PET_IDS)
    assert PET_CATALOG["cosmetic.study_scarf"].kind is CatalogKind.COSMETIC
    assert PET_CATALOG["animation.earned_celebration"].kind is CatalogKind.ANIMATION
    assert "animation.pro_flourish" not in PET_CATALOG


def test_streak_shows_yesterday_until_today_is_done_then_breaks_after_missed_day():
    days = (date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1))
    due_today = reconstruct_streak(reversed(days), today=date(2027, 1, 2))
    assert (due_today.active_days, due_today.best_days) == (3, 3)
    assert due_today.last_qualified_day == date(2027, 1, 1)
    assert due_today.qualified_today is False

    completed_today = reconstruct_streak((*days, date(2027, 1, 2)), today=date(2027, 1, 2))
    assert (completed_today.active_days, completed_today.best_days) == (4, 4)
    assert completed_today.qualified_today is True

    missed_day = reconstruct_streak(days, today=date(2027, 1, 3))
    assert (missed_day.active_days, missed_day.best_days) == (0, 3)


def test_late_study_day_repairs_a_gap_in_a_leap_year():
    today = date(2024, 3, 1)
    without_leap_day = reconstruct_streak(
        (date(2024, 2, 28), today), today=today
    )
    assert (without_leap_day.active_days, without_leap_day.best_days) == (1, 1)

    with_leap_day = reconstruct_streak(
        (today, date(2024, 2, 29), date(2024, 2, 28)), today=today
    )
    assert (with_leap_day.active_days, with_leap_day.best_days) == (3, 3)


def test_streak_is_order_and_duplicate_independent_for_all_eight_day_patterns():
    first_day = date(2026, 9, 20)
    today = first_day + timedelta(days=7)
    for mask in range(1 << 8):
        days = tuple(
            first_day + timedelta(days=offset)
            for offset in range(8)
            if mask & (1 << offset)
        )
        expected = reconstruct_streak(days, today=today)
        assert reconstruct_streak((*reversed(days), *days), today=today) == expected
        assert 0 <= expected.active_days <= expected.best_days <= len(days)
        assert expected.qualified_today == (today in days)
        for offset in range(8):
            added = first_day + timedelta(days=offset)
            enlarged = reconstruct_streak((*days, added), today=today)
            assert enlarged.best_days >= expected.best_days


def test_as_of_view_excludes_future_days_and_handles_first_date():
    first = reconstruct_streak((date.min,), today=date.min)
    assert (first.active_days, first.best_days, first.qualified_today) == (1, 1, True)
    empty = reconstruct_streak((date(2026, 9, 28),), today=date(2026, 9, 27))
    assert (empty.active_days, empty.best_days, empty.last_qualified_day) == (0, 0, None)
