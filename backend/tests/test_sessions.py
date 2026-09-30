from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from typing import Callable
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import FakeAuthVerifier
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.session import Database
from app.domain.errors import (
    AnswerAlreadySubmittedError,
    AnswerTooLateError,
    InsufficientParticipantsError,
    InvalidOptionError,
    NotRoomMemberError,
    NotSessionParticipantError,
    ParticipantsNotReadyError,
    QuestionBankUnavailableError,
    QuestionNotOpenError,
    RoomOwnerRequiredError,
    SessionAlreadyActiveError,
    SessionNotActiveError,
    StaleSessionQuestionError,
)
from app.domain.member import RoomMember
from app.domain.quiz import QuizSessionStatus
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.realtime.publisher import room_state_payload, state_snapshot_payload
from app.scripts.seed_questions import seed_physics_sprint
from app.schemas.quiz import SessionStateResponse
from app.services.rooms import RoomService
from app.services.sessions import SessionService
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


SECOND_USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
THIRD_USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
FOURTH_USER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _register_user(
    repository: PostgresUserRepository,
    user_id: UUID,
    display_name: str,
) -> None:
    repository.upsert_profile(user_id, display_name)


def _add_member(
    database: Database,
    repository: PostgresUserRepository,
    room_id: UUID,
    user_id: UUID,
    display_name: str,
    maximum_members: int = 8,
) -> UUID:
    _register_user(repository, user_id, display_name)
    membership_repository = PostgresMembershipRepository(database.session_factory)
    membership_repository.join(
        RoomMember(
            user_id=user_id,
            display_name=display_name,
            room_id=room_id,
        ),
        maximum_members,
    )
    with database.session_factory() as session:
        membership_id = session.scalar(
            select(RoomMembershipModel.id).where(
                RoomMembershipModel.room_id == room_id,
                RoomMembershipModel.user_id == user_id,
                RoomMembershipModel.left_at.is_(None),
            )
        )
    assert membership_id is not None
    return membership_id


def _create_two_member_room(
    database: Database,
    room_service: RoomService,
    user_repository: PostgresUserRepository,
) -> UUID:
    room = room_service.create_room(
        name="Physics Sprint",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    _add_member(database, user_repository, room.id, SECOND_USER_ID, "Second User")
    return room.id


def _seed_startable_session(
    database: Database,
    room_service: RoomService,
    session_service: SessionService,
    user_repository: PostgresUserRepository,
) -> tuple[UUID, UUID]:
    room_id = _create_two_member_room(database, room_service, user_repository)
    assert seed_physics_sprint(database.session_factory) == 5
    session_service.set_ready(room_id, SECOND_USER_ID, True)
    session = session_service.start_session(room_id, OWNER_ID)
    with database.session_factory() as db_session:
        question_id = db_session.scalar(
            select(SessionQuestionModel.id).where(
                SessionQuestionModel.session_id == session.id,
                SessionQuestionModel.position == 0,
            )
        )
    assert question_id is not None
    return room_id, question_id


def _force_current_question_closed(database: Database, session_id: UUID) -> None:
    with database.session_factory() as session:
        with session.begin():
            session_model = session.get(QuizSessionModel, session_id)
            assert session_model is not None
            question = session.scalar(
                select(SessionQuestionModel).where(
                    SessionQuestionModel.session_id == session_id,
                    SessionQuestionModel.position
                    == session_model.current_question_position,
                )
            )
            assert question is not None
            now = datetime.now(timezone.utc)
            question.opened_at = now - timedelta(seconds=2)
            question.closes_at = now - timedelta(seconds=1)


def _force_reveal_expired(database: Database, session_id: UUID) -> None:
    with database.session_factory() as session:
        with session.begin():
            session_model = session.get(QuizSessionModel, session_id)
            assert session_model is not None
            session_model.reveal_ends_at = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            )


def _current_session(database: Database, room_id: UUID) -> QuizSessionModel:
    with database.session_factory() as session:
        model = session.scalar(
            select(QuizSessionModel).where(
                QuizSessionModel.room_id == room_id,
                QuizSessionModel.status.in_(("QUESTION_OPEN", "QUESTION_REVEAL")),
            )
        )
    assert model is not None
    return model


