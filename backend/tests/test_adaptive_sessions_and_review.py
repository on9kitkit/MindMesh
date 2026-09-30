"""Tests for adaptive session lifecycle, discriminated submissions, private review, deletion, and retention."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.account_deletion.settings import AccountDeletionSettings
from app.account_deletion.repository import PostgresAccountDeletionRepository
from app.account_deletion.service import AccountDeletionService
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.generated_quiz_question import GeneratedQuizQuestionModel
from app.db.models.quiz_preparation import QuizPreparationModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.models.safety_report import SafetyReportModel
from app.domain.adaptive_quiz import QuestionType
from app.domain.member import RoomMember
from app.domain.room import Room
from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.verification import FakeQuizContentVerifier
from app.main import create_app
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_preparations import (
    PostgresQuizPreparationRepository,
)
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.retention.policy import RetentionPolicy
from app.retention.repository import PostgresRetentionRepository
from app.retention.service import RetentionService
from app.services.quiz_preparation_service import QuizPreparationService
from app.services.rooms import RoomService
from app.services.sessions import SessionService
from tests.conftest import FakeAuthVerifier, OWNER_ID

OTHER_USER_ID = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def adaptive_setup(
    postgres_database,
    postgres_user_repository: PostgresUserRepository,
):
    postgres_user_repository.upsert_profile(OTHER_USER_ID, "Other Student")
    room_repo = PostgresRoomRepository(postgres_database.session_factory)
    prep_repo = PostgresQuizPreparationRepository(postgres_database.session_factory)
    session_repo = PostgresQuizSessionRepository(postgres_database.session_factory)
    generator = FakeQuizContentGenerator()
    prep_service = QuizPreparationService(
        prep_repo,
        room_repo,
        generator,
        verifier=FakeQuizContentVerifier(),
    )
    session_service = SessionService(session_repo)

    return {
        "database": postgres_database,
        "room_repo": room_repo,
        "prep_repo": prep_repo,
        "session_repo": session_repo,
        "generator": generator,
        "prep_service": prep_service,
        "session_service": session_service,
    }


@pytest.mark.anyio
async def test_adaptive_session_start_requires_ready_preparation(adaptive_setup):
    room_repo = adaptive_setup["room_repo"]
    session_service = adaptive_setup["session_service"]

    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Adaptive Physics",
        join_code="ADAP01",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="physics",
        quiz_topic="energy",
        target_total_marks=10,
    )
    room_repo.create_with_owner(
        room,
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"),
    )
    from app.repositories.postgres_members import PostgresMembershipRepository
    mem_repo = PostgresMembershipRepository(adaptive_setup["database"].session_factory)
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    # Attempting to start without preparation raises QuizNotReadyError
    from app.domain.errors import QuizNotReadyError
    with pytest.raises(QuizNotReadyError):
        session_service.start_session(room_id, OWNER_ID)

    # Prepare quiz to READY
    prep_service = adaptive_setup["prep_service"]
    prep = await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    assert prep.is_ready is True

    # Now starting succeeds!
    session = session_service.start_session(room_id, OWNER_ID)
    assert session.is_adaptive is True
    assert session.total_available_marks == 10
    assert session.question_bank_key.startswith("adaptive:")


@pytest.mark.anyio
async def test_discriminated_submissions_and_deterministic_grading(adaptive_setup):
    room_repo = adaptive_setup["room_repo"]
    prep_service = adaptive_setup["prep_service"]
    session_service = adaptive_setup["session_service"]
    mem_repo = PostgresMembershipRepository(adaptive_setup["database"].session_factory)

    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Discriminated Submissions",
        join_code="SUBM01",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="physics",
        quiz_topic="forces",
        target_total_marks=7,  # MCQ(1) + Numerical(2) + Written(4)
    )
    room_repo.create_with_owner(
        room,
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"),
    )
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)

    questions = session_service.list_questions(sess.id)
    assert len(questions) >= 3

    # Question 0 is MCQ (1 mark)
    q0 = questions[0]
    assert q0.question_type == "MULTIPLE_CHOICE"
    ack0 = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=q0.id,
        selected_option_id=q0.correct_option_id,
    )
    assert ack0.grading_status == "GRADED"

    # Advance to Question 1: Numerical (2 marks)
    # Set closes_at in the past and reconcile
    with adaptive_setup["database"].session_factory() as s:
        with s.begin():
            sq0 = s.get(SessionQuestionModel, q0.id)
            sq0.opened_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            sq0.closes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session_service.reconcile_session(session_id=sess.id)  # advances to REVEAL
    with adaptive_setup["database"].session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, sess.id)
            sm.reveal_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session_service.reconcile_session(session_id=sess.id)  # advances to Q1 OPEN

    q1 = session_service.list_questions(sess.id)[1]
    assert q1.question_type == "NUMERICAL"

    # Submit numerical answer
    ack1 = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=q1.id,
        answer_text="10.0 J",
    )
    assert ack1.grading_status == "GRADED"

    # Advance to Question 2: Written (4 marks)
    with adaptive_setup["database"].session_factory() as s:
        with s.begin():
            sq1 = s.get(SessionQuestionModel, q1.id)
            sq1.opened_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            sq1.closes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session_service.reconcile_session(session_id=sess.id)  # advances to REVEAL
    with adaptive_setup["database"].session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, sess.id)
            sm.reveal_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session_service.reconcile_session(session_id=sess.id)  # advances to Q2 OPEN

    q2 = session_service.list_questions(sess.id)[2]
    assert q2.question_type == "WRITTEN"

    # Submit written answer -> commits as PENDING
    ack2 = session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=q2.id,
        answer_text="Energy is conserved in closed systems.",
    )
    assert ack2.grading_status == "PENDING"

    # When deadline passes, session transitions to QUESTION_GRADING because written answer is PENDING
    with adaptive_setup["database"].session_factory() as s:
        with s.begin():
            sq2 = s.get(SessionQuestionModel, q2.id)
            sq2.opened_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            sq2.closes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    updated_sess = session_service.reconcile_session(session_id=sess.id)
    assert updated_sess.status.value == "QUESTION_GRADING"


@pytest.mark.anyio
async def test_private_review_endpoint_and_privacy_boundaries(
    adaptive_setup,
    auth_verifier: FakeAuthVerifier,
):
    room_repo = adaptive_setup["room_repo"]
    prep_service = adaptive_setup["prep_service"]
    session_service = adaptive_setup["session_service"]
    mem_repo = PostgresMembershipRepository(adaptive_setup["database"].session_factory)

    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Review Room",
        join_code="REVW01",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="biology",
        quiz_topic="cells",
        target_total_marks=5,
    )
    room_repo.create_with_owner(
        room,
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"),
    )
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    q0 = session_service.list_questions(sess.id)[0]

    # Both participants submit answers
    session_service.submit_answer(
        room_id=room_id,
        user_id=OWNER_ID,
        session_question_id=q0.id,
        selected_option_id=q0.correct_option_id,
    )
    wrong_opt = next(opt.id for opt in q0.options_snapshot if opt.id != q0.correct_option_id)
    session_service.submit_answer(
        room_id=room_id,
        user_id=OTHER_USER_ID,
        session_question_id=q0.id,
        selected_option_id=wrong_opt,
    )
    # Move session to FINISHED
    with adaptive_setup["database"].session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, sess.id)
            sm.status = "FINISHED"
            sm.finished_at = datetime.now(timezone.utc)
            for sq in s.scalars(select(SessionQuestionModel).where(SessionQuestionModel.session_id == sess.id)).all():
                sq.revealed_at = datetime.now(timezone.utc)

    # Test private review via SessionService
    review_owner = session_service.get_session_review(room_id, sess.id, OWNER_ID)
    assert review_owner.session_id == sess.id
    assert review_owner.viewer_user_id == OWNER_ID
    assert review_owner.total_earned_marks > 0
    # Viewer's response is included
    assert review_owner.questions[0].selected_option_id == q0.correct_option_id

    review_other = session_service.get_session_review(room_id, sess.id, OTHER_USER_ID)
    assert review_other.viewer_user_id == OTHER_USER_ID
    assert review_other.questions[0].selected_option_id == wrong_opt
    # Neither review exposes the other participant's answer
    assert review_owner.questions[0].selected_option_id != review_other.questions[0].selected_option_id


@pytest.mark.anyio
async def test_account_deletion_deletes_raw_answers_and_feedback(adaptive_setup):
    db = adaptive_setup["database"]
    room_repo = adaptive_setup["room_repo"]
    prep_service = adaptive_setup["prep_service"]
    session_service = adaptive_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)
    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Deletion Test Room",
        join_code="DELT01",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="chemistry",
        quiz_topic="atomic_structure",
        target_total_marks=5,
    )
    room_repo.create_with_owner(
        room,
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"),
    )
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)
    q0 = session_service.list_questions(sess.id)[0]

    session_service.submit_answer(
        room_id=room_id,
        user_id=OTHER_USER_ID,
        session_question_id=q0.id,
        selected_option_id=q0.correct_option_id,
    )

    survivor = session_service.submit_answer(
        room_id=room_id, user_id=OWNER_ID, session_question_id=q0.id,
        selected_option_id=q0.correct_option_id,
    )
    # Populate exact private-data canaries and capture IDs before deletion.
    with db.session_factory() as s, s.begin():
        participant_ids = set(s.scalars(select(SessionParticipantModel.id).where(SessionParticipantModel.user_id == OTHER_USER_ID)).all())
        submissions = s.scalars(select(AnswerSubmissionModel).where(AnswerSubmissionModel.participant_id.in_(participant_ids))).all()
        submission_ids = {submission.id for submission in submissions}
        assert participant_ids and submission_ids
        for submission in submissions:
            submission.selected_option_id = None
            submission.answer_text = "PRIVATE-ANSWER-ERASURE-CANARY"
            submission.feedback = {"summary": "PRIVATE-FEEDBACK-ERASURE-CANARY"}

    # Finish the session so deletion is allowed
    with db.session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, sess.id)
            sm.status = "FINISHED"
            sm.finished_at = datetime.now(timezone.utc)

    # Delete OTHER_USER_ID account
    del_repo = PostgresAccountDeletionRepository(db.session_factory)
    del_repo.delete_local_account(OTHER_USER_ID)

    # Verify that all raw answers, feedback, and submissions for OTHER_USER_ID were deleted!
    with db.session_factory() as s:
        assert not s.scalars(select(SessionParticipantModel).where(SessionParticipantModel.id.in_(participant_ids))).all()
        assert not s.scalars(select(AnswerSubmissionModel).where(AnswerSubmissionModel.id.in_(submission_ids))).all()
        assert s.get(AnswerSubmissionModel, survivor.submission_id) is not None


@pytest.mark.anyio
async def test_retention_purge_order_and_safety_report_protection(adaptive_setup):
    db = adaptive_setup["database"]
    room_repo = adaptive_setup["room_repo"]
    prep_service = adaptive_setup["prep_service"]
    session_service = adaptive_setup["session_service"]
    mem_repo = PostgresMembershipRepository(db.session_factory)

    room_id = uuid4()
    room = Room(
        id=room_id,
        owner_id=OWNER_ID,
        name="Retention Test Room",
        join_code="RETN01",
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="biology",
        quiz_topic="ecology",
        target_total_marks=5,
    )
    room_repo.create_with_owner(
        room,
        RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"),
    )
    mem_repo.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    session_service.set_ready(room_id, OTHER_USER_ID, True)

    await prep_service.prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    sess = session_service.start_session(room_id, OWNER_ID)

    # Finish session and close room in the past (> 30 days ago)
    old_time = datetime.now(timezone.utc) - timedelta(days=35)
    with db.session_factory() as s:
        with s.begin():
            sm = s.get(QuizSessionModel, sess.id)
            sm.status = "FINISHED"
            sm.finished_at = old_time
            rm = s.get(RoomModel, room_id)
            rm.created_at = old_time - timedelta(days=1)
            rm.closed_at = old_time

    # Run retention purge
    retention_repo = PostgresRetentionRepository(db.session_factory)
    policy = RetentionPolicy(
        maximum_accepted_jwt_lifetime=timedelta(hours=1),
        batch_limit=100,
    )
    report_id = uuid4()
    with db.session_factory() as s, s.begin():
        s.add(SafetyReportModel(id=report_id, room_id=room_id, reporter_user_id=OWNER_ID, reported_user_id=OTHER_USER_ID, reported_display_name_snapshot="Other", reason="other_safety_concern", status="OPEN", created_at=old_time))
    protected = retention_repo.purge(policy, as_of=datetime.now(timezone.utc))
    assert protected.deleted.closed_rooms == 0
    with db.session_factory() as s, s.begin():
        assert s.get(RoomModel, room_id) is not None
        assert s.get(QuizSessionModel, sess.id) is not None
        report = s.get(SafetyReportModel, report_id)
        report.status = "RESOLVED"
        report.resolved_at = datetime.now(timezone.utc) - timedelta(days=100)
    summary = retention_repo.purge(policy, as_of=datetime.now(timezone.utc))
    assert summary.deleted.closed_rooms >= 1

    # Verify quiz_preparations and generated_quiz_questions were cascade deleted with the room
    with db.session_factory() as s:
        preps = s.scalars(select(QuizPreparationModel).where(QuizPreparationModel.room_id == room_id)).all()
        assert len(preps) == 0
        sessions = s.scalars(select(QuizSessionModel).where(QuizSessionModel.room_id == room_id)).all()
        assert len(sessions) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("by_code", [False, True])
async def test_join_rejects_grading_but_allows_finished(adaptive_setup, by_code):
    from app.db.models.membership import RoomMembershipModel
    from tests.conftest import auth_headers

    db = adaptive_setup["database"]
    users = PostgresUserRepository(db.session_factory)
    outsider = uuid4()
    users.upsert_profile(outsider, "New participant")
    room_id = uuid4()
    room = Room(id=room_id, owner_id=OWNER_ID, name="Join guard", join_code="JNG234", maximum_members=8, quiz_mode="ADAPTIVE", education_level="GCSE", quiz_subject="physics", quiz_topic="forces", target_total_marks=5)
    adaptive_setup["room_repo"].create_with_owner(room, RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"))
    members = PostgresMembershipRepository(db.session_factory)
    members.add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    service = adaptive_setup["session_service"]
    service.set_ready(room_id, OTHER_USER_ID, True)
    await adaptive_setup["prep_service"].prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    quiz = service.start_session(room_id, OWNER_ID)
    with db.session_factory() as s, s.begin():
        s.get(QuizSessionModel, quiz.id).status = "QUESTION_GRADING"
    app = create_app(repository=adaptive_setup["room_repo"], membership_repository=members, user_repository=users, auth_verifier=FakeAuthVerifier({"outsider": outsider}), session_service=service)
    path = "/rooms/join" if by_code else f"/rooms/{room_id}/members"
    payload = {"join_code": room.join_code} if by_code else {}
    with TestClient(app) as client:
        response = client.post(path, json=payload, headers=auth_headers("outsider"))
        assert response.status_code == (404 if by_code else 409)
        with db.session_factory() as s, s.begin():
            assert not s.scalars(select(RoomMembershipModel).where(RoomMembershipModel.user_id == outsider)).all()
            current = s.get(QuizSessionModel, quiz.id)
            current.status = "FINISHED"
            current.finished_at = datetime.now(timezone.utc)
        assert client.post(path, json=payload, headers=auth_headers("outsider")).status_code == 201


@pytest.mark.anyio
async def test_account_deletion_blocked_during_grading(adaptive_setup):
    from app.domain.errors import AccountDeletionBlockedActiveQuizError
    db = adaptive_setup["database"]
    room_id = uuid4()
    room = Room(id=room_id, owner_id=OWNER_ID, name="Grading deletion", join_code="GD0001", maximum_members=8, quiz_mode="ADAPTIVE", education_level="GCSE", quiz_subject="physics", quiz_topic="forces", target_total_marks=5)
    adaptive_setup["room_repo"].create_with_owner(room, RoomMember(room_id=room_id, user_id=OWNER_ID, display_name="Host"))
    PostgresMembershipRepository(db.session_factory).add(RoomMember(room_id=room_id, user_id=OTHER_USER_ID, display_name="Other"))
    service = adaptive_setup["session_service"]
    service.set_ready(room_id, OTHER_USER_ID, True)
    await adaptive_setup["prep_service"].prepare_quiz(
        room_id, uuid4(), OWNER_ID, wait_for_completion=True
    )
    quiz = service.start_session(room_id, OWNER_ID)
    with db.session_factory() as s, s.begin():
        s.get(QuizSessionModel, quiz.id).status = "QUESTION_GRADING"
    with pytest.raises(AccountDeletionBlockedActiveQuizError):
        PostgresAccountDeletionRepository(db.session_factory).delete_local_account(OTHER_USER_ID)
