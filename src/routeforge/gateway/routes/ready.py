"""Application readiness health check endpoint."""

import redis.asyncio as aioredis
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from routeforge.gateway.schemas.base import GatewayBaseModel
from routeforge.storage.database import DatabaseManager
from routeforge.storage.ratelimit import RedisRateLimiter, get_redis_url

router = APIRouter(tags=["Health"])


class ReadinessResponse(GatewayBaseModel):
    """Readiness endpoint response schema."""

    status: str
    database: str
    redis: str = "connected"


@router.get("/readyz", response_model=ReadinessResponse)
async def ready_check(request: Request, response: Response) -> ReadinessResponse:
    """Verify application configuration loading, database connectivity, and Redis availability."""
    model_registry = getattr(request.app.state, "model_registry", None)
    policy_registry = getattr(request.app.state, "policy_registry", None)

    if model_registry is None or policy_registry is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="unhealthy", database="configuration_missing", redis="unknown"
        )

    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    own_db = False
    if db_manager is None:
        db_manager = DatabaseManager()
        own_db = True

    try:
        async with db_manager.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unhealthy", database="unavailable", redis="unknown")
    finally:
        if own_db and db_manager is not None:
            await db_manager.aclose()

    rate_limiter: RedisRateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is not None:
        try:
            redis_ok = await rate_limiter.ping()
            if not redis_ok:
                raise RuntimeError("Redis ping returned False")
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="unhealthy", database="connected", redis="unavailable")
    else:
        redis_client = aioredis.from_url(get_redis_url(), decode_responses=True)
        try:
            await redis_client.ping()
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="unhealthy", database="connected", redis="unavailable")
        finally:
            await redis_client.aclose()

    return ReadinessResponse(status="ready", database="connected", redis="connected")
