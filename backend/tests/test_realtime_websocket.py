from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import FakeAuthVerifier
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.session_question import SessionQuestionModel
from app.db.session import Database
from app.domain.member import RoomMember
from app.domain.quiz import QuizSessionStatus
from app.main import create_app
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.scripts.seed_questions import seed_physics_sprint
from app.services.rooms import RoomService
from app.services.sessions import SessionService
from starlette.websockets import WebSocketDisconnect
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


SECOND_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SECOND_TOKEN = "test-second-token"


def _prepare_startable_room(
    database: Database,
    room_service: RoomService,
    session_service: SessionService,
    user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> UUID:
    room = room_service.create_room(
        name="Physics Sprint",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    user_repository.upsert_profile(SECOND_ID, "Second User")
    auth_verifier.register(SECOND_TOKEN, SECOND_ID)
    PostgresMembershipRepository(database.session_factory).join(
        RoomMember(
            user_id=SECOND_ID,
            display_name="Second User",
            room_id=room.id,
        ),
        room.maximum_members,
    )
    assert seed_physics_sprint(database.session_factory) == 5
    session_service.set_ready(room.id, SECOND_ID, True)
    return room.id


def _auth(socket: object, token: str) -> None:
    send_json = getattr(socket, "send_json")
    send_json(
        {
            "protocol_version": 1,
            "type": "AUTHENTICATE",
            "payload": {"access_token": token},
        }
    )


def _receive_initial(socket: object) -> tuple[dict[str, object], ...]:
    receive_json = getattr(socket, "receive_json")
    events = tuple(receive_json() for _ in range(3))
    assert [event["type"] for event in events] == [
        "CONNECTED",
        "STATE_SNAPSHOT",
        "ROOM_STATE",
    ]
    return events


def _force_open_question_closed(database: Database, room_id: UUID) -> UUID:
    with database.session_factory() as session:
        with session.begin():
            current = session.scalar(
                select(QuizSessionModel).where(
                    QuizSessionModel.room_id == room_id,
                    QuizSessionModel.status == QuizSessionStatus.QUESTION_OPEN.value,
                )
            )
            assert current is not None
            question = session.scalar(
                select(SessionQuestionModel).where(
                    SessionQuestionModel.session_id == current.id,
                    SessionQuestionModel.position == current.current_question_position,
                )
            )
            assert question is not None
            now = datetime.now(timezone.utc)
            question.opened_at = now - timedelta(seconds=2)
            question.closes_at = now - timedelta(seconds=1)
            return current.id


def _force_reveal_expired(database: Database, session_id: UUID) -> None:
    with database.session_factory() as session:
        with session.begin():
            current = session.get(QuizSessionModel, session_id)
            assert current is not None
            current.reveal_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)


def _request_transition(socket: object) -> tuple[dict[str, object], dict[str, object]]:
    getattr(socket, "send_json")(
        {
            "protocol_version": 1,
            "type": "REQUEST_STATE",
            "payload": {},
        }
    )
    first = getattr(socket, "receive_json")()
    second = getattr(socket, "receive_json")()
    return first, second


def _submit_answer(
    socket: object,
    session_question_id: str,
    selected_option_id: str,
) -> dict[str, object]:
    getattr(socket, "send_json")(
        {
            "protocol_version": 1,
            "type": "SUBMIT_ANSWER",
            "payload": {
                "session_question_id": session_question_id,
                "selected_option_id": selected_option_id,
            },
        }
    )
    acknowledgement = getattr(socket, "receive_json")()
    assert acknowledgement["type"] == "ANSWER_ACCEPTED"
    assert acknowledgement["payload"]["session_question_id"] == session_question_id
    assert acknowledgement["payload"]["selected_option_id"] == selected_option_id
    assert "is_correct" not in acknowledgement["payload"]
    assert "points" not in acknowledgement["payload"]
    return acknowledgement


def _assert_same_public_question(
    first: dict[str, object],
    second: dict[str, object],
) -> None:
    first_without_server_time = {
        key: value for key, value in first.items() if key != "server_time"
    }
    second_without_server_time = {
        key: value for key, value in second.items() if key != "server_time"
    }
    assert first_without_server_time == second_without_server_time


def test_member_leave_replaces_room_state_and_terminates_departed_socket(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    path = f"/ws/rooms/{room_id}"

    with postgres_client.websocket_connect(path) as owner_socket:
        _auth(owner_socket, OWNER_TOKEN)
        _receive_initial(owner_socket)
        with postgres_client.websocket_connect(path) as member_socket:
            _auth(member_socket, SECOND_TOKEN)
            _receive_initial(member_socket)
            assert owner_socket.receive_json()["type"] == "ROOM_STATE"

            response = postgres_client.post(
                f"/rooms/{room_id}/leave",
                headers=auth_headers(SECOND_TOKEN),
            )

            assert response.status_code == 204
            member_error = member_socket.receive_json()
            assert member_error["type"] == "ERROR"
            assert member_error["payload"]["code"] == "room_left"
            with pytest.raises(WebSocketDisconnect) as disconnected:
                member_socket.receive_json()
            assert disconnected.value.code == 4403

            owner_update = owner_socket.receive_json()
            assert owner_update["type"] == "ROOM_STATE"
            assert [
                participant["user_id"]
                for participant in owner_update["payload"]["participants"]
            ] == [str(OWNER_ID)]


def test_host_close_notifies_and_terminates_every_room_socket(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    path = f"/ws/rooms/{room_id}"

    with postgres_client.websocket_connect(path) as owner_socket:
        _auth(owner_socket, OWNER_TOKEN)
        _receive_initial(owner_socket)
        with postgres_client.websocket_connect(path) as member_socket:
            _auth(member_socket, SECOND_TOKEN)
            _receive_initial(member_socket)
            assert owner_socket.receive_json()["type"] == "ROOM_STATE"

            response = postgres_client.post(
                f"/rooms/{room_id}/close",
                headers=auth_headers(OWNER_TOKEN),
            )

            assert response.status_code == 204
            for socket in (owner_socket, member_socket):
                error = socket.receive_json()
                assert error["type"] == "ERROR"
                assert error["payload"]["code"] == "room_closed"
                with pytest.raises(WebSocketDisconnect) as disconnected:
                    socket.receive_json()
                assert disconnected.value.code == 4404

    with postgres_client.websocket_connect(path) as closed_socket:
        _auth(closed_socket, OWNER_TOKEN)
        error = closed_socket.receive_json()
        assert error["payload"]["code"] == "room_closed"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            closed_socket.receive_json()
        assert disconnected.value.code == 4404


def test_active_session_rejects_lifecycle_without_closing_sockets(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    postgres_session_service.start_session(room_id, OWNER_ID)

    with postgres_client.websocket_connect(f"/ws/rooms/{room_id}") as socket:
        _auth(socket, SECOND_TOKEN)
        _receive_initial(socket)
        response = postgres_client.post(
            f"/rooms/{room_id}/leave",
            headers=auth_headers(SECOND_TOKEN),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "session_already_active"
        socket.send_json(
            {
                "protocol_version": 1,
                "type": "REQUEST_STATE",
                "payload": {},
            }
        )
        snapshot = socket.receive_json()
        assert snapshot["type"] == "STATE_SNAPSHOT"
        assert snapshot["payload"]["status"] == "QUESTION_OPEN"


def test_authenticated_websocket_drives_authoritative_session(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    path = f"/ws/rooms/{room_id}"

    with postgres_client.websocket_connect(path) as owner_socket:
        _auth(owner_socket, OWNER_TOKEN)
        _receive_initial(owner_socket)
        with postgres_client.websocket_connect(path) as second_socket:
            _auth(second_socket, SECOND_TOKEN)
            _receive_initial(second_socket)
            assert owner_socket.receive_json()["type"] == "ROOM_STATE"

            ready = {
                "protocol_version": 1,
                "type": "SET_READY",
                "payload": {"ready": True},
            }
            second_socket.send_json(ready)
            assert owner_socket.receive_json()["type"] == "ROOM_STATE"
            assert second_socket.receive_json()["type"] == "ROOM_STATE"

            second_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "START_SESSION",
                    "payload": {},
                }
            )
            assert second_socket.receive_json()["payload"]["code"] == (
                "room_owner_required"
            )

            owner_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "START_SESSION",
                    "payload": {},
                }
            )
            owner_start = tuple(owner_socket.receive_json() for _ in range(3))
            second_start = tuple(second_socket.receive_json() for _ in range(3))
            assert [event["type"] for event in owner_start] == [
                "SESSION_STARTED",
                "QUESTION_OPENED",
                "STATE_SNAPSHOT",
            ]
            assert [event["type"] for event in second_start] == [
                "SESSION_STARTED",
                "QUESTION_OPENED",
                "STATE_SNAPSHOT",
            ]
            session_id = UUID(owner_start[0]["payload"]["session_id"])
            assert owner_start[0]["payload"] == second_start[0]["payload"]
            question_payload = owner_start[1]["payload"]["question"]
            question_id = question_payload["session_question_id"]
            assert "correct_option_id" not in question_payload
            assert "is_correct" not in question_payload
            assert "points" not in question_payload
            assert owner_start[2]["payload"]["session_id"] == str(session_id)

            second_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "SUBMIT_ANSWER",
                    "payload": {
                        "session_question_id": question_id,
                        "selected_option_id": "newton",
                    },
                }
            )
            accepted = second_socket.receive_json()
            assert accepted["type"] == "ANSWER_ACCEPTED"
            assert "is_correct" not in accepted["payload"]
            assert "points" not in accepted["payload"]

            second_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "SUBMIT_ANSWER",
                    "payload": {
                        "session_question_id": question_id,
                        "selected_option_id": "newton",
                    },
                }
            )
            assert second_socket.receive_json()["type"] == "ANSWER_ACCEPTED"
            second_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "SUBMIT_ANSWER",
                    "payload": {
                        "session_question_id": question_id,
                        "selected_option_id": "joule",
                    },
                }
            )
            assert second_socket.receive_json()["payload"]["code"] == (
                "answer_already_submitted"
            )

            owner_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "REQUEST_STATE",
                    "payload": {},
                }
            )
            assert owner_socket.receive_json()["type"] == "STATE_SNAPSHOT"

            assert _force_open_question_closed(postgres_database, room_id) == session_id
            owner_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "SUBMIT_ANSWER",
                    "payload": {
                        "session_question_id": question_id,
                        "selected_option_id": "newton",
                    },
                }
            )
            assert owner_socket.receive_json()["payload"]["code"] == "answer_too_late"
            revealed, revealed_snapshot = _request_transition(owner_socket)
            assert revealed["type"] == "QUESTION_REVEALED"
            assert revealed["payload"]["question"]["correct_option_id"] == "newton"
            assert revealed["payload"]["viewer_submission"] is None
            assert revealed_snapshot["type"] == "STATE_SNAPSHOT"
            second_revealed = second_socket.receive_json()
            second_revealed_snapshot = second_socket.receive_json()
            assert second_revealed["type"] == "QUESTION_REVEALED"
            assert second_revealed["payload"]["viewer_submission"]["is_correct"] is True
            assert second_revealed_snapshot["type"] == "STATE_SNAPSHOT"

            _force_reveal_expired(postgres_database, session_id)
            opened, _ = _request_transition(owner_socket)
            assert opened["type"] == "QUESTION_OPENED"

            for question_number in range(2, 6):
                _force_open_question_closed(postgres_database, room_id)
                revealed_event, _ = _request_transition(owner_socket)
                assert revealed_event["type"] == "QUESTION_REVEALED"
                _force_reveal_expired(postgres_database, session_id)
                if question_number < 5:
                    opened_event, _ = _request_transition(owner_socket)
                    assert opened_event["type"] == "QUESTION_OPENED"
                else:
                    finished_event, finished_snapshot = _request_transition(owner_socket)
                    assert finished_event["type"] == "SESSION_FINISHED"
                    assert finished_event["payload"]["session_id"] == str(session_id)
                    assert finished_event["payload"]["leaderboard"]
                    assert finished_snapshot["type"] == "STATE_SNAPSHOT"
                    assert finished_snapshot["payload"]["status"] == "FINISHED"


