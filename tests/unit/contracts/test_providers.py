"""Unit tests for provider requests, responses, and execution error contracts."""

import pytest

from routeforge.contracts.common import AttemptId, ModelId, ProviderId, RequestId
from routeforge.contracts.errors import ErrorCode
from routeforge.contracts.inference import (
    ChatMessage,
    ChatRole,
    FinishReason,
    OutputFormat,
    TokenUsage,
)
from routeforge.contracts.providers import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)


def test_valid_provider_request() -> None:
    preq = ProviderRequest(
        request_id=RequestId("req_1"),
        attempt_id=AttemptId("att_1"),
        model_id=ModelId("gpt-4o"),
        messages=(ChatMessage(role=ChatRole.USER, content="Test prompt"),),
        output_format=OutputFormat.TEXT,
        timeout_ms=5000,
        idempotency_key="idem_123",
    )
    assert preq.request_id == RequestId("req_1")
    assert preq.timeout_ms == 5000


def test_provider_request_invalid_identifiers_and_messages() -> None:
    msg = (ChatMessage(role=ChatRole.USER, content="Test"),)

    with pytest.raises(ValueError, match="request_id cannot be empty"):
        ProviderRequest(
            request_id=RequestId(""),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("m1"),
            messages=msg,
            output_format=OutputFormat.TEXT,
            timeout_ms=1000,
            idempotency_key="idem_1",
        )

    with pytest.raises(ValueError, match="attempt_id cannot be empty"):
        ProviderRequest(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId(""),
            model_id=ModelId("m1"),
            messages=msg,
            output_format=OutputFormat.TEXT,
            timeout_ms=1000,
            idempotency_key="idem_1",
        )

    with pytest.raises(ValueError, match="model_id cannot be empty"):
        ProviderRequest(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId(""),
            messages=msg,
            output_format=OutputFormat.TEXT,
            timeout_ms=1000,
            idempotency_key="idem_1",
        )

    with pytest.raises(ValueError, match="idempotency_key cannot be empty"):
        ProviderRequest(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("m1"),
            messages=msg,
            output_format=OutputFormat.TEXT,
            timeout_ms=1000,
            idempotency_key="   ",
        )

    with pytest.raises(ValueError, match="ProviderRequest messages cannot be empty"):
        ProviderRequest(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("m1"),
            messages=(),
            output_format=OutputFormat.TEXT,
            timeout_ms=1000,
            idempotency_key="idem_1",
        )


def test_provider_request_iterable_conversion() -> None:
    msg = [ChatMessage(role=ChatRole.USER, content="Test")]  # list
    preq = ProviderRequest(
        request_id=RequestId("req_1"),
        attempt_id=AttemptId("att_1"),
        model_id=ModelId("gpt-4o"),
        messages=msg,  # type: ignore[arg-type]
        output_format=OutputFormat.TEXT,
        timeout_ms=5000,
        idempotency_key="idem_123",
    )
    assert isinstance(preq.messages, tuple)


def test_invalid_provider_request_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_ms must be positive"):
        ProviderRequest(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("gpt-4o"),
            messages=(ChatMessage(role=ChatRole.USER, content="Test prompt"),),
            output_format=OutputFormat.TEXT,
            timeout_ms=0,
            idempotency_key="idem_123",
        )


def test_valid_provider_response() -> None:
    presp = ProviderResponse(
        request_id=RequestId("req_1"),
        attempt_id=AttemptId("att_1"),
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        content="Response payload",
        finish_reason=FinishReason.STOP,
        usage=TokenUsage.unavailable(),
        latency_ms=250,
        provider_request_id="prov_req_999",
    )
    assert presp.latency_ms == 250
    assert presp.provider_request_id == "prov_req_999"


def test_provider_response_invalid_identifiers() -> None:
    usage = TokenUsage.unavailable()

    with pytest.raises(ValueError, match="request_id cannot be empty"):
        ProviderResponse(
            request_id=RequestId(""),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            latency_ms=100,
        )

    with pytest.raises(ValueError, match="attempt_id cannot be empty"):
        ProviderResponse(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId(""),
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            latency_ms=100,
        )

    with pytest.raises(ValueError, match="model_id cannot be empty"):
        ProviderResponse(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId(""),
            provider_id=ProviderId("p1"),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            latency_ms=100,
        )

    with pytest.raises(ValueError, match="provider_id cannot be empty"):
        ProviderResponse(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("m1"),
            provider_id=ProviderId(""),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            latency_ms=100,
        )


def test_invalid_provider_response_latency() -> None:
    with pytest.raises(ValueError, match="latency_ms must not be negative"):
        ProviderResponse(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            model_id=ModelId("gpt-4o"),
            provider_id=ProviderId("openai"),
            content="Response payload",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage.unavailable(),
            latency_ms=-50,
        )


def test_provider_error_contracts() -> None:
    perr = ProviderError(
        request_id=RequestId("req_1"),
        attempt_id=AttemptId("att_1"),
        provider_id=ProviderId("anthropic"),
        model_id=ModelId("claude-3-5-sonnet"),
        code=ErrorCode.PROVIDER_RATE_LIMITED,
        message="Rate limit exceeded.",
        retryable=True,
        provider_status_code=429,
    )
    assert perr.code == ErrorCode.PROVIDER_RATE_LIMITED
    assert perr.retryable is True
    assert perr.provider_status_code == 429


def test_provider_error_invalid_identifiers_and_message() -> None:
    with pytest.raises(ValueError, match="request_id cannot be empty"):
        ProviderError(
            request_id=RequestId(""),
            attempt_id=AttemptId("att_1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Error",
            retryable=True,
        )

    with pytest.raises(ValueError, match="attempt_id cannot be empty"):
        ProviderError(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId(""),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Error",
            retryable=True,
        )

    with pytest.raises(ValueError, match="provider_id cannot be empty"):
        ProviderError(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            provider_id=ProviderId(""),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Error",
            retryable=True,
        )

    with pytest.raises(ValueError, match="model_id cannot be empty"):
        ProviderError(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId(""),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Error",
            retryable=True,
        )

    with pytest.raises(ValueError, match="ProviderError message cannot be empty"):
        ProviderError(
            request_id=RequestId("req_1"),
            attempt_id=AttemptId("att_1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="   ",
            retryable=True,
        )
