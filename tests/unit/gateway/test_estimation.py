"""Unit tests for deterministic gateway candidate estimation logic."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts import (
    Capability,
    ChatMessage,
    ChatRequest,
    ChatRole,
    FeatureId,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderId,
    QualityProfile,
    RequestId,
    RoutingConstraints,
    TeamId,
)
from routeforge.gateway.estimation import build_candidate_estimate, estimate_input_tokens


def make_test_model(
    model_id: str = "mock-economy",
    input_price: str = "1.00",
    output_price: str = "2.00",
) -> ModelDefinition:
    return ModelDefinition(
        model_id=ModelId(model_id),
        provider_id=ProviderId("mock"),
        display_name="Mock Economy Model",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=8192,
        estimated_input_cost_per_million_tokens_usd=Decimal(input_price),
        estimated_output_cost_per_million_tokens_usd=Decimal(output_price),
        estimated_latency_ms=120,
        quality_profiles=(
            QualityProfile(
                task_type="general-chat",
                predicted_quality=0.80,
                source="mock-bench-v1",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )


def test_estimate_input_tokens() -> None:
    req = ChatRequest(
        request_id=RequestId("req_1"),
        team_id=TeamId("local-development"),
        feature_id=FeatureId("general-chat"),
        messages=(
            ChatMessage(role=ChatRole.SYSTEM, content="System prompt here"),
            ChatMessage(role=ChatRole.USER, content="Hello world from user"),
        ),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )
    tokens = estimate_input_tokens(req)
    assert tokens == 7  # 3 words + 4 words


def test_build_candidate_estimate_success() -> None:
    model = make_test_model()
    req = ChatRequest(
        request_id=RequestId("req_1"),
        team_id=TeamId("local-development"),
        feature_id=FeatureId("general-chat"),
        messages=(ChatMessage(role=ChatRole.USER, content="One two three four five"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )

    est = build_candidate_estimate(
        request=req,
        model=model,
        feature_id=FeatureId("general-chat"),
    )

    assert est.predicted_quality == 0.80
    assert est.estimated_latency_ms == 120
    # Input tokens = 5 words.
    # input_cost = 5 * 1.00 / 1_000_000 = 0.000005
    # output_cost = 128 * 2.00 / 1_000_000 = 0.000256
    # total = 0.000261
    assert est.estimated_cost_usd == Decimal("0.000261")
    assert est.cost_provenance.source == "m2-deterministic-estimator"
    assert est.cost_provenance.version == "v1-output-budget-128"


def test_build_candidate_estimate_missing_quality_profile_raises() -> None:
    model = make_test_model()
    req = ChatRequest(
        request_id=RequestId("req_1"),
        team_id=TeamId("local-development"),
        feature_id=FeatureId("unknown-feature"),
        messages=(ChatMessage(role=ChatRole.USER, content="Hi"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="has no quality profile matching task"):
        build_candidate_estimate(
            request=req,
            model=model,
            feature_id=FeatureId("unknown-feature"),
        )
