"""PostgreSQL authority checks for solo attempts on an isolated migrated test DB.

These tests intentionally use the shared postgres_database fixture. Its target
guard and table cleanup must admit only the manager's disposable 0012 database.
No generator, grader, provider, or live account is involved.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from time import sleep
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.db.models.user import UserModel
from app.db.session import Database
from app.learning_companions.contracts import SoloCreateRequest, study_date_for
from app.learning_companions.models import (
    CompletionReceiptModel,
    LearningSettingsModel,
    SoloAnswerModel,
    SoloAttemptModel,
    SoloQuestionModel,
)
from app.learning_companions.solo_domain import SoloError
from app.learning_companions.solo_repository import PostgresSoloRepository
from app.repositories.postgres_users import PostgresUserRepository


ZONE = "Europe/London"
OPTIONS = [
    {"id": "newton", "label": "Newton"},
    {"id": "joule", "label": "Joule"},
]


def _owner(database: Database) -> UUID:
    user_id = uuid4()
    PostgresUserRepository(database.session_factory).upsert_profile(user_id, "Solo Tester")
    with database.session_factory() as session, session.begin():
        session.add(LearningSettingsModel(user_id=user_id, home_timezone=ZONE))
    return user_id


def _attempt(
    owner_id: UUID,
    *,
    status: str = "PREPARING",
    topic: str = "forces",
    total_marks: int = 5,
    terminal_at: datetime | None = None,
    created_at: datetime | None = None,
) -> SoloAttemptModel:
    return SoloAttemptModel(
        id=uuid4(), owner_id=owner_id, request_id=uuid4(), status=status,
        state_version=1, education_level="GCSE", subject="physics", topic=topic,
        total_marks=total_marks, current_question_position=0,
        home_timezone_snapshot=ZONE, home_zone_version=1, reward_rule_version=1,
        created_at=created_at or datetime.now(timezone.utc),
        terminal_at=terminal_at,
    )


def _assert_constraint(database: Database, row: SoloAttemptModel, name: str) -> None:
    with pytest.raises(IntegrityError) as failure:
        with database.session_factory() as session, session.begin():
            session.add(row)
            session.flush()
    assert failure.value.orig.diag.constraint_name == name


def _started_quiz(database: Database, owner_id: UUID) -> tuple[UUID, tuple[UUID, ...]]:
    """Seed a canonical, provider-free five-MCQ attempt for transaction tests."""
    now = datetime.now(timezone.utc)
    started = _attempt(owner_id, status="IN_PROGRESS")
    started.started_at = now
    ids = tuple(uuid4() for _ in range(5))
    with database.session_factory() as session, session.begin():
        session.add(started)
        session.flush()
        for position, question_id in enumerate(ids):
            session.add(SoloQuestionModel(
                id=question_id, attempt_id=started.id, position=position,
                question_type="MULTIPLE_CHOICE", max_marks=1,
                prompt_snapshot=f"Choose the unit of force ({position}).",
                options_snapshot=OPTIONS, correct_option_id="newton",
                grading_rubric_snapshot={}, worked_explanation_snapshot="Newton.",
                original_extract=None, content_fingerprint=f"{position + 1:064x}",
            ))
    return started.id, ids


def _finish_quiz(database: Database, owner_id: UUID) -> tuple[UUID, tuple[UUID, ...]]:
    attempt_id, question_ids = _started_quiz(database, owner_id)
    repository = PostgresSoloRepository(database.session_factory)
    for question_id in question_ids:
        repository.submit_answer(owner_id, attempt_id, question_id, "newton", None)
    assert repository.get_state(owner_id, attempt_id).status == "FINISHED"
    return attempt_id, question_ids


def test_0012_solo_checks_and_one_active_owner_index_are_enforced(
    postgres_database: Database,
) -> None:
    owner_id = _owner(postgres_database)
    with postgres_database.session_factory() as session, session.begin():
        session.add(_attempt(owner_id))

    _assert_constraint(
        postgres_database, _attempt(owner_id, status="PREPARING"),
        "uq_solo_attempts_active_owner",
    )
    finished_at = datetime.now(timezone.utc)
    _assert_constraint(
        postgres_database,
        _attempt(owner_id, status="FAILED", topic="algebra", terminal_at=finished_at),
        "ck_solo_attempts_subject_topic",
    )
    _assert_constraint(
        postgres_database,
        _attempt(owner_id, status="FAILED", total_marks=4, terminal_at=finished_at),
        "ck_solo_attempts_total_marks",
    )
    _assert_constraint(
        postgres_database, _attempt(owner_id, status="FINISHED"),
        "ck_solo_attempts_terminal_at",
    )


def test_same_request_conflicting_create_serializes_on_user_lock(
    postgres_database: Database,
) -> None:
    owner_id = _owner(postgres_database)
    request_id = uuid4()
    repository = PostgresSoloRepository(postgres_database.session_factory)
    barrier = Barrier(3)

    def claim(topic: str) -> tuple[str, UUID | str]:
        barrier.wait(timeout=10)
        try:
            result = repository.claim_or_create(
                owner_id,
                SoloCreateRequest(request_id=request_id, subject="physics", topic=topic, total_marks=5),
                model_id="offline-test", lease_seconds=30,
            )
            return "created", result.attempt.id
        except SoloError as error:
            return "rejected", error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        with postgres_database.session_factory() as locking_session, locking_session.begin():
            assert locking_session.scalar(select(UserModel).where(
                UserModel.id == owner_id
            ).with_for_update()) is not None
            first = executor.submit(claim, "forces")
            second = executor.submit(claim, "energy")
            barrier.wait(timeout=10)
            sleep(0.05)  # Both callers contend while the owner row remains locked.
            assert not first.done() and not second.done()
        outcomes = [first.result(timeout=10), second.result(timeout=10)]

    assert sorted(kind for kind, _ in outcomes) == ["created", "rejected"]
    assert next(value for kind, value in outcomes if kind == "rejected") == "solo_conflict"
    with postgres_database.session_factory() as session:
        attempts = tuple(session.scalars(select(SoloAttemptModel).where(
            SoloAttemptModel.owner_id == owner_id
        )))
        assert len(attempts) == 1
        assert attempts[0].request_id == request_id
        assert attempts[0].id == next(value for kind, value in outcomes if kind == "created")

    same = repository.claim_or_create(
        owner_id,
        SoloCreateRequest(
            request_id=request_id, subject="physics", topic=attempts[0].topic, total_marks=5,
        ),
        model_id="offline-test", lease_seconds=30,
    )
    assert same.attempt.id == attempts[0].id
    assert same.claimed is False


def test_terminal_answer_and_receipt_commit_or_roll_back_together(
    postgres_database: Database,
) -> None:
    owner_id = _owner(postgres_database)
    attempt_id, question_ids = _started_quiz(postgres_database, owner_id)
    repository = PostgresSoloRepository(postgres_database.session_factory)
    for question_id in question_ids[:-1]:
        repository.submit_answer(owner_id, attempt_id, question_id, "newton", None)
    with postgres_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CompletionReceiptModel).where(
            CompletionReceiptModel.source_id == attempt_id
        )) == 0

    # An existing source receipt forces the fifth-answer transaction to fail.
    # The attempted terminal update and answer must roll back with that insert.
    now = datetime.now(timezone.utc)
    duplicate_id = uuid4()
    with postgres_database.session_factory() as session, session.begin():
        session.add(CompletionReceiptModel(
            id=duplicate_id, user_id=owner_id, source_kind="solo", source_id=attempt_id,
            terminal_state="FINISHED", canonical_question_count=5,
            accepted_answer_count=5, latest_accepted_at=now,
            home_timezone_snapshot=ZONE, home_zone_version=1,
            study_date=study_date_for(now, ZONE), completed_at=now,
            completion_state_version=9, reward_rule_version=1, status="pending",
        ))
    with pytest.raises(IntegrityError) as failure:
        repository.submit_answer(owner_id, attempt_id, question_ids[-1], "newton", None)
    assert failure.value.orig.diag.constraint_name == "uq_learning_receipts_source"
    with postgres_database.session_factory() as session:
        saved = session.get(SoloAttemptModel, attempt_id)
        assert saved is not None and saved.status == "IN_PROGRESS"
        assert saved.current_question_position == 4 and saved.terminal_at is None
        assert session.scalar(select(func.count()).select_from(SoloAnswerModel).where(
            SoloAnswerModel.attempt_id == attempt_id
        )) == 4

    with postgres_database.session_factory() as session, session.begin():
        session.execute(delete(CompletionReceiptModel).where(CompletionReceiptModel.id == duplicate_id))
    accepted = repository.submit_answer(owner_id, attempt_id, question_ids[-1], "newton", None)
    finished = repository.get_state(owner_id, attempt_id)
    assert finished.status == "FINISHED" and finished.terminal_at is not None
    with postgres_database.session_factory() as session:
        receipts = tuple(session.scalars(select(CompletionReceiptModel).where(
            CompletionReceiptModel.user_id == owner_id,
            CompletionReceiptModel.source_kind == "solo",
            CompletionReceiptModel.source_id == attempt_id,
        )))
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt.status == "pending"
        assert receipt.canonical_question_count == receipt.accepted_answer_count == 5
        assert receipt.latest_accepted_at == max(answer.accepted_at for answer in finished.answers)
        assert receipt.latest_accepted_at == accepted.accepted_at
        assert receipt.completed_at == finished.terminal_at
        assert receipt.study_date == study_date_for(receipt.latest_accepted_at, ZONE)


def test_terminal_purge_keeps_answer_free_receipt_until_account_deletion(
    postgres_database: Database,
) -> None:
    owner_id = _owner(postgres_database)
    finished_id, question_ids = _finish_quiz(postgres_database, owner_id)
    now = datetime.now(timezone.utc)
    old = timedelta(days=31)
    pending = _attempt(
        owner_id, status="AWAITING_MARKING", created_at=now - old,
    )
    pending.started_at = now - old
    pending.current_question_position = 1
    pending_question_id = uuid4()
    recent = _attempt(
        owner_id, status="ABANDONED", terminal_at=now - timedelta(days=29),
        created_at=now - timedelta(days=29),
    )
    with postgres_database.session_factory() as session, session.begin():
        finished = session.get(SoloAttemptModel, finished_id)
        assert finished is not None and finished.terminal_at is not None
        finished.created_at -= old
        finished.started_at -= old
        finished.terminal_at -= old
        for answer in session.scalars(select(SoloAnswerModel).where(
            SoloAnswerModel.attempt_id == finished_id
        )):
            answer.accepted_at -= old
            assert answer.graded_at is not None
            answer.graded_at -= old
        receipt = session.scalar(select(CompletionReceiptModel).where(
            CompletionReceiptModel.source_id == finished_id,
            CompletionReceiptModel.source_kind == "solo",
        ))
        assert receipt is not None
        receipt.latest_accepted_at -= old
        receipt.completed_at -= old
        receipt.created_at -= old
        receipt.study_date = study_date_for(receipt.latest_accepted_at, ZONE)
        session.add_all((pending, recent))
        session.flush()
        session.add(SoloQuestionModel(
            id=pending_question_id, attempt_id=pending.id, position=0,
            question_type="WRITTEN", max_marks=5, prompt_snapshot="Explain force.",
            options_snapshot=[], correct_option_id=None,
            grading_rubric_snapshot={}, worked_explanation_snapshot="Reference answer.",
            original_extract=None, content_fingerprint="a" * 64,
        ))
        session.flush()
        session.add(SoloAnswerModel(
            id=uuid4(), attempt_id=pending.id, question_id=pending_question_id,
            selected_option_id=None, answer_text="My saved long answer",
            accepted_at=now - old, grading_status="PENDING",
            mark_provenance="AI_RUBRIC", earned_marks=None,
        ))

    repository = PostgresSoloRepository(postgres_database.session_factory)
    assert repository.purge_terminal_content(now - timedelta(days=30), limit=1) == 1
    with postgres_database.session_factory() as session:
        assert session.get(SoloAttemptModel, finished_id) is None
        assert session.get(SoloAttemptModel, pending.id) is not None
        assert session.get(SoloAttemptModel, recent.id) is not None
        assert session.scalar(select(func.count()).select_from(SoloQuestionModel).where(
            SoloQuestionModel.attempt_id == finished_id
        )) == 0
        assert session.scalar(select(func.count()).select_from(SoloAnswerModel).where(
            SoloAnswerModel.attempt_id == finished_id
        )) == 0
        assert session.scalar(select(func.count()).select_from(CompletionReceiptModel).where(
            CompletionReceiptModel.user_id == owner_id,
            CompletionReceiptModel.source_id == finished_id,
        )) == 1
        assert session.scalar(select(func.count()).select_from(SoloAnswerModel).where(
            SoloAnswerModel.question_id == pending_question_id
        )) == 1

    deleted = PostgresAccountDeletionRepository(postgres_database.session_factory).delete_local_account(owner_id)
    assert deleted.already_deleted is False
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, owner_id)
        assert user is not None and user.deleted_at is not None
        assert session.get(LearningSettingsModel, owner_id) is None
        assert session.scalar(select(func.count()).select_from(SoloAttemptModel).where(
            SoloAttemptModel.owner_id == owner_id
        )) == 0
        assert session.scalar(select(func.count()).select_from(CompletionReceiptModel).where(
            CompletionReceiptModel.user_id == owner_id
        )) == 0
    with pytest.raises(SoloError) as failure:
        repository.claim_or_create(
            owner_id,
            SoloCreateRequest(
                request_id=uuid4(), subject="physics", topic="forces", total_marks=5,
            ),
            model_id="offline-test", lease_seconds=30,
        )
    assert failure.value.code == "solo_not_found"
