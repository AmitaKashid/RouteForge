"""Unit tests for InMemoryFeaturePolicyRegistry."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts import (
    Capability,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    GovernanceClassification,
    ModelId,
    PolicyId,
    PolicyStatus,
    PolicyVersion,
)
from routeforge.registries import (
    InMemoryFeaturePolicyRegistry,
    RegistryConfigurationError,
)


def create_sample_policy(
    policy_id_str: str,
    version_str: str = "v1",
    feature_id_str: str = "feat_1",
    status: PolicyStatus = PolicyStatus.ACTIVE,
) -> FeaturePolicy:
    return FeaturePolicy(
        policy_id=PolicyId(policy_id_str),
        version=PolicyVersion(version_str),
        feature_id=FeatureId(feature_id_str),
        status=status,
        allowed_model_ids=(ModelId("m1"),),
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.7,
        maximum_latency_ms=1000,
        maximum_estimated_cost_usd=Decimal("1.0"),
        maximum_governance_classification=GovernanceClassification.PUBLIC,
        allow_degraded_providers=False,
        fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
        created_at=datetime.now(UTC),
    )


def test_lookup_and_grouping() -> None:
    p1 = create_sample_policy("pol_b", "v1", "feat_1", status=PolicyStatus.ACTIVE)
    p2 = create_sample_policy("pol_a", "v2", "feat_1", status=PolicyStatus.DRAFT)
    p3 = create_sample_policy("pol_c", "v1", "feat_2", status=PolicyStatus.ACTIVE)

    registry = InMemoryFeaturePolicyRegistry([p1, p2, p3])

    assert registry.get(PolicyId("pol_b"), PolicyVersion("v1")) == p1
    assert registry.get(PolicyId("pol_a"), PolicyVersion("v2")) == p2
    assert registry.get(PolicyId("nonexistent"), PolicyVersion("v1")) is None

    assert registry.get_active_for_feature(FeatureId("feat_1")) == p1
    assert registry.get_active_for_feature(FeatureId("feat_2")) == p3
    assert registry.get_active_for_feature(FeatureId("nonexistent")) is None

    all_policies = registry.list_all()
    assert len(all_policies) == 3
    # Deterministic ordering by (policy_id, version): pol_a/v2, pol_b/v1, pol_c/v1
    assert all_policies[0].policy_id == PolicyId("pol_a")
    assert all_policies[1].policy_id == PolicyId("pol_b")

    feat1_policies = registry.list_for_feature(FeatureId("feat_1"))
    assert len(feat1_policies) == 2


def test_duplicate_policy_version_rejection() -> None:
    p1 = create_sample_policy("pol_1", "v1", "feat_1")
    p1_dup = create_sample_policy("pol_1", "v1", "feat_2")

    with pytest.raises(RegistryConfigurationError) as exc_info:
        InMemoryFeaturePolicyRegistry([p1, p1_dup])

    assert any(i.code == "DUPLICATE_POLICY_VERSION" for i in exc_info.value.issues)


def test_multiple_active_policies_for_same_feature_rejected() -> None:
    p1 = create_sample_policy("pol_1", "v1", "feat_1", status=PolicyStatus.ACTIVE)
    p2 = create_sample_policy("pol_2", "v1", "feat_1", status=PolicyStatus.ACTIVE)

    with pytest.raises(RegistryConfigurationError) as exc_info:
        InMemoryFeaturePolicyRegistry([p1, p2])

    assert any(i.code == "MULTIPLE_ACTIVE_POLICIES" for i in exc_info.value.issues)


def test_caller_mutation_isolation() -> None:
    p1 = create_sample_policy("pol_1")
    input_list = [p1]

    registry = InMemoryFeaturePolicyRegistry(input_list)
    input_list.clear()

    assert registry.get(PolicyId("pol_1"), PolicyVersion("v1")) == p1
