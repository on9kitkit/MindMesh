"""Offline contract checks for solo answer locking and participation rewards."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.learning_companions.contracts import (
    CompletionEvidence,
    CompletionSource,
    HomeZoneSelectionRequest,
    LockedSelfCheck,
    SelfCheckCriterion,
    SoloAnswerRequest,
    SoloCreateRequest,
    SoloSelfCheckRequest,
    calculate_reward_amounts,
    resolve_self_check,
    study_date_for,
)


def test_solo_create_uses_existing_six_subject_eighteen_topic_catalogue() -> None:
    request = SoloCreateRequest(
        request_id=uuid4(), subject="english_literature", topic="poetry_analysis", total_marks=40
    )
    assert (request.subject, request.topic, request.total_marks) == (
        "english_literature", "poetry_analysis", 40
    )
    with pytest.raises(ValidationError):
        SoloCreateRequest(
            request_id=uuid4(), subject="physics", topic="poetry_analysis", total_marks=20
        )
    with pytest.raises(ValidationError):
        SoloCreateRequest(
            request_id=uuid4(), subject="Physics", topic="energy", total_marks=20
        )
    with pytest.raises(ValidationError):
        SoloCreateRequest(
            request_id=uuid4(), subject="physics", topic="energy", total_marks=41
        )


def test_answer_requires_one_valid_locked_response() -> None:
    question_id = uuid4()
    assert SoloAnswerRequest(question_id=question_id, text="  my answer  ").text == "my answer"
    assert SoloAnswerRequest(question_id=question_id, selected_option_id="a").selected_option_id == "a"
    for payload in (
        {"question_id": question_id},
        {"question_id": question_id, "selected_option_id": "a", "text": "also text"},
        {"question_id": question_id, "text": "   "},
        {"question_id": question_id, "selected_option_id": "   "},
    ):
        with pytest.raises(ValidationError):
            SoloAnswerRequest.model_validate(payload)


def test_self_check_is_server_scored_from_saved_weights_and_accepts_zero() -> None:
    locked = LockedSelfCheck(
        question_id=uuid4(),
        locked_answer="The student answer is already accepted.",
        intended_answer="The reference answer appears after the lock.",
        max_marks=4,
        criteria=(
            SelfCheckCriterion("reason", 2, "Explains the reason", "Reasoning"),
            SelfCheckCriterion("example", 1, "Gives an example", "Example"),
            SelfCheckCriterion("unit", 1, "Uses the unit", "Unit"),
        ),
    )
    assert SoloSelfCheckRequest(selected_criterion_ids=[]).selected_criterion_ids == []
    assert resolve_self_check(locked, ()).earned_marks == 0
    awarded = resolve_self_check(locked, ("unit", "reason"))
    assert awarded.earned_marks == 3
    assert awarded.selected_criterion_ids == ("reason", "unit")
    with pytest.raises(ValueError, match="not in the saved rubric"):
        resolve_self_check(locked, ("not_a_criterion",))
    with pytest.raises(ValueError, match="unique"):
        resolve_self_check(locked, ("reason", "reason"))
    with pytest.raises(ValidationError):
        SoloSelfCheckRequest(selected_criterion_ids=["reason", "reason"])


def test_invalid_or_ai_size_self_check_rubric_is_rejected() -> None:
    invalid = LockedSelfCheck(
        question_id=uuid4(), locked_answer="x", intended_answer="y", max_marks=4,
        criteria=(SelfCheckCriterion("a", 1, "a", "a"),),
    )
    with pytest.raises(ValueError, match="rubric"):
        resolve_self_check(invalid, ("a",))
    ai_question = LockedSelfCheck(
        question_id=uuid4(), locked_answer="x", intended_answer="y", max_marks=5,
        criteria=(SelfCheckCriterion("a", 5, "a", "a"),),
    )
    with pytest.raises(ValueError, match="one- to four-mark"):
        resolve_self_check(ai_question, ("a",))


def test_receipt_evidence_requires_finished_full_coverage_and_original_answer_time() -> None:
    answer_at = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
    finish_at = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
    values = dict(
        user_id=uuid4(), source_kind=CompletionSource.SOLO, source_id=uuid4(),
        terminal_state="FINISHED", canonical_question_count=3,
        distinct_accepted_answer_count=3,
        latest_original_accepted_at_utc=answer_at,
        home_timezone_snapshot="Europe/London", home_zone_version=1,
        completed_at_utc=finish_at, completion_state_version=6,
    )
    assert CompletionEvidence(**values).study_date.isoformat() == "2026-03-29"
    with pytest.raises(ValueError, match="one accepted answer"):
        CompletionEvidence(**(values | {"distinct_accepted_answer_count": 2}))
    with pytest.raises(ValueError, match="finished"):
        CompletionEvidence(**(values | {"terminal_state": "AWAITING_MARKING"}))
    with pytest.raises(ValueError, match="postdate"):
        CompletionEvidence(**(values | {"completed_at_utc": datetime(2026, 3, 28, tzinfo=timezone.utc)}))
    with pytest.raises(ValueError, match="timezone-aware"):
        CompletionEvidence(**(values | {"latest_original_accepted_at_utc": answer_at.replace(tzinfo=None)}))


def test_study_day_uses_fixed_iana_zone_with_dst_and_rejects_unknown_zone() -> None:
    assert study_date_for(datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc), "Europe/London").isoformat() == "2026-03-29"
    assert study_date_for(datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc), "Europe/London").isoformat() == "2026-03-30"
    assert study_date_for(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), "Europe/London").isoformat() == "2026-10-25"
    assert HomeZoneSelectionRequest(home_timezone="Europe/London").home_timezone == "Europe/London"
    with pytest.raises(ValidationError):
        HomeZoneSelectionRequest(home_timezone="London-ish")


def test_day_cap_counts_bonus_and_quizzes_then_clips_fourth() -> None:
    amounts = [calculate_reward_amounts(prior_study_day_coins=0, first_qualification=True)]
    for _ in range(4):
        prior = sum(item.total for item in amounts)
        amounts.append(calculate_reward_amounts(prior_study_day_coins=prior, first_qualification=False))
    assert [(item.daily_bonus, item.quiz_coins) for item in amounts] == [
        (30, 20), (0, 20), (0, 20), (0, 10), (0, 0)
    ]
    assert sum(item.total for item in amounts) == 100
    with pytest.raises(ValueError):
        calculate_reward_amounts(prior_study_day_coins=50, first_qualification=True)
