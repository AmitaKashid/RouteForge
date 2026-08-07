"""Unit tests for gateway API-to-domain and domain-to-API translation."""

from datetime import UTC, datetime
from decimal import Decimal

from routeforge.contracts import (
    AttemptId,
    CandidateEstimate,
    CandidateEvaluation,
    ChatMessage,
    ChatRole,
    EstimateProvenance,
    FeatureId,
    FinishReason,
    GovernanceClassification,
    ModelId,
    OutputFormat,
    PolicyId,
    PolicyVersion,
    ProviderId,
    ProviderResponse,
    RequestId,
    RoutingDecision,
    RoutingReason,
    TeamId,
    TokenUsage,
    UsageSource,
)
from routeforge.gateway.schemas import (
    ApiChatMessage,
    ApiChatRole,
    ApiGovernanceClassification,
    ChatCompletionsRequest,
    ResponseFormat,
    RouteForgeRequestOptions,
)
from routeforge.gateway.translation import to_api_chat_response, to_domain_chat_request


def test_to_domain_chat_request_text_format() -> None:
    req_id = RequestId("req_test_123")
    team_id = TeamId("local-development")
    now = datetime.now(UTC)

    api_req = ChatCompletionsRequest(
        model="routeforge",
        messages=[
            ApiChatMessage(role=ApiChatRole.SYSTEM, content="System prompt"),
            ApiChatMessage(role=ApiChatRole.USER, content="User prompt"),
        ],
        stream=False,
        response_format=ResponseFormat(type="text"),
        routeforge=RouteForgeRequestOptions(
            feature_id="general-chat",
            minimum_quality=0.8,
            maximum_latency_ms=200,
            maximum_estimated_cost_usd=Decimal("0.005"),
            required_governance=ApiGovernanceClassification.INTERNAL,
            allow_degraded_provider=True,
        ),
    )

    domain_req = to_domain_chat_request(
        api_req,
        request_id=req_id,
        team_id=team_id,
        created_at=now,
    )

    assert domain_req.request_id == req_id
    assert domain_req.team_id == team_id
    assert domain_req.feature_id == "general-chat"
    assert len(domain_req.messages) == 2
    assert domain_req.messages[0] == ChatMessage(role=ChatRole.SYSTEM, content="System prompt")
    assert domain_req.messages[1] == ChatMessage(role=ChatRole.USER, content="User prompt")
    assert domain_req.output_format == OutputFormat.TEXT
    assert domain_req.routing_constraints.minimum_quality == 0.8
    assert domain_req.routing_constraints.maximum_latency_ms == 200
    assert domain_req.routing_constraints.maximum_estimated_cost_usd == Decimal("0.005")
    assert domain_req.routing_constraints.required_governance == GovernanceClassification.INTERNAL
    assert domain_req.routing_constraints.allow_degraded_provider is True
    assert domain_req.created_at == now


def test_to_domain_chat_request_json_format() -> None:
    req_id = RequestId("req_json_1")
    team_id = TeamId("local-development")
    now = datetime.now(UTC)

    api_req = ChatCompletionsRequest(
        model="routeforge",
        messages=[ApiChatMessage(role=ApiChatRole.USER, content="Generate JSON")],
        response_format=ResponseFormat(type="json_object"),
        routeforge=RouteForgeRequestOptions(feature_id="general-chat"),
    )

    domain_req = to_domain_chat_request(
        api_req,
        request_id=req_id,
        team_id=team_id,
        created_at=now,
    )

    assert domain_req.output_format == OutputFormat.JSON


def test_to_api_chat_response_mapping() -> None:
    req_id = RequestId("req_resp_1")
    now = datetime.now(UTC)

    est = CandidateEstimate(
        predicted_quality=0.8,
        estimated_latency_ms=100,
        estimated_cost_usd=Decimal("0.001"),
        quality_provenance=EstimateProvenance(source="test", version="v1"),
        latency_provenance=EstimateProvenance(source="test", version="v1"),
        cost_provenance=EstimateProvenance(source="test", version="v1"),
    )

    eval_item = CandidateEvaluation(
        model_id=ModelId("mock-economy"),
        provider_id=ProviderId("mock"),
        eligible=True,
        estimate=est,
        rejection_reasons=(),
    )

    decision = RoutingDecision(
        request_id=req_id,
        team_id=TeamId("local-development"),
        feature_id=FeatureId("general-chat"),
        policy_id=PolicyId("general-chat-policy"),
        policy_version=PolicyVersion("v1"),
        selected_model_id=ModelId("mock-economy"),
        selected_provider_id=ProviderId("mock"),
        routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
        candidates=(eval_item,),
        decided_at=now,
    )

    provider_resp = ProviderResponse(
        request_id=req_id,
        attempt_id=AttemptId("att_1"),
        provider_id=ProviderId("mock"),
        model_id=ModelId("mock-economy"),
        content="mock-response-content",
        finish_reason=FinishReason.STOP,
        usage=TokenUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            source=UsageSource.PROVIDER_REPORTED,
        ),
        latency_ms=42,
    )

    api_resp = to_api_chat_response(
        decision=decision,
        provider_response=provider_resp,
        created_at=now,
    )

    assert api_resp.id == f"chatcmpl-{req_id}"
    assert api_resp.object == "chat.completion"
    assert api_resp.model == "mock-economy"
    assert len(api_resp.choices) == 1
    assert api_resp.choices[0].message.content == "mock-response-content"
    assert api_resp.choices[0].finish_reason == "stop"
    assert api_resp.usage.prompt_tokens == 10
    assert api_resp.usage.completion_tokens == 5
    assert api_resp.usage.total_tokens == 15
    assert api_resp.routeforge.request_id == str(req_id)
    assert api_resp.routeforge.provider == "mock"
    assert api_resp.routeforge.routing_reason == RoutingReason.CHEAPEST_ELIGIBLE_MODEL
    assert api_resp.routeforge.fallback_used is False
