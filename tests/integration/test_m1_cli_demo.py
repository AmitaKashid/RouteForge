"""Integration test executing routeforge module CLI demo against committed scenarios."""

import json
import subprocess
import sys
from pathlib import Path


def test_m1_cli_demo_integration_general_chat() -> None:
    scenario = Path("examples/m1/general-chat.json")
    result = subprocess.run(
        [sys.executable, "-m", "routeforge", "demo", str(scenario), "--pretty"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""

    data = json.loads(result.stdout)
    assert data["demo_version"] == "m1"
    assert data["routing_decision"]["selected_model_id"] == "mock-economy"
    assert data["provider_response"]["model_id"] == "mock-economy"


def test_m1_cli_demo_integration_constrained_routing() -> None:
    scenario = Path("examples/m1/constrained-routing.json")
    result = subprocess.run(
        [sys.executable, "-m", "routeforge", "demo", str(scenario)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0

    data = json.loads(result.stdout)
    assert data["routing_decision"]["selected_model_id"] == "mock-premium"
    assert data["provider_response"]["model_id"] == "mock-premium"


def test_m1_cli_demo_integration_no_eligible_model() -> None:
    scenario = Path("examples/m1/no-eligible-model.json")
    result = subprocess.run(
        [sys.executable, "-m", "routeforge", "demo", str(scenario)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2

    data = json.loads(result.stdout)
    assert data["routing_decision"]["selected_model_id"] is None
    assert data["routing_decision"]["routing_reason"] == "NO_ELIGIBLE_MODEL"
    assert data["provider_response"] is None
