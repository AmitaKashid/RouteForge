"""In-memory model and feature-policy registry implementations."""

from collections.abc import Iterable
from pathlib import Path

from routeforge.contracts.common import FeatureId, ModelId, PolicyId, PolicyVersion
from routeforge.contracts.models import ModelDefinition
from routeforge.contracts.policies import FeaturePolicy, PolicyStatus
from routeforge.registries.errors import (
    ConfigurationIssue,
    ConfigurationIssueCode,
    RegistryConfigurationError,
)
from routeforge.registries.interfaces import FeaturePolicyRegistry, ModelRegistry


class InMemoryModelRegistry(ModelRegistry):
    """In-memory immutable model registry."""

    def __init__(self, models: Iterable[ModelDefinition]) -> None:
        model_map: dict[ModelId, ModelDefinition] = {}
        issues: list[ConfigurationIssue] = []

        for model in models:
            if model.model_id in model_map:
                issues.append(
                    ConfigurationIssue(
                        code=ConfigurationIssueCode.DUPLICATE_MODEL_ID,
                        source_path=Path("memory"),
                        field_path="model_id",
                        message=f"Duplicate model_id '{model.model_id}' found in registry.",
                    )
                )
            else:
                model_map[model.model_id] = model

        if issues:
            raise RegistryConfigurationError(issues)

        # Sort map deterministically by model_id string
        sorted_keys = sorted(model_map.keys(), key=lambda m: str(m))
        self._models: dict[ModelId, ModelDefinition] = {k: model_map[k] for k in sorted_keys}

    def get(self, model_id: ModelId) -> ModelDefinition | None:
        """Lookup model definition by ID. Returns None if not found."""
        return self._models.get(model_id)

    def list_all(self) -> tuple[ModelDefinition, ...]:
        """List all model definitions ordered deterministically by model ID."""
        return tuple(self._models.values())

    def list_enabled(self) -> tuple[ModelDefinition, ...]:
        """List all enabled model definitions ordered deterministically by model ID."""
        return tuple(m for m in self._models.values() if m.enabled)


class InMemoryFeaturePolicyRegistry(FeaturePolicyRegistry):
    """In-memory immutable feature policy registry."""

    def __init__(self, policies: Iterable[FeaturePolicy]) -> None:
        policy_map: dict[tuple[PolicyId, PolicyVersion], FeaturePolicy] = {}
        active_map: dict[FeatureId, FeaturePolicy] = {}
        issues: list[ConfigurationIssue] = []

        for policy in policies:
            key = (policy.policy_id, policy.version)
            if key in policy_map:
                issues.append(
                    ConfigurationIssue(
                        code=ConfigurationIssueCode.DUPLICATE_POLICY_VERSION,
                        source_path=Path("memory"),
                        field_path="policy_id",
                        message=(
                            f"Duplicate policy_id/version '{policy.policy_id}'/'{policy.version}' "
                            "found in registry."
                        ),
                    )
                )
            else:
                policy_map[key] = policy

            if policy.status == PolicyStatus.ACTIVE:
                if policy.feature_id in active_map:
                    issues.append(
                        ConfigurationIssue(
                            code=ConfigurationIssueCode.MULTIPLE_ACTIVE_POLICIES,
                            source_path=Path("memory"),
                            field_path="feature_id",
                            message=f"Multiple active policies for feature '{policy.feature_id}'.",
                        )
                    )
                else:
                    active_map[policy.feature_id] = policy

        if issues:
            raise RegistryConfigurationError(issues)

        # Sort map deterministically by policy_id and version string
        sorted_keys = sorted(policy_map.keys(), key=lambda k: (str(k[0]), str(k[1])))
        self._policies: dict[tuple[PolicyId, PolicyVersion], FeaturePolicy] = {
            k: policy_map[k] for k in sorted_keys
        }
        self._active_policies: dict[FeatureId, FeaturePolicy] = dict(active_map)

    def get(
        self,
        policy_id: PolicyId,
        version: PolicyVersion,
    ) -> FeaturePolicy | None:
        """Lookup policy by policy ID and version. Returns None if not found."""
        return self._policies.get((policy_id, version))

    def get_active_for_feature(
        self,
        feature_id: FeatureId,
    ) -> FeaturePolicy | None:
        """Lookup active policy for feature ID. Returns None if none is active."""
        return self._active_policies.get(feature_id)

    def list_all(self) -> tuple[FeaturePolicy, ...]:
        """List all policies ordered deterministically by policy ID and version."""
        return tuple(self._policies.values())

    def list_for_feature(
        self,
        feature_id: FeatureId,
    ) -> tuple[FeaturePolicy, ...]:
        """List all policies for feature ID ordered deterministically by version."""
        matching = [p for p in self._policies.values() if p.feature_id == feature_id]
        matching.sort(key=lambda p: (str(p.policy_id), str(p.version)))
        return tuple(matching)
