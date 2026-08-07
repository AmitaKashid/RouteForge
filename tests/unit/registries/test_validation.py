"""Unit tests for cross-reference validation logic."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts import (
    Capability,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    PolicyId,
    PolicyStatus,
    PolicyVersion,
    ProviderId,
    QualityProfile,
)
from routeforge.registries import (
    InMemoryFeaturePolicyRegistry,
    InMemoryModelRegistry,
    RegistryConfigurationError,
)
from routeforge.registries.validation import validate_cross_references


def test_cross_reference_validation_errors() -> None:
    qp = QualityProfile("gen", 0.8, "s", "v")
    model_disabled = ModelDefinition(
        model_id=ModelId("m_disabled"),
        provider_id=ProviderId("p1"),
        display_name="Disabled Model",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=1000,
        estimated_input_cost_per_million_tokens_usd=Decimal("1.0"),
        estimated_output_cost_per_million_tokens_usd=Decimal("2.0"),
        estimated_latency_ms=100,
        quality_profiles=(qp,),
        enabled=False,  # Disabled!
        configuration_version="v1",
    )
    models = InMemoryModelRegistry([model_disabled])

    policy_active_no_enabled = FeaturePolicy(
        policy_id=PolicyId("pol_1"),
        version=PolicyVersion("v1"),
        feature_id=FeatureId("feat_1"),
        status=PolicyStatus.ACTIVE,  # Active policy with no enabled model!
        allowed_model_ids=(ModelId("m_disabled"), ModelId("unknown_model")),  # Unknown model!
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.5,
        maximum_latency_ms=100,
        maximum_estimated_cost_usd=Decimal("10.0"),
        maximum_governance_classification=GovernanceClassification.PUBLIC,
        allow_degraded_providers=False,
        fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
        created_at=datetime.now(UTC),
        pinned_model_id=ModelId("unknown_model"),  # Missing pinned model!
    )
    policies = InMemoryFeaturePolicyRegistry([policy_active_no_enabled])

    with pytest.raises(RegistryConfigurationError) as exc:
        validate_cross_references(models, policies)

    codes = [i.code for i in exc.value.issues]
    assert "UNKNOWN_MODEL_REFERENCE" in codes
    assert "PINNED_MODEL_REFERENCE_MISSING" in codes
    assert "NO_ENABLED_MODEL_FOR_ACTIVE_POLICY" in codes
