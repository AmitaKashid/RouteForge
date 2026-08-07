"""Unit tests for gateway authentication, readyz, and routing-decisions endpoints."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routeforge.contracts import TeamId
from routeforge.gateway import create_app
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.storage.models import InferenceRecordModel
from routeforge.storage.records import AuthResult


class MockResult:
    def __init__(self, record: InferenceRecordModel | None) -> None:
        self._record = record

    def scalar_one_or_none(self) -> InferenceRecordModel | None:
        return self._record


class MockAsyncSession:
    def __init__(self, record: InferenceRecordModel | None = None) -> None:
        self.record = record

    async def __aenter__(self) -> "MockAsyncSession":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def execute(self, statement: Any) -> MockResult:
        return MockResult(self.record)


class MockDatabaseManager:
    def __init__(
        self,
        auth_result: AuthResult | None = None,
        record: InferenceRecordModel | None = None,
    ) -> None:
        self.auth_result = auth_result
        self.record = record

    def session_factory(self) -> MockAsyncSession:
        return MockAsyncSession(record=self.record)

    async def aclose(self) -> None:
        pass


@pytest.mark.anyio
async def test_auth_missing_header() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/v1/chat/completions", json={})
        assert resp.status_code == 401
        assert "Missing or invalid authentication credentials" in resp.json()["detail"]


@pytest.mark.anyio
async def test_auth_invalid_scheme() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={},
            headers={"Authorization": "Basic invalid_credentials"},
        )
        assert resp.status_code == 401
        assert "Missing or invalid authentication credentials" in resp.json()["detail"]


def test_readyz_endpoint_configuration_missing() -> None:
    app = FastAPI()
    from routeforge.gateway.routes.ready import router as ready_router

    app.include_router(ready_router)
    with TestClient(app) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unhealthy"


class MockRateLimiter:
    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


def test_readyz_endpoint_database_connected() -> None:
    mock_db = MockDatabaseManager()
    mock_limiter = MockRateLimiter()
    app = create_app(db_manager=cast(Any, mock_db), rate_limiter=cast(Any, mock_limiter))
    with TestClient(app) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert data["redis"] == "connected"


def test_routing_decisions_get_record_not_found() -> None:
    mock_db = MockDatabaseManager(record=None)
    app = create_app(db_manager=cast(Any, mock_db))
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-test")

    with TestClient(app) as client:
        resp = client.get("/v1/routing-decisions/req_nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Routing decision not found."


def test_routing_decisions_get_record_found() -> None:
    record = InferenceRecordModel(
        request_id="req_found_1",
        team_id="team-test",
        feature_id="general-chat",
        policy_id="default-policy",
        policy_version="v1",
        selected_model_id="mock-economy",
        selected_provider_id="mock",
        routing_reason="CHEAPEST_ELIGIBLE_MODEL",
        candidate_decisions=[],
        status="SUCCEEDED",
        error_code=None,
        prompt_hash="a" * 64,
        message_count=1,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        accounted_cost_usd=Decimal("0.00010000"),
        cost_source="test",
        provider_latency_ms=50,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    mock_db = MockDatabaseManager(record=record)
    app = create_app(db_manager=cast(Any, mock_db))
    app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("team-test")

    with TestClient(app) as client:
        resp = client.get("/v1/routing-decisions/req_found_1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == "req_found_1"
        assert data["team_id"] == "team-test"
        assert data["selected_model_id"] == "mock-economy"
