from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.session import Database
from app.domain.constants import PHYSICS_SPRINT_BANK_KEY
from app.domain.member import RoomMember
from app.domain.quiz import QuizSessionStatus
from app.repositories.postgres_questions import PostgresQuestionRepository
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.scripts.seed_questions import seed_physics_sprint
from app.services.rooms import RoomService
from tests.conftest import OWNER_ID


SECOND_USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _create_room(
    postgres_service: RoomService,
    *,
    name: str = "Physics Sprint",
) -> UUID:
    return postgres_service.create_room(
        name=name,
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    ).id


def _owner_membership_id(database: Database, room_id: UUID) -> UUID:
    with database.session_factory() as session:
        membership_id = session.scalar(
            select(RoomMembershipModel.id).where(
                RoomMembershipModel.room_id == room_id,
                RoomMembershipModel.user_id == OWNER_ID,
                RoomMembershipModel.left_at.is_(None),
            )
        )
    assert membership_id is not None
    return membership_id


def _register_second_member(
    database: Database,
    room_id: UUID,
    postgres_user_repository: PostgresUserRepository,
) -> UUID:
    postgres_user_repository.upsert_profile(SECOND_USER_ID, "Second User")
    membership_repository = PostgresMembershipRepository(database.session_factory)
    membership_repository.join(
        RoomMember(
            user_id=SECOND_USER_ID,
            display_name="Second User",
            room_id=room_id,
        ),
        8,
    )
    with database.session_factory() as session:
        membership_id = session.scalar(
            select(RoomMembershipModel.id).where(
                RoomMembershipModel.room_id == room_id,
                RoomMembershipModel.user_id == SECOND_USER_ID,
                RoomMembershipModel.left_at.is_(None),
            )
        )
    assert membership_id is not None
    return membership_id


def _seed_questions(database: Database) -> tuple[UUID, ...]:
    assert seed_physics_sprint(database.session_factory) == 5
    repository = PostgresQuestionRepository(database.session_factory)
    questions = repository.list_active_by_bank(PHYSICS_SPRINT_BANK_KEY)
    assert len(questions) == 5
    return tuple(question.id for question in questions)


def _add_session(
    database: Database,
    room_id: UUID,
    *,
    status: QuizSessionStatus = QuizSessionStatus.QUESTION_OPEN,
) -> UUID:
    session_id = uuid4()
    finished_at = (
        datetime.now(timezone.utc) if status is QuizSessionStatus.FINISHED else None
    )
    with database.session_factory() as session:
        with session.begin():
            session.add(
                QuizSessionModel(
                    id=session_id,
                    room_id=room_id,
                    question_bank_key=PHYSICS_SPRINT_BANK_KEY,
                    status=status.value,
                    finished_at=finished_at,
                )
            )
    return session_id


def _add_participant(
    database: Database,
    session_id: UUID,
    *,
    user_id: UUID = OWNER_ID,
    room_membership_id: UUID,
    display_name: str = "Room Owner",
) -> UUID:
    participant_id = uuid4()
    with database.session_factory() as session:
        with session.begin():
            session.add(
                SessionParticipantModel(
                    id=participant_id,
                    session_id=session_id,
                    user_id=user_id,
                    room_membership_id=room_membership_id,
                    display_name_snapshot=display_name,
                )
            )
    return participant_id


def _add_session_question(
    database: Database,
    session_id: UUID,
    source_question_id: UUID,
    *,
    position: int = 0,
) -> UUID:
    question_id = uuid4()
    with database.session_factory() as session:
        with session.begin():
            session.add(
                SessionQuestionModel(
                    id=question_id,
                    session_id=session_id,
                    source_question_id=source_question_id,
                    position=position,
                    prompt_snapshot="What is the SI unit of force?",
                    options_snapshot=[
                        {"id": "joule", "label": "Joule"},
                        {"id": "newton", "label": "Newton"},
                        {"id": "watt", "label": "Watt"},
                        {"id": "pascal", "label": "Pascal"},
                    ],
                    correct_option_id="newton",
                    duration_seconds=20,
                )
            )
    return question_id


def _add_answer(
    database: Database,
    session_id: UUID,
    question_id: UUID,
    participant_id: UUID,
    *,
    response_time_ms: int = 500,
    is_correct: bool = True,
    points: int = 100,
) -> UUID:
    answer_id = uuid4()
    with database.session_factory() as session:
        with session.begin():
            session.add(
                AnswerSubmissionModel(
                    id=answer_id,
                    session_id=session_id,
                    session_question_id=question_id,
                    participant_id=participant_id,
                    selected_option_id="newton",
                    response_time_ms=response_time_ms,
                    is_correct=is_correct,
                    points=points,
                )
            )
    return answer_id


