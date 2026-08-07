"""Gateway integration tests for Milestone 5.2 Circuit Breakers and Passive Provider Health."""

from decimal import Decimal

import pytest

from routeforge.contracts import (
    Capability,
    ChatMessage,
    ChatRequest,
    ChatRole,
    CircuitBreakerPolicy,
    ErrorCode,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    FinishReason,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    PolicyId,
    PolicyStatus,
    PolicyVersion,
    ProviderError,
    ProviderId,
    ProviderRequest,
    ProviderResponse,
    RequestId,
    RetryPolicy,
    RoutingConstraints,
    TeamId,
    TokenUsage,
    UsageSource,
    utc_now,
)
from routeforge.gateway.inference import execute_inference
from routeforge.providers import LLMProvider, ProviderExecutionError
from routeforge.resilience import CircuitState, RedisCircuitBreaker
from tests.unit.resilience.test_circuit_breaker_unit import DummyRedisClient


class ConfigurableTestProvider(LLMProvider):
    """Deterministic test provider supporting success and failure modes."""

    def __init__(self, provider_id: str, failure_code: ErrorCode | None = None) -> None:
        self._provider_id = ProviderId(provider_id)
        self.failure_code = failure_code
        self.call_count = 0

    @property
    def provider_id(self) -> ProviderId:
        return self._provider_id

    async def complete(self, request: ProviderRequest, model: ModelDefinition) -> ProviderResponse:
        self.call_count += 1
        if self.failure_code is not None:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self._provider_id,
                    model_id=request.model_id,
                    code=self.failure_code,
                    message=f"Simulated error: {self.failure_code}",
                    retryable=self.failure_code
                    in (
                        ErrorCode.PROVIDER_TIMEOUT,
                        ErrorCode.PROVIDER_RATE_LIMITED,
                        ErrorCode.PROVIDER_CONNECTION_ERROR,
                        ErrorCode.PROVIDER_UNAVAILABLE,
                    ),
                )
            )
        return ProviderResponse(
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            model_id=request.model_id,
            provider_id=self._provider_id,
            content=f"Response from {self._provider_id}:{request.model_id}",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                source=UsageSource.PROVIDER_REPORTED,
            ),
            latency_ms=45,
        )


def make_test_model(m_id: str, p_id: str, cost: Decimal = Decimal("1.00")) -> ModelDefinition:
    from routeforge.contracts.models import QualityProfile

    qp = QualityProfile(
        task_type="summarization",
        predicted_quality=0.9,
        source="benchmark",
        version="1.0.0",
    )
    return ModelDefinition(
        model_id=ModelId(m_id),
        provider_id=ProviderId(p_id),
        display_name=m_id,
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=8192,
        estimated_input_cost_per_million_tokens_usd=cost,
        estimated_output_cost_per_million_tokens_usd=cost,
        estimated_latency_ms=100,
        quality_profiles=(qp,),
        enabled=True,
        configuration_version="1.0.0",
    )


def make_test_policy(
    allowed_models: list[str],
    pinned: str | None = None,
    cb_enabled: bool = True,
    threshold: int = 3,
    cooldown: int = 30,
) -> FeaturePolicy:
    return FeaturePolicy(
        policy_id=PolicyId("policy-m52"),
        version=PolicyVersion("1.0.0"),
        feature_id=FeatureId("summarization"),
        status=PolicyStatus.ACTIVE,
        allowed_model_ids=tuple(ModelId(m) for m in allowed_models),
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.5,
        maximum_latency_ms=500,
        maximum_estimated_cost_usd=Decimal("0.10"),
        maximum_governance_classification=GovernanceClassification.PUBLIC,
        allow_degraded_providers=True,
        retry_policy=RetryPolicy(enabled=True, maximum_retries=1, initial_backoff_ms=10),
        fallback_policy=FallbackPolicy(enabled=True, maximum_fallback_attempts=2),
        circuit_breaker_policy=CircuitBreakerPolicy(
            enabled=cb_enabled, failure_threshold=threshold, open_duration_seconds=cooldown
        ),
        created_at=utc_now(),
        pinned_model_id=ModelId(pinned) if pinned else None,
    )


