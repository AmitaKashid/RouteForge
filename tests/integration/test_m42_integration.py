"""Integration tests for RouteForge M4.2 Budget and Rate Enforcement."""

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient
from scripts.set_team_limits import async_main as set_team_limits_main
from sqlalchemy import text

from routeforge.gateway import create_app
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import Base, InferenceRecordModel
from routeforge.storage.ratelimit import RedisRateLimiter
from routeforge.storage.records import (
    create_api_key_record,
    create_or_get_team,
    generate_api_key,
    reconcile_actual_cost,
    reserve_budget_for_request,
)

TEST_DB_URL = os.getenv(
    "ROUTEFORGE_TEST_DATABASE_URL",
    "postgresql+asyncpg://routeforge:routeforge_pass@localhost:5432/routeforge_dev",
)
TEST_REDIS_URL = os.getenv(
    "ROUTEFORGE_TEST_REDIS_URL",
    "redis://localhost:6379/0",
)

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
async def db_manager() -> DatabaseManager:
    """Provide real DatabaseManager fixture connected to PostgreSQL test database."""
    try:
        manager = DatabaseManager(database_url=TEST_DB_URL)
        async with manager.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip(
            f"PostgreSQL test database unavailable at {TEST_DB_URL}. Skipping integration tests."
        )

    # Recreate tables cleanly
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    return manager


@pytest.fixture(scope="module")
async def redis_limiter() -> RedisRateLimiter:
    """Provide real RedisRateLimiter fixture connected to Redis test database."""
    try:
        r_client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
        await r_client.ping()
        await r_client.flushdb()
        limiter = RedisRateLimiter(redis_client=r_client)
    except Exception:
        pytest.skip(f"Redis unavailable at {TEST_REDIS_URL}. Skipping integration tests.")

    return limiter


async def test_team_limits_creation_and_update(db_manager: DatabaseManager) -> None:
    async with db_manager.session_factory() as session:
        await create_or_get_team(session, "team-lim-1", "Limiter Team 1")

    # Set limits via CLI script entry point
    res1 = await set_team_limits_main(
        team_id="team-lim-1",
        requests_per_minute=10,
        tokens_per_minute=1000,
        monthly_budget_usd=Decimal("50.00"),
    )
    assert res1 == 0

    # Update limits
    res2 = await set_team_limits_main(
        team_id="team-lim-1",
        requests_per_minute=20,
        tokens_per_minute=2000,
        monthly_budget_usd=Decimal("100.00"),
    )
    assert res2 == 0


async def test_redis_rate_limiter_request_and_token_exhaustion(
    redis_limiter: RedisRateLimiter,
) -> None:
    now = datetime.now(UTC)

    # 1. Allowed request rate
    res1 = await redis_limiter.check_and_consume(
        team_id="t-rl-1",
        requests_per_minute=2,
        tokens_per_minute=1000,
        estimated_tokens=100,
        now=now,
    )
    assert res1.allowed is True
    assert res1.remaining_requests == 1

    res2 = await redis_limiter.check_and_consume(
        team_id="t-rl-1",
        requests_per_minute=2,
        tokens_per_minute=1000,
        estimated_tokens=100,
        now=now,
    )
    assert res2.allowed is True
    assert res2.remaining_requests == 0

    # 2. Request limit exhausted
    res3 = await redis_limiter.check_and_consume(
        team_id="t-rl-1",
        requests_per_minute=2,
        tokens_per_minute=1000,
        estimated_tokens=100,
        now=now,
    )
    assert res3.allowed is False
    assert res3.exceeded_limit_type == "requests"

    # 3. Token limit exhausted for another team
    res_tok1 = await redis_limiter.check_and_consume(
        team_id="t-rl-2",
        requests_per_minute=10,
        tokens_per_minute=500,
        estimated_tokens=400,
        now=now,
    )
    assert res_tok1.allowed is True

    res_tok2 = await redis_limiter.check_and_consume(
        team_id="t-rl-2",
        requests_per_minute=10,
        tokens_per_minute=500,
        estimated_tokens=200,
        now=now,
    )
    assert res_tok2.allowed is False
    assert res_tok2.exceeded_limit_type == "tokens"


async def test_budget_reservation_and_reconciliation(db_manager: DatabaseManager) -> None:
    async with db_manager.session_factory() as session:
        await create_or_get_team(session, "t-bg-1", "Budget Team")

    await set_team_limits_main(
        team_id="t-bg-1",
        requests_per_minute=100,
        tokens_per_minute=100000,
        monthly_budget_usd=Decimal("10.00"),
    )

    now = datetime.now(UTC)

    # Reserve $3.00
    async with db_manager.session_factory() as session:
        allowed, _budget, committed, _est = await reserve_budget_for_request(
            session, "t-bg-1", Decimal("3.00"), now=now
        )
        assert allowed is True
        assert committed == Decimal("0")

        record = InferenceRecordModel(
            request_id="req-res-1",
            team_id="t-bg-1",
            feature_id="general-chat",
            policy_id="p1",
            policy_version="v1",
            selected_model_id="mock-economy",
            selected_provider_id="mock",
            routing_reason="CHEAPEST_ELIGIBLE_MODEL",
            candidate_decisions=[],
            status="BUDGET_RESERVED",
            prompt_hash="a" * 64,
            message_count=1,
            estimated_cost_usd=Decimal("3.00"),
            reserved_cost_usd=Decimal("3.00"),
            budget_period_start=now.date().replace(day=1),
            created_at=now,
            completed_at=now,
        )
        session.add(record)
        await session.commit()

    # Reconcile actual cost $2.50
    async with db_manager.session_factory() as session:
        await reconcile_actual_cost(
            session=session,
            request_id="req-res-1",
            actual_cost_usd=Decimal("2.50"),
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            provider_latency_ms=45,
        )

    # Reserve $8.00 -> Should exceed budget $10.00 (since $2.50 + $8.00 = $10.50 > $10.00)
    async with db_manager.session_factory() as session:
        allowed2, _budget2, committed2, _est2 = await reserve_budget_for_request(
            session, "t-bg-1", Decimal("8.00"), now=now
        )
        assert allowed2 is False
        assert committed2 == Decimal("2.50")


