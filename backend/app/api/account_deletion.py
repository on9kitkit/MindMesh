import asyncio
from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, Request, status

from app.account_deletion.repository import AccountDeletionLocalResult
from app.account_deletion.service import AccountDeletionOperations
from app.api.dependencies import (
    CurrentUser,
    get_current_user_for_account_deletion,
)
from app.domain.errors import (
    AccountDeletedError,
    AccountDeletionUnavailableError,
    RecentAuthenticationRequiredError,
)
from app.realtime.close_codes import FORBIDDEN
from app.realtime.manager import ConnectionManager
from app.realtime.protocol import error_event
from app.realtime.publisher import RealtimePublisher
from app.schemas.account_deletion import (
    AccountDeletionRequest,
    AccountDeletionResponse,
)


router = APIRouter(prefix="/me", tags=["account"])


@router.delete(
    "",
    response_model=AccountDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_account(
    request: Request,
    payload: AccountDeletionRequest,
    current_user: CurrentUser = Depends(get_current_user_for_account_deletion),
) -> AccountDeletionResponse:
    deletion_service = getattr(request.app.state, "account_deletion_service", None)
    if not _supports_account_deletion(deletion_service):
        raise AccountDeletionUnavailableError
    deletion_service = cast(AccountDeletionOperations, deletion_service)
    _require_recent_authentication(request, current_user)

    local_result = await asyncio.to_thread(
        deletion_service.delete_local_account,
        current_user.id,
    )
    if local_result.already_deleted:
        raise AccountDeletedError

    await _terminate_realtime_state(request, local_result)
    await asyncio.to_thread(
        deletion_service.process_user_jobs,
        current_user.id,
    )
    provider_cleanup_pending = await asyncio.to_thread(
        deletion_service.has_pending_jobs,
        current_user.id,
    )
    return AccountDeletionResponse(
        status="account_deleted",
        local_deletion_complete=True,
        provider_cleanup_pending=provider_cleanup_pending,
    )


def _require_recent_authentication(
    request: Request,
    current_user: CurrentUser,
) -> None:
    settings = getattr(request.app.state, "account_deletion_settings", None)
    window_seconds = getattr(settings, "recent_auth_window_seconds", None)
    authenticated_at = current_user.authenticated_at
    if not isinstance(window_seconds, int) or authenticated_at is None:
        raise RecentAuthenticationRequiredError
    now = datetime_now_utc()
    if authenticated_at.tzinfo is None:
        raise RecentAuthenticationRequiredError
    age_seconds = (now - authenticated_at.astimezone(now.tzinfo)).total_seconds()
    if age_seconds < 0 or age_seconds > window_seconds:
        raise RecentAuthenticationRequiredError


async def _terminate_realtime_state(
    request: Request,
    local_result: AccountDeletionLocalResult,
) -> None:
    manager = getattr(request.app.state, "connection_manager", None)
    if isinstance(manager, ConnectionManager):
        await manager.close_user(
            local_result.user_id,
            code=FORBIDDEN,
            reason="account_deleted",
            final_message=error_event(
                "account_deleted",
                AccountDeletedError.message,
            ),
        )

    publisher = getattr(request.app.state, "realtime_publisher", None)
    if not isinstance(publisher, RealtimePublisher):
        return
    for room_id in local_result.closed_room_ids:
        try:
            await publisher.publish_room_closed(room_id)
        except Exception:
            pass
    for room_id in local_result.left_room_ids:
        try:
            await publisher.send_room_state_to_all(room_id)
        except Exception:
            pass


def datetime_now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _supports_account_deletion(value: object) -> bool:
    return all(
        callable(getattr(value, name, None))
        for name in (
            "delete_local_account",
            "process_user_jobs",
            "has_pending_jobs",
        )
    )
