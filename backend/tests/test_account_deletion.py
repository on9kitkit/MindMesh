from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from starlette.websockets import WebSocketDisconnect

from app.account_deletion import AccountDeletionService
from app.account_deletion.ports import (
    AccountDeletionProviderError,
    RevenueCatCustomerDeletionProvider,
    SupabaseAuthDeletionProvider,
)
from app.account_deletion.providers import (
    RevenueCatCustomerAdminDeletionProvider,
    SupabaseAuthAdminDeletionProvider,
)
from app.account_deletion.repository import (
    AccountDeletionLocalResult,
    PostgresAccountDeletionRepository,
)
from app.auth import FakeAuthVerifier
from app.db.models.account_deletion_outbox import AccountDeletionOutboxModel
from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.models.question import QuestionModel
from app.db.models.user import UserModel
from app.db.session import Database
from app.domain.errors import (
    AccountDeletionBlockedActiveQuizError,
    AccountDeletedError,
    RoomClosedError,
    SessionStartConflictError,
)
from app.domain.quiz import QuizSession, QuizSessionStatus
from app.main import create_app
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.scripts.seed_questions import seed_physics_sprint
from app.services.rooms import RoomService
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


OTHER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_TOKEN = "account-deletion-other-token"


class RecordingSupabaseProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[UUID] = []
        self.fail = fail

    def delete_identity(self, user_id: UUID) -> None:
        self.calls.append(user_id)
        if self.fail:
            raise AccountDeletionProviderError("provider_temporarily_unavailable")


class RecordingRevenueCatProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def delete_customer(self, customer_id: str) -> None:
        self.calls.append(customer_id)
        if self.fail:
            raise AccountDeletionProviderError("provider_temporarily_unavailable")


def _ensure_user(database: Database, user_id: UUID, display_name: str) -> None:
    PostgresUserRepository(database.session_factory).upsert_profile(
        user_id,
        display_name,
    )


def _create_room_with_member(
    database: Database,
    *,
    owner_id: UUID = OWNER_ID,
    member_id: UUID = OTHER_ID,
) -> tuple[UUID, UUID, UUID]:
    _ensure_user(database, owner_id, "Room Owner")
    _ensure_user(database, member_id, "Other Player")
    room_id = uuid4()
    owner_membership_id = uuid4()
    member_membership_id = uuid4()
    with database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=owner_id,
                    name="Private Study Room",
                    join_code="DEL123",
                    maximum_members=8,
                )
            )
            session.flush()
            session.add_all(
                [
                    RoomMembershipModel(
                        id=owner_membership_id,
                        room_id=room_id,
                        user_id=owner_id,
                    ),
                    RoomMembershipModel(
                        id=member_membership_id,
                        room_id=room_id,
                        user_id=member_id,
                    ),
                ]
            )
    return room_id, owner_membership_id, member_membership_id


def _account_deletion_service(
    database: Database,
    *,
    supabase_provider: SupabaseAuthDeletionProvider | None = None,
    revenuecat_provider: RevenueCatCustomerDeletionProvider | None = None,
) -> AccountDeletionService:
    return AccountDeletionService(
        PostgresAccountDeletionRepository(database.session_factory),
        supabase_provider=supabase_provider,
        revenuecat_provider=revenuecat_provider,
    )


def _capture(operation: Callable[[], object]) -> object:
    try:
        return operation()
    except Exception as error:
        return error


