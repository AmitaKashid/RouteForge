"""Pydantic schemas for OpenAI-style chat completion wire requests and responses."""

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from routeforge.contracts import RoutingReason
from routeforge.gateway.schemas.base import GatewayBaseModel


class ApiChatRole(StrEnum):
    """Supported API chat turn roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ApiChatMessage(GatewayBaseModel):
    """Single chat turn in an incoming completion request."""

    role: ApiChatRole
    content: str = Field(description="Plain text chat content.")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Message content must be a non-empty, non-whitespace-only string.")
        return v


class ApiGovernanceClassification(StrEnum):
    """API-facing governance classification levels."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RouteForgeRequestOptions(GatewayBaseModel):
    """RouteForge-specific policy and routing constraint extensions."""

    feature_id: str = Field(description="Required feature ID for policy resolution.")
    minimum_quality: float | None = Field(
        default=None, description="Optional minimum quality score between 0.0 and 1.0."
    )
    maximum_latency_ms: int | None = Field(
        default=None, description="Optional maximum latency in milliseconds."
    )
    maximum_estimated_cost_usd: Decimal | None = Field(
        default=None, description="Optional maximum estimated cost in USD."
    )
    required_governance: ApiGovernanceClassification | None = Field(
        default=None, description="Optional data governance sensitivity classification."
    )
    allow_degraded_provider: bool = Field(
        default=False, description="Whether to permit degraded provider candidates."
    )

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("feature_id must be a nonblank string.")
        return v

    @field_validator("minimum_quality")
    @classmethod
    def validate_minimum_quality(cls, v: float | None) -> float | None:
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError("minimum_quality must be between 0.0 and 1.0 inclusive.")
        return v

    @field_validator("maximum_latency_ms")
    @classmethod
    def validate_maximum_latency(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("maximum_latency_ms must be a positive integer.")
        return v

    @field_validator("maximum_estimated_cost_usd")
    @classmethod
    def validate_maximum_cost(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < Decimal("0"):
            raise ValueError("maximum_estimated_cost_usd cannot be negative.")
        return v


class ResponseFormat(GatewayBaseModel):
    """Requested output format configuration."""

    type: Literal["text", "json_object"] = "text"


class ChatCompletionsRequest(GatewayBaseModel):
    """Incoming OpenAI-compatible chat completion wire request."""

    model: Literal["routeforge"] = Field(
        default="routeforge",
        description="Virtual gateway model identifier. Must be 'routeforge'.",
    )
    messages: list[ApiChatMessage] = Field(
        description="Non-empty list of conversation turn messages."
    )
    stream: Literal[False] = Field(
        default=False, description="Streaming option. Must be false in V1."
    )
    response_format: ResponseFormat | None = Field(
        default=None, description="Optional output format configuration."
    )
    routeforge: RouteForgeRequestOptions = Field(
        description="Required RouteForge extension options."
    )

    @field_validator("messages")
    @classmethod
    def validate_messages_non_empty(cls, v: list[ApiChatMessage]) -> list[ApiChatMessage]:
        if not v:
            raise ValueError("messages list cannot be empty.")
        return v


class ApiAssistantMessage(GatewayBaseModel):
    """Assistant turn message in completion response choice."""

    role: Literal["assistant"] = "assistant"
    content: str


class ApiChoice(GatewayBaseModel):
    """Individual completion choice item."""

    index: int = Field(ge=0, description="Choice index (zero-based).")
    message: ApiAssistantMessage
    finish_reason: Literal["stop", "length", "content_filter", "error"]


class ApiUsage(GatewayBaseModel):
    """Token usage metrics in response."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total_tokens(self) -> "ApiUsage":
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError(
                f"total_tokens ({self.total_tokens}) must equal prompt_tokens "
                f"({self.prompt_tokens}) plus completion_tokens ({self.completion_tokens})."
            )
        return self


class RouteForgeResponseMetadata(GatewayBaseModel):
    """RouteForge decision metadata attached to response."""

    request_id: str = Field(description="Unique request correlation ID.")
    provider: str = Field(description="Provider identifier of selected candidate.")
    policy_version: str = Field(description="Feature policy version applied.")
    routing_reason: RoutingReason = Field(description="Machine-readable routing decision reason.")
    fallback_used: bool = Field(
        default=False, description="Whether fallback execution was triggered."
    )
    retry_count: int = Field(default=0, description="Total same-model retry attempts executed.")

    @field_validator("request_id", "provider", "policy_version")
    @classmethod
    def validate_nonblank_meta(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Metadata string fields must be nonblank.")
        return v


class ChatCompletionsResponse(GatewayBaseModel):
    """OpenAI-compatible chat completion response payload."""

    id: str = Field(description="Completion response identifier.")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(ge=0, description="Unix epoch creation timestamp in seconds.")
    model: str = Field(description="Actual selected backend model ID.")
    choices: list[ApiChoice] = Field(description="List of completion choices.")
    usage: ApiUsage = Field(description="Token consumption breakdown.")
    routeforge: RouteForgeResponseMetadata = Field(description="RouteForge routing metadata.")

    @field_validator("id", "model")
    @classmethod
    def validate_nonblank_fields(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Response id and model fields must be nonblank strings.")
        return v

    @field_validator("choices")
    @classmethod
    def validate_choices_non_empty(cls, v: list[ApiChoice]) -> list[ApiChoice]:
        if not v:
            raise ValueError("choices list cannot be empty.")
        return v