def _finish_session(
    database: Database,
    session_service: SessionService,
    session_id: UUID,
) -> None:
    current = session_service.get_session(session_id)
    assert current is not None
    while current.status is not QuizSessionStatus.FINISHED:
        if current.status is QuizSessionStatus.QUESTION_OPEN:
            _force_current_question_closed(database, session_id)
        else:
            _force_reveal_expired(database, session_id)
        reconciled = session_service.reconcile_session(session_id=session_id)
        assert reconciled is not None
        current = reconciled


def _concurrently(
    functions: tuple[Callable[[], object], Callable[[], object]],
) -> list[tuple[str, object]]:
    barrier = Barrier(2)

    def run(function: Callable[[], object]) -> tuple[str, object]:
        barrier.wait(timeout=10)
        try:
            return "ok", function()
        except Exception as error:  # noqa: BLE001 - test captures race outcomes
            return type(error).__name__, error

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(run, functions))


def test_ready_is_desired_state_and_idempotent(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )

    first = postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    repeated = postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    cleared = postgres_session_service.set_ready(room_id, SECOND_USER_ID, False)

    assert first.ready is True
    assert repeated.ready_at == first.ready_at
    assert cleared.ready is False
    assert cleared.ready_at is None


def test_non_member_cannot_set_ready(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )

    with pytest.raises(NotRoomMemberError):
        postgres_session_service.set_ready(room_id, THIRD_USER_ID, True)


