"""Unit tests for evaluate_candidate routing function."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts import (
    CandidateEstimate,
    CandidateRejectionReason,
    Capability,
    ChatMessage,
    ChatRequest,
    ChatRole,
    EstimateProvenance,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    PolicyId,
    PolicyStatus,
    PolicyVersion,
    ProviderId,
    ProviderOperatingState,
    QualityProfile,
    RequestId,
    RoutingConstraints,
    TeamId,
)
from routeforge.routing import evaluate_candidate


def create_test_model(
    model_id_str: str = "m1",
    provider_id_str: str = "mock",
    enabled: bool = True,
    capabilities: tuple[Capability, ...] = (Capability.TEXT_CHAT,),
    governance_allowed: tuple[GovernanceClassification, ...] = (
        GovernanceClassification.PUBLIC,
        GovernanceClassification.INTERNAL,
    ),
) -> ModelDefinition:
    qp = QualityProfile(task_type="general", predicted_quality=0.8, source="e", version="v1")
    return ModelDefinition(
        model_id=ModelId(model_id_str),
        provider_id=ProviderId(provider_id_str),
        display_name="Test Model",
        capabilities=capabilities,
        governance_allowed=governance_allowed,
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.10"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.20"),
        estimated_latency_ms=100,
        quality_profiles=(qp,),
        enabled=enabled,
        configuration_version="v1",
    )


def create_test_policy(
    policy_id_str: str = "pol_1",
    version_str: str = "v1",
    feature_id_str: str = "feat_1",
    status: PolicyStatus = PolicyStatus.ACTIVE,
    allowed_model_ids: tuple[ModelId, ...] = (ModelId("m1"), ModelId("m2")),
    required_capabilities: tuple[Capability, ...] = (Capability.TEXT_CHAT,),
    minimum_quality: float = 0.7,
    maximum_latency_ms: int = 500,
    maximum_estimated_cost_usd: Decimal = Decimal("1.0"),
    maximum_governance: GovernanceClassification = GovernanceClassification.INTERNAL,
    allow_degraded: bool = True,
    pinned_model_id: ModelId | None = None,
) -> FeaturePolicy:
    return FeaturePolicy(
        policy_id=PolicyId(policy_id_str),
        version=PolicyVersion(version_str),
        feature_id=FeatureId(feature_id_str),
        status=status,
        allowed_model_ids=allowed_model_ids,
        required_capabilities=required_capabilities,
        minimum_quality=minimum_quality,
        maximum_latency_ms=maximum_latency_ms,
        maximum_estimated_cost_usd=maximum_estimated_cost_usd,
        maximum_governance_classification=maximum_governance,
        allow_degraded_providers=allow_degraded,
        fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
        created_at=datetime.now(UTC),
        pinned_model_id=pinned_model_id,
    )


def create_test_request(
    request_id_str: str = "req_1",
    feature_id_str: str = "feat_1",
    output_format: OutputFormat = OutputFormat.TEXT,
    constraints: RoutingConstraints | None = None,
) -> ChatRequest:
    return ChatRequest(
        request_id=RequestId(request_id_str),
        team_id=TeamId("team_1"),
        feature_id=FeatureId(feature_id_str),
        messages=(ChatMessage(role=ChatRole.USER, content="Hello"),),
        output_format=output_format,
        routing_constraints=constraints if constraints is not None else RoutingConstraints(),
        created_at=datetime.now(UTC),
    )


def create_test_estimate(
    quality: float = 0.8,
    latency_ms: int = 200,
    cost_usd: Decimal = Decimal("0.5"),
) -> CandidateEstimate:
    prov = EstimateProvenance(source="test", version="v1")
    return CandidateEstimate(
        predicted_quality=quality,
        estimated_latency_ms=latency_ms,
        estimated_cost_usd=cost_usd,
        quality_provenance=prov,
        latency_provenance=prov,
        cost_provenance=prov,
    )


def test_valid_candidate_eligible() -> None:
    model = create_test_model()
    policy = create_test_policy()
    request = create_test_request()
    estimate = create_test_estimate()

    result = evaluate_candidate(
        request=request,
        policy=policy,
        model=model,
        estimate=estimate,
        provider_state=ProviderOperatingState.HEALTHY,
    )

    assert result.eligible is True
    assert result.rejection_reasons == ()
    assert result.model_id == model.model_id
    assert result.provider_id == model.provider_id
    assert result.estimate == estimate


def test_model_permission_rule() -> None:
    m_disabled = create_test_model(enabled=False)
    p = create_test_policy()
    r = create_test_request()
    e = create_test_estimate()

    res1 = evaluate_candidate(
        request=r,
        policy=p,
        model=m_disabled,
        estimate=e,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res1.eligible is False
    assert CandidateRejectionReason.MODEL_NOT_ALLOWED in res1.rejection_reasons

    m_unallowed = create_test_model(model_id_str="unallowed_model")
    res2 = evaluate_candidate(
        request=r,
        policy=p,
        model=m_unallowed,
        estimate=e,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res2.eligible is False
    assert CandidateRejectionReason.MODEL_NOT_ALLOWED in res2.rejection_reasons

    p_pinned = create_test_policy(pinned_model_id=ModelId("m2"))
    m1 = create_test_model(model_id_str="m1")
    m2 = create_test_model(model_id_str="m2")

    res_unpinned = evaluate_candidate(
        request=r,
        policy=p_pinned,
        model=m1,
        estimate=e,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_unpinned.eligible is False
    assert CandidateRejectionReason.MODEL_NOT_ALLOWED in res_unpinned.rejection_reasons

    res_pinned = evaluate_candidate(
        request=r,
        policy=p_pinned,
        model=m2,
        estimate=e,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_pinned.eligible is True

    p_draft = create_test_policy(status=PolicyStatus.DRAFT)
    res_draft = evaluate_candidate(
        request=r,
        policy=p_draft,
        model=m1,
        estimate=e,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_draft.eligible is True


def test_capability_rule() -> None:
    m = create_test_model(capabilities=(Capability.TEXT_CHAT,))
    p = create_test_policy(required_capabilities=(Capability.TEXT_CHAT,))
    e = create_test_estimate()

    r_json = create_test_request(output_format=OutputFormat.JSON)
    res_json = evaluate_candidate(
        request=r_json, policy=p, model=m, estimate=e, provider_state=ProviderOperatingState.HEALTHY
    )
    assert res_json.eligible is False
    assert CandidateRejectionReason.CAPABILITY_MISMATCH in res_json.rejection_reasons

    m_struct = create_test_model(capabilities=(Capability.TEXT_CHAT, Capability.STRUCTURED_OUTPUT))
    res_struct = evaluate_candidate(
        request=r_json,
        policy=p,
        model=m_struct,
        estimate=e,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_struct.eligible is True


def test_quality_rule() -> None:
    m = create_test_model()
    p = create_test_policy(minimum_quality=0.80)
    e_low = create_test_estimate(quality=0.79)
    e_exact = create_test_estimate(quality=0.80)

    r = create_test_request()
    res_low = evaluate_candidate(
        request=r, policy=p, model=m, estimate=e_low, provider_state=ProviderOperatingState.HEALTHY
    )
    assert CandidateRejectionReason.QUALITY_BELOW_THRESHOLD in res_low.rejection_reasons

    res_exact = evaluate_candidate(
        request=r,
        policy=p,
        model=m,
        estimate=e_exact,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_exact.eligible is True

    r_strict = create_test_request(constraints=RoutingConstraints(minimum_quality=0.85))
    res_strict = evaluate_candidate(
        request=r_strict,
        policy=p,
        model=m,
        estimate=e_exact,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert CandidateRejectionReason.QUALITY_BELOW_THRESHOLD in res_strict.rejection_reasons


def test_latency_rule() -> None:
    m = create_test_model()
    p = create_test_policy(maximum_latency_ms=300)
    e_high = create_test_estimate(latency_ms=301)
    e_exact = create_test_estimate(latency_ms=300)

    r = create_test_request()
    res_high = evaluate_candidate(
        request=r, policy=p, model=m, estimate=e_high, provider_state=ProviderOperatingState.HEALTHY
    )
    assert CandidateRejectionReason.LATENCY_ABOVE_TARGET in res_high.rejection_reasons

    res_exact = evaluate_candidate(
        request=r,
        policy=p,
        model=m,
        estimate=e_exact,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_exact.eligible is True

    # Request maximum latency stricter than policy
    r_strict = create_test_request(constraints=RoutingConstraints(maximum_latency_ms=250))
    res_strict = evaluate_candidate(
        request=r_strict,
        policy=p,
        model=m,
        estimate=e_exact,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert CandidateRejectionReason.LATENCY_ABOVE_TARGET in res_strict.rejection_reasons


def test_cost_rule() -> None:
    m = create_test_model()
    p = create_test_policy(maximum_estimated_cost_usd=Decimal("0.50"))
    e_high = create_test_estimate(cost_usd=Decimal("0.51"))
    e_exact = create_test_estimate(cost_usd=Decimal("0.50"))

    r = create_test_request()
    res_high = evaluate_candidate(
        request=r, policy=p, model=m, estimate=e_high, provider_state=ProviderOperatingState.HEALTHY
    )
    assert CandidateRejectionReason.COST_ABOVE_REQUEST_LIMIT in res_high.rejection_reasons

    res_exact = evaluate_candidate(
        request=r,
        policy=p,
        model=m,
        estimate=e_exact,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert res_exact.eligible is True

    # Request maximum cost stricter than policy
    r_strict = create_test_request(
        constraints=RoutingConstraints(maximum_estimated_cost_usd=Decimal("0.40"))
    )
    res_strict = evaluate_candidate(
        request=r_strict,
        policy=p,
        model=m,
        estimate=e_exact,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert CandidateRejectionReason.COST_ABOVE_REQUEST_LIMIT in res_strict.rejection_reasons


def test_governance_rule() -> None:
    m_public = create_test_model(governance_allowed=(GovernanceClassification.PUBLIC,))
    p_internal = create_test_policy(maximum_governance=GovernanceClassification.INTERNAL)

    r_confidential = create_test_request(
        constraints=RoutingConstraints(required_governance=GovernanceClassification.CONFIDENTIAL)
    )
    res_gov = evaluate_candidate(
        request=r_confidential,
        policy=p_internal,
        model=m_public,
        estimate=create_test_estimate(),
        provider_state=ProviderOperatingState.HEALTHY,
    )
    assert CandidateRejectionReason.GOVERNANCE_MISMATCH in res_gov.rejection_reasons
    assert res_gov.rejection_reasons.count(CandidateRejectionReason.GOVERNANCE_MISMATCH) == 1


def test_provider_state_rule() -> None:
    m = create_test_model()
    p_allow = create_test_policy(allow_degraded=True)
    p_deny = create_test_policy(allow_degraded=False)
    e = create_test_estimate()

    r = create_test_request()
    res_unavail = evaluate_candidate(
        request=r,
        policy=p_allow,
        model=m,
        estimate=e,
        provider_state=ProviderOperatingState.UNAVAILABLE,
    )
    assert CandidateRejectionReason.PROVIDER_UNAVAILABLE in res_unavail.rejection_reasons
    assert CandidateRejectionReason.DEGRADED_STATE_NOT_ALLOWED not in res_unavail.rejection_reasons

    r_allow = create_test_request(constraints=RoutingConstraints(allow_degraded_provider=True))
    res_deg_allow = evaluate_candidate(
        request=r_allow,
        policy=p_allow,
        model=m,
        estimate=e,
        provider_state=ProviderOperatingState.DEGRADED,
    )
    assert res_deg_allow.eligible is True

    res_deg_deny_policy = evaluate_candidate(
        request=r_allow,
        policy=p_deny,
        model=m,
        estimate=e,
        provider_state=ProviderOperatingState.DEGRADED,
    )
    assert (
        CandidateRejectionReason.DEGRADED_STATE_NOT_ALLOWED in res_deg_deny_policy.rejection_reasons
    )

    r_deny = create_test_request(constraints=RoutingConstraints(allow_degraded_provider=False))
    res_deg_deny_req = evaluate_candidate(
        request=r_deny,
        policy=p_allow,
        model=m,
        estimate=e,
        provider_state=ProviderOperatingState.DEGRADED,
    )
    assert CandidateRejectionReason.DEGRADED_STATE_NOT_ALLOWED in res_deg_deny_req.rejection_reasons


def test_multiple_failures_exact_stable_ordering() -> None:
    m = create_test_model(
        enabled=False,
        capabilities=(),
        governance_allowed=(GovernanceClassification.PUBLIC,),
    )
    p = create_test_policy(
        minimum_quality=0.9,
        maximum_latency_ms=100,
        maximum_estimated_cost_usd=Decimal("0.10"),
        maximum_governance=GovernanceClassification.PUBLIC,
        allow_degraded=False,
    )
    r = create_test_request(
        output_format=OutputFormat.JSON,
        constraints=RoutingConstraints(required_governance=GovernanceClassification.RESTRICTED),
    )
    e = create_test_estimate(quality=0.5, latency_ms=500, cost_usd=Decimal("2.00"))

    res = evaluate_candidate(
        request=r,
        policy=p,
        model=m,
        estimate=e,
        provider_state=ProviderOperatingState.DEGRADED,
    )

    assert res.eligible is False
    expected_order = (
        CandidateRejectionReason.MODEL_NOT_ALLOWED,
        CandidateRejectionReason.CAPABILITY_MISMATCH,
        CandidateRejectionReason.QUALITY_BELOW_THRESHOLD,
        CandidateRejectionReason.LATENCY_ABOVE_TARGET,
        CandidateRejectionReason.COST_ABOVE_REQUEST_LIMIT,
        CandidateRejectionReason.GOVERNANCE_MISMATCH,
        CandidateRejectionReason.DEGRADED_STATE_NOT_ALLOWED,
    )
    assert res.rejection_reasons == expected_order


def test_input_consistency_precondition_failure() -> None:
    m = create_test_model()
    p = create_test_policy(feature_id_str="feat_A")
    r = create_test_request(feature_id_str="feat_B")
    e = create_test_estimate()

    with pytest.raises(
        ValueError, match="feature_id 'feat_B' does not match policy feature_id 'feat_A'"
    ):
        evaluate_candidate(
            request=r, policy=p, model=m, estimate=e, provider_state=ProviderOperatingState.HEALTHY
        )
