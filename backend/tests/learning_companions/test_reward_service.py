"""Offline checks for one-time home zone and first daily invitation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.dependencies import get_current_user
from app.api.learning_companions import get_reward_service, router
from app.learning_companions.contracts import CompletionSource, ReceiptStatus
from app.learning_companions.models import LearningSettingsModel
from app.learning_companions.reward_service import (
    DailyInvitation,
    HomeZoneAlreadySet,
    HomeZoneRequired,
    RewardSourceInconsistent,
    RewardSourceNotFound,
    RewardSourceStatus,
    RewardService,
    StaleDailyInvitation,
)


USER_ID = uuid4()
USER = SimpleNamespace(id=USER_ID, deleted_at=None, suspended_at=None)
NOW = datetime(2026, 3, 28, 23, 30, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self, *scalars, gets=(), row_groups=()):
        self.results = list(scalars)
        self.get_results = list(gets)
        self.row_groups = list(row_groups)
        self.added: list[object] = []
        self.statements: list[object] = []

    def scalar(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    def get(self, _model, _key):
        return self.get_results.pop(0)

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: list(self.row_groups.pop(0)))

    def add(self, row):
        self.added.append(row)


class FakeFactory:
    def __init__(self, *sessions):
        self.sessions = list(sessions)

    @contextmanager
    def begin(self):
        yield self.sessions.pop(0)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(
        "app.learning_companions.reward_service._database_now", lambda _session: NOW
    )


def test_home_zone_selected_once_and_identical_retry_is_idempotent() -> None:
    create = FakeSession(USER, None)
    chosen = RewardService(FakeFactory(create)).select_home_zone(USER_ID, "Europe/London")
    assert chosen.home_zone_version == 1
    settings = next(row for row in create.added if isinstance(row, LearningSettingsModel))
    assert settings.zone_selected_at == NOW
    retry = FakeSession(USER, settings)
    assert RewardService(FakeFactory(retry)).select_home_zone(
        USER_ID, "Europe/London"
    ) == chosen
    assert retry.added == []
    change = FakeSession(USER, settings)
    with pytest.raises(HomeZoneAlreadySet):
        RewardService(FakeFactory(change)).select_home_zone(USER_ID, "America/New_York")


def _settings() -> LearningSettingsModel:
    return LearningSettingsModel(
        user_id=USER_ID,
        home_timezone="Europe/London",
        home_zone_version=1,
        zone_selected_at=NOW,
        updated_at=NOW,
    )


def test_crash_before_ack_reoffers_and_ack_suppresses_future_offer() -> None:
    settings = _settings()
    first = FakeSession(USER, settings, None)
    invitation = RewardService(FakeFactory(first)).claim_daily_invitation(USER_ID)
    assert invitation.should_open and invitation.reason == "first_entry"
    assert invitation.study_date == date(2026, 3, 28)
    assert settings.last_invited_study_date is None

    # Home can unmount before onShow; a second device gets the same offer.
    crash_retry = FakeSession(USER, settings, None)
    retry = RewardService(FakeFactory(crash_retry)).claim_daily_invitation(USER_ID)
    assert retry == invitation
    assert settings.last_invited_study_date is None

    acknowledge = FakeSession(USER, settings, None)
    ack = RewardService(FakeFactory(acknowledge)).acknowledge_daily_invitation(
        USER_ID, invitation.study_date
    )
    assert not ack.should_open and ack.reason == "already_invited"
    assert settings.last_invited_study_date == invitation.study_date
    after_ack = FakeSession(USER, settings, None)
    assert RewardService(FakeFactory(after_ack)).claim_daily_invitation(
        USER_ID
    ).reason == "already_invited"
    repeated_ack = FakeSession(USER, settings, None)
    assert RewardService(FakeFactory(repeated_ack)).acknowledge_daily_invitation(
        USER_ID, invitation.study_date
    ) == ack


def test_dismissal_is_separate_and_takes_precedence() -> None:
    settings = _settings()
    offered_day = date(2026, 3, 28)
    dismissed = RewardService(FakeFactory(FakeSession(USER, settings))).dismiss_daily_invitation(
        USER_ID, offered_day
    )
    assert dismissed.reason == "dismissed" and not dismissed.should_open
    assert settings.last_dismissed_study_date == offered_day
    assert settings.last_invited_study_date is None
    # Dismissal wins even if another device acknowledges or the day qualifies.
    assert RewardService(FakeFactory(FakeSession(USER, settings))).claim_daily_invitation(
        USER_ID
    ).reason == "dismissed"
    assert RewardService(FakeFactory(FakeSession(USER, settings))).acknowledge_daily_invitation(
        USER_ID, offered_day
    ).reason == "dismissed"

    presented_then_dismissed = _settings()
    RewardService(
        FakeFactory(FakeSession(USER, presented_then_dismissed, None))
    ).acknowledge_daily_invitation(USER_ID, offered_day)
    RewardService(
        FakeFactory(FakeSession(USER, presented_then_dismissed))
    ).dismiss_daily_invitation(USER_ID, offered_day)
    assert RewardService(
        FakeFactory(FakeSession(USER, presented_then_dismissed))
    ).claim_daily_invitation(USER_ID).reason == "dismissed"


def test_qualification_suppresses_offer_without_recording_presentation() -> None:
    settings = _settings()
    qualified = FakeSession(USER, settings, USER_ID)
    result = RewardService(FakeFactory(qualified)).claim_daily_invitation(USER_ID)
    assert result.reason == "already_qualified" and not result.should_open
    acknowledged = FakeSession(USER, settings, USER_ID)
    assert RewardService(FakeFactory(acknowledged)).acknowledge_daily_invitation(
        USER_ID, result.study_date
    ).reason == "already_qualified"
    assert settings.last_invited_study_date is None


def test_stale_modal_cannot_acknowledge_or_dismiss_new_day(monkeypatch) -> None:
    settings = _settings()
    old_offer = date(2026, 3, 28)
    monkeypatch.setattr(
        "app.learning_companions.reward_service._database_now",
        lambda _session: datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
    )
    with pytest.raises(StaleDailyInvitation):
        RewardService(FakeFactory(FakeSession(USER, settings))).acknowledge_daily_invitation(
            USER_ID, old_offer
        )
    with pytest.raises(StaleDailyInvitation):
        RewardService(FakeFactory(FakeSession(USER, settings))).dismiss_daily_invitation(
            USER_ID, old_offer
        )
    assert settings.last_invited_study_date is None
    assert settings.last_dismissed_study_date is None
    current = FakeSession(USER, settings, None)
    new_offer = RewardService(FakeFactory(current)).claim_daily_invitation(USER_ID)
    assert new_offer.study_date == date(2026, 3, 29)
    assert new_offer.should_open


def test_daily_entry_requires_saved_zone() -> None:
    with pytest.raises(HomeZoneRequired):
        RewardService(FakeFactory(FakeSession(USER, None))).claim_daily_invitation(USER_ID)


def test_invitation_acknowledge_and_dismiss_require_offered_day() -> None:
    offered_day = date(2026, 3, 28)

    class StubRewardService:
        def acknowledge_daily_invitation(self, user_id, study_date):
            assert (user_id, study_date) == (USER_ID, offered_day)
            return DailyInvitation(study_date, False, "already_invited")

        def dismiss_daily_invitation(self, user_id, study_date):
            assert (user_id, study_date) == (USER_ID, offered_day)
            return DailyInvitation(study_date, False, "dismissed")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER_ID)
    app.dependency_overrides[get_reward_service] = StubRewardService
    client = TestClient(app)
    assert client.post("/me/daily-invitation/acknowledge").status_code == 422
    acknowledged = client.post(
        "/me/daily-invitation/acknowledge", json={"study_date": offered_day.isoformat()}
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["reason"] == "already_invited"
    dismissed = client.post(
        "/me/daily-invitation/dismiss", json={"study_date": offered_day.isoformat()}
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["reason"] == "dismissed"


@pytest.mark.parametrize(
    ("receipt_state", "expected"),
    [
        (ReceiptStatus.PENDING, "reward_pending"),
        (ReceiptStatus.LEASED, "reward_pending"),
        (ReceiptStatus.RETRY_WAIT, "reward_pending"),
        (ReceiptStatus.BLOCKED, "reward_delayed"),
        (ReceiptStatus.POSTED, "credited"),
    ],
)
@pytest.mark.parametrize("source_kind", (CompletionSource.SOLO, CompletionSource.ROOM))
def test_receipt_is_authoritative_after_source_purge(
    receipt_state, expected, source_kind
) -> None:
    source_id = uuid4()
    receipt = SimpleNamespace(status=receipt_state.value, posting_order=5)
    session = FakeSession(USER, receipt)
    status = RewardService(FakeFactory(session)).get_source_status(
        USER_ID, source_kind, source_id
    )
    assert status.status == expected
    assert status.source_id == source_id
    assert session.get_results == [] and session.row_groups == []
    assert session.results == []  # No source or ledger lookup, including capped zero.
    sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "learning_completion_receipts.user_id =" in sql
    assert "learning_completion_receipts.source_kind =" in sql
    assert "learning_completion_receipts.source_id =" in sql


def test_solo_awaiting_marking_and_unanswered_finish_do_not_earn() -> None:
    source_id = uuid4()
    awaiting = FakeSession(USER, None, SimpleNamespace(status="AWAITING_MARKING"), None)
    assert RewardService(FakeFactory(awaiting)).get_source_status(
        USER_ID, CompletionSource.SOLO, source_id
    ).status == "awaiting_marking"

    question_id = uuid4()
    unfinished_coverage = FakeSession(
        USER,
        None,
        SimpleNamespace(status="FINISHED", terminal_at=NOW),
        None,
        row_groups=((question_id,), ()),
    )
    assert RewardService(FakeFactory(unfinished_coverage)).get_source_status(
        USER_ID, CompletionSource.SOLO, source_id
    ).status == "not_eligible"


def test_solo_finished_full_coverage_without_receipt_is_not_falsely_pending() -> None:
    source_id = uuid4()
    question_id = uuid4()
    attempt = SimpleNamespace(status="FINISHED", terminal_at=NOW)
    missing = FakeSession(
        USER, None, attempt, None, row_groups=((question_id,), (question_id,))
    )
    with pytest.raises(RewardSourceInconsistent):
        RewardService(FakeFactory(missing)).get_source_status(
            USER_ID, CompletionSource.SOLO, source_id
        )

    posted = SimpleNamespace(status=ReceiptStatus.POSTED.value)
    committed_during_read = FakeSession(
        USER, None, attempt, posted, row_groups=((question_id,), (question_id,))
    )
    assert RewardService(FakeFactory(committed_during_read)).get_source_status(
        USER_ID, CompletionSource.SOLO, source_id
    ).status == "credited"


def test_unknown_or_other_owner_source_is_opaque_not_found() -> None:
    source_id = uuid4()
    session = FakeSession(USER, None, None)
    with pytest.raises(RewardSourceNotFound):
        RewardService(FakeFactory(session)).get_source_status(
            USER_ID, CompletionSource.SOLO, source_id
        )
    owner_sql = str(session.statements[2].compile(dialect=postgresql.dialect()))
    assert "solo_attempts.owner_id =" in owner_sql


def test_room_enrollment_and_owner_marking_control_fallback() -> None:
    source_id = uuid4()
    participant = SimpleNamespace(id=uuid4())
    finished = SimpleNamespace(status="FINISHED", finished_at=NOW)
    historical = FakeSession(
        USER, None, participant, None, gets=(finished, None)
    )
    assert RewardService(FakeFactory(historical)).get_source_status(
        USER_ID, CompletionSource.ROOM, source_id
    ).status == "not_eligible"

    enrollment = SimpleNamespace(user_id=USER_ID)
    grading = SimpleNamespace(status="QUESTION_GRADING")
    pending = FakeSession(
        USER, None, participant, uuid4(), None, gets=(grading, enrollment)
    )
    assert RewardService(FakeFactory(pending)).get_source_status(
        USER_ID, CompletionSource.ROOM, source_id
    ).status == "awaiting_marking"
    pending_sql = str(pending.statements[3].compile(dialect=postgresql.dialect()))
    assert "answer_submissions.participant_id =" in pending_sql


def test_room_finished_coverage_without_receipt_is_consistency_error() -> None:
    source_id = uuid4()
    question_id = uuid4()
    participant = SimpleNamespace(id=uuid4())
    quiz = SimpleNamespace(status="FINISHED", finished_at=NOW)
    enrollment = SimpleNamespace(user_id=USER_ID)
    missing = FakeSession(
        USER, None, participant, None,
        gets=(quiz, enrollment),
        row_groups=((question_id,), (question_id,)),
    )
    with pytest.raises(RewardSourceInconsistent):
        RewardService(FakeFactory(missing)).get_source_status(
            USER_ID, CompletionSource.ROOM, source_id
        )


def test_source_status_http_contract_has_only_owner_status_and_no_store() -> None:
    source_id = uuid4()

    class StubRewardService:
        def get_source_status(self, user_id, source_kind, requested_id):
            assert (user_id, source_kind, requested_id) == (
                USER_ID, CompletionSource.SOLO, source_id
            )
            return RewardSourceStatus(source_kind, requested_id, "credited")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER_ID)
    app.dependency_overrides[get_reward_service] = StubRewardService
    response = TestClient(app).get(f"/me/rewards/sources/solo/{source_id}")
    assert response.status_code == 200
    assert response.json() == {
        "source_kind": "solo", "source_id": str(source_id), "status": "credited"
    }
    assert response.headers["Cache-Control"] == "no-store"
