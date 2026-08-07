"""Domain error codes, candidate rejection reasons, and routing reason codes."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from routeforge.contracts.common import RequestId


class CandidateRejectionReason(StrEnum):
    """Candidate model rejection reason codes."""

    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    QUALITY_BELOW_THRESHOLD = "QUALITY_BELOW_THRESHOLD"
    LATENCY_ABOVE_TARGET = "LATENCY_ABOVE_TARGET"
    COST_ABOVE_REQUEST_LIMIT = "COST_ABOVE_REQUEST_LIMIT"
    GOVERNANCE_MISMATCH = "GOVERNANCE_MISMATCH"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DEGRADED_STATE_NOT_ALLOWED = "DEGRADED_STATE_NOT_ALLOWED"


class RoutingReason(StrEnum):
    """Reason codes for final routing decisions."""

    CHEAPEST_ELIGIBLE_MODEL = "CHEAPEST_ELIGIBLE_MODEL"
    POLICY_PINNED_MODEL = "POLICY_PINNED_MODEL"
    DEGRADED_MODE_SELECTION = "DEGRADED_MODE_SELECTION"
    FALLBACK_AFTER_TRANSIENT_FAILURE = "FALLBACK_AFTER_TRANSIENT_FAILURE"
    NO_ELIGIBLE_MODEL = "NO_ELIGIBLE_MODEL"


class ErrorCode(StrEnum):
    """Domain-level error codes."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN_FEATURE = "UNKNOWN_FEATURE"
    UNKNOWN_POLICY = "UNKNOWN_POLICY"
    UNKNOWN_MODEL = "UNKNOWN_MODEL"
    NO_ELIGIBLE_MODEL = "NO_ELIGIBLE_MODEL"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_CONNECTION_ERROR = "PROVIDER_CONNECTION_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_AUTHENTICATION_FAILED = "PROVIDER_AUTHENTICATION_FAILED"
    PROVIDER_INVALID_REQUEST = "PROVIDER_INVALID_REQUEST"
    PROVIDER_UNSUPPORTED_MODEL = "PROVIDER_UNSUPPORTED_MODEL"
    PROVIDER_MALFORMED_RESPONSE = "PROVIDER_MALFORMED_RESPONSE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    MONTHLY_BUDGET_EXCEEDED = "MONTHLY_BUDGET_EXCEEDED"
    FALLBACK_BUDGET_EXCEEDED = "FALLBACK_BUDGET_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class RouteForgeError:
    """Immutable domain error representation."""

    code: ErrorCode
    message: str
    retryable: bool
    request_id: RequestId | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message or not self.message.strip():
            raise ValueError("RouteForgeError message cannot be empty or whitespace-only.")
        if not isinstance(self.details, MappingProxyType):
            object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
