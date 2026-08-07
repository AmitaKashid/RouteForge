"""Routing decision retrieval endpoint for authenticated teams."""

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from sqlalchemy import select

from routeforge.contracts import TeamId
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.gateway.schemas.base import GatewayBaseModel
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import QualityVerificationRecord
from routeforge.storage.records import get_inference_record_by_request_id

router = APIRouter(prefix="/v1/routing-decisions", tags=["Routing Decisions"])


class VerificationSummaryResponse(GatewayBaseModel):
    """Quality verification summary audit details."""

    verification_id: str = Field(description="Unique verification record ID.")
    status: str = Field(
        description="Verification status (QUEUED, RUNNING, SUCCEEDED, FAILED, SKIPPED)."
    )
    strategy: str = Field(description="Comparison strategy name.")
    selected_model_id: str = Field(description="Selected backend model ID.")
    reference_model_id: str = Field(description="Reference backend model ID.")
    score: Decimal | None = Field(default=None, description="Agreement score between 0 and 1.")
    passed: bool | None = Field(
        default=None, description="Whether score met minimum score threshold."
    )
    verification_cost_usd: Decimal | None = Field(
        default=None, description="Reference verification execution cost in USD."
    )
    queued_at: str = Field(description="Queue timestamp in ISO UTC format.")
    started_at: str | None = Field(
        default=None, description="Worker start timestamp in ISO UTC format."
    )
    completed_at: str | None = Field(
        default=None, description="Worker completion timestamp in ISO UTC format."
    )
    failure_code: str | None = Field(default=None, description="Machine-readable failure code.")


class RoutingDecisionRecordResponse(GatewayBaseModel):
    """Auditable routing decision record response payload."""

    request_id: str = Field(description="Unique request correlation ID.")
    team_id: str = Field(description="Authenticated team ID.")
    feature_id: str = Field(description="Feature routing policy target ID.")
    policy_id: str = Field(description="Policy ID evaluated.")
    policy_version: str = Field(description="Policy version evaluated.")
    initial_model_id: str | None = Field(
        default=None, description="Initial selected model ID before retry/fallback."
    )
    initial_provider_id: str | None = Field(
        default=None, description="Initial selected provider ID before retry/fallback."
    )
    selected_model_id: str | None = Field(
        default=None, description="Final selected backend model ID."
    )
    selected_provider_id: str | None = Field(
        default=None, description="Final selected provider adapter ID."
    )
    routing_reason: str = Field(description="Machine-readable routing decision reason code.")
    fallback_used: bool = Field(
        default=False, description="Whether fallback execution was triggered."
    )
    retry_count: int = Field(default=0, description="Total same-model retry attempts executed.")
    candidate_decisions: Any = Field(
        description="Candidate evaluation details and eligibility outcomes."
    )
    execution_attempts: Any = Field(
        default_factory=list, description="Ordered attempt audit records."
    )
    status: str = Field(
        description="Execution status (SUCCEEDED, NO_ELIGIBLE_MODEL, PROVIDER_ERROR, "
        "BUDGET_REJECTED)."
    )
    error_code: str | None = Field(
        default=None, description="Machine-readable error code if failed."
    )
    prompt_hash: str = Field(description="SHA-256 hash of normalized prompt messages.")
    message_count: int = Field(description="Number of prompt messages.")
    input_tokens: int | None = Field(default=None, description="Actual input token count.")
    output_tokens: int | None = Field(default=None, description="Actual output token count.")
    total_tokens: int | None = Field(default=None, description="Actual total token count.")
    accounted_cost_usd: Decimal | None = Field(
        default=None, description="Accounted cost in USD with high precision."
    )
    cost_source: str | None = Field(default=None, description="Pricing source provenance.")
    provider_latency_ms: int | None = Field(
        default=None, description="Actual provider execution latency in ms."
    )
    created_at: str = Field(description="Request start timestamp in ISO UTC format.")
    completed_at: str = Field(description="Request completion timestamp in ISO UTC format.")
    verification: VerificationSummaryResponse | None = Field(
        default=None, description="Quality verification audit summary if sampled."
    )


@router.get("/{request_id}", response_model=RoutingDecisionRecordResponse)
async def get_routing_decision(
    request_id: str,
    request: Request,
    team_id: Annotated[TeamId, Depends(get_authenticated_team_id)],
) -> RoutingDecisionRecordResponse:
    """Retrieve complete auditable routing decision record for authenticated team."""
    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    if db_manager is None:
        db_manager = DatabaseManager()

    async with db_manager.session_factory() as session:
        record = await get_inference_record_by_request_id(
            session, request_id=request_id, team_id=str(team_id)
        )
        qv_stmt = select(QualityVerificationRecord).where(
            QualityVerificationRecord.request_id == request_id,
            QualityVerificationRecord.team_id == str(team_id),
        )
        qv_res = await session.execute(qv_stmt)
        qv_rec = qv_res.scalar_one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Routing decision not found.",
        )

    verification_summary: VerificationSummaryResponse | None = None
    if qv_rec is not None:
        verification_summary = VerificationSummaryResponse(
            verification_id=str(qv_rec.verification_id),
            status=qv_rec.status,
            strategy=qv_rec.strategy,
            selected_model_id=qv_rec.selected_model_id,
            reference_model_id=qv_rec.reference_model_id,
            score=qv_rec.score,
            passed=qv_rec.passed,
            verification_cost_usd=qv_rec.reference_cost_usd,
            queued_at=qv_rec.queued_at.isoformat(),
            started_at=qv_rec.started_at.isoformat() if qv_rec.started_at else None,
            completed_at=qv_rec.completed_at.isoformat() if qv_rec.completed_at else None,
            failure_code=qv_rec.failure_code,
        )

    return RoutingDecisionRecordResponse(
        request_id=record.request_id,
        team_id=record.team_id,
        feature_id=record.feature_id,
        policy_id=record.policy_id,
        policy_version=record.policy_version,
        initial_model_id=record.initial_model_id,
        initial_provider_id=record.initial_provider_id,
        selected_model_id=record.selected_model_id,
        selected_provider_id=record.selected_provider_id,
        routing_reason=record.routing_reason,
        fallback_used=record.fallback_used if record.fallback_used is not None else False,
        retry_count=record.retry_count if record.retry_count is not None else 0,
        candidate_decisions=record.candidate_decisions,
        execution_attempts=record.execution_attempts
        if record.execution_attempts is not None
        else [],
        status=record.status,
        error_code=record.error_code,
        prompt_hash=record.prompt_hash,
        message_count=record.message_count,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        accounted_cost_usd=record.accounted_cost_usd,
        cost_source=record.cost_source,
        provider_latency_ms=record.provider_latency_ms,
        created_at=record.created_at.isoformat(),
        completed_at=record.completed_at.isoformat(),
        verification=verification_summary,
    )
