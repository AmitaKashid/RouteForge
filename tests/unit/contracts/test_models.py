"""Unit tests for model definitions and quality profiles."""

from decimal import Decimal

import pytest

from routeforge.contracts.common import (
    Capability,
    GovernanceClassification,
    ModelId,
    ProviderId,
)
from routeforge.contracts.models import (
    ModelDefinition,
    ProviderOperatingState,
    QualityProfile,
)


def test_valid_quality_profile() -> None:
    qp = QualityProfile(
        task_type="coding",
        predicted_quality=0.92,
        source="benchmark_v1",
        version="1.0.0",
    )
    assert qp.task_type == "coding"
    assert qp.predicted_quality == 0.92


def test_invalid_quality_profile() -> None:
    with pytest.raises(ValueError, match="predicted_quality must be between"):
        QualityProfile(task_type="text", predicted_quality=1.5, source="src", version="1")

    with pytest.raises(ValueError, match="task_type cannot be empty"):
        QualityProfile(task_type=" ", predicted_quality=0.5, source="src", version="1")

    with pytest.raises(ValueError, match="source cannot be empty"):
        QualityProfile(task_type="text", predicted_quality=0.5, source=" ", version="1")

    with pytest.raises(ValueError, match="version cannot be empty"):
        QualityProfile(task_type="text", predicted_quality=0.5, source="src", version=" ")


def test_valid_model_definition() -> None:
    model = ModelDefinition(
        model_id=ModelId("claude-3-5-sonnet"),
        provider_id=ProviderId("anthropic"),
        display_name="Claude 3.5 Sonnet",
        capabilities=(Capability.TEXT_CHAT, Capability.REASONING),
        governance_allowed=(GovernanceClassification.PUBLIC, GovernanceClassification.INTERNAL),
        context_window_tokens=200000,
        estimated_input_cost_per_million_tokens_usd=Decimal("3.00"),
        estimated_output_cost_per_million_tokens_usd=Decimal("15.00"),
        estimated_latency_ms=800,
        quality_profiles=(
            QualityProfile(
                task_type="general",
                predicted_quality=0.95,
                source="eval",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="2026-01-01.1",
    )
    assert model.model_id == ModelId("claude-3-5-sonnet")
    assert isinstance(model.capabilities, tuple)
    assert isinstance(model.governance_allowed, tuple)


def test_empty_quality_profiles_rejected() -> None:
    with pytest.raises(ValueError, match="must contain at least one QualityProfile"):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=(Capability.TEXT_CHAT,),
            governance_allowed=(GovernanceClassification.PUBLIC,),
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(),
            enabled=True,
            configuration_version="v1",
        )


def test_model_definition_invalid_identifiers() -> None:
    qp = QualityProfile("gen", 0.8, "s", "v")
    caps = (Capability.TEXT_CHAT,)
    gov = (GovernanceClassification.PUBLIC,)

    with pytest.raises(ValueError, match="model_id cannot be empty"):
        ModelDefinition(
            model_id=ModelId(""),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )

    with pytest.raises(ValueError, match="provider_id cannot be empty"):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId(""),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )

    with pytest.raises(ValueError, match="display_name cannot be empty"):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name=" ",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )

    with pytest.raises(ValueError, match="configuration_version cannot be empty"):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version=" ",
        )


def test_invalid_context_window_latency_and_cost() -> None:
    qp = QualityProfile("gen", 0.8, "s", "v")
    caps = (Capability.TEXT_CHAT,)
    gov = (GovernanceClassification.PUBLIC,)

    with pytest.raises(ValueError, match="context_window_tokens must be positive"):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=0,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )

    with pytest.raises(ValueError, match="estimated_latency_ms must be positive"):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=0,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )

    with pytest.raises(
        ValueError, match="estimated_input_cost_per_million_tokens_usd must not be negative"
    ):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("-1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )

    with pytest.raises(
        ValueError, match="estimated_output_cost_per_million_tokens_usd must not be negative"
    ):
        ModelDefinition(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            display_name="M1",
            capabilities=caps,
            governance_allowed=gov,
            context_window_tokens=1000,
            estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
            estimated_output_cost_per_million_tokens_usd=Decimal("-2.0"),
            estimated_latency_ms=100,
            quality_profiles=(qp,),
            enabled=True,
            configuration_version="v1",
        )


def test_mutable_input_converted_to_tuples() -> None:
    qp = QualityProfile("gen", 0.8, "s", "v")
    model = ModelDefinition(
        model_id=ModelId("m1"),
        provider_id=ProviderId("p1"),
        display_name="M1",
        capabilities=[Capability.TEXT_CHAT],  # type: ignore[arg-type]
        governance_allowed=[GovernanceClassification.PUBLIC],  # type: ignore[arg-type]
        context_window_tokens=1000,
        estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
        estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
        estimated_latency_ms=100,
        quality_profiles=[qp],  # type: ignore[arg-type]
        enabled=True,
        configuration_version="v1",
    )
    assert isinstance(model.capabilities, tuple)
    assert isinstance(model.governance_allowed, tuple)
    assert isinstance(model.quality_profiles, tuple)


def test_provider_operating_state_enum() -> None:
    assert ProviderOperatingState.HEALTHY == "HEALTHY"
    assert ProviderOperatingState.DEGRADED == "DEGRADED"
    assert ProviderOperatingState.UNAVAILABLE == "UNAVAILABLE"
