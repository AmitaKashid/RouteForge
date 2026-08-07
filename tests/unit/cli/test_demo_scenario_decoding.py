"""Unit tests for scenario decoding logic in routeforge.cli."""

from pathlib import Path

import pytest

from routeforge.cli import DemoValidationError, decode_demo_scenario
from routeforge.registries import RegistrySnapshot, load_registry_snapshot


@pytest.fixture
def snapshot() -> RegistrySnapshot:
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return load_registry_snapshot(
        models_directory=repo_root / "config" / "models",
        policies_directory=repo_root / "config" / "policies",
    )


def test_valid_scenario_decoding(snapshot: RegistrySnapshot) -> None:
    valid_data = {
        "request": {
            "request_id": "req-1",
            "team_id": "team-1",
            "feature_id": "general-chat",
            "messages": [{"role": "USER", "content": "Hello"}],
            "output_format": "TEXT",
            "routing_constraints": {
                "minimum_quality": "0.75",
                "maximum_latency_ms": 500,
                "maximum_estimated_cost_usd": "0.010000",
                "required_capabilities": ["TEXT_CHAT"],
                "required_governance": "PUBLIC",
                "allow_degraded_provider": True,
            },
            "created_at": "2026-08-06T12:00:00Z",
        },
        "policy": {"use_active_for_feature": True},
        "candidates": [
            {
                "model_id": "mock-economy",
                "provider_state": "HEALTHY",
                "estimate": {
                    "predicted_quality": "0.80",
                    "estimated_latency_ms": 100,
                    "estimated_cost_usd": "0.001000",
                    "quality_provenance": {"source": "s", "version": "v"},
                    "latency_provenance": {"source": "s", "version": "v"},
                    "cost_provenance": {"source": "s", "version": "v"},
                },
            }
        ],
        "execution": {"attempt_id": "att-1", "timeout_ms": 1000},
        "decided_at": "2026-08-06T12:00:01Z",
    }
    scenario = decode_demo_scenario(valid_data, snapshot)
    assert scenario.request.request_id == "req-1"
    assert scenario.candidates[0].model.model_id == "mock-economy"


def test_decoding_validation_errors(snapshot: RegistrySnapshot) -> None:
    # Non-object root
    with pytest.raises(DemoValidationError, match="JSON root must be an object"):
        decode_demo_scenario([], snapshot)

    # Missing root key
    with pytest.raises(DemoValidationError, match="Missing required top-level field"):
        decode_demo_scenario({"request": {}}, snapshot)

    # Unknown root key
    with pytest.raises(DemoValidationError, match="Unknown top-level field"):
        decode_demo_scenario({"request": {}, "unknown": 123}, snapshot)

    # Invalid request object
    with pytest.raises(DemoValidationError, match="Field 'request' must be an object"):
        decode_demo_scenario(
            {
                "request": "invalid",
                "policy": {},
                "candidates": [],
                "execution": {},
                "decided_at": "2026-08-06T12:00:00Z",
            },
            snapshot,
        )

    # Float cost rejected
    float_cost_data = {
        "request": {
            "request_id": "req-1",
            "team_id": "t",
            "feature_id": "general-chat",
            "messages": [{"role": "USER", "content": "hi"}],
            "created_at": "2026-08-06T12:00:00Z",
        },
        "policy": {"use_active_for_feature": True},
        "candidates": [
            {
                "model_id": "mock-economy",
                "provider_state": "HEALTHY",
                "estimate": {
                    "predicted_quality": "0.80",
                    "estimated_latency_ms": 100,
                    "estimated_cost_usd": 0.001,  # float cost rejected!
                    "quality_provenance": {"source": "s", "version": "v"},
                    "latency_provenance": {"source": "s", "version": "v"},
                    "cost_provenance": {"source": "s", "version": "v"},
                },
            }
        ],
        "execution": {"attempt_id": "att-1", "timeout_ms": 1000},
        "decided_at": "2026-08-06T12:00:01Z",
    }
    with pytest.raises(DemoValidationError, match="cannot be a float JSON number"):
        decode_demo_scenario(float_cost_data, snapshot)

    # Timezone-naive timestamp rejected
    valid_scenario_data = {
        "request": {
            "request_id": "req-1",
            "team_id": "t",
            "feature_id": "general-chat",
            "messages": [{"role": "USER", "content": "hi"}],
            "created_at": "2026-08-06T12:00:00Z",
        },
        "policy": {"use_active_for_feature": True},
        "candidates": [
            {
                "model_id": "mock-economy",
                "provider_state": "HEALTHY",
                "estimate": {
                    "predicted_quality": "0.80",
                    "estimated_latency_ms": 100,
                    "estimated_cost_usd": "0.001000",
                    "quality_provenance": {"source": "s", "version": "v"},
                    "latency_provenance": {"source": "s", "version": "v"},
                    "cost_provenance": {"source": "s", "version": "v"},
                },
            }
        ],
        "execution": {"attempt_id": "att-1", "timeout_ms": 1000},
        "decided_at": "2026-08-06T12:00:01",  # naive timestamp!
    }
    with pytest.raises(DemoValidationError, match="must be timezone-aware"):
        decode_demo_scenario(valid_scenario_data, snapshot)

    # Unknown candidate model_id
    unknown_model_data = {
        "request": {
            "request_id": "req-1",
            "team_id": "t",
            "feature_id": "general-chat",
            "messages": [{"role": "USER", "content": "hi"}],
            "created_at": "2026-08-06T12:00:00Z",
        },
        "policy": {"use_active_for_feature": True},
        "candidates": [
            {
                "model_id": "nonexistent-model",
                "provider_state": "HEALTHY",
                "estimate": {
                    "predicted_quality": "0.80",
                    "estimated_latency_ms": 100,
                    "estimated_cost_usd": "0.001000",
                    "quality_provenance": {"source": "s", "version": "v"},
                    "latency_provenance": {"source": "s", "version": "v"},
                    "cost_provenance": {"source": "s", "version": "v"},
                },
            }
        ],
        "execution": {"attempt_id": "att-1", "timeout_ms": 1000},
        "decided_at": "2026-08-06T12:00:01Z",
    }
    with pytest.raises(DemoValidationError, match="not found in loaded ModelRegistry"):
        decode_demo_scenario(unknown_model_data, snapshot)

    # Missing active feature policy
    no_policy_data = {
        "request": {
            "request_id": "req-1",
            "team_id": "t",
            "feature_id": "nonexistent-feature",
            "messages": [{"role": "USER", "content": "hi"}],
            "created_at": "2026-08-06T12:00:00Z",
        },
        "policy": {"use_active_for_feature": True},
        "candidates": [
            {
                "model_id": "mock-economy",
                "provider_state": "HEALTHY",
                "estimate": {
                    "predicted_quality": "0.80",
                    "estimated_latency_ms": 100,
                    "estimated_cost_usd": "0.001000",
                    "quality_provenance": {"source": "s", "version": "v"},
                    "latency_provenance": {"source": "s", "version": "v"},
                    "cost_provenance": {"source": "s", "version": "v"},
                },
            }
        ],
        "execution": {"attempt_id": "att-1", "timeout_ms": 1000},
        "decided_at": "2026-08-06T12:00:01Z",
    }
    with pytest.raises(DemoValidationError, match="No active feature policy found"):
        decode_demo_scenario(no_policy_data, snapshot)
