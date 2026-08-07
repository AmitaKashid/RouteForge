"""Integration test evaluating committed configuration models and policies."""

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
    ProviderOperatingState,
    RequestId,
    RoutingConstraints,
    TeamId,
)
from routeforge.registries import load_registry_snapshot
from routeforge.routing import evaluate_candidate


def test_evaluate_committed_models_with_active_general_chat_policy() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    models_dir = repo_root / "config" / "models"
    policies_dir = repo_root / "config" / "policies"

    snapshot = load_registry_snapshot(
        models_directory=models_dir,
        policies_directory=policies_dir,
    )

    policy = snapshot.policies.get_active_for_feature(FeatureId("general-chat"))
    assert policy is not None

    m_economy = snapshot.models.get(ModelId("mock-economy"))
    m_premium = snapshot.models.get(ModelId("mock-premium"))
    assert m_economy is not None
    assert m_premium is not None

    request = ChatRequest(
        request_id=RequestId("req_integ_eval_1"),
        team_id=TeamId("team_1"),
        feature_id=FeatureId("general-chat"),
        messages=(ChatMessage(role=ChatRole.USER, content="Hello RouteForge"),),
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

    eval_economy = evaluate_candidate(
        request=request,
        policy=policy,
        model=m_economy,
        estimate=est_economy,
        provider_state=ProviderOperatingState.HEALTHY,
    )
    eval_premium = evaluate_candidate(
        request=request,
        policy=policy,
        model=m_premium,
        estimate=est_premium,
        provider_state=ProviderOperatingState.HEALTHY,
    )

    assert eval_economy.eligible is True
    assert eval_economy.rejection_reasons == ()

    assert eval_premium.eligible is True
    assert eval_premium.rejection_reasons == ()
