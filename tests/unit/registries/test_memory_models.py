"""Unit tests for InMemoryModelRegistry."""

from decimal import Decimal

import pytest

from routeforge.contracts import (
    Capability,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    ProviderId,
    QualityProfile,
)
from routeforge.registries import InMemoryModelRegistry, RegistryConfigurationError


def create_sample_model(
    model_id_str: str,
    enabled: bool = True,
) -> ModelDefinition:
    qp = QualityProfile(
        task_type="general",
        predicted_quality=0.8,
        source="eval",
        version="v1",
    )
    return ModelDefinition(
        model_id=ModelId(model_id_str),
        provider_id=ProviderId("mock"),
        display_name=f"Model {model_id_str}",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.10"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.20"),
        estimated_latency_ms=200,
        quality_profiles=(qp,),
        enabled=enabled,
        configuration_version="v1",
    )


def test_lookup_and_filtering() -> None:
    m1 = create_sample_model("b-model", enabled=True)
    m2 = create_sample_model("a-model", enabled=False)

    registry = InMemoryModelRegistry([m1, m2])

    assert registry.get(ModelId("b-model")) == m1
    assert registry.get(ModelId("a-model")) == m2
    assert registry.get(ModelId("nonexistent")) is None

    # Deterministic ordering by model ID ("a-model", "b-model")
    all_models = registry.list_all()
    assert len(all_models) == 2
    assert all_models[0].model_id == ModelId("a-model")
    assert all_models[1].model_id == ModelId("b-model")

    enabled_models = registry.list_enabled()
    assert len(enabled_models) == 1
    assert enabled_models[0].model_id == ModelId("b-model")


def test_duplicate_model_rejection() -> None:
    m1 = create_sample_model("m1")
    m1_dup = create_sample_model("m1")

    with pytest.raises(RegistryConfigurationError) as exc_info:
        InMemoryModelRegistry([m1, m1_dup])

    assert any(i.code == "DUPLICATE_MODEL_ID" for i in exc_info.value.issues)


def test_caller_mutation_isolation() -> None:
    m1 = create_sample_model("m1")
    models_input = [m1]

    registry = InMemoryModelRegistry(models_input)
    models_input.clear()

    assert registry.get(ModelId("m1")) == m1
