"""Unit tests for JSON model and policy decoding functions."""

from pathlib import Path

import pytest

from routeforge.contracts import Capability, GovernanceClassification, PolicyStatus
from routeforge.registries.decoding import (
    decode_feature_policy,
    decode_model_definition,
)
from routeforge.registries.errors import RegistryConfigurationError


def test_decode_valid_model_definition() -> None:
    data = {
        "model_id": "m1",
        "provider_id": "p1",
        "display_name": "Model One",
        "capabilities": ["TEXT_CHAT"],
        "governance_allowed": ["PUBLIC"],
        "context_window_tokens": 8000,
        "estimated_input_cost_per_million_tokens_usd": "1.50",
        "estimated_output_cost_per_million_tokens_usd": "3.00",
        "estimated_latency_ms": 300,
        "quality_profiles": [
            {
                "task_type": "coding",
                "predicted_quality": 0.85,
                "source": "bench",
                "version": "v1",
            }
        ],
        "enabled": True,
        "configuration_version": "v1",
    }
    model = decode_model_definition(data, source_path=Path("model.json"))
    assert model.model_id == "m1"
    assert model.capabilities == (Capability.TEXT_CHAT,)
    assert model.governance_allowed == (GovernanceClassification.PUBLIC,)


def test_decode_model_definition_invalid_field_types_and_missing_fields() -> None:
    # Missing required field
    with pytest.raises(RegistryConfigurationError) as exc:
        decode_model_definition({}, source_path=Path("model.json"))
    assert any(i.code == "MISSING_FIELD" for i in exc.value.issues)

    # Unknown field
    with pytest.raises(RegistryConfigurationError) as exc:
        decode_model_definition({"unknown_key": 123}, source_path=Path("model.json"))
    assert any(i.code == "UNKNOWN_FIELD" for i in exc.value.issues)

    # Float cost rejected (must be decimal string)
    invalid_cost_data = {
        "model_id": "m1",
        "provider_id": "p1",
        "display_name": "Model One",
        "capabilities": ["TEXT_CHAT"],
        "governance_allowed": ["PUBLIC"],
        "context_window_tokens": 8000,
        "estimated_input_cost_per_million_tokens_usd": 1.5,  # float instead of string!
        "estimated_output_cost_per_million_tokens_usd": "3.00",
        "estimated_latency_ms": 300,
        "quality_profiles": [
            {
                "task_type": "coding",
                "predicted_quality": 0.85,
                "source": "bench",
                "version": "v1",
            }
        ],
        "enabled": True,
        "configuration_version": "v1",
    }
    with pytest.raises(RegistryConfigurationError) as exc:
        decode_model_definition(invalid_cost_data, source_path=Path("model.json"))
    assert any(i.code == "INVALID_DECIMAL" for i in exc.value.issues)


def test_decode_valid_feature_policy() -> None:
    data = {
        "policy_id": "pol_1",
        "version": "v1",
        "feature_id": "feat_1",
        "status": "ACTIVE",
        "allowed_model_ids": ["m1", "m2"],
        "required_capabilities": ["TEXT_CHAT"],
        "minimum_quality": 0.80,
        "maximum_latency_ms": 500,
        "maximum_estimated_cost_usd": "0.05",
        "maximum_governance_classification": "INTERNAL",
        "allow_degraded_providers": False,
        "fallback_policy": {"enabled": False, "maximum_fallback_attempts": 0},
        "created_at": "2026-08-06T12:00:00Z",
        "pinned_model_id": "m1",
    }
    policy = decode_feature_policy(data, source_path=Path("policy.json"))
    assert policy.policy_id == "pol_1"
    assert policy.status == PolicyStatus.ACTIVE
    assert policy.pinned_model_id == "m1"


def test_decode_policy_invalid_enum_and_timezone_naive() -> None:
    data = {
        "policy_id": "pol_1",
        "version": "v1",
        "feature_id": "feat_1",
        "status": "INVALID_STATUS",  # Bad enum
        "allowed_model_ids": ["m1"],
        "required_capabilities": ["TEXT_CHAT"],
        "minimum_quality": 0.80,
        "maximum_latency_ms": 500,
        "maximum_estimated_cost_usd": "0.05",
        "maximum_governance_classification": "INTERNAL",
        "allow_degraded_providers": False,
        "fallback_policy": {"enabled": False, "maximum_fallback_attempts": 0},
        "created_at": "2026-08-06T12:00:00",  # Naive datetime!
    }
    with pytest.raises(RegistryConfigurationError) as exc:
        decode_feature_policy(data, source_path=Path("policy.json"))

    codes = [i.code for i in exc.value.issues]
    assert "INVALID_ENUM_VALUE" in codes
    assert "INVALID_DATETIME" in codes
