"""Provider-neutral model and feature-policy registry protocols."""

from typing import Protocol

from routeforge.contracts.common import FeatureId, ModelId, PolicyId, PolicyVersion
from routeforge.contracts.models import ModelDefinition
from routeforge.contracts.policies import FeaturePolicy


class ModelRegistry(Protocol):
    """Immutable registry interface for model definitions."""

    def get(self, model_id: ModelId) -> ModelDefinition | None:
        """Lookup model definition by ID. Returns None if not found."""
        ...

    def list_all(self) -> tuple[ModelDefinition, ...]:
        """List all model definitions ordered deterministically by model ID."""
        ...

    def list_enabled(self) -> tuple[ModelDefinition, ...]:
        """List all enabled model definitions ordered deterministically by model ID."""
        ...


class FeaturePolicyRegistry(Protocol):
    """Immutable registry interface for feature routing policies."""

    def get(
        self,
        policy_id: PolicyId,
        version: PolicyVersion,
    ) -> FeaturePolicy | None:
        """Lookup policy by policy ID and version. Returns None if not found."""
        ...

    def get_active_for_feature(
        self,
        feature_id: FeatureId,
    ) -> FeaturePolicy | None:
        """Lookup active policy for feature ID. Returns None if none is active."""
        ...

    def list_all(self) -> tuple[FeaturePolicy, ...]:
        """List all policies ordered deterministically by policy ID and version."""
        ...

    def list_for_feature(
        self,
        feature_id: FeatureId,
    ) -> tuple[FeaturePolicy, ...]:
        """List all policies for feature ID ordered deterministically by version."""
        ...
