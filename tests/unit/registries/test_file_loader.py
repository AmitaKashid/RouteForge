"""Unit tests for load_registry_snapshot file loader."""

import json
from pathlib import Path

import pytest

from routeforge.registries import RegistryConfigurationError, load_registry_snapshot


def test_load_snapshot_successful(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    policies_dir = tmp_path / "policies"
    models_dir.mkdir()
    policies_dir.mkdir()

    model_data = {
        "model_id": "m1",
        "provider_id": "p1",
        "display_name": "Model 1",
        "capabilities": ["TEXT_CHAT"],
        "governance_allowed": ["PUBLIC"],
        "context_window_tokens": 4000,
        "estimated_input_cost_per_million_tokens_usd": "1.00",
        "estimated_output_cost_per_million_tokens_usd": "2.00",
        "estimated_latency_ms": 100,
        "quality_profiles": [
            {
                "task_type": "gen",
                "predicted_quality": 0.8,
                "source": "s",
                "version": "v1",
            }
        ],
        "enabled": True,
        "configuration_version": "v1",
    }
    with open(models_dir / "m1.json", "w", encoding="utf-8") as f:
        json.dump(model_data, f)

    policy_data = {
        "policy_id": "pol_1",
        "version": "v1",
        "feature_id": "feat_1",
        "status": "ACTIVE",
        "allowed_model_ids": ["m1"],
        "required_capabilities": ["TEXT_CHAT"],
        "minimum_quality": 0.5,
        "maximum_latency_ms": 500,
        "maximum_estimated_cost_usd": "10.00",
        "maximum_governance_classification": "PUBLIC",
        "allow_degraded_providers": False,
        "fallback_policy": {"enabled": False, "maximum_fallback_attempts": 0},
        "created_at": "2026-08-06T00:00:00Z",
    }
    with open(policies_dir / "p1.json", "w", encoding="utf-8") as f:
        json.dump(policy_data, f)

    snapshot = load_registry_snapshot(
        models_directory=models_dir,
        policies_directory=policies_dir,
    )
    assert snapshot.models.get("m1") is not None  # type: ignore[arg-type]
    assert snapshot.policies.get_active_for_feature("feat_1") is not None  # type: ignore[arg-type]


def test_missing_directories(tmp_path: Path) -> None:
    with pytest.raises(RegistryConfigurationError) as exc:
        load_registry_snapshot(
            models_directory=tmp_path / "missing_models",
            policies_directory=tmp_path / "missing_policies",
        )
    assert any(i.code == "DIRECTORY_NOT_FOUND" for i in exc.value.issues)


def test_empty_directories(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    policies_dir = tmp_path / "policies"
    models_dir.mkdir()
    policies_dir.mkdir()

    with pytest.raises(RegistryConfigurationError) as exc:
        load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
    assert any(i.code == "FILE_NOT_FOUND" for i in exc.value.issues)


def test_malformed_json_and_non_object_root(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    policies_dir = tmp_path / "policies"
    models_dir.mkdir()
    policies_dir.mkdir()

    with open(models_dir / "bad.json", "w", encoding="utf-8") as f:
        f.write("{ invalid json")

    with open(policies_dir / "array.json", "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")

    with pytest.raises(RegistryConfigurationError) as exc:
        load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
    codes = [i.code for i in exc.value.issues]
    assert "INVALID_JSON" in codes
    assert "INVALID_ROOT_TYPE" in codes


def test_malformed_policy_json_and_array_model_root(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    policies_dir = tmp_path / "policies"
    models_dir.mkdir()
    policies_dir.mkdir()

    with open(models_dir / "array.json", "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")

    with open(policies_dir / "bad.json", "w", encoding="utf-8") as f:
        f.write("{ invalid policy json")

    with pytest.raises(RegistryConfigurationError) as exc:
        load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
    codes = [i.code for i in exc.value.issues]
    assert "INVALID_ROOT_TYPE" in codes
    assert "INVALID_JSON" in codes


def test_decoding_error_propagation_in_file_loader(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    policies_dir = tmp_path / "policies"
    models_dir.mkdir()
    policies_dir.mkdir()

    # Model missing required field
    with open(models_dir / "m_invalid.json", "w", encoding="utf-8") as f:
        f.write('{"model_id": "m1"}')

    # Policy missing required field
    with open(policies_dir / "p_invalid.json", "w", encoding="utf-8") as f:
        f.write('{"policy_id": "p1"}')

    with pytest.raises(RegistryConfigurationError) as exc:
        load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
    assert len(exc.value.issues) >= 2
