"""Gateway wire schemas for RouteForge HTTP API."""

from routeforge.gateway.schemas.base import GatewayBaseModel
from routeforge.gateway.schemas.chat import (
    ApiAssistantMessage,
    ApiChatMessage,
    ApiChatRole,
    ApiChoice,
    ApiGovernanceClassification,
    ApiUsage,
    ChatCompletionsRequest,
    ChatCompletionsResponse,
    ResponseFormat,
    RouteForgeRequestOptions,
    RouteForgeResponseMetadata,
)
from routeforge.gateway.schemas.errors import (
    ApiErrorDetail,
    ApiErrorMetadata,
    ApiErrorResponse,
)
from routeforge.gateway.schemas.health import HealthResponse

__all__ = [
    "ApiAssistantMessage",
    "ApiChatMessage",
    "ApiChatRole",
    "ApiChoice",
    "ApiErrorDetail",
    "ApiErrorMetadata",
    "ApiErrorResponse",
    "ApiGovernanceClassification",
    "ApiUsage",
    "ChatCompletionsRequest",
    "ChatCompletionsResponse",
    "GatewayBaseModel",
    "HealthResponse",
    "ResponseFormat",
    "RouteForgeRequestOptions",
    "RouteForgeResponseMetadata",
]