def test_two_clients_complete_one_authoritative_five_question_session(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    path = f"/ws/rooms/{room_id}"

    with postgres_client.websocket_connect(path) as owner_socket:
        _auth(owner_socket, OWNER_TOKEN)
        _receive_initial(owner_socket)
        with postgres_client.websocket_connect(path) as member_socket:
            _auth(member_socket, SECOND_TOKEN)
            member_initial = _receive_initial(member_socket)
            owner_presence = owner_socket.receive_json()
            assert owner_presence["type"] == "ROOM_STATE"
            owner_participants = owner_presence["payload"]["participants"]
            member_participants = member_initial[2]["payload"]["participants"]
            assert owner_participants == member_participants
            assert [participant["user_id"] for participant in owner_participants] == [
                str(OWNER_ID),
                str(SECOND_ID),
            ]
            assert all(participant["online"] for participant in owner_participants)
            assert owner_participants[1]["ready"] is True

            for desired_ready in (False, True):
                member_socket.send_json(
                    {
                        "protocol_version": 1,
                        "type": "SET_READY",
                        "payload": {"ready": desired_ready},
                    }
                )
                owner_readiness = owner_socket.receive_json()
                member_readiness = member_socket.receive_json()
                assert owner_readiness["type"] == "ROOM_STATE"
                assert member_readiness["type"] == "ROOM_STATE"
                assert (
                    owner_readiness["payload"]["participants"]
                    == member_readiness["payload"]["participants"]
                )
                assert owner_readiness["payload"]["participants"][1]["ready"] is (
                    desired_ready
                )

            member_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "START_SESSION",
                    "payload": {},
                }
            )
            member_start_error = member_socket.receive_json()
            assert member_start_error["type"] == "ERROR"
            assert member_start_error["payload"]["code"] == "room_owner_required"

            owner_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "START_SESSION",
                    "payload": {},
                }
            )
            owner_start = tuple(owner_socket.receive_json() for _ in range(3))
            member_start = tuple(member_socket.receive_json() for _ in range(3))
            assert [event["type"] for event in owner_start] == [
                "SESSION_STARTED",
                "QUESTION_OPENED",
                "STATE_SNAPSHOT",
            ]
            assert [event["type"] for event in member_start] == [
                "SESSION_STARTED",
                "QUESTION_OPENED",
                "STATE_SNAPSHOT",
            ]
            assert owner_start[0]["payload"] == member_start[0]["payload"]
            session_id = UUID(owner_start[0]["payload"]["session_id"])
            owner_snapshot = owner_start[2]["payload"]
            member_snapshot = member_start[2]["payload"]
            assert owner_snapshot["session_id"] == member_snapshot["session_id"]
            _assert_same_public_question(
                owner_snapshot["question"],
                member_snapshot["question"],
            )

            question_ids: list[str] = []
            final_owner_snapshot: dict[str, object] | None = None
            final_member_snapshot: dict[str, object] | None = None
            for question_number in range(1, 6):
                question = owner_snapshot["question"]
                assert question["question_number"] == question_number
                _assert_same_public_question(question, member_snapshot["question"])
                question_id = question["session_question_id"]
                question_ids.append(question_id)
                assert "correct_option_id" not in question
                assert "is_correct" not in question
                assert "points" not in question
                option_ids = [option["id"] for option in question["options"]]
                assert len(option_ids) == 4

                _submit_answer(owner_socket, question_id, option_ids[0])
                if question_number == 1:
                    _submit_answer(owner_socket, question_id, option_ids[0])
                _submit_answer(member_socket, question_id, option_ids[1])

                assert _force_open_question_closed(postgres_database, room_id) == session_id
                owner_reveal, owner_reveal_snapshot = _request_transition(owner_socket)
                member_reveal = member_socket.receive_json()
                member_reveal_snapshot = member_socket.receive_json()
                assert owner_reveal["type"] == "QUESTION_REVEALED"
                assert member_reveal["type"] == "QUESTION_REVEALED"
                assert owner_reveal_snapshot["payload"]["status"] == "QUESTION_REVEAL"
                assert member_reveal_snapshot["payload"]["status"] == "QUESTION_REVEAL"
                assert owner_reveal_snapshot["payload"]["viewer_submission"][
                    "selected_option_id"
                ] == option_ids[0]
                assert member_reveal_snapshot["payload"]["viewer_submission"][
                    "selected_option_id"
                ] == option_ids[1]
                assert all(
                    "selected_option_id" not in entry
                    for entry in owner_reveal_snapshot["payload"]["leaderboard"]
                )
                assert (
                    owner_reveal_snapshot["payload"]["leaderboard"]
                    == member_reveal_snapshot["payload"]["leaderboard"]
                )

                _force_reveal_expired(postgres_database, session_id)
                owner_transition, owner_next_snapshot = _request_transition(owner_socket)
                member_transition = member_socket.receive_json()
                member_next_snapshot = member_socket.receive_json()
                if question_number < 5:
                    assert owner_transition["type"] == "QUESTION_OPENED"
                    assert member_transition["type"] == "QUESTION_OPENED"
                    owner_snapshot = owner_next_snapshot["payload"]
                    member_snapshot = member_next_snapshot["payload"]
                    assert owner_snapshot["status"] == "QUESTION_OPEN"
                    assert member_snapshot["status"] == "QUESTION_OPEN"
                else:
                    assert owner_transition["type"] == "SESSION_FINISHED"
                    assert member_transition["type"] == "SESSION_FINISHED"
                    final_owner_snapshot = owner_next_snapshot["payload"]
                    final_member_snapshot = member_next_snapshot["payload"]

            assert final_owner_snapshot is not None
            assert final_member_snapshot is not None
            assert final_owner_snapshot["status"] == "FINISHED"
            assert final_member_snapshot["status"] == "FINISHED"
            assert len(question_ids) == 5
            assert len(set(question_ids)) == 5
            assert (
                final_owner_snapshot["leaderboard"]
                == final_member_snapshot["leaderboard"]
            )

            with postgres_database.session_factory() as database_session:
                historical_before = tuple(
                    database_session.execute(
                        select(
                            QuizSessionModel.id,
                            QuizSessionModel.status,
                            QuizSessionModel.state_version,
                            QuizSessionModel.current_question_position,
                            QuizSessionModel.started_at,
                            QuizSessionModel.finished_at,
                        ).where(QuizSessionModel.id == session_id)
                    ).one()
                )
                submission_count_before = database_session.scalar(
                    select(func.count(AnswerSubmissionModel.id)).where(
                        AnswerSubmissionModel.session_id == session_id
                    )
                )
                submissions_before = tuple(
                    database_session.execute(
                        select(
                            AnswerSubmissionModel.id,
                            AnswerSubmissionModel.session_question_id,
                            AnswerSubmissionModel.participant_id,
                            AnswerSubmissionModel.selected_option_id,
                            AnswerSubmissionModel.submitted_at,
                            AnswerSubmissionModel.response_time_ms,
                            AnswerSubmissionModel.is_correct,
                            AnswerSubmissionModel.points,
                        )
                        .where(AnswerSubmissionModel.session_id == session_id)
                        .order_by(
                            AnswerSubmissionModel.session_question_id,
                            AnswerSubmissionModel.participant_id,
                        )
                    ).all()
                )
            assert submission_count_before == 10
            assert len(submissions_before) == 10

            member_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "SET_READY",
                    "payload": {"ready": True},
                }
            )
            assert owner_socket.receive_json()["type"] == "ROOM_STATE"
            assert member_socket.receive_json()["type"] == "ROOM_STATE"
            owner_socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "START_SESSION",
                    "payload": {},
                }
            )
            owner_rematch = tuple(owner_socket.receive_json() for _ in range(3))
            member_rematch = tuple(member_socket.receive_json() for _ in range(3))
            assert [event["type"] for event in owner_rematch] == [
                "SESSION_STARTED",
                "QUESTION_OPENED",
                "STATE_SNAPSHOT",
            ]
            assert [event["type"] for event in member_rematch] == [
                "SESSION_STARTED",
                "QUESTION_OPENED",
                "STATE_SNAPSHOT",
            ]
            rematch_id = UUID(owner_rematch[0]["payload"]["session_id"])
            assert rematch_id != session_id
            assert owner_rematch[0]["payload"] == member_rematch[0]["payload"]

    with postgres_database.session_factory() as database_session:
        submission_count = database_session.scalar(
            select(func.count(AnswerSubmissionModel.id)).where(
                AnswerSubmissionModel.session_id == session_id
            )
        )
        historical_after = tuple(
            database_session.execute(
                select(
                    QuizSessionModel.id,
                    QuizSessionModel.status,
                    QuizSessionModel.state_version,
                    QuizSessionModel.current_question_position,
                    QuizSessionModel.started_at,
                    QuizSessionModel.finished_at,
                ).where(QuizSessionModel.id == session_id)
            ).one()
        )
        submissions_after = tuple(
            database_session.execute(
                select(
                    AnswerSubmissionModel.id,
                    AnswerSubmissionModel.session_question_id,
                    AnswerSubmissionModel.participant_id,
                    AnswerSubmissionModel.selected_option_id,
                    AnswerSubmissionModel.submitted_at,
                    AnswerSubmissionModel.response_time_ms,
                    AnswerSubmissionModel.is_correct,
                    AnswerSubmissionModel.points,
                )
                .where(AnswerSubmissionModel.session_id == session_id)
                .order_by(
                    AnswerSubmissionModel.session_question_id,
                    AnswerSubmissionModel.participant_id,
                )
            ).all()
        )
    assert submission_count == 10
    assert historical_after == historical_before
    assert submissions_after == submissions_before


