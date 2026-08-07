"""Configuration-backed registries package."""

from routeforge.registries.errors import (
    ConfigurationIssue,
    ConfigurationIssueCode,
    RegistryConfigurationError,
)
from routeforge.registries.file_loader import RegistrySnapshot, load_registry_snapshot
from routeforge.registries.interfaces import FeaturePolicyRegistry, ModelRegistry
from routeforge.registries.memory import (
    InMemoryFeaturePolicyRegistry,
    InMemoryModelRegistry,
)

__all__ = [
    "ConfigurationIssue",
    "ConfigurationIssueCode",
    "FeaturePolicyRegistry",
    "InMemoryFeaturePolicyRegistry",
    "InMemoryModelRegistry",
    "ModelRegistry",
    "RegistryConfigurationError",
    "RegistrySnapshot",
    "load_registry_snapshot",
]
