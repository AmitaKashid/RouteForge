"""Targeted unit tests for storage records, auth, estimation, and error branches."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from routeforge.contracts import (
    ChatMessage,
    ChatRequest,
    ChatRole,
    FeatureId,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderId,
    QualityProfile,
    RequestId,
    RoutingConstraints,
    TeamId,
)
from routeforge.evaluation.model_profiles import (
    MeasuredModelProfile,
    MeasuredQualityProfile,
    ModelProfileRegistry,
)
from routeforge.gateway.estimation import (
    build_candidate_estimate,
)
from routeforge.storage.models import InferenceRecordModel, TeamLimitsModel
from routeforge.storage.records import (
    reconcile_actual_cost,
    release_budget_reservation,
    replace_budget_reservation,
)


def _make_dummy_model(model_id: str = "m1") -> ModelDefinition:
    from routeforge.contracts import Capability, GovernanceClassification

    return ModelDefinition(
        model_id=ModelId(model_id),
        provider_id=ProviderId("p1"),
        display_name=model_id,
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.10"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.20"),
        estimated_latency_ms=100,
        quality_profiles=(
            QualityProfile(
                task_type="coding",
                predicted_quality=0.85,
                source="test",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )


def _make_dummy_request(feature: str = "coding-assistant") -> ChatRequest:
    return ChatRequest(
        request_id=RequestId("req-cov-1"),
        team_id=TeamId("team-cov"),
        feature_id=FeatureId(feature),
        messages=(ChatMessage(role=ChatRole.USER, content="def foo(): pass"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )


# Estimation Unit Tests
def test_estimation_profile_branches() -> None:
    req = _make_dummy_request("coding-assistant")
    model = _make_dummy_model("m1")

    # Profile registry with matching profile
    quality_profile = MeasuredQualityProfile(
        task_type="general",
        measured_quality=0.92,
        measured_pass_rate=0.92,
        measured_median_latency_ms=120,
        measured_p95_latency_ms=150,
        sample_count=100,
        source_benchmark_file="bench.json",
        evaluator_version="v1",
    )
    model_profile = MeasuredModelProfile(
        model_id=ModelId("m1"),
        task_profiles={"general": quality_profile},
    )
    reg = ModelProfileRegistry(
        profile_version="v1",
        profiles={ModelId("m1"): model_profile},
    )

    est = build_candidate_estimate(
        request=req,
        model=model,
        feature_id=req.feature_id,
        model_profile_registry=reg,
    )
    assert est.predicted_quality == 0.92
    assert est.estimated_latency_ms == 120

    # Profile registry with unmeasured task type
    req_other = _make_dummy_request("summarization")
    est_unmeasured = build_candidate_estimate(
        request=req_other,
        model=model,
        feature_id=req_other.feature_id,
        model_profile_registry=reg,
    )
    assert est_unmeasured.predicted_quality == 0.0

    # Model without matching quality profiles raises ValueError
    no_match_model = ModelDefinition(
        model_id=ModelId("m2"),
        provider_id=ProviderId("p1"),
        display_name="m2",
        capabilities=model.capabilities,
        governance_allowed=model.governance_allowed,
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.1"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.2"),
        estimated_latency_ms=100,
        quality_profiles=(
            QualityProfile(
                task_type="unrelated-task",
                predicted_quality=0.5,
                source="test",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )
    with pytest.raises(ValueError, match="has no quality profile matching task"):
        build_candidate_estimate(
            request=req,
            model=no_match_model,
            feature_id=req.feature_id,
        )


class MockResult:
    def __init__(self, val: Any = None) -> None:
        self.val = val

    def scalar_one_or_none(self) -> Any:
        return self.val

    def scalar(self) -> Any:
        return self.val if self.val is not None else Decimal("0")

    def scalars(self) -> "MockResult":
        return self

    def all(self) -> list[Any]:
        return []


# Storage Records Unit Tests
@pytest.mark.anyio
async def test_records_replace_budget_reservation_branches() -> None:
    session = AsyncMock()

    team_limits = TeamLimitsModel(
        team_id="team-cov",
        requests_per_minute=100,
        tokens_per_minute=10000,
        monthly_budget_usd=Decimal("5.00"),
        active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    rec = InferenceRecordModel(
        request_id="req-cov-1",
        team_id="team-cov",
        feature_id="general-chat",
        policy_id="p1",
        policy_version="v1",
        selected_model_id="m1",
        selected_provider_id="p1",
        routing_reason="CHEAPEST",
        candidate_decisions=[],
        status="BUDGET_RESERVED",
        error_code=None,
        prompt_hash="a" * 64,
        message_count=1,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    async def mock_exec(stmt: Any) -> MockResult:
        stmt_str = str(stmt)
        if "team_limits" in stmt_str:
            return MockResult(team_limits)
        if "coalesce" in stmt_str or "sum" in stmt_str:
            return MockResult(Decimal("1.00"))
        if "inference_records" in stmt_str:
            return MockResult(rec)
        return MockResult(Decimal("1.00"))

    session.execute = mock_exec
    session.commit = AsyncMock()

    allowed, mb, _committed = await replace_budget_reservation(
        session=session,
        request_id="req-cov-1",
        team_id="team-cov",
        new_estimated_cost=Decimal("0.50"),
    )
    assert allowed is True
    assert mb == Decimal("5.00")

    # Exceed budget path
    allowed_exceeded, _, _ = await replace_budget_reservation(
        session=session,
        request_id="req-cov-1",
        team_id="team-cov",
        new_estimated_cost=Decimal("10.00"),  # > 5.00
    )
    assert allowed_exceeded is False


@pytest.mark.anyio
async def test_records_reconcile_and_release_when_record_none() -> None:
    session = AsyncMock()

    async def mock_exec(stmt: Any) -> MockResult:
        return MockResult(None)

    session.execute = mock_exec
    session.commit = AsyncMock()

    # Reconcile when record not found does not crash
    await reconcile_actual_cost(
        session=session,
        request_id="req-nonexistent",
        actual_cost_usd=Decimal("0.01"),
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        provider_latency_ms=50,
    )

    # Release when record not found does not crash
    await release_budget_reservation(
        session=session,
        request_id="req-nonexistent",
        status_name="PROVIDER_ERROR",
        error_code="PROVIDER_TIMEOUT",
    )


@pytest.mark.anyio
async def test_chat_feature_not_found_returns_404() -> None:
    from fastapi.testclient import TestClient

    from routeforge.contracts import TeamId
    from routeforge.gateway import create_app
    from routeforge.gateway.auth import get_authenticated_team_id

    app = create_app()
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-test")

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "nonexistent-feature"},
            },
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FEATURE_NOT_FOUND"


@pytest.mark.anyio
async def test_get_authenticated_team_id_all_branches() -> None:
    from unittest.mock import MagicMock

    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from routeforge.contracts import KeyId
    from routeforge.gateway.auth import get_authenticated_team_id
    from routeforge.storage.records import AuthResult

    req = MagicMock()
    req.app.state = MagicMock()
    req.app.state.db_manager = None

    # 1. Missing credentials -> 401
    with pytest.raises(HTTPException) as exc_info:
        await get_authenticated_team_id(req, None)
    assert exc_info.value.status_code == 401

    # 2. Scheme not bearer -> 401
    with pytest.raises(HTTPException) as exc_info:
        await get_authenticated_team_id(
            req, HTTPAuthorizationCredentials(scheme="Basic", credentials="abc")
        )
    assert exc_info.value.status_code == 401

    # 3. Non-rf_ prefix key without DB -> 401
    with pytest.raises(HTTPException) as exc_info:
        await get_authenticated_team_id(
            req, HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid_key")
        )
    assert exc_info.value.status_code == 401

    # 4. Valid rf_ prefix key without DB -> returns local-development team
    team_id = await get_authenticated_team_id(
        req, HTTPAuthorizationCredentials(scheme="Bearer", credentials="rf_test_key")
    )
    assert team_id == "local-development"

    # 5. DB manager with inactive key -> 403
    db_mgr = MagicMock()
    session = AsyncMock()

    class AsyncCtx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *args: Any) -> None:
            pass

    db_mgr.session_factory.return_value = AsyncCtx()
    req.app.state.db_manager = db_mgr

    with pytest.raises(HTTPException) as exc_info:
        # authenticate_api_key returns inactive key AuthResult
        with pytest.MonkeyPatch.context() as m:
            m.setattr(
                "routeforge.gateway.auth.authenticate_api_key",
                AsyncMock(
                    return_value=AuthResult(
                        team_id=TeamId("t1"),
                        key_id=KeyId("k1"),
                        is_key_active=False,
                        is_team_active=True,
                    )
                ),
            )
            await get_authenticated_team_id(
                req, HTTPAuthorizationCredentials(scheme="Bearer", credentials="key_inactive")
            )
    assert exc_info.value.status_code == 403

    # 6. DB manager with active key -> returns team_id
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            "routeforge.gateway.auth.authenticate_api_key",
            AsyncMock(
                return_value=AuthResult(
                    team_id=TeamId("team-db"),
                    key_id=KeyId("k1"),
                    is_key_active=True,
                    is_team_active=True,
                )
            ),
        )
        res_team = await get_authenticated_team_id(
            req, HTTPAuthorizationCredentials(scheme="Bearer", credentials="key_valid")
        )
        assert res_team == "team-db"


def test_routing_policy_validation_branches() -> None:
    from routeforge.contracts import (
        Capability,
        GovernanceClassification,
        PolicyId,
        PolicyStatus,
    )
    from routeforge.contracts.policies import FallbackPolicy, FeaturePolicy, RetryPolicy

    base_kwargs: dict[str, Any] = {
        "policy_id": PolicyId("p1"),
        "version": "v1",
        "feature_id": FeatureId("f1"),
        "status": PolicyStatus.ACTIVE,
        "allowed_model_ids": (ModelId("m1"),),
        "required_capabilities": (Capability.TEXT_CHAT,),
        "minimum_quality": 0.5,
        "maximum_latency_ms": 1000,
        "maximum_estimated_cost_usd": Decimal("1.00"),
        "maximum_governance_classification": GovernanceClassification.PUBLIC,
        "allow_degraded_providers": True,
        "fallback_policy": FallbackPolicy(enabled=True, maximum_fallback_attempts=1),
        "created_at": datetime.now(UTC),
        "retry_policy": RetryPolicy(enabled=True, maximum_retries=1, initial_backoff_ms=100),
    }

    # Empty policy_id
    with pytest.raises(ValueError, match="policy_id cannot be empty"):
        FeaturePolicy(**{**base_kwargs, "policy_id": PolicyId("")})

    # Empty version
    with pytest.raises(ValueError, match="version cannot be empty"):
        FeaturePolicy(**{**base_kwargs, "version": ""})

    # Empty feature_id
    with pytest.raises(ValueError, match="feature_id cannot be empty"):
        FeaturePolicy(**{**base_kwargs, "feature_id": FeatureId("")})

    # Empty allowed_model_ids
    with pytest.raises(ValueError, match="allowed_model_ids cannot be empty"):
        FeaturePolicy(**{**base_kwargs, "allowed_model_ids": ()})

    # Invalid minimum_quality
    with pytest.raises(ValueError, match="minimum_quality must be between"):
        FeaturePolicy(**{**base_kwargs, "minimum_quality": 1.5})

    # Invalid maximum_latency_ms
    with pytest.raises(ValueError, match="maximum_latency_ms must be positive"):
        FeaturePolicy(**{**base_kwargs, "maximum_latency_ms": 0})

    # Negative maximum_estimated_cost_usd
    with pytest.raises(ValueError, match="maximum_estimated_cost_usd must not be negative"):
        FeaturePolicy(**{**base_kwargs, "maximum_estimated_cost_usd": Decimal("-1.00")})

    # Pinned model not in allowed list
    with pytest.raises(ValueError, match="must be in allowed_model_ids"):
        FeaturePolicy(**{**base_kwargs, "pinned_model_id": ModelId("m2")})


@pytest.mark.anyio
async def test_gateway_runtime_manager_branches() -> None:
    from routeforge.gateway.runtime import GatewayRuntimeManager, GatewayRuntimeSettings

    # 1. Ollama provider mode initialization
    settings_ollama = GatewayRuntimeSettings(
        provider_mode="ollama",
        profile_path="nonexistent_profile.json",
    )
    mgr_ollama = GatewayRuntimeManager(settings=settings_ollama)
    assert mgr_ollama.get_provider("ollama") is not None
    await mgr_ollama.aclose()

    # 2. Get provider when _providers is empty raises ValueError
    mgr_empty = GatewayRuntimeManager(settings=GatewayRuntimeSettings(profile_path="nonexistent"))
    mgr_empty._providers.clear()
    with pytest.raises(ValueError, match="No registered provider found"):
        mgr_empty.get_provider("unknown")
    await mgr_empty.aclose()


@pytest.mark.anyio
async def test_authenticate_api_key_invalid_prefix() -> None:
    from routeforge.storage.records import authenticate_api_key

    session = AsyncMock()
    res = await authenticate_api_key(session, "invalid_prefix")
    assert res is None
