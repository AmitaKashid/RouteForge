"""Cross-reference validation between model definitions and feature policies."""

from collections.abc import Mapping
from pathlib import Path

from routeforge.contracts.policies import PolicyStatus
from routeforge.registries.errors import (
    ConfigurationIssue,
    ConfigurationIssueCode,
    RegistryConfigurationError,
)
from routeforge.registries.interfaces import FeaturePolicyRegistry, ModelRegistry


def validate_cross_references(
    models: ModelRegistry,
    policies: FeaturePolicyRegistry,
    source_paths: Mapping[object, Path] | None = None,
) -> None:
    """Validate cross-references between feature policies and model definitions.

    Enforces:
    - Every model referenced in allowed_model_ids exists.
    - Every pinned_model_id exists and is allowed.
    - Every active feature policy has at least one enabled model in its allowed_model_ids.
    """
    issues: list[ConfigurationIssue] = []

    all_models = {m.model_id: m for m in models.list_all()}

    for policy in policies.list_all():
        path = (
            source_paths.get(policy, Path("policy.json")) if source_paths else Path("policy.json")
        )

        has_enabled_model = False
        for model_id in policy.allowed_model_ids:
            if model_id not in all_models:
                issues.append(
                    ConfigurationIssue(
                        code=ConfigurationIssueCode.UNKNOWN_MODEL_REFERENCE,
                        source_path=path,
                        field_path="allowed_model_ids",
                        message=(
                            f"Policy '{policy.policy_id}' version '{policy.version}' references "
                            f"unknown model_id '{model_id}'."
                        ),
                    )
                )
            else:
                if all_models[model_id].enabled:
                    has_enabled_model = True

        if policy.pinned_model_id is not None:
            if policy.pinned_model_id not in all_models:
                issues.append(
                    ConfigurationIssue(
                        code=ConfigurationIssueCode.PINNED_MODEL_REFERENCE_MISSING,
                        source_path=path,
                        field_path="pinned_model_id",
                        message=(
                            f"Policy '{policy.policy_id}' version '{policy.version}' pins "
                            f"missing model_id '{policy.pinned_model_id}'."
                        ),
                    )
                )

        if policy.status == PolicyStatus.ACTIVE and not has_enabled_model:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.NO_ENABLED_MODEL_FOR_ACTIVE_POLICY,
                    source_path=path,
                    field_path="status",
                    message=(
                        f"Active policy '{policy.policy_id}' v'{policy.version}' for "
                        f"'{policy.feature_id}' has no enabled models in allowed_model_ids."
                    ),
                )
            )

    if issues:
        raise RegistryConfigurationError(issues)
