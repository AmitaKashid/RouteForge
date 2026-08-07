"""Unit tests for feature policies and fallback policies."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts.common import (
    Capability,
    FeatureId,
    GovernanceClassification,
    ModelId,
    PolicyId,
    PolicyVersion,
)
from routeforge.contracts.policies import (
    FallbackPolicy,
    FeaturePolicy,
    PolicyStatus,
)


def test_valid_fallback_policy() -> None:
    disabled = FallbackPolicy(enabled=False, maximum_fallback_attempts=0)
    assert disabled.enabled is False
    assert disabled.maximum_fallback_attempts == 0

    enabled = FallbackPolicy(enabled=True, maximum_fallback_attempts=2)
    assert enabled.enabled is True
    assert enabled.maximum_fallback_attempts == 2


def test_invalid_fallback_policy() -> None:
    with pytest.raises(ValueError, match="must be 0 when fallback policy is disabled"):
        FallbackPolicy(enabled=False, maximum_fallback_attempts=2)

    with pytest.raises(ValueError, match="must be at least 1 when fallback policy is enabled"):
        FallbackPolicy(enabled=True, maximum_fallback_attempts=0)


def test_valid_feature_policy() -> None:
    policy = FeaturePolicy(
        policy_id=PolicyId("pol_search"),
        version=PolicyVersion("1.0.0"),
        feature_id=FeatureId("feat_search"),
        status=PolicyStatus.ACTIVE,
        allowed_model_ids=(ModelId("gpt-4o"), ModelId("claude-3-5-sonnet")),
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.85,
        maximum_latency_ms=1000,
        maximum_estimated_cost_usd=Decimal("0.05"),
        maximum_governance_classification=GovernanceClassification.INTERNAL,
        allow_degraded_providers=False,
        fallback_policy=FallbackPolicy(enabled=True, maximum_fallback_attempts=1),
        created_at=datetime.now(UTC),
        pinned_model_id=ModelId("gpt-4o"),
    )
    assert policy.status == PolicyStatus.ACTIVE
    assert policy.pinned_model_id == ModelId("gpt-4o")


def test_feature_policy_invalid_identifiers() -> None:
    now = datetime.now(UTC)
    fb = FallbackPolicy(enabled=False, maximum_fallback_attempts=0)
    models = (ModelId("m1"),)

    with pytest.raises(ValueError, match="policy_id cannot be empty"):
        FeaturePolicy(
            policy_id=PolicyId(""),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=models,
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=fb,
            created_at=now,
        )

    with pytest.raises(ValueError, match="version cannot be empty"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion(""),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=models,
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=fb,
            created_at=now,
        )

    with pytest.raises(ValueError, match="feature_id cannot be empty"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId(""),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=models,
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=fb,
            created_at=now,
        )


def test_empty_allowed_models_rejected() -> None:
    with pytest.raises(ValueError, match="allowed_model_ids cannot be empty"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=(),
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
            created_at=datetime.now(UTC),
        )


def test_pinned_model_outside_allow_list_rejected() -> None:
    with pytest.raises(ValueError, match="must be in allowed_model_ids"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=(ModelId("model_a"),),
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
            created_at=datetime.now(UTC),
            pinned_model_id=ModelId("model_unallowed"),
        )


def test_invalid_quality_latency_and_cost_thresholds() -> None:
    now = datetime.now(UTC)
    fb = FallbackPolicy(enabled=False, maximum_fallback_attempts=0)
    models = (ModelId("m1"),)

    with pytest.raises(ValueError, match="minimum_quality must be between"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=models,
            required_capabilities=(),
            minimum_quality=2.0,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=fb,
            created_at=now,
        )

    with pytest.raises(ValueError, match="maximum_latency_ms must be positive"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=models,
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=0,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=fb,
            created_at=now,
        )

    with pytest.raises(ValueError, match="maximum_estimated_cost_usd must not be negative"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=models,
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("-1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=fb,
            created_at=now,
        )


def test_timezone_naive_policy_created_at_rejected() -> None:
    with pytest.raises(ValueError, match="must be timezone-aware"):
        FeaturePolicy(
            policy_id=PolicyId("p1"),
            version=PolicyVersion("v1"),
            feature_id=FeatureId("f1"),
            status=PolicyStatus.ACTIVE,
            allowed_model_ids=(ModelId("model_a"),),
            required_capabilities=(),
            minimum_quality=0.5,
            maximum_latency_ms=100,
            maximum_estimated_cost_usd=Decimal("1.0"),
            maximum_governance_classification=GovernanceClassification.PUBLIC,
            allow_degraded_providers=False,
            fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
            created_at=datetime(2026, 1, 1, 0, 0, 0),
        )
