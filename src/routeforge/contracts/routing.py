"""Routing decision and candidate evaluation contracts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from routeforge.contracts.common import (
    FeatureId,
    ModelId,
    PolicyId,
    PolicyVersion,
    ProviderId,
    RequestId,
    TeamId,
    ensure_utc,
)
from routeforge.contracts.errors import CandidateRejectionReason, RoutingReason


@dataclass(frozen=True)
class EstimateProvenance:
    """Provenance tracking for candidate metrics estimates."""

    source: str
    version: str

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError("source cannot be empty or whitespace-only.")
        if not self.version or not self.version.strip():
            raise ValueError("version cannot be empty or whitespace-only.")


@dataclass(frozen=True)
class CandidateEstimate:
    """Predicted metrics for a candidate model/provider pair."""

    predicted_quality: float
    estimated_latency_ms: int
    estimated_cost_usd: Decimal
    quality_provenance: EstimateProvenance
    latency_provenance: EstimateProvenance
    cost_provenance: EstimateProvenance

    def __post_init__(self) -> None:
        if not (0.0 <= self.predicted_quality <= 1.0):
            raise ValueError("predicted_quality must be between 0.0 and 1.0.")
        if self.estimated_latency_ms < 0:
            raise ValueError("estimated_latency_ms must not be negative.")
        if self.estimated_cost_usd < Decimal("0"):
            raise ValueError("estimated_cost_usd must not be negative.")


@dataclass(frozen=True)
class CandidateEvaluation:
    """Evaluation result for a model candidate against routing constraints."""

    model_id: ModelId
    provider_id: ProviderId
    eligible: bool
    rejection_reasons: tuple[CandidateRejectionReason, ...]
    estimate: CandidateEstimate

    def __post_init__(self) -> None:
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("provider_id cannot be empty.")

        if not isinstance(self.rejection_reasons, tuple):
            object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))

        if self.eligible and self.rejection_reasons:
            raise ValueError("An eligible candidate must not have rejection reasons.")
        if not self.eligible and not self.rejection_reasons:
            raise ValueError("An ineligible candidate must have at least one rejection reason.")


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable final decision recorded by the router."""

    request_id: RequestId
    team_id: TeamId
    feature_id: FeatureId
    policy_id: PolicyId
    policy_version: PolicyVersion
    candidates: tuple[CandidateEvaluation, ...]
    routing_reason: RoutingReason
    decided_at: datetime
    selected_model_id: ModelId | None = None
    selected_provider_id: ProviderId | None = None
    classifier_version: str | None = None
    fallback_used: bool = False
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            raise ValueError("request_id cannot be empty.")
        if not self.team_id or not str(self.team_id).strip():
            raise ValueError("team_id cannot be empty.")
        if not self.feature_id or not str(self.feature_id).strip():
            raise ValueError("feature_id cannot be empty.")
        if not self.policy_id or not str(self.policy_id).strip():
            raise ValueError("policy_id cannot be empty.")
        if not self.policy_version or not str(self.policy_version).strip():
            raise ValueError("policy_version cannot be empty.")

        if self.retry_count < 0:
            raise ValueError("retry_count must not be negative.")

        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))

        if not self.candidates:
            raise ValueError("candidates cannot be empty in RoutingDecision.")

        ensure_utc(self.decided_at)

        # Selected model and provider must be both present or both absent
        if (self.selected_model_id is None) != (self.selected_provider_id is None):
            raise ValueError(
                "selected_model_id and selected_provider_id must both be present or both absent."
            )

        if self.routing_reason == RoutingReason.NO_ELIGIBLE_MODEL:
            if self.selected_model_id is not None or self.selected_provider_id is not None:
                raise ValueError(
                    "RoutingReason.NO_ELIGIBLE_MODEL requires selected_model_id and "
                    "selected_provider_id to be None."
                )
        else:
            if self.selected_model_id is None or self.selected_provider_id is None:
                raise ValueError(
                    f"Successful routing reason {self.routing_reason} requires "
                    "selected_model_id and selected_provider_id."
                )

        if self.selected_model_id is not None and self.selected_provider_id is not None:
            # Find matching candidate
            matching_candidates = [
                c
                for c in self.candidates
                if c.model_id == self.selected_model_id
                and c.provider_id == self.selected_provider_id
            ]
            if not matching_candidates:
                raise ValueError(
                    f"Selected model/provider ({self.selected_model_id}/"
                    f"{self.selected_provider_id}) is not present in candidates list."
                )
            selected_cand = matching_candidates[0]
            if not selected_cand.eligible:
                raise ValueError(
                    f"Selected model/provider ({self.selected_model_id}/"
                    f"{self.selected_provider_id}) must be an eligible candidate."
                )
