"""Task-specific deterministic quality evaluators for benchmark execution."""

import json
import re
from dataclasses import dataclass, field

EVALUATOR_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Immutable result of a deterministic benchmark case evaluation."""

    case_id: str
    evaluator_type: str
    score: float
    passed: bool
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)
    version: str = EVALUATOR_VERSION

    def __post_init__(self) -> None:
        if not self.case_id or not self.case_id.strip():
            raise ValueError("case_id cannot be empty.")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("score must be between 0.0 and 1.0.")
        if not isinstance(self.failure_reasons, tuple):
            object.__setattr__(self, "failure_reasons", tuple(self.failure_reasons))


def evaluate_exact_label(case_id: str, actual: str, expected: str) -> EvaluationResult:
    """Evaluate exact normalized label match."""
    norm_actual = actual.strip().upper()
    norm_expected = expected.strip().upper()
    passed = norm_actual == norm_expected or norm_expected in norm_actual
    score = 1.0 if passed else 0.0
    reasons = () if passed else (f"Expected label '{expected}', got '{actual.strip()}'",)
    return EvaluationResult(
        case_id=case_id,
        evaluator_type="exact_label",
        score=score,
        passed=passed,
        failure_reasons=reasons,
    )


def evaluate_json_validity(case_id: str, actual: str) -> EvaluationResult:
    """Evaluate whether the actual output is valid JSON."""
    try:
        json.loads(actual.strip())
        return EvaluationResult(
            case_id=case_id,
            evaluator_type="json_validity",
            score=1.0,
            passed=True,
        )
    except Exception as err:
        return EvaluationResult(
            case_id=case_id,
            evaluator_type="json_validity",
            score=0.0,
            passed=False,
            failure_reasons=(f"Invalid JSON: {err}",),
        )


def evaluate_json_fields(
    case_id: str,
    actual: str,
    expected_fields: list[str],
) -> EvaluationResult:
    """Evaluate JSON validity and required key coverage."""
    try:
        data = json.loads(actual.strip())
        if not isinstance(data, dict):
            return EvaluationResult(
                case_id=case_id,
                evaluator_type="json_fields",
                score=0.0,
                passed=False,
                failure_reasons=("Root JSON is not an object/dictionary.",),
            )
        missing = [f for f in expected_fields if f not in data]
        if not expected_fields:
            score = 1.0
        else:
            found_count = len(expected_fields) - len(missing)
            score = found_count / len(expected_fields)
        passed = len(missing) == 0
        reasons = () if passed else (f"Missing required JSON fields: {missing}",)
        return EvaluationResult(
            case_id=case_id,
            evaluator_type="json_fields",
            score=score,
            passed=passed,
            failure_reasons=reasons,
        )
    except Exception as err:
        return EvaluationResult(
            case_id=case_id,
            evaluator_type="json_fields",
            score=0.0,
            passed=False,
            failure_reasons=(f"Invalid JSON response: {err}",),
        )


def evaluate_fact_coverage(
    case_id: str,
    actual: str,
    expected_phrases: list[str],
) -> EvaluationResult:
    """Evaluate presence of expected phrases in text."""
    norm_actual = actual.lower()
    missing = [p for p in expected_phrases if p.lower() not in norm_actual]
    if not expected_phrases:
        score = 1.0
    else:
        found_count = len(expected_phrases) - len(missing)
        score = found_count / len(expected_phrases)
    passed = len(missing) == 0
    reasons = () if passed else (f"Missing expected facts/phrases: {missing}",)
    return EvaluationResult(
        case_id=case_id,
        evaluator_type="fact_coverage",
        score=score,
        passed=passed,
        failure_reasons=reasons,
    )


def evaluate_numeric_answer(case_id: str, actual: str, expected: str) -> EvaluationResult:
    """Evaluate exact normalized numeric or short-text answer match."""
    norm_actual = actual.strip().lower()
    norm_expected = expected.strip().lower()

    # Extract digits/numbers if present
    nums_actual = re.findall(r"\b\d+(?:\.\d+)?\b", norm_actual)
    nums_expected = re.findall(r"\b\d+(?:\.\d+)?\b", norm_expected)

    passed = norm_expected in norm_actual or (
        len(nums_actual) > 0 and len(nums_expected) > 0 and nums_actual[0] == nums_expected[0]
    )
    score = 1.0 if passed else 0.0
    reasons = () if passed else (f"Expected numeric/text '{expected}', got '{actual.strip()}'",)
    return EvaluationResult(
        case_id=case_id,
        evaluator_type="numeric_answer",
        score=score,
        passed=passed,
        failure_reasons=reasons,
    )


def evaluate_summary_keypoints(
    case_id: str,
    actual: str,
    required_phrases: list[str],
) -> EvaluationResult:
    """Evaluate keypoint phrase coverage in generated summary."""
    return evaluate_fact_coverage(case_id, actual, required_phrases)
