"""Data structures and file loader for measured model quality and latency profiles."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from routeforge.contracts import ModelId


@dataclass(frozen=True, slots=True)
class MeasuredQualityProfile:
    """Measured performance metrics for a specific model and task type."""

    task_type: str
    measured_quality: float
    measured_pass_rate: float
    measured_median_latency_ms: int
    measured_p95_latency_ms: int
    sample_count: int
    benchmark_dataset_version: str = "v1"
    evaluator_version: str = "v1"
    source_benchmark_file: str = "two-model-baseline.jsonl"

    def __post_init__(self) -> None:
        if not self.task_type or not self.task_type.strip():
            raise ValueError("task_type cannot be empty.")
        if not (0.0 <= self.measured_quality <= 1.0):
            raise ValueError("measured_quality must be between 0.0 and 1.0.")
        if not (0.0 <= self.measured_pass_rate <= 1.0):
            raise ValueError("measured_pass_rate must be between 0.0 and 1.0.")
        if self.measured_median_latency_ms < 0:
            raise ValueError("measured_median_latency_ms cannot be negative.")
        if self.measured_p95_latency_ms < 0:
            raise ValueError("measured_p95_latency_ms cannot be negative.")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive.")


@dataclass(frozen=True, slots=True)
class MeasuredModelProfile:
    """Measured performance profile for a specific RouteForge model ID."""

    model_id: ModelId
    task_profiles: Mapping[str, MeasuredQualityProfile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not isinstance(self.task_profiles, MappingProxyType):
            object.__setattr__(
                self,
                "task_profiles",
                MappingProxyType(dict(self.task_profiles)),
            )


@dataclass(frozen=True, slots=True)
class ModelProfileRegistry:
    """Registry containing active measured model profiles."""

    profile_version: str
    profiles: Mapping[ModelId, MeasuredModelProfile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_version or not self.profile_version.strip():
            raise ValueError("profile_version cannot be empty.")
        if not isinstance(self.profiles, MappingProxyType):
            object.__setattr__(
                self,
                "profiles",
                MappingProxyType(dict(self.profiles)),
            )

    def get_quality_profile(
        self,
        model_id: ModelId,
        task_type: str,
    ) -> MeasuredQualityProfile | None:
        """Lookup measured quality profile for a given model ID and task type."""
        model_profile = self.profiles.get(model_id)
        if model_profile is None:
            return None
        return model_profile.task_profiles.get(task_type)


def load_model_profile_registry(data: dict[str, object]) -> ModelProfileRegistry:
    """Decode a ModelProfileRegistry from a raw dictionary snapshot."""
    profile_version = str(data.get("profile_version", "v1"))
    raw_profiles = data.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ValueError("Registry profiles must be a JSON object.")

    decoded_profiles: dict[ModelId, MeasuredModelProfile] = {}
    for model_id_str, raw_model in raw_profiles.items():
        if not isinstance(raw_model, dict):
            continue
        model_id = ModelId(model_id_str)
        raw_tasks = raw_model.get("task_profiles", {})
        if not isinstance(raw_tasks, dict):
            continue

        decoded_tasks: dict[str, MeasuredQualityProfile] = {}
        for task_type, raw_tp in raw_tasks.items():
            if not isinstance(raw_tp, dict):
                continue
            decoded_tasks[task_type] = MeasuredQualityProfile(
                task_type=task_type,
                measured_quality=float(raw_tp["measured_quality"]),
                measured_pass_rate=float(raw_tp["measured_pass_rate"]),
                measured_median_latency_ms=int(raw_tp["measured_median_latency_ms"]),
                measured_p95_latency_ms=int(raw_tp["measured_p95_latency_ms"]),
                sample_count=int(raw_tp["sample_count"]),
                benchmark_dataset_version=str(raw_tp.get("benchmark_dataset_version", "v1")),
                evaluator_version=str(raw_tp.get("evaluator_version", "v1")),
                source_benchmark_file=str(raw_tp.get("source_benchmark_file", "")),
            )

        decoded_profiles[model_id] = MeasuredModelProfile(
            model_id=model_id,
            task_profiles=decoded_tasks,
        )

    return ModelProfileRegistry(
        profile_version=profile_version,
        profiles=decoded_profiles,
    )


def load_model_profile_registry_file(file_path: str | Path) -> ModelProfileRegistry:
    """Load and parse ModelProfileRegistry from a JSON file."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model profile registry file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return load_model_profile_registry(data)
