"""Deterministic candidate selection and request routing."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from routeforge.contracts import (
    CandidateEstimate,
    CandidateEvaluation,
    ChatRequest,
    FeaturePolicy,
    ModelDefinition,
    ProviderOperatingState,
    RoutingDecision,
    RoutingReason,
)
from routeforge.contracts.common import ensure_utc
from routeforge.routing.eligibility import evaluate_candidate


@dataclass(frozen=True, slots=True)
class RoutingCandidate:
    """Grouped candidate model input for eligibility evaluation and routing."""

    model: ModelDefinition
    estimate: CandidateEstimate
    provider_state: ProviderOperatingState


def route_request(
    *,
    request: ChatRequest,
    policy: FeaturePolicy,
    candidates: Iterable[RoutingCandidate],
    decided_at: datetime,
) -> RoutingDecision:
    """Route a request deterministically to the lowest-cost eligible candidate model.

    Evaluates all candidates using evaluate_candidate, sorts candidates deterministically
    by model_id, selects the lowest-cost eligible candidate, and returns a RoutingDecision.
    """
    ensure_utc(decided_at)

    if request.feature_id != policy.feature_id:
        raise ValueError(
            f"Request feature_id '{request.feature_id}' does not match "
            f"policy feature_id '{policy.feature_id}'."
        )

    candidate_list = list(candidates)
    if not candidate_list:
        raise ValueError("Candidate collection cannot be empty.")

    seen_model_ids: set[str] = set()
    for c in candidate_list:
        model_id_str = str(c.model.model_id)
        if model_id_str in seen_model_ids:
            raise ValueError(f"Duplicate model_id '{c.model.model_id}' found in candidates.")
        seen_model_ids.add(model_id_str)

    # Sort candidates by model_id ascending for deterministic evaluation order
    sorted_candidates = sorted(candidate_list, key=lambda c: str(c.model.model_id))

    evaluations: list[CandidateEvaluation] = []
    eligible_pairs: list[tuple[CandidateEvaluation, RoutingCandidate]] = []

    for c in sorted_candidates:
        eval_result = evaluate_candidate(
            request=request,
            policy=policy,
            model=c.model,
            estimate=c.estimate,
            provider_state=c.provider_state,
        )
        evaluations.append(eval_result)
        if eval_result.eligible:
            eligible_pairs.append((eval_result, c))

    evaluations_tuple = tuple(evaluations)

    if not eligible_pairs:
        return RoutingDecision(
            request_id=request.request_id,
            team_id=request.team_id,
            feature_id=request.feature_id,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            candidates=evaluations_tuple,
            routing_reason=RoutingReason.NO_ELIGIBLE_MODEL,
            decided_at=decided_at,
            selected_model_id=None,
            selected_provider_id=None,
            classifier_version=None,
            fallback_used=False,
            retry_count=0,
        )

    # Select candidate with lowest estimated_cost_usd ascending, tie-breaking by model_id ascending
    _, selected_candidate = min(
        eligible_pairs,
        key=lambda pair: (pair[1].estimate.estimated_cost_usd, str(pair[1].model.model_id)),
    )

    if (
        policy.pinned_model_id is not None
        and selected_candidate.model.model_id == policy.pinned_model_id
    ):
        routing_reason = RoutingReason.POLICY_PINNED_MODEL
    elif selected_candidate.provider_state == ProviderOperatingState.DEGRADED:
        routing_reason = RoutingReason.DEGRADED_MODE_SELECTION
    else:
        routing_reason = RoutingReason.CHEAPEST_ELIGIBLE_MODEL

    return RoutingDecision(
        request_id=request.request_id,
        team_id=request.team_id,
        feature_id=request.feature_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidates=evaluations_tuple,
        routing_reason=routing_reason,
        decided_at=decided_at,
        selected_model_id=selected_candidate.model.model_id,
        selected_provider_id=selected_candidate.model.provider_id,
        classifier_version=None,
        fallback_used=False,
        retry_count=0,
    )