def test_local_deletion_is_one_transaction_and_outbox_is_idempotent(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    _ensure_user(postgres_database, OTHER_ID, "Other Player")
    room_id, _, member_membership_id = _create_room_with_member(postgres_database)
    supabase = RecordingSupabaseProvider()
    revenuecat = RecordingRevenueCatProvider()
    service = _account_deletion_service(
        postgres_database,
        supabase_provider=supabase,
        revenuecat_provider=revenuecat,
    )

    result = service.delete_local_account(OWNER_ID)

    assert result.already_deleted is False
    assert result.closed_room_ids == (room_id,)
    assert supabase.calls == []
    assert revenuecat.calls == []
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, OWNER_ID)
        room = session.get(RoomModel, room_id)
        surviving_membership = session.get(
            RoomMembershipModel,
            member_membership_id,
        )
        jobs = list(
            session.scalars(
                select(AccountDeletionOutboxModel).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        )
    assert user is not None
    assert user.deleted_at is not None
    assert user.display_name == "Deleted user"
    assert room is not None
    assert room.name == "Deleted room"
    assert room.closed_at is not None
    assert surviving_membership is not None
    assert surviving_membership.left_at == room.closed_at
    assert len(jobs) == 2
    assert {job.provider for job in jobs} == {"supabase_auth", "revenuecat"}

    service.process_user_jobs(OWNER_ID)
    second = service.delete_local_account(OWNER_ID)

    assert supabase.calls == [OWNER_ID]
    assert revenuecat.calls == [str(OWNER_ID)]
    assert second.already_deleted is True
    assert len(PostgresAccountDeletionRepository(postgres_database.session_factory).list_jobs(OWNER_ID)) == 2
    with postgres_database.session_factory() as session:
        statuses = set(
            session.scalars(
                select(AccountDeletionOutboxModel.status).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        )
    assert statuses == {"completed"}
    with pytest.raises(AccountDeletedError):
        postgres_user_repository.upsert_profile(OWNER_ID, "Recreated")


@pytest.mark.parametrize(
    "status",
    [QuizSessionStatus.QUESTION_OPEN.value, QuizSessionStatus.QUESTION_REVEAL.value],
)
def test_deletion_is_blocked_for_a_live_quiz(
    postgres_database: Database,
    status: str,
) -> None:
    _ensure_user(postgres_database, OTHER_ID, "Other Player")
    room_id, owner_membership_id, _ = _create_room_with_member(postgres_database)
    with postgres_database.session_factory() as session:
        with session.begin():
            session_model = QuizSessionModel(
                id=uuid4(),
                room_id=room_id,
                question_bank_key="physics_sprint",
                status=status,
                current_question_position=0,
                state_version=1,
                started_at=datetime.now(timezone.utc),
            )
            session.add(session_model)
            session.flush()
            session.add(
                SessionParticipantModel(
                    id=uuid4(),
                    session_id=session_model.id,
                    user_id=OWNER_ID,
                    room_membership_id=owner_membership_id,
                    display_name_snapshot="Room Owner",
                )
            )

    repository = PostgresAccountDeletionRepository(postgres_database.session_factory)
    with pytest.raises(AccountDeletionBlockedActiveQuizError):
        repository.delete_local_account(OWNER_ID)
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, OWNER_ID)
        jobs = session.scalar(
            select(AccountDeletionOutboxModel.id).where(
                AccountDeletionOutboxModel.user_id == OWNER_ID
            )
        )
    assert user is not None
    assert user.deleted_at is None
    assert jobs is None


def test_finished_history_keeps_other_participant_and_answer(
    postgres_database: Database,
) -> None:
    _ensure_user(postgres_database, OTHER_ID, "Other Player")
    room_id, owner_membership_id, member_membership_id = _create_room_with_member(
        postgres_database
    )
    now = datetime.now(timezone.utc)
    with postgres_database.session_factory() as session:
        with session.begin():
            question = QuestionModel(
                id=uuid4(),
                bank_key="physics_sprint",
                stable_key="deletion-test",
                position=0,
                prompt="What is measured in newtons?",
                options=[{"id": "a", "label": "Force"}, {"id": "b", "label": "Mass"}],
                correct_option_id="a",
                duration_seconds=30,
                is_active=True,
            )
            session.add(question)
            quiz_session = QuizSessionModel(
                id=uuid4(),
                room_id=room_id,
                question_bank_key="physics_sprint",
                status=QuizSessionStatus.FINISHED.value,
                current_question_position=0,
                state_version=2,
                started_at=now - timedelta(minutes=2),
                finished_at=now - timedelta(minutes=1),
            )
            session.add(quiz_session)
            session.flush()
            session_question = SessionQuestionModel(
                id=uuid4(),
                session_id=quiz_session.id,
                source_question_id=question.id,
                position=0,
                prompt_snapshot=question.prompt,
                options_snapshot=question.options,
                correct_option_id=question.correct_option_id,
                duration_seconds=30,
                opened_at=now - timedelta(minutes=2),
                closes_at=now - timedelta(minutes=1, seconds=30),
            )
            session.add(session_question)
            owner_participant = SessionParticipantModel(
                id=uuid4(),
                session_id=quiz_session.id,
                user_id=OWNER_ID,
                room_membership_id=owner_membership_id,
                display_name_snapshot="Room Owner",
            )
            other_participant = SessionParticipantModel(
                id=uuid4(),
                session_id=quiz_session.id,
                user_id=OTHER_ID,
                room_membership_id=member_membership_id,
                display_name_snapshot="Other Player",
            )
            session.add_all([owner_participant, other_participant])
            session.flush()
            session.add_all(
                [
                    AnswerSubmissionModel(
                        id=uuid4(),
                        session_id=quiz_session.id,
                        session_question_id=session_question.id,
                        participant_id=owner_participant.id,
                        selected_option_id="a",
                        submitted_at=now - timedelta(minutes=1, seconds=45),
                        response_time_ms=5000,
                        is_correct=True,
                        points=100,
                    ),
                    AnswerSubmissionModel(
                        id=uuid4(),
                        session_id=quiz_session.id,
                        session_question_id=session_question.id,
                        participant_id=other_participant.id,
                        selected_option_id="b",
                        submitted_at=now - timedelta(minutes=1, seconds=40),
                        response_time_ms=10000,
                        is_correct=False,
                        points=0,
                    ),
                ]
            )

    PostgresAccountDeletionRepository(
        postgres_database.session_factory
    ).delete_local_account(OWNER_ID)

    with postgres_database.session_factory() as session:
        participants = list(session.scalars(select(SessionParticipantModel)).all())
        answers = list(session.scalars(select(AnswerSubmissionModel)).all())
        room = session.get(RoomModel, room_id)
    assert [participant.user_id for participant in participants] == [OTHER_ID]
    assert len(answers) == 1
    assert answers[0].participant_id == participants[0].id
    assert room is not None
    assert room.name == "Deleted room"


def test_api_requires_recent_auth_and_denies_old_jwt_after_tombstone(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id, _, _ = _create_room_with_member(postgres_database)
    supabase = RecordingSupabaseProvider()
    revenuecat = RecordingRevenueCatProvider()
    deletion_service = _account_deletion_service(
        postgres_database,
        supabase_provider=supabase,
        revenuecat_provider=revenuecat,
    )
    verifier = FakeAuthVerifier()
    verifier.register(
        OWNER_TOKEN,
        OWNER_ID,
        authenticated_at=datetime.now(timezone.utc),
    )
    app = create_app(
        repository=PostgresRoomRepository(postgres_database.session_factory),
        membership_repository=PostgresMembershipRepository(
            postgres_database.session_factory
        ),
        user_repository=postgres_user_repository,
        auth_verifier=verifier,
        account_deletion_service=deletion_service,
    )
    with TestClient(app) as client:
        response = client.request(
            "DELETE",
            "/me",
            headers=auth_headers(),
            json={"confirmation": "DELETE"},
        )
        assert response.status_code == 202
        assert response.json() == {
            "status": "account_deleted",
            "local_deletion_complete": True,
            "provider_cleanup_pending": False,
        }
        for method, path, kwargs in (
            ("get", "/me", {}),
            ("put", "/me/profile", {"json": {"display_name": "Recreated"}}),
            (
                "post",
                "/rooms",
                {"json": {"name": "Should fail", "maximum_members": 2}},
            ),
            (
                "post",
                "/rooms/join",
                {"json": {"join_code": "DEL123"}},
            ),
        ):
            blocked = getattr(client, method)(
                path,
                headers=auth_headers(),
                **kwargs,
            )
            assert blocked.status_code == 403
            assert blocked.json()["error"]["code"] == "account_deleted"
        with client.websocket_connect(f"/ws/rooms/{room_id}") as socket:
            socket.send_json(
                {
                    "protocol_version": 1,
                    "type": "AUTHENTICATE",
                    "payload": {"access_token": OWNER_TOKEN},
                }
            )
            error = socket.receive_json()
            assert error["type"] == "ERROR"
            assert error["payload"]["code"] == "account_deleted"
            with pytest.raises(WebSocketDisconnect) as disconnected:
                socket.receive_json()
            assert disconnected.value.code == 4403
        incomplete = client.request(
            "DELETE",
            "/me",
            headers=auth_headers(),
            json={"confirmation": "delete"},
        )
        assert incomplete.status_code == 403
        assert incomplete.json()["error"]["code"] == "account_deleted"


def test_delete_fails_closed_without_recent_authentication_proof(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    verifier = FakeAuthVerifier()
    verifier.register(OWNER_TOKEN, OWNER_ID)
    app = create_app(
        repository=PostgresRoomRepository(postgres_database.session_factory),
        membership_repository=PostgresMembershipRepository(
            postgres_database.session_factory
        ),
        user_repository=postgres_user_repository,
        auth_verifier=verifier,
        account_deletion_service=_account_deletion_service(postgres_database),
    )

    with TestClient(app) as client:
        response = client.request(
            "DELETE",
            "/me",
            headers=auth_headers(),
            json={"confirmation": "DELETE"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "recent_authentication_required"
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, OWNER_ID)
        assert user is not None
        assert user.deleted_at is None


def test_concurrent_delete_requests_have_one_local_winner(
    postgres_database: Database,
) -> None:
    _ensure_user(postgres_database, OWNER_ID, "Room Owner")
    services = [
        _account_deletion_service(postgres_database),
        _account_deletion_service(postgres_database),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.delete_local_account, OWNER_ID)
            for service in services
        ]
        results = [future.result() for future in futures]

    assert sorted(
        result.already_deleted
        for result in results
        if isinstance(result, AccountDeletionLocalResult)
    ) == [False, True]
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, OWNER_ID)
        jobs = list(
            session.scalars(
                select(AccountDeletionOutboxModel).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        )
    assert user is not None and user.deleted_at is not None
    assert {job.provider for job in jobs} == {"supabase_auth", "revenuecat"}


def test_delete_races_start_session_without_leaving_a_live_deleted_participant(
    postgres_database: Database,
) -> None:
    seed_physics_sprint(postgres_database.session_factory)
    room_id, _, _ = _create_room_with_member(postgres_database)
    session_repository = PostgresQuizSessionRepository(
        postgres_database.session_factory
    )
    session_repository.set_ready(room_id, OWNER_ID, True)
    session_repository.set_ready(room_id, OTHER_ID, True)
    deletion_repository = PostgresAccountDeletionRepository(
        postgres_database.session_factory
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        delete_future = executor.submit(
            _capture,
            lambda: deletion_repository.delete_local_account(OWNER_ID),
        )
        start_future = executor.submit(
            _capture,
            lambda: session_repository.start_session(room_id, OWNER_ID),
        )
        delete_result = delete_future.result()
        start_result = start_future.result()

    if isinstance(delete_result, AccountDeletionLocalResult):
        assert delete_result.already_deleted is False
        assert isinstance(start_result, (RoomClosedError, SessionStartConflictError))
    else:
        assert isinstance(delete_result, AccountDeletionBlockedActiveQuizError)
        assert isinstance(start_result, QuizSession)


def test_provider_failure_keeps_local_tombstone_and_retry_completes(
    postgres_database: Database,
) -> None:
    _ensure_user(postgres_database, OWNER_ID, "Room Owner")
    supabase = RecordingSupabaseProvider(fail=True)
    revenuecat = RecordingRevenueCatProvider(fail=True)
    service = _account_deletion_service(
        postgres_database,
        supabase_provider=supabase,
        revenuecat_provider=revenuecat,
    )

    service.delete_local_account(OWNER_ID)
    first_summary = service.process_user_jobs(OWNER_ID)
    assert first_summary.pending is True
    with postgres_database.session_factory() as session:
        session.execute(
            update(AccountDeletionOutboxModel)
            .where(AccountDeletionOutboxModel.user_id == OWNER_ID)
            .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        session.commit()

    supabase.fail = False
    revenuecat.fail = False
    retry_summary = service.retry_pending()

    assert retry_summary.pending is False
    assert supabase.calls == [OWNER_ID, OWNER_ID]
    assert revenuecat.calls == [str(OWNER_ID), str(OWNER_ID)]
    with postgres_database.session_factory() as session:
        assert session.get(UserModel, OWNER_ID).deleted_at is not None
        statuses = set(
            session.scalars(
                select(AccountDeletionOutboxModel.status).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        )
    assert statuses == {"completed"}


def test_provider_adapters_accept_absent_customer_without_exposing_response() -> None:
    def absent(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    secret = "unit-test-key-value"
    supabase = SupabaseAuthAdminDeletionProvider(
        "https://project.supabase.co",
        SecretStr(secret),
        transport=httpx.MockTransport(absent),
    )
    revenuecat = RevenueCatCustomerAdminDeletionProvider(
        "project-id",
        SecretStr(secret),
        SecretStr(secret),
        transport=httpx.MockTransport(absent),
    )
    supabase.delete_identity(OWNER_ID)
    revenuecat.delete_customer(str(OWNER_ID))
    supabase.close()
    revenuecat.close()


def test_queued_revenuecat_deletion_stays_pending_and_skips_unrelated_jobs(
    postgres_database: Database,
) -> None:
    _ensure_user(postgres_database, OWNER_ID, "Deleted Owner")
    _ensure_user(postgres_database, OTHER_ID, "Unrelated Deleted User")
    requests: list[str] = []

    def queued_and_present(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        status_code = 202 if request.method == "DELETE" else 200
        return httpx.Response(status_code, request=request)

    supabase = RecordingSupabaseProvider()
    revenuecat = RevenueCatCustomerAdminDeletionProvider(
        "project-id",
        SecretStr("unit-test-deletion-key"),
        SecretStr("unit-test-read-key"),
        transport=httpx.MockTransport(queued_and_present),
        sleep=lambda _seconds: None,
    )
    service = _account_deletion_service(
        postgres_database,
        supabase_provider=supabase,
        revenuecat_provider=revenuecat,
    )

    try:
        service.delete_local_account(OWNER_ID)
        service.delete_local_account(OTHER_ID)
        summary = service.process_user_jobs(OWNER_ID)
    finally:
        service.close()

    assert summary.attempted_jobs == 2
    assert summary.pending is True
    assert supabase.calls == [OWNER_ID]
    assert requests[0] == "DELETE"
    assert requests[1:] and set(requests[1:]) == {"GET"}
    with postgres_database.session_factory() as session:
        owner = session.get(UserModel, OWNER_ID)
        owner_jobs = {
            job.provider: job
            for job in session.scalars(
                select(AccountDeletionOutboxModel).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        }
        unrelated_jobs = list(
            session.scalars(
                select(AccountDeletionOutboxModel).where(
                    AccountDeletionOutboxModel.user_id == OTHER_ID
                )
            ).all()
        )
    assert owner is not None and owner.deleted_at is not None
    assert owner_jobs["supabase_auth"].status == "completed"
    assert owner_jobs["revenuecat"].status == "pending"
    assert owner_jobs["revenuecat"].completed_at is None
    assert owner_jobs["revenuecat"].last_error_category == "queued_not_confirmed"
    assert all(job.status == "pending" for job in unrelated_jobs)
    assert all(job.attempts == 0 for job in unrelated_jobs)


def test_confirmed_revenuecat_absence_completes_once(
    postgres_database: Database,
) -> None:
    _ensure_user(postgres_database, OWNER_ID, "Deleted Owner")
    requests: list[str] = []

    def queued_then_absent(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        status_code = 202 if request.method == "DELETE" else 404
        return httpx.Response(status_code, request=request)

    supabase = RecordingSupabaseProvider()
    revenuecat = RevenueCatCustomerAdminDeletionProvider(
        "project-id",
        SecretStr("unit-test-deletion-key"),
        SecretStr("unit-test-read-key"),
        transport=httpx.MockTransport(queued_then_absent),
        sleep=lambda _seconds: None,
    )
    service = _account_deletion_service(
        postgres_database,
        supabase_provider=supabase,
        revenuecat_provider=revenuecat,
    )

    try:
        service.delete_local_account(OWNER_ID)
        first = service.process_user_jobs(OWNER_ID)
        second = service.process_user_jobs(OWNER_ID)
    finally:
        service.close()

    assert first.attempted_jobs == 2
    assert first.pending is False
    assert second.attempted_jobs == 0
    assert second.pending is False
    assert supabase.calls == [OWNER_ID]
    assert requests == ["DELETE", "GET"]
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, OWNER_ID)
        jobs = list(
            session.scalars(
                select(AccountDeletionOutboxModel).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        )
    assert user is not None and user.deleted_at is not None
    assert all(job.status == "completed" for job in jobs)
    assert all(job.attempts == 1 for job in jobs)


def test_lost_revenuecat_delete_response_retries_to_idempotent_completion(
    postgres_database: Database,
) -> None:
    _ensure_user(postgres_database, OWNER_ID, "Deleted Owner")
    delete_count = 0

    def lost_then_absent(request: httpx.Request) -> httpx.Response:
        nonlocal delete_count
        assert request.method == "DELETE"
        delete_count += 1
        if delete_count == 1:
            raise httpx.ReadTimeout("simulated response loss", request=request)
        return httpx.Response(404, request=request)

    supabase = RecordingSupabaseProvider()
    revenuecat = RevenueCatCustomerAdminDeletionProvider(
        "project-id",
        SecretStr("unit-test-deletion-key"),
        SecretStr("unit-test-read-key"),
        transport=httpx.MockTransport(lost_then_absent),
        sleep=lambda _seconds: None,
    )
    service = _account_deletion_service(
        postgres_database,
        supabase_provider=supabase,
        revenuecat_provider=revenuecat,
    )

    try:
        service.delete_local_account(OWNER_ID)
        first = service.process_user_jobs(OWNER_ID)
        with postgres_database.session_factory() as session:
            session.execute(
                update(AccountDeletionOutboxModel)
                .where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID,
                    AccountDeletionOutboxModel.provider == "revenuecat",
                )
                .values(
                    next_attempt_at=(
                        datetime.now(timezone.utc) - timedelta(seconds=1)
                    )
                )
            )
            session.commit()
        second = service.retry_pending()
    finally:
        service.close()

    assert first.pending is True
    assert second.attempted_jobs == 1
    assert second.pending is False
    assert supabase.calls == [OWNER_ID]
    assert delete_count == 2
    with postgres_database.session_factory() as session:
        user = session.get(UserModel, OWNER_ID)
        jobs = {
            job.provider: job
            for job in session.scalars(
                select(AccountDeletionOutboxModel).where(
                    AccountDeletionOutboxModel.user_id == OWNER_ID
                )
            ).all()
        }
    assert user is not None and user.deleted_at is not None
    assert jobs["supabase_auth"].status == "completed"
    assert jobs["supabase_auth"].attempts == 1
    assert jobs["revenuecat"].status == "completed"
    assert jobs["revenuecat"].attempts == 2
