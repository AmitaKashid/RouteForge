"""Pure deterministic candidate eligibility evaluator."""

from routeforge.contracts import (
    CandidateEstimate,
    CandidateEvaluation,
    CandidateRejectionReason,
    Capability,
    ChatRequest,
    FeaturePolicy,
    GovernanceClassification,
    ModelDefinition,
    OutputFormat,
    ProviderOperatingState,
)

_GOVERNANCE_RANK: dict[GovernanceClassification, int] = {
    GovernanceClassification.PUBLIC: 0,
    GovernanceClassification.INTERNAL: 1,
    GovernanceClassification.CONFIDENTIAL: 2,
    GovernanceClassification.RESTRICTED: 3,
}


def evaluate_candidate(
    *,
    request: ChatRequest,
    policy: FeaturePolicy,
    model: ModelDefinition,
    estimate: CandidateEstimate,
    provider_state: ProviderOperatingState,
) -> CandidateEvaluation:
    """Evaluate whether a model is eligible for a request under a feature policy.

    Evaluates all rules deterministically and returns a CandidateEvaluation.
    """
    # Precondition validation
    if request.feature_id != policy.feature_id:
        raise ValueError(
            f"Request feature_id '{request.feature_id}' does not match "
            f"policy feature_id '{policy.feature_id}'."
        )

    rejection_reasons: list[CandidateRejectionReason] = []

    # Rule 1: Model Permission
    model_not_allowed = False
    if not model.enabled:
        model_not_allowed = True
    if model.model_id not in policy.allowed_model_ids:
        model_not_allowed = True
    if policy.pinned_model_id is not None and policy.pinned_model_id != model.model_id:
        model_not_allowed = True

    if model_not_allowed:
        rejection_reasons.append(CandidateRejectionReason.MODEL_NOT_ALLOWED)

    # Rule 2: Required Capabilities
    effective_capabilities = set(policy.required_capabilities)
    effective_capabilities.update(request.routing_constraints.required_capabilities)
    if request.output_format == OutputFormat.JSON:
        effective_capabilities.add(Capability.STRUCTURED_OUTPUT)

    model_capabilities = set(model.capabilities)
    if not effective_capabilities.issubset(model_capabilities):
        rejection_reasons.append(CandidateRejectionReason.CAPABILITY_MISMATCH)

    # Rule 3: Effective Quality Threshold
    if request.routing_constraints.minimum_quality is None:
        effective_min_quality = policy.minimum_quality
    else:
        effective_min_quality = max(
            policy.minimum_quality,
            request.routing_constraints.minimum_quality,
        )

    if estimate.predicted_quality < effective_min_quality:
        rejection_reasons.append(CandidateRejectionReason.QUALITY_BELOW_THRESHOLD)

    # Rule 4: Effective Latency Limit
    if request.routing_constraints.maximum_latency_ms is None:
        effective_max_latency = policy.maximum_latency_ms
    else:
        effective_max_latency = min(
            policy.maximum_latency_ms,
            request.routing_constraints.maximum_latency_ms,
        )

    if estimate.estimated_latency_ms > effective_max_latency:
        rejection_reasons.append(CandidateRejectionReason.LATENCY_ABOVE_TARGET)

    # Rule 5: Effective Cost Limit
    if request.routing_constraints.maximum_estimated_cost_usd is None:
        effective_max_cost = policy.maximum_estimated_cost_usd
    else:
        effective_max_cost = min(
            policy.maximum_estimated_cost_usd,
            request.routing_constraints.maximum_estimated_cost_usd,
        )

    if estimate.estimated_cost_usd > effective_max_cost:
        rejection_reasons.append(CandidateRejectionReason.COST_ABOVE_REQUEST_LIMIT)

    # Rule 6: Governance Compatibility
    effective_governance = (
        request.routing_constraints.required_governance
        if request.routing_constraints.required_governance is not None
        else GovernanceClassification.PUBLIC
    )

    governance_mismatch = False
    if effective_governance not in model.governance_allowed:
        governance_mismatch = True
    if (
        _GOVERNANCE_RANK[effective_governance]
        > _GOVERNANCE_RANK[policy.maximum_governance_classification]
    ):
        governance_mismatch = True

    if governance_mismatch:
        rejection_reasons.append(CandidateRejectionReason.GOVERNANCE_MISMATCH)

    # Rule 7: Provider Unavailable
    if provider_state == ProviderOperatingState.UNAVAILABLE:
        rejection_reasons.append(CandidateRejectionReason.PROVIDER_UNAVAILABLE)

    # Rule 8: Degraded Provider
    if provider_state == ProviderOperatingState.DEGRADED:
        allowed = (
            policy.allow_degraded_providers and request.routing_constraints.allow_degraded_provider
        )
        if not allowed:
            rejection_reasons.append(CandidateRejectionReason.DEGRADED_STATE_NOT_ALLOWED)

    eligible = len(rejection_reasons) == 0

    return CandidateEvaluation(
        model_id=model.model_id,
        provider_id=model.provider_id,
        eligible=eligible,
        rejection_reasons=tuple(rejection_reasons),
        estimate=estimate,
    )
