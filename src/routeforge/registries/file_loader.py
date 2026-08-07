"""JSON file loader constructing immutable registry snapshots."""

import json
from dataclasses import dataclass
from pathlib import Path

from routeforge.contracts.models import ModelDefinition
from routeforge.contracts.policies import FeaturePolicy
from routeforge.registries.decoding import decode_feature_policy, decode_model_definition
from routeforge.registries.errors import (
    ConfigurationIssue,
    ConfigurationIssueCode,
    RegistryConfigurationError,
)
from routeforge.registries.interfaces import FeaturePolicyRegistry, ModelRegistry
from routeforge.registries.memory import (
    InMemoryFeaturePolicyRegistry,
    InMemoryModelRegistry,
)
from routeforge.registries.validation import validate_cross_references


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Immutable snapshot holding loaded model and feature policy registries."""

    models: ModelRegistry
    policies: FeaturePolicyRegistry


def load_registry_snapshot(
    *,
    models_directory: Path,
    policies_directory: Path,
) -> RegistrySnapshot:
    """Load, decode, and validate registry snapshot from local JSON directories."""
    issues: list[ConfigurationIssue] = []

    if not models_directory.exists() or not models_directory.is_dir():
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.DIRECTORY_NOT_FOUND,
                source_path=models_directory,
                message=f"Models directory '{models_directory}' does not exist.",
            )
        )

    if not policies_directory.exists() or not policies_directory.is_dir():
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.DIRECTORY_NOT_FOUND,
                source_path=policies_directory,
                message=f"Policies directory '{policies_directory}' does not exist.",
            )
        )

    if issues:
        raise RegistryConfigurationError(issues)

    model_files = sorted(
        p for p in models_directory.iterdir() if p.is_file() and p.name.endswith(".json")
    )
    policy_files = sorted(
        p for p in policies_directory.iterdir() if p.is_file() and p.name.endswith(".json")
    )

    if not model_files:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.FILE_NOT_FOUND,
                source_path=models_directory,
                message=f"No JSON configuration files in models directory '{models_directory}'.",
            )
        )

    if not policy_files:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.FILE_NOT_FOUND,
                source_path=policies_directory,
                message=f"No JSON files in policies directory '{policies_directory}'.",
            )
        )

    if issues:
        raise RegistryConfigurationError(issues)

    decoded_models: list[ModelDefinition] = []
    decoded_policies: list[FeaturePolicy] = []
    source_paths: dict[object, Path] = {}

    for file_path in model_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as err:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_JSON,
                    source_path=file_path,
                    message=f"Malformed JSON document: {err}",
                )
            )
            continue
        except Exception as err:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_JSON,
                    source_path=file_path,
                    message=f"Could not read JSON file: {err}",
                )
            )
            continue

        if not isinstance(raw_data, dict):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_ROOT_TYPE,
                    source_path=file_path,
                    message=f"JSON root must be an object, got {type(raw_data).__name__}.",
                )
            )
            continue

        try:
            model = decode_model_definition(raw_data, source_path=file_path)
            decoded_models.append(model)
            source_paths[model] = file_path
        except RegistryConfigurationError as err:
            issues.extend(err.issues)

    for file_path in policy_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as err:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_JSON,
                    source_path=file_path,
                    message=f"Malformed JSON document: {err}",
                )
            )
            continue
        except Exception as err:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_JSON,
                    source_path=file_path,
                    message=f"Could not read JSON file: {err}",
                )
            )
            continue

        if not isinstance(raw_data, dict):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_ROOT_TYPE,
                    source_path=file_path,
                    message=f"JSON root must be an object, got {type(raw_data).__name__}.",
                )
            )
            continue

        try:
            policy = decode_feature_policy(raw_data, source_path=file_path)
            decoded_policies.append(policy)
            source_paths[policy] = file_path
        except RegistryConfigurationError as err:
            issues.extend(err.issues)

    if issues:
        raise RegistryConfigurationError(issues)

    try:
        model_registry = InMemoryModelRegistry(decoded_models)
    except RegistryConfigurationError as err:
        issues.extend(err.issues)

    try:
        policy_registry = InMemoryFeaturePolicyRegistry(decoded_policies)
    except RegistryConfigurationError as err:
        issues.extend(err.issues)

    if issues:
        raise RegistryConfigurationError(issues)

    validate_cross_references(model_registry, policy_registry, source_paths=source_paths)

    return RegistrySnapshot(models=model_registry, policies=policy_registry)
