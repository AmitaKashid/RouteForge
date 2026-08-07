"""FastAPI route handler for GET /v1/costs budget & accounted cost endpoint."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field

from routeforge.contracts import TeamId
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.gateway.schemas.base import GatewayBaseModel
from routeforge.storage.database import DatabaseManager
from routeforge.storage.records import get_monthly_cost_summary

router = APIRouter(prefix="/v1", tags=["Costs"])


class CostSummaryResponse(GatewayBaseModel):
    """Monthly cost and budget utilization summary response schema for an authenticated team."""

    monthly_budget_usd: Decimal = Field(description="Configured monthly budget cap in USD.")
    accounted_cost_usd: Decimal = Field(description="Total accounted actual cost in USD.")
    reserved_cost_usd: Decimal = Field(description="Currently active reserved cost in USD.")
    committed_cost_usd: Decimal = Field(description="Committed cost (accounted + reserved) in USD.")
    remaining_available_budget_usd: Decimal = Field(
        description="Remaining available budget in USD (clamped to 0)."
    )
    overrun_cost_usd: Decimal = Field(description="Recorded cost overrun in USD if any.")
    budget_utilization_percentage: float = Field(
        description="Budget utilization percentage (0.0 - 100.0+)."
    )
    currency: str = Field(default="USD", description="Billing currency.")
    period_start: str = Field(description="Current calendar month start timestamp in ISO UTC.")
    period_end: str = Field(description="Current calendar month end timestamp in ISO UTC.")


@router.get("/costs", response_model=CostSummaryResponse)
async def get_team_costs(
    request: Request,
    team_id: Annotated[TeamId, Depends(get_authenticated_team_id)],
) -> CostSummaryResponse:
    """Retrieve current UTC calendar-month cost and budget information for authenticated team."""
    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    own_manager = False
    if db_manager is None:
        db_manager = DatabaseManager()
        own_manager = True

    try:
        async with db_manager.session_factory() as session:
            summary = await get_monthly_cost_summary(session, str(team_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage backend unavailable: {exc}",
        ) from exc
    finally:
        if own_manager and db_manager is not None:
            await db_manager.aclose()

    return CostSummaryResponse(**summary)
