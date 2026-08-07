"""Unit tests for task-specific deterministic quality evaluators."""

from routeforge.evaluation.deterministic import (
    evaluate_exact_label,
    evaluate_fact_coverage,
    evaluate_json_fields,
    evaluate_json_validity,
    evaluate_numeric_answer,
    evaluate_summary_keypoints,
)


def test_evaluate_exact_label() -> None:
    res1 = evaluate_exact_label("c1", " POSITIVE \n", "positive")
    assert res1.passed is True
    assert res1.score == 1.0
    assert len(res1.failure_reasons) == 0

    res2 = evaluate_exact_label("c2", "NEGATIVE", "POSITIVE")
    assert res2.passed is False
    assert res2.score == 0.0
    assert len(res2.failure_reasons) == 1


def test_evaluate_json_validity() -> None:
    res1 = evaluate_json_validity("c1", '{"key": "value"}')
    assert res1.passed is True
    assert res1.score == 1.0

    res2 = evaluate_json_validity("c2", "INVALID JSON {")
    assert res2.passed is False
    assert res2.score == 0.0
    assert "Invalid JSON" in res2.failure_reasons[0]


def test_evaluate_json_fields() -> None:
    res1 = evaluate_json_fields("c1", '{"name": "Alice", "age": 30}', ["name", "age"])
    assert res1.passed is True
    assert res1.score == 1.0

    res2 = evaluate_json_fields("c2", '{"name": "Alice"}', ["name", "age", "city"])
    assert res2.passed is False
    assert abs(res2.score - (1.0 / 3.0)) < 1e-4
    assert "Missing required JSON fields" in res2.failure_reasons[0]

    res3 = evaluate_json_fields("c3", "[1, 2, 3]", ["name"])
    assert res3.passed is False
    assert res3.score == 0.0


def test_evaluate_fact_coverage() -> None:
    res1 = evaluate_fact_coverage(
        "c1", "RouteForge is a fast LLM gateway", ["RouteForge", "LLM gateway"]
    )
    assert res1.passed is True
    assert res1.score == 1.0

    res2 = evaluate_fact_coverage("c2", "RouteForge is fast", ["RouteForge", "PostgreSQL", "Redis"])
    assert res2.passed is False
    assert abs(res2.score - (1.0 / 3.0)) < 1e-4
    assert len(res2.failure_reasons) == 1


def test_evaluate_numeric_answer() -> None:
    res1 = evaluate_numeric_answer("c1", "The answer is 150 miles.", "150")
    assert res1.passed is True
    assert res1.score == 1.0

    res2 = evaluate_numeric_answer("c2", "The total is 42.", "100")
    assert res2.passed is False
    assert res2.score == 0.0


def test_evaluate_summary_keypoints() -> None:
    res1 = evaluate_summary_keypoints("c1", "Docker uses containers", ["Docker", "containers"])
    assert res1.passed is True
    assert res1.score == 1.0
