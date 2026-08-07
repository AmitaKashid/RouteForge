"""Unit tests for validate_architecture script."""

from pathlib import Path

from scripts.validate_architecture import check_architecture_dependencies


def test_valid_architecture_layout(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    rf_dir = src_dir / "routeforge"
    contracts_dir = rf_dir / "contracts"
    routing_dir = rf_dir / "routing"
    gateway_dir = rf_dir / "gateway"
    contracts_dir.mkdir(parents=True)
    routing_dir.mkdir(parents=True)
    gateway_dir.mkdir(parents=True)

    (contracts_dir / "common.py").write_text("class MyContract:\n    pass\n", encoding="utf-8")
    (routing_dir / "selection.py").write_text(
        "from routeforge.contracts.common import MyContract\n", encoding="utf-8"
    )
    (gateway_dir / "app.py").write_text(
        "import fastapi\nfrom routeforge.contracts import RequestId\n", encoding="utf-8"
    )

    violations = check_architecture_dependencies(src_dir)
    assert violations == []


def test_prohibited_imports_detected(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    rf_dir = src_dir / "routeforge"

    contracts_dir = rf_dir / "contracts"
    registries_dir = rf_dir / "registries"
    providers_dir = rf_dir / "providers"
    routing_dir = rf_dir / "routing"
    gateway_dir = rf_dir / "gateway"

    for d in (contracts_dir, registries_dir, providers_dir, routing_dir, gateway_dir):
        d.mkdir(parents=True)

    # 1. Contract importing routing
    (contracts_dir / "bad_c.py").write_text(
        "import routeforge.routing.selection\n", encoding="utf-8"
    )
    # 2. Registry importing providers
    (registries_dir / "bad_reg.py").write_text(
        "from routeforge.providers import MockScenario\n", encoding="utf-8"
    )
    # 3. Provider importing routing
    (providers_dir / "bad_p.py").write_text(
        "import routeforge.routing.eligibility\n", encoding="utf-8"
    )
    # 4. Routing importing providers
    (routing_dir / "bad_r.py").write_text("import routeforge.providers.mock\n", encoding="utf-8")
    # 5. Prohibited third-party import in contracts
    (contracts_dir / "fastapi_user.py").write_text(
        "import fastapi\nfrom pydantic import BaseModel\n", encoding="utf-8"
    )
    # 6. Contract importing gateway
    (contracts_dir / "gw_user.py").write_text("import routeforge.gateway.app\n", encoding="utf-8")
    # 7. Routing importing FastAPI
    (routing_dir / "fastapi_r.py").write_text("import fastapi\n", encoding="utf-8")
    # 8. Providers importing Pydantic
    (providers_dir / "pydantic_p.py").write_text("import pydantic\n", encoding="utf-8")

    violations = check_architecture_dependencies(src_dir)
    assert len(violations) >= 8

    violation_rules = [v.rule_description for v in violations]
    assert any("Contracts package must not import" in r for r in violation_rules)
    assert any("Registries package must not import" in r for r in violation_rules)
    assert any("Providers package must not import" in r for r in violation_rules)
    assert any("Routing package must not import" in r for r in violation_rules)
    assert any("prohibited framework/SDK 'fastapi'" in r for r in violation_rules)