def test_start_requires_owner_two_members_and_readiness(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    with pytest.raises(ParticipantsNotReadyError):
        postgres_session_service.start_session(room_id, OWNER_ID)
    with pytest.raises(RoomOwnerRequiredError):
        postgres_session_service.start_session(room_id, SECOND_USER_ID)

    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    with pytest.raises(QuestionBankUnavailableError):
        postgres_session_service.start_session(room_id, OWNER_ID)

    with postgres_database.session_factory() as session:
        assert session.scalar(
            select(func.count(QuizSessionModel.id)).where(
                QuizSessionModel.room_id == room_id
            )
        ) == 0
        assert session.scalar(
            select(func.count(SessionParticipantModel.id))
        ) == 0
        assert session.scalar(
            select(func.count(SessionQuestionModel.id))
        ) == 0


def test_start_with_one_participant_fails(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
) -> None:
    room = postgres_service.create_room(
        name="Solo Room",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    seed_physics_sprint(postgres_database.session_factory)

    with pytest.raises(InsufficientParticipantsError):
        postgres_session_service.start_session(room.id, OWNER_ID)


def test_start_snapshots_participants_questions_and_clears_ready(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    seed_physics_sprint(postgres_database.session_factory)
    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    started = postgres_session_service.start_session(room_id, OWNER_ID)

    with postgres_database.session_factory() as session:
        participants = session.scalars(
            select(SessionParticipantModel).where(
                SessionParticipantModel.session_id == started.id
            )
        ).all()
        questions = session.scalars(
            select(SessionQuestionModel)
            .where(SessionQuestionModel.session_id == started.id)
            .order_by(SessionQuestionModel.position)
        ).all()
        memberships = session.scalars(
            select(RoomMembershipModel).where(RoomMembershipModel.room_id == room_id)
        ).all()

    assert len(participants) == 2
    assert len(questions) == 5
    assert questions[0].opened_at is not None
    assert questions[0].closes_at is not None
    assert questions[0].closes_at > questions[0].opened_at
    assert all(question.opened_at is None for question in questions[1:])
    assert all(membership.ready_at is None for membership in memberships)
    assert questions[0].correct_option_id == "newton"

    snapshot = postgres_session_service.get_state_snapshot(room_id, OWNER_ID)
    response = SessionStateResponse.from_domain(snapshot).model_dump()
    assert response["question"] is not None
    assert "correct_option_id" not in response["question"]
    assert all(entry.total_points == 0 for entry in snapshot.leaderboard)


def test_ready_is_rejected_after_session_starts(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, _ = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )

    with pytest.raises(SessionAlreadyActiveError):
        postgres_session_service.set_ready(room_id, SECOND_USER_ID, False)


def test_non_member_snapshot_read_does_not_reconcile_room_state(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, _ = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    session = _current_session(postgres_database, room_id)
    _force_current_question_closed(postgres_database, session.id)

    with pytest.raises(NotRoomMemberError):
        postgres_session_service.get_state_snapshot(room_id, THIRD_USER_ID)

    with postgres_database.session_factory() as db_session:
        persisted = db_session.get(QuizSessionModel, session.id)
    assert persisted is not None
    assert persisted.status == QuizSessionStatus.QUESTION_OPEN.value


def test_answers_are_server_scored_and_duplicate_retry_is_safe(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    correct = postgres_session_service.submit_answer(
        room_id,
        OWNER_ID,
        question_id,
        "newton",
    )
    repeated = postgres_session_service.submit_answer(
        room_id,
        OWNER_ID,
        question_id,
        "newton",
    )
    with pytest.raises(AnswerAlreadySubmittedError):
        postgres_session_service.submit_answer(
            room_id,
            OWNER_ID,
            question_id,
            "joule",
        )
    incorrect = postgres_session_service.submit_answer(
        room_id,
        SECOND_USER_ID,
        question_id,
        "joule",
    )

    assert repeated.submission_id == correct.submission_id
    assert not hasattr(correct, "is_correct")
    with postgres_database.session_factory() as session:
        answers = session.scalars(
            select(AnswerSubmissionModel).where(
                AnswerSubmissionModel.session_question_id == question_id
            )
        ).all()
    assert sorted(answer.points for answer in answers) == [0, 100]
    assert all(answer.response_time_ms >= 0 for answer in answers)
    assert incorrect.selected_option_id == "joule"


def test_answer_rejects_invalid_stale_late_and_nonparticipant_requests(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    with pytest.raises(InvalidOptionError):
        postgres_session_service.submit_answer(
            room_id,
            OWNER_ID,
            question_id,
            "not-an-option",
        )
    with pytest.raises(StaleSessionQuestionError):
        postgres_session_service.submit_answer(
            room_id,
            OWNER_ID,
            uuid4(),
            "newton",
        )
    _register_user(postgres_user_repository, THIRD_USER_ID, "Third User")
    with pytest.raises(NotSessionParticipantError):
        postgres_session_service.submit_answer(
            room_id,
            THIRD_USER_ID,
            question_id,
            "newton",
        )
    session = _current_session(postgres_database, room_id)
    _force_current_question_closed(postgres_database, session.id)
    with pytest.raises(AnswerTooLateError):
        postgres_session_service.submit_answer(
            room_id,
            SECOND_USER_ID,
            question_id,
            "newton",
        )


def test_reconciliation_transitions_once_and_uses_fresh_next_deadline(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, _ = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    session = _current_session(postgres_database, room_id)
    before = postgres_session_service.reconcile_session(session_id=session.id)
    assert before is not None
    assert before.status is QuizSessionStatus.QUESTION_OPEN
    assert before.state_version == 1

    _force_current_question_closed(postgres_database, session.id)
    revealed = postgres_session_service.reconcile_session(session_id=session.id)
    repeated_reveal = postgres_session_service.reconcile_session(session_id=session.id)
    assert revealed is not None
    assert revealed.status is QuizSessionStatus.QUESTION_REVEAL
    assert revealed.state_version == 2
    assert repeated_reveal is not None
    assert repeated_reveal.state_version == 2

    _force_reveal_expired(postgres_database, session.id)
    opened_next = postgres_session_service.reconcile_session(session_id=session.id)
    assert opened_next is not None
    assert opened_next.status is QuizSessionStatus.QUESTION_OPEN
    assert opened_next.current_question_position == 1
    assert opened_next.state_version == 3

    with postgres_database.session_factory() as db_session:
        question = db_session.scalar(
            select(SessionQuestionModel).where(
                SessionQuestionModel.session_id == session.id,
                SessionQuestionModel.position == 1,
            )
        )
    assert question is not None
    assert question.opened_at is not None
    assert question.closes_at is not None
    assert question.closes_at - question.opened_at >= timedelta(seconds=19)


def test_final_reveal_finishes_and_finished_is_a_noop(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, _ = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    session = _current_session(postgres_database, room_id)

    for position in range(5):
        _force_current_question_closed(postgres_database, session.id)
        postgres_session_service.reconcile_session(session_id=session.id)
        _force_reveal_expired(postgres_database, session.id)
        session_state = postgres_session_service.reconcile_session(
            session_id=session.id
        )
        assert session_state is not None
        if position < 4:
            assert session_state.status is QuizSessionStatus.QUESTION_OPEN
        else:
            assert session_state.status is QuizSessionStatus.FINISHED

    finished_again = postgres_session_service.reconcile_session(session_id=session.id)
    assert finished_again.status is QuizSessionStatus.FINISHED
    with pytest.raises(SessionNotActiveError):
        postgres_session_service.submit_answer(
            room_id,
            OWNER_ID,
            uuid4(),
            "newton",
        )


def test_reveal_snapshot_exposes_only_viewer_result_and_revealed_scores(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    postgres_session_service.submit_answer(
        room_id,
        OWNER_ID,
        question_id,
        "newton",
    )
    postgres_session_service.submit_answer(
        room_id,
        SECOND_USER_ID,
        question_id,
        "joule",
    )
    hidden = postgres_session_service.get_state_snapshot(room_id, OWNER_ID)
    assert hidden.question is not None
    assert not hasattr(hidden.question, "correct_option_id")
    assert hidden.leaderboard[0].total_points == 0
    hidden_protocol = state_snapshot_payload(
        hidden,
        online_users=(),
    ).model_dump(mode="json")
    assert "correct_option_id" not in hidden_protocol["question"]
    assert "is_correct" not in hidden_protocol["viewer_submission"]
    assert "points" not in hidden_protocol["viewer_submission"]

    session = _current_session(postgres_database, room_id)
    _force_current_question_closed(postgres_database, session.id)
    postgres_session_service.reconcile_session(session_id=session.id)
    owner_reveal = postgres_session_service.get_state_snapshot(room_id, OWNER_ID)
    second_reveal = postgres_session_service.get_state_snapshot(
        room_id,
        SECOND_USER_ID,
    )
    assert owner_reveal.question is not None
    assert hasattr(owner_reveal.question, "correct_option_id")
    assert owner_reveal.viewer_submission is not None
    assert owner_reveal.viewer_submission.is_correct is True
    assert owner_reveal.viewer_submission.points == 100
    assert second_reveal.viewer_submission is not None
    assert second_reveal.viewer_submission.is_correct is False
    assert second_reveal.leaderboard[0].total_points == 100
    assert [entry.user_id for entry in second_reveal.leaderboard] == [
        OWNER_ID,
        SECOND_USER_ID,
    ]
    assert [entry.rank for entry in second_reveal.leaderboard] == [1, 2]
    assert not hasattr(second_reveal, "other_participant_answers")
    owner_protocol = state_snapshot_payload(
        owner_reveal,
        online_users=(),
    ).model_dump(mode="json")
    second_protocol = state_snapshot_payload(
        second_reveal,
        online_users=(),
    ).model_dump(mode="json")
    assert owner_protocol["question"]["correct_option_id"] == "newton"
    assert owner_protocol["viewer_submission"]["selected_option_id"] == "newton"
    assert owner_protocol["viewer_submission"]["is_correct"] is True
    assert second_protocol["viewer_submission"]["selected_option_id"] == "joule"
    assert second_protocol["viewer_submission"]["is_correct"] is False
    assert all(
        "selected_option_id" not in entry
        for entry in second_protocol["leaderboard"]
    )


def test_finished_session_privacy_and_rematch_use_current_membership(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    first_session = _current_session(postgres_database, room_id)
    postgres_session_service.submit_answer(
        room_id,
        OWNER_ID,
        question_id,
        "newton",
    )
    postgres_session_service.submit_answer(
        room_id,
        SECOND_USER_ID,
        question_id,
        "joule",
    )
    _finish_session(
        postgres_database,
        postgres_session_service,
        first_session.id,
    )

    with postgres_database.session_factory() as database_session:
        historical_session = database_session.execute(
            select(
                QuizSessionModel.id,
                QuizSessionModel.status,
                QuizSessionModel.state_version,
                QuizSessionModel.current_question_position,
                QuizSessionModel.started_at,
                QuizSessionModel.finished_at,
            ).where(QuizSessionModel.id == first_session.id)
        ).one()
        historical_participants = tuple(
            database_session.execute(
                select(
                    SessionParticipantModel.id,
                    SessionParticipantModel.user_id,
                    SessionParticipantModel.room_membership_id,
                    SessionParticipantModel.display_name_snapshot,
                )
                .where(SessionParticipantModel.session_id == first_session.id)
                .order_by(SessionParticipantModel.id)
            ).all()
        )
        historical_questions = tuple(
            database_session.execute(
                select(
                    SessionQuestionModel.id,
                    SessionQuestionModel.position,
                    SessionQuestionModel.prompt_snapshot,
                    SessionQuestionModel.correct_option_id,
                )
                .where(SessionQuestionModel.session_id == first_session.id)
                .order_by(SessionQuestionModel.position)
            ).all()
        )
        historical_answers = tuple(
            database_session.execute(
                select(
                    AnswerSubmissionModel.id,
                    AnswerSubmissionModel.participant_id,
                    AnswerSubmissionModel.selected_option_id,
                    AnswerSubmissionModel.is_correct,
                    AnswerSubmissionModel.points,
                )
                .where(AnswerSubmissionModel.session_id == first_session.id)
                .order_by(AnswerSubmissionModel.id)
            ).all()
        )

    _register_user(postgres_user_repository, THIRD_USER_ID, "Third User")
    room = postgres_service.get_room(room_id)
    joined = postgres_service.join_room_by_code(
        join_code=room.join_code,
        user_id=THIRD_USER_ID,
        display_name="Third User",
    )
    assert joined.room_id == room_id

    owner_snapshot = postgres_session_service.get_state_snapshot(room_id, OWNER_ID)
    assert owner_snapshot.session is not None
    assert owner_snapshot.session.id == first_session.id
    assert owner_snapshot.session.status is QuizSessionStatus.FINISHED
    assert owner_snapshot.viewer_participated is True
    assert [participant.user_id for participant in owner_snapshot.participants] == [
        OWNER_ID,
        SECOND_USER_ID,
        THIRD_USER_ID,
    ]
    assert [entry.user_id for entry in owner_snapshot.leaderboard] == [
        OWNER_ID,
        SECOND_USER_ID,
    ]

    newcomer_snapshot = postgres_session_service.get_state_snapshot(
        room_id,
        THIRD_USER_ID,
    )
    assert newcomer_snapshot.session is None
    assert newcomer_snapshot.viewer_participated is False
    assert newcomer_snapshot.question is None
    assert newcomer_snapshot.viewer_submission is None
    assert newcomer_snapshot.leaderboard == ()
    assert newcomer_snapshot.finished_at is None
    assert [participant.user_id for participant in newcomer_snapshot.participants] == [
        OWNER_ID,
        SECOND_USER_ID,
        THIRD_USER_ID,
    ]

    newcomer_http = SessionStateResponse.from_domain(newcomer_snapshot).model_dump(
        mode="json"
    )
    assert newcomer_http["session"] is None
    assert newcomer_http["viewer_participated"] is False
    assert newcomer_http["viewer_submission"] is None
    assert newcomer_http["leaderboard"] == []
    assert newcomer_http["finished_at"] is None

    newcomer_protocol = state_snapshot_payload(
        newcomer_snapshot,
        online_users=(),
    ).model_dump(mode="json")
    assert newcomer_protocol["session_id"] is None
    assert newcomer_protocol["viewer_participated"] is False
    assert newcomer_protocol["leaderboard"] == []
    assert newcomer_protocol["viewer_submission"] is None
    assert newcomer_protocol["finished_at"] is None
    assert [
        participant["user_id"]
        for participant in newcomer_protocol["room_state"]["participants"]
    ] == [str(OWNER_ID), str(SECOND_USER_ID), str(THIRD_USER_ID)]

    owner_room_state = room_state_payload(
        owner_snapshot,
        online_users=(OWNER_ID, THIRD_USER_ID),
    ).model_dump(mode="json")
    assert [participant["user_id"] for participant in owner_room_state["participants"]] == [
        str(OWNER_ID),
        str(SECOND_USER_ID),
        str(THIRD_USER_ID),
    ]

    with pytest.raises(ParticipantsNotReadyError):
        postgres_session_service.start_session(room_id, OWNER_ID)
    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    postgres_session_service.set_ready(room_id, THIRD_USER_ID, True)
    rematch = postgres_session_service.start_session(room_id, OWNER_ID)
    assert rematch.id != first_session.id
    rematch_snapshot = postgres_session_service.get_state_snapshot(
        room_id,
        THIRD_USER_ID,
    )
    assert rematch_snapshot.session is not None
    assert rematch_snapshot.session.id == rematch.id
    assert rematch_snapshot.viewer_participated is True

    with postgres_database.session_factory() as database_session:
        rematch_users = set(
            database_session.scalars(
                select(SessionParticipantModel.user_id).where(
                    SessionParticipantModel.session_id == rematch.id
                )
            ).all()
        )
        persisted_historical_participants = tuple(
            database_session.execute(
                select(
                    SessionParticipantModel.id,
                    SessionParticipantModel.user_id,
                    SessionParticipantModel.room_membership_id,
                    SessionParticipantModel.display_name_snapshot,
                )
                .where(SessionParticipantModel.session_id == first_session.id)
                .order_by(SessionParticipantModel.id)
            ).all()
        )
        persisted_historical_questions = tuple(
            database_session.execute(
                select(
                    SessionQuestionModel.id,
                    SessionQuestionModel.position,
                    SessionQuestionModel.prompt_snapshot,
                    SessionQuestionModel.correct_option_id,
                )
                .where(SessionQuestionModel.session_id == first_session.id)
                .order_by(SessionQuestionModel.position)
            ).all()
        )
        persisted_historical_answers = tuple(
            database_session.execute(
                select(
                    AnswerSubmissionModel.id,
                    AnswerSubmissionModel.participant_id,
                    AnswerSubmissionModel.selected_option_id,
                    AnswerSubmissionModel.is_correct,
                    AnswerSubmissionModel.points,
                )
                .where(AnswerSubmissionModel.session_id == first_session.id)
                .order_by(AnswerSubmissionModel.id)
            ).all()
        )
        persisted_historical_session = database_session.execute(
            select(
                QuizSessionModel.id,
                QuizSessionModel.status,
                QuizSessionModel.state_version,
                QuizSessionModel.current_question_position,
                QuizSessionModel.started_at,
                QuizSessionModel.finished_at,
            ).where(QuizSessionModel.id == first_session.id)
        ).one()

    assert rematch_users == {OWNER_ID, SECOND_USER_ID, THIRD_USER_ID}
    assert persisted_historical_session == historical_session
    assert persisted_historical_participants == historical_participants
    assert persisted_historical_questions == historical_questions
    assert persisted_historical_answers == historical_answers


def test_join_by_code_active_room_recovery_and_member_only_reads(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room = postgres_service.create_room(
        name="Joinable Room",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    _register_user(postgres_user_repository, SECOND_USER_ID, "Second User")
    _register_user(postgres_user_repository, FOURTH_USER_ID, "Fourth User")
    auth_verifier.register("second-token", SECOND_USER_ID)
    auth_verifier.register("fourth-token", FOURTH_USER_ID)

    joined = postgres_client.post(
        "/rooms/join",
        json={"join_code": room.join_code.lower()},
        headers=auth_headers("second-token"),
    )
    assert joined.status_code == 201
    assert joined.json()["member"]["user_id"] == str(SECOND_USER_ID)

    active = postgres_client.get(
        "/me/active-room",
        headers=auth_headers("second-token"),
    )
    assert active.status_code == 200
    assert active.json()["id"] == str(room.id)

    private_members = postgres_client.get(
        f"/rooms/{room.id}/members",
        headers=auth_headers("fourth-token"),
    )
    assert private_members.status_code == 403
    assert private_members.json()["error"]["code"] == "not_room_member"

    no_room = postgres_client.get(
        "/me/active-room",
        headers=auth_headers("fourth-token"),
    )
    assert no_room.status_code == 200
    assert no_room.json() is None


def test_join_is_rejected_while_session_is_active(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    room = postgres_service.get_room(room_id)
    seed_physics_sprint(postgres_database.session_factory)
    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    postgres_session_service.start_session(room_id, OWNER_ID)
    _register_user(postgres_user_repository, THIRD_USER_ID, "Third User")
    auth_verifier.register("third-token", THIRD_USER_ID)

    response = postgres_client.post(
        "/rooms/join",
        json={"join_code": room.join_code},
        headers=auth_headers("third-token"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "room_join_unavailable"


def test_authenticated_quiz_http_endpoints_return_safe_state(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    _register_user(postgres_user_repository, SECOND_USER_ID, "Second User")
    auth_verifier.register("second-token", SECOND_USER_ID)
    seed_physics_sprint(postgres_database.session_factory)

    ready = postgres_client.post(
        f"/rooms/{room_id}/ready",
        json={"ready": True},
        headers=auth_headers("second-token"),
    )
    assert ready.status_code == 200
    assert ready.json()["ready"] is True

    started = postgres_client.post(
        f"/rooms/{room_id}/start",
        headers=auth_headers(),
    )
    assert started.status_code == 201
    started_payload = started.json()
    assert started_payload["question"] is not None
    assert "correct_option_id" not in started_payload["question"]
    question_id = started_payload["question"]["id"]

    acknowledgement = postgres_client.post(
        f"/rooms/{room_id}/answers",
        json={
            "session_question_id": question_id,
            "selected_option_id": "newton",
        },
        headers=auth_headers(),
    )
    assert acknowledgement.status_code == 201
    assert "is_correct" not in acknowledgement.json()
    assert "points" not in acknowledgement.json()

    state = postgres_client.get(
        f"/rooms/{room_id}/state",
        headers=auth_headers(),
    )
    assert state.status_code == 200
    assert "correct_option_id" not in state.json()["question"]


def test_answer_and_deadline_reconciliation_serialize(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    session = _current_session(postgres_database, room_id)
    _force_current_question_closed(postgres_database, session.id)
    services = (
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
    )
    results = _concurrently(
        (
            lambda: services[0].submit_answer(
                room_id,
                OWNER_ID,
                question_id,
                "newton",
            ),
            lambda: services[1].reconcile_session(session_id=session.id),
        )
    )

    assert results[0][0] in {"AnswerTooLateError", "QuestionNotOpenError"}
    assert results[1][0] == "ok"
    with postgres_database.session_factory() as db_session:
        persisted = db_session.get(QuizSessionModel, session.id)
        answer_count = db_session.scalar(
            select(func.count(AnswerSubmissionModel.id)).where(
                AnswerSubmissionModel.session_question_id == question_id
            )
        )
    assert persisted is not None
    assert persisted.status == QuizSessionStatus.QUESTION_REVEAL.value
    assert persisted.state_version == 2
    assert answer_count == 0


def test_join_and_start_are_serialized_by_the_room_lock(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    _register_user(postgres_user_repository, THIRD_USER_ID, "Third User")
    seed_physics_sprint(postgres_database.session_factory)
    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    start_service = SessionService(
        PostgresQuizSessionRepository(postgres_database.session_factory)
    )
    results = _concurrently(
        (
            lambda: start_service.start_session(room_id, OWNER_ID),
            lambda: postgres_service.join_room(
                room_id=room_id,
                user_id=THIRD_USER_ID,
                display_name="Third User",
            ),
        )
    )

    with postgres_database.session_factory() as session:
        active_session_count = session.scalar(
            select(func.count(QuizSessionModel.id)).where(
                QuizSessionModel.room_id == room_id,
                QuizSessionModel.status.in_(
                    ("QUESTION_OPEN", "QUESTION_REVEAL")
                ),
            )
        )
        third_membership = session.scalar(
            select(RoomMembershipModel.id).where(
                RoomMembershipModel.room_id == room_id,
                RoomMembershipModel.user_id == THIRD_USER_ID,
                RoomMembershipModel.left_at.is_(None),
            )
        )

    assert results[0][0] in {"ok", "ParticipantsNotReadyError"}
    assert results[1][0] in {"ok", "SessionAlreadyActiveError"}
    if results[0][0] == "ok":
        assert results[1][0] == "SessionAlreadyActiveError"
        assert active_session_count == 1
        assert third_membership is None
    else:
        assert results[0][0] == "ParticipantsNotReadyError"
        assert results[1][0] == "ok"
        assert active_session_count == 0
        assert third_membership is not None


def test_ready_and_start_are_serialized_by_the_room_lock(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    seed_physics_sprint(postgres_database.session_factory)
    services = (
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
    )
    results = _concurrently(
        (
            lambda: services[0].set_ready(room_id, SECOND_USER_ID, True),
            lambda: services[1].start_session(room_id, OWNER_ID),
        )
    )

    with postgres_database.session_factory() as session:
        active_session_count = session.scalar(
            select(func.count(QuizSessionModel.id)).where(
                QuizSessionModel.room_id == room_id,
                QuizSessionModel.status.in_(
                    ("QUESTION_OPEN", "QUESTION_REVEAL")
                ),
            )
        )
        membership = session.scalar(
            select(RoomMembershipModel).where(
                RoomMembershipModel.room_id == room_id,
                RoomMembershipModel.user_id == SECOND_USER_ID,
                RoomMembershipModel.left_at.is_(None),
            )
        )

    assert results[0][0] in {"ok", "SessionAlreadyActiveError"}
    assert results[1][0] in {"ok", "ParticipantsNotReadyError"}
    if results[1][0] == "ok":
        assert results[0][0] in {"ok", "SessionAlreadyActiveError"}
        assert active_session_count == 1
        assert membership is not None
        assert membership.ready_at is None
    else:
        assert results[0][0] == "ok"
        assert active_session_count == 0
        assert membership is not None
        assert membership.ready_at is not None


def test_zero_score_leaderboard_uses_user_uuid_tie_breaker(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    _add_member(
        postgres_database,
        postgres_user_repository,
        room_id,
        THIRD_USER_ID,
        "Third User",
    )
    seed_physics_sprint(postgres_database.session_factory)
    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    postgres_session_service.set_ready(room_id, THIRD_USER_ID, True)
    postgres_session_service.start_session(room_id, OWNER_ID)

    snapshot = postgres_session_service.get_state_snapshot(room_id, OWNER_ID)
    assert [entry.user_id for entry in snapshot.leaderboard] == [
        OWNER_ID,
        SECOND_USER_ID,
        THIRD_USER_ID,
    ]


def test_two_start_attempts_create_one_active_session(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_two_member_room(
        postgres_database,
        postgres_service,
        postgres_user_repository,
    )
    seed_physics_sprint(postgres_database.session_factory)
    postgres_session_service.set_ready(room_id, SECOND_USER_ID, True)
    services = (
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
    )
    results = _concurrently(
        (
            lambda: services[0].start_session(room_id, OWNER_ID),
            lambda: services[1].start_session(room_id, OWNER_ID),
        )
    )

    assert sorted(result[0] for result in results) == ["SessionAlreadyActiveError", "ok"]
    with postgres_database.session_factory() as session:
        assert session.scalar(
            select(func.count(QuizSessionModel.id)).where(
                QuizSessionModel.room_id == room_id,
                QuizSessionModel.status.in_(("QUESTION_OPEN", "QUESTION_REVEAL")),
            )
        ) == 1


def test_two_identical_answers_create_one_official_row(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    services = (
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
    )
    results = _concurrently(
        (
            lambda: services[0].submit_answer(
                room_id,
                OWNER_ID,
                question_id,
                "newton",
            ),
            lambda: services[1].submit_answer(
                room_id,
                OWNER_ID,
                question_id,
                "newton",
            ),
        )
    )
    assert all(result[0] == "ok" for result in results)
    with postgres_database.session_factory() as session:
        assert session.scalar(
            select(func.count(AnswerSubmissionModel.id)).where(
                AnswerSubmissionModel.session_question_id == question_id
            )
        ) == 1


def test_two_different_answers_leave_one_official_result(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, question_id = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    services = (
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
    )
    results = _concurrently(
        (
            lambda: services[0].submit_answer(
                room_id,
                OWNER_ID,
                question_id,
                "newton",
            ),
            lambda: services[1].submit_answer(
                room_id,
                OWNER_ID,
                question_id,
                "joule",
            ),
        )
    )
    assert sorted(result[0] for result in results) == [
        "AnswerAlreadySubmittedError",
        "ok",
    ]
    with postgres_database.session_factory() as session:
        assert session.scalar(
            select(func.count(AnswerSubmissionModel.id)).where(
                AnswerSubmissionModel.session_question_id == question_id
            )
        ) == 1


def test_two_reconciliation_calls_make_one_transition(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, _ = _seed_startable_session(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    session = _current_session(postgres_database, room_id)
    _force_current_question_closed(postgres_database, session.id)
    services = (
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
        SessionService(PostgresQuizSessionRepository(postgres_database.session_factory)),
    )
    results = _concurrently(
        (
            lambda: services[0].reconcile_session(session_id=session.id),
            lambda: services[1].reconcile_session(session_id=session.id),
        )
    )
    assert all(result[0] == "ok" for result in results)
    with postgres_database.session_factory() as db_session:
        persisted = db_session.get(QuizSessionModel, session.id)
    assert persisted is not None
    assert persisted.status == QuizSessionStatus.QUESTION_REVEAL.value
    assert persisted.state_version == 2
