from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from routeforge.contracts.common import AttemptId, ModelId, ProviderId, RequestId, ensure_utc
from routeforge.contracts.errors import ErrorCode
from routeforge.contracts.inference import (
    ChatMessage,
    FinishReason,
    OutputFormat,
    TokenUsage,
)


class ExecutionAttemptKind(StrEnum):
    """Kind of inference execution attempt."""

    PRIMARY = "PRIMARY"
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"


class ExecutionAttemptOutcome(StrEnum):
    """Outcome status of an execution attempt."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExecutionAttempt:
    """Immutable audit record of a single provider execution attempt."""

    attempt_number: int
    attempt_id: AttemptId
    attempt_kind: ExecutionAttemptKind
    model_id: ModelId
    provider_id: ProviderId
    outcome: ExecutionAttemptOutcome
    estimated_cost_usd: Decimal
    started_at: datetime
    completed_at: datetime
    error_code: ErrorCode | None = None
    retryable: bool | None = None
    provider_status_code: int | None = None
    latency_ms: int | None = None
    actual_cost_usd: Decimal | None = None
    is_half_open_probe: bool = False

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1.")
        if not self.attempt_id or not str(self.attempt_id).strip():
            raise ValueError("attempt_id cannot be empty.")
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("provider_id cannot be empty.")
        if self.estimated_cost_usd < Decimal("0"):
            raise ValueError("estimated_cost_usd must not be negative.")
        if self.actual_cost_usd is not None and self.actual_cost_usd < Decimal("0"):
            raise ValueError("actual_cost_usd must not be negative.")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative.")
        ensure_utc(self.started_at)
        ensure_utc(self.completed_at)


@dataclass(frozen=True)
class ProviderRequest:
    """Normalized payload sent to a provider adapter."""

    request_id: RequestId
    attempt_id: AttemptId
    model_id: ModelId
    messages: tuple[ChatMessage, ...]
    output_format: OutputFormat
    timeout_ms: int
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            raise ValueError("request_id cannot be empty.")
        if not self.attempt_id or not str(self.attempt_id).strip():
            raise ValueError("attempt_id cannot be empty.")
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty.")

        if not isinstance(self.messages, tuple):
            object.__setattr__(self, "messages", tuple(self.messages))

        if not self.messages:
            raise ValueError("ProviderRequest messages cannot be empty.")

        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive.")


@dataclass(frozen=True)
class ProviderResponse:
    """Normalized result returned from a provider adapter."""

    request_id: RequestId
    attempt_id: AttemptId
    model_id: ModelId
    provider_id: ProviderId
    content: str
    finish_reason: FinishReason
    usage: TokenUsage
    latency_ms: int
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            raise ValueError("request_id cannot be empty.")
        if not self.attempt_id or not str(self.attempt_id).strip():
            raise ValueError("attempt_id cannot be empty.")
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("provider_id cannot be empty.")

        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative.")


@dataclass(frozen=True)
class ProviderError:
    """Standardized provider execution error envelope."""

    request_id: RequestId
    attempt_id: AttemptId
    provider_id: ProviderId
    model_id: ModelId
    code: ErrorCode
    message: str
    retryable: bool
    provider_status_code: int | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            raise ValueError("request_id cannot be empty.")
        if not self.attempt_id or not str(self.attempt_id).strip():
            raise ValueError("attempt_id cannot be empty.")
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("provider_id cannot be empty.")
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.message or not self.message.strip():
            raise ValueError("ProviderError message cannot be empty.")
