"""Normalized text-only chat request and response contracts."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from routeforge.contracts.common import (
    Capability,
    FeatureId,
    GovernanceClassification,
    ModelId,
    ProviderId,
    RequestId,
    TeamId,
    ensure_utc,
)


class ChatRole(StrEnum):
    """Supported roles in chat conversation turns."""

    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"


@dataclass(frozen=True)
class ChatMessage:
    """Individual turn in a chat interaction."""

    role: ChatRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("ChatMessage content must be a non-empty string.")


class OutputFormat(StrEnum):
    """Requested output format."""

    TEXT = "TEXT"
    JSON = "JSON"


@dataclass(frozen=True)
class RoutingConstraints:
    """Constraints governing model candidate eligibility for a request."""

    minimum_quality: float | None = None
    maximum_latency_ms: int | None = None
    maximum_estimated_cost_usd: Decimal | None = None
    required_capabilities: tuple[Capability, ...] = ()
    required_governance: GovernanceClassification | None = None
    allow_degraded_provider: bool = False

    def __post_init__(self) -> None:
        if self.minimum_quality is not None and not (0.0 <= self.minimum_quality <= 1.0):
            raise ValueError("minimum_quality must be between 0.0 and 1.0.")
        if self.maximum_latency_ms is not None and self.maximum_latency_ms <= 0:
            raise ValueError("maximum_latency_ms must be positive.")
        if (
            self.maximum_estimated_cost_usd is not None
            and self.maximum_estimated_cost_usd < Decimal("0")
        ):
            raise ValueError("maximum_estimated_cost_usd must not be negative.")
        if not isinstance(self.required_capabilities, tuple):
            object.__setattr__(self, "required_capabilities", tuple(self.required_capabilities))


@dataclass(frozen=True)
class ChatRequest:
    """Normalized chat completion request."""

    request_id: RequestId
    team_id: TeamId
    feature_id: FeatureId
    messages: tuple[ChatMessage, ...]
    output_format: OutputFormat
    routing_constraints: RoutingConstraints
    created_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            raise ValueError("request_id cannot be empty.")
        if not self.team_id or not str(self.team_id).strip():
            raise ValueError("team_id cannot be empty.")
        if not self.feature_id or not str(self.feature_id).strip():
            raise ValueError("feature_id cannot be empty.")

        if not isinstance(self.messages, tuple):
            object.__setattr__(self, "messages", tuple(self.messages))

        if not self.messages:
            raise ValueError("ChatRequest messages list cannot be empty.")

        if self.messages[-1].role != ChatRole.USER:
            raise ValueError("The final message in ChatRequest must have role USER.")

        ensure_utc(self.created_at)

        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class UsageSource(StrEnum):
    """Provenance of token usage counts."""

    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    LOCALLY_ESTIMATED = "LOCALLY_ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class TokenUsage:
    """Token consumption record."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: UsageSource

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0 or self.total_tokens < 0:
            raise ValueError("Token counts cannot be negative.")
        if self.source != UsageSource.UNAVAILABLE:
            if self.total_tokens != self.input_tokens + self.output_tokens:
                raise ValueError(
                    f"total_tokens ({self.total_tokens}) must equal "
                    f"input_tokens ({self.input_tokens}) + output_tokens ({self.output_tokens})."
                )

    @classmethod
    def unavailable(cls) -> "TokenUsage":
        """Factory for unavailable usage metrics."""
        return cls(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            source=UsageSource.UNAVAILABLE,
        )


class FinishReason(StrEnum):
    """Reason execution finished."""

    STOP = "STOP"
    LENGTH = "LENGTH"
    CONTENT_FILTER = "CONTENT_FILTER"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ChatResponse:
    """Normalized chat completion response."""

    request_id: RequestId
    response_id: str
    model_id: ModelId
    provider_id: ProviderId
    content: str
    finish_reason: FinishReason
    usage: TokenUsage
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            raise ValueError("request_id cannot be empty.")
        if not self.response_id or not self.response_id.strip():
            raise ValueError("response_id cannot be empty.")
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("provider_id cannot be empty.")

        ensure_utc(self.created_at)
