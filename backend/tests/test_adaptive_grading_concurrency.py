"""Two-connection regressions for the adaptive parent-before-child lock order."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, get_ident
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select

from app.db.models.answer_submission import AnswerSubmissionModel as Answer
from app.db.models.generated_quiz_question import GeneratedQuizQuestionModel
from app.db.models.quiz_preparation import QuizPreparationModel as Preparation
from app.db.models.quiz_session import QuizSessionModel as Quiz
from app.db.models.room import RoomModel
from app.db.models.session_question import SessionQuestionModel as Question
from app.domain.member import RoomMember
from app.domain.room import Room
from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.protocol import GenerationRequest
from app.generator.verification import FakeQuizContentVerifier, VerifiedQuizSet
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_preparations import PostgresQuizPreparationRepository
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.services.quiz_preparation_service import QuizPreparationService


def _verified_set(target_total_marks: int = 7) -> VerifiedQuizSet:
    request = GenerationRequest(
        education_level="GCSE",
        quiz_subject="physics",
        quiz_topic="energy",
        target_total_marks=target_total_marks,
    )
    questions = asyncio.run(FakeQuizContentGenerator().generate_quiz_questions(request))
    return asyncio.run(FakeQuizContentVerifier().verify_quiz_content(questions, request))


@pytest.fixture
def prepared(postgres_database):
    db = postgres_database
    owner, member, room_id, request_id = uuid4(), uuid4(), uuid4(), uuid4()
    users = PostgresUserRepository(db.session_factory)
    users.upsert_profile(owner, "Host")
    users.upsert_profile(member, "Student")
    rooms = PostgresRoomRepository(db.session_factory)
    room = Room(id=room_id, owner_id=owner, name="Concurrency", join_code="LOCK42",
                maximum_members=8, quiz_mode="ADAPTIVE", education_level="GCSE",
                quiz_subject="physics", quiz_topic="energy", target_total_marks=7)
    rooms.create_with_owner(room, RoomMember(room_id=room_id, user_id=owner, display_name="Host"))
    PostgresMembershipRepository(db.session_factory).add(
        RoomMember(room_id=room_id, user_id=member, display_name="Student"))
    preparations = PostgresQuizPreparationRepository(db.session_factory)
    prep = asyncio.run(QuizPreparationService(
        preparations,
        rooms,
        FakeQuizContentGenerator(),
        verifier=FakeQuizContentVerifier(),
    )
                       .prepare_quiz(
                           room_id,
                           request_id,
                           owner,
                           wait_for_completion=True,
                       ))
    return db, room, member, prep, preparations


@pytest.fixture
def grading(prepared):
    db, room, member, _, _ = prepared
    repository = PostgresQuizSessionRepository(db.session_factory)
    repository.set_ready(room.id, member, True)
    quiz = repository.start_session(room.id, room.owner_id)
    with db.session_factory() as session, session.begin():
        question = session.scalar(select(Question).where(
            Question.session_id == quiz.id, Question.question_type == "WRITTEN"))
        assert question is not None
        question_id = question.id
        now = session.scalar(select(func.clock_timestamp()))
        current = session.get(Quiz, quiz.id)
        current.current_question_position = question.position
        question.opened_at = now
        question.closes_at = now + timedelta(minutes=5)
    for user_id in (room.owner_id, member):
        repository.submit_answer(room.id, user_id, question_id, answer_text="A synthetic response")
    claims = repository.claim_due_written_submissions()
    assert len(claims) == 2
    return db, room, quiz.id, repository, claims


def parent_barrier(db, parent, parent_id, child, child_id, operation, mutation=None):
    """While a finalizer waits for the parent, its child must remain lockable.

    The before-execute event is a barrier at the actual parent SQL statement;
    the old inversion already owns the child at this exact point.
    """
    attempted = Event()
    main_thread = get_ident()

    def observe(connection, cursor, statement, parameters, context, executemany):
        if get_ident() != main_thread and f"FROM {parent.__tablename__}" in statement and "FOR UPDATE" in statement:
            attempted.set()

    event.listen(db.engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with db.session_factory() as holder, holder.begin():
                holder.scalar(select(parent).where(parent.id == parent_id).with_for_update())
                future = pool.submit(operation)
                assert attempted.wait(3), "finalizer never reached parent lock"
                row = holder.scalar(select(child).where(child.id == child_id).with_for_update(nowait=True))
                assert row is not None, "child disappeared"
                if mutation is not None:
                    mutation(holder, row)
            return future.result(timeout=5)
    finally:
        event.remove(db.engine, "before_cursor_execute", observe)


def finalize(repository, claim, failure=False):
    if failure:
        return repository.mark_written_grading_retryable_or_unavailable(
            claim.submission_id, claim.claim_token, "provider_timeout")
    return repository.store_written_grading_result_cas(
        claim.submission_id, claim.claim_token, 0, False, 0, [], {})


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("expire", [False, True])
def test_grading_finalizer_waits_without_answer_lock_and_rechecks_lease(grading, failure, expire):
    db, _, quiz_id, repository, claims = grading
    claim = claims[0]

    def expire_now(session, answer):
        # Later than the waiting transaction's start, earlier than its lock grant.
        answer.lease_expires_at = session.scalar(select(func.clock_timestamp()))

    result = parent_barrier(db, Quiz, quiz_id, Answer, claim.submission_id,
                            lambda: finalize(repository, claim, failure), expire_now if expire else None)
    assert result is (not expire)
    with db.session_factory() as session:
        answer = session.get(Answer, claim.submission_id)
        assert answer.grading_status == ("IN_PROGRESS" if expire else "RETRYABLE" if failure else "GRADED")


@pytest.mark.parametrize("operation", ["complete", "fail", "renew"])
@pytest.mark.parametrize("expire", [False, True])
def test_preparation_finalizer_waits_without_prep_lock_and_rechecks_clock(prepared, operation, expire):
    db, room, _, prep, repository = prepared
    token = uuid4()
    verified_set = _verified_set(room.target_total_marks or 7)
    with db.session_factory() as session, session.begin():
        row = session.get(Preparation, prep.id)
        row.status = "GENERATING"
        row.claim_token = token
        row.lease_expires_at = session.scalar(select(func.clock_timestamp())) + timedelta(minutes=1)
        session.execute(
            delete(GeneratedQuizQuestionModel).where(
                GeneratedQuizQuestionModel.preparation_id == prep.id
            )
        )

    def mutate():
        if operation == "complete":
            # A typed proof is required even for this CAS lock-order test.
            return repository.store_generated_questions_cas(
                prep.id,
                prep.request_id,
                token,
                prep.generation_attempt,
                verified_set,
                operation_deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
            )
        if operation == "fail":
            return repository.mark_preparation_failed_cas(prep.id, prep.request_id, token, "provider_timeout")
        return repository.renew_preparation_lease_cas(prep.id, prep.request_id, token)

    def expire_now(session, row):
        row.lease_expires_at = session.scalar(select(func.clock_timestamp()))

    assert parent_barrier(db, RoomModel, room.id, Preparation, prep.id, mutate,
                          expire_now if expire else None) is (not expire)
    with db.session_factory() as session:
        current = session.get(Preparation, prep.id)
        assert current.state_version == prep.state_version + (0 if expire else 1)
        expected_status = "GENERATING" if expire or operation == "renew" else "READY" if operation == "complete" else "FAILED"
        assert current.status == expected_status
        if not expire and operation == "renew":
            assert current.claim_token == token
            assert current.lease_expires_at > session.scalar(select(func.clock_timestamp()))


@pytest.mark.parametrize("lock_parent", [False, True])
def test_recovery_skips_locks_bounds_batch_and_never_claims_attempt_three(grading, lock_parent):
    db, _, quiz_id, repository, claims = grading
    with db.session_factory() as session, session.begin():
        for claim in claims:
            row = session.get(Answer, claim.submission_id)
            row.lease_expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
            row.attempt_count = 2
        before = session.get(Quiz, quiz_id).state_version
    parent = Quiz if lock_parent else Answer
    target = quiz_id if lock_parent else claims[0].submission_id
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.session_factory() as holder, holder.begin():
            holder.scalar(select(parent).where(parent.id == target).with_for_update())
            future = pool.submit(repository.reset_expired_grading_claims, 100)
            result = future.result(timeout=3)
            assert result == (() if lock_parent else (quiz_id,))
    repository.reset_expired_grading_claims(limit=1)
    with db.session_factory() as session:
        unavailable = list(session.scalars(select(Answer).where(Answer.grading_status == "UNAVAILABLE")))
        assert len(unavailable) == (1 if lock_parent else 2)
        assert session.get(Quiz, quiz_id).state_version == before + len(unavailable)
    repository.reset_expired_grading_claims()
    assert repository.claim_due_written_submissions() == ()


def test_concurrent_finalizers_preserve_each_version_increment(grading):
    db, _, quiz_id, repository, claims = grading
    with db.session_factory() as session:
        before = session.get(Quiz, quiz_id).state_version
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda claim: finalize(repository, claim), claims))
    assert results == [True, True]
    with db.session_factory() as session:
        assert session.get(Quiz, quiz_id).state_version == before + 2


@pytest.mark.parametrize("lock_parent", [False, True])
def test_preparation_recovery_skips_contended_parent_or_child(prepared, lock_parent):
    db, room, _, prep, repository = prepared
    with db.session_factory() as session, session.begin():
        row = session.get(Preparation, prep.id)
        row.status = "GENERATING"
        row.claim_token = uuid4()
        row.lease_expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        before = row.state_version
    parent = RoomModel if lock_parent else Preparation
    target = room.id if lock_parent else prep.id
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.session_factory() as holder, holder.begin():
            holder.scalar(select(parent).where(parent.id == target).with_for_update())
            assert pool.submit(repository.fail_expired_generating_preparations).result(timeout=3) == ()
    recovered = repository.fail_expired_generating_preparations(limit=1)
    assert len(recovered) == 1
    assert recovered[0].status == "FAILED"
    assert recovered[0].state_version == before + 1
    assert repository.fail_expired_generating_preparations() == ()


@pytest.mark.parametrize("change", ["question", "token", "deleted"])
def test_waiting_grading_result_revalidates_current_question_token_and_deleted_answer(grading, change):
    db, _, quiz_id, repository, claims = grading
    claim = claims[0]

    def invalidate(session, answer):
        if change == "question":
            session.get(Quiz, quiz_id).current_question_position += 1
        elif change == "token":
            answer.claim_token = uuid4()
        else:
            session.delete(answer)

    assert parent_barrier(db, Quiz, quiz_id, Answer, claim.submission_id,
                          lambda: finalize(repository, claim), invalidate) is False


@pytest.mark.parametrize("change", ["closed", "token", "attempt"])
def test_waiting_preparation_result_revalidates_room_claim_and_attempt(prepared, change):
    db, room, _, prep, repository = prepared
    token = uuid4()
    verified_set = _verified_set(room.target_total_marks or 7)
    with db.session_factory() as session, session.begin():
        row = session.get(Preparation, prep.id)
        row.status = "GENERATING"
        row.claim_token = token
        row.lease_expires_at = session.scalar(select(func.clock_timestamp())) + timedelta(minutes=1)

    def invalidate(session, row):
        if change == "closed":
            session.get(RoomModel, room.id).closed_at = session.scalar(select(func.clock_timestamp()))
        elif change == "token":
            row.claim_token = uuid4()
        else:
            row.generation_attempt += 1

    assert parent_barrier(db, RoomModel, room.id, Preparation, prep.id,
        lambda: repository.store_generated_questions_cas(prep.id, prep.request_id, token,
                                                          prep.generation_attempt, verified_set,
                                                          operation_deadline=datetime.now(timezone.utc) + timedelta(minutes=1)), invalidate) is False


@pytest.mark.parametrize("lock_parent", [False, True])
def test_claims_skip_contended_rows_and_recheck_attempt_cap(grading, lock_parent):
    db, _, quiz_id, repository, claims = grading
    with db.session_factory() as session, session.begin():
        for claim in claims:
            row = session.get(Answer, claim.submission_id)
            row.grading_status = "PENDING"
            row.attempt_count = 1
            row.claim_token = None
            row.lease_expires_at = None
    parent = Quiz if lock_parent else Answer
    target = quiz_id if lock_parent else claims[0].submission_id
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.session_factory() as holder, holder.begin():
            holder.scalar(select(parent).where(parent.id == target).with_for_update())
            claimed = pool.submit(repository.claim_due_written_submissions).result(timeout=3)
            assert len(claimed) == (0 if lock_parent else 1)
            assert all(c.attempt_count == 2 for c in claimed)
    remaining = repository.claim_due_written_submissions(limit=1)
    assert len(remaining) == 1
    with db.session_factory() as session, session.begin():
        for row in session.scalars(select(Answer)):
            row.grading_status = "PENDING"
            row.attempt_count = 2
            row.claim_token = None
            row.lease_expires_at = None
    assert repository.claim_due_written_submissions() == ()


def test_host_retry_waits_without_answer_lock_and_starts_one_new_cycle(grading):
    db, room, quiz_id, repository, claims = grading
    with db.session_factory() as session, session.begin():
        session.get(Quiz, quiz_id).status = "QUESTION_GRADING"
        for row in session.scalars(select(Answer)):
            row.grading_status = "UNAVAILABLE"
            row.attempt_count = 2
            row.claim_token = None
            row.lease_expires_at = None
        before = session.get(Quiz, quiz_id).state_version
    assert parent_barrier(db, Quiz, quiz_id, Answer, claims[0].submission_id,
                          lambda: repository.retry_grading_for_room(room.id, room.owner_id)) == 2
    assert repository.retry_grading_for_room(room.id, room.owner_id) == 0
    with db.session_factory() as session:
        assert session.get(Quiz, quiz_id).state_version == before + 1
        assert all(row.attempt_count == 0 and row.attempt_cycle == claims[0].attempt_cycle + 1
                   for row in session.scalars(select(Answer)))
    assert finalize(repository, claims[0]) is False
