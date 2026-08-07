"""Unit tests for inference chat request, response, constraints, and token usage contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts.common import (
    Capability,
    FeatureId,
    GovernanceClassification,
    ModelId,
    ProviderId,
    RequestId,
    TeamId,
)
from routeforge.contracts.inference import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
    FinishReason,
    OutputFormat,
    RoutingConstraints,
    TokenUsage,
    UsageSource,
)


def test_valid_chat_request() -> None:
    req = ChatRequest(
        request_id=RequestId("req_100"),
        team_id=TeamId("team_alpha"),
        feature_id=FeatureId("feat_search"),
        messages=(
            ChatMessage(role=ChatRole.SYSTEM, content="You are a helpful bot."),
            ChatMessage(role=ChatRole.USER, content="Hello!"),
        ),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(
            minimum_quality=0.8,
            maximum_latency_ms=500,
            maximum_estimated_cost_usd=Decimal("0.01"),
            required_capabilities=(Capability.TEXT_CHAT,),
            required_governance=GovernanceClassification.INTERNAL,
            allow_degraded_provider=False,
        ),
        created_at=datetime.now(UTC),
    )
    assert req.request_id == RequestId("req_100")
    assert req.messages[-1].role == ChatRole.USER
    assert req.routing_constraints.minimum_quality == 0.8


def test_blank_chat_message_content_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        ChatMessage(role=ChatRole.USER, content="   ")

    with pytest.raises(ValueError, match="non-empty string"):
        ChatMessage(role=ChatRole.USER, content=123)  # type: ignore[arg-type]


def test_empty_messages_list_rejected() -> None:
    with pytest.raises(ValueError, match="messages list cannot be empty"):
        ChatRequest(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            messages=(),
            output_format=OutputFormat.TEXT,
            routing_constraints=RoutingConstraints(),
            created_at=datetime.now(UTC),
        )


def test_final_non_user_message_rejected() -> None:
    with pytest.raises(ValueError, match="final message in ChatRequest must have role USER"):
        ChatRequest(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            messages=(
                ChatMessage(role=ChatRole.USER, content="Hello"),
                ChatMessage(role=ChatRole.ASSISTANT, content="Hi there"),
            ),
            output_format=OutputFormat.TEXT,
            routing_constraints=RoutingConstraints(),
            created_at=datetime.now(UTC),
        )


def test_chat_request_invalid_identifiers() -> None:
    msgs = (ChatMessage(role=ChatRole.USER, content="Hi"),)
    constraints = RoutingConstraints()
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="request_id cannot be empty"):
        ChatRequest(
            request_id=RequestId(""),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            messages=msgs,
            output_format=OutputFormat.TEXT,
            routing_constraints=constraints,
            created_at=now,
        )

    with pytest.raises(ValueError, match="team_id cannot be empty"):
        ChatRequest(
            request_id=RequestId("r1"),
            team_id=TeamId(""),
            feature_id=FeatureId("f1"),
            messages=msgs,
            output_format=OutputFormat.TEXT,
            routing_constraints=constraints,
            created_at=now,
        )

    with pytest.raises(ValueError, match="feature_id cannot be empty"):
        ChatRequest(
            request_id=RequestId("r1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId(""),
            messages=msgs,
            output_format=OutputFormat.TEXT,
            routing_constraints=constraints,
            created_at=now,
        )


def test_chat_request_messages_iterable_conversion() -> None:
    msgs = [ChatMessage(role=ChatRole.USER, content="Hi")]  # list
    req = ChatRequest(
        request_id=RequestId("r1"),
        team_id=TeamId("t1"),
        feature_id=FeatureId("f1"),
        messages=msgs,  # type: ignore[arg-type]
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )
    assert isinstance(req.messages, tuple)


def test_invalid_routing_constraints() -> None:
    with pytest.raises(ValueError, match="minimum_quality must be between"):
        RoutingConstraints(minimum_quality=1.5)

    with pytest.raises(ValueError, match="minimum_quality must be between"):
        RoutingConstraints(minimum_quality=-0.1)

    with pytest.raises(ValueError, match="maximum_latency_ms must be positive"):
        RoutingConstraints(maximum_latency_ms=0)

    with pytest.raises(ValueError, match="maximum_estimated_cost_usd must not be negative"):
        RoutingConstraints(maximum_estimated_cost_usd=Decimal("-0.01"))

    rc = RoutingConstraints(required_capabilities=[Capability.TEXT_CHAT])  # type: ignore[arg-type]
    assert isinstance(rc.required_capabilities, tuple)


def test_timezone_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="must be timezone-aware"):
        ChatRequest(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            messages=(ChatMessage(role=ChatRole.USER, content="Hello"),),
            output_format=OutputFormat.TEXT,
            routing_constraints=RoutingConstraints(),
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )


def test_valid_and_unavailable_token_usage() -> None:
    usage = TokenUsage(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        source=UsageSource.PROVIDER_REPORTED,
    )
    assert usage.total_tokens == 150

    unavail = TokenUsage.unavailable()
    assert unavail.source == UsageSource.UNAVAILABLE
    assert unavail.total_tokens == 0


def test_invalid_token_usage() -> None:
    with pytest.raises(ValueError, match="Token counts cannot be negative"):
        TokenUsage(
            input_tokens=-1,
            output_tokens=10,
            total_tokens=9,
            source=UsageSource.PROVIDER_REPORTED,
        )

    with pytest.raises(ValueError, match=r"total_tokens .* must equal input_tokens"):
        TokenUsage(
            input_tokens=10,
            output_tokens=20,
            total_tokens=100,
            source=UsageSource.PROVIDER_REPORTED,
        )


def test_valid_chat_response() -> None:
    resp = ChatResponse(
        request_id=RequestId("req_1"),
        response_id="resp_999",
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        content="Response text.",
        finish_reason=FinishReason.STOP,
        usage=TokenUsage.unavailable(),
        created_at=datetime.now(UTC),
    )
    assert resp.response_id == "resp_999"
    assert resp.finish_reason == FinishReason.STOP


def test_chat_response_invalid_identifiers() -> None:
    now = datetime.now(UTC)
    usage = TokenUsage.unavailable()

    with pytest.raises(ValueError, match="request_id cannot be empty"):
        ChatResponse(
            request_id=RequestId(""),
            response_id="resp_1",
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            created_at=now,
        )

    with pytest.raises(ValueError, match="response_id cannot be empty"):
        ChatResponse(
            request_id=RequestId("req_1"),
            response_id="   ",
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            created_at=now,
        )

    with pytest.raises(ValueError, match="model_id cannot be empty"):
        ChatResponse(
            request_id=RequestId("req_1"),
            response_id="resp_1",
            model_id=ModelId(""),
            provider_id=ProviderId("p1"),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            created_at=now,
        )

    with pytest.raises(ValueError, match="provider_id cannot be empty"):
        ChatResponse(
            request_id=RequestId("req_1"),
            response_id="resp_1",
            model_id=ModelId("m1"),
            provider_id=ProviderId(""),
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=usage,
            created_at=now,
        )
