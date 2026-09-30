from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from app.db.models.account_deletion_outbox import AccountDeletionOutboxModel
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.question import QuestionModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.safety_report import SafetyReportModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.models.user import UserModel
from app.db.session import Database
from app.retention import RetentionPolicy, RetentionService
from app.retention import repository as retention_repository
from app.retention.policy import MAX_ACCEPTED_JWT_LIFETIME_ENV
from app.retention.summary import RetentionCounts, RetentionMode, RetentionRunSummary
from app.scripts import purge_retained_data
from tests.conftest import OWNER_ID


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
OTHER_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
THIRD_USER_ID = UUID("33333333-3333-4333-8333-333333333333")


def _policy(limit: int = 100) -> RetentionPolicy:
    return RetentionPolicy(
        maximum_accepted_jwt_lifetime=timedelta(days=7),
        batch_limit=limit,
    )


def _ensure_user(
    database: Database,
    user_id: UUID,
    *,
    deleted_at: datetime | None = None,
) -> None:
    with database.session_factory() as session:
        with session.begin():
            user = session.get(UserModel, user_id)
            if user is None:
                session.add(
                    UserModel(
                        id=user_id,
                        display_name="Deleted user" if deleted_at else "Retention user",
                        created_at=NOW - timedelta(days=365),
                        updated_at=NOW - timedelta(days=365),
                        deleted_at=deleted_at,
                    )
                )
            else:
                user.deleted_at = deleted_at


def _insert_room(
    database: Database,
    *,
    closed_at: datetime,
    with_membership: bool = False,
) -> tuple[UUID, UUID | None]:
    room_id = uuid4()
    membership_id = uuid4() if with_membership else None
    created_at = closed_at - timedelta(days=1)
    with database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=OWNER_ID,
                    name="Retention room",
                    join_code=room_id.hex[:6].upper(),
                    maximum_members=8,
                    created_at=created_at,
                    closed_at=closed_at,
                )
            )
            session.flush()
            if membership_id is not None:
                session.add(
                    RoomMembershipModel(
                        id=membership_id,
                        room_id=room_id,
                        user_id=OWNER_ID,
                        joined_at=created_at,
                        left_at=closed_at,
                    )
                )
    return room_id, membership_id


def _insert_report(
    database: Database,
    *,
    room_id: UUID | None,
    status: str,
    resolved_at: datetime | None,
    created_at: datetime = NOW - timedelta(days=365),
) -> UUID:
    report_id = uuid4()
    with database.session_factory() as session:
        with session.begin():
            session.add(
                SafetyReportModel(
                    id=report_id,
                    reporter_user_id=OWNER_ID,
                    reported_user_id=OTHER_USER_ID,
                    room_id=room_id,
                    reported_display_name_snapshot="Sentinel report text",
                    reason="other_safety_concern",
                    details="Sentinel report details",
                    status=status,
                    created_at=created_at,
                    resolved_at=resolved_at,
                )
            )
    return report_id


def _insert_outbox(
    database: Database,
    *,
    user_id: UUID,
    provider: str,
    status: str,
    completed_at: datetime | None,
    claimed_at: datetime | None = None,
    last_error_category: str | None = None,
) -> UUID:
    outbox_id = uuid4()
    with database.session_factory() as session:
        with session.begin():
            session.add(
                AccountDeletionOutboxModel(
                    id=outbox_id,
                    user_id=user_id,
                    provider=provider,
                    status=status,
                    attempts=1,
                    next_attempt_at=NOW - timedelta(days=365),
                    created_at=NOW - timedelta(days=365),
                    updated_at=NOW - timedelta(days=365),
                    completed_at=completed_at,
                    claimed_at=claimed_at,
                    last_error_category=last_error_category,
                )
            )
    return outbox_id


