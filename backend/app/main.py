from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import asyncio
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.account_deletion import router as account_deletion_router
from app.api.learning_summary import router as learning_summary_router
from app.api.learning_companions import router as learning_companions_router
from app.api.solo import router as solo_router
from app.api.profile import router as profile_router
from app.account_deletion import (
    AccountDeletionOperations,
    AccountDeletionService,
    AccountDeletionSettings,
    PostgresAccountDeletionRepository,
)
from app.account_deletion.providers import (
    AccountDeletionProviderConfiguration,
    build_deletion_providers,
)
from app.api.quiz import router as quiz_router
from app.api.rooms import router as rooms_router
from app.api.safety_reports import router as safety_reports_router
from app.api.websocket import router as websocket_router
from app.auth import AuthVerifier, SupabaseJWKSAuthVerifier
from app.config import LOCAL_DEVELOPMENT_ORIGINS, RuntimeSettings
from app.domain.errors import (
    AuthenticationRequiredError,
    InvalidAuthTokenError,
    InvalidRoomDataError,
    NotRoomMemberError,
    NotSessionParticipantError,
    PremiumVerificationUnavailableError,
    ProRequiredError,
    QuizSessionError,
    RoomClosedError,
    RoomCreationError,
    RoomMembershipError,
    RoomNotFoundError,
    RoomOwnerMustCloseError,
    RoomOwnerRequiredError,
    UserProfileRequiredError,
    AccountDeletedError,
    AccountSuspendedError,
    AccountDeletionBlockedActiveQuizError,
    AccountDeletionUnavailableError,
    InvalidDisplayNameError,
    RecentAuthenticationRequiredError,
    RoomJoinRateLimitedError,
    RoomJoinUnavailableError,
    SafetyReportNotAllowedError,
    SafetyReportUnavailableError,
)
from app.domain.errors import (
    AiGenerationUnavailableError,
    PreparationConflictError,
    PreparationFailedError,
    QuizNotReadyError,
)
from app.domain.quiz import QuizSession, QuizSessionStatus
from app.domain.quiz_preparation import QuizPreparation
from app.generator.openai_adapter import OpenAiQuizContentGenerator
from app.generator.protocol import QuizContentGenerator
from app.grading.coordinator import GradingCoordinator
from app.grading.openai_grader import OpenAiWrittenAnswerGrader
from app.grading.protocol import WrittenAnswerGrader
from app.learning_companions.pet_service import PetService
from app.learning_companions.reward_repository import RewardRepository
from app.learning_companions.reward_service import RewardService
from app.learning_companions.reward_worker import RewardWorker
from app.learning_companions.solo_grading_admission import GradingAdmission
from app.learning_companions.solo_repository import PostgresSoloRepository
from app.learning_companions.solo_service import SoloService
from app.repositories.postgres_quiz_preparations import PostgresQuizPreparationRepository
from app.services.quiz_preparation_service import QuizPreparationService
from app.generator.verification.protocol import QuizContentVerifier
from app.generator.verification.openai_adapter import (
    OpenAiBlindQuizSolver,
    OpenAiQuizConsistencyAssessor,
)
from app.generator.verification.verifier import QuizContentVerificationService
from app.db.session import Database
from app.repositories.members import InMemoryMembershipRepository, MembershipRepository
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_quiz_sessions import PostgresQuizSessionRepository
from app.repositories.learning_summary import LearningSummaryRepository
from app.repositories.postgres_learning_summary import (
    PostgresLearningSummaryRepository,
)
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.repositories.rooms import InMemoryRoomRepository, RoomRepository
from app.repositories.users import InMemoryUserRepository, UserRepository
from app.premium.config import (
    RevenueCatConfigurationError,
    RevenueCatServerConfiguration,
)
from app.premium.revenuecat import RevenueCatEntitlementVerifier
from app.premium.verifier import PremiumEntitlementVerifier
from app.realtime.deadlines import DeadlineCoordinator
from app.realtime.manager import ConnectionManager
from app.realtime.publisher import RealtimePublisher
from app.services.rooms import RoomService
from app.services.join_throttle import JoinFailureThrottle
from app.services.sessions import SessionService
from app.services.safety_reports import (
    InMemorySafetyReportService,
    PostgresSafetyReportService,
    SafetyReportOperations,
)
from sqlalchemy import text as sql_text