def test_websocket_rejects_non_member_and_expired_authentication(
    postgres_client: TestClient,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room = postgres_service.create_room(
        name="Physics Sprint",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    outsider_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    outsider_token = "test-outsider-token"
    expired_token = "test-expired-token"
    postgres_user_repository.upsert_profile(outsider_id, "Outsider")
    auth_verifier.register(outsider_token, outsider_id)
    auth_verifier.register(
        expired_token,
        OWNER_ID,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with postgres_client.websocket_connect(f"/ws/rooms/{room.id}") as socket:
        _auth(socket, outsider_token)
        error = socket.receive_json()
        assert error["payload"]["code"] == "not_room_member"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4403

    with postgres_client.websocket_connect(f"/ws/rooms/{room.id}") as socket:
        _auth(socket, expired_token)
        error = socket.receive_json()
        assert error["payload"]["code"] == "invalid_auth_token"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4401


def test_websocket_rejects_missing_room_after_authentication(
    postgres_client: TestClient,
) -> None:
    missing_room_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    with postgres_client.websocket_connect(f"/ws/rooms/{missing_room_id}") as socket:
        _auth(socket, OWNER_TOKEN)
        error = socket.receive_json()
        assert error["type"] == "ERROR"
        assert error["payload"]["code"] == "room_not_found"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4404


def test_verified_token_expiry_closes_registered_socket(
    postgres_client: TestClient,
    postgres_service: RoomService,
    auth_verifier: FakeAuthVerifier,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room = postgres_service.create_room(
        name="Physics Sprint",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    expiring_token = "test-expiring-token"
    auth_verifier.register(
        expiring_token,
        OWNER_ID,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=0.1),
    )
    assert postgres_user_repository.get_by_id(OWNER_ID) is not None

    with postgres_client.websocket_connect(f"/ws/rooms/{room.id}") as socket:
        _auth(socket, expiring_token)
        _receive_initial(socket)
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4401


def test_authentication_timeout_closes_without_accepting_a_second_command(
    postgres_client: TestClient,
    postgres_service: RoomService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import websocket as websocket_api

    room = postgres_service.create_room(
        name="Physics Sprint",
        maximum_members=8,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )
    monkeypatch.setattr(websocket_api, "AUTHENTICATION_TIMEOUT_SECONDS", 0.01)

    with postgres_client.websocket_connect(f"/ws/rooms/{room.id}") as socket:
        error = socket.receive_json()
        assert error["payload"]["code"] == "authentication_required"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4401


def test_backend_restarts_recover_open_and_reveal_deadlines_once(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    session = postgres_session_service.start_session(room_id, OWNER_ID)
    app_kwargs = {
        "repository": PostgresRoomRepository(postgres_database.session_factory),
        "membership_repository": PostgresMembershipRepository(
            postgres_database.session_factory
        ),
        "user_repository": postgres_user_repository,
        "auth_verifier": auth_verifier,
        "session_service": postgres_session_service,
    }

    first_app = create_app(**app_kwargs)
    with TestClient(first_app):
        pass
    assert _force_open_question_closed(postgres_database, room_id) == session.id

    second_app = create_app(**app_kwargs)
    with TestClient(second_app) as restarted_client:
        with restarted_client.websocket_connect(f"/ws/rooms/{room_id}") as socket:
            _auth(socket, OWNER_TOKEN)
            initial = _receive_initial(socket)
            snapshot = initial[1]["payload"]
            assert snapshot["session_id"] == str(session.id)
            assert snapshot["status"] == "QUESTION_REVEAL"
            assert snapshot["state_version"] == 2
            socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "REQUEST_STATE",
                    "payload": {},
                }
            )
            repaired = socket.receive_json()
            assert repaired["type"] == "STATE_SNAPSHOT"
            assert repaired["payload"]["state_version"] == 2

    with postgres_database.session_factory() as database_session:
        persisted = database_session.get(QuizSessionModel, session.id)
        assert persisted is not None
        assert persisted.state_version == 2
        assert persisted.status == QuizSessionStatus.QUESTION_REVEAL.value

    _force_reveal_expired(postgres_database, session.id)
    third_app = create_app(**app_kwargs)
    with TestClient(third_app) as restarted_client:
        with restarted_client.websocket_connect(f"/ws/rooms/{room_id}") as socket:
            _auth(socket, OWNER_TOKEN)
            initial = _receive_initial(socket)
            snapshot = initial[1]["payload"]
            assert snapshot["session_id"] == str(session.id)
            assert snapshot["status"] == "QUESTION_OPEN"
            assert snapshot["current_question_number"] == 2
            assert snapshot["state_version"] == 3
            assert snapshot["question"]["question_number"] == 2
            assert "correct_option_id" not in snapshot["question"]

    with postgres_database.session_factory() as database_session:
        persisted = database_session.get(QuizSessionModel, session.id)
        assert persisted is not None
        assert persisted.state_version == 3
        assert persisted.status == QuizSessionStatus.QUESTION_OPEN.value
        assert persisted.current_question_position == 1
        assert persisted.reveal_ends_at is None


def test_reconnect_rebuilds_waiting_open_reveal_and_finished_snapshots(
    postgres_client: TestClient,
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
        auth_verifier,
    )
    path = f"/ws/rooms/{room_id}"

    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, SECOND_TOKEN)
        waiting = _receive_initial(socket)
        assert waiting[1]["payload"]["session_id"] is None
        assert waiting[1]["payload"]["room_state"]["viewer_ready"] is True

    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, SECOND_TOKEN)
        restored_waiting = _receive_initial(socket)
        assert restored_waiting[1]["payload"]["session_id"] is None
        assert restored_waiting[1]["payload"]["room_state"]["viewer_ready"] is True

    session = postgres_session_service.start_session(room_id, OWNER_ID)
    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, OWNER_TOKEN)
        open_state = _receive_initial(socket)
        open_snapshot = open_state[1]["payload"]
        assert open_snapshot["status"] == "QUESTION_OPEN"
        question_id = open_snapshot["question"]["session_question_id"]
        assert open_snapshot["viewer_submission"] is None

    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, OWNER_TOKEN)
        restored_open_state = _receive_initial(socket)
        restored_open_snapshot = restored_open_state[1]["payload"]
        assert restored_open_snapshot["status"] == "QUESTION_OPEN"
        assert restored_open_snapshot["question"]["session_question_id"] == question_id
        assert restored_open_snapshot["viewer_submission"] is None
        socket.send_json(
            {
                "protocol_version": 1,
                "type": "SUBMIT_ANSWER",
                "payload": {
                    "session_question_id": question_id,
                    "selected_option_id": "newton",
                },
            }
        )
        assert socket.receive_json()["type"] == "ANSWER_ACCEPTED"

    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, OWNER_TOKEN)
        answered_open_state = _receive_initial(socket)
        answered_submission = answered_open_state[1]["payload"]["viewer_submission"]
        assert answered_submission["session_question_id"] == question_id
        assert answered_submission["selected_option_id"] == "newton"
        assert "is_correct" not in answered_submission
        assert "points" not in answered_submission

    _force_open_question_closed(postgres_database, room_id)
    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, OWNER_TOKEN)
        reveal_state = _receive_initial(socket)
        reveal_snapshot = reveal_state[1]["payload"]
        assert reveal_snapshot["status"] == "QUESTION_REVEAL"
        assert reveal_snapshot["viewer_submission"]["is_correct"] is True

    current = postgres_session_service.get_session(session.id)
    assert current is not None
    while current.status != QuizSessionStatus.FINISHED:
        if current.status == QuizSessionStatus.QUESTION_OPEN:
            _force_open_question_closed(postgres_database, room_id)
        _force_reveal_expired(postgres_database, session.id)
        current = postgres_session_service.reconcile_session(session_id=session.id)

    with postgres_client.websocket_connect(path) as socket:
        _auth(socket, OWNER_TOKEN)
        finished_state = _receive_initial(socket)
        finished_snapshot = finished_state[1]["payload"]
        assert finished_snapshot["status"] == "FINISHED"
        assert finished_snapshot["finished_at"] is not None
        assert finished_snapshot["leaderboard"]