def test_retention_boundaries_dry_run_and_execute_are_consistent(
    postgres_database: Database,
    postgres_user_repository: object,
) -> None:
    _ensure_user(postgres_database, OTHER_USER_ID)
    _ensure_user(postgres_database, THIRD_USER_ID)
    old_room, _ = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=30),
    )
    _insert_room(postgres_database, closed_at=NOW - timedelta(days=30) + timedelta(seconds=1))

    exact_report = _insert_report(
        postgres_database,
        room_id=None,
        status="RESOLVED",
        resolved_at=NOW - timedelta(days=90),
    )
    _insert_report(
        postgres_database,
        room_id=None,
        status="DISMISSED",
        resolved_at=NOW - timedelta(days=90) + timedelta(seconds=1),
    )
    _insert_report(
        postgres_database,
        room_id=None,
        status="OPEN",
        resolved_at=NOW - timedelta(days=365),
    )
    _insert_report(
        postgres_database,
        room_id=None,
        status="RESOLVED",
        resolved_at=None,
    )

    exact_outbox = _insert_outbox(
        postgres_database,
        user_id=OWNER_ID,
        provider="supabase_auth",
        status="completed",
        completed_at=NOW - timedelta(days=8),
    )
    _insert_outbox(
        postgres_database,
        user_id=OTHER_USER_ID,
        provider="supabase_auth",
        status="completed",
        completed_at=NOW - timedelta(days=8) + timedelta(seconds=1),
    )
    _insert_outbox(
        postgres_database,
        user_id=THIRD_USER_ID,
        provider="supabase_auth",
        status="pending",
        completed_at=None,
    )
    _insert_outbox(
        postgres_database,
        user_id=OWNER_ID,
        provider="revenuecat",
        status="failed",
        completed_at=NOW - timedelta(days=365),
        last_error_category="provider_unavailable",
    )
    _insert_outbox(
        postgres_database,
        user_id=OTHER_USER_ID,
        provider="revenuecat",
        status="in_progress",
        completed_at=None,
        claimed_at=NOW - timedelta(days=365),
    )
    _insert_outbox(
        postgres_database,
        user_id=THIRD_USER_ID,
        provider="revenuecat",
        status="completed",
        completed_at=NOW - timedelta(days=365),
        last_error_category="malformed_completed",
    )
    _insert_outbox(
        postgres_database,
        user_id=OTHER_USER_ID,
        provider="unknown_provider",
        status="completed",
        completed_at=None,
    )

    service = RetentionService(
        retention_repository.PostgresRetentionRepository(
            postgres_database.session_factory
        )
    )
    preview = service.preview(_policy(), as_of=NOW)
    assert preview.mode is RetentionMode.DRY_RUN
    assert preview.eligible.safety_reports == 1
    assert preview.eligible.closed_rooms == 1
    assert preview.eligible.deletion_outbox_rows == 1
    assert preview.deleted == RetentionCounts()

    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, old_room) is not None
        assert session.get(SafetyReportModel, exact_report) is not None
        assert session.get(AccountDeletionOutboxModel, exact_outbox) is not None

    purged = service.purge(_policy(), as_of=NOW)
    assert purged.mode is RetentionMode.EXECUTE_PURGE
    assert purged.eligible.safety_reports == preview.eligible.safety_reports
    assert purged.eligible.closed_rooms == preview.eligible.closed_rooms
    assert purged.eligible.deletion_outbox_rows == preview.eligible.deletion_outbox_rows
    assert purged.deleted.safety_reports == 1
    assert purged.deleted.closed_rooms == 1
    assert purged.deleted.deletion_outbox_rows == 1

    repeated = service.purge(_policy(), as_of=NOW)
    assert repeated.deleted == RetentionCounts()

    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, old_room) is None
        assert session.get(SafetyReportModel, exact_report) is None
        assert session.get(AccountDeletionOutboxModel, exact_outbox) is None


