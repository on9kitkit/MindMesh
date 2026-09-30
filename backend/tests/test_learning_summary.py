"""Offline tests for the authenticated viewer-only learning summary."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import (
    Column,
    DateTime,
    delete,
    Integer,
    MetaData,
    select,
    String,
    Table,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from pydantic import ValidationError

from app.api.quiz import get_session_service
from app.auth import FakeAuthVerifier
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.domain.learning_summary import (
    EligibleLearningSession,
    LearningQuestionRecord,
    summarize_learning_data,
)
from app.domain.user import User
from app.main import create_app
from app.repositories.postgres_learning_summary import (
    PostgresLearningSummaryRepository,
)
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.members import InMemoryMembershipRepository
from app.repositories.rooms import InMemoryRoomRepository
from app.repositories.users import InMemoryUserRepository
from app.schemas.learning_summary import LearningSummaryResponse
from app.services.sessions import SessionService
from tests.conftest import auth_headers

VIEWER_TOKEN = "learning-summary-viewer-token"
PEER_ID = UUID("22222222-2222-4222-8222-222222222222")
LEARNER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class _Tables:
    metadata: MetaData
    rooms: Table
    memberships: Table
    sessions: Table
    participants: Table
    questions: Table
    submissions: Table


@dataclass(frozen=True, slots=True)
class _Environment:
    client: TestClient
    app: FastAPI
    engine: Engine
    session_factory: sessionmaker[Session]
    tables: _Tables
    users: InMemoryUserRepository


@dataclass(frozen=True, slots=True)
class _QuestionSeed:
    max_marks: int
    fingerprint: str
    viewer_status: str | None = None
    viewer_earned: int | None = None
    peer_status: str | None = None
    peer_earned: int | None = None


@pytest.fixture
def learning_environment():
    metadata = MetaData()
    def uuid_type() -> PostgreSQLUUID:
        return PostgreSQLUUID(as_uuid=True)

    tables = _Tables(
        metadata=metadata,
        rooms=Table(
            "rooms",
            metadata,
            Column("id", uuid_type(), primary_key=True),
            Column("owner_id", uuid_type(), nullable=False),
            Column("name", String(60), nullable=False),
            Column("join_code", String(6), nullable=False),
            Column("maximum_members", Integer, nullable=False),
            Column("closed_at", DateTime(timezone=True)),
            Column("quiz_mode", String(24), nullable=False),
            Column("education_level", String(16)),
            Column("quiz_subject", String(32)),
            Column("quiz_topic", String(40)),
            Column("target_total_marks", Integer),
            Column("created_at", DateTime(timezone=True), nullable=False),
        ),
        memberships=Table(
            "room_memberships",
            metadata,
            Column("id", uuid_type(), primary_key=True),
            Column("room_id", uuid_type(), nullable=False),
            Column("user_id", uuid_type(), nullable=False),
            Column("joined_at", DateTime(timezone=True), nullable=False),
            Column("left_at", DateTime(timezone=True)),
            Column("ready_at", DateTime(timezone=True)),
        ),
        sessions=Table(
            "quiz_sessions",
            metadata,
            Column("id", uuid_type(), primary_key=True),
            Column("room_id", uuid_type(), nullable=False),
            Column("preparation_id", uuid_type()),
            Column("question_bank_key", String(64), nullable=False),
            Column("quiz_mode", String(24), nullable=False),
            Column("education_level", String(16)),
            Column("quiz_subject", String(32)),
            Column("quiz_topic", String(40)),
            Column("total_available_marks", Integer, nullable=False),
            Column("status", String(24), nullable=False),
            Column("current_question_position", Integer, nullable=False),
            Column("state_version", Integer, nullable=False),
            Column("reveal_ends_at", DateTime(timezone=True)),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("finished_at", DateTime(timezone=True)),
        ),
        participants=Table(
            "session_participants",
            metadata,
            Column("id", uuid_type(), primary_key=True),
            Column("session_id", uuid_type(), nullable=False),
            Column("user_id", uuid_type(), nullable=False),
            Column("room_membership_id", uuid_type(), nullable=False),
            Column("display_name_snapshot", String(40), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        ),
        questions=Table(
            "session_questions",
            metadata,
            Column("id", uuid_type(), primary_key=True),
            Column("session_id", uuid_type(), nullable=False),
            Column("position", Integer, nullable=False),
            Column("max_marks", Integer, nullable=False),
            Column("content_fingerprint", String(64), nullable=False),
        ),
        submissions=Table(
            "answer_submissions",
            metadata,
            Column("id", uuid_type(), primary_key=True),
            Column("session_id", uuid_type(), nullable=False),
            Column("session_question_id", uuid_type(), nullable=False),
            Column("participant_id", uuid_type(), nullable=False),
            Column("grading_status", String(24), nullable=False),
            Column("earned_marks", Integer),
        ),
    )
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = PostgresLearningSummaryRepository(session_factory)
    users = InMemoryUserRepository()
    users.upsert_profile(LEARNER_ID, "Learning Student")
    review_service = SessionService(PostgresQuizSessionRepository(session_factory))
    app = create_app(
        repository=InMemoryRoomRepository(),
        membership_repository=InMemoryMembershipRepository(),
        user_repository=users,
        auth_verifier=FakeAuthVerifier({VIEWER_TOKEN: LEARNER_ID}),
        learning_summary_repository=repository,
    )
    app.dependency_overrides[get_session_service] = lambda: review_service
    with TestClient(app) as client:
        yield _Environment(
            client=client,
            app=app,
            engine=engine,
            session_factory=session_factory,
            tables=tables,
            users=users,
        )
    engine.dispose()


def _insert_room(
    connection: Connection,
    tables: _Tables,
    *,
    subject: str | None = "physics",
    topic: str | None = "energy",
    closed: bool = False,
    mode: str = "ADAPTIVE",
    education_level: str | None = "GCSE",
    viewer_left: bool = False,
) -> tuple[UUID, UUID]:
    room_id = uuid4()
    membership_id = uuid4()
    connection.execute(
        tables.rooms.insert().values(
            id=room_id,
            owner_id=LEARNER_ID,
            name="Summary Test Room",
            join_code=room_id.hex[:6].upper(),
            maximum_members=8,
            closed_at=BASE_TIME + timedelta(days=30) if closed else None,
            quiz_mode=mode,
            education_level=education_level,
            quiz_subject=subject,
            quiz_topic=topic,
            target_total_marks=None if mode == "LEGACY_PHYSICS" else 5,
            created_at=BASE_TIME,
        )
    )
    connection.execute(
        tables.memberships.insert().values(
            id=membership_id,
            room_id=room_id,
            user_id=LEARNER_ID,
            joined_at=BASE_TIME,
            left_at=BASE_TIME if viewer_left else None,
            ready_at=None,
        )
    )
    return room_id, membership_id


def _insert_session(
    connection: Connection,
    tables: _Tables,
    *,
    room_id: UUID,
    viewer_membership_id: UUID,
    started_at: datetime,
    questions: tuple[_QuestionSeed, ...] = (),
    participant: bool = True,
    peer_participant: bool = False,
    status: str = "FINISHED",
    finished_at_offset: timedelta | None = None,
    mode: str = "ADAPTIVE",
    education_level: str | None = "GCSE",
    subject: str | None = "physics",
    topic: str | None = "energy",
) -> UUID:
    session_id = uuid4()
    finished_at = (
        started_at + (finished_at_offset or timedelta(seconds=1))
        if status == "FINISHED"
        else None
    )
    connection.execute(
        tables.sessions.insert().values(
            id=session_id,
            room_id=room_id,
            preparation_id=uuid4() if mode == "ADAPTIVE" else None,
            question_bank_key="adaptive:test" if mode == "ADAPTIVE" else "legacy",
            quiz_mode=mode,
            education_level=education_level,
            quiz_subject=subject,
            quiz_topic=topic,
            total_available_marks=sum(question.max_marks for question in questions) or 5,
            status=status,
            current_question_position=0,
            state_version=1,
            reveal_ends_at=None,
            started_at=started_at,
            finished_at=finished_at,
        )
    )
    viewer_participant_id: UUID | None = None
    peer_participant_id: UUID | None = None
    if participant:
        viewer_participant_id = uuid4()
        connection.execute(
            tables.participants.insert().values(
                id=viewer_participant_id,
                session_id=session_id,
                user_id=LEARNER_ID,
                room_membership_id=viewer_membership_id,
                display_name_snapshot="Learning Student",
                created_at=started_at,
            )
        )
    if peer_participant:
        peer_participant_id = uuid4()
        connection.execute(
            tables.participants.insert().values(
                id=peer_participant_id,
                session_id=session_id,
                user_id=PEER_ID,
                room_membership_id=viewer_membership_id,
                display_name_snapshot="Peer Student",
                created_at=started_at,
            )
        )

    for position, question_seed in enumerate(questions):
        question_id = uuid4()
        connection.execute(
            tables.questions.insert().values(
                id=question_id,
                session_id=session_id,
                position=position,
                max_marks=question_seed.max_marks,
                content_fingerprint=question_seed.fingerprint,
            )
        )
        if viewer_participant_id is not None and question_seed.viewer_status is not None:
            connection.execute(
                tables.submissions.insert().values(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=question_id,
                    participant_id=viewer_participant_id,
                    grading_status=question_seed.viewer_status,
                    earned_marks=question_seed.viewer_earned,
                )
            )
        if peer_participant_id is not None and question_seed.peer_status is not None:
            connection.execute(
                tables.submissions.insert().values(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=question_id,
                    participant_id=peer_participant_id,
                    grading_status=question_seed.peer_status,
                    earned_marks=question_seed.peer_earned,
                )
            )
    return session_id


def test_authenticated_query_includes_retained_closed_and_left_history_but_only_viewer_rows(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    assert environment.client.get("/me/learning-summary").status_code == 401

    with environment.engine.begin() as connection:
        open_room_id, open_membership_id = _insert_room(
            connection, environment.tables
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=open_room_id,
            viewer_membership_id=open_membership_id,
            started_at=BASE_TIME,
            peer_participant=True,
            questions=(
                _QuestionSeed(
                    2,
                    "viewer-fingerprint-1",
                    viewer_status="GRADED",
                    viewer_earned=1,
                    peer_status="GRADED",
                    peer_earned=2,
                ),
            ),
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=open_room_id,
            viewer_membership_id=open_membership_id,
            started_at=BASE_TIME + timedelta(minutes=1),
            questions=(
                _QuestionSeed(
                    1,
                    "viewer-fingerprint-2",
                    viewer_status="GRADED",
                    viewer_earned=1,
                ),
            ),
        )

        closed_room_id, closed_membership_id = _insert_room(
            connection, environment.tables, closed=True
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=closed_room_id,
            viewer_membership_id=closed_membership_id,
            started_at=BASE_TIME + timedelta(minutes=2),
            questions=(
                _QuestionSeed(1, "closed-room", "GRADED", 1),
            ),
        )

        left_room_id, left_membership_id = _insert_room(
            connection, environment.tables, viewer_left=True
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=left_room_id,
            viewer_membership_id=left_membership_id,
            started_at=BASE_TIME + timedelta(minutes=3),
            questions=(
                _QuestionSeed(1, "left-room", "GRADED", 0),
            ),
        )

        _insert_session(
            connection,
            environment.tables,
            room_id=open_room_id,
            viewer_membership_id=open_membership_id,
            started_at=BASE_TIME + timedelta(minutes=4),
            participant=False,
            peer_participant=True,
            questions=(
                _QuestionSeed(1, "not-viewer-participant", peer_status="GRADED", peer_earned=1),
            ),
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=open_room_id,
            viewer_membership_id=open_membership_id,
            started_at=BASE_TIME + timedelta(minutes=5),
            status="QUESTION_OPEN",
            questions=(_QuestionSeed(1, "unfinished", "GRADED", 1),),
        )

        legacy_room_id, legacy_membership_id = _insert_room(
            connection,
            environment.tables,
            subject=None,
            topic=None,
            mode="LEGACY_PHYSICS",
            education_level=None,
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=legacy_room_id,
            viewer_membership_id=legacy_membership_id,
            started_at=BASE_TIME + timedelta(minutes=6),
            mode="LEGACY_PHYSICS",
            education_level=None,
            subject=None,
            topic=None,
            questions=(_QuestionSeed(1, "legacy", "GRADED", 1),),
        )

        level_room_id, level_membership_id = _insert_room(
            connection,
            environment.tables,
            education_level="A_LEVEL",
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=level_room_id,
            viewer_membership_id=level_membership_id,
            started_at=BASE_TIME + timedelta(minutes=7),
            education_level="A_LEVEL",
            questions=(_QuestionSeed(1, "wrong-level", "GRADED", 1),),
        )

    response = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_evidence"
    assert payload["session_window"] == {
        "limit": 100,
        "included": 4,
        "truncated": False,
    }
    assert len(payload["topics"]) == 1
    topic = payload["topics"][0]
    assert topic["subject"] == "physics"
    assert topic["topic"] == "energy"
    assert topic["finished_session_count"] == 4
    assert topic["graded_attempt_count"] == 4
    assert topic["earned_marks"] == 3
    assert topic["possible_marks"] == 5
    assert topic["accuracy_on_graded_answers_percent"] == 60.0
    assert topic["full_credit_attempt_count"] == 2
    assert topic["partial_credit_attempt_count"] == 1
    assert topic["zero_credit_attempt_count"] == 1
    assert payload["strongest_topics"] == []
    assert payload["weakest_topics"] == []
    assert set(payload) == {
        "status",
        "session_window",
        "topics",
        "strongest_topics",
        "weakest_topics",
    }
    assert set(topic) == {
        "subject",
        "topic",
        "evidence_status",
        "finished_session_count",
        "presented_question_count",
        "answered_attempt_count",
        "graded_attempt_count",
        "ungraded_attempt_count",
        "unanswered_question_count",
        "distinct_question_count",
        "repeat_attempt_count",
        "earned_marks",
        "possible_marks",
        "accuracy_on_graded_answers_percent",
        "full_credit_attempt_count",
        "partial_credit_attempt_count",
        "zero_credit_attempt_count",
    }
    response_text = response.text
    assert "viewer-fingerprint" not in response_text
    assert "closed-room" not in response_text
    assert "session_id" not in response_text
    assert "answer_text" not in response_text

    assert environment.client.get(
        "/me/learning-summary?user_id=" + str(PEER_ID),
        headers=auth_headers(VIEWER_TOKEN),
    ).status_code == 422


def test_no_data_keeps_answer_coverage_and_rejects_open_response_fields(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    with environment.engine.begin() as connection:
        room_id, membership_id = _insert_room(connection, environment.tables)
        _insert_session(
            connection,
            environment.tables,
            room_id=room_id,
            viewer_membership_id=membership_id,
            started_at=BASE_TIME,
            questions=(
                _QuestionSeed(1, "unanswered"),
                _QuestionSeed(2, "pending", "PENDING"),
                _QuestionSeed(3, "unavailable", "UNAVAILABLE"),
            ),
        )

    response = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["session_window"] == {
        "limit": 100,
        "included": 1,
        "truncated": False,
    }
    topic = payload["topics"][0]
    assert topic["evidence_status"] == "no_data"
    assert topic["presented_question_count"] == 3
    assert topic["answered_attempt_count"] == 2
    assert topic["graded_attempt_count"] == 0
    assert topic["ungraded_attempt_count"] == 2
    assert topic["unanswered_question_count"] == 1
    assert topic["earned_marks"] == 0
    assert topic["possible_marks"] == 0
    assert topic["accuracy_on_graded_answers_percent"] is None
    assert payload["strongest_topics"] == []
    assert payload["weakest_topics"] == []
    assert response.headers["cache-control"] == "no-store"
    with pytest.raises(ValidationError):
        LearningSummaryResponse.model_validate({**payload, "unexpected": "value"})
    with pytest.raises(ValidationError):
        LearningSummaryResponse.model_validate({**payload, "topics": []})


def test_current_review_still_rejects_left_and_closed_rooms(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    with environment.engine.begin() as connection:
        left_room_id, left_membership_id = _insert_room(
            connection, environment.tables, viewer_left=True
        )
        left_session_id = _insert_session(
            connection,
            environment.tables,
            room_id=left_room_id,
            viewer_membership_id=left_membership_id,
            started_at=BASE_TIME,
            questions=(_QuestionSeed(1, "left-review"),),
        )
        closed_room_id, closed_membership_id = _insert_room(
            connection, environment.tables, closed=True
        )
        closed_session_id = _insert_session(
            connection,
            environment.tables,
            room_id=closed_room_id,
            viewer_membership_id=closed_membership_id,
            started_at=BASE_TIME + timedelta(minutes=1),
            questions=(_QuestionSeed(1, "closed-review"),),
        )

    summary = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert summary.status_code == 200
    assert summary.json()["session_window"]["included"] == 2

    left_review = environment.client.get(
        f"/rooms/{left_room_id}/sessions/{left_session_id}/review",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert left_review.status_code == 403
    assert left_review.json()["error"]["code"] == "not_room_member"

    closed_review = environment.client.get(
        f"/rooms/{closed_room_id}/sessions/{closed_session_id}/review",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert closed_review.status_code == 409
    assert closed_review.json()["error"]["code"] == "room_closed"


def test_auth_suspension_and_deleted_profile_gates_are_preserved(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    environment.users.suspend(LEARNER_ID, "safety_review")
    suspended = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert suspended.status_code == 403
    assert suspended.json()["error"]["code"] == "account_suspended"
    environment.users.unsuspend(LEARNER_ID)

    class _DeletedProfileRepository:
        def get_by_id(self, user_id: UUID) -> User:
            return User(
                id=user_id,
                display_name="Deleted User",
                created_at=BASE_TIME,
                updated_at=BASE_TIME,
                deleted_at=BASE_TIME,
            )

    environment.app.state.user_repository = _DeletedProfileRepository()
    deleted = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert deleted.status_code == 403
    assert deleted.json()["error"]["code"] == "account_deleted"


def test_summary_disappears_when_account_deletion_or_retention_removes_sources(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    with environment.engine.begin() as connection:
        purge_room_id, purge_membership_id = _insert_room(
            connection, environment.tables, closed=True
        )
        purge_session_id = _insert_session(
            connection,
            environment.tables,
            room_id=purge_room_id,
            viewer_membership_id=purge_membership_id,
            started_at=BASE_TIME,
            questions=(_QuestionSeed(1, "purged", "GRADED", 1),),
        )
        deletion_room_id, deletion_membership_id = _insert_room(
            connection, environment.tables, viewer_left=True
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=deletion_room_id,
            viewer_membership_id=deletion_membership_id,
            started_at=BASE_TIME + timedelta(minutes=1),
            questions=(_QuestionSeed(1, "account-deleted", "GRADED", 1),),
        )

    initial = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    ).json()
    assert initial["session_window"]["included"] == 2

    # The retention purge removes the closed-room session graph before its room.
    with environment.session_factory() as session, session.begin():
        session.execute(
            delete(AnswerSubmissionModel).where(
                AnswerSubmissionModel.session_id == purge_session_id
            )
        )
        session.execute(
            delete(SessionQuestionModel).where(
                SessionQuestionModel.session_id == purge_session_id
            )
        )
        session.execute(
            delete(SessionParticipantModel).where(
                SessionParticipantModel.session_id == purge_session_id
            )
        )
        session.execute(
            delete(QuizSessionModel).where(QuizSessionModel.id == purge_session_id)
        )
        session.execute(
            delete(RoomMembershipModel).where(
                RoomMembershipModel.room_id == purge_room_id
            )
        )
        session.execute(delete(RoomModel).where(RoomModel.id == purge_room_id))

    after_purge = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    ).json()
    assert after_purge["session_window"]["included"] == 1

    # Account deletion removes the viewer's answers before participant and
    # membership rows, making their retained sessions ineligible without cache.
    with environment.session_factory() as session, session.begin():
        participant_ids = select(SessionParticipantModel.id).where(
            SessionParticipantModel.user_id == LEARNER_ID
        )
        session.execute(
            delete(AnswerSubmissionModel).where(
                AnswerSubmissionModel.participant_id.in_(participant_ids)
            )
        )
        session.execute(
            delete(SessionParticipantModel).where(
                SessionParticipantModel.user_id == LEARNER_ID
            )
        )
        session.execute(
            delete(RoomMembershipModel).where(
                RoomMembershipModel.user_id == LEARNER_ID
            )
        )

    after_deletion = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    ).json()
    assert after_deletion["status"] == "no_data"
    assert after_deletion["session_window"]["included"] == 0
    assert after_deletion["topics"] == []


def test_query_caps_history_to_101_sessions_and_4000_question_rows(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    with environment.engine.begin() as connection:
        room_id, membership_id = _insert_room(connection, environment.tables)
        session_rows = []
        participant_rows = []
        question_rows = []
        for session_number in range(101):
            session_id = uuid4()
            session_rows.append(
                {
                    "id": session_id,
                    "room_id": room_id,
                    "preparation_id": uuid4(),
                    "question_bank_key": "adaptive:bounded-test",
                    "quiz_mode": "ADAPTIVE",
                    "education_level": "GCSE",
                    "quiz_subject": "physics",
                    "quiz_topic": "energy",
                    "total_available_marks": 40,
                    "status": "FINISHED",
                    "current_question_position": 40,
                    "state_version": 41,
                    "reveal_ends_at": None,
                    "started_at": BASE_TIME + timedelta(seconds=session_number),
                    "finished_at": BASE_TIME + timedelta(seconds=session_number + 1),
                }
            )
            participant_rows.append(
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "user_id": LEARNER_ID,
                    "room_membership_id": membership_id,
                    "display_name_snapshot": "Learning Student",
                    "created_at": BASE_TIME + timedelta(seconds=session_number),
                }
            )
            for position in range(40):
                question_rows.append(
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "position": position,
                        "max_marks": 1,
                        "content_fingerprint": f"fp-{session_number}-{position}",
                    }
                )
        connection.execute(environment.tables.sessions.insert(), session_rows)
        connection.execute(
            environment.tables.participants.insert(), participant_rows
        )
        connection.execute(environment.tables.questions.insert(), question_rows)

    response = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_window"] == {
        "limit": 100,
        "included": 100,
        "truncated": True,
    }
    topic = payload["topics"][0]
    assert topic["finished_session_count"] == 100
    assert topic["presented_question_count"] == 4_000
    assert topic["unanswered_question_count"] == 4_000
    assert topic["graded_attempt_count"] == 0


def test_session_window_orders_by_finished_time_not_started_time(
    learning_environment: _Environment,
) -> None:
    environment = learning_environment
    with environment.engine.begin() as connection:
        energy_room_id, energy_membership_id = _insert_room(
            connection, environment.tables, topic="energy"
        )
        for session_number in range(100):
            _insert_session(
                connection,
                environment.tables,
                room_id=energy_room_id,
                viewer_membership_id=energy_membership_id,
                started_at=BASE_TIME + timedelta(seconds=session_number),
                finished_at_offset=timedelta(seconds=102),
                topic="energy",
            )

        later_started_room_id, later_started_membership_id = _insert_room(
            connection, environment.tables, topic="forces"
        )
        _insert_session(
            connection,
            environment.tables,
            room_id=later_started_room_id,
            viewer_membership_id=later_started_membership_id,
            started_at=BASE_TIME + timedelta(seconds=100),
            finished_at_offset=timedelta(seconds=1),
            topic="forces",
        )

    response = environment.client.get(
        "/me/learning-summary",
        headers=auth_headers(VIEWER_TOKEN),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_window"] == {
        "limit": 100,
        "included": 100,
        "truncated": True,
    }
    assert [topic["topic"] for topic in payload["topics"]] == ["energy"]
    assert payload["topics"][0]["finished_session_count"] == 100


def _observed_records(
    session_ids: tuple[UUID, UUID],
    subject: str,
    topic: str,
    scores: tuple[tuple[int, str, int], ...],
) -> tuple[tuple[EligibleLearningSession, ...], tuple[LearningQuestionRecord, ...]]:
    sessions = tuple(
        EligibleLearningSession(session_id, subject, topic)
        for session_id in session_ids
    )
    split = (len(scores) + 1) // 2
    questions = tuple(
        LearningQuestionRecord(
            session_id=session_ids[0] if index < split else session_ids[1],
            max_marks=max_marks,
            content_fingerprint=fingerprint,
            has_submission=True,
            grading_status="GRADED",
            earned_marks=earned_marks,
        )
        for index, (max_marks, fingerprint, earned_marks) in enumerate(scores)
    )
    return sessions, questions


def test_partial_credit_repeats_and_exact_within_subject_ties() -> None:
    energy_sessions, energy_questions = _observed_records(
        (uuid4(), uuid4()),
        "physics",
        "energy",
        (
            (2, "energy-1", 1),
            (2, "energy-2", 2),
            (2, "energy-3", 0),
            (2, "energy-4", 1),
            (1, "energy-5", 1),
            (2, "energy-1", 1),
        ),
    )
    forces_sessions, forces_questions = _observed_records(
        (uuid4(), uuid4()),
        "physics",
        "forces",
        (
            (2, "forces-1", 2),
            (2, "forces-2", 1),
            (2, "forces-3", 0),
            (2, "forces-4", 1),
            (1, "forces-5", 1),
            (2, "forces-1", 1),
        ),
    )
    biology_sessions, biology_questions = _observed_records(
        (uuid4(), uuid4()),
        "biology",
        "ecology",
        tuple((1, f"ecology-{index}", 1) for index in range(5)),
    )
    result = summarize_learning_data(
        energy_sessions + forces_sessions + biology_sessions,
        energy_questions
        + forces_questions
        + biology_questions
        + (
            LearningQuestionRecord(
                session_id=energy_sessions[1].session_id,
                max_marks=2,
                content_fingerprint="energy-ungraded",
                has_submission=True,
                grading_status="PENDING",
                earned_marks=None,
            ),
            LearningQuestionRecord(
                session_id=energy_sessions[1].session_id,
                max_marks=1,
                content_fingerprint="energy-unanswered",
                has_submission=False,
                grading_status=None,
                earned_marks=None,
            ),
        ),
        truncated=False,
    )
    response = LearningSummaryResponse.from_result(result)
    energy = next(topic for topic in response.topics if topic.topic == "energy")
    assert energy.evidence_status == "observed"
    assert energy.presented_question_count == 8
    assert energy.answered_attempt_count == 7
    assert energy.ungraded_attempt_count == 1
    assert energy.unanswered_question_count == 1
    assert energy.graded_attempt_count == 6
    assert energy.earned_marks == 6
    assert energy.possible_marks == 11
    assert energy.accuracy_on_graded_answers_percent == 54.5
    assert energy.distinct_question_count == 5
    assert energy.repeat_attempt_count == 1
    assert energy.full_credit_attempt_count == 2
    assert energy.partial_credit_attempt_count == 3
    assert energy.zero_credit_attempt_count == 1
    assert response.strongest_topics == (
        response.weakest_topics[0],
        response.weakest_topics[1],
    )
    assert {(key.subject, key.topic) for key in response.strongest_topics} == {
        ("physics", "energy"),
        ("physics", "forces"),
    }
    assert all(key.subject == "physics" for key in response.weakest_topics)


def test_relative_topics_use_exact_ratio_when_display_rounding_ties() -> None:
    sessions: list[EligibleLearningSession] = []
    questions: list[LearningQuestionRecord] = []
    for topic, possible_total, earned_total in (
        ("energy", 6_000, 4_000),
        ("forces", 5_999, 3_999),
    ):
        topic_sessions = tuple(uuid4() for _ in range(25))
        sessions.extend(
            EligibleLearningSession(session_id, "physics", topic)
            for session_id in topic_sessions
        )
        for index in range(1_000):
            max_marks = (
                5
                if topic == "forces" and index == 999
                else 6
            )
            if topic == "energy":
                earned_marks = 6 if index < 666 else 1 if index < 670 else 0
            else:
                earned_marks = 6 if index < 600 else 1 if index < 999 else 0
            fingerprint = f"{topic}-fingerprint-{index % 5}"
            questions.append(
                LearningQuestionRecord(
                    session_id=topic_sessions[index // 40],
                    max_marks=max_marks,
                    content_fingerprint=fingerprint,
                    has_submission=True,
                    grading_status="GRADED",
                    earned_marks=earned_marks,
                )
            )
        assert sum(question.max_marks for question in questions if question.session_id in topic_sessions) == possible_total
        assert sum(question.earned_marks or 0 for question in questions if question.session_id in topic_sessions) == earned_total

    result = summarize_learning_data(tuple(sessions), tuple(questions), truncated=False)
    summary = LearningSummaryResponse.from_result(result)
    topic_rates = {
        topic.topic: topic.accuracy_on_graded_answers_percent
        for topic in summary.topics
    }
    assert topic_rates == {"energy": 66.7, "forces": 66.7}
    assert [(topic.subject, topic.topic) for topic in summary.strongest_topics] == [
        ("physics", "energy")
    ]
    assert [(topic.subject, topic.topic) for topic in summary.weakest_topics] == [
        ("physics", "forces")
    ]