async def test_concurrent_budget_reservations(db_manager: DatabaseManager) -> None:
    async with db_manager.session_factory() as session:
        await create_or_get_team(session, "t-conc-1", "Concurrency Team")

    await set_team_limits_main(
        team_id="t-conc-1",
        requests_per_minute=100,
        tokens_per_minute=100000,
        monthly_budget_usd=Decimal("5.00"),
    )

    now = datetime.now(UTC)

    async def _try_reserve(idx: int) -> bool:
        async with db_manager.session_factory() as session:
            allowed, _, _, _ = await reserve_budget_for_request(
                session, "t-conc-1", Decimal("2.00"), now=now
            )
            if allowed:
                rec = InferenceRecordModel(
                    request_id=f"req-conc-{idx}",
                    team_id="t-conc-1",
                    feature_id="general-chat",
                    policy_id="p1",
                    policy_version="v1",
                    selected_model_id="m1",
                    selected_provider_id="p1",
                    routing_reason="CHEAPEST_ELIGIBLE_MODEL",
                    candidate_decisions=[],
                    status="BUDGET_RESERVED",
                    prompt_hash="b" * 64,
                    message_count=1,
                    estimated_cost_usd=Decimal("2.00"),
                    reserved_cost_usd=Decimal("2.00"),
                    budget_period_start=now.date().replace(day=1),
                    created_at=now,
                    completed_at=now,
                )
                session.add(rec)
                await session.commit()
            return allowed

    # Execute 4 concurrent reservations of $2.00 each on a $5.00 budget. Max allowed must be 2!
    results = await asyncio.gather(*[_try_reserve(i) for i in range(4)])
    successful_reservations = sum(1 for r in results if r is True)
    assert successful_reservations == 2


async def test_gateway_rate_limit_and_budget_http_responses(
    db_manager: DatabaseManager, redis_limiter: RedisRateLimiter
) -> None:
    async with db_manager.session_factory() as session:
        await create_or_get_team(session, "team-http-1", "HTTP Test Team")
        full_key, prefix, key_hash = generate_api_key()
        await create_api_key_record(session, "team-http-1", prefix, key_hash)

    # Set 1 req/min and $1.00 budget cap
    await set_team_limits_main(
        team_id="team-http-1",
        requests_per_minute=1,
        tokens_per_minute=50000,
        monthly_budget_usd=Decimal("1.00"),
    )

    app = create_app(db_manager=db_manager, rate_limiter=redis_limiter)
    headers = {"Authorization": f"Bearer {full_key}"}

    with TestClient(app) as client:
        payload = {
            "model": "routeforge",
            "messages": [{"role": "user", "content": "Hello rate limits!"}],
            "routeforge": {"feature_id": "general-chat"},
        }

        # 1st request -> HTTP 200 OK with rate limit headers
        resp1 = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert resp1.status_code == 200
        assert "X-RateLimit-Limit-Requests" in resp1.headers
        assert "X-RateLimit-Remaining-Requests" in resp1.headers
        assert resp1.headers["X-RateLimit-Remaining-Requests"] == "0"

        # 2nd request -> HTTP 429 Too Many Requests (Rate limit exhausted)
        resp2 = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert resp2.status_code == 429
        assert resp2.headers["X-RateLimit-Remaining"] == "0"
        assert "Retry-After" in resp2.headers
        assert resp2.json()["error"]["code"] == "REQUEST_RATE_LIMIT_EXCEEDED"

        # Check /v1/usage and /v1/costs endpoints
        res_usage = client.get("/v1/usage", headers=headers)
        assert res_usage.status_code == 200
        u_data = res_usage.json()
        assert u_data["request_count"] >= 1
        assert u_data["successful_request_count"] >= 1

        res_costs = client.get("/v1/costs", headers=headers)
        assert res_costs.status_code == 200
        c_data = res_costs.json()
        assert c_data["currency"] == "USD"
        assert Decimal(c_data["monthly_budget_usd"]) == Decimal("1.00000000")


async def test_readiness_failures(db_manager: DatabaseManager) -> None:
    app_broken_db = create_app(
        db_manager=DatabaseManager(database_url="postgresql+asyncpg://invalid:5432/db")
    )
    with TestClient(app_broken_db) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"
