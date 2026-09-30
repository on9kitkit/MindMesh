from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import FakeAuthVerifier
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.session import Database
from app.domain.errors import (
    InsufficientParticipantsError,
    NotRoomMemberError,
    RoomClosedError,
    RoomOwnerMustCloseError,
    RoomOwnerRequiredError,
    SessionAlreadyActiveError,
    UserAlreadyInAnotherRoomError,
)
from app.domain.member import RoomMember
from app.domain.quiz import QuizSessionStatus
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.scripts.seed_questions import seed_physics_sprint
from app.services.rooms import RoomService
from app.services.sessions import SessionService
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers

MEMBER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_OWNER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
JOINER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
MEMBER_TOKEN = "room-lifecycle-member-token"
JOINER_TOKEN = "room-lifecycle-joiner-token"


def _create_room(
    service: RoomService,
    *,
    owner_id: UUID = OWNER_ID,
    owner_name: str = "Room Owner",
    name: str = "Physics Sprint",
) -> UUID:
    return service.create_room(
        name=name,
        maximum_members=8,
        owner_id=owner_id,
        owner_display_name=owner_name,
    ).id


def _add_member(
    database: Database,
    users: PostgresUserRepository,
    room_id: UUID,
    user_id: UUID = MEMBER_ID,
    display_name: str = "Room Member",
) -> UUID:
    users.upsert_profile(user_id, display_name)
    PostgresMembershipRepository(database.session_factory).join(
        RoomMember(
            room_id=room_id,
            user_id=user_id,
            display_name=display_name,
        ),
        8,
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


def _prepare_startable_room(
    database: Database,
    rooms: RoomService,
    sessions: SessionService,
    users: PostgresUserRepository,
) -> UUID:
    room_id = _create_room(rooms)
    _add_member(database, users, room_id)
    assert seed_physics_sprint(database.session_factory) == 5
    sessions.set_ready(room_id, MEMBER_ID, True)
    return room_id


def _finish_session(database: Database, session_id: UUID) -> None:
    with database.session_factory() as session:
        with session.begin():
            model = session.get(QuizSessionModel, session_id)
            assert model is not None
            model.status = QuizSessionStatus.FINISHED.value
            model.finished_at = datetime.now(timezone.utc)
            model.reveal_ends_at = None


def _active_membership_count(database: Database, user_id: UUID) -> int:
    with database.session_factory() as session:
        count = session.scalar(
            select(func.count(RoomMembershipModel.id)).where(
                RoomMembershipModel.user_id == user_id,
                RoomMembershipModel.left_at.is_(None),
            )
        )
    return int(count or 0)


def test_member_leave_is_durable_idempotent_and_releases_active_room(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_room(postgres_service)
    membership_id = _add_member(
        postgres_database,
        postgres_user_repository,
        room_id,
    )
    postgres_session_service.set_ready(room_id, MEMBER_ID, True)

    first = postgres_service.leave_room(room_id=room_id, user_id=MEMBER_ID)
    second = postgres_service.leave_room(room_id=room_id, user_id=MEMBER_ID)

    assert first.already_left is False
    assert second.already_left is True
    assert second.left_at == first.left_at
    assert first.left_at.utcoffset() is not None
    assert postgres_service.count_room_members(room_id) == 1
    assert postgres_service.get_active_room_for_user(MEMBER_ID) is None
    with postgres_database.session_factory() as session:
        membership = session.get(RoomMembershipModel, membership_id)
        assert membership is not None
        assert membership.left_at == first.left_at
        assert membership.ready_at is None
        history_count = session.scalar(
            select(func.count(RoomMembershipModel.id)).where(
                RoomMembershipModel.room_id == room_id
            )
        )
    assert history_count == 2

    postgres_user_repository.upsert_profile(OTHER_OWNER_ID, "Other Owner")
    other_room_id = _create_room(
        postgres_service,
        owner_id=OTHER_OWNER_ID,
        owner_name="Other Owner",
        name="Second Room",
    )
    joined = postgres_service.join_room(
        room_id=other_room_id,
        user_id=MEMBER_ID,
        display_name="Room Member",
    )
    assert joined.room_id == other_room_id
    assert _active_membership_count(postgres_database, MEMBER_ID) == 1


def test_leave_rejects_never_member_and_requires_owner_to_close(
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)

    with pytest.raises(NotRoomMemberError):
        postgres_service.leave_room(room_id=room_id, user_id=MEMBER_ID)
    with pytest.raises(RoomOwnerMustCloseError):
        postgres_service.leave_room(room_id=room_id, user_id=OWNER_ID)


def test_host_close_is_durable_idempotent_and_ends_all_memberships(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_room(postgres_service)
    join_code = postgres_service.get_room(room_id).join_code
    _add_member(postgres_database, postgres_user_repository, room_id)
    postgres_session_service.set_ready(room_id, MEMBER_ID, True)

    first = postgres_service.close_room(room_id=room_id, user_id=OWNER_ID)
    second = postgres_service.close_room(room_id=room_id, user_id=OWNER_ID)

    assert first.already_closed is False
    assert second.already_closed is True
    assert second.closed_at == first.closed_at
    assert first.closed_at.utcoffset() is not None
    with postgres_database.session_factory() as session:
        room = session.get(RoomModel, room_id)
        memberships = list(
            session.scalars(
                select(RoomMembershipModel).where(
                    RoomMembershipModel.room_id == room_id
                )
            ).all()
        )
    assert room is not None
    assert room.closed_at == first.closed_at
    assert len(memberships) == 2
    assert all(member.left_at == first.closed_at for member in memberships)
    assert all(member.ready_at is None for member in memberships)
    assert postgres_service.get_active_room_for_user(OWNER_ID) is None
    assert postgres_service.get_active_room_for_user(MEMBER_ID) is None

    with pytest.raises(RoomClosedError):
        postgres_service.join_room(
            room_id=room_id,
            user_id=JOINER_ID,
            display_name="Joiner",
        )
    with pytest.raises(RoomClosedError):
        postgres_service.join_room_by_code(
            join_code=join_code,
            user_id=JOINER_ID,
            display_name="Joiner",
        )
    with pytest.raises(RoomClosedError):
        PostgresMembershipRepository(postgres_database.session_factory).add(
            RoomMember(
                room_id=room_id,
                user_id=JOINER_ID,
                display_name="Joiner",
            )
        )
    with pytest.raises(RoomClosedError):
        postgres_session_service.set_ready(room_id, OWNER_ID, True)
    with pytest.raises(RoomClosedError):
        postgres_session_service.start_session(room_id, OWNER_ID)


def test_non_owner_cannot_close_room(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_room(postgres_service)
    _add_member(postgres_database, postgres_user_repository, room_id)

    with pytest.raises(RoomOwnerRequiredError):
        postgres_service.close_room(room_id=room_id, user_id=MEMBER_ID)

    assert postgres_service.get_room(room_id).closed_at is None
    assert postgres_service.count_room_members(room_id) == 2


def test_active_session_blocks_leave_and_close_without_partial_mutation(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    postgres_session_service.start_session(room_id, OWNER_ID)

    with pytest.raises(SessionAlreadyActiveError):
        postgres_service.leave_room(room_id=room_id, user_id=MEMBER_ID)
    with pytest.raises(SessionAlreadyActiveError):
        postgres_service.close_room(room_id=room_id, user_id=OWNER_ID)

    assert postgres_service.get_room(room_id).closed_at is None
    assert postgres_service.count_room_members(room_id) == 2


def test_finished_session_permits_leave_and_close_and_preserves_history(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    quiz_session = postgres_session_service.start_session(room_id, OWNER_ID)
    _finish_session(postgres_database, quiz_session.id)

    postgres_service.leave_room(room_id=room_id, user_id=MEMBER_ID)
    postgres_service.close_room(room_id=room_id, user_id=OWNER_ID)

    with postgres_database.session_factory() as session:
        persisted_session = session.get(QuizSessionModel, quiz_session.id)
        participant_count = session.scalar(
            select(func.count(SessionParticipantModel.id)).where(
                SessionParticipantModel.session_id == quiz_session.id
            )
        )
    assert persisted_session is not None
    assert persisted_session.status == QuizSessionStatus.FINISHED.value
    assert participant_count == 2


def test_lifecycle_http_contract_uses_identity_and_returns_empty_204(
    postgres_client: TestClient,
    postgres_service: RoomService,
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
    auth_verifier: FakeAuthVerifier,
) -> None:
    room_id = _create_room(postgres_service)
    join_code = postgres_service.get_room(room_id).join_code
    _add_member(postgres_database, postgres_user_repository, room_id)
    auth_verifier.register(MEMBER_TOKEN, MEMBER_ID)
    auth_verifier.register(JOINER_TOKEN, JOINER_ID)
    postgres_user_repository.upsert_profile(JOINER_ID, "Joiner")

    leave = postgres_client.post(
        f"/rooms/{room_id}/leave",
        headers=auth_headers(MEMBER_TOKEN),
    )
    assert leave.status_code == 204
    assert leave.content == b""
    assert postgres_client.get(
        "/me/active-room",
        headers=auth_headers(MEMBER_TOKEN),
    ).json() is None
    historical_read = postgres_client.get(
        f"/rooms/{room_id}",
        headers=auth_headers(MEMBER_TOKEN),
    )
    assert historical_read.status_code == 403
    assert historical_read.json()["error"]["code"] == "not_room_member"

    close = postgres_client.post(
        f"/rooms/{room_id}/close",
        headers=auth_headers(OWNER_TOKEN),
    )
    assert close.status_code == 204
    assert close.content == b""
    closed_read = postgres_client.get(
        f"/rooms/{room_id}",
        headers=auth_headers(OWNER_TOKEN),
    )
    assert closed_read.status_code == 409
    assert closed_read.json()["error"]["code"] == "room_closed"
    for path, body in (
        ("/rooms/join", {"join_code": join_code}),
        (f"/rooms/{room_id}/members", None),
    ):
        request: dict[str, object] = {
            "headers": auth_headers(JOINER_TOKEN),
        }
        if body is not None:
            request["json"] = body
        closed_join = postgres_client.post(path, **request)
        if path == "/rooms/join":
            assert closed_join.status_code == 404
            assert closed_join.json()["error"]["code"] == "room_join_unavailable"
        else:
            assert closed_join.status_code == 409
            assert closed_join.json()["error"]["code"] == "room_closed"
    assert postgres_client.get(
        "/me/active-room",
        headers=auth_headers(OWNER_TOKEN),
    ).json() is None


def test_lifecycle_http_errors_are_stable_and_do_not_mutate_active_room(
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
    )
    auth_verifier.register(MEMBER_TOKEN, MEMBER_ID)

    owner_leave = postgres_client.post(
        f"/rooms/{room_id}/leave",
        headers=auth_headers(OWNER_TOKEN),
    )
    member_close = postgres_client.post(
        f"/rooms/{room_id}/close",
        headers=auth_headers(MEMBER_TOKEN),
    )

    assert owner_leave.status_code == 409
    assert owner_leave.json()["error"]["code"] == "room_owner_must_close"
    assert member_close.status_code == 403
    assert member_close.json()["error"]["code"] == "room_owner_required"

    postgres_session_service.start_session(room_id, OWNER_ID)
    for path, token in (
        ("leave", MEMBER_TOKEN),
        ("close", OWNER_TOKEN),
    ):
        response = postgres_client.post(
            f"/rooms/{room_id}/{path}",
            headers=auth_headers(token),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "session_already_active"

    assert postgres_service.get_room(room_id).closed_at is None
    assert postgres_service.count_room_members(room_id) == 2


def test_leave_and_start_race_has_one_coherent_winner(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    barrier = Barrier(2)

    def leave() -> str:
        barrier.wait(timeout=10)
        try:
            postgres_service.leave_room(room_id=room_id, user_id=MEMBER_ID)
            return "left"
        except SessionAlreadyActiveError:
            return "session-active"

    def start() -> str:
        barrier.wait(timeout=10)
        try:
            postgres_session_service.start_session(room_id, OWNER_ID)
            return "started"
        except InsufficientParticipantsError:
            return "insufficient"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(leave), executor.submit(start)]
        outcomes = {future.result(timeout=20) for future in futures}

    assert outcomes in (
        {"left", "insufficient"},
        {"session-active", "started"},
    )
    active_session = postgres_session_service.get_active_session(room_id)
    active_member = _active_membership_count(postgres_database, MEMBER_ID)
    assert (active_session is not None, active_member) in ((True, 1), (False, 0))


def test_close_and_join_race_cannot_leave_an_active_member_in_closed_room(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_room(postgres_service)
    postgres_user_repository.upsert_profile(JOINER_ID, "Joiner")
    barrier = Barrier(2)

    def close() -> str:
        barrier.wait(timeout=10)
        postgres_service.close_room(room_id=room_id, user_id=OWNER_ID)
        return "closed"

    def join() -> str:
        barrier.wait(timeout=10)
        try:
            postgres_service.join_room(
                room_id=room_id,
                user_id=JOINER_ID,
                display_name="Joiner",
            )
            return "joined"
        except RoomClosedError:
            return "room-closed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(close), executor.submit(join)]
        outcomes = {future.result(timeout=20) for future in futures}

    assert "closed" in outcomes
    assert outcomes <= {"closed", "joined", "room-closed"}
    assert postgres_service.get_room(room_id).is_closed
    assert _active_membership_count(postgres_database, JOINER_ID) == 0


def test_close_and_start_race_has_one_coherent_lifecycle_direction(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_session_service: SessionService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _prepare_startable_room(
        postgres_database,
        postgres_service,
        postgres_session_service,
        postgres_user_repository,
    )
    barrier = Barrier(2)

    def close() -> str:
        barrier.wait(timeout=10)
        try:
            postgres_service.close_room(room_id=room_id, user_id=OWNER_ID)
            return "closed"
        except SessionAlreadyActiveError:
            return "session-active"

    def start() -> str:
        barrier.wait(timeout=10)
        try:
            postgres_session_service.start_session(room_id, OWNER_ID)
            return "started"
        except RoomClosedError:
            return "room-closed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(close), executor.submit(start)]
        outcomes = {future.result(timeout=20) for future in futures}

    assert outcomes in (
        {"closed", "room-closed"},
        {"session-active", "started"},
    )
    room = postgres_service.get_room(room_id)
    active_session = postgres_session_service.get_active_session(room_id)
    assert (room.is_closed, active_session is not None) in (
        (True, False),
        (False, True),
    )


def test_leave_and_join_other_room_race_never_creates_two_active_memberships(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    first_room_id = _create_room(postgres_service)
    _add_member(postgres_database, postgres_user_repository, first_room_id)
    postgres_user_repository.upsert_profile(OTHER_OWNER_ID, "Other Owner")
    second_room_id = _create_room(
        postgres_service,
        owner_id=OTHER_OWNER_ID,
        owner_name="Other Owner",
        name="Other Room",
    )
    barrier = Barrier(2)

    def leave() -> str:
        barrier.wait(timeout=10)
        postgres_service.leave_room(room_id=first_room_id, user_id=MEMBER_ID)
        return "left"

    def join() -> str:
        barrier.wait(timeout=10)
        try:
            postgres_service.join_room(
                room_id=second_room_id,
                user_id=MEMBER_ID,
                display_name="Room Member",
            )
            return "joined"
        except UserAlreadyInAnotherRoomError:
            return "active-conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(leave), executor.submit(join)]
        outcomes = {future.result(timeout=20) for future in futures}

    assert "left" in outcomes
    assert outcomes <= {"left", "joined", "active-conflict"}
    assert _active_membership_count(postgres_database, MEMBER_ID) <= 1


def test_simultaneous_leave_retries_create_one_transition(
    postgres_database: Database,
    postgres_service: RoomService,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = _create_room(postgres_service)
    membership_id = _add_member(
        postgres_database,
        postgres_user_repository,
        room_id,
    )
    barrier = Barrier(2)

    def leave():
        barrier.wait(timeout=10)
        return PostgresRoomRepository(
            postgres_database.session_factory
        ).leave_member(room_id, MEMBER_ID)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: leave(), range(2)))

    assert sorted(outcome.already_left for outcome in outcomes) == [False, True]
    assert outcomes[0].left_at == outcomes[1].left_at
    with postgres_database.session_factory() as session:
        membership = session.get(RoomMembershipModel, membership_id)
        history_count = session.scalar(
            select(func.count(RoomMembershipModel.id)).where(
                RoomMembershipModel.room_id == room_id,
                RoomMembershipModel.user_id == MEMBER_ID,
            )
        )
    assert membership is not None and membership.left_at == outcomes[0].left_at
    assert history_count == 1


def test_simultaneous_close_retries_keep_one_closure_timestamp(
    postgres_database: Database,
    postgres_service: RoomService,
) -> None:
    room_id = _create_room(postgres_service)
    barrier = Barrier(2)

    def close():
        barrier.wait(timeout=10)
        return PostgresRoomRepository(
            postgres_database.session_factory
        ).close_room(room_id, OWNER_ID)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: close(), range(2)))

    assert sorted(outcome.already_closed for outcome in outcomes) == [False, True]
    assert outcomes[0].closed_at == outcomes[1].closed_at
    with postgres_database.session_factory() as session:
        room = session.get(RoomModel, room_id)
    assert room is not None and room.closed_at == outcomes[0].closed_at
