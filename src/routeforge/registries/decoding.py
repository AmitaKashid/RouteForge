"""Strict JSON decoding functions converting raw configuration objects to domain contracts."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import TypeVar

from routeforge.contracts import (
    Capability,
    CircuitBreakerPolicy,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    PolicyId,
    PolicyStatus,
    PolicyVersion,
    ProviderId,
    QualityProfile,
    RetryPolicy,
    VerificationPolicy,
    VerificationStrategy,
)
from routeforge.registries.errors import (
    ConfigurationIssue,
    ConfigurationIssueCode,
    RegistryConfigurationError,
)

E = TypeVar("E", bound=Enum)


def _check_known_fields(
    data: Mapping[str, object],
    allowed_fields: set[str],
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> None:
    for key in data.keys():
        if key not in allowed_fields:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.UNKNOWN_FIELD,
                    source_path=source_path,
                    field_path=key,
                    message=f"Unknown field '{key}' found in configuration.",
                )
            )


def _get_required_field(
    data: Mapping[str, object],
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> object | None:
    if field_name not in data:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.MISSING_FIELD,
                source_path=source_path,
                field_path=field_name,
                message=f"Missing required field '{field_name}'.",
            )
        )
        return None
    return data[field_name]


def _decode_str(
    val: object,
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> str | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, str):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                source_path=source_path,
                field_path=field_name,
                message=f"Field '{field_name}' must be a string, got {type(val).__name__}.",
            )
        )
        return None
    return val


def _decode_int(
    val: object,
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> int | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                source_path=source_path,
                field_path=field_name,
                message=f"Field '{field_name}' must be an integer, got {type(val).__name__}.",
            )
        )
        return None
    return val


def _decode_float(
    val: object,
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> float | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                source_path=source_path,
                field_path=field_name,
                message=f"Field '{field_name}' must be a number, got {type(val).__name__}.",
            )
        )
        return None
    return float(val)


def _decode_bool(
    val: object,
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> bool | None:
    if val is None:
        return None
    if not isinstance(val, bool):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                source_path=source_path,
                field_path=field_name,
                message=f"Field '{field_name}' must be a boolean, got {type(val).__name__}.",
            )
        )
        return None
    return val


def _decode_decimal(
    val: object,
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> Decimal | None:
    if val is None:
        return None
    if isinstance(val, (float, int, bool)) or not isinstance(val, str):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_DECIMAL,
                source_path=source_path,
                field_path=field_name,
                message=(
                    f"Monetary field '{field_name}' must be a decimal string, "
                    f"got {type(val).__name__}."
                ),
            )
        )
        return None
    try:
        return Decimal(val)
    except InvalidOperation:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_DECIMAL,
                source_path=source_path,
                field_path=field_name,
                message=f"Field '{field_name}' contains invalid decimal string '{val}'.",
            )
        )
        return None


def _decode_datetime(
    val: object,
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, str):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_DATETIME,
                source_path=source_path,
                field_path=field_name,
                message=f"Datetime field '{field_name}' must be an ISO 8601 string.",
            )
        )
        return None
    try:
        iso_str = val.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_DATETIME,
                    source_path=source_path,
                    field_path=field_name,
                    message=f"Datetime field '{field_name}' must be timezone-aware UTC.",
                )
            )
            return None
        return dt
    except ValueError:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_DATETIME,
                source_path=source_path,
                field_path=field_name,
                message=f"Field '{field_name}' contains invalid ISO 8601 datetime '{val}'.",
            )
        )
        return None


def _decode_enum[E: Enum](
    val: object,
    enum_cls: type[E],
    field_name: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> E | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, str):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_ENUM_VALUE,
                source_path=source_path,
                field_path=field_name,
                message=f"Enum field '{field_name}' must be a string.",
            )
        )
        return None
    try:
        return enum_cls(val)
    except ValueError:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_ENUM_VALUE,
                source_path=source_path,
                field_path=field_name,
                message=(
                    f"Field '{field_name}' value '{val}' is not a valid {enum_cls.__name__} value. "
                    f"Allowed: {[e.value for e in enum_cls]}"
                ),
            )
        )
        return None


def _decode_quality_profile(
    data: object,
    field_path: str,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> QualityProfile | None:
    if not isinstance(data, dict):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                source_path=source_path,
                field_path=field_path,
                message=f"QualityProfile '{field_path}' must be an object.",
            )
        )
        return None

    _check_known_fields(
        data,
        {"task_type", "predicted_quality", "source", "version"},
        source_path,
        issues,
    )
    raw_task = _get_required_field(data, "task_type", source_path, issues)
    raw_quality = _get_required_field(data, "predicted_quality", source_path, issues)
    raw_source = _get_required_field(data, "source", source_path, issues)
    raw_version = _get_required_field(data, "version", source_path, issues)

    task_type = _decode_str(raw_task, f"{field_path}.task_type", source_path, issues)
    quality = _decode_float(raw_quality, f"{field_path}.predicted_quality", source_path, issues)
    src = _decode_str(raw_source, f"{field_path}.source", source_path, issues)
    ver = _decode_str(raw_version, f"{field_path}.version", source_path, issues)

    if task_type is None or quality is None or src is None or ver is None:
        return None

    try:
        return QualityProfile(
            task_type=task_type,
            predicted_quality=quality,
            source=src,
            version=ver,
        )
    except ValueError as err:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                source_path=source_path,
                field_path=field_path,
                message=str(err),
            )
        )
        return None


def decode_model_definition(
    data: Mapping[str, object],
    *,
    source_path: Path,
) -> ModelDefinition:
    """Decode raw JSON dict into ModelDefinition domain contract."""
    issues: list[ConfigurationIssue] = []

    allowed = {
        "model_id",
        "provider_id",
        "display_name",
        "capabilities",
        "governance_allowed",
        "context_window_tokens",
        "estimated_input_cost_per_million_tokens_usd",
        "estimated_output_cost_per_million_tokens_usd",
        "estimated_latency_ms",
        "quality_profiles",
        "enabled",
        "configuration_version",
    }
    _check_known_fields(data, allowed, source_path, issues)

    raw_model_id = _get_required_field(data, "model_id", source_path, issues)
    raw_provider_id = _get_required_field(data, "provider_id", source_path, issues)
    raw_display_name = _get_required_field(data, "display_name", source_path, issues)
    raw_capabilities = _get_required_field(data, "capabilities", source_path, issues)
    raw_governance = _get_required_field(data, "governance_allowed", source_path, issues)
    raw_ctx = _get_required_field(data, "context_window_tokens", source_path, issues)
    raw_input_cost = _get_required_field(
        data, "estimated_input_cost_per_million_tokens_usd", source_path, issues
    )
    raw_output_cost = _get_required_field(
        data, "estimated_output_cost_per_million_tokens_usd", source_path, issues
    )
    raw_latency = _get_required_field(data, "estimated_latency_ms", source_path, issues)
    raw_profiles = _get_required_field(data, "quality_profiles", source_path, issues)
    raw_enabled = _get_required_field(data, "enabled", source_path, issues)
    raw_cfg_ver = _get_required_field(data, "configuration_version", source_path, issues)

    model_id_str = _decode_str(raw_model_id, "model_id", source_path, issues)
    provider_id_str = _decode_str(raw_provider_id, "provider_id", source_path, issues)
    display_name = _decode_str(raw_display_name, "display_name", source_path, issues)

    capabilities: list[Capability] = []
    if raw_capabilities is not None:
        if not isinstance(raw_capabilities, list):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="capabilities",
                    message="Field 'capabilities' must be an array.",
                )
            )
        else:
            for idx, cap_val in enumerate(raw_capabilities):
                cap_enum = _decode_enum(
                    cap_val, Capability, f"capabilities[{idx}]", source_path, issues
                )
                if cap_enum is not None:
                    capabilities.append(cap_enum)

    governance: list[GovernanceClassification] = []
    if raw_governance is not None:
        if not isinstance(raw_governance, list):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="governance_allowed",
                    message="Field 'governance_allowed' must be an array.",
                )
            )
        else:
            for idx, gov_val in enumerate(raw_governance):
                gov_enum = _decode_enum(
                    gov_val,
                    GovernanceClassification,
                    f"governance_allowed[{idx}]",
                    source_path,
                    issues,
                )
                if gov_enum is not None:
                    governance.append(gov_enum)

    ctx_tokens = _decode_int(raw_ctx, "context_window_tokens", source_path, issues)
    input_cost = _decode_decimal(
        raw_input_cost,
        "estimated_input_cost_per_million_tokens_usd",
        source_path,
        issues,
    )
    output_cost = _decode_decimal(
        raw_output_cost,
        "estimated_output_cost_per_million_tokens_usd",
        source_path,
        issues,
    )
    latency_ms = _decode_int(raw_latency, "estimated_latency_ms", source_path, issues)

    quality_profiles: list[QualityProfile] = []
    if raw_profiles is not None:
        if not isinstance(raw_profiles, list):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="quality_profiles",
                    message="Field 'quality_profiles' must be an array.",
                )
            )
        else:
            for idx, prof_val in enumerate(raw_profiles):
                qp = _decode_quality_profile(
                    prof_val, f"quality_profiles[{idx}]", source_path, issues
                )
                if qp is not None:
                    quality_profiles.append(qp)

    enabled = _decode_bool(raw_enabled, "enabled", source_path, issues)
    cfg_ver = _decode_str(raw_cfg_ver, "configuration_version", source_path, issues)

    if issues:
        raise RegistryConfigurationError(issues)

    assert model_id_str is not None
    assert provider_id_str is not None
    assert display_name is not None
    assert ctx_tokens is not None
    assert input_cost is not None
    assert output_cost is not None
    assert latency_ms is not None
    assert enabled is not None
    assert cfg_ver is not None

    try:
        return ModelDefinition(
            model_id=ModelId(model_id_str),
            provider_id=ProviderId(provider_id_str),
            display_name=display_name,
            capabilities=tuple(capabilities),
            governance_allowed=tuple(governance),
            context_window_tokens=ctx_tokens,
            estimated_input_cost_per_million_tokens_usd=input_cost,
            estimated_output_cost_per_million_tokens_usd=output_cost,
            estimated_latency_ms=latency_ms,
            quality_profiles=tuple(quality_profiles),
            enabled=enabled,
            configuration_version=cfg_ver,
        )
    except ValueError as err:
        raise RegistryConfigurationError(
            [
                ConfigurationIssue(
                    code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                    source_path=source_path,
                    message=str(err),
                )
            ]
        ) from err


def decode_feature_policy(
    data: Mapping[str, object],
    *,
    source_path: Path,
) -> FeaturePolicy:
    """Decode raw JSON dict into FeaturePolicy domain contract."""
    issues: list[ConfigurationIssue] = []

    allowed = {
        "policy_id",
        "version",
        "feature_id",
        "status",
        "allowed_model_ids",
        "required_capabilities",
        "minimum_quality",
        "maximum_latency_ms",
        "maximum_estimated_cost_usd",
        "maximum_governance_classification",
        "allow_degraded_providers",
        "retry_policy",
        "fallback_policy",
        "circuit_breaker_policy",
        "verification_policy",
        "created_at",
        "pinned_model_id",
    }
    _check_known_fields(data, allowed, source_path, issues)

    raw_policy_id = _get_required_field(data, "policy_id", source_path, issues)
    raw_version = _get_required_field(data, "version", source_path, issues)
    raw_feature_id = _get_required_field(data, "feature_id", source_path, issues)
    raw_status = _get_required_field(data, "status", source_path, issues)
    raw_allowed_models = _get_required_field(data, "allowed_model_ids", source_path, issues)
    raw_capabilities = _get_required_field(data, "required_capabilities", source_path, issues)
    raw_quality = _get_required_field(data, "minimum_quality", source_path, issues)
    raw_latency = _get_required_field(data, "maximum_latency_ms", source_path, issues)
    raw_cost = _get_required_field(data, "maximum_estimated_cost_usd", source_path, issues)
    raw_gov = _get_required_field(data, "maximum_governance_classification", source_path, issues)
    raw_allow_degraded = _get_required_field(data, "allow_degraded_providers", source_path, issues)
    raw_retry = data.get("retry_policy")
    raw_fallback = _get_required_field(data, "fallback_policy", source_path, issues)
    raw_cb = data.get("circuit_breaker_policy")
    raw_vp = data.get("verification_policy")
    raw_created_at = _get_required_field(data, "created_at", source_path, issues)
    raw_pinned = data.get("pinned_model_id")

    policy_id_str = _decode_str(raw_policy_id, "policy_id", source_path, issues)
    version_str = _decode_str(raw_version, "version", source_path, issues)
    feature_id_str = _decode_str(raw_feature_id, "feature_id", source_path, issues)
    status_enum = _decode_enum(raw_status, PolicyStatus, "status", source_path, issues)

    allowed_models: list[ModelId] = []
    if raw_allowed_models is not None:
        if not isinstance(raw_allowed_models, list):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="allowed_model_ids",
                    message="Field 'allowed_model_ids' must be an array.",
                )
            )
        else:
            for idx, m_val in enumerate(raw_allowed_models):
                m_str = _decode_str(m_val, f"allowed_model_ids[{idx}]", source_path, issues)
                if m_str is not None:
                    allowed_models.append(ModelId(m_str))

    capabilities: list[Capability] = []
    if raw_capabilities is not None:
        if not isinstance(raw_capabilities, list):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="required_capabilities",
                    message="Field 'required_capabilities' must be an array.",
                )
            )
        else:
            for idx, cap_val in enumerate(raw_capabilities):
                cap_enum = _decode_enum(
                    cap_val,
                    Capability,
                    f"required_capabilities[{idx}]",
                    source_path,
                    issues,
                )
                if cap_enum is not None:
                    capabilities.append(cap_enum)

    minimum_quality = _decode_float(raw_quality, "minimum_quality", source_path, issues)
    maximum_latency_ms = _decode_int(raw_latency, "maximum_latency_ms", source_path, issues)
    maximum_cost_usd = _decode_decimal(raw_cost, "maximum_estimated_cost_usd", source_path, issues)
    max_gov_enum = _decode_enum(
        raw_gov,
        GovernanceClassification,
        "maximum_governance_classification",
        source_path,
        issues,
    )
    allow_degraded = _decode_bool(
        raw_allow_degraded, "allow_degraded_providers", source_path, issues
    )

    retry_policy = RetryPolicy(enabled=False, maximum_retries=0, initial_backoff_ms=0)
    if raw_retry is not None:
        if not isinstance(raw_retry, dict):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="retry_policy",
                    message="Field 'retry_policy' must be an object.",
                )
            )
        else:
            _check_known_fields(
                raw_retry,
                {"enabled", "maximum_retries", "initial_backoff_ms"},
                source_path,
                issues,
            )
            raw_rt_enabled = _get_required_field(raw_retry, "enabled", source_path, issues)
            raw_rt_retries = _get_required_field(raw_retry, "maximum_retries", source_path, issues)
            raw_rt_backoff = _get_required_field(
                raw_retry, "initial_backoff_ms", source_path, issues
            )
            rt_enabled = _decode_bool(raw_rt_enabled, "retry_policy.enabled", source_path, issues)
            rt_retries = _decode_int(
                raw_rt_retries, "retry_policy.maximum_retries", source_path, issues
            )
            rt_backoff = _decode_int(
                raw_rt_backoff, "retry_policy.initial_backoff_ms", source_path, issues
            )
            if rt_enabled is not None and rt_retries is not None and rt_backoff is not None:
                try:
                    retry_policy = RetryPolicy(
                        enabled=rt_enabled,
                        maximum_retries=rt_retries,
                        initial_backoff_ms=rt_backoff,
                    )
                except ValueError as err:
                    issues.append(
                        ConfigurationIssue(
                            code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                            source_path=source_path,
                            field_path="retry_policy",
                            message=str(err),
                        )
                    )

    fallback_policy: FallbackPolicy | None = None
    if raw_fallback is not None:
        if not isinstance(raw_fallback, dict):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="fallback_policy",
                    message="Field 'fallback_policy' must be an object.",
                )
            )
        else:
            _check_known_fields(
                raw_fallback,
                {"enabled", "maximum_fallback_attempts"},
                source_path,
                issues,
            )
            raw_fb_enabled = _get_required_field(raw_fallback, "enabled", source_path, issues)
            raw_fb_attempts = _get_required_field(
                raw_fallback, "maximum_fallback_attempts", source_path, issues
            )
            fb_enabled = _decode_bool(
                raw_fb_enabled, "fallback_policy.enabled", source_path, issues
            )
            fb_attempts = _decode_int(
                raw_fb_attempts, "fallback_policy.maximum_fallback_attempts", source_path, issues
            )
            if fb_enabled is not None and fb_attempts is not None:
                try:
                    fallback_policy = FallbackPolicy(
                        enabled=fb_enabled,
                        maximum_fallback_attempts=fb_attempts,
                    )
                except ValueError as err:
                    issues.append(
                        ConfigurationIssue(
                            code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                            source_path=source_path,
                            field_path="fallback_policy",
                            message=str(err),
                        )
                    )

    circuit_breaker_policy = CircuitBreakerPolicy(
        enabled=False, failure_threshold=3, open_duration_seconds=30
    )
    if raw_cb is not None:
        if not isinstance(raw_cb, dict):
            issues.append(
                ConfigurationIssue(
                    code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                    source_path=source_path,
                    field_path="circuit_breaker_policy",
                    message="Field 'circuit_breaker_policy' must be an object.",
                )
            )
        else:
            _check_known_fields(
                raw_cb,
                {"enabled", "failure_threshold", "open_duration_seconds"},
                source_path,
                issues,
            )
            raw_cb_enabled = _get_required_field(raw_cb, "enabled", source_path, issues)
            raw_cb_threshold = _get_required_field(raw_cb, "failure_threshold", source_path, issues)
            raw_cb_duration = _get_required_field(
                raw_cb, "open_duration_seconds", source_path, issues
            )
            cb_enabled = _decode_bool(
                raw_cb_enabled, "circuit_breaker_policy.enabled", source_path, issues
            )
            cb_threshold = _decode_int(
                raw_cb_threshold,
                "circuit_breaker_policy.failure_threshold",
                source_path,
                issues,
            )
            cb_duration = _decode_int(
                raw_cb_duration,
                "circuit_breaker_policy.open_duration_seconds",
                source_path,
                issues,
            )
            if cb_enabled is not None and cb_threshold is not None and cb_duration is not None:
                try:
                    circuit_breaker_policy = CircuitBreakerPolicy(
                        enabled=cb_enabled,
                        failure_threshold=cb_threshold,
                        open_duration_seconds=cb_duration,
                    )
                except ValueError as err:
                    issues.append(
                        ConfigurationIssue(
                            code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                            source_path=source_path,
                            field_path="circuit_breaker_policy",
                            message=str(err),
                        )
                    )

    verification_policy = _decode_verification_policy(raw_vp, source_path, issues)

    created_at = _decode_datetime(raw_created_at, "created_at", source_path, issues)

    pinned_model_id: ModelId | None = None
    if raw_pinned is not None:
        pinned_str = _decode_str(raw_pinned, "pinned_model_id", source_path, issues)
        if pinned_str is not None:
            pinned_model_id = ModelId(pinned_str)

    if issues:
        raise RegistryConfigurationError(issues)

    assert policy_id_str is not None
    assert version_str is not None
    assert feature_id_str is not None
    assert status_enum is not None
    assert minimum_quality is not None
    assert maximum_latency_ms is not None
    assert maximum_cost_usd is not None
    assert max_gov_enum is not None
    assert allow_degraded is not None
    assert fallback_policy is not None
    assert created_at is not None

    try:
        return FeaturePolicy(
            policy_id=PolicyId(policy_id_str),
            version=PolicyVersion(version_str),
            feature_id=FeatureId(feature_id_str),
            status=status_enum,
            allowed_model_ids=tuple(allowed_models),
            required_capabilities=tuple(capabilities),
            minimum_quality=minimum_quality,
            maximum_latency_ms=maximum_latency_ms,
            maximum_estimated_cost_usd=maximum_cost_usd,
            maximum_governance_classification=max_gov_enum,
            allow_degraded_providers=allow_degraded,
            retry_policy=retry_policy,
            fallback_policy=fallback_policy,
            circuit_breaker_policy=circuit_breaker_policy,
            verification_policy=verification_policy,
            created_at=created_at,
            pinned_model_id=pinned_model_id,
        )
    except ValueError as err:
        raise RegistryConfigurationError(
            [
                ConfigurationIssue(
                    code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                    source_path=source_path,
                    message=str(err),
                )
            ]
        ) from err


def _decode_verification_policy(
    data: object,
    source_path: Path,
    issues: list[ConfigurationIssue],
) -> VerificationPolicy:
    if data is None:
        return VerificationPolicy()
    if not isinstance(data, dict):
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.INVALID_FIELD_TYPE,
                source_path=source_path,
                field_path="verification_policy",
                message="Field 'verification_policy' must be an object.",
            )
        )
        return VerificationPolicy()

    _check_known_fields(
        data,
        {"enabled", "sample_rate_basis_points", "reference_model_id", "strategy", "minimum_score"},
        source_path,
        issues,
    )

    raw_enabled = data.get("enabled", False)
    raw_sample_rate = data.get("sample_rate_basis_points", 0)
    raw_ref_model = data.get("reference_model_id")
    raw_strategy = data.get("strategy")
    raw_min_score = data.get("minimum_score")

    enabled = _decode_bool(raw_enabled, "verification_policy.enabled", source_path, issues)
    sample_rate = _decode_int(
        raw_sample_rate, "verification_policy.sample_rate_basis_points", source_path, issues
    )

    ref_model_str: str | None = None
    if raw_ref_model is not None:
        ref_model_str = _decode_str(
            raw_ref_model, "verification_policy.reference_model_id", source_path, issues
        )

    strategy_enum: VerificationStrategy | None = None
    if raw_strategy is not None:
        strategy_enum = _decode_enum(
            raw_strategy,
            VerificationStrategy,
            "verification_policy.strategy",
            source_path,
            issues,
        )

    min_score_dec: Decimal | None = None
    if raw_min_score is not None:
        min_score_dec = _decode_decimal(
            raw_min_score, "verification_policy.minimum_score", source_path, issues
        )

    if enabled is None or sample_rate is None:
        return VerificationPolicy()

    ref_model_id = ModelId(ref_model_str) if ref_model_str is not None else None

    try:
        return VerificationPolicy(
            enabled=enabled,
            sample_rate_basis_points=sample_rate,
            reference_model_id=ref_model_id,
            strategy=strategy_enum,
            minimum_score=min_score_dec,
        )
    except ValueError as err:
        issues.append(
            ConfigurationIssue(
                code=ConfigurationIssueCode.CONTRACT_VALIDATION_FAILED,
                source_path=source_path,
                field_path="verification_policy",
                message=str(err),
            )
        )
        return VerificationPolicy()
