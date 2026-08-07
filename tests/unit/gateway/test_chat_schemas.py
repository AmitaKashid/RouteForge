"""Unit tests for chat wire request and response Pydantic schemas."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from routeforge.contracts import RoutingReason
from routeforge.gateway.schemas import (
    ApiAssistantMessage,
    ApiChatMessage,
    ApiChatRole,
    ApiChoice,
    ApiGovernanceClassification,
    ApiUsage,
    ChatCompletionsRequest,
    ChatCompletionsResponse,
    ResponseFormat,
    RouteForgeRequestOptions,
    RouteForgeResponseMetadata,
)


def test_api_chat_message_validation() -> None:
    msg = ApiChatMessage(role=ApiChatRole.USER, content="Hello")
    assert msg.role == ApiChatRole.USER
    assert msg.content == "Hello"

    # Blank content rejected
    with pytest.raises(ValidationError):
        ApiChatMessage(role=ApiChatRole.USER, content="   ")

    # Unknown field rejected
    with pytest.raises(ValidationError):
        ApiChatMessage.model_validate({"role": "user", "content": "hi", "name": "Alice"})


def test_routeforge_request_options_validation() -> None:
    opts = RouteForgeRequestOptions(
        feature_id="general-chat",
        minimum_quality=0.85,
        maximum_latency_ms=300,
        maximum_estimated_cost_usd=Decimal("0.005000"),
        required_governance=ApiGovernanceClassification.PUBLIC,
        allow_degraded_provider=True,
    )
    assert opts.feature_id == "general-chat"
    assert opts.minimum_quality == 0.85
    assert opts.maximum_estimated_cost_usd == Decimal("0.005000")

    # Blank feature_id rejected
    with pytest.raises(ValidationError):
        RouteForgeRequestOptions(feature_id="  ")

    # Minimum quality out of bounds
    with pytest.raises(ValidationError):
        RouteForgeRequestOptions(feature_id="f", minimum_quality=1.5)

    # Maximum latency <= 0
    with pytest.raises(ValidationError):
        RouteForgeRequestOptions(feature_id="f", maximum_latency_ms=0)

    # Negative maximum cost
    with pytest.raises(ValidationError):
        RouteForgeRequestOptions(feature_id="f", maximum_estimated_cost_usd=Decimal("-0.01"))

    # Unknown field rejected
    with pytest.raises(ValidationError):
        RouteForgeRequestOptions.model_validate({"feature_id": "f", "unknown": True})


def test_chat_completions_request_validation() -> None:
    req = ChatCompletionsRequest(
        model="routeforge",
        messages=[ApiChatMessage(role=ApiChatRole.USER, content="Hi")],
        stream=False,
        response_format=ResponseFormat(type="json_object"),
        routeforge=RouteForgeRequestOptions(feature_id="general-chat"),
    )
    assert req.model == "routeforge"
    assert req.stream is False

    # Backend model ID rejected
    with pytest.raises(ValidationError):
        ChatCompletionsRequest.model_validate(
            {
                "model": "gpt-4o",  # Only 'routeforge' allowed!
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "f"},
            }
        )

    # Empty messages list rejected
    with pytest.raises(ValidationError):
        ChatCompletionsRequest(
            messages=[],
            routeforge=RouteForgeRequestOptions(feature_id="f"),
        )

    # stream=True rejected
    with pytest.raises(ValidationError):
        ChatCompletionsRequest.model_validate(
            {
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
                "routeforge": {"feature_id": "f"},
            }
        )

    # Unsupported OpenAI fields rejected (e.g. temperature, max_tokens)
    with pytest.raises(ValidationError):
        ChatCompletionsRequest.model_validate(
            {
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "temperature": 0.7,
                "routeforge": {"feature_id": "f"},
            }
        )


def test_chat_completions_response_validation() -> None:
    usage = ApiUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    meta = RouteForgeResponseMetadata(
        request_id="req_123",
        provider="mock",
        policy_version="v1",
        routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
        fallback_used=False,
    )
    choice = ApiChoice(
        index=0,
        message=ApiAssistantMessage(role="assistant", content="Hello there!"),
        finish_reason="stop",
    )
    resp = ChatCompletionsResponse(
        id="chatcmpl-123",
        created=1770000000,
        model="mock-economy",
        choices=[choice],
        usage=usage,
        routeforge=meta,
    )

    assert resp.id == "chatcmpl-123"
    assert resp.object == "chat.completion"
    assert resp.model == "mock-economy"

    # Total tokens mismatch rejected
    with pytest.raises(ValidationError, match="total_tokens"):
        ApiUsage(prompt_tokens=10, completion_tokens=5, total_tokens=99)

    # Empty choices rejected
    with pytest.raises(ValidationError):
        ChatCompletionsResponse(
            id="c",
            created=100,
            model="m",
            choices=[],
            usage=usage,
            routeforge=meta,
        )
