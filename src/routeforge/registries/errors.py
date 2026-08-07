"""Configuration error codes, issue data structures, and registry exception types."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ConfigurationIssueCode(StrEnum):
    """Stable error codes for configuration decoding and validation issues."""

    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    DIRECTORY_NOT_FOUND = "DIRECTORY_NOT_FOUND"
    INVALID_JSON = "INVALID_JSON"
    INVALID_ROOT_TYPE = "INVALID_ROOT_TYPE"
    MISSING_FIELD = "MISSING_FIELD"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    INVALID_FIELD_TYPE = "INVALID_FIELD_TYPE"
    INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"
    INVALID_DECIMAL = "INVALID_DECIMAL"
    INVALID_DATETIME = "INVALID_DATETIME"
    CONTRACT_VALIDATION_FAILED = "CONTRACT_VALIDATION_FAILED"
    DUPLICATE_MODEL_ID = "DUPLICATE_MODEL_ID"
    DUPLICATE_POLICY_VERSION = "DUPLICATE_POLICY_VERSION"
    UNKNOWN_MODEL_REFERENCE = "UNKNOWN_MODEL_REFERENCE"
    PINNED_MODEL_REFERENCE_MISSING = "PINNED_MODEL_REFERENCE_MISSING"
    MULTIPLE_ACTIVE_POLICIES = "MULTIPLE_ACTIVE_POLICIES"
    NO_ENABLED_MODEL_FOR_ACTIVE_POLICY = "NO_ENABLED_MODEL_FOR_ACTIVE_POLICY"


@dataclass(frozen=True)
class ConfigurationIssue:
    """Detailed record of a single configuration error."""

    code: ConfigurationIssueCode
    source_path: Path
    message: str
    field_path: str | None = None


class RegistryConfigurationError(Exception):
    """Raised when registry configuration decoding or validation fails."""

    issues: tuple[ConfigurationIssue, ...]

    def __init__(self, issues: Sequence[ConfigurationIssue]) -> None:
        sorted_issues = tuple(
            sorted(
                issues,
                key=lambda i: (
                    str(i.source_path),
                    i.field_path or "",
                    i.code.value,
                    i.message,
                ),
            )
        )
        self.issues = sorted_issues

        summary_lines = [f"Registry configuration error ({len(sorted_issues)} issues found):"]
        for issue in sorted_issues:
            location = (
                f"{issue.source_path}:{issue.field_path}"
                if issue.field_path
                else str(issue.source_path)
            )
            summary_lines.append(f"  - [{issue.code}] {location}: {issue.message}")

        super().__init__("\n".join(summary_lines))
