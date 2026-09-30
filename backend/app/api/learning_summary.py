"""Authenticated viewer-only learning-summary API."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies import CurrentUser, get_current_user
from app.repositories.learning_summary import LearningSummaryRepository
from app.schemas.learning_summary import LearningSummaryResponse

router = APIRouter(tags=["learning"])


def get_learning_summary_repository(request: Request) -> LearningSummaryRepository:
    repository = getattr(request.app.state, "learning_summary_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learning summary is unavailable.",
        )
    return repository


@router.get(
    "/me/learning-summary",
    response_model=LearningSummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_learning_summary(
    request: Request,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    repository: LearningSummaryRepository = Depends(
        get_learning_summary_repository
    ),
) -> LearningSummaryResponse:
    response.headers["Cache-Control"] = "no-store"
    if request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Learning summary does not accept query parameters.",
        )
    result = repository.get_learning_summary(current_user.id)
    return LearningSummaryResponse.from_result(result)
