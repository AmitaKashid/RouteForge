"""Feature policy domain data contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from routeforge.contracts.common import (
    Capability,
    FeatureId,
    GovernanceClassification,
    ModelId,
    PolicyId,
    PolicyVersion,
    ensure_utc,
)
from routeforge.contracts.verification import VerificationPolicy


class PolicyStatus(StrEnum):
    """Lifecycle status of a feature routing policy."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class RetryPolicy:
    """Policy rules governing same-provider model retries upon transient failures."""

    enabled: bool
    maximum_retries: int
    initial_backoff_ms: int

    def __post_init__(self) -> None:
        if not self.enabled and self.maximum_retries != 0:
            raise ValueError("maximum_retries must be 0 when retry policy is disabled.")
        if self.enabled and self.maximum_retries < 1:
            raise ValueError("maximum_retries must be at least 1 when retry policy is enabled.")
        if self.initial_backoff_ms < 0:
            raise ValueError("initial_backoff_ms must be non-negative.")


@dataclass(frozen=True)
class FallbackPolicy:
    """Policy rules governing fallback attempts upon provider failure."""

    enabled: bool
    maximum_fallback_attempts: int

    def __post_init__(self) -> None:
        if not self.enabled and self.maximum_fallback_attempts != 0:
            raise ValueError(
                "maximum_fallback_attempts must be 0 when fallback policy is disabled."
            )
        if self.enabled and self.maximum_fallback_attempts < 1:
            raise ValueError(
                "maximum_fallback_attempts must be at least 1 when fallback policy is enabled."
            )


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    """Policy rules governing passive provider-model circuit breakers."""

    enabled: bool = False
    failure_threshold: int = 3
    open_duration_seconds: int = 30

    def __post_init__(self) -> None:
        if self.enabled:
            if self.failure_threshold <= 0:
                raise ValueError(
                    "failure_threshold must be positive when circuit breaker policy is enabled."
                )
            if self.open_duration_seconds <= 0:
                raise ValueError(
                    "open_duration_seconds must be positive when circuit breaker policy is enabled."
                )


@dataclass(frozen=True)
class FeaturePolicy:
    """Immutable policy governing model selection for a given feature."""

    policy_id: PolicyId
    version: PolicyVersion
    feature_id: FeatureId
    status: PolicyStatus
    allowed_model_ids: tuple[ModelId, ...]
    required_capabilities: tuple[Capability, ...]
    minimum_quality: float
    maximum_latency_ms: int
    maximum_estimated_cost_usd: Decimal
    maximum_governance_classification: GovernanceClassification
    allow_degraded_providers: bool
    fallback_policy: FallbackPolicy
    created_at: datetime
    retry_policy: RetryPolicy = RetryPolicy(enabled=False, maximum_retries=0, initial_backoff_ms=0)
    circuit_breaker_policy: CircuitBreakerPolicy = CircuitBreakerPolicy(
        enabled=False, failure_threshold=3, open_duration_seconds=30
    )
    verification_policy: VerificationPolicy = field(default_factory=VerificationPolicy)
    pinned_model_id: ModelId | None = None

    def __post_init__(self) -> None:
        if not self.policy_id or not str(self.policy_id).strip():
            raise ValueError("policy_id cannot be empty.")
        if not self.version or not str(self.version).strip():
            raise ValueError("version cannot be empty.")
        if not self.feature_id or not str(self.feature_id).strip():
            raise ValueError("feature_id cannot be empty.")

        if not isinstance(self.allowed_model_ids, tuple):
            object.__setattr__(self, "allowed_model_ids", tuple(self.allowed_model_ids))
        if not isinstance(self.required_capabilities, tuple):
            object.__setattr__(self, "required_capabilities", tuple(self.required_capabilities))

        if not self.allowed_model_ids:
            raise ValueError("allowed_model_ids cannot be empty.")

        if not (0.0 <= self.minimum_quality <= 1.0):
            raise ValueError("minimum_quality must be between 0.0 and 1.0.")

        if self.maximum_latency_ms <= 0:
            raise ValueError("maximum_latency_ms must be positive.")

        if self.maximum_estimated_cost_usd < Decimal("0"):
            raise ValueError("maximum_estimated_cost_usd must not be negative.")

        if self.pinned_model_id is not None and self.pinned_model_id not in self.allowed_model_ids:
            raise ValueError(
                f"pinned_model_id ({self.pinned_model_id}) must be in allowed_model_ids."
            )

        ensure_utc(self.created_at)
