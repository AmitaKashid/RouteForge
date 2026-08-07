"""FastAPI route handler for GET /v1/usage operational metrics endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field

from routeforge.contracts import TeamId
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.gateway.schemas.base import GatewayBaseModel
from routeforge.storage.database import DatabaseManager
from routeforge.storage.records import get_monthly_usage_summary

router = APIRouter(prefix="/v1", tags=["Usage"])


class UsageSummaryResponse(GatewayBaseModel):
    """Monthly usage summary response schema for an authenticated team."""

    request_count: int = Field(description="Total inference requests in current calendar month.")
    successful_request_count: int = Field(description="Successful requests (status SUCCEEDED).")
    no_eligible_count: int = Field(description="Requests rejected due to no eligible model.")
    provider_error_count: int = Field(description="Requests failed due to provider error.")
    budget_rejected_count: int = Field(description="Requests rejected due to budget limit.")
    total_input_tokens: int = Field(description="Total input tokens consumed.")
    total_output_tokens: int = Field(description="Total output tokens consumed.")
    total_tokens: int = Field(description="Total tokens consumed.")


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_team_usage(
    request: Request,
    team_id: Annotated[TeamId, Depends(get_authenticated_team_id)],
) -> UsageSummaryResponse:
    """Retrieve current UTC calendar-month operational usage metrics for authenticated team."""
    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    own_manager = False
    if db_manager is None:
        db_manager = DatabaseManager()
        own_manager = True

    try:
        async with db_manager.session_factory() as session:
            summary = await get_monthly_usage_summary(session, str(team_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage backend unavailable: {exc}",
        ) from exc
    finally:
        if own_manager and db_manager is not None:
            await db_manager.aclose()

    return UsageSummaryResponse(**summary)
