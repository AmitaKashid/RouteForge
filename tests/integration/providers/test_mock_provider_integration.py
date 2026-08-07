"""Integration test verifying committed model configuration with DeterministicMockProvider."""

import asyncio
from pathlib import Path

from routeforge.contracts import (
    AttemptId,
    ChatMessage,
    ChatRole,
    ModelId,
    OutputFormat,
    ProviderRequest,
    RequestId,
)
from routeforge.providers import DeterministicMockProvider
from routeforge.registries import load_registry_snapshot


def test_committed_mock_economy_model_execution() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    models_dir = repo_root / "config" / "models"
    policies_dir = repo_root / "config" / "policies"

    snapshot = load_registry_snapshot(
        models_directory=models_dir,
        policies_directory=policies_dir,
    )

    model = snapshot.models.get(ModelId("mock-economy"))
    assert model is not None
    assert model.provider_id == "mock"

    provider = DeterministicMockProvider()
    request = ProviderRequest(
        request_id=RequestId("req_integ_1"),
        attempt_id=AttemptId("att_integ_1"),
        model_id=ModelId("mock-economy"),
        messages=(ChatMessage(role=ChatRole.USER, content="Integration prompt test"),),
        output_format=OutputFormat.TEXT,
        timeout_ms=5000,
        idempotency_key="idem_integ_1",
    )

    response = asyncio.run(provider.complete(request, model))

    assert response.request_id == RequestId("req_integ_1")
    assert response.model_id == ModelId("mock-economy")
    assert response.provider_id == "mock"
    assert "mock-response:mock-economy:" in response.content
    assert response.usage.input_tokens == 3
    assert response.usage.output_tokens > 0