# Kept as a compatibility alias for local tooling. Runtime requests use the
# validated RuntimeSettings instance passed to create_app().
DEVELOPMENT_CORS_ORIGINS = LOCAL_DEVELOPMENT_ORIGINS
LEARNING_SCHEMA_REVISION = "0012_learning_companions"


def _require_learning_schema(database: Database) -> None:
    """Fail closed; application startup never applies an unapproved migration."""
    with database.session_factory() as session:
        revision = session.scalar(sql_text("SELECT version_num FROM alembic_version"))
    if revision != LEARNING_SCHEMA_REVISION:
        raise RuntimeError("Learning companions database revision 0012 is required.")


def _error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def create_app(
    *,
    repository: RoomRepository | None = None,
    membership_repository: MembershipRepository | None = None,
    service: RoomService | None = None,
    user_repository: UserRepository | None = None,
    auth_verifier: AuthVerifier | None = None,
    session_service: SessionService | None = None,
    premium_entitlement_verifier: PremiumEntitlementVerifier | None = None,
    premium_entitlement_lookup_key: str | None = None,
    runtime_settings: RuntimeSettings | None = None,
    account_deletion_service: AccountDeletionOperations | None = None,
    account_deletion_settings: AccountDeletionSettings | None = None,
    safety_report_service: SafetyReportOperations | None = None,
    join_failure_throttle: JoinFailureThrottle | None = None,
    quiz_preparation_service: QuizPreparationService | None = None,
    quiz_generator: QuizContentGenerator | None = None,
    quiz_verifier: QuizContentVerifier | None = None,
    written_grader: WrittenAnswerGrader | None = None,
    grading_coordinator: GradingCoordinator | None = None,
    learning_summary_repository: LearningSummaryRepository | None = None,
) -> FastAPI:
    configured_runtime_settings = (
        runtime_settings or RuntimeSettings.from_environment()
    )
    configured_account_deletion_settings = (
        account_deletion_settings or AccountDeletionSettings.from_environment()
    )

    if service is not None and (
        repository is not None or membership_repository is not None
    ):
        raise ValueError("provide either service or repositories, not both")

    injected_dependencies = (
        service is not None
        or repository is not None
        or membership_repository is not None
    )
    configured_service = (
        service
        if service is not None
        else (
            RoomService(
                repository or InMemoryRoomRepository(),
                membership_repository=membership_repository
                or InMemoryMembershipRepository(),
                premium_entitlement_verifier=premium_entitlement_verifier,
                premium_entitlement_lookup_key=premium_entitlement_lookup_key,
            )
            if injected_dependencies
            else None
        )
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database: Database | None = None
        owned_revenuecat_verifier: RevenueCatEntitlementVerifier | None = None
        owned_account_deletion_service: AccountDeletionService | None = None
        connection_manager = ConnectionManager()
        app.state.connection_manager = connection_manager
        app.state.realtime_manager = connection_manager
        app.state.runtime_settings = configured_runtime_settings
        app.state.account_deletion_settings = configured_account_deletion_settings
        app.state.account_deletion_service = account_deletion_service
        app.state.join_failure_throttle = (
            join_failure_throttle or JoinFailureThrottle()
        )
        app.state.websocket_allowed_origins = (
            configured_runtime_settings.allowed_websocket_origins
        )
        app.state.quiz_preparation_service = quiz_preparation_service
        app.state.solo_service = None
        app.state.solo_grading_task = None
        app.state.reward_service = None
        app.state.pet_service = None
        app.state.reward_worker = None
        try:
            if configured_service is None:
                database = Database.from_environment()
                _require_learning_schema(database)
                app.state.learning_summary_repository = (
                    learning_summary_repository
                    or PostgresLearningSummaryRepository(database.session_factory)
                )
                runtime_entitlement_verifier = premium_entitlement_verifier
                runtime_entitlement_lookup_key = premium_entitlement_lookup_key
                if runtime_entitlement_verifier is None:
                    try:
                        revenuecat_configuration = (
                            RevenueCatServerConfiguration.from_environment()
                        )
                    except RevenueCatConfigurationError:
                        runtime_entitlement_lookup_key = None
                    else:
                        owned_revenuecat_verifier = (
                            RevenueCatEntitlementVerifier(
                                revenuecat_configuration
                            )
                        )
                        runtime_entitlement_verifier = (
                            owned_revenuecat_verifier
                        )
                        runtime_entitlement_lookup_key = (
                            revenuecat_configuration.entitlement_lookup_key
                        )
                app.state.room_service = RoomService(
                    PostgresRoomRepository(database.session_factory),
                    membership_repository=PostgresMembershipRepository(
                        database.session_factory
                    ),
                    premium_entitlement_verifier=(
                        runtime_entitlement_verifier
                    ),
                    premium_entitlement_lookup_key=(
                        runtime_entitlement_lookup_key
                    ),
                )
                app.state.user_repository = (
                    user_repository
                    or PostgresUserRepository(database.session_factory)
                )
                app.state.auth_verifier = (
                    auth_verifier or SupabaseJWKSAuthVerifier.from_environment()
                )
                app.state.session_service = session_service or SessionService(
                    PostgresQuizSessionRepository(database.session_factory)
                )
                app.state.safety_report_service = (
                    safety_report_service
                    or PostgresSafetyReportService(database.session_factory)
                )
                if account_deletion_service is None:
                    deletion_configuration = (
                        AccountDeletionProviderConfiguration.from_environment()
                    )
                    supabase_deletion_provider, revenuecat_deletion_provider = (
                        build_deletion_providers(deletion_configuration)
                    )
                    owned_account_deletion_service = AccountDeletionService(
                        PostgresAccountDeletionRepository(
                            database.session_factory
                        ),
                        supabase_provider=supabase_deletion_provider,
                        revenuecat_provider=revenuecat_deletion_provider,
                        settings=configured_account_deletion_settings,
                    )
                    app.state.account_deletion_service = (
                        owned_account_deletion_service
                    )
                gen = quiz_generator or OpenAiQuizContentGenerator()
                verifier = quiz_verifier or QuizContentVerificationService(
                    solver=OpenAiBlindQuizSolver(),
                    assessor=OpenAiQuizConsistencyAssessor(),
                )
                if app.state.quiz_preparation_service is None:
                    prep_repo = PostgresQuizPreparationRepository(database.session_factory)
                    app.state.quiz_preparation_service = QuizPreparationService(
                        preparation_repository=prep_repo,
                        room_repository=app.state.room_service._repository,
                        generator=gen,
                        verifier=verifier,
                    )
                app.state.reward_service = RewardService(database.session_factory)
                app.state.pet_service = PetService(database.session_factory)
            else:
                app.state.room_service = configured_service
                app.state.learning_summary_repository = learning_summary_repository
                app.state.user_repository = (
                    user_repository or InMemoryUserRepository()
                )
                if auth_verifier is None:
                    raise RuntimeError(
                        "An AuthVerifier is required when injecting test repositories."
                    )
                app.state.auth_verifier = auth_verifier
                app.state.session_service = session_service
                if safety_report_service is not None:
                    app.state.safety_report_service = safety_report_service
                elif isinstance(membership_repository, PostgresMembershipRepository):
                    app.state.safety_report_service = PostgresSafetyReportService(
                        membership_repository.session_factory
                    )
                else:
                    app.state.safety_report_service = InMemorySafetyReportService(
                        room_repository=repository or InMemoryRoomRepository(),
                        membership_repository=(
                            membership_repository or InMemoryMembershipRepository()
                        ),
                        user_repository=app.state.user_repository,
                    )
            configured_session_service = getattr(app.state, "session_service", None)
            if isinstance(configured_session_service, SessionService):
                realtime_publisher = RealtimePublisher(
                    connection_manager,
                    configured_session_service,
                )
                deadline_coordinator = DeadlineCoordinator(
                    configured_session_service,
                    realtime_publisher.publish_transition,
                )
                app.state.realtime_publisher = realtime_publisher
                app.state.deadline_coordinator = deadline_coordinator
                await deadline_coordinator.startup_recovery()
                # Bounded Luna written-answer grading runs outside DB
                # transactions; without a key every attempt degrades to
                # explicit UNAVAILABLE rather than an invented mark.
                owned_grading_coordinator = grading_coordinator
                grading_grader = written_grader or OpenAiWrittenAnswerGrader()
                grading_permits = GradingAdmission()
                if owned_grading_coordinator is None and database is not None:
                    async def _grading_transition(
                        room_id: UUID,
                        previous: QuizSession | None,
                        current: QuizSession,
                    ) -> bool:
                        published = await realtime_publisher.publish_transition(
                            room_id, previous, current
                        )
                        if current.status != QuizSessionStatus.FINISHED:
                            await deadline_coordinator.schedule_session(current.id)
                        return published

                    owned_grading_coordinator = GradingCoordinator(
                        configured_session_service,
                        grading_grader,
                        publish_transition=_grading_transition,
                        grading_permits=grading_permits,
                    )
                if database is not None:
                    if grading_coordinator is not None:
                        # An injected room coordinator must use the exact same
                        # paid-call boundary as the solo worker.
                        grading_grader = grading_coordinator._grader
                        grading_permits = grading_coordinator._grading_permits
                    solo_service_state = SoloService(
                        PostgresSoloRepository(database.session_factory),
                        gen,
                        verifier,
                        grading_grader,
                        grading_permits=grading_permits,
                    )
                    app.state.solo_service = solo_service_state
                    app.state.solo_grading_task = asyncio.create_task(
                        solo_service_state.run_grading_loop(),
                        name="studyroom-solo-grading",
                    )
                    reward_worker_state = RewardWorker(
                        RewardRepository(database.session_factory)
                    )
                    app.state.reward_worker = reward_worker_state
                    reward_worker_state.start()
                app.state.grading_coordinator = owned_grading_coordinator
                grading_task = None
                if owned_grading_coordinator is not None:
                    await owned_grading_coordinator.startup_recovery()
                    grading_task = asyncio.create_task(
                        owned_grading_coordinator.run_loop(),
                        name="studyroom-grading-coordinator",
                    )
                app.state.grading_task = grading_task
                # Preparation claim broadcast + dead-lease recovery. The hook
                # publishes GENERATING immediately after the claim
                # transaction; the periodic task CAS-marks crashed leases
                # FAILED (retryable via a fresh request UUID) and broadcasts.
                # Process-owned, tracked, and shutdown-clean: no DB lock is
                # ever held across provider work.
                prep_service_state = getattr(
                    app.state, "quiz_preparation_service", None
                )
                prep_recovery_task = None
                if isinstance(prep_service_state, QuizPreparationService):
                    async def _broadcast_prep_room(room_id: UUID) -> None:
                        try:
                            await realtime_publisher.send_room_state_to_all(room_id)
                        except Exception:
                            pass

                    async def _broadcast_prep_claim(
                        room_id: UUID, prep: QuizPreparation
                    ) -> None:
                        await _broadcast_prep_room(room_id)

                    prep_service_state.set_claimed_hook(_broadcast_prep_claim)
                    prep_service_state.set_terminal_hook(_broadcast_prep_claim)
                    recovered = await prep_service_state.recover_expired_preparations()
                    for prep in recovered:
                        await _broadcast_prep_room(prep.room_id)

                    async def _prep_recovery_loop() -> None:
                        while True:
                            await asyncio.sleep(30.0)
                            try:
                                expired = await prep_service_state.recover_expired_preparations()
                            except asyncio.CancelledError:
                                break
                            except Exception:
                                continue
                            for prep in expired:
                                await _broadcast_prep_room(prep.room_id)

                    prep_recovery_task = asyncio.create_task(
                        _prep_recovery_loop(),
                        name="studyroom-prep-recovery",
                    )
                app.state.prep_recovery_task = prep_recovery_task
            else:
                app.state.realtime_publisher = None
                app.state.deadline_coordinator = None
                app.state.grading_coordinator = grading_coordinator
                app.state.grading_task = None
                app.state.prep_recovery_task = None
            yield
        finally:
            reward_worker_state = getattr(app.state, "reward_worker", None)
            if isinstance(reward_worker_state, RewardWorker):
                await reward_worker_state.stop()
            solo_service_state = getattr(app.state, "solo_service", None)
            if isinstance(solo_service_state, SoloService):
                await solo_service_state.shutdown()
            solo_task_state = getattr(app.state, "solo_grading_task", None)
            if solo_task_state is not None:
                solo_task_state.cancel()
                await asyncio.gather(solo_task_state, return_exceptions=True)
            prep_service_state = getattr(app.state, "quiz_preparation_service", None)
            if isinstance(prep_service_state, QuizPreparationService):
                await prep_service_state.shutdown()
            prep_recovery_state = getattr(app.state, "prep_recovery_task", None)
            if prep_recovery_state is not None:
                prep_recovery_state.cancel()
                await asyncio.gather(prep_recovery_state, return_exceptions=True)
            grading_coordinator_state = getattr(
                app.state, "grading_coordinator", None
            )
            if isinstance(grading_coordinator_state, GradingCoordinator):
                grading_coordinator_state.stop()
            grading_task_state = getattr(app.state, "grading_task", None)
            if grading_task_state is not None:
                grading_task_state.cancel()
                await asyncio.gather(grading_task_state, return_exceptions=True)
            if isinstance(
                getattr(app.state, "deadline_coordinator", None),
                DeadlineCoordinator,
            ):
                await app.state.deadline_coordinator.shutdown()
            await connection_manager.shutdown()
            if database is not None:
                database.dispose()
            if owned_revenuecat_verifier is not None:
                owned_revenuecat_verifier.close()
            if owned_account_deletion_service is not None:
                owned_account_deletion_service.close()

    app = FastAPI(
        title="MindMesh API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured_runtime_settings.allowed_http_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Accept", "Authorization", "Content-Type"],
    )
    app.include_router(rooms_router)
    app.include_router(profile_router)
    app.include_router(learning_summary_router)
    app.include_router(learning_companions_router)
    app.include_router(solo_router)
    app.include_router(account_deletion_router)
    app.include_router(safety_reports_router)
    app.include_router(quiz_router)
    app.include_router(websocket_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        safe_details = [
            {
                "type": error.get("type", "validation_error"),
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": error.get("msg", "Request validation failed."),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": safe_details,
                }
            },
        )

    @app.exception_handler(RoomNotFoundError)
    async def room_not_found_handler(
        request: Request,
        exc: RoomNotFoundError,
    ) -> JSONResponse:
        return _error_response(
            "room_not_found",
            "Room was not found.",
            404,
        )

    @app.exception_handler(AuthenticationRequiredError)
    async def authentication_required_handler(
        request: Request,
        exc: AuthenticationRequiredError,
    ) -> JSONResponse:
        return _error_response(
            "authentication_required",
            "Authentication is required.",
            401,
        )

    @app.exception_handler(InvalidAuthTokenError)
    async def invalid_auth_token_handler(
        request: Request,
        exc: InvalidAuthTokenError,
    ) -> JSONResponse:
        return _error_response(
            "invalid_auth_token",
            "The authentication token is invalid.",
            401,
        )

    @app.exception_handler(RoomOwnerRequiredError)
    async def room_owner_required_handler(
        request: Request,
        exc: RoomOwnerRequiredError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 403)

    @app.exception_handler(ProRequiredError)
    async def pro_required_handler(
        request: Request,
        exc: ProRequiredError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 403)

    @app.exception_handler(PremiumVerificationUnavailableError)
    async def premium_verification_unavailable_handler(
        request: Request,
        exc: PremiumVerificationUnavailableError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 503)

    @app.exception_handler(RoomOwnerMustCloseError)
    async def room_owner_must_close_handler(
        request: Request,
        exc: RoomOwnerMustCloseError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 409)

    @app.exception_handler(RoomClosedError)
    async def room_closed_handler(
        request: Request,
        exc: RoomClosedError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 409)

    @app.exception_handler(UserProfileRequiredError)
    async def user_profile_required_handler(
        request: Request,
        exc: UserProfileRequiredError,
    ) -> JSONResponse:
        return _error_response(
            "profile_required",
            "Complete your MindMesh profile before using rooms.",
            409,
        )

    @app.exception_handler(AccountDeletedError)
    async def account_deleted_handler(
        request: Request,
        exc: AccountDeletedError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 403)

    @app.exception_handler(AccountSuspendedError)
    async def account_suspended_handler(
        request: Request,
        exc: AccountSuspendedError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 403)

    @app.exception_handler(InvalidDisplayNameError)
    async def invalid_display_name_handler(
        request: Request,
        exc: InvalidDisplayNameError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 422)

    @app.exception_handler(RoomJoinUnavailableError)
    async def room_join_unavailable_handler(
        request: Request,
        exc: RoomJoinUnavailableError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 404)

    @app.exception_handler(RoomJoinRateLimitedError)
    async def room_join_rate_limited_handler(
        request: Request,
        exc: RoomJoinRateLimitedError,
    ) -> JSONResponse:
        return _error_response(
            exc.code,
            exc.message,
            429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    @app.exception_handler(RecentAuthenticationRequiredError)
    async def recent_authentication_required_handler(
        request: Request,
        exc: RecentAuthenticationRequiredError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 401)

    @app.exception_handler(AccountDeletionBlockedActiveQuizError)
    async def account_deletion_blocked_handler(
        request: Request,
        exc: AccountDeletionBlockedActiveQuizError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 409)

    @app.exception_handler(AccountDeletionUnavailableError)
    async def account_deletion_unavailable_handler(
        request: Request,
        exc: AccountDeletionUnavailableError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 503)

    @app.exception_handler(SafetyReportNotAllowedError)
    async def safety_report_not_allowed_handler(
        request: Request,
        exc: SafetyReportNotAllowedError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 403)

    @app.exception_handler(SafetyReportUnavailableError)
    async def safety_report_unavailable_handler(
        request: Request,
        exc: SafetyReportUnavailableError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 503)

    @app.exception_handler(InvalidRoomDataError)
    async def invalid_room_data_handler(
        request: Request,
        exc: InvalidRoomDataError,
    ) -> JSONResponse:
        return _error_response("validation_error", str(exc), 422)

    @app.exception_handler(RoomCreationError)
    async def room_generation_error_handler(
        request: Request,
        exc: RoomCreationError,
    ) -> JSONResponse:
        return _error_response(
            "internal_error",
            "Unable to create room.",
            500,
        )

    @app.exception_handler(RoomMembershipError)
    async def membership_conflict_handler(
        request: Request,
        exc: RoomMembershipError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 409)

    @app.exception_handler(NotRoomMemberError)
    async def not_room_member_handler(
        request: Request,
        exc: NotRoomMemberError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 403)

    @app.exception_handler(QuizSessionError)
    async def quiz_session_error_handler(
        request: Request,
        exc: QuizSessionError,
    ) -> JSONResponse:
        status_code = 403 if isinstance(exc, NotSessionParticipantError) else 409
        return _error_response(exc.code, exc.message, status_code)

    @app.exception_handler(PreparationConflictError)
    async def preparation_conflict_handler(
        request: Request,
        exc: PreparationConflictError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 409)

    @app.exception_handler(PreparationFailedError)
    async def preparation_failed_handler(
        request: Request,
        exc: PreparationFailedError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 502)

    @app.exception_handler(AiGenerationUnavailableError)
    async def ai_generation_unavailable_handler(
        request: Request,
        exc: AiGenerationUnavailableError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, 503)

    return app


app = create_app()
