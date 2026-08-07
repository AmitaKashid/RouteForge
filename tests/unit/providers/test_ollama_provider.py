"""Unit tests for OllamaProvider adapter."""

import asyncio
import json
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest

from routeforge.contracts import (
    AttemptId,
    Capability,
    ChatMessage,
    ChatRole,
    ErrorCode,
    FinishReason,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderId,
    ProviderRequest,
    QualityProfile,
    RequestId,
    UsageSource,
)
from routeforge.providers.errors import ProviderExecutionError
from routeforge.providers.ollama import OllamaProvider, OllamaProviderConfig


def make_test_model(
    model_id: str = "ollama-llama3",
    provider_id: str = "ollama",
    enabled: bool = True,
) -> ModelDefinition:
    return ModelDefinition(
        model_id=ModelId(model_id),
        provider_id=ProviderId(provider_id),
        display_name="Ollama Llama3",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=8192,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.0"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.0"),
        estimated_latency_ms=100,
        quality_profiles=(
            QualityProfile(
                task_type="general",
                predicted_quality=0.8,
                source="test",
                version="v1",
            ),
        ),
        enabled=enabled,
        configuration_version="v1",
    )


def make_test_request(
    model_id: str = "ollama-llama3",
    output_format: OutputFormat = OutputFormat.TEXT,
) -> ProviderRequest:
    return ProviderRequest(
        request_id=RequestId("req_1"),
        attempt_id=AttemptId("att_1"),
        model_id=ModelId(model_id),
        messages=(
            ChatMessage(role=ChatRole.SYSTEM, content="System prompt"),
            ChatMessage(role=ChatRole.USER, content="Hello world"),
            ChatMessage(role=ChatRole.ASSISTANT, content="Hi there"),
        ),
        output_format=output_format,
        timeout_ms=5000,
        idempotency_key="key_1",
    )


def make_ollama_json_response(
    content: str = "Ollama response text",
    done_reason: str = "stop",
    prompt_eval_count: int = 15,
    eval_count: int = 10,
    total_duration_ns: int = 500_000_000,
) -> str:
    return json.dumps(
        {
            "model": "llama3.2:latest",
            "created_at": "2026-08-06T12:00:00Z",
            "message": {
                "role": "assistant",
                "content": content,
            },
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
            "total_duration": total_duration_ns,
        }
    )


def test_valid_request_translation_and_role_mapping() -> None:
    sent_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_payload
        assert request.url.path == "/api/chat"
        sent_payload = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, text=make_ollama_json_response())

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            req = make_test_request()
            model = make_test_model()
            resp = await provider.complete(req, model)

            assert resp.content == "Ollama response text"
            assert sent_payload["model"] == "llama3.2:latest"
            assert sent_payload["stream"] is False
            assert "format" not in sent_payload
            msgs = cast(list[dict[str, str]], sent_payload["messages"])
            assert len(msgs) == 3
            assert msgs[0] == {"role": "system", "content": "System prompt"}
            assert msgs[1] == {"role": "user", "content": "Hello world"}
            assert msgs[2] == {"role": "assistant", "content": "Hi there"}

    asyncio.run(_run())


def test_json_response_format_translation() -> None:
    sent_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_payload
        sent_payload = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, text=make_ollama_json_response())

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            req = make_test_request(output_format=OutputFormat.JSON)
            model = make_test_model()
            await provider.complete(req, model)

            assert sent_payload["format"] == "json"

    asyncio.run(_run())


def test_token_accounting_and_duration_conversion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=make_ollama_json_response(
                prompt_eval_count=20,
                eval_count=30,
                total_duration_ns=1_250_000_000,
            ),
        )

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            resp = await provider.complete(make_test_request(), make_test_model())

            assert resp.usage.input_tokens == 20
            assert resp.usage.output_tokens == 30
            assert resp.usage.total_tokens == 50
            assert resp.usage.source == UsageSource.PROVIDER_REPORTED
            assert resp.latency_ms == 1250  # 1_250_000_000 ns -> 1250 ms

    asyncio.run(_run())


def test_finish_reason_mapping() -> None:
    for reason_str, expected_reason in [
        ("stop", FinishReason.STOP),
        ("length", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
    ]:

        def handler(request: httpx.Request, r: str = reason_str) -> httpx.Response:
            return httpx.Response(200, text=make_ollama_json_response(done_reason=r))

        async def _run(exp: FinishReason = expected_reason) -> None:
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost:11434"
            ) as client:
                config = OllamaProviderConfig(
                    model_names={ModelId("ollama-llama3"): "llama3.2:latest"}
                )
                provider = OllamaProvider(config=config, client=client)
                resp = await provider.complete(make_test_request(), make_test_model())
                assert resp.finish_reason == exp

        asyncio.run(_run())


def test_request_model_mismatch() -> None:
    config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
    provider = OllamaProvider(config=config)

    req = make_test_request(model_id="ollama-llama3")
    model = make_test_model(model_id="different-model")

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(provider.complete(req, model))

    assert exc_info.value.error.code == ErrorCode.PROVIDER_INVALID_REQUEST
    assert exc_info.value.error.retryable is False


