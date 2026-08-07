"""Storage operations for authentication, inference recording, limits, and costs."""

import hashlib
import hmac
import secrets
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from routeforge.contracts import (
    ChatMessage,
    KeyId,
    ModelDefinition,
    TeamId,
)
from routeforge.storage.models import (
    ApiKeyModel,
    InferenceRecordModel,
    TeamLimitsModel,
    TeamModel,
)


class AuthResult(NamedTuple):
    """Result of authentication containing team and key identity."""

    team_id: TeamId
    key_id: KeyId
    is_key_active: bool
    is_team_active: bool


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 digest of plaintext API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def parse_api_key_prefix(raw_key: str) -> str | None:
    """Extract public prefix from formatted API key (rf_<prefix>_<secret>)."""
    parts = raw_key.split("_")
    if len(parts) == 3 and parts[0] == "rf" and parts[1]:
        return parts[1]
    return None


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key string, prefix, and SHA-256 hash digest."""
    prefix = secrets.token_hex(4)  # 8 hex chars
    secret = secrets.token_hex(16)  # 32 hex chars
    full_key = f"rf_{prefix}_{secret}"
    key_hash = hash_api_key(full_key)
    return full_key, prefix, key_hash


async def authenticate_api_key(session: AsyncSession, raw_key: str) -> AuthResult | None:
    """Authenticate API key against database, returning AuthResult or None if key invalid."""
    key_prefix = parse_api_key_prefix(raw_key)
    if key_prefix is None:
        return None

    computed_hash = hash_api_key(raw_key)

    stmt = select(ApiKeyModel).where(ApiKeyModel.key_prefix == key_prefix)
    result = await session.execute(stmt)
    candidate_keys = result.scalars().all()

    matched_key: ApiKeyModel | None = None
    for candidate in candidate_keys:
        if hmac.compare_digest(candidate.key_hash, computed_hash):
            matched_key = candidate
            break

    if matched_key is None:
        return None

    # Fetch team to check activity
    stmt_team = select(TeamModel).where(TeamModel.team_id == matched_key.team_id)
    team_result = await session.execute(stmt_team)
    team = team_result.scalar_one_or_none()

    if team is None:
        return None

    # Update last_used_at timestamp safely
    matched_key.last_used_at = datetime.now(UTC)
    await session.commit()

    return AuthResult(
        team_id=TeamId(matched_key.team_id),
        key_id=KeyId(str(matched_key.key_id)),
        is_key_active=matched_key.active,
        is_team_active=team.active,
    )


def hash_prompt(messages: Sequence[ChatMessage]) -> str:
    """Compute canonical SHA-256 digest over normalized message roles and contents."""
    canonical_parts: list[str] = []
    for msg in messages:
        role_str = str(msg.role).lower()
        content_str = msg.content
        canonical_parts.append(f"{role_str}:{content_str}")

    canonical_str = "\n".join(canonical_parts) + "\n"
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def calculate_accounted_cost(
    model: ModelDefinition, input_tokens: int, output_tokens: int
) -> Decimal:
    """Compute accounted cost USD from actual token usage and configured model pricing."""
    input_cost = (
        Decimal(input_tokens) * model.estimated_input_cost_per_million_tokens_usd
    ) / Decimal("1000000")
    output_cost = (
        Decimal(output_tokens) * model.estimated_output_cost_per_million_tokens_usd
    ) / Decimal("1000000")
    return input_cost + output_cost


def get_monthly_period_start(now: datetime | None = None) -> date:
    """Return current UTC calendar month start date."""
    if now is None:
        now = datetime.now(UTC)
    return date(now.year, now.month, 1)


def get_monthly_period_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return timezone-aware start and end UTC datetime bounds for current calendar month."""
    if now is None:
        now = datetime.now(UTC)

    period_start = datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=UTC)
    if now.month == 12:
        period_end = datetime(now.year + 1, 1, 1, 0, 0, 0, tzinfo=UTC)
    else:
        period_end = datetime(now.year, now.month + 1, 1, 0, 0, 0, tzinfo=UTC)

    return period_start, period_end


