"""Health check endpoint route for RouteForge gateway."""

from fastapi import APIRouter

from routeforge import __version__
from routeforge.gateway.schemas.health import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["Health"])
def health_check() -> HealthResponse:
    """Return lightweight service health status."""
    return HealthResponse(
        status="ok",
        service="routeforge-gateway",
        version=__version__,
    )
