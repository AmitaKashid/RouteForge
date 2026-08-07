"""Integration test demonstrating sequential M1 routing and provider attempt execution."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from routeforge.contracts import (
    AttemptId,
    CandidateEstimate,
    ChatMessage,
    ChatRequest,
    ChatRole,
    EstimateProvenance,
    FeatureId,
    ModelId,
    OutputFormat,
    ProviderOperatingState,
    ProviderRequest,
    RequestId,
    RoutingConstraints,
    RoutingReason,
    TeamId,
)
from routeforge.providers import DeterministicMockProvider
from routeforge.registries import load_registry_snapshot
from routeforge.routing import RoutingCandidate, route_request


def test_complete_m1_routing_and_provider_attempt_flow() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    models_dir = repo_root / "config" / "models"
    policies_dir = repo_root / "config" / "policies"

    # 1. Load committed registry snapshot
    snapshot = load_registry_snapshot(
        models_directory=models_dir,
        policies_directory=policies_dir,
    )

    # 2. Resolve active general-chat policy
    policy = snapshot.policies.get_active_for_feature(FeatureId("general-chat"))
    assert policy is not None

    # 3. Retrieve models
    m_economy = snapshot.models.get(ModelId("mock-economy"))
    m_premium = snapshot.models.get(ModelId("mock-premium"))
    assert m_economy is not None
    assert m_premium is not None

    # 4. Construct normalized ChatRequest
    request_id = RequestId("req_m1_flow_100")
    team_id = TeamId("team_alpha")
    chat_request = ChatRequest(
        request_id=request_id,
        team_id=team_id,
        feature_id=FeatureId("general-chat"),
        messages=(ChatMessage(role=ChatRole.USER, content="Explain quantum computing simply."),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )

    # 5. Construct explicit candidate estimates
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

    # 6. Supply explicit provider states
    # 7. Construct RoutingCandidate values
    candidates = [
        RoutingCandidate(
            model=m_premium, estimate=est_premium, provider_state=ProviderOperatingState.HEALTHY
        ),
        RoutingCandidate(
            model=m_economy, estimate=est_economy, provider_state=ProviderOperatingState.HEALTHY
        ),
    ]

    # 8. Call route_request
    decided_at = datetime.now(UTC)
    decision = route_request(
        request=chat_request,
        policy=policy,
        candidates=candidates,
        decided_at=decided_at,
    )

    # 9. Verify expected model was selected (mock-economy is cheaper)
    assert decision.selected_model_id == ModelId("mock-economy")
    assert decision.selected_provider_id == "mock"
    assert decision.routing_reason == RoutingReason.CHEAPEST_ELIGIBLE_MODEL

    # 10. Verify both candidate evaluations retained
    assert len(decision.candidates) == 2
    assert decision.candidates[0].model_id == ModelId("mock-economy")
    assert decision.candidates[1].model_id == ModelId("mock-premium")
    assert decision.candidates[0].eligible is True
    assert decision.candidates[1].eligible is True

    # 11. Construct ProviderRequest for the selected model
    attempt_id = AttemptId("att_1")
    selected_model = m_economy
    provider_request = ProviderRequest(
        request_id=request_id,
        attempt_id=attempt_id,
        model_id=selected_model.model_id,
        messages=chat_request.messages,
        output_format=chat_request.output_format,
        timeout_ms=5000,
        idempotency_key="idem_m1_flow_1",
    )

    # 12. Execute selected model through DeterministicMockProvider
    provider = DeterministicMockProvider()
    provider_response = asyncio.run(provider.complete(provider_request, selected_model))

    # 13. Verify normalized deterministic ProviderResponse
    assert provider_response.content.startswith("mock-response:mock-economy:")
    assert provider_response.usage.input_tokens > 0
    assert provider_response.usage.output_tokens > 0

    # 14. Verify request, attempt, model, and provider identifiers remain correlated
    assert provider_response.request_id == chat_request.request_id
    assert provider_response.request_id == decision.request_id
    assert provider_response.attempt_id == attempt_id
    assert provider_response.model_id == decision.selected_model_id
    assert provider_response.provider_id == decision.selected_provider_id
