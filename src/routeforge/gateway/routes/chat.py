"""HTTP route handler for POST /v1/chat/completions."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from routeforge.contracts import (
    FeatureId,
    PolicyStatus,
    RequestId,
    TeamId,
    utc_now,
)
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.gateway.estimation import estimate_input_tokens
from routeforge.gateway.schemas import (
    ApiErrorDetail,
    ApiErrorMetadata,
    ApiErrorResponse,
    ChatCompletionsRequest,
    ChatCompletionsResponse,
)
from routeforge.gateway.translation import to_api_chat_response, to_domain_chat_request
from routeforge.storage.database import DatabaseManager
from routeforge.storage.records import (
    get_team_limits,
)

router = APIRouter()


def default_request_id_generator() -> RequestId:
    """Generate unique request correlation ID."""
    return RequestId(f"req_{uuid.uuid4().hex}")


@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionsResponse,
    responses={
        401: {"model": ApiErrorResponse, "description": "Unauthenticated or invalid API key."},
        402: {"model": ApiErrorResponse, "description": "Monthly budget limit exceeded."},
        403: {"model": ApiErrorResponse, "description": "Inactive API key or team."},
        404: {"model": ApiErrorResponse, "description": "Feature policy not found or inactive."},
        429: {"model": ApiErrorResponse, "description": "Requests or tokens rate limit exceeded."},
        502: {"model": ApiErrorResponse, "description": "Provider execution failure."},
        503: {
            "model": ApiErrorResponse,
            "description": "No eligible model or rate-limit backend unavailable.",
        },
    },
    tags=["Chat"],
)
async def create_chat_completion(
    api_request: ChatCompletionsRequest,
    request: Request,
    team_id: Annotated[TeamId, Depends(get_authenticated_team_id)],
) -> ChatCompletionsResponse | JSONResponse:
    """Execute authenticated chat completion using deterministic policy routing."""
    id_generator: Callable[[], RequestId] = getattr(
        request.app.state, "request_id_generator", default_request_id_generator
    )
    req_id = id_generator()
    now = utc_now()
    created_timestamp = datetime.now(UTC)

    domain_req = to_domain_chat_request(
        api_request,
        request_id=req_id,
        team_id=team_id,
        created_at=now,
    )

    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    rate_limiter = getattr(request.app.state, "rate_limiter", None)

    rate_limit_headers: dict[str, str] = {}

    # 1. Rate Limiting Check (Redis)
    limits = None
    if db_manager is not None:
        try:
            async with db_manager.session_factory() as session:
                limits = await get_team_limits(session, str(team_id))
        except Exception:
            limits = None

    if limits is not None and limits.active and rate_limiter is not None:
        est_input = estimate_input_tokens(domain_req)
        est_rate_tokens = est_input + 128  # 128 output token budget

        from routeforge.storage.ratelimit import RedisUnavailableError

        try:
            rl_res = await rate_limiter.check_and_consume(
                team_id=str(team_id),
                requests_per_minute=limits.requests_per_minute,
                tokens_per_minute=limits.tokens_per_minute,
                estimated_tokens=est_rate_tokens,
                now=created_timestamp,
            )
        except RedisUnavailableError as exc:
            err_body = ApiErrorResponse(
                error=ApiErrorDetail(
                    message=f"Rate limit backend unavailable: {exc}",
                    type="service_unavailable",
                    code="RATE_LIMIT_BACKEND_UNAVAILABLE",
                ),
                routeforge=ApiErrorMetadata(request_id=str(req_id)),
            )
            return JSONResponse(status_code=503, content=err_body.model_dump(mode="json"))

        if not rl_res.allowed:
            code_val = (
                "REQUEST_RATE_LIMIT_EXCEEDED"
                if rl_res.exceeded_limit_type == "requests"
                else "TOKEN_RATE_LIMIT_EXCEEDED"
            )
            err_body = ApiErrorResponse(
                error=ApiErrorDetail(
                    message=f"Rate limit exceeded: {rl_res.exceeded_limit_type} limit.",
                    type="rate_limit_error",
                    code=code_val,
                ),
                routeforge=ApiErrorMetadata(request_id=str(req_id)),
            )
            exceeded_limit = (
                rl_res.limit_requests
                if rl_res.exceeded_limit_type == "requests"
                else rl_res.limit_tokens
            )
            headers = {
                "Retry-After": str(rl_res.retry_after_seconds),
                "X-RateLimit-Limit": str(exceeded_limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(rl_res.reset_timestamp),
            }
            return JSONResponse(
                status_code=429,
                content=err_body.model_dump(mode="json"),
                headers=headers,
            )

        rate_limit_headers = {
            "X-RateLimit-Limit-Requests": str(rl_res.limit_requests),
            "X-RateLimit-Remaining-Requests": str(rl_res.remaining_requests),
            "X-RateLimit-Limit-Tokens": str(rl_res.limit_tokens),
            "X-RateLimit-Remaining-Tokens": str(rl_res.remaining_tokens),
            "X-RateLimit-Reset": str(rl_res.reset_timestamp),
        }

    # 2. Resolve Policy & Candidates
    policy_registry = request.app.state.policy_registry
    model_registry = request.app.state.model_registry
    provider = request.app.state.provider

    policy = policy_registry.get_active_for_feature(FeatureId(api_request.routeforge.feature_id))
    if policy is None or policy.status != PolicyStatus.ACTIVE:
        err_body = ApiErrorResponse(
            error=ApiErrorDetail(
                message=f"Feature policy '{api_request.routeforge.feature_id}' not found.",
                type="invalid_request_error",
                code="FEATURE_NOT_FOUND",
            ),
            routeforge=ApiErrorMetadata(request_id=str(req_id)),
        )
        return JSONResponse(status_code=404, content=err_body.model_dump(mode="json"))

    candidate_models = [
        model_registry.get(m_id)
        for m_id in policy.allowed_model_ids
        if model_registry.get(m_id) is not None
    ]

    profile_registry = getattr(request.app.state, "profile_registry", None)
    runtime_manager = getattr(request.app.state, "runtime_manager", None)
    circuit_breaker = getattr(request.app.state, "circuit_breaker", None)

    from typing import cast

    from routeforge.gateway.inference import execute_inference
    from routeforge.providers import LLMProvider

    def resolve_provider(p_id: Any) -> LLMProvider:
        if runtime_manager is not None:
            p = runtime_manager.get_provider(str(p_id))
            if p is not None:
                return cast(LLMProvider, p)
        return cast(LLMProvider, provider)

    exec_result = await execute_inference(
        request=domain_req,
        policy=policy,
        candidate_models=[m for m in candidate_models if m is not None],
        provider_resolver=resolve_provider,
        db_manager=db_manager,
        profile_registry=profile_registry,
        circuit_breaker=circuit_breaker,
        redis_client=getattr(rate_limiter, "redis", rate_limiter),
    )

    if not exec_result.success:
        err_type = (
            "budget_error"
            if exec_result.http_status_code == 402
            else ("routing_error" if exec_result.http_status_code == 503 else "provider_error")
        )
        err_code_val = (
            exec_result.error_code.value
            if (exec_result.error_code is not None and hasattr(exec_result.error_code, "value"))
            else str(exec_result.error_code or "INTERNAL_ERROR")
        )
        err_body = ApiErrorResponse(
            error=ApiErrorDetail(
                message=exec_result.error_message or "Execution failed.",
                type=err_type,
                code=err_code_val,
            ),
            routeforge=ApiErrorMetadata(request_id=str(req_id)),
        )
        return JSONResponse(
            status_code=exec_result.http_status_code,
            content=err_body.model_dump(mode="json"),
        )

    assert exec_result.decision is not None
    assert exec_result.response is not None

    response_obj = to_api_chat_response(
        decision=exec_result.decision,
        provider_response=exec_result.response,
        created_at=now,
    )

    if rate_limit_headers:
        response_dict = response_obj.model_dump(mode="json")
        return JSONResponse(
            status_code=200,
            content=response_dict,
            headers=rate_limit_headers,
        )

    return response_obj
