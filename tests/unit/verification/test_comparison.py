"""Unit tests for text and JSON output comparison strategies."""

from decimal import Decimal

from routeforge.contracts.verification import VerificationStrategy
from routeforge.verification.comparison import (
    compare_json_field_agreement,
    compare_normalized_exact,
    evaluate_verification,
)


def test_normalized_exact_match() -> None:
    score, fail_code = compare_normalized_exact("positive", "positive")
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_normalized_exact_trimmed_whitespace() -> None:
    score, fail_code = compare_normalized_exact("  positive \n", "positive")
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_normalized_exact_line_endings() -> None:
    score, fail_code = compare_normalized_exact("line1\r\nline2", "line1\nline2")
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_normalized_exact_case_sensitive() -> None:
    score, fail_code = compare_normalized_exact("Positive", "positive", case_sensitive=True)
    assert score == Decimal("0.00000")
    assert fail_code == "VALUE_MISMATCH"


def test_normalized_exact_mismatch_score_zero() -> None:
    score, fail_code = compare_normalized_exact("positive", "negative")
    assert score == Decimal("0.00000")
    assert fail_code == "VALUE_MISMATCH"


def test_json_equal_objects_score_one() -> None:
    sel = '{"label": "A", "confidence": 0.95}'
    ref = '{"label": "A", "confidence": 0.95}'
    score, fail_code = compare_json_field_agreement(sel, ref)
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_json_key_ordering_does_not_matter() -> None:
    sel = '{"a": 1, "b": 2}'
    ref = '{"b": 2, "a": 1}'
    score, fail_code = compare_json_field_agreement(sel, ref)
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_json_partial_field_agreement_ratio() -> None:
    sel = '{"a": 1, "b": 2}'
    ref = '{"a": 1, "b": 3}'  # 'a' matches, 'b' mismatches
    score, fail_code = compare_json_field_agreement(sel, ref)
    assert score == Decimal("0.50000")
    assert fail_code == "VALUE_MISMATCH"


def test_json_missing_fields_reduce_score() -> None:
    sel = '{"a": 1}'
    ref = '{"a": 1, "b": 2}'
    score, fail_code = compare_json_field_agreement(sel, ref)
    assert score == Decimal("0.50000")
    assert fail_code == "MISSING_FIELDS"


def test_json_nested_objects_flattened_correctly() -> None:
    sel = '{"user": {"name": "Alice", "id": 10}}'
    ref = '{"user": {"name": "Alice", "id": 10}}'
    score, fail_code = compare_json_field_agreement(sel, ref)
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_json_arrays_or_primitive_roots_rejected() -> None:
    score, fail_code = compare_json_field_agreement("[1, 2, 3]", '{"a": 1}')
    assert score == Decimal("0.00000")
    assert fail_code == "SELECTED_OUTPUT_NOT_JSON_OBJECT"

    score2, fail_code2 = compare_json_field_agreement('{"a": 1}', '"string_root"')
    assert score2 == Decimal("0.00000")
    assert fail_code2 == "REFERENCE_OUTPUT_NOT_JSON_OBJECT"


def test_json_invalid_json_creates_stable_code() -> None:
    score, fail_code = compare_json_field_agreement("invalid json {", '{"a": 1}')
    assert score == Decimal("0.00000")
    assert fail_code == "SELECTED_OUTPUT_NOT_JSON_OBJECT"


def test_json_empty_objects_behavior() -> None:
    score, fail_code = compare_json_field_agreement("{}", "{}")
    assert score == Decimal("1.00000")
    assert fail_code is None

    score2, fail_code2 = compare_json_field_agreement("{}", '{"a": 1}')
    assert score2 == Decimal("0.00000")
    assert fail_code2 == "VALUE_MISMATCH"


def test_json_decimal_numeric_comparison_stable() -> None:
    sel = '{"val": 1.0}'
    ref = '{"val": 1.00}'
    score, fail_code = compare_json_field_agreement(sel, ref)
    assert score == Decimal("1.00000")
    assert fail_code is None


def test_evaluate_verification_pass_decision() -> None:
    score, passed, fail_code = evaluate_verification(
        strategy=VerificationStrategy.NORMALIZED_EXACT,
        selected_output="positive",
        reference_output="positive",
        minimum_score=Decimal("1.00000"),
    )
    assert score == Decimal("1.00000")
    assert passed is True
    assert fail_code is None

    score2, passed2, fail_code2 = evaluate_verification(
        strategy=VerificationStrategy.NORMALIZED_EXACT,
        selected_output="positive",
        reference_output="negative",
        minimum_score=Decimal("0.80000"),
    )
    assert score2 == Decimal("0.00000")
    assert passed2 is False
    assert fail_code2 == "VALUE_MISMATCH"
