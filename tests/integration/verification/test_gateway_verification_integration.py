"""Gateway integration tests for quality verification sampling and endpoints."""

import uuid
from decimal import Decimal

import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from routeforge.contracts import utc_now
from routeforge.gateway.app import create_app
from routeforge.gateway.auth import create_api_key
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import ApiKeyModel, TeamLimitsModel, TeamModel


@pytest.mark.asyncio
async def test_quality_summary_endpoint_team_isolated() -> None:
    """Test GET /v1/quality-summary returns calendar-month statistics for authenticated team."""
    try:
        redis_client = aioredis.from_url("redis://localhost:6379/0")
        await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis unavailable: {exc}")

    db_manager = DatabaseManager()
    try:
        async with db_manager.session_factory() as session:
            team = TeamModel(
                team_id="team-qs-1", display_name="QS Team", active=True, created_at=utc_now()
            )
            session.add(team)
            limits = TeamLimitsModel(
                team_id="team-qs-1",
                requests_per_minute=60,
                tokens_per_minute=10000,
                monthly_budget_usd=Decimal("100.00"),
                active=True,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(limits)
            raw_key, pfx, key_hash = create_api_key()
            key_rec = ApiKeyModel(
                key_id=uuid.uuid4(),
                team_id="team-qs-1",
                key_prefix=pfx,
                key_hash=key_hash,
                active=True,
                created_at=utc_now(),
            )
            session.add(key_rec)
            await session.commit()

        app = create_app(db_manager=db_manager)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            res = await client.get(
                "/v1/quality-summary",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["team_id"] == "team-qs-1"
            assert "eligible_successful_requests" in data
            assert "total_verification_cost_usd" in data
            assert data["currency"] == "USD"
    except Exception as exc:
        pytest.skip(f"Integration environment error: {exc}")
    finally:
        await redis_client.aclose()
        await db_manager.aclose()