def test_wrong_provider_id() -> None:
    config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
    provider = OllamaProvider(config=config)

    req = make_test_request()
    model = make_test_model(provider_id="openai")

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(provider.complete(req, model))

    assert exc_info.value.error.code == ErrorCode.PROVIDER_UNSUPPORTED_MODEL
    assert exc_info.value.error.retryable is False


def test_disabled_model() -> None:
    config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
    provider = OllamaProvider(config=config)

    req = make_test_request()
    model = make_test_model(enabled=False)

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(provider.complete(req, model))

    assert exc_info.value.error.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert exc_info.value.error.retryable is False


def test_unknown_model_mapping() -> None:
    config = OllamaProviderConfig(model_names={})  # Empty mapping
    provider = OllamaProvider(config=config)

    req = make_test_request()
    model = make_test_model()

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(provider.complete(req, model))

    assert exc_info.value.error.code == ErrorCode.PROVIDER_UNSUPPORTED_MODEL
    assert exc_info.value.error.retryable is False


def test_timeout_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Timeout")

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.complete(make_test_request(), make_test_model())

            assert exc_info.value.error.code == ErrorCode.PROVIDER_TIMEOUT
            assert exc_info.value.error.retryable is True

    asyncio.run(_run())


def test_connection_error_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.complete(make_test_request(), make_test_model())

            assert exc_info.value.error.code == ErrorCode.PROVIDER_CONNECTION_ERROR
            assert exc_info.value.error.retryable is True

    asyncio.run(_run())


def test_http_status_mappings() -> None:
    status_expectations = [
        (400, ErrorCode.PROVIDER_INVALID_REQUEST, False),
        (404, ErrorCode.PROVIDER_UNSUPPORTED_MODEL, False),
        (429, ErrorCode.PROVIDER_RATE_LIMITED, True),
        (500, ErrorCode.PROVIDER_UNAVAILABLE, True),
        (502, ErrorCode.PROVIDER_UNAVAILABLE, True),
        (503, ErrorCode.PROVIDER_UNAVAILABLE, True),
        (504, ErrorCode.PROVIDER_UNAVAILABLE, True),
    ]

    for status, expected_code, expected_retryable in status_expectations:

        def handler(request: httpx.Request, s: int = status) -> httpx.Response:
            return httpx.Response(s, text="Error body")

        async def _run(exp_c: ErrorCode = expected_code, exp_r: bool = expected_retryable) -> None:
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost:11434"
            ) as client:
                config = OllamaProviderConfig(
                    model_names={ModelId("ollama-llama3"): "llama3.2:latest"}
                )
                provider = OllamaProvider(config=config, client=client)

                with pytest.raises(ProviderExecutionError) as exc_info:
                    await provider.complete(make_test_request(), make_test_model())

                assert exc_info.value.error.code == exp_c
                assert exc_info.value.error.retryable == exp_r

        asyncio.run(_run())


def test_invalid_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="NOT VALID JSON")

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.complete(make_test_request(), make_test_model())

            assert exc_info.value.error.code == ErrorCode.PROVIDER_MALFORMED_RESPONSE
            assert exc_info.value.error.retryable is False

    asyncio.run(_run())


def test_missing_message_content() -> None:
    bad_body = json.dumps({"done": True, "message": {"role": "assistant"}})  # Missing content

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=bad_body)

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.complete(make_test_request(), make_test_model())

            assert exc_info.value.error.code == ErrorCode.PROVIDER_MALFORMED_RESPONSE

    asyncio.run(_run())


def test_missing_token_fields() -> None:
    bad_body = json.dumps(
        {
            "done": True,
            "message": {"role": "assistant", "content": "hi"},
            # Missing prompt_eval_count & eval_count
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=bad_body)

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.complete(make_test_request(), make_test_model())

            assert exc_info.value.error.code == ErrorCode.PROVIDER_MALFORMED_RESPONSE

    asyncio.run(_run())


def test_blank_generated_content() -> None:
    bad_body = json.dumps(
        {
            "done": True,
            "message": {"role": "assistant", "content": "   "},  # Blank
            "prompt_eval_count": 5,
            "eval_count": 5,
            "total_duration": 1000,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=bad_body)

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as client:
            config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
            provider = OllamaProvider(config=config, client=client)

            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.complete(make_test_request(), make_test_model())

            assert exc_info.value.error.code == ErrorCode.PROVIDER_MALFORMED_RESPONSE

    asyncio.run(_run())


def test_client_reuse_and_cleanup() -> None:
    config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
    provider = OllamaProvider(config=config)
    assert not provider._client.is_closed
    asyncio.run(provider.aclose())
    assert provider._client.is_closed


def test_structural_compliance_with_llmprovider() -> None:
    config = OllamaProviderConfig(model_names={ModelId("ollama-llama3"): "llama3.2:latest"})
    provider = OllamaProvider(config=config)
    assert hasattr(provider, "complete")
    assert hasattr(provider, "provider_id")
    assert provider.provider_id == ProviderId("ollama")
