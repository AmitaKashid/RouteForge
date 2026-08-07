"""Unit tests for route_request deterministic candidate selection."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts import (
    CandidateEstimate,
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
    RoutingReason,
    TeamId,
)
from routeforge.routing import RoutingCandidate, route_request


def create_test_model(
    model_id_str: str,
    provider_id_str: str = "mock",
    enabled: bool = True,
    capabilities: tuple[Capability, ...] = (Capability.TEXT_CHAT,),
    governance_allowed: tuple[GovernanceClassification, ...] = (GovernanceClassification.PUBLIC,),
) -> ModelDefinition:
    qp = QualityProfile(task_type="general", predicted_quality=0.8, source="e", version="v1")
    return ModelDefinition(
        model_id=ModelId(model_id_str),
        provider_id=ProviderId(provider_id_str),
        display_name=f"Model {model_id_str}",
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
    feature_id_str: str = "feat_1",
    allowed_model_ids: tuple[ModelId, ...] = (ModelId("m1"), ModelId("m2"), ModelId("m3")),
    pinned_model_id: ModelId | None = None,
    allow_degraded: bool = True,
) -> FeaturePolicy:
    return FeaturePolicy(
        policy_id=PolicyId(policy_id_str),
        version=PolicyVersion("v1"),
        feature_id=FeatureId(feature_id_str),
        status=PolicyStatus.ACTIVE,
        allowed_model_ids=allowed_model_ids,
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.5,
        maximum_latency_ms=1000,
        maximum_estimated_cost_usd=Decimal("10.0"),
        maximum_governance_classification=GovernanceClassification.PUBLIC,
        allow_degraded_providers=allow_degraded,
        fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
        created_at=datetime.now(UTC),
        pinned_model_id=pinned_model_id,
    )


def create_test_request(feature_id_str: str = "feat_1") -> ChatRequest:
    return ChatRequest(
        request_id=RequestId("req_1"),
        team_id=TeamId("team_1"),
        feature_id=FeatureId(feature_id_str),
        messages=(ChatMessage(role=ChatRole.USER, content="Hello"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )


def create_test_estimate(
    cost_usd: Decimal = Decimal("0.10"),
    quality: float = 0.8,
    latency_ms: int = 100,
) -> CandidateEstimate:
    prov = EstimateProvenance(source="t", version="v1")
    return CandidateEstimate(
        predicted_quality=quality,
        estimated_latency_ms=latency_ms,
        estimated_cost_usd=cost_usd,
        quality_provenance=prov,
        latency_provenance=prov,
        cost_provenance=prov,
    )


def test_basic_successful_selection() -> None:
    model = create_test_model("m1")
    policy = create_test_policy()
    request = create_test_request()
    estimate = create_test_estimate()
    cand = RoutingCandidate(model, estimate, ProviderOperatingState.HEALTHY)

    decided_at = datetime.now(UTC)
    decision = route_request(
        request=request,
        policy=policy,
        candidates=[cand],
        decided_at=decided_at,
    )

    assert decision.selected_model_id == ModelId("m1")
    assert decision.selected_provider_id == ProviderId("mock")
    assert decision.routing_reason == RoutingReason.CHEAPEST_ELIGIBLE_MODEL
    assert len(decision.candidates) == 1
    assert decision.candidates[0].model_id == ModelId("m1")
    assert decision.fallback_used is False
    assert decision.retry_count == 0
    assert decision.classifier_version is None
    assert decision.decided_at == decided_at


def test_lowest_cost_selection_ignores_order_and_metrics() -> None:
    m_exp = create_test_model("m_exp")
    m_cheap = create_test_model("m_cheap")

    est_exp = create_test_estimate(cost_usd=Decimal("0.50"), quality=0.99, latency_ms=10)
    est_cheap = create_test_estimate(cost_usd=Decimal("0.05"), quality=0.60, latency_ms=500)

    policy = create_test_policy(allowed_model_ids=(ModelId("m_exp"), ModelId("m_cheap")))
    request = create_test_request()

    cand_exp = RoutingCandidate(m_exp, est_exp, ProviderOperatingState.HEALTHY)
    cand_cheap = RoutingCandidate(m_cheap, est_cheap, ProviderOperatingState.HEALTHY)

    # Pass candidates in reverse order (expensive first)
    decision = route_request(
        request=request,
        policy=policy,
        candidates=[cand_exp, cand_cheap],
        decided_at=datetime.now(UTC),
    )

    assert decision.selected_model_id == ModelId("m_cheap")
    assert decision.routing_reason == RoutingReason.CHEAPEST_ELIGIBLE_MODEL
    assert len(decision.candidates) == 2


def test_cost_tie_breaking_by_model_id() -> None:
    m_b = create_test_model("m_b")
    m_a = create_test_model("m_a")

    est_same = create_test_estimate(cost_usd=Decimal("0.10"))
    policy = create_test_policy(allowed_model_ids=(ModelId("m_a"), ModelId("m_b")))
    request = create_test_request()

    cand_b = RoutingCandidate(m_b, est_same, ProviderOperatingState.HEALTHY)
    cand_a = RoutingCandidate(m_a, est_same, ProviderOperatingState.HEALTHY)

    decision1 = route_request(
        request=request, policy=policy, candidates=[cand_b, cand_a], decided_at=datetime.now(UTC)
    )
    decision2 = route_request(
        request=request, policy=policy, candidates=[cand_a, cand_b], decided_at=datetime.now(UTC)
    )

    assert decision1.selected_model_id == ModelId("m_a")
    assert decision2.selected_model_id == ModelId("m_a")


def test_candidate_decision_ordering_always_by_model_id() -> None:
    m3 = create_test_model("m3")
    m1 = create_test_model("m1")
    m2 = create_test_model("m2")

    policy = create_test_policy(allowed_model_ids=(ModelId("m1"), ModelId("m2"), ModelId("m3")))
    request = create_test_request()
    est = create_test_estimate()

    cands = [
        RoutingCandidate(m3, est, ProviderOperatingState.HEALTHY),
        RoutingCandidate(m1, est, ProviderOperatingState.HEALTHY),
        RoutingCandidate(m2, est, ProviderOperatingState.HEALTHY),
    ]

    decision = route_request(
        request=request, policy=policy, candidates=cands, decided_at=datetime.now(UTC)
    )

    candidate_ids = [c.model_id for c in decision.candidates]
    assert candidate_ids == [ModelId("m1"), ModelId("m2"), ModelId("m3")]


def test_ineligible_candidates_skipped() -> None:
    m_cheap_disabled = create_test_model("m_cheap", enabled=False)
    m_exp_enabled = create_test_model("m_exp", enabled=True)

    est_cheap = create_test_estimate(cost_usd=Decimal("0.01"))
    est_exp = create_test_estimate(cost_usd=Decimal("1.00"))

    policy = create_test_policy(allowed_model_ids=(ModelId("m_cheap"), ModelId("m_exp")))
    request = create_test_request()

    cand_cheap = RoutingCandidate(m_cheap_disabled, est_cheap, ProviderOperatingState.HEALTHY)
    cand_exp = RoutingCandidate(m_exp_enabled, est_exp, ProviderOperatingState.HEALTHY)

    decision = route_request(
        request=request,
        policy=policy,
        candidates=[cand_cheap, cand_exp],
        decided_at=datetime.now(UTC),
    )

    assert decision.selected_model_id == ModelId("m_exp")
    assert len(decision.candidates) == 2
    assert decision.candidates[0].eligible is False
    assert decision.candidates[1].eligible is True


def test_no_eligible_model() -> None:
    m1 = create_test_model("m1", enabled=False)
    policy = create_test_policy(allowed_model_ids=(ModelId("m1"),))
    request = create_test_request()
    cand = RoutingCandidate(m1, create_test_estimate(), ProviderOperatingState.HEALTHY)

    decision = route_request(
        request=request, policy=policy, candidates=[cand], decided_at=datetime.now(UTC)
    )

    assert decision.selected_model_id is None
    assert decision.selected_provider_id is None
    assert decision.routing_reason == RoutingReason.NO_ELIGIBLE_MODEL
    assert len(decision.candidates) == 1
    assert decision.candidates[0].eligible is False


def test_pinned_policy_precedence_and_ineligible_pin() -> None:
    m1_cheap = create_test_model("m1")
    m2_pinned_exp = create_test_model("m2")

    policy_pinned = create_test_policy(
        allowed_model_ids=(ModelId("m1"), ModelId("m2")),
        pinned_model_id=ModelId("m2"),
    )
    request = create_test_request()

    c1 = RoutingCandidate(
        m1_cheap, create_test_estimate(cost_usd=Decimal("0.01")), ProviderOperatingState.HEALTHY
    )
    c2 = RoutingCandidate(
        m2_pinned_exp,
        create_test_estimate(cost_usd=Decimal("0.90")),
        ProviderOperatingState.HEALTHY,
    )

    # Eligible pinned model selected even when more expensive
    decision = route_request(
        request=request, policy=policy_pinned, candidates=[c1, c2], decided_at=datetime.now(UTC)
    )
    assert decision.selected_model_id == ModelId("m2")
    assert decision.routing_reason == RoutingReason.POLICY_PINNED_MODEL

    # Ineligible pinned model yields NO_ELIGIBLE_MODEL
    m2_disabled = create_test_model("m2", enabled=False)
    c2_disabled = RoutingCandidate(
        m2_disabled, create_test_estimate(), ProviderOperatingState.HEALTHY
    )
    decision_ineligible_pin = route_request(
        request=request,
        policy=policy_pinned,
        candidates=[c1, c2_disabled],
        decided_at=datetime.now(UTC),
    )
    assert decision_ineligible_pin.selected_model_id is None
    assert decision_ineligible_pin.routing_reason == RoutingReason.NO_ELIGIBLE_MODEL


def test_degraded_provider_selection_and_precedence() -> None:
    m_deg = create_test_model("m1")
    policy = create_test_policy(allow_degraded=True)
    create_test_request()
    req_deg_allow = ChatRequest(
        request_id=RequestId("req_2"),
        team_id=TeamId("team_1"),
        feature_id=FeatureId("feat_1"),
        messages=(ChatMessage(role=ChatRole.USER, content="Hi"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(allow_degraded_provider=True),
        created_at=datetime.now(UTC),
    )

    cand_deg = RoutingCandidate(m_deg, create_test_estimate(), ProviderOperatingState.DEGRADED)

    decision = route_request(
        request=req_deg_allow, policy=policy, candidates=[cand_deg], decided_at=datetime.now(UTC)
    )
    assert decision.selected_model_id == ModelId("m1")
    assert decision.routing_reason == RoutingReason.DEGRADED_MODE_SELECTION


def test_input_validation_errors() -> None:
    policy = create_test_policy()
    req = create_test_request()
    now = datetime.now(UTC)

    # Empty candidates
    with pytest.raises(ValueError, match="Candidate collection cannot be empty"):
        route_request(request=req, policy=policy, candidates=[], decided_at=now)

    # Duplicate model_id
    m1 = create_test_model("m1")
    c1 = RoutingCandidate(m1, create_test_estimate(), ProviderOperatingState.HEALTHY)
    c1_dup = RoutingCandidate(m1, create_test_estimate(), ProviderOperatingState.HEALTHY)
    with pytest.raises(ValueError, match="Duplicate model_id 'm1'"):
        route_request(request=req, policy=policy, candidates=[c1, c1_dup], decided_at=now)

    # Mismatched feature_id
    req_other = create_test_request(feature_id_str="feat_other")
    with pytest.raises(ValueError, match="does not match policy feature_id"):
        route_request(request=req_other, policy=policy, candidates=[c1], decided_at=now)

    # Naive decided_at
    naive_dt = datetime.now()
    with pytest.raises(ValueError, match="timezone-aware"):
        route_request(request=req, policy=policy, candidates=[c1], decided_at=naive_dt)


def test_generator_candidate_input_consumed_deterministically() -> None:
    m1 = create_test_model("m1")
    policy = create_test_policy()
    req = create_test_request()
    cand = RoutingCandidate(m1, create_test_estimate(), ProviderOperatingState.HEALTHY)

    # Supply generator
    gen_candidates = (c for c in [cand])
    decision = route_request(
        request=req, policy=policy, candidates=gen_candidates, decided_at=datetime.now(UTC)
    )
    assert decision.selected_model_id == ModelId("m1")