async def get_team_limits(session: AsyncSession, team_id: str) -> TeamLimitsModel | None:
    """Retrieve operational rate limits and monthly budget configuration for a team."""
    stmt = select(TeamLimitsModel).where(
        TeamLimitsModel.team_id == team_id,
        TeamLimitsModel.active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_or_update_team_limits(
    session: AsyncSession,
    team_id: str,
    requests_per_minute: int,
    tokens_per_minute: int,
    monthly_budget_usd: Decimal,
) -> TeamLimitsModel:
    """Create or update operational rate limits and budget cap for a team."""
    stmt = select(TeamLimitsModel).where(TeamLimitsModel.team_id == team_id)
    res = await session.execute(stmt)
    limits = res.scalar_one_or_none()

    now = datetime.now(UTC)
    if limits is None:
        limits = TeamLimitsModel(
            team_id=team_id,
            requests_per_minute=requests_per_minute,
            tokens_per_minute=tokens_per_minute,
            monthly_budget_usd=monthly_budget_usd,
            active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(limits)
    else:
        limits.requests_per_minute = requests_per_minute
        limits.tokens_per_minute = tokens_per_minute
        limits.monthly_budget_usd = monthly_budget_usd
        limits.updated_at = now

    await session.commit()
    return limits


async def reserve_budget_for_request(
    session: AsyncSession,
    team_id: str,
    estimated_cost_usd: Decimal,
    now: datetime | None = None,
) -> tuple[bool, Decimal | None, Decimal, Decimal]:
    """Atomically evaluate monthly budget cap and reserve estimated cost in PostgreSQL.

    Returns (allowed, monthly_budget_usd, current_committed_usd, estimated_cost_usd).
    If no team limits exist, returns (True, None, 0, estimated_cost_usd) allowing request.
    """
    if now is None:
        now = datetime.now(UTC)

    period_start_dt, period_end_dt = get_monthly_period_bounds(now)

    # 1. Lock team_limits row using SELECT ... FOR UPDATE for concurrency safety
    stmt_limits = (
        select(TeamLimitsModel)
        .where(TeamLimitsModel.team_id == team_id, TeamLimitsModel.active.is_(True))
        .with_for_update()
    )
    res_limits = await session.execute(stmt_limits)
    limits = res_limits.scalar_one_or_none()

    if limits is None:
        # No configured budget cap on team -> budget check succeeds
        return True, None, Decimal("0"), estimated_cost_usd

    monthly_budget = limits.monthly_budget_usd

    # 2. Calculate current monthly committed spending (accounted + reserved costs)
    stmt_acc = select(
        func.coalesce(func.sum(InferenceRecordModel.accounted_cost_usd), Decimal("0"))
    ).where(
        InferenceRecordModel.team_id == team_id,
        InferenceRecordModel.status == "SUCCEEDED",
        InferenceRecordModel.created_at >= period_start_dt,
        InferenceRecordModel.created_at < period_end_dt,
    )
    acc_res = await session.execute(stmt_acc)
    accounted_sum = acc_res.scalar() or Decimal("0")

    stmt_res = select(
        func.coalesce(func.sum(InferenceRecordModel.reserved_cost_usd), Decimal("0"))
    ).where(
        InferenceRecordModel.team_id == team_id,
        InferenceRecordModel.status == "BUDGET_RESERVED",
        InferenceRecordModel.created_at >= period_start_dt,
        InferenceRecordModel.created_at < period_end_dt,
    )
    res_sum_res = await session.execute(stmt_res)
    reserved_sum = res_sum_res.scalar() or Decimal("0")

    committed_spending = Decimal(str(accounted_sum)) + Decimal(str(reserved_sum))

    if committed_spending + estimated_cost_usd > monthly_budget:
        return False, monthly_budget, committed_spending, estimated_cost_usd

    return True, monthly_budget, committed_spending, estimated_cost_usd


async def replace_budget_reservation(
    session: AsyncSession,
    request_id: str,
    team_id: str,
    new_estimated_cost: Decimal,
    now: datetime | None = None,
) -> tuple[bool, Decimal | None, Decimal]:
    """Atomically replace budget reservation for fallback attempt within PostgreSQL transaction.

    Returns (allowed, monthly_budget_usd, committed_spending_usd).
    """
    if now is None:
        now = datetime.now(UTC)

    period_start_dt, period_end_dt = get_monthly_period_bounds(now)

    # 1. Lock team_limits row using SELECT ... FOR UPDATE
    stmt_limits = (
        select(TeamLimitsModel)
        .where(TeamLimitsModel.team_id == team_id, TeamLimitsModel.active.is_(True))
        .with_for_update()
    )
    res_limits = await session.execute(stmt_limits)
    limits = res_limits.scalar_one_or_none()

    # 2. Lock inference_records row for request_id
    stmt_rec = (
        select(InferenceRecordModel)
        .where(
            InferenceRecordModel.request_id == request_id,
            InferenceRecordModel.team_id == team_id,
        )
        .with_for_update()
    )
    res_rec = await session.execute(stmt_rec)
    record = res_rec.scalar_one_or_none()

    monthly_budget = limits.monthly_budget_usd if limits is not None else None

    if limits is not None:
        # 3. Calculate committed spending excluding current request_id's reservation
        stmt_acc = select(
            func.coalesce(func.sum(InferenceRecordModel.accounted_cost_usd), Decimal("0"))
        ).where(
            InferenceRecordModel.team_id == team_id,
            InferenceRecordModel.status == "SUCCEEDED",
            InferenceRecordModel.created_at >= period_start_dt,
            InferenceRecordModel.created_at < period_end_dt,
        )
        acc_res = await session.execute(stmt_acc)
        accounted_sum = acc_res.scalar() or Decimal("0")

        stmt_res = select(
            func.coalesce(func.sum(InferenceRecordModel.reserved_cost_usd), Decimal("0"))
        ).where(
            InferenceRecordModel.team_id == team_id,
            InferenceRecordModel.status == "BUDGET_RESERVED",
            InferenceRecordModel.request_id != request_id,
            InferenceRecordModel.created_at >= period_start_dt,
            InferenceRecordModel.created_at < period_end_dt,
        )
        res_sum_res = await session.execute(stmt_res)
        reserved_sum = res_sum_res.scalar() or Decimal("0")

        committed_spending = Decimal(str(accounted_sum)) + Decimal(str(reserved_sum))

        if committed_spending + new_estimated_cost > limits.monthly_budget_usd:
            if record is not None:
                record.reserved_cost_usd = Decimal("0")
                record.status = "BUDGET_REJECTED"
                record.error_code = "FALLBACK_BUDGET_EXCEEDED"
                record.completed_at = datetime.now(UTC)
                await session.commit()
            return False, monthly_budget, committed_spending

    committed_spending = Decimal("0")
    if record is not None:
        record.estimated_cost_usd = new_estimated_cost
        record.reserved_cost_usd = new_estimated_cost
        record.status = "BUDGET_RESERVED"
        record.completed_at = datetime.now(UTC)
        await session.commit()

    return True, monthly_budget, committed_spending


async def reconcile_actual_cost(
    session: AsyncSession,
    request_id: str,
    actual_cost_usd: Decimal,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    provider_latency_ms: int,
    execution_attempts: list[dict[str, Any]] | None = None,
    retry_count: int | None = None,
    fallback_used: bool | None = None,
    selected_model_id: str | None = None,
    selected_provider_id: str | None = None,
    routing_reason: str | None = None,
) -> InferenceRecordModel | None:
    """Reconcile reserved cost to actual accounted cost upon successful provider execution."""
    stmt = select(InferenceRecordModel).where(InferenceRecordModel.request_id == request_id)
    res = await session.execute(stmt)
    record = res.scalar_one_or_none()

    if record is not None:
        record.accounted_cost_usd = actual_cost_usd
        record.reserved_cost_usd = Decimal("0")
        record.status = "SUCCEEDED"
        record.input_tokens = input_tokens
        record.output_tokens = output_tokens
        record.total_tokens = total_tokens
        record.provider_latency_ms = provider_latency_ms
        if execution_attempts is not None:
            record.execution_attempts = execution_attempts
        if retry_count is not None:
            record.retry_count = retry_count
        if fallback_used is not None:
            record.fallback_used = fallback_used
        if selected_model_id is not None:
            record.selected_model_id = selected_model_id
        if selected_provider_id is not None:
            record.selected_provider_id = selected_provider_id
        if routing_reason is not None:
            record.routing_reason = routing_reason
        record.completed_at = datetime.now(UTC)
        await session.commit()
    return record


async def release_budget_reservation(
    session: AsyncSession,
    request_id: str,
    status_name: str = "PROVIDER_ERROR",
    error_code: str | None = None,
    execution_attempts: list[dict[str, Any]] | None = None,
    retry_count: int | None = None,
    fallback_used: bool | None = None,
) -> InferenceRecordModel | None:
    """Release reserved cost on provider failure or unhandled exception."""
    stmt = select(InferenceRecordModel).where(InferenceRecordModel.request_id == request_id)
    res = await session.execute(stmt)
    record = res.scalar_one_or_none()

    if record is not None:
        record.reserved_cost_usd = Decimal("0")
        record.status = status_name
        record.error_code = error_code
        if execution_attempts is not None:
            record.execution_attempts = execution_attempts
        if retry_count is not None:
            record.retry_count = retry_count
        if fallback_used is not None:
            record.fallback_used = fallback_used
        record.completed_at = datetime.now(UTC)
        await session.commit()
    return record


async def create_inference_record(session: AsyncSession, record: InferenceRecordModel) -> None:
    """Persist a single durable inference record."""
    session.add(record)
    await session.commit()


async def get_inference_record_by_request_id(
    session: AsyncSession, request_id: str, team_id: str
) -> InferenceRecordModel | None:
    """Retrieve inference record by request ID, enforcing team identity isolation."""
    stmt = select(InferenceRecordModel).where(
        InferenceRecordModel.request_id == request_id,
        InferenceRecordModel.team_id == team_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_or_get_team(session: AsyncSession, team_id: str, display_name: str) -> TeamModel:
    """Create team if absent or retrieve existing team."""
    stmt = select(TeamModel).where(TeamModel.team_id == team_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    team = TeamModel(
        team_id=team_id,
        display_name=display_name,
        active=True,
        created_at=datetime.now(UTC),
    )
    session.add(team)
    await session.commit()
    return team


async def create_api_key_record(
    session: AsyncSession,
    team_id: str,
    key_prefix: str,
    key_hash: str,
    active: bool = True,
) -> ApiKeyModel:
    """Create a new API key database record for a team."""
    key_record = ApiKeyModel(
        team_id=team_id,
        key_prefix=key_prefix,
        key_hash=key_hash,
        active=active,
        created_at=datetime.now(UTC),
    )
    session.add(key_record)
    await session.commit()
    return key_record


async def get_monthly_usage_summary(
    session: AsyncSession,
    team_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate request counts and token usage for team's current month."""
    period_start_dt, period_end_dt = get_monthly_period_bounds(now)

    stmt = select(InferenceRecordModel).where(
        InferenceRecordModel.team_id == team_id,
        InferenceRecordModel.created_at >= period_start_dt,
        InferenceRecordModel.created_at < period_end_dt,
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    request_count = len(records)
    successful_count = sum(1 for r in records if r.status == "SUCCEEDED")
    no_eligible_count = sum(1 for r in records if r.routing_reason == "NO_ELIGIBLE_MODEL")
    provider_error_count = sum(1 for r in records if r.status == "PROVIDER_ERROR")
    budget_rejected_count = sum(1 for r in records if r.status == "BUDGET_REJECTED")

    total_input_tokens = sum(r.input_tokens or 0 for r in records)
    total_output_tokens = sum(r.output_tokens or 0 for r in records)
    total_tokens = sum(r.total_tokens or 0 for r in records)

    return {
        "request_count": request_count,
        "successful_request_count": successful_count,
        "no_eligible_count": no_eligible_count,
        "provider_error_count": provider_error_count,
        "budget_rejected_count": budget_rejected_count,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
    }


async def get_monthly_cost_summary(
    session: AsyncSession,
    team_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate monthly budget, accounted cost, reserved cost, and available budget."""
    period_start_dt, period_end_dt = get_monthly_period_bounds(now)

    limits = await get_team_limits(session, team_id)
    monthly_budget = limits.monthly_budget_usd if limits is not None else Decimal("0")

    stmt_acc = select(
        func.coalesce(func.sum(InferenceRecordModel.accounted_cost_usd), Decimal("0"))
    ).where(
        InferenceRecordModel.team_id == team_id,
        InferenceRecordModel.status == "SUCCEEDED",
        InferenceRecordModel.created_at >= period_start_dt,
        InferenceRecordModel.created_at < period_end_dt,
    )
    acc_res = await session.execute(stmt_acc)
    acc_val = acc_res.scalar()
    accounted_cost = acc_val if isinstance(acc_val, Decimal) else Decimal(str(acc_val or "0"))

    stmt_res = select(
        func.coalesce(func.sum(InferenceRecordModel.reserved_cost_usd), Decimal("0"))
    ).where(
        InferenceRecordModel.team_id == team_id,
        InferenceRecordModel.status == "BUDGET_RESERVED",
        InferenceRecordModel.created_at >= period_start_dt,
        InferenceRecordModel.created_at < period_end_dt,
    )
    res_res = await session.execute(stmt_res)
    res_val = res_res.scalar()
    reserved_cost = res_val if isinstance(res_val, Decimal) else Decimal(str(res_val or "0"))

    committed_cost = accounted_cost + reserved_cost
    remaining_budget = max(Decimal("0"), monthly_budget - committed_cost)
    overrun_cost = max(Decimal("0"), committed_cost - monthly_budget)

    if monthly_budget > Decimal("0"):
        utilization_pct = float(
            (committed_cost / monthly_budget * Decimal("100")).quantize(Decimal("0.01"))
        )
    else:
        utilization_pct = 0.0

    return {
        "monthly_budget_usd": monthly_budget,
        "accounted_cost_usd": accounted_cost,
        "reserved_cost_usd": reserved_cost,
        "committed_cost_usd": committed_cost,
        "remaining_available_budget_usd": remaining_budget,
        "overrun_cost_usd": overrun_cost,
        "budget_utilization_percentage": utilization_pct,
        "currency": "USD",
        "period_start": period_start_dt.isoformat(),
        "period_end": period_end_dt.isoformat(),
    }
