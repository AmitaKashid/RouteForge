"""Unit tests for fixed-minute window calculation, rate limit structures, and Redis errors."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import redis.exceptions

from routeforge.gateway.routes.costs import CostSummaryResponse
from routeforge.gateway.routes.usage import UsageSummaryResponse
from routeforge.storage.ratelimit import (
    RateLimitResult,
    RedisRateLimiter,
    RedisUnavailableError,
    calculate_minute_window,
    get_redis_url,
)
from routeforge.storage.records import (
    get_monthly_period_bounds,
    get_monthly_period_start,
)


def test_calculate_minute_window() -> None:
    dt1 = datetime(2026, 8, 6, 12, 0, 15, tzinfo=UTC)
    dt2 = datetime(2026, 8, 6, 12, 0, 45, tzinfo=UTC)
    dt3 = datetime(2026, 8, 6, 12, 1, 0, tzinfo=UTC)

    w1 = calculate_minute_window(dt1)
    w2 = calculate_minute_window(dt2)
    w3 = calculate_minute_window(dt3)

    assert w1 == w2
    assert w3 == w1 + 1


def test_monthly_period_start_and_bounds() -> None:
    dt = datetime(2026, 8, 15, 14, 30, 0, tzinfo=UTC)
    start_date = get_monthly_period_start(dt)
    assert start_date.year == 2026
    assert start_date.month == 8
    assert start_date.day == 1

    start_dt, end_dt = get_monthly_period_bounds(dt)
    assert start_dt == datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

    # Test December rollover
    dec_dt = datetime(2026, 12, 20, 10, 0, 0, tzinfo=UTC)
    d_start, d_end = get_monthly_period_bounds(dec_dt)
    assert d_start == datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC)
    assert d_end == datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_rate_limit_result_fields() -> None:
    res = RateLimitResult(
        allowed=True,
        exceeded_limit_type=None,
        limit_requests=60,
        remaining_requests=59,
        limit_tokens=50000,
        remaining_tokens=49800,
        reset_timestamp=1786000000,
        retry_after_seconds=30,
    )
    assert res.allowed is True
    assert res.remaining_requests == 59


def test_usage_summary_response_serialization() -> None:
    summary = UsageSummaryResponse(
        request_count=10,
        successful_request_count=8,
        no_eligible_count=1,
        provider_error_count=1,
        budget_rejected_count=0,
        total_input_tokens=100,
        total_output_tokens=50,
        total_tokens=150,
    )
    data = summary.model_dump(mode="json")
    assert data["request_count"] == 10
    assert data["total_tokens"] == 150


def test_cost_summary_response_serialization() -> None:
    costs = CostSummaryResponse(
        monthly_budget_usd=Decimal("25.00000000"),
        accounted_cost_usd=Decimal("5.25000000"),
        reserved_cost_usd=Decimal("0.00000000"),
        committed_cost_usd=Decimal("5.25000000"),
        remaining_available_budget_usd=Decimal("19.75000000"),
        overrun_cost_usd=Decimal("0.00000000"),
        budget_utilization_percentage=21.0,
        currency="USD",
        period_start="2026-08-01T00:00:00+00:00",
        period_end="2026-09-01T00:00:00+00:00",
    )
    data = costs.model_dump(mode="json")
    assert data["monthly_budget_usd"] == "25.00000000"
    assert data["budget_utilization_percentage"] == 21.0


def test_get_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTEFORGE_REDIS_URL", "redis://custom-redis:6379/1")
    assert get_redis_url() == "redis://custom-redis:6379/1"
    monkeypatch.delenv("ROUTEFORGE_REDIS_URL", raising=False)
    assert get_redis_url() == "redis://localhost:6379/0"


@pytest.mark.anyio
async def test_redis_rate_limiter_mocked_allowed() -> None:
    mock_client = AsyncMock()
    mock_client.eval.return_value = [1, 0, 1, 200]

    limiter = RedisRateLimiter(redis_client=mock_client)
    res = await limiter.check_and_consume(
        team_id="team-1",
        requests_per_minute=60,
        tokens_per_minute=50000,
        estimated_tokens=200,
        now=datetime(2026, 8, 6, 12, 0, 15, tzinfo=UTC),
    )
    assert res.allowed is True
    assert res.remaining_requests == 59
    assert res.remaining_tokens == 49800


@pytest.mark.anyio
async def test_redis_rate_limiter_mocked_request_exceeded() -> None:
    mock_client = AsyncMock()
    mock_client.eval.return_value = [0, 1, 0, 49800]

    limiter = RedisRateLimiter(redis_client=mock_client)
    res = await limiter.check_and_consume(
        team_id="team-1",
        requests_per_minute=60,
        tokens_per_minute=50000,
        estimated_tokens=200,
        now=datetime(2026, 8, 6, 12, 0, 15, tzinfo=UTC),
    )
    assert res.allowed is False
    assert res.exceeded_limit_type == "requests"


@pytest.mark.anyio
async def test_redis_rate_limiter_mocked_token_exceeded() -> None:
    mock_client = AsyncMock()
    mock_client.eval.return_value = [0, 2, 59, 0]

    limiter = RedisRateLimiter(redis_client=mock_client)
    res = await limiter.check_and_consume(
        team_id="team-1",
        requests_per_minute=60,
        tokens_per_minute=50000,
        estimated_tokens=200,
        now=datetime(2026, 8, 6, 12, 0, 15, tzinfo=UTC),
    )
    assert res.allowed is False
    assert res.exceeded_limit_type == "tokens"


@pytest.mark.anyio
async def test_redis_rate_limiter_error_handling() -> None:
    mock_client = AsyncMock()
    mock_client.eval.side_effect = redis.exceptions.RedisError("Connection refused")

    limiter = RedisRateLimiter(redis_client=mock_client)
    with pytest.raises(RedisUnavailableError):
        await limiter.check_and_consume(
            team_id="team-1",
            requests_per_minute=60,
            tokens_per_minute=50000,
            estimated_tokens=200,
        )


@pytest.mark.anyio
async def test_redis_rate_limiter_ping_and_aclose() -> None:
    mock_client = AsyncMock()
    mock_client.ping.return_value = True

    limiter = RedisRateLimiter(redis_client=mock_client)
    assert await limiter.ping() is True
    await limiter.aclose()
    mock_client.aclose.assert_called_once()


@pytest.mark.anyio
async def test_redis_rate_limiter_lazy_client_init() -> None:
    from unittest.mock import patch

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_client.eval.return_value = [1, 0, 59, 100]

        limiter = RedisRateLimiter()
        res = await limiter.check_and_consume(
            team_id="team-1",
            requests_per_minute=60,
            tokens_per_minute=50000,
            estimated_tokens=200,
        )
        assert res.allowed is True
        mock_from_url.assert_called_once()

    limiter_none = RedisRateLimiter()
    await limiter_none.aclose()