def test_terminal_report_and_room_graph_purge_preserves_retained_context_and_tombstones(
    postgres_database: Database,
    postgres_user_repository: object,
) -> None:
    del postgres_user_repository
    _ensure_user(postgres_database, OWNER_ID)
    _ensure_user(postgres_database, OTHER_USER_ID)
    tombstone_time = NOW - timedelta(days=200)
    _ensure_user(postgres_database, THIRD_USER_ID, deleted_at=tombstone_time)
    tombstone_outbox_id = _insert_outbox(
        postgres_database,
        user_id=THIRD_USER_ID,
        provider="supabase_auth",
        status="completed",
        completed_at=NOW - timedelta(days=365),
    )
    eligible_room, membership_id = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=31),
        with_membership=True,
    )
    open_room, open_membership_id = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=31),
        with_membership=True,
    )
    younger_report_room, younger_membership_id = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=31),
        with_membership=True,
    )
    _insert_report(
        postgres_database,
        room_id=eligible_room,
        status="RESOLVED",
        resolved_at=NOW - timedelta(days=91),
    )
    open_report = _insert_report(
        postgres_database,
        room_id=open_room,
        status="OPEN",
        resolved_at=None,
    )
    younger_report = _insert_report(
        postgres_database,
        room_id=younger_report_room,
        status="DISMISSED",
        resolved_at=NOW - timedelta(days=89),
    )

    question_id = uuid4()
    session_id = uuid4()
    session_question_id = uuid4()
    participant_id = uuid4()
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                QuestionModel(
                    id=question_id,
                    bank_key="retention-test",
                    stable_key="retention-question",
                    position=0,
                    prompt="Sentinel prompt",
                    options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    correct_option_id="a",
                    duration_seconds=30,
                    is_active=True,
                    created_at=NOW - timedelta(days=200),
                    updated_at=NOW - timedelta(days=200),
                )
            )
            session.flush()
            session.add(
                QuizSessionModel(
                    id=session_id,
                    room_id=eligible_room,
                    question_bank_key="retention-test",
                    status="FINISHED",
                    current_question_position=0,
                    state_version=2,
                    started_at=NOW - timedelta(days=32),
                    finished_at=NOW - timedelta(days=32) + timedelta(minutes=1),
                )
            )
            session.flush()
            session.add(
                SessionQuestionModel(
                    id=session_question_id,
                    session_id=session_id,
                    source_question_id=question_id,
                    position=0,
                    prompt_snapshot="Sentinel prompt",
                    options_snapshot=[
                        {"id": "a", "label": "A"},
                        {"id": "b", "label": "B"},
                    ],
                    correct_option_id="a",
                    duration_seconds=30,
                )
            )
            session.add(
                SessionParticipantModel(
                    id=participant_id,
                    session_id=session_id,
                    user_id=OWNER_ID,
                    room_membership_id=membership_id,
                    display_name_snapshot="Retention user",
                    created_at=NOW - timedelta(days=32),
                )
            )
            session.flush()
            session.add(
                AnswerSubmissionModel(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=session_question_id,
                    participant_id=participant_id,
                    selected_option_id="a",
                    submitted_at=NOW - timedelta(days=32),
                    response_time_ms=100,
                    is_correct=True,
                    points=100,
                )
            )

    service = RetentionService(
        retention_repository.PostgresRetentionRepository(
            postgres_database.session_factory
        )
    )
    summary = service.purge(_policy(), as_of=NOW)
    assert summary.deleted.closed_rooms == 1
    assert summary.deleted.deletion_outbox_rows == 1
    assert summary.eligible.protected_rooms == 0

    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, eligible_room) is None
        assert session.get(RoomMembershipModel, membership_id) is None
        assert session.get(QuizSessionModel, session_id) is None
        assert session.get(SessionQuestionModel, session_question_id) is None
        assert session.get(SessionParticipantModel, participant_id) is None
        assert session.scalar(
            select(AnswerSubmissionModel.id).where(
                AnswerSubmissionModel.session_id == session_id
            )
        ) is None
        assert session.get(QuestionModel, question_id) is not None
        assert session.get(UserModel, THIRD_USER_ID) is not None
        assert session.get(AccountDeletionOutboxModel, tombstone_outbox_id) is None
        assert session.get(RoomModel, open_room) is not None
        assert session.get(RoomMembershipModel, open_membership_id) is not None
        assert session.get(SafetyReportModel, open_report) is not None
        assert session.get(RoomModel, younger_report_room) is not None
        assert session.get(RoomMembershipModel, younger_membership_id) is not None
        assert session.get(SafetyReportModel, younger_report) is not None


def test_report_batch_limit_keeps_room_until_all_report_context_is_selected(
    postgres_database: Database,
    postgres_user_repository: object,
) -> None:
    del postgres_user_repository
    _ensure_user(postgres_database, OWNER_ID)
    _ensure_user(postgres_database, OTHER_USER_ID)
    room_id, _ = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=31),
    )
    oldest_report = _insert_report(
        postgres_database,
        room_id=room_id,
        status="RESOLVED",
        resolved_at=NOW - timedelta(days=100),
    )
    younger_report = _insert_report(
        postgres_database,
        room_id=room_id,
        status="DISMISSED",
        resolved_at=NOW - timedelta(days=99),
    )
    service = RetentionService(
        retention_repository.PostgresRetentionRepository(
            postgres_database.session_factory
        )
    )

    first = service.purge(_policy(limit=1), as_of=NOW)
    assert first.deleted.safety_reports == 1
    assert first.deleted.closed_rooms == 0
    assert first.eligible.closed_rooms == 0
    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, room_id) is not None
        assert session.get(SafetyReportModel, oldest_report) is None
        assert session.get(SafetyReportModel, younger_report) is not None

    second = service.purge(_policy(limit=1), as_of=NOW)
    assert second.deleted.safety_reports == 1
    assert second.deleted.closed_rooms == 1
    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, room_id) is None
        assert session.get(SafetyReportModel, younger_report) is None


