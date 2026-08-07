"""Pydantic schema for health endpoint response."""

from typing import Literal

from pydantic import Field

from routeforge.gateway.schemas.base import GatewayBaseModel


class HealthResponse(GatewayBaseModel):
    """Response model for /healthz endpoint."""

    status: Literal["ok"] = "ok"
    service: Literal["routeforge-gateway"] = "routeforge-gateway"
    version: str = Field(description="Package version of the running gateway.")
