"""API wire contracts to internal domain contracts translation module."""

from datetime import datetime

from routeforge.contracts import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
    FeatureId,
    GovernanceClassification,
    OutputFormat,
    ProviderResponse,
    RequestId,
    RoutingConstraints,
    RoutingDecision,
    TeamId,
)
from routeforge.gateway.schemas import (
    ApiAssistantMessage,
    ApiChatRole,
    ApiChoice,
    ApiGovernanceClassification,
    ApiUsage,
    ChatCompletionsRequest,
    ChatCompletionsResponse,
    RouteForgeResponseMetadata,
)

ROLE_MAP: dict[ApiChatRole, ChatRole] = {
    ApiChatRole.SYSTEM: ChatRole.SYSTEM,
    ApiChatRole.USER: ChatRole.USER,
    ApiChatRole.ASSISTANT: ChatRole.ASSISTANT,
}

GOVERNANCE_MAP: dict[ApiGovernanceClassification, GovernanceClassification] = {
    ApiGovernanceClassification.PUBLIC: GovernanceClassification.PUBLIC,
    ApiGovernanceClassification.INTERNAL: GovernanceClassification.INTERNAL,
    ApiGovernanceClassification.CONFIDENTIAL: GovernanceClassification.CONFIDENTIAL,
    ApiGovernanceClassification.RESTRICTED: GovernanceClassification.RESTRICTED,
}


def to_domain_chat_request(
    api_request: ChatCompletionsRequest,
    *,
    request_id: RequestId,
    team_id: TeamId,
    created_at: datetime,
) -> ChatRequest:
    """Translate gateway ChatCompletionsRequest model into internal ChatRequest domain model."""
    domain_messages = tuple(
        ChatMessage(
            role=ROLE_MAP[msg.role],
            content=msg.content,
        )
        for msg in api_request.messages
    )

    output_format = OutputFormat.TEXT
    if api_request.response_format and api_request.response_format.type == "json_object":
        output_format = OutputFormat.JSON

    opts = api_request.routeforge
    required_gov = GOVERNANCE_MAP[opts.required_governance] if opts.required_governance else None

    constraints = RoutingConstraints(
        minimum_quality=opts.minimum_quality,
        maximum_latency_ms=opts.maximum_latency_ms,
        maximum_estimated_cost_usd=opts.maximum_estimated_cost_usd,
        required_governance=required_gov,
        allow_degraded_provider=opts.allow_degraded_provider,
    )

    return ChatRequest(
        request_id=request_id,
        team_id=team_id,
        feature_id=FeatureId(opts.feature_id),
        messages=domain_messages,
        output_format=output_format,
        routing_constraints=constraints,
        created_at=created_at,
    )


def to_api_chat_response(
    *,
    decision: RoutingDecision,
    provider_response: ProviderResponse | ChatResponse,
    created_at: datetime,
) -> ChatCompletionsResponse:
    """Translate RoutingDecision and ProviderResponse into ChatCompletionsResponse wire model."""
    choice = ApiChoice(
        index=0,
        message=ApiAssistantMessage(role="assistant", content=provider_response.content),
        finish_reason=provider_response.finish_reason.value.lower(),  # type: ignore[arg-type]
    )

    usage = ApiUsage(
        prompt_tokens=provider_response.usage.input_tokens,
        completion_tokens=provider_response.usage.output_tokens,
        total_tokens=provider_response.usage.total_tokens,
    )

    routeforge_meta = RouteForgeResponseMetadata(
        request_id=str(decision.request_id),
        provider=str(provider_response.provider_id),
        policy_version=str(decision.policy_version),
        routing_reason=decision.routing_reason,
        fallback_used=decision.fallback_used,
        retry_count=decision.retry_count,
    )

    return ChatCompletionsResponse(
        id=f"chatcmpl-{decision.request_id}",
        object="chat.completion",
        created=int(created_at.timestamp()),
        model=str(provider_response.model_id),
        choices=[choice],
        usage=usage,
        routeforge=routeforge_meta,
    )