def test_purge_rolls_back_all_categories_on_mid_operation_error(
    postgres_database: Database,
    postgres_user_repository: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del postgres_user_repository
    _ensure_user(postgres_database, OWNER_ID)
    _ensure_user(postgres_database, OTHER_USER_ID)
    room_id, _ = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=31),
    )
    report_id = _insert_report(
        postgres_database,
        room_id=None,
        status="RESOLVED",
        resolved_at=NOW - timedelta(days=91),
    )

    original_delete = retention_repository.delete

    def fail_on_room_delete(model: object) -> object:
        if model is RoomModel:
            raise RuntimeError("injected retention failure")
        return original_delete(model)

    monkeypatch.setattr(retention_repository, "delete", fail_on_room_delete)
    service = RetentionService(
        retention_repository.PostgresRetentionRepository(
            postgres_database.session_factory
        )
    )
    with pytest.raises(RuntimeError, match="injected retention failure"):
        service.purge(_policy(), as_of=NOW)

    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, room_id) is not None
        assert session.get(SafetyReportModel, report_id) is not None


def test_locked_room_blocks_concurrent_retained_report_insertion(
    postgres_database: Database,
    postgres_user_repository: object,
) -> None:
    del postgres_user_repository
    _ensure_user(postgres_database, OWNER_ID)
    _ensure_user(postgres_database, OTHER_USER_ID)
    room_id, _ = _insert_room(
        postgres_database,
        closed_at=NOW - timedelta(days=31),
    )
    policy = _policy()
    cutoffs = policy.cutoffs(NOW)

    first_session = postgres_database.session_factory()
    first_transaction = first_session.begin()
    try:
        selected_report_ids = list(
            first_session.scalars(
                retention_repository.build_eligible_safety_report_ids(
                    cutoffs,
                    policy,
                ).with_for_update(skip_locked=True)
            ).all()
        )
        selected_room_ids = list(
            first_session.scalars(
                retention_repository.build_eligible_closed_room_ids_for_ids(
                    cutoffs,
                    policy,
                    selected_report_ids=selected_report_ids,
                ).with_for_update(skip_locked=True)
            ).all()
        )
        assert selected_room_ids == [room_id]

        second_session = postgres_database.session_factory()
        try:
            with pytest.raises(OperationalError):
                with second_session.begin():
                    second_session.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    second_session.add(
                        SafetyReportModel(
                            id=uuid4(),
                            reporter_user_id=OWNER_ID,
                            reported_user_id=OTHER_USER_ID,
                            room_id=room_id,
                            reported_display_name_snapshot="Concurrent report",
                            reason="other_safety_concern",
                            status="OPEN",
                            created_at=NOW,
                        )
                    )
                    second_session.flush()
        finally:
            second_session.close()

        assert retention_repository.PostgresRetentionRepository._recheck_room_report_context(
            first_session,
            selected_room_ids,
            selected_report_ids,
        ) == (room_id,)
        first_session.execute(delete(RoomModel).where(RoomModel.id == room_id))
        first_transaction.commit()
    finally:
        if first_transaction.is_active:
            first_transaction.rollback()
        first_session.close()

    with postgres_database.session_factory() as session:
        assert session.get(RoomModel, room_id) is None


def test_retention_cli_rejects_limits_and_missing_jwt_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as limit_error:
        purge_retained_data.main(["--limit", "0"])
    assert limit_error.value.code == 2
    assert "between 1 and 100" in capsys.readouterr().err

    monkeypatch.delenv(MAX_ACCEPTED_JWT_LIFETIME_ENV, raising=False)
    with pytest.raises(SystemExit) as configuration_error:
        purge_retained_data.main([])
    assert configuration_error.value.code == 2
    stderr = capsys.readouterr().err
    assert MAX_ACCEPTED_JWT_LIFETIME_ENV in stderr
    assert "sentinel" not in stderr.lower()


def test_retention_cli_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(MAX_ACCEPTED_JWT_LIFETIME_ENV, "604800")

    class FakeDatabase:
        session_factory = object()

        def dispose(self) -> None:
            return None

    class FakeService:
        def __init__(self, repository: object) -> None:
            assert repository is not None

        def run(self, policy: object, *, execute: bool) -> RetentionRunSummary:
            assert execute is True
            return RetentionRunSummary(
                mode=RetentionMode.EXECUTE_PURGE,
                eligible=RetentionCounts(
                    safety_reports=2,
                    closed_rooms=1,
                    deletion_outbox_rows=3,
                    protected_rooms=1,
                ),
                deleted=RetentionCounts(
                    safety_reports=2,
                    closed_rooms=1,
                    deletion_outbox_rows=3,
                    protected_rooms=1,
                ),
            )

    monkeypatch.setattr(purge_retained_data.Database, "from_environment", lambda: FakeDatabase())
    monkeypatch.setattr(purge_retained_data, "RetentionService", FakeService)
    purge_retained_data.main(["--execute-purge"])
    output = capsys.readouterr().out
    assert "mode=execute-purge" in output
    assert "eligible_safety_reports=2" in output
    assert "deleted_closed_rooms=1" in output
    assert "Sentinel report text" not in output
    assert "Sentinel report details" not in output
    assert str(OWNER_ID) not in output
