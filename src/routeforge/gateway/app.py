"""FastAPI application factory for RouteForge gateway."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from routeforge import __version__
from routeforge.gateway.routes.chat import router as chat_router
from routeforge.gateway.routes.costs import router as costs_router
from routeforge.gateway.routes.decisions import router as decisions_router
from routeforge.gateway.routes.health import router as health_router
from routeforge.gateway.routes.quality_summary import router as quality_summary_router
from routeforge.gateway.routes.ready import router as ready_router
from routeforge.gateway.routes.usage import router as usage_router
from routeforge.gateway.runtime import GatewayRuntimeManager, GatewayRuntimeSettings
from routeforge.providers import LLMProvider
from routeforge.registries import (
    FeaturePolicyRegistry,
    ModelRegistry,
    load_registry_snapshot,
)
from routeforge.storage.database import DatabaseManager
from routeforge.storage.ratelimit import RedisRateLimiter


def create_app(
    model_registry: ModelRegistry | None = None,
    policy_registry: FeaturePolicyRegistry | None = None,
    provider: LLMProvider | None = None,
    runtime_settings: GatewayRuntimeSettings | None = None,
    db_manager: DatabaseManager | None = None,
    rate_limiter: RedisRateLimiter | None = None,
    circuit_breaker: Any = None,
) -> FastAPI:
    """Create and configure a new FastAPI application instance for RouteForge gateway."""

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
        yield
        mgr: DatabaseManager | None = getattr(app_instance.state, "db_manager", None)
        if mgr is not None:
            await mgr.aclose()
        limiter: RedisRateLimiter | None = getattr(app_instance.state, "rate_limiter", None)
        if limiter is not None:
            await limiter.aclose()

    app = FastAPI(
        title="RouteForge",
        description="Quality-aware multi-provider LLM gateway API.",
        version=__version__,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    if model_registry is None or policy_registry is None:
        models_dir = Path("config/models")
        policies_dir = Path("config/policies")
        snapshot = load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
        model_registry = model_registry or snapshot.models
        policy_registry = policy_registry or snapshot.policies

    runtime_manager = GatewayRuntimeManager(settings=runtime_settings)

    if provider is not None:
        provider_id_val = getattr(provider, "provider_id", "mock")
        runtime_manager.register_provider(str(provider_id_val), provider)
    else:
        provider = runtime_manager.get_provider(
            "ollama" if runtime_manager.settings.provider_mode == "ollama" else "mock"
        )

    if circuit_breaker is None:
        from routeforge.resilience import RedisCircuitBreaker

        redis_client = getattr(rate_limiter, "redis", None)
        circuit_breaker = RedisCircuitBreaker(redis_client=redis_client)

    app.state.model_registry = model_registry
    app.state.policy_registry = policy_registry
    app.state.provider = provider
    app.state.runtime_manager = runtime_manager
    app.state.profile_registry = runtime_manager.profile_registry
    app.state.db_manager = db_manager
    app.state.rate_limiter = rate_limiter
    app.state.circuit_breaker = circuit_breaker

    app.include_router(health_router)
    app.include_router(ready_router)
    app.include_router(chat_router)
    app.include_router(decisions_router)
    app.include_router(usage_router)
    app.include_router(costs_router)
    app.include_router(quality_summary_router)

    return app
