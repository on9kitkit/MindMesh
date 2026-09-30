"""Authenticated room WebSocket transport over the authoritative session service."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import AuthenticatedIdentity
from app.domain.errors import (
    AccountDeletedError,
    AccountSuspendedError,
    AiGenerationUnavailableError,
    AuthenticationRequiredError,
    InvalidAuthTokenError,
    NotRoomMemberError,
    PreparationConflictError,
    PreparationFailedError,
    QuizSessionError,
    RoomApplicationError,
    RoomClosedError,
    RoomNotFoundError,
    RoomOwnerRequiredError,
    UserProfileRequiredError,
)
from app.realtime.close_codes import (
    AUTHENTICATION_FAILURE,
    BAD_PROTOCOL,
    CONNECTION_CONFLICT,
    FORBIDDEN,
    NOT_FOUND,
    UNEXPECTED_SERVER_ERROR,
)
from app.realtime.controls import (
    CommandRateLimiter,
    RoomRetryLimiter,
    origin_is_allowed,
)
from app.realtime.deadlines import DeadlineCoordinator
from app.realtime.manager import (
    ConnectionLimitReachedError,
    ConnectionManager,
    ManagedConnection,
)
from app.realtime.protocol import (
    AuthenticateCommand,
    ClientCommand,
    MAX_MESSAGE_BYTES,
    ProtocolError,
    RequestStateCommand,
    SetReadyCommand,
    StartSessionCommand,
    SubmitAnswerCommand,
    error_event,
    parse_client_command,
)
from app.realtime.protocol_v2 import (
    AuthenticateCommandV2,
    ClientCommandV2,
    PrepareQuizCommandV2,
    ProtocolV2Error,
    RequestStateCommandV2,
    RetryGradingCommandV2,
    SetReadyCommandV2,
    StartSessionCommandV2,
    SubmitAnswerCommandV2,
    error_event_v2,
    parse_client_command_v2,
)
from app.realtime.publisher import RealtimePublisher
from app.services.rooms import RoomService
from app.services.sessions import SessionService

AUTHENTICATION_TIMEOUT_SECONDS = 5.0
COMMAND_RATE_LIMIT = 20
# RETRY_GRADING is host-only and bounded process-wide per (room, host):
# at most two explicit retries per 30 seconds even across reconnects or
# extra sockets. Concurrent commands additionally coalesce through durable
# row status and grading leases. Process-local, not DB-durable.
RETRY_GRADING_RATE_LIMIT = 2
RETRY_GRADING_RATE_WINDOW_SECONDS = 30.0
_retry_grading_limiter = RoomRetryLimiter(
    limit=RETRY_GRADING_RATE_LIMIT,
    window_seconds=RETRY_GRADING_RATE_WINDOW_SECONDS,
)


def _peek_protocol_version(message: str | bytes) -> int | None:
    """Read the framing version without enforcing either wire contract."""
    try:
        raw = json.loads(message if isinstance(message, str) else message.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("protocol_version")
    return version if type(version) is int else None

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/rooms/{room_id}")
async def room_websocket(websocket: WebSocket, room_id: UUID) -> None:
    """Serve one authenticated room connection until it disconnects."""

    allowed_origins = getattr(
        websocket.app.state,
        "websocket_allowed_origins",
        (),
    )
    if not origin_is_allowed(websocket.headers.get("origin"), allowed_origins):
        await _close_safely(websocket, FORBIDDEN, "origin not allowed")
        return

    await websocket.accept()
    manager = getattr(websocket.app.state, "connection_manager", None)
    publisher = getattr(websocket.app.state, "realtime_publisher", None)
    coordinator = getattr(websocket.app.state, "deadline_coordinator", None)
    session_service = getattr(websocket.app.state, "session_service", None)
    if not isinstance(manager, ConnectionManager):
        await _send_error_direct(websocket, "internal_error")
        await _close_safely(
            websocket,
            UNEXPECTED_SERVER_ERROR,
            "realtime service unavailable",
        )
        return

    try:
        first_message = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=AUTHENTICATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        await _send_error_direct(websocket, "authentication_required")
        await _close_safely(
            websocket,
            AUTHENTICATION_FAILURE,
            "authentication required",
        )
        return
    except (WebSocketDisconnect, RuntimeError):
        return

    try:
        first_version = _peek_protocol_version(first_message)
        first_command: AuthenticateCommand | AuthenticateCommandV2
        connection_version = 1
        if first_version == 2:
            try:
                parsed_v2 = parse_client_command_v2(first_message)
            except Exception:
                await _send_error_direct_v2(websocket, "protocol_error")
                await _close_safely(websocket, BAD_PROTOCOL, "invalid authentication message")
                return
            if not isinstance(parsed_v2, AuthenticateCommandV2):
                await _send_error_direct_v2(websocket, "authentication_required")
                await _close_safely(
                    websocket,
                    AUTHENTICATION_FAILURE,
                    "authentication required",
                )
                return
            first_command = parsed_v2
            connection_version = 2
        else:
            try:
                first_command_v1 = parse_client_command(first_message)
            except ProtocolError as error:
                await _send_error_direct(websocket, error.code)
                await _close_safely(websocket, BAD_PROTOCOL, "invalid authentication message")
                return
            if not isinstance(first_command_v1, AuthenticateCommand):
                await _send_error_direct(websocket, "authentication_required")
                await _close_safely(
                    websocket,
                    AUTHENTICATION_FAILURE,
                    "authentication required",
                )
                return
            first_command = first_command_v1
    except (WebSocketDisconnect, RuntimeError):
        return

    try:
        identity = await _authenticate_connection(
            websocket,
            room_id,
            first_command,
        )
    except RoomApplicationError as error:
        code, close_code = _connection_error(error)
        if connection_version == 2:
            await _send_error_direct_v2(websocket, code)
        else:
            await _send_error_direct(websocket, code)
        await _close_safely(websocket, close_code, code)
        return
    except Exception:
        if connection_version == 2:
            await _send_error_direct_v2(websocket, "internal_error")
        else:
            await _send_error_direct(websocket, "internal_error")
        await _close_safely(
            websocket,
            UNEXPECTED_SERVER_ERROR,
            "authentication service failure",
        )
        return

    if not isinstance(publisher, RealtimePublisher) or not isinstance(
        coordinator,
        DeadlineCoordinator,
    ) or not isinstance(session_service, SessionService):
        if connection_version == 2:
            await _send_error_direct_v2(websocket, "internal_error")
        else:
            await _send_error_direct(websocket, "internal_error")
        await _close_safely(
            websocket,
            UNEXPECTED_SERVER_ERROR,
            "realtime service unavailable",
        )
        return

    already_online = await manager.user_is_online(room_id, identity.user_id)
    try:
        connection = await manager.register(
            room_id, identity.user_id, websocket, protocol_version=connection_version
        )
    except ConnectionLimitReachedError:
        if connection_version == 2:
            await _send_error_direct_v2(websocket, "connection_limit_reached")
        else:
            await _send_error_direct(websocket, "connection_limit_reached")
        await _close_safely(
            websocket,
            CONNECTION_CONFLICT,
            "connection limit reached",
        )
        return

    try:
        await _require_current_membership(websocket, room_id, identity.user_id)
    except RoomApplicationError as error:
        code, close_code = _connection_error(error)
        await _send_connection_error(manager, connection, code)
        await manager.close_connection(
            connection.connection_id,
            code=close_code,
            reason=code,
        )
        return

    expiry_task: asyncio.Task[None] | None = None
    try:
        reconciled = await asyncio.to_thread(
            session_service.reconcile_session,
            room_id=room_id,
        )
        await publisher.send_connected(connection.connection_id)
        await publisher.send_snapshot(
            connection.connection_id,
            room_id,
            identity.user_id,
        )
        if not already_online:
            await publisher.send_room_state_to_all(room_id)
        if reconciled is not None and reconciled.status.value != "FINISHED":
            await coordinator.schedule_session(reconciled.id)
        if identity.expires_at is not None:
            expiry_task = asyncio.create_task(
                _close_at_expiry(
                    manager,
                    publisher,
                    connection,
                    identity,
                ),
                name=f"studyroom-auth-expiry-{connection.connection_id}",
            )
        await _command_loop(
            websocket,
            connection,
            manager,
            publisher,
            coordinator,
            session_service,
        )
    except WebSocketDisconnect:
        return
    except Exception:
        if connection_version == 2:
            await manager.send_to_connection(
                connection.connection_id,
                error_event_v2("internal_error", "The realtime request failed."),
            )
        else:
            await manager.send_to_connection(
                connection.connection_id,
                error_event("internal_error", "The realtime request failed."),
            )
        await manager.close_connection(
            connection.connection_id,
            code=UNEXPECTED_SERVER_ERROR,
            reason="realtime request failure",
        )
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
            await asyncio.gather(expiry_task, return_exceptions=True)
        removed, became_offline = await manager.unregister_with_presence(
            connection.connection_id
        )
        if removed is not None and became_offline:
            try:
                await publisher.send_room_state_to_all(room_id)
            except Exception:
                pass


async def _send_connection_error(
    manager: ConnectionManager,
    connection: ManagedConnection,
    code: str,
) -> None:
    """Send a version-matched ERROR event on one connection."""
    message_text = _protocol_error_message(code)
    if connection.protocol_version == 2:
        await manager.send_to_connection(
            connection.connection_id, error_event_v2(code, message_text)
        )
    else:
        await manager.send_to_connection(
            connection.connection_id, error_event(code, message_text)
        )


async def _command_loop(
    websocket: WebSocket,
    connection: ManagedConnection,
    manager: ConnectionManager,
    publisher: RealtimePublisher,
    coordinator: DeadlineCoordinator,
    session_service: SessionService,
) -> None:
    limiter = CommandRateLimiter(limit=COMMAND_RATE_LIMIT)
    is_v2 = connection.protocol_version == 2
    while True:
        message = await websocket.receive_text()
        if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
            await _send_connection_error(
                manager, connection, "protocol_error"
            )
            await manager.close_connection(
                connection.connection_id,
                code=BAD_PROTOCOL,
                reason="message too large",
            )
            return
        if not limiter.allow():
            await _send_connection_error(manager, connection, "rate_limited")
            continue
        if _peek_protocol_version(message) != connection.protocol_version:
            # Strict wire separation: a v1 socket never accepts v2 frames
            # and vice versa. No silent cross-version handling.
            await _send_connection_error(manager, connection, "protocol_error")
            continue
        try:
            if is_v2:
                command: ClientCommand | ClientCommandV2 = parse_client_command_v2(
                    message
                )
            else:
                command = parse_client_command(message)
        except (ProtocolError, ProtocolV2Error) as error:
            # Frozen public v2 codes are `protocol_error` (plus true
            # `unsupported_protocol_version`); internal parser detail
            # categories never reach the wire.
            public_code = error.code
            if is_v2 and public_code not in (
                "protocol_error",
                "unsupported_protocol_version",
            ):
                public_code = "protocol_error"
            await manager.send_to_connection(
                connection.connection_id,
                error_event(error.code, _protocol_error_message(error.code))
                if not is_v2
                else error_event_v2(public_code, _protocol_error_message(public_code)),
            )
            continue
        except Exception:
            await _send_connection_error(manager, connection, "protocol_error")
            continue
        if isinstance(command, (AuthenticateCommand, AuthenticateCommandV2)):
            await _send_connection_error(manager, connection, "protocol_error")
            continue
        if isinstance(command, RetryGradingCommandV2) and not _retry_grading_limiter.allow(
            connection.room_id, connection.user_id
        ):
            await _send_connection_error(manager, connection, "rate_limited")
            continue
        try:
            if not isinstance(command, (RequestStateCommand, RequestStateCommandV2)):
                await _require_active_profile(websocket, connection.user_id)
            await _handle_command(
                command,
                connection,
                manager,
                publisher,
                coordinator,
                session_service,
                websocket,
            )
        except (
            AccountDeletedError,
            AccountSuspendedError,
            UserProfileRequiredError,
        ) as error:
            code, _ = _connection_error(error)
            await manager.send_to_connection(
                connection.connection_id,
                error_event(code, _error_message(error))
                if not is_v2
                else error_event_v2(code, _error_message(error)),
            )
            await manager.close_connection(
                connection.connection_id,
                code=(
                    FORBIDDEN
                    if not isinstance(error, UserProfileRequiredError)
                    else NOT_FOUND
                ),
                reason=code,
            )
            return
        except RoomApplicationError as error:
            code, _ = _connection_error(error)
            await manager.send_to_connection(
                connection.connection_id,
                error_event(code, _error_message(error))
                if not is_v2
                else error_event_v2(code, _error_message(error)),
            )
        except Exception:
            await manager.send_to_connection(
                connection.connection_id,
                error_event("internal_error", "The realtime request failed.")
                if not is_v2
                else error_event_v2("internal_error", "The realtime request failed."),
            )


async def _handle_command(
    command: ClientCommand | ClientCommandV2,
    connection: ManagedConnection,
    manager: ConnectionManager,
    publisher: RealtimePublisher,
    coordinator: DeadlineCoordinator,
    session_service: SessionService,
    websocket: WebSocket,
) -> None:
    room_id = connection.room_id
    user_id = connection.user_id
    if isinstance(command, (SetReadyCommand, SetReadyCommandV2)):
        await asyncio.to_thread(
            session_service.set_ready,
            room_id,
            user_id,
            command.payload.ready,
        )
        await publisher.send_room_state_to_all(room_id)
        return
    if isinstance(command, (StartSessionCommand, StartSessionCommandV2)):
        previous = await asyncio.to_thread(
            session_service.get_active_session,
            room_id,
        )
        started = await asyncio.to_thread(
            session_service.start_session,
            room_id,
            user_id,
        )
        await publisher.publish_transition(room_id, previous, started)
        await coordinator.schedule_session(started.id)
        return
    if isinstance(command, PrepareQuizCommandV2):
        prep_service = getattr(websocket.app.state, "quiz_preparation_service", None)
        if prep_service is None:
            raise AiGenerationUnavailableError
        # Bounded generation runs here; the command loop resumes after the
        # durable preparation reaches READY/FAILED. Same-request retries
        # return the current durable state without a second provider call.
        try:
            await prep_service.prepare_quiz(
                room_id=room_id,
                request_id=command.payload.request_id,
                user_id=user_id,
                wait_for_completion=False,
            )
        except (AiGenerationUnavailableError, PreparationFailedError):
            # Terminal CAS outcome (notably the raising unavailable path):
            # broadcast the durable room state so peers stop displaying a
            # stale GENERATING phase, then let the requester receive the
            # version-matched safe error. The snapshot re-reads durable
            # truth, so a lost CAS cannot publish a false terminal state.
            await publisher.send_room_state_to_all(room_id)
            raise
        await publisher.send_snapshot(connection.connection_id, room_id, user_id)
        await publisher.send_room_state_to_all(room_id)
        return
    if isinstance(command, RetryGradingCommandV2):
        # Host-only; service enforces ownership and GRADING state.
        # Concurrent commands coalesce through row status and leases.
        previous = await asyncio.to_thread(
            session_service.get_active_session,
            room_id,
        )
        await asyncio.to_thread(
            session_service.retry_grading_for_room,
            room_id,
            user_id,
        )
        await _schedule_grading(websocket)
        current = await asyncio.to_thread(
            session_service.get_active_session,
            room_id,
        )
        if (
            current is not None
            and previous is not None
            and current.id == previous.id
            and current.state_version != previous.state_version
        ):
            # Publish to every participant's socket (viewer-specific
            # snapshots), not only the host that sent the command.
            await publisher.publish_transition(room_id, previous, current)
        else:
            await publisher.send_snapshot(connection.connection_id, room_id, user_id)
        return
    if isinstance(command, SubmitAnswerCommand):
        acknowledgement = await asyncio.to_thread(
            session_service.submit_answer,
            room_id,
            user_id,
            command.payload.session_question_id,
            command.payload.selected_option_id,
        )
        await publisher.send_answer_acknowledgement(
            connection.connection_id,
            room_id,
            user_id,
            acknowledgement,
        )
        return
    if isinstance(command, SubmitAnswerCommandV2):
        # Discriminated v2 input: choice carries only option_id, typed
        # numerical/written answers carry only bounded nonblank text.
        if command.payload.type == "choice":
            selected_option_id = command.payload.option_id
            answer_text = None
        else:
            selected_option_id = None
            answer_text = command.payload.text
        acknowledgement = await asyncio.to_thread(
            session_service.submit_answer,
            room_id,
            user_id,
            command.payload.session_question_id,
            selected_option_id,
            answer_text,
        )
        await publisher.send_answer_acknowledgement(
            connection.connection_id,
            room_id,
            user_id,
            acknowledgement,
        )
        if acknowledgement.grading_status == "PENDING":
            # Advisory wakeup only; durable PENDING rows drive recovery.
            await _schedule_grading(websocket)
        return
    if isinstance(command, (RequestStateCommand, RequestStateCommandV2)):
        previous = await asyncio.to_thread(
            session_service.get_active_session,
            room_id,
        )
        reconciled = await asyncio.to_thread(
            session_service.reconcile_session,
            room_id=room_id,
        )
        if (
            reconciled is not None
            and previous is not None
            and reconciled.state_version != previous.state_version
        ):
            published = await publisher.publish_transition(
                room_id,
                previous,
                reconciled,
            )
            if not published:
                await publisher.send_snapshot(
                    connection.connection_id,
                    room_id,
                    user_id,
                )
        else:
            await publisher.send_snapshot(
                connection.connection_id,
                room_id,
                user_id,
            )
        if reconciled is not None and reconciled.status.value != "FINISHED":
            await coordinator.schedule_session(reconciled.id)
        return
    raise RuntimeError("unhandled realtime command")


async def _authenticate_connection(
    websocket: WebSocket,
    room_id: UUID,
    command: AuthenticateCommand | AuthenticateCommandV2,
) -> AuthenticatedIdentity:
    verifier = websocket.app.state.auth_verifier
    user_repository = websocket.app.state.user_repository
    identity = await asyncio.to_thread(
        verifier.verify,
        command.payload.access_token,
    )
    profile = await asyncio.to_thread(
        user_repository.get_by_id,
        identity.user_id,
    )
    if profile is None:
        raise UserProfileRequiredError
    if profile.is_deleted:
        raise AccountDeletedError
    if profile.is_suspended:
        raise AccountSuspendedError
    await _require_current_membership(websocket, room_id, identity.user_id)
    return identity


async def _require_active_profile(websocket: WebSocket, user_id: UUID) -> None:
    profile = await asyncio.to_thread(
        websocket.app.state.user_repository.get_by_id,
        user_id,
    )
    if profile is None:
        raise UserProfileRequiredError
    if profile.is_deleted:
        raise AccountDeletedError
    if profile.is_suspended:
        raise AccountSuspendedError


async def _require_current_membership(
    websocket: WebSocket,
    room_id: UUID,
    user_id: UUID,
) -> None:
    room_service = websocket.app.state.room_service
    if not isinstance(room_service, RoomService):
        raise RuntimeError("invalid room service")
    await asyncio.to_thread(
        room_service.require_active_room_member,
        room_id=room_id,
        user_id=user_id,
    )


async def _close_at_expiry(
    manager: ConnectionManager,
    publisher: RealtimePublisher,
    connection: ManagedConnection,
    identity: AuthenticatedIdentity,
) -> None:
    if identity.expires_at is None:
        return
    try:
        delay = max(
            0.0,
            (identity.expires_at - datetime_now_utc()).total_seconds(),
        )
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    closed = await manager.close_connection(
        connection.connection_id,
        code=AUTHENTICATION_FAILURE,
        reason="authentication expired",
    )
    if closed and not await manager.user_is_online(
        connection.room_id,
        connection.user_id,
    ):
        try:
            await publisher.send_room_state_to_all(connection.room_id)
        except Exception:
            pass


def datetime_now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _schedule_grading(websocket: WebSocket) -> None:
    """Advisory wakeup for the process-local grading coordinator, if any."""
    coordinator = getattr(websocket.app.state, "grading_coordinator", None)
    schedule = getattr(coordinator, "schedule_grading", None)
    if schedule is None:
        return
    try:
        await schedule()
    except Exception:
        return


async def _send_error_direct(websocket: WebSocket, code: str) -> None:
    try:
        await websocket.send_text(error_event(code, _protocol_error_message(code)))
    except Exception:
        return


async def _send_error_direct_v2(websocket: WebSocket, code: str) -> None:
    try:
        await websocket.send_text(error_event_v2(code, _protocol_error_message(code)))
    except Exception:
        return


async def _close_safely(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        return


def _connection_error(error: RoomApplicationError) -> tuple[str, int]:
    if isinstance(error, (AuthenticationRequiredError, InvalidAuthTokenError)):
        return _error_code(error), AUTHENTICATION_FAILURE
    if isinstance(error, UserProfileRequiredError):
        return "profile_required", NOT_FOUND
    if isinstance(error, AccountDeletedError):
        return error.code, FORBIDDEN
    if isinstance(error, AccountSuspendedError):
        return error.code, FORBIDDEN
    if isinstance(error, RoomNotFoundError):
        return "room_not_found", NOT_FOUND
    if isinstance(error, RoomClosedError):
        return "room_closed", NOT_FOUND
    if isinstance(error, (NotRoomMemberError, RoomOwnerRequiredError)):
        return _error_code(error), FORBIDDEN
    return _error_code(error), 0


def _error_code(error: RoomApplicationError) -> str:
    if isinstance(error, AuthenticationRequiredError):
        return "authentication_required"
    if isinstance(error, InvalidAuthTokenError):
        return "invalid_auth_token"
    if isinstance(error, NotRoomMemberError):
        return "not_room_member"
    if isinstance(error, RoomOwnerRequiredError):
        return "room_owner_required"
    if isinstance(error, QuizSessionError):
        return error.code
    return getattr(error, "code", "internal_error")


def _error_message(error: RoomApplicationError) -> str:
    if isinstance(error, AuthenticationRequiredError):
        return "Authentication is required."
    if isinstance(error, InvalidAuthTokenError):
        return "The authentication token is invalid."
    if isinstance(error, UserProfileRequiredError):
        return "Complete your MindMesh profile before using rooms."
    if isinstance(error, AccountDeletedError):
        return error.message
    if isinstance(error, AccountSuspendedError):
        return error.message
    if isinstance(error, RoomNotFoundError):
        return "Room was not found."
    if isinstance(error, NotRoomMemberError):
        return NotRoomMemberError.message
    if isinstance(error, RoomOwnerRequiredError):
        return RoomOwnerRequiredError.message
    if isinstance(error, QuizSessionError):
        return error.message
    return getattr(error, "message", "The realtime request failed.")


def _protocol_error_message(code: str) -> str:
    messages = {
        "authentication_required": "Authentication is required.",
        "invalid_auth_token": "The authentication token is invalid.",
        "unsupported_protocol_version": "The protocol version is unsupported.",
        "protocol_error": "The command is invalid.",
        "rate_limited": "Too many commands; try again shortly.",
        "profile_required": "Complete your MindMesh profile before using rooms.",
        "account_deleted": "This MindMesh account has been deleted.",
        "account_suspended": "Your MindMesh account is currently unavailable.",
        "room_not_found": "Room was not found.",
        "room_closed": "This room is closed.",
        "room_left": "You left this room.",
        "not_room_member": "You are not an active member of this room.",
        "room_owner_required": "Only the room host can perform this action.",
        "connection_limit_reached": "The connection limit has been reached.",
        "preparation_conflict": "Another quiz preparation is already in progress for this room.",
        "quiz_not_ready": "Quiz content is still preparing or generation failed.",
        "preparation_failed": "Failed to generate quiz content.",
        "ai_generation_unavailable": "AI quiz generation is currently unavailable.",
        "internal_error": "The realtime request failed.",
    }
    return messages.get(code, "The realtime request failed.")
