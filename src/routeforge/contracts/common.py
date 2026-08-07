"""Common types, identifiers, governance enums, and serialization helpers."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any, NewType

# Domain Identifier Type Aliases
RequestId = NewType("RequestId", str)
TeamId = NewType("TeamId", str)
FeatureId = NewType("FeatureId", str)
PolicyId = NewType("PolicyId", str)
PolicyVersion = NewType("PolicyVersion", str)
ModelId = NewType("ModelId", str)
ProviderId = NewType("ProviderId", str)
AttemptId = NewType("AttemptId", str)
KeyId = NewType("KeyId", str)


def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware and set to UTC."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"Datetime {dt} must be timezone-aware.")
    return dt


class GovernanceClassification(StrEnum):
    """Allowed data-governance classification categories."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class Capability(StrEnum):
    """Supported model or request capability flags for V1."""

    TEXT_CHAT = "TEXT_CHAT"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    LONG_CONTEXT = "LONG_CONTEXT"
    GROUNDING = "GROUNDING"
    REASONING = "REASONING"


def serialize_contract(obj: Any) -> Any:
    """Recursively serialize domain contracts into JSON-compatible Python primitives."""

    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {field.name: serialize_contract(getattr(obj, field.name)) for field in fields(obj)}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [serialize_contract(item) for item in obj]
    if isinstance(obj, Mapping):
        return {str(k): serialize_contract(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)
