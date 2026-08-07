"""Unit tests for common domain identifiers, UTC helper, enums, and serialization helper."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts.common import (
    AttemptId,
    Capability,
    FeatureId,
    GovernanceClassification,
    ModelId,
    PolicyId,
    PolicyVersion,
    ProviderId,
    RequestId,
    TeamId,
    ensure_utc,
    serialize_contract,
    utc_now,
)


def test_domain_identifiers() -> None:
    req_id = RequestId("req_1")
    team_id = TeamId("team_1")
    feature_id = FeatureId("feat_1")
    policy_id = PolicyId("pol_1")
    policy_ver = PolicyVersion("v1")
    model_id = ModelId("model_1")
    provider_id = ProviderId("prov_1")
    attempt_id = AttemptId("att_1")

    assert str(req_id) == "req_1"
    assert str(team_id) == "team_1"
    assert str(feature_id) == "feat_1"
    assert str(policy_id) == "pol_1"
    assert str(policy_ver) == "v1"
    assert str(model_id) == "model_1"
    assert str(provider_id) == "prov_1"
    assert str(attempt_id) == "att_1"


def test_utc_now() -> None:
    now = utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.tzinfo == UTC


def test_ensure_utc_rejects_naive() -> None:
    naive_dt = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="must be timezone-aware"):
        ensure_utc(naive_dt)

    aware_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert ensure_utc(aware_dt) == aware_dt


def test_governance_and_capability_enums() -> None:
    assert GovernanceClassification.PUBLIC == "PUBLIC"
    assert GovernanceClassification.RESTRICTED == "RESTRICTED"
    assert Capability.TEXT_CHAT == "TEXT_CHAT"
    assert Capability.REASONING == "REASONING"


def test_serialize_contract_edge_cases() -> None:
    assert serialize_contract(None) is None
    assert serialize_contract(Decimal("1.5")) == "1.5"

    class CustomObj:
        def __str__(self) -> str:
            return "custom_val"

    assert serialize_contract(CustomObj()) == "custom_val"
    assert serialize_contract({"a": 1, "b": Decimal("2.0")}) == {"a": 1, "b": "2.0"}
    assert serialize_contract({1, 2}) == [1, 2] or serialize_contract({1, 2}) == [2, 1]