@pytest.mark.anyio
async def test_m52_closed_primary_executes_normally() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)

    p1 = ConfigurableTestProvider("provider-a")
    model_a = make_test_model("model-a", "provider-a", Decimal("1.00"))
    policy = make_test_policy(["model-a"])

    req = ChatRequest(
        request_id=RequestId("req-1"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Hello"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=utc_now(),
    )

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p1,
        circuit_breaker=cb,
    )

    assert res.success is True
    assert res.selected_model_id == ModelId("model-a")
    assert res.fallback_used is False
    assert p1.call_count == 1

    snap = await cb.get_routing_state("provider-a", "model-a", policy.circuit_breaker_policy)
    assert snap.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_m52_repeated_terminal_failures_open_primary_and_prerouting_avoidance() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)

    p_failing = ConfigurableTestProvider("provider-a", failure_code=ErrorCode.PROVIDER_TIMEOUT)
    p_healthy = ConfigurableTestProvider("provider-b")

    model_a = make_test_model("model-a", "provider-a", Decimal("1.00"))
    model_b = make_test_model("model-b", "provider-b", Decimal("2.00"))
    policy = make_test_policy(["model-a", "model-b"], threshold=2)

    def resolver(pid: ProviderId) -> LLMProvider:
        return p_failing if pid == ProviderId("provider-a") else p_healthy

    req = ChatRequest(
        request_id=RequestId("req-fail-1"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Test"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=utc_now(),
    )

    res1 = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model_a, model_b],
        provider_resolver=resolver,
        circuit_breaker=cb,
    )
    assert res1.success is True
    assert res1.fallback_used is True

    res2 = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model_a, model_b],
        provider_resolver=resolver,
        circuit_breaker=cb,
    )
    assert res2.success is True

    snap_a = await cb.get_routing_state("provider-a", "model-a", policy.circuit_breaker_policy)
    assert snap_a.circuit_state == CircuitState.OPEN

    p_failing.call_count = 0
    p_healthy.call_count = 0

    res3 = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model_a, model_b],
        provider_resolver=resolver,
        circuit_breaker=cb,
    )

    assert res3.success is True
    assert res3.selected_model_id == ModelId("model-b")
    assert res3.fallback_used is False
    assert res3.retry_count == 0
    assert p_failing.call_count == 0
    assert p_healthy.call_count == 1


@pytest.mark.anyio
async def test_m52_pinned_model_with_open_circuit_returns_503() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)

    p_failing = ConfigurableTestProvider("provider-a", failure_code=ErrorCode.PROVIDER_TIMEOUT)
    model_a = make_test_model("model-a", "provider-a")
    policy = make_test_policy(["model-a"], pinned="model-a", threshold=1)

    req = ChatRequest(
        request_id=RequestId("req-pinned"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Test"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=utc_now(),
    )

    await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p_failing,
        circuit_breaker=cb,
    )

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p_failing,
        circuit_breaker=cb,
    )

    assert res.success is False
    assert res.error_code == ErrorCode.NO_ELIGIBLE_MODEL
    assert res.http_status_code == 503


