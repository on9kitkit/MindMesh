from typing import cast

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import CurrentUser, get_current_user
from app.domain.errors import SafetyReportUnavailableError
from app.schemas.safety_reports import (
    SafetyReportCreateRequest,
    SafetyReportResponse,
)
from app.services.safety_reports import SafetyReportOperations


router = APIRouter(prefix="/safety-reports", tags=["safety"])


def get_safety_report_service(request: Request) -> SafetyReportOperations:
    service = getattr(request.app.state, "safety_report_service", None)
    if not callable(getattr(service, "submit_report", None)):
        raise SafetyReportUnavailableError
    return cast(SafetyReportOperations, service)


@router.post(
    "",
    response_model=SafetyReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_safety_report(
    payload: SafetyReportCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: SafetyReportOperations = Depends(get_safety_report_service),
) -> SafetyReportResponse:
    return service.submit_report(
        reporter_id=current_user.id,
        payload=payload,
    )