def _assert_insert_fails(
    database: Database,
    model: (
        AnswerSubmissionModel
        | QuizSessionModel
        | SessionParticipantModel
        | SessionQuestionModel
    ),
) -> None:
    with database.session_factory() as session:
        session.add(model)
        with pytest.raises(IntegrityError):
            session.commit()


def test_physics_seed_inserts_five_questions_and_is_idempotent(
    postgres_database: Database,
) -> None:
    first_count = seed_physics_sprint(postgres_database.session_factory)
    second_count = seed_physics_sprint(postgres_database.session_factory)
    repository = PostgresQuestionRepository(postgres_database.session_factory)

    questions = repository.list_active_by_bank(PHYSICS_SPRINT_BANK_KEY)

    assert first_count == 5
    assert second_count == 5
    assert len(questions) == 5
    assert [question.position for question in questions] == [0, 1, 2, 3, 4]
    with postgres_database.session_factory() as session:
        assert session.scalar(
            select(QuizSessionModel.id).limit(1)
        ) is None


def test_one_active_session_per_room_is_database_enforced(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    _add_session(postgres_database, room_id)

    _assert_insert_fails(
        postgres_database,
        QuizSessionModel(
            id=uuid4(),
            room_id=room_id,
            question_bank_key=PHYSICS_SPRINT_BANK_KEY,
            status=QuizSessionStatus.QUESTION_REVEAL.value,
        ),
    )


def test_finished_session_does_not_block_a_future_session(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    finished_id = _add_session(
        postgres_database,
        room_id,
        status=QuizSessionStatus.FINISHED,
    )

    future_id = _add_session(postgres_database, room_id)

    assert future_id != finished_id


def test_session_participant_user_and_membership_uniqueness(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_room(postgres_service)
    second_membership_id = _register_second_member(
        postgres_database,
        room_id,
        postgres_user_repository,
    )
    owner_membership_id = _owner_membership_id(postgres_database, room_id)
    session_id = _add_session(postgres_database, room_id)
    _add_participant(
        postgres_database,
        session_id,
        room_membership_id=owner_membership_id,
    )

    _assert_insert_fails(
        postgres_database,
        SessionParticipantModel(
            id=uuid4(),
            session_id=session_id,
            user_id=OWNER_ID,
            room_membership_id=second_membership_id,
            display_name_snapshot="Room Owner",
        ),
    )
    _assert_insert_fails(
        postgres_database,
        SessionParticipantModel(
            id=uuid4(),
            session_id=session_id,
            user_id=SECOND_USER_ID,
            room_membership_id=owner_membership_id,
            display_name_snapshot="Second User",
        ),
    )


def test_cross_session_participant_and_question_references_are_rejected(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    source_question_ids = _seed_questions(postgres_database)
    owner_membership_id = _owner_membership_id(postgres_database, room_id)
    first_session_id = _add_session(postgres_database, room_id)
    second_session_id = _add_session(
        postgres_database,
        room_id,
        status=QuizSessionStatus.FINISHED,
    )
    first_participant_id = _add_participant(
        postgres_database,
        first_session_id,
        room_membership_id=owner_membership_id,
    )
    second_participant_id = _add_participant(
        postgres_database,
        second_session_id,
        room_membership_id=owner_membership_id,
    )
    first_question_id = _add_session_question(
        postgres_database,
        first_session_id,
        source_question_ids[0],
    )
    second_question_id = _add_session_question(
        postgres_database,
        second_session_id,
        source_question_ids[1],
    )

    _assert_insert_fails(
        postgres_database,
        AnswerSubmissionModel(
            id=uuid4(),
            session_id=first_session_id,
            session_question_id=first_question_id,
            participant_id=second_participant_id,
            selected_option_id="newton",
            response_time_ms=500,
            is_correct=True,
            points=100,
        ),
    )
    _assert_insert_fails(
        postgres_database,
        AnswerSubmissionModel(
            id=uuid4(),
            session_id=first_session_id,
            session_question_id=second_question_id,
            participant_id=first_participant_id,
            selected_option_id="newton",
            response_time_ms=500,
            is_correct=True,
            points=100,
        ),
    )


def test_session_question_position_and_source_are_unique(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    source_question_ids = _seed_questions(postgres_database)
    session_id = _add_session(postgres_database, room_id)
    _add_session_question(postgres_database, session_id, source_question_ids[0])

    _assert_insert_fails(
        postgres_database,
        SessionQuestionModel(
            id=uuid4(),
            session_id=session_id,
            source_question_id=source_question_ids[1],
            position=0,
            prompt_snapshot="Second question",
            options_snapshot=[
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
            correct_option_id="a",
            duration_seconds=20,
        ),
    )
    _assert_insert_fails(
        postgres_database,
        SessionQuestionModel(
            id=uuid4(),
            session_id=session_id,
            source_question_id=source_question_ids[0],
            position=1,
            prompt_snapshot="Duplicate source",
            options_snapshot=[
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
            correct_option_id="a",
            duration_seconds=20,
        ),
    )


def test_answer_is_unique_per_question_and_participant(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    source_question_ids = _seed_questions(postgres_database)
    owner_membership_id = _owner_membership_id(postgres_database, room_id)
    session_id = _add_session(postgres_database, room_id)
    participant_id = _add_participant(
        postgres_database,
        session_id,
        room_membership_id=owner_membership_id,
    )
    question_id = _add_session_question(
        postgres_database,
        session_id,
        source_question_ids[0],
    )
    _add_answer(postgres_database, session_id, question_id, participant_id)

    _assert_insert_fails(
        postgres_database,
        AnswerSubmissionModel(
            id=uuid4(),
            session_id=session_id,
            session_question_id=question_id,
            participant_id=participant_id,
            selected_option_id="newton",
            response_time_ms=600,
            is_correct=True,
            points=100,
        ),
    )


@pytest.mark.parametrize(
    ("is_correct", "points", "response_time_ms"),
    [
        (True, 0, 500),
        (False, 100, 500),
        (True, 50, 500),
        (True, 100, -1),
    ],
)
def test_answer_correctness_points_and_response_constraints(
    postgres_database: Database,
    postgres_service: RoomService,
    is_correct: bool,
    points: int,
    response_time_ms: int,
) -> None:
    room_id = _create_room(postgres_service)
    source_question_ids = _seed_questions(postgres_database)
    owner_membership_id = _owner_membership_id(postgres_database, room_id)
    session_id = _add_session(postgres_database, room_id)
    participant_id = _add_participant(
        postgres_database,
        session_id,
        room_membership_id=owner_membership_id,
    )
    question_id = _add_session_question(
        postgres_database,
        session_id,
        source_question_ids[0],
    )

    _assert_insert_fails(
        postgres_database,
        AnswerSubmissionModel(
            id=uuid4(),
            session_id=session_id,
            session_question_id=question_id,
            participant_id=participant_id,
            selected_option_id="newton",
            response_time_ms=response_time_ms,
            is_correct=is_correct,
            points=points,
        ),
    )


def test_ready_at_persists_for_active_membership(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    membership_id = _owner_membership_id(postgres_database, room_id)
    ready_at = datetime.now(timezone.utc)

    with postgres_database.session_factory() as session:
        with session.begin():
            membership = session.get(RoomMembershipModel, membership_id)
            assert membership is not None
            membership.ready_at = ready_at

    with postgres_database.session_factory() as session:
        membership = session.get(RoomMembershipModel, membership_id)
        assert membership is not None
        assert membership.ready_at == ready_at


def test_postgres_quiz_repositories_load_snapshots_and_derive_leaderboard(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    source_question_ids = _seed_questions(postgres_database)
    owner_membership_id = _owner_membership_id(postgres_database, room_id)
    session_id = _add_session(postgres_database, room_id)
    participant_id = _add_participant(
        postgres_database,
        session_id,
        room_membership_id=owner_membership_id,
    )
    question_id = _add_session_question(
        postgres_database,
        session_id,
        source_question_ids[0],
    )
    _add_answer(postgres_database, session_id, question_id, participant_id)

    session_repository = PostgresQuizSessionRepository(
        postgres_database.session_factory
    )
    question_repository = PostgresQuestionRepository(postgres_database.session_factory)

    session = session_repository.get_active_by_room(room_id)
    questions = session_repository.list_questions(session_id)
    participants = session_repository.list_participants(session_id)
    submissions = session_repository.list_submissions(session_id)
    leaderboard = session_repository.derive_leaderboard(session_id)

    assert session is not None
    assert session.id == session_id
    assert len(question_repository.list_active_by_bank(PHYSICS_SPRINT_BANK_KEY)) == 5
    assert len(questions) == 1
    assert questions[0].correct_option_id == "newton"
    assert len(participants) == 1
    assert len(submissions) == 1
    assert leaderboard[0].points == 100
    assert leaderboard[0].correct_count == 1
    assert leaderboard[0].rank == 1
