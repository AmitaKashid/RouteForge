"""Contract tests for JSON serialization helper across domain contracts."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from routeforge.contracts import (
    CandidateEstimate,
    CandidateEvaluation,
    CandidateRejectionReason,
    Capability,
    ChatMessage,
    ChatRequest,
    ChatRole,
    EstimateProvenance,
    FeatureId,
    GovernanceClassification,
    ModelId,
    OutputFormat,
    PolicyId,
    PolicyVersion,
    ProviderId,
    RequestId,
    RoutingConstraints,
    RoutingDecision,
    RoutingReason,
    TeamId,
    serialize_contract,
)


def test_serialize_chat_request() -> None:
    dt = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
    req = ChatRequest(
        request_id=RequestId("req_100"),
        team_id=TeamId("team_alpha"),
        feature_id=FeatureId("feat_search"),
        messages=(
            ChatMessage(role=ChatRole.SYSTEM, content="System instruction"),
            ChatMessage(role=ChatRole.USER, content="User question"),
        ),
        output_format=OutputFormat.JSON,
        routing_constraints=RoutingConstraints(
            minimum_quality=0.85,
            maximum_latency_ms=400,
            maximum_estimated_cost_usd=Decimal("0.0050"),
            required_capabilities=(Capability.TEXT_CHAT, Capability.STRUCTURED_OUTPUT),
            required_governance=GovernanceClassification.CONFIDENTIAL,
            allow_degraded_provider=False,
        ),
        created_at=dt,
        metadata={"client": "test-suite"},
    )

    serialized = serialize_contract(req)
    assert serialized["request_id"] == "req_100"
    assert serialized["output_format"] == "JSON"
    assert serialized["created_at"] == "2026-08-06T12:00:00+00:00"
    assert serialized["routing_constraints"]["maximum_estimated_cost_usd"] == "0.0050"
    assert serialized["routing_constraints"]["required_capabilities"] == [
        "TEXT_CHAT",
        "STRUCTURED_OUTPUT",
    ]
    assert serialized["messages"][0]["role"] == "SYSTEM"

    # Verify JSON dumps compatibility
    json_str = json.dumps(serialized)
    assert isinstance(json_str, str)


def test_serialize_routing_decision() -> None:
    dt = datetime(2026, 8, 6, 12, 5, 0, tzinfo=UTC)
    prov = EstimateProvenance(source="benchmark", version="1.0.0")
    cand_eval = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=CandidateEstimate(
            predicted_quality=0.92,
            estimated_latency_ms=250,
            estimated_cost_usd=Decimal("0.00125"),
            quality_provenance=prov,
            latency_provenance=prov,
            cost_provenance=prov,
        ),
    )
    cand_inelig = CandidateEvaluation(
        model_id=ModelId("legacy-model"),
        provider_id=ProviderId("openai"),
        eligible=False,
        rejection_reasons=(CandidateRejectionReason.QUALITY_BELOW_THRESHOLD,),
        estimate=CandidateEstimate(
            predicted_quality=0.40,
            estimated_latency_ms=500,
            estimated_cost_usd=Decimal("0.00050"),
            quality_provenance=prov,
            latency_provenance=prov,
            cost_provenance=prov,
        ),
    )
    decision = RoutingDecision(
        request_id=RequestId("req_200"),
        team_id=TeamId("team_beta"),
        feature_id=FeatureId("feat_code"),
        policy_id=PolicyId("pol_code"),
        policy_version=PolicyVersion("2.1.0"),
        candidates=(cand_eval, cand_inelig),
        routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
        decided_at=dt,
        selected_model_id=ModelId("gpt-4o"),
        selected_provider_id=ProviderId("openai"),
        retry_count=0,
    )

    serialized = serialize_contract(decision)

    assert serialized["routing_reason"] == "CHEAPEST_ELIGIBLE_MODEL"
    assert serialized["selected_model_id"] == "gpt-4o"
    assert serialized["candidates"][0]["estimate"]["estimated_cost_usd"] == "0.00125"
    assert serialized["candidates"][1]["rejection_reasons"] == ["QUALITY_BELOW_THRESHOLD"]

    # Verify JSON dumps compatibility
    json_str = json.dumps(serialized)
    assert isinstance(json_str, str)
