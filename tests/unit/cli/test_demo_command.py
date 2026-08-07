"""Unit tests for routeforge CLI command handling."""

import json
from pathlib import Path

import pytest

from routeforge.cli import main, run_demo


def test_cli_demo_general_chat(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = Path("examples/m1/general-chat.json")
    code = main(["demo", str(scenario), "--pretty"])
    assert code == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["demo_version"] == "m1"
    assert data["routing_decision"]["selected_model_id"] == "mock-economy"
    assert data["provider_response"] is not None


def test_cli_demo_route_only(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = Path("examples/m1/general-chat.json")
    code = main(["demo", str(scenario), "--route-only"])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["routing_decision"]["selected_model_id"] == "mock-economy"
    assert data["provider_response"] is None


def test_cli_demo_no_eligible_model(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = Path("examples/m1/no-eligible-model.json")
    code = main(["demo", str(scenario)])
    assert code == 2

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["routing_decision"]["selected_model_id"] is None
    assert data["routing_decision"]["routing_reason"] == "NO_ELIGIBLE_MODEL"
    assert data["provider_response"] is None


def test_cli_demo_invalid_file(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["demo", "nonexistent.json"])
    assert code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_cli_no_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    assert code == 1
    captured = capsys.readouterr()
    assert "Available subcommands" in captured.err


def test_run_demo_missing_config_dirs(tmp_path: Path) -> None:
    scenario = tmp_path / "sc.json"
    scenario.write_text("{}", encoding="utf-8")
    code, _ = run_demo(
        scenario_path=scenario,
        models_dir=tmp_path / "missing_models",
        policies_dir=tmp_path / "missing_policies",
    )
    assert code == 1


def test_run_demo_invalid_json(tmp_path: Path) -> None:
    scenario = tmp_path / "invalid.json"
    scenario.write_text("{bad_json", encoding="utf-8")
    code, _ = run_demo(
        scenario_path=scenario,
        models_dir=Path("config/models"),
        policies_dir=Path("config/policies"),
    )
    assert code == 1
