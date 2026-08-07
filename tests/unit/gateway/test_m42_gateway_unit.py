"""Unit tests for M4.2 rate limiting and budget enforcement on HTTP endpoints."""

from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from routeforge.contracts import TeamId
from routeforge.gateway import create_app
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.storage.models import TeamLimitsModel
from routeforge.storage.ratelimit import RateLimitResult, RedisUnavailableError


class MockAsyncSessionContext:
    def __init__(
        self, limits: TeamLimitsModel | None = None, session_override: Any | None = None
    ) -> None:
        if session_override is not None:
            self.session = session_override
        else:
            self.session = AsyncMock()
            res_limits = MagicMock()
            res_limits.scalar_one_or_none.return_value = limits
            res_acc = MagicMock()
            res_acc.scalar.return_value = Decimal("0")
            res_acc.scalar_one.return_value = Decimal("0")
            res_res = MagicMock()
            res_res.scalar.return_value = Decimal("0")
            res_res.scalar_one.return_value = Decimal("0")
            self.session.execute.side_effect = [
                res_limits,
                res_acc,
                res_res,
                res_limits,
                res_acc,
                res_res,
            ]

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        pass


class MockDbManager:
    def __init__(
        self,
        limits: TeamLimitsModel | None = None,
        session_override: Any | None = None,
    ) -> None:
        self.limits = limits
        self.session_override = session_override

    def session_factory(self) -> Any:
        return MockAsyncSessionContext(self.limits, self.session_override)

    async def aclose(self) -> None:
        pass


@pytest.mark.anyio
async def test_chat_rate_limit_exceeded_http_429() -> None:
    limits = TeamLimitsModel(
        team_id="team-m42-unit",
        requests_per_minute=2,
        tokens_per_minute=1000,
        monthly_budget_usd=Decimal("50.00"),
        active=True,
    )
    mock_db = MockDbManager(limits=limits)
    mock_limiter = AsyncMock()
    mock_limiter.check_and_consume.return_value = RateLimitResult(
        allowed=False,
        exceeded_limit_type="requests",
        limit_requests=2,
        remaining_requests=0,
        limit_tokens=1000,
        remaining_tokens=900,
        reset_timestamp=1786000000,
        retry_after_seconds=45,
    )

    app = create_app(db_manager=cast(Any, mock_db), rate_limiter=cast(Any, mock_limiter))
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-m42-unit")

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
        )
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "45"
        assert resp.json()["error"]["code"] == "REQUEST_RATE_LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_chat_redis_unavailable_http_503() -> None:
    limits = TeamLimitsModel(
        team_id="team-m42-unit",
        requests_per_minute=2,
        tokens_per_minute=1000,
        monthly_budget_usd=Decimal("50.00"),
        active=True,
    )
    mock_db = MockDbManager(limits=limits)
    mock_limiter = AsyncMock()
    mock_limiter.check_and_consume.side_effect = RedisUnavailableError("Redis down")

    app = create_app(db_manager=cast(Any, mock_db), rate_limiter=cast(Any, mock_limiter))
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-m42-unit")

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "RATE_LIMIT_BACKEND_UNAVAILABLE"


@pytest.mark.anyio
async def test_chat_budget_exceeded_http_402() -> None:
    limits = TeamLimitsModel(
        team_id="team-m42-unit",
        requests_per_minute=100,
        tokens_per_minute=100000,
        monthly_budget_usd=Decimal("1.00"),
        active=True,
    )

    session = AsyncMock()
    res_limits = MagicMock()
    res_limits.scalar_one_or_none.return_value = limits

    res_acc = MagicMock()
    res_acc.scalar.return_value = Decimal("2.00")
    res_acc.scalar_one.return_value = Decimal("2.00")

    res_res = MagicMock()
    res_res.scalar.return_value = Decimal("0")
    res_res.scalar_one.return_value = Decimal("0")

    session.execute.side_effect = [res_limits, res_limits, res_acc, res_res]
    mock_db = MockDbManager(limits=limits, session_override=session)

    mock_limiter = AsyncMock()
    mock_limiter.check_and_consume.return_value = RateLimitResult(
        allowed=True,
        exceeded_limit_type=None,
        limit_requests=100,
        remaining_requests=99,
        limit_tokens=100000,
        remaining_tokens=99800,
        reset_timestamp=1786000000,
        retry_after_seconds=0,
    )

    app = create_app(db_manager=cast(Any, mock_db), rate_limiter=cast(Any, mock_limiter))
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-m42-unit")

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
        )
        assert resp.status_code == 402
        assert resp.json()["error"]["code"] == "MONTHLY_BUDGET_EXCEEDED"


@pytest.mark.anyio
async def test_get_usage_and_costs_endpoints() -> None:
    session = AsyncMock()

    # Mock records for usage query
    res_usage = MagicMock()
    res_usage.scalars.return_value.all.return_value = []

    # Mock limits & sums for costs query
    limits = TeamLimitsModel(
        team_id="team-m42-unit",
        monthly_budget_usd=Decimal("50.00"),
        active=True,
    )
    res_limits = MagicMock()
    res_limits.scalar_one_or_none.return_value = limits

    res_acc = MagicMock()
    res_acc.scalar.return_value = Decimal("5.00")

    res_res = MagicMock()
    res_res.scalar.return_value = Decimal("1.00")

    session.execute.side_effect = [res_usage, res_limits, res_acc, res_res]
    mock_db = MockDbManager(session_override=session)

    app = create_app(db_manager=cast(Any, mock_db))
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-m42-unit")

    with TestClient(app) as client:
        u_resp = client.get("/v1/usage")
        assert u_resp.status_code == 200
        assert u_resp.json()["request_count"] == 0

        c_resp = client.get("/v1/costs")
        assert c_resp.status_code == 200
        data = c_resp.json()
        assert data["currency"] == "USD"
        assert Decimal(data["monthly_budget_usd"]) == Decimal("50.00000000")
        assert Decimal(data["committed_cost_usd"]) == Decimal("6.00000000")


@pytest.mark.anyio
async def test_readyz_redis_unhealthy() -> None:
    mock_db = MockDbManager()
    mock_limiter = AsyncMock()
    mock_limiter.ping.return_value = False

    app = create_app(db_manager=cast(Any, mock_db), rate_limiter=cast(Any, mock_limiter))
    with TestClient(app) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert data["redis"] == "unavailable"
