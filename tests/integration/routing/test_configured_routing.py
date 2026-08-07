"""Integration test verifying request routing against committed configuration."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from routeforge.contracts import (
    CandidateEstimate,
    ChatMessage,
    ChatRequest,
    ChatRole,
    EstimateProvenance,
    FeatureId,
    ModelId,
    OutputFormat,
    PolicyId,
    PolicyVersion,
    ProviderOperatingState,
    RequestId,
    RoutingConstraints,
    RoutingReason,
    TeamId,
)
from routeforge.registries import load_registry_snapshot
from routeforge.routing import RoutingCandidate, route_request


def test_route_request_with_committed_development_configuration() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    models_dir = repo_root / "config" / "models"
    policies_dir = repo_root / "config" / "policies"

    snapshot = load_registry_snapshot(
        models_directory=models_dir,
        policies_directory=policies_dir,
    )

    policy = snapshot.policies.get_active_for_feature(FeatureId("general-chat"))
    assert policy is not None
    assert policy.policy_id == PolicyId("general-chat-policy")
    assert policy.version == PolicyVersion("v1")

    m_economy = snapshot.models.get(ModelId("mock-economy"))
    m_premium = snapshot.models.get(ModelId("mock-premium"))
    assert m_economy is not None
    assert m_premium is not None

    request = ChatRequest(
        request_id=RequestId("req_integ_route_1"),
        team_id=TeamId("team_1"),
        feature_id=FeatureId("general-chat"),
        messages=(ChatMessage(role=ChatRole.USER, content="Route me!"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )

    prov = EstimateProvenance(source="fixture", version="v1")
    est_economy = CandidateEstimate(
        predicted_quality=0.75,
        estimated_latency_ms=120,
        estimated_cost_usd=Decimal("0.001000"),
        quality_provenance=prov,
        latency_provenance=prov,
        cost_provenance=prov,
    )
    est_premium = CandidateEstimate(
        predicted_quality=0.92,
        estimated_latency_ms=250,
        estimated_cost_usd=Decimal("0.005000"),
        quality_provenance=prov,
        latency_provenance=prov,
        cost_provenance=prov,
    )

    cands = [
        RoutingCandidate(
            model=m_premium, estimate=est_premium, provider_state=ProviderOperatingState.HEALTHY
        ),
        RoutingCandidate(
            model=m_economy, estimate=est_economy, provider_state=ProviderOperatingState.HEALTHY
        ),
    ]

    decided_at = datetime.now(UTC)
    decision = route_request(
        request=request,
        policy=policy,
        candidates=cands,
        decided_at=decided_at,
    )

    # 1. Lower-cost eligible candidate (mock-economy) selected
    assert decision.selected_model_id == ModelId("mock-economy")
    assert decision.selected_provider_id == "mock"
    assert decision.routing_reason == RoutingReason.CHEAPEST_ELIGIBLE_MODEL

    # 2. Both candidate evaluations present and sorted by model_id ascending
    assert len(decision.candidates) == 2
    assert decision.candidates[0].model_id == ModelId("mock-economy")
    assert decision.candidates[1].model_id == ModelId("mock-premium")
    assert decision.candidates[0].eligible is True
    assert decision.candidates[1].eligible is True

    # 3. Policy ID and version recorded
    assert decision.policy_id == PolicyId("general-chat-policy")
    assert decision.policy_version == PolicyVersion("v1")
    assert decision.decided_at == decided_at
