"""Unit tests for measured model profiles and registry loader."""

from pathlib import Path

import pytest

from routeforge.contracts import ModelId
from routeforge.evaluation import (
    MeasuredModelProfile,
    MeasuredQualityProfile,
    ModelProfileRegistry,
    load_model_profile_registry_file,
)


def test_measured_quality_profile_invariants() -> None:
    qp = MeasuredQualityProfile(
        task_type="classification",
        measured_quality=0.95,
        measured_pass_rate=0.90,
        measured_median_latency_ms=120,
        measured_p95_latency_ms=150,
        sample_count=10,
    )
    assert qp.task_type == "classification"
    assert qp.measured_quality == 0.95

    with pytest.raises(ValueError, match="measured_quality must be between"):
        MeasuredQualityProfile(
            task_type="c",
            measured_quality=1.5,
            measured_pass_rate=0.9,
            measured_median_latency_ms=10,
            measured_p95_latency_ms=20,
            sample_count=5,
        )


def test_model_profile_registry_lookup() -> None:
    qp = MeasuredQualityProfile(
        task_type="classification",
        measured_quality=0.85,
        measured_pass_rate=0.80,
        measured_median_latency_ms=100,
        measured_p95_latency_ms=120,
        sample_count=8,
    )
    mp = MeasuredModelProfile(
        model_id=ModelId("ollama-economy"),
        task_profiles={"classification": qp},
    )
    registry = ModelProfileRegistry(
        profile_version="v1",
        profiles={ModelId("ollama-economy"): mp},
    )

    found = registry.get_quality_profile(ModelId("ollama-economy"), "classification")
    assert found is not None
    assert found.measured_quality == 0.85

    missing_task = registry.get_quality_profile(ModelId("ollama-economy"), "summarization")
    assert missing_task is None

    missing_model = registry.get_quality_profile(ModelId("unknown-model"), "classification")
    assert missing_model is None


def test_load_model_profile_registry_file() -> None:
    path = Path("config/profiles/routing-profile-v1.json")
    if path.is_file():
        registry = load_model_profile_registry_file(path)
        assert registry.profile_version == "routing-profile-v1"
        assert ModelId("ollama-economy") in registry.profiles
        assert ModelId("ollama-quality") in registry.profiles
