from fastapi import FastAPI
from fastapi.testclient import TestClient

from routeforge.contracts import RequestId
from routeforge.gateway import create_app
from routeforge.providers.mock import DeterministicMockProvider, MockOutcome, MockScenario


def get_test_client(app: FastAPI) -> TestClient:
    return TestClient(app, headers={"Authorization": "Bearer rf_test_dev_key"})


def test_chat_completions_success_cheapest_model() -> None:
    app = create_app()

    # Fixed request ID generator for test determinism
    app.state.request_id_generator = lambda: RequestId("req_test_fixed_1")

    payload = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Explain routing logic."}],
        "stream": False,
        "routeforge": {
            "feature_id": "general-chat",
        },
    }

    with get_test_client(app) as client:
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

        data = response.json()
        assert data["id"] == "chatcmpl-req_test_fixed_1"
        assert data["object"] == "chat.completion"
        assert data["model"] == "mock-economy"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert "mock-response:mock-economy:" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["usage"]["prompt_tokens"] > 0
        assert data["usage"]["completion_tokens"] > 0
        assert data["usage"]["total_tokens"] == (
            data["usage"]["prompt_tokens"] + data["usage"]["completion_tokens"]
        )
        assert data["routeforge"]["request_id"] == "req_test_fixed_1"
        assert data["routeforge"]["provider"] == "mock"
        assert data["routeforge"]["routing_reason"] == "CHEAPEST_ELIGIBLE_MODEL"
        assert data["routeforge"]["fallback_used"] is False


def test_chat_completions_quality_constraint_selects_premium() -> None:
    app = create_app()
    app.state.request_id_generator = lambda: RequestId("req_test_fixed_2")

    payload = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Need high quality analysis."}],
        "stream": False,
        "routeforge": {
            "feature_id": "general-chat",
            "minimum_quality": 0.90,  # Rejects mock-economy (0.78), selects mock-premium (0.92)
        },
    }

    with get_test_client(app) as client:
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["model"] == "mock-premium"
        assert "mock-response:mock-premium:" in data["choices"][0]["message"]["content"]


def test_chat_completions_no_eligible_model_returns_503() -> None:
    app = create_app()
    app.state.request_id_generator = lambda: RequestId("req_test_fixed_3")

    payload = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False,
        "routeforge": {
            "feature_id": "general-chat",
            "maximum_estimated_cost_usd": "0.0000000001",  # Unachievable cost limit
        },
    }

    with get_test_client(app) as client:
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 503

        data = response.json()
        assert data["error"]["type"] == "routing_error"
        assert data["error"]["code"] == "NO_ELIGIBLE_MODEL"
        assert data["routeforge"]["request_id"] == "req_test_fixed_3"


def test_chat_completions_provider_failure_returns_502() -> None:
    # Inject a mock provider scenario that fails
    mock_provider = DeterministicMockProvider(
        default_scenario=MockScenario(
            outcome=MockOutcome.TIMEOUT,
        )
    )
    app = create_app(provider=mock_provider)
    app.state.request_id_generator = lambda: RequestId("req_test_fixed_4")

    payload = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False,
        "routeforge": {
            "feature_id": "general-chat",
        },
    }

    with get_test_client(app) as client:
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 502

        data = response.json()
        assert data["error"]["type"] == "provider_error"
        assert data["error"]["code"] == "PROVIDER_TIMEOUT"
        assert data["routeforge"]["request_id"] == "req_test_fixed_4"


def test_chat_completions_unsupported_inputs_rejected() -> None:
    app = create_app()

    # 1. Backend model ID rejected
    payload1 = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hi"}],
        "routeforge": {"feature_id": "general-chat"},
    }
    with get_test_client(app) as client:
        assert client.post("/v1/chat/completions", json=payload1).status_code == 422

    # 2. stream=True rejected
    payload2 = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
        "routeforge": {"feature_id": "general-chat"},
    }
    with get_test_client(app) as client:
        assert client.post("/v1/chat/completions", json=payload2).status_code == 422

    # 3. temperature rejected
    payload3 = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Hi"}],
        "temperature": 0.7,
        "routeforge": {"feature_id": "general-chat"},
    }
    with get_test_client(app) as client:
        assert client.post("/v1/chat/completions", json=payload3).status_code == 422


def test_chat_completions_unknown_feature_returns_404() -> None:
    app = create_app()
    app.state.request_id_generator = lambda: RequestId("req_test_fixed_5")

    payload = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False,
        "routeforge": {
            "feature_id": "nonexistent-feature",
        },
    }

    with get_test_client(app) as client:
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 404

        data = response.json()
        assert data["error"]["type"] == "invalid_request_error"
        assert data["error"]["code"] == "FEATURE_NOT_FOUND"
        assert data["routeforge"]["request_id"] == "req_test_fixed_5"


def test_chat_completions_deterministic_output_with_fixed_inputs() -> None:
    app = create_app()
    app.state.request_id_generator = lambda: RequestId("req_test_det_1")

    payload = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Deterministic test message."}],
        "stream": False,
        "routeforge": {
            "feature_id": "general-chat",
        },
    }

    with get_test_client(app) as client:
        res1 = client.post("/v1/chat/completions", json=payload).json()
        # Reset request ID generator to produce same request ID
        app.state.request_id_generator = lambda: RequestId("req_test_det_1")
        res2 = client.post("/v1/chat/completions", json=payload).json()

        assert res1["id"] == res2["id"] == "chatcmpl-req_test_det_1"
        assert res1["model"] == res2["model"] == "mock-economy"
        assert res1["choices"][0]["message"]["content"] == res2["choices"][0]["message"]["content"]


def test_chat_completions_openapi_schema_contains_path() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()

        paths = schema["paths"]
        assert "/v1/chat/completions" in paths
        post_op = paths["/v1/chat/completions"]["post"]
        assert "404" in post_op["responses"]
        assert "502" in post_op["responses"]
        assert "503" in post_op["responses"]
