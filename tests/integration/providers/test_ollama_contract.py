"""Integration contract compliance tests for OllamaProvider."""

import asyncio
import json
from decimal import Decimal

import httpx

from routeforge.contracts import (
    AttemptId,
    Capability,
    ChatMessage,
    ChatRole,
    FinishReason,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderId,
    ProviderRequest,
    QualityProfile,
    RequestId,
)
from routeforge.providers.ollama import OllamaProvider, OllamaProviderConfig


def test_ollama_provider_full_contract_flow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/chat"
        payload = json.loads(request.read().decode("utf-8"))
        assert payload["model"] == "llama3.2:latest"
        assert payload["stream"] is False

        return httpx.Response(
            200,
            json={
                "model": "llama3.2:latest",
                "created_at": "2026-08-06T12:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "This is a valid Ollama response.",
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 8,
                "total_duration": 450_000_000,
            },
        )

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            async with OllamaProvider(config=config, client=client) as provider:
                request = ProviderRequest(
                    request_id=RequestId("req_contract_1"),
                    attempt_id=AttemptId("att_contract_1"),
                    model_id=ModelId("ollama-llama3"),
                    messages=(ChatMessage(role=ChatRole.USER, content="Test message"),),
                    output_format=OutputFormat.TEXT,
                    timeout_ms=5000,
                    idempotency_key="key_contract_1",
                )
                model = ModelDefinition(
                    model_id=ModelId("ollama-llama3"),
                    provider_id=ProviderId("ollama"),
                    display_name="Ollama Llama 3",
                    capabilities=(Capability.TEXT_CHAT,),
                    governance_allowed=(GovernanceClassification.PUBLIC,),
                    context_window_tokens=8192,
                    estimated_input_cost_per_million_tokens_usd=Decimal("0"),
                    estimated_output_cost_per_million_tokens_usd=Decimal("0"),
                    estimated_latency_ms=100,
                    quality_profiles=(
                        QualityProfile(
                            task_type="general",
                            predicted_quality=0.8,
                            source="test",
                            version="v1",
                        ),
                    ),
                    enabled=True,
                    configuration_version="v1",
                )

                resp = await provider.complete(request, model)

                assert resp.request_id == RequestId("req_contract_1")
                assert resp.attempt_id == AttemptId("att_contract_1")
                assert resp.provider_id == ProviderId("ollama")
                assert resp.model_id == ModelId("ollama-llama3")
                assert resp.content == "This is a valid Ollama response."
                assert resp.finish_reason == FinishReason.STOP
                assert resp.usage.input_tokens == 12
                assert resp.usage.output_tokens == 8
                assert resp.usage.total_tokens == 20
                assert resp.latency_ms == 450

    asyncio.run(_run())