@pytest.mark.anyio
async def test_m52_half_open_probe_success_closes_circuit() -> None:
    from datetime import UTC, datetime

    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)

    p_provider = ConfigurableTestProvider("provider-a")
    model_a = make_test_model("model-a", "provider-a")
    policy = make_test_policy(["model-a"], threshold=1, cooldown=30)

    req1 = ChatRequest(
        request_id=RequestId("req-probe-1"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Probe Test"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(allow_degraded_provider=True),
        created_at=utc_now(),
    )

    # 1. Trigger OPEN state
    p_provider.failure_code = ErrorCode.PROVIDER_TIMEOUT
    await execute_inference(
        request=req1,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p_provider,
        circuit_breaker=cb,
    )

    snap_open = await cb.get_routing_state("provider-a", "model-a", policy.circuit_breaker_policy)
    assert snap_open.circuit_state == CircuitState.OPEN
    assert snap_open.open_until is not None

    # 2. Advance time beyond open_until -> HALF_OPEN
    probe_timestamp = snap_open.open_until + 5.0
    probe_dt = datetime.fromtimestamp(probe_timestamp, tz=UTC)

    snap_ho = await cb.get_routing_state(
        "provider-a", "model-a", policy.circuit_breaker_policy, now=probe_timestamp
    )
    assert snap_ho.circuit_state == CircuitState.HALF_OPEN

    # 3. Make provider succeed and execute probe request at probe_dt
    req2 = ChatRequest(
        request_id=RequestId("req-probe-2"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Probe Test 2"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(allow_degraded_provider=True),
        created_at=probe_dt,
    )
    p_provider.failure_code = None
    res = await execute_inference(
        request=req2,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p_provider,
        circuit_breaker=cb,
    )

    assert res.success is True
    assert res.attempts[0].is_half_open_probe is True

    # 4. Verify circuit returned to CLOSED
    snap_closed = await cb.get_routing_state(
        "provider-a", "model-a", policy.circuit_breaker_policy, now=probe_timestamp + 1.0
    )
    assert snap_closed.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_m52_half_open_probe_failure_reopens_circuit() -> None:
    from datetime import UTC, datetime

    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)

    p_failing = ConfigurableTestProvider("provider-a", failure_code=ErrorCode.PROVIDER_TIMEOUT)
    model_a = make_test_model("model-a", "provider-a")
    policy = make_test_policy(["model-a"], threshold=1, cooldown=30)

    req1 = ChatRequest(
        request_id=RequestId("req-probe-fail-1"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Probe Fail"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(allow_degraded_provider=True),
        created_at=utc_now(),
    )

    # 1. Trigger OPEN state
    await execute_inference(
        request=req1,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p_failing,
        circuit_breaker=cb,
    )

    snap_open = await cb.get_routing_state("provider-a", "model-a", policy.circuit_breaker_policy)
    assert snap_open.circuit_state == CircuitState.OPEN
    assert snap_open.open_until is not None

    # 2. Advance time -> HALF_OPEN
    probe_timestamp = snap_open.open_until + 5.0
    probe_dt = datetime.fromtimestamp(probe_timestamp, tz=UTC)

    snap_ho = await cb.get_routing_state(
        "provider-a", "model-a", policy.circuit_breaker_policy, now=probe_timestamp
    )
    assert snap_ho.circuit_state == CircuitState.HALF_OPEN

    # 3. Probe fails at probe_dt -> reopens immediately with new open_until (probe_timestamp + 30)
    req2 = ChatRequest(
        request_id=RequestId("req-probe-fail-2"),
        team_id=TeamId("team-1"),
        feature_id=FeatureId("summarization"),
        messages=(ChatMessage(role=ChatRole.USER, content="Probe Fail 2"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(allow_degraded_provider=True),
        created_at=probe_dt,
    )
    res = await execute_inference(
        request=req2,
        policy=policy,
        candidate_models=[model_a],
        provider_resolver=lambda pid: p_failing,
        circuit_breaker=cb,
    )

    assert res.success is False
    assert res.attempts[0].is_half_open_probe is True

    snap_reopened = await cb.get_routing_state(
        "provider-a", "model-a", policy.circuit_breaker_policy, now=probe_timestamp + 1.0
    )
    assert snap_reopened.circuit_state == CircuitState.OPEN
    assert snap_reopened.open_until == pytest.approx(probe_timestamp + 30.0, abs=2.0)
