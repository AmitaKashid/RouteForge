"""Deterministic comparison strategies for quality verification."""

import json
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from routeforge.contracts.verification import VerificationStrategy


def _normalize_text(text: str, case_sensitive: bool = True) -> str:
    """Normalize text with Unicode NFC, line endings, and whitespace trimming."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.strip()
    if not case_sensitive:
        normalized = normalized.lower()
    return normalized


def compare_normalized_exact(
    selected_output: str,
    reference_output: str,
    case_sensitive: bool = True,
) -> tuple[Decimal, str | None]:
    """Compare text outputs using NORMALIZED_EXACT strategy.

    Returns:
        Tuple of (score, failure_code).
    """
    sel_norm = _normalize_text(selected_output, case_sensitive=case_sensitive)
    ref_norm = _normalize_text(reference_output, case_sensitive=case_sensitive)

    if sel_norm == ref_norm:
        return Decimal("1.00000"), None
    return Decimal("0.00000"), "VALUE_MISMATCH"


def flatten_json_leaves(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten leaf paths of a parsed JSON structure."""
    leaves: dict[str, Any] = {}
    if isinstance(obj, dict):
        if not obj:
            return leaves
        for key, val in sorted(obj.items(), key=lambda x: str(x[0])):
            path = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(flatten_json_leaves(val, path))
    elif isinstance(obj, list):
        if not obj:
            return leaves
        for idx, val in enumerate(obj):
            path = f"{prefix}.{idx}"
            leaves.update(flatten_json_leaves(val, path))
    else:
        leaves[prefix] = obj
    return leaves


def _normalize_json_val(val: Any) -> Any:
    """Convert numeric values to Decimal for exact decimal comparison."""
    if isinstance(val, (int, float, Decimal)) and not isinstance(val, bool):
        try:
            return Decimal(str(val))
        except Exception:
            return val
    return val


def compare_json_field_agreement(
    selected_output: str,
    reference_output: str,
) -> tuple[Decimal, str | None]:
    """Compare structured outputs using JSON_FIELD_AGREEMENT strategy.

    Returns:
        Tuple of (score, failure_code).
    """
    try:
        sel_json = json.loads(selected_output)
    except Exception:
        return Decimal("0.00000"), "SELECTED_OUTPUT_NOT_JSON_OBJECT"

    try:
        ref_json = json.loads(reference_output)
    except Exception:
        return Decimal("0.00000"), "REFERENCE_OUTPUT_NOT_JSON_OBJECT"

    if not isinstance(sel_json, dict):
        return Decimal("0.00000"), "SELECTED_OUTPUT_NOT_JSON_OBJECT"

    if not isinstance(ref_json, dict):
        return Decimal("0.00000"), "REFERENCE_OUTPUT_NOT_JSON_OBJECT"

    sel_leaves = flatten_json_leaves(sel_json)
    ref_leaves = flatten_json_leaves(ref_json)

    if len(sel_leaves) == 0 and len(ref_leaves) == 0:
        return Decimal("1.00000"), None

    if len(sel_leaves) == 0 or len(ref_leaves) == 0:
        return Decimal("0.00000"), "VALUE_MISMATCH"

    all_paths = sorted(set(sel_leaves.keys()) | set(ref_leaves.keys()))
    matching_count = 0
    missing_fields = False
    value_mismatch = False

    for path in all_paths:
        in_sel = path in sel_leaves
        in_ref = path in ref_leaves

        if in_sel and in_ref:
            val_sel = _normalize_json_val(sel_leaves[path])
            val_ref = _normalize_json_val(ref_leaves[path])
            if val_sel == val_ref:
                matching_count += 1
            else:
                value_mismatch = True
        else:
            missing_fields = True

    total_paths = len(all_paths)
    raw_ratio = Decimal(matching_count) / Decimal(total_paths)
    score = raw_ratio.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

    if score == Decimal("1.00000"):
        return Decimal("1.00000"), None

    if missing_fields:
        return score, "MISSING_FIELDS"
    if value_mismatch:
        return score, "VALUE_MISMATCH"
    return score, "VALUE_MISMATCH"


def evaluate_verification(
    *,
    strategy: VerificationStrategy,
    selected_output: str,
    reference_output: str,
    minimum_score: Decimal,
) -> tuple[Decimal, bool, str | None]:
    """Evaluate verification outputs against policy strategy and threshold.

    Returns:
        Tuple of (score, passed, failure_code).
    """
    if strategy == VerificationStrategy.NORMALIZED_EXACT:
        score, failure_code = compare_normalized_exact(selected_output, reference_output)
    elif strategy == VerificationStrategy.JSON_FIELD_AGREEMENT:
        score, failure_code = compare_json_field_agreement(selected_output, reference_output)
    else:
        raise ValueError(f"Unsupported verification strategy: {strategy}")

    passed = score >= minimum_score
    return score, passed, failure_code
