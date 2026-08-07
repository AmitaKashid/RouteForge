"""Integration tests for M5.1 policy-controlled retry and fallback resilience mechanics."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from routeforge.contracts import (
    AttemptId,
    ErrorCode,
    FinishReason,
    ModelDefinition,
    ModelId,
    ProviderError,
    ProviderId,
    ProviderRequest,
    ProviderResponse,
    RequestId,
    TeamId,
    TokenUsage,
    UsageSource,
)
from routeforge.gateway import create_app
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.providers import LLMProvider, ProviderExecutionError
from routeforge.registries.file_loader import load_registry_snapshot
from routeforge.storage.models import InferenceRecordModel, TeamLimitsModel


def _load_config() -> tuple[Any, Any]:
    snapshot = load_registry_snapshot(
        models_directory=Path("config/models"),
        policies_directory=Path("config/policies"),
    )
    return snapshot.models, snapshot.policies


class ScriptedIntegrationProvider(LLMProvider):
    def __init__(self, provider_id: str) -> None:
        self._provider_id = ProviderId(provider_id)
        self.outcomes: list[ProviderResponse | ProviderError] = []
        self.executed_requests: list[ProviderRequest] = []

    @property
    def provider_id(self) -> ProviderId:
        return self._provider_id

    async def complete(self, request: ProviderRequest, model: ModelDefinition) -> ProviderResponse:
        self.executed_requests.append(request)
        if not self.outcomes:
            return ProviderResponse(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                model_id=request.model_id,
                provider_id=self._provider_id,
                content="Mock response",
                finish_reason=FinishReason.STOP,
                usage=TokenUsage(10, 10, 20, UsageSource.PROVIDER_REPORTED),
                latency_ms=50,
            )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ProviderError):
            raise ProviderExecutionError(outcome)
        return outcome


class RuntimeManagerMock:
    def __init__(self, providers: dict[str, LLMProvider]) -> None:
        self.providers = providers

    def get_provider(self, provider_id: str) -> LLMProvider | None:
        return self.providers.get(provider_id)


class FakeScalarResult:
    def __init__(self, val: Any = None) -> None:
        self.val = val

    def scalar_one_or_none(self) -> Any:
        return self.val

    def scalar_one(self) -> Any:
        return self.val if self.val is not None else Decimal("0")

    def scalar(self) -> Any:
        return self.val if self.val is not None else Decimal("0")

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return []


class MockSession:
    def __init__(
        self,
        fake_budget: TeamLimitsModel | None = None,
        saved_records: list[InferenceRecordModel] | None = None,
    ) -> None:
        self.fake_budget = fake_budget
        self.saved_records = saved_records if saved_records is not None else []

    async def __aenter__(self) -> "MockSession":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def add(self, rec: Any) -> None:
        if isinstance(rec, InferenceRecordModel):
            self.saved_records.append(rec)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        stmt_str = str(stmt)
        if "team_limits" in stmt_str:
            return FakeScalarResult(self.fake_budget)
        if "inference_records" in stmt_str and self.saved_records:
            return FakeScalarResult(self.saved_records[0])
        return FakeScalarResult(None)


@pytest.mark.anyio
async def test_fallback_budget_exhaustion_returns_http_402() -> None:
    """Test that if primary model fails and fallback model cost exceeds budget,

    it fails with HTTP 402 FALLBACK_BUDGET_EXCEEDED and does NOT execute fallback.
    """
    model_reg, policy_reg = _load_config()

    prov_mock = ScriptedIntegrationProvider("mock")
    prov_mock.outcomes = [
        ProviderError(
            request_id=RequestId("req-b1"),
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("mock"),
            model_id=ModelId("mock-economy"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout",
            retryable=True,
        ),
        ProviderError(
            request_id=RequestId("req-b1"),
            attempt_id=AttemptId("a2"),
            provider_id=ProviderId("mock"),
            model_id=ModelId("mock-economy"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout retry",
            retryable=True,
        ),
    ]

    runtime_mgr = RuntimeManagerMock({"mock": prov_mock})

    # mock-economy cost is ~0.000100; mock-premium cost is ~0.000200.
    # Budget of $0.000100 allows mock-economy initial reservation,
    # but rejects mock-premium fallback replacement.
    fake_budget = TeamLimitsModel(
        team_id="team-m51",
        requests_per_minute=100,
        tokens_per_minute=100000,
        monthly_budget_usd=Decimal("0.00010000"),
        active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class MockDbManager:
        def session_factory(self) -> MockSession:
            return MockSession(fake_budget=fake_budget)

        async def aclose(self) -> None:
            pass

    app = create_app(db_manager=cast(Any, MockDbManager()))
    app.state.model_registry = model_reg
    app.state.policy_registry = policy_reg
    app.state.runtime_manager = runtime_mgr
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-m51")

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hello"}],
                "routeforge": {"feature_id": "general-chat"},
            },
        )
        assert resp.status_code == 402
        data = resp.json()
        assert data["error"]["code"] == "FALLBACK_BUDGET_EXCEEDED"
        # Only 2 attempts on primary model mock-economy were executed before fallback budget failure
        assert len(prov_mock.executed_requests) == 2


@pytest.mark.anyio
async def test_end_to_end_fallback_and_decision_audit() -> None:
    """Test end-to-end retry + fallback success and subsequent GET /v1/routing-decisions query."""
    model_reg, policy_reg = _load_config()

    prov_mock = ScriptedIntegrationProvider("mock")
    prov_mock.outcomes = [
        # Attempt 1: mock-economy fails
        ProviderError(
            request_id=RequestId("req-aud-1"),
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("mock"),
            model_id=ModelId("mock-economy"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Primary timeout 1",
            retryable=True,
        ),
        # Attempt 2: mock-economy retry fails
        ProviderError(
            request_id=RequestId("req-aud-1"),
            attempt_id=AttemptId("a2"),
            provider_id=ProviderId("mock"),
            model_id=ModelId("mock-economy"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Primary timeout 2",
            retryable=True,
        ),
        # Attempt 3: mock-premium fallback succeeds
        ProviderResponse(
            request_id=RequestId("req-aud-1"),
            attempt_id=AttemptId("a3"),
            model_id=ModelId("mock-premium"),
            provider_id=ProviderId("mock"),
            content="Fallback success answer",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(12, 8, 20, UsageSource.PROVIDER_REPORTED),
            latency_ms=80,
        ),
    ]

    runtime_mgr = RuntimeManagerMock({"mock": prov_mock})
    saved_records: list[InferenceRecordModel] = []

    class MockDbManager:
        def session_factory(self) -> MockSession:
            return MockSession(saved_records=saved_records)

        async def aclose(self) -> None:
            pass

    app = create_app(db_manager=cast(Any, MockDbManager()))
    app.state.model_registry = model_reg
    app.state.policy_registry = policy_reg
    app.state.runtime_manager = runtime_mgr
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-m51")

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hello fallback"}],
                "routeforge": {"feature_id": "general-chat"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Fallback success answer"
        assert data["routeforge"]["fallback_used"] is True
        assert data["routeforge"]["retry_count"] == 1

        req_id = data["routeforge"]["request_id"]

        dec_resp = client.get(f"/v1/routing-decisions/{req_id}")
        assert dec_resp.status_code == 200
        dec_data = dec_resp.json()
        assert dec_data["fallback_used"] is True
        assert dec_data["retry_count"] == 1
        assert dec_data["initial_model_id"] == "mock-economy"
        assert dec_data["selected_model_id"] == "mock-premium"
        assert len(dec_data["execution_attempts"]) == 3
