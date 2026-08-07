"""Quality verification summary endpoint for authenticated teams."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import func, select

from routeforge.contracts import TeamId
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.gateway.schemas.base import GatewayBaseModel
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import InferenceRecordModel, QualityVerificationRecord

router = APIRouter(prefix="/v1/quality-summary", tags=["Quality Verification"])


class QualitySummaryResponse(GatewayBaseModel):
    """UTC calendar-month quality verification statistics response."""

    team_id: str = Field(description="Authenticated team ID.")
    period_start: str = Field(description="Period start timestamp (ISO UTC).")
    period_end: str = Field(description="Period end timestamp (ISO UTC).")
    eligible_successful_requests: int = Field(
        description="Total eligible successful inference requests in period."
    )
    sampled_requests: int = Field(description="Total requests sampled for verification.")
    completed_verifications: int = Field(
        description="Total verifications completed with status SUCCEEDED."
    )
    passed_verifications: int = Field(description="Total verifications where passed is true.")
    failed_quality_checks: int = Field(
        description="Total verifications completed with passed is false."
    )
    worker_failures: int = Field(description="Total verifications with status FAILED.")
    skipped_verifications: int = Field(description="Total verifications with status SKIPPED.")
    sampling_rate_observed: float = Field(
        description="Ratio of sampled requests to eligible successful requests."
    )
    mean_verification_score: Decimal | None = Field(
        default=None, description="Average verification agreement score in period."
    )
    verification_pass_rate: float | None = Field(
        default=None, description="Ratio of passed verifications to completed verifications."
    )
    total_reference_input_tokens: int = Field(
        description="Total input tokens consumed by reference model executions."
    )
    total_reference_output_tokens: int = Field(
        description="Total output tokens produced by reference model executions."
    )
    total_verification_cost_usd: Decimal = Field(
        description="Total control-plane reference verification cost in USD."
    )
    currency: str = Field(default="USD", description="Currency unit.")


@router.get("", response_model=QualitySummaryResponse)
async def get_quality_summary(
    request: Request,
    team_id: Annotated[TeamId, Depends(get_authenticated_team_id)],
) -> QualitySummaryResponse:
    """Retrieve current UTC calendar-month quality verification metrics for authenticated team."""
    now = datetime.now(UTC)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_end = now

    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    if db_manager is None:
        db_manager = DatabaseManager()

    async with db_manager.session_factory() as session:
        # Eligible successful requests count
        elig_stmt = (
            select(func.count())
            .select_from(InferenceRecordModel)
            .where(
                InferenceRecordModel.team_id == str(team_id),
                InferenceRecordModel.status == "SUCCEEDED",
                InferenceRecordModel.created_at >= period_start,
            )
        )
        elig_res = await session.execute(elig_stmt)
        eligible_requests = elig_res.scalar() or 0

        # Quality verifications in period
        qv_stmt = select(QualityVerificationRecord).where(
            QualityVerificationRecord.team_id == str(team_id),
            QualityVerificationRecord.queued_at >= period_start,
        )
        qv_res = await session.execute(qv_stmt)
        qv_records = list(qv_res.scalars().all())

    sampled_requests = len(qv_records)
    completed_verifications = sum(1 for r in qv_records if r.status == "SUCCEEDED")
    passed_verifications = sum(
        1 for r in qv_records if r.status == "SUCCEEDED" and r.passed is True
    )
    failed_quality_checks = sum(
        1 for r in qv_records if r.status == "SUCCEEDED" and r.passed is False
    )
    worker_failures = sum(1 for r in qv_records if r.status == "FAILED")
    skipped_verifications = sum(1 for r in qv_records if r.status == "SKIPPED")

    sampling_rate_observed = (
        float(sampled_requests) / float(eligible_requests) if eligible_requests > 0 else 0.0
    )

    scores = [r.score for r in qv_records if r.status == "SUCCEEDED" and r.score is not None]
    mean_score = (
        (sum(scores, Decimal("0")) / Decimal(len(scores))).quantize(Decimal("0.00001"))
        if scores
        else None
    )

    pass_rate = (
        float(passed_verifications) / float(completed_verifications)
        if completed_verifications > 0
        else None
    )

    tot_ref_in = sum(r.reference_input_tokens or 0 for r in qv_records)
    tot_ref_out = sum(r.reference_output_tokens or 0 for r in qv_records)
    tot_ref_cost = sum(
        (r.reference_cost_usd for r in qv_records if r.reference_cost_usd is not None),
        Decimal("0.00000000"),
    )

    return QualitySummaryResponse(
        team_id=str(team_id),
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        eligible_successful_requests=eligible_requests,
        sampled_requests=sampled_requests,
        completed_verifications=completed_verifications,
        passed_verifications=passed_verifications,
        failed_quality_checks=failed_quality_checks,
        worker_failures=worker_failures,
        skipped_verifications=skipped_verifications,
        sampling_rate_observed=sampling_rate_observed,
        mean_verification_score=mean_score,
        verification_pass_rate=pass_rate,
        total_reference_input_tokens=tot_ref_in,
        total_reference_output_tokens=tot_ref_out,
        total_verification_cost_usd=tot_ref_cost,
        currency="USD",
    )
