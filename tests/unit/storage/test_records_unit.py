"""Mocked unit tests for storage operations in routeforge.storage.records."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from routeforge.contracts import ChatMessage, ChatRole
from routeforge.storage.models import InferenceRecordModel, TeamLimitsModel
from routeforge.storage.records import (
    authenticate_api_key,
    create_api_key_record,
    create_or_get_team,
    create_or_update_team_limits,
    generate_api_key,
    get_inference_record_by_request_id,
    get_monthly_cost_summary,
    get_monthly_usage_summary,
    get_team_limits,
    hash_prompt,
    reconcile_actual_cost,
    release_budget_reservation,
    reserve_budget_for_request,
)


@pytest.mark.anyio
async def test_hash_prompt_unit() -> None:
    msgs = [ChatMessage(role=ChatRole.USER, content="Hello World")]
    digest = hash_prompt(msgs)
    assert len(digest) == 64


@pytest.mark.anyio
async def test_api_key_generation_and_auth_unit() -> None:
    session = AsyncMock()

    raw_key, prefix, key_hash = generate_api_key()
    assert raw_key.startswith("rf_")
    assert raw_key.startswith(f"rf_{prefix}")

    # Test create_api_key_record
    key_record = await create_api_key_record(session, "t1", prefix, key_hash)
    assert key_record.team_id == "t1"
    session.add.assert_called_once()

    # Test authenticate_api_key (valid key)
    res_mock = MagicMock()
    mock_key_model = MagicMock()
    mock_key_model.team_id = "t1"
    mock_key_model.active = True
    mock_key_model.key_hash = key_hash
    res_mock.scalars.return_value.all.return_value = [mock_key_model]
    session.execute.return_value = res_mock

    auth_res = await authenticate_api_key(session, raw_key)
    assert auth_res is not None
    assert auth_res.team_id == "t1"


@pytest.mark.anyio
async def test_create_or_get_team_unit() -> None:
    session = AsyncMock()

    # Case 1: Team exists
    existing = MagicMock()
    res_exist = MagicMock()
    res_exist.scalar_one_or_none.return_value = existing
    session.execute.return_value = res_exist

    t1 = await create_or_get_team(session, "t1", "Team 1")
    assert t1 == existing

    # Case 2: Team does not exist -> Create
    session.reset_mock()
    res_none = MagicMock()
    res_none.scalar_one_or_none.return_value = None
    session.execute.return_value = res_none

    t2 = await create_or_get_team(session, "t2", "Team 2")
    assert t2.team_id == "t2"
    session.add.assert_called_once()


@pytest.mark.anyio
async def test_create_or_update_team_limits_unit() -> None:
    session = AsyncMock()

    # Case 1: Limit row does not exist -> Create new
    res_none = MagicMock()
    res_none.scalar_one_or_none.return_value = None
    session.execute.return_value = res_none

    limits = await create_or_update_team_limits(
        session,
        team_id="team-unit-1",
        requests_per_minute=60,
        tokens_per_minute=50000,
        monthly_budget_usd=Decimal("50.00"),
    )
    assert limits.team_id == "team-unit-1"
    session.add.assert_called_once()

    # Case 2: Limit row exists -> Update existing
    session.reset_mock()
    existing = TeamLimitsModel(
        team_id="team-unit-1",
        requests_per_minute=10,
        tokens_per_minute=1000,
        monthly_budget_usd=Decimal("10.00"),
        active=True,
    )
    res_exist = MagicMock()
    res_exist.scalar_one_or_none.return_value = existing
    session.execute.return_value = res_exist

    updated = await create_or_update_team_limits(
        session,
        team_id="team-unit-1",
        requests_per_minute=120,
        tokens_per_minute=100000,
        monthly_budget_usd=Decimal("100.00"),
    )
    assert updated.requests_per_minute == 120
    assert updated.monthly_budget_usd == Decimal("100.00")


@pytest.mark.anyio
async def test_get_team_limits_unit() -> None:
    session = AsyncMock()
    existing = TeamLimitsModel(team_id="t1", requests_per_minute=60, tokens_per_minute=50000)
    res = MagicMock()
    res.scalar_one_or_none.return_value = existing
    session.execute.return_value = res

    limits = await get_team_limits(session, "t1")
    assert limits is not None
    assert limits.team_id == "t1"


@pytest.mark.anyio
async def test_reserve_budget_for_request_unit() -> None:
    session = AsyncMock()

    # Case 1: No team limits -> Budget allowed
    res_no_limits = MagicMock()
    res_no_limits.scalar_one_or_none.return_value = None
    session.execute.return_value = res_no_limits

    allowed, budget, _committed, _est = await reserve_budget_for_request(
        session, "t-no-lim", Decimal("1.00")
    )
    assert allowed is True
    assert budget is None

    # Case 2: Budget allowed ($3.00 + $2.00 <= $10.00)
    limits = TeamLimitsModel(team_id="t-lim", monthly_budget_usd=Decimal("10.00"), active=True)
    res_limits = MagicMock()
    res_limits.scalar_one_or_none.return_value = limits

    res_acc = MagicMock()
    res_acc.scalar.return_value = Decimal("3.00")
    res_acc.scalar_one.return_value = Decimal("3.00")

    res_res = MagicMock()
    res_res.scalar.return_value = Decimal("2.00")
    res_res.scalar_one.return_value = Decimal("2.00")

    session.execute.side_effect = [res_limits, res_acc, res_res]

    allowed2, budget2, committed2, _ = await reserve_budget_for_request(
        session, "t-lim", Decimal("2.00")
    )
    assert allowed2 is True
    assert budget2 == Decimal("10.00")
    assert committed2 == Decimal("5.00")


@pytest.mark.anyio
async def test_release_and_reconcile_records_unit() -> None:
    session = AsyncMock()
    record = InferenceRecordModel(
        request_id="req-rel-1",
        team_id="t1",
        feature_id="f1",
        policy_id="p1",
        policy_version="v1",
        status="BUDGET_RESERVED",
        reserved_cost_usd=Decimal("1.00"),
    )
    res = MagicMock()
    res.scalar_one_or_none.return_value = record
    session.execute.return_value = res

    rel_rec = await release_budget_reservation(
        session, "req-rel-1", status_name="PROVIDER_ERROR", error_code="TIMEOUT"
    )
    assert rel_rec is not None
    assert rel_rec.status == "PROVIDER_ERROR"
    assert rel_rec.reserved_cost_usd == Decimal("0")

    # Reconcile actual cost
    session.reset_mock()
    session.execute.return_value = res
    rec_rec = await reconcile_actual_cost(
        session=session,
        request_id="req-rel-1",
        actual_cost_usd=Decimal("0.80"),
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        provider_latency_ms=100,
    )
    assert rec_rec is not None
    assert rec_rec.status == "SUCCEEDED"
    assert rec_rec.accounted_cost_usd == Decimal("0.80")


@pytest.mark.anyio
async def test_monthly_summaries_unit() -> None:
    session = AsyncMock()

    rec1 = InferenceRecordModel(
        request_id="r1",
        team_id="t1",
        feature_id="f1",
        policy_id="p1",
        policy_version="v1",
        status="SUCCEEDED",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        accounted_cost_usd=Decimal("2.00"),
        reserved_cost_usd=Decimal("0"),
    )
    rec2 = InferenceRecordModel(
        request_id="r2",
        team_id="t1",
        feature_id="f1",
        policy_id="p1",
        policy_version="v1",
        status="NO_ELIGIBLE_MODEL",
        routing_reason="NO_ELIGIBLE_MODEL",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        accounted_cost_usd=Decimal("0"),
        reserved_cost_usd=Decimal("0"),
    )

    res_scalars = MagicMock()
    res_scalars.scalars.return_value.all.return_value = [rec1, rec2]
    session.execute.return_value = res_scalars

    usage = await get_monthly_usage_summary(session, "t1")
    assert usage["request_count"] == 2
    assert usage["successful_request_count"] == 1
    assert usage["total_tokens"] == 150

    # Test Cost Summary with budget
    session.reset_mock()
    limits = TeamLimitsModel(team_id="t1", monthly_budget_usd=Decimal("10.00"), active=True)
    res_limits = MagicMock()
    res_limits.scalar_one_or_none.return_value = limits

    res_acc = MagicMock()
    res_acc.scalar.return_value = Decimal("2.00")

    res_res = MagicMock()
    res_res.scalar.return_value = Decimal("1.00")

    session.execute.side_effect = [res_limits, res_acc, res_res]

    cost_summary = await get_monthly_cost_summary(session, "t1")
    assert cost_summary["monthly_budget_usd"] == Decimal("10.00")
    assert cost_summary["committed_cost_usd"] == Decimal("3.00")
    assert cost_summary["remaining_available_budget_usd"] == Decimal("7.00")
    assert cost_summary["budget_utilization_percentage"] == 30.0

    # Test Cost Summary without budget (zero budget)
    session.reset_mock()
    res_limits_zero = MagicMock()
    res_limits_zero.scalar_one_or_none.return_value = None
    session.execute.side_effect = [res_limits_zero, res_acc, res_res]

    cost_zero = await get_monthly_cost_summary(session, "t1")
    assert cost_zero["monthly_budget_usd"] == Decimal("0")
    assert cost_zero["budget_utilization_percentage"] == 0.0


@pytest.mark.anyio
async def test_get_inference_record_by_request_id_unit() -> None:
    session = AsyncMock()
    mock_record = InferenceRecordModel(request_id="req-1", team_id="t1")
    res_mock = MagicMock()
    res_mock.scalar_one_or_none.return_value = mock_record
    session.execute.return_value = res_mock

    rec = await get_inference_record_by_request_id(session, "req-1", "t1")
    assert rec is not None
    assert rec.request_id == "req-1"
