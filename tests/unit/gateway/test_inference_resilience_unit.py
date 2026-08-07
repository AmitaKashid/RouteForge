"""Unit tests for M5.1 policy-controlled retry and fallback resilience mechanics."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from routeforge.contracts import (
    AttemptId,
    ChatMessage,
    ChatRequest,
    ChatRole,
    ErrorCode,
    ExecutionAttemptKind,
    ExecutionAttemptOutcome,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    FinishReason,
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
    RoutingReason,
    TeamId,
    TokenUsage,
    UsageSource,
)
from routeforge.gateway.inference import (
    calculate_exponential_backoff_ms,
    execute_inference,
)
from routeforge.providers import LLMProvider, ProviderExecutionError


def _make_model(model_id: str, provider_id: str, cost: str = "0.001000") -> ModelDefinition:
    from routeforge.contracts import Capability, GovernanceClassification, QualityProfile

    return ModelDefinition(
        model_id=ModelId(model_id),
        provider_id=ProviderId(provider_id),
        display_name=model_id,
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal(cost),
        estimated_output_cost_per_million_tokens_usd=Decimal(cost),
        estimated_latency_ms=100,
        quality_profiles=(
            QualityProfile(
                task_type="general",
                predicted_quality=0.9,
                source="test",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )


def _make_policy(
    allowed_models: tuple[ModelId, ...] = (ModelId("m1"), ModelId("m2")),
    retry_enabled: bool | None = None,
    max_retries: int = 1,
    initial_backoff_ms: int = 100,
    fallback_enabled: bool | None = None,
    max_fallbacks: int = 1,
    pinned_model: ModelId | None = None,
) -> FeaturePolicy:
    from routeforge.contracts import Capability, GovernanceClassification

    if retry_enabled is None:
        retry_enabled = max_retries > 0
    if fallback_enabled is None:
        fallback_enabled = max_fallbacks > 0

    return FeaturePolicy(
        policy_id=PolicyId("p1"),
        version=PolicyVersion("v1"),
        feature_id=FeatureId("general-chat"),
        status=PolicyStatus.ACTIVE,
        allowed_model_ids=allowed_models,
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.5,
        maximum_latency_ms=5000,
        maximum_estimated_cost_usd=Decimal("10.00"),
        maximum_governance_classification=GovernanceClassification.RESTRICTED,
        allow_degraded_providers=False,
        retry_policy=RetryPolicy(
            enabled=retry_enabled,
            maximum_retries=max_retries if retry_enabled else 0,
            initial_backoff_ms=initial_backoff_ms if retry_enabled else 0,
        ),
        fallback_policy=FallbackPolicy(
            enabled=fallback_enabled,
            maximum_fallback_attempts=max_fallbacks if fallback_enabled else 0,
        ),
        created_at=datetime.now(UTC),
        pinned_model_id=pinned_model,
    )


def _make_request(request_id: str = "req-1") -> ChatRequest:
    return ChatRequest(
        request_id=RequestId(request_id),
        team_id=TeamId("t1"),
        feature_id=FeatureId("general-chat"),
        messages=(ChatMessage(role=ChatRole.USER, content="Hello"),),
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )


class ScriptedMockProvider(LLMProvider):
    """Mock provider with a scripted queue of execution outcomes."""

    def __init__(self, provider_id: str) -> None:
        self._provider_id = ProviderId(provider_id)
        self.outcomes: list[ProviderResponse | ProviderError] = []
        self.received_requests: list[ProviderRequest] = []

    @property
    def provider_id(self) -> ProviderId:
        return self._provider_id

    async def complete(self, request: ProviderRequest, model: ModelDefinition) -> ProviderResponse:
        self.received_requests.append(request)
        if not self.outcomes:
            return ProviderResponse(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                model_id=request.model_id,
                provider_id=self.provider_id,
                content="Default success",
                finish_reason=FinishReason.STOP,
                usage=TokenUsage(10, 10, 20, UsageSource.PROVIDER_REPORTED),
                latency_ms=50,
            )
        next_outcome = self.outcomes.pop(0)
        if isinstance(next_outcome, ProviderError):
            raise ProviderExecutionError(next_outcome)
        return next_outcome


# 1 & 2. Error Classification Unit Tests
def test_01_02_error_code_classification() -> None:
    retryable_codes = {
        ErrorCode.PROVIDER_TIMEOUT,
        ErrorCode.PROVIDER_RATE_LIMITED,
        ErrorCode.PROVIDER_CONNECTION_ERROR,
        ErrorCode.PROVIDER_UNAVAILABLE,
    }
    non_retryable_codes = {
        ErrorCode.PROVIDER_AUTHENTICATION_FAILED,
        ErrorCode.PROVIDER_INVALID_REQUEST,
        ErrorCode.PROVIDER_UNSUPPORTED_MODEL,
        ErrorCode.PROVIDER_MALFORMED_RESPONSE,
    }

    for code in retryable_codes:
        err = ProviderError(
            request_id=RequestId("r"),
            attempt_id=AttemptId("a"),
            provider_id=ProviderId("p"),
            model_id=ModelId("m"),
            code=code,
            message="err",
            retryable=True,
        )
        assert err.retryable is True

    for code in non_retryable_codes:
        err = ProviderError(
            request_id=RequestId("r"),
            attempt_id=AttemptId("a"),
            provider_id=ProviderId("p"),
            model_id=ModelId("m"),
            code=code,
            message="err",
            retryable=False,
        )
        assert err.retryable is False


# 3. Exponential Backoff Calculation
def test_03_exponential_backoff_calculation() -> None:
    assert calculate_exponential_backoff_ms(100, 1) == 100
    assert calculate_exponential_backoff_ms(100, 2) == 200
    assert calculate_exponential_backoff_ms(100, 3) == 400
    assert calculate_exponential_backoff_ms(50, 4) == 400

    with pytest.raises(ValueError):
        calculate_exponential_backoff_ms(100, 0)


# 4. Disabled Retry Policy
@pytest.mark.anyio
async def test_04_disabled_retry_policy() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy(retry_enabled=False, max_retries=0)
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout",
            retryable=True,
        )
    ]

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
    )

    assert res.success is False
    assert len(res.attempts) == 1
    assert res.retry_count == 0


# 5. Successful First Attempt
@pytest.mark.anyio
async def test_05_successful_first_attempt() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy()
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
    )

    assert res.success is True
    assert res.retry_count == 0
    assert res.fallback_used is False
    assert len(res.attempts) == 1
    assert res.attempts[0].attempt_kind == ExecutionAttemptKind.PRIMARY
    assert res.attempts[0].outcome == ExecutionAttemptOutcome.SUCCEEDED


# 6 & 17. Retry Succeeds on Second Attempt (not marked as fallback)
@pytest.mark.anyio
async def test_06_17_retry_succeeds_second_attempt() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy(max_retries=1)
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout",
            retryable=True,
        ),
        ProviderResponse(
            request_id=req.request_id,
            attempt_id=AttemptId("a2"),
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            content="Retry success",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(10, 10, 20, UsageSource.PROVIDER_REPORTED),
            latency_ms=40,
        ),
    ]

    sleep_mock = AsyncMock()
    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
        sleep_fn=sleep_mock,
    )

    assert res.success is True
    assert res.retry_count == 1
    assert res.fallback_used is False
    assert len(res.attempts) == 2
    assert res.attempts[0].outcome == ExecutionAttemptOutcome.FAILED
    assert res.attempts[1].outcome == ExecutionAttemptOutcome.SUCCEEDED
    assert res.attempts[1].attempt_kind == ExecutionAttemptKind.RETRY
    sleep_mock.assert_called_once_with(0.1)


# 7. Retry Limit Respected
@pytest.mark.anyio
async def test_07_retry_limit_respected() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy(max_retries=1, fallback_enabled=False)
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout 1",
            retryable=True,
        ),
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a2"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout 2",
            retryable=True,
        ),
    ]

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
        sleep_fn=AsyncMock(),
    )

    assert res.success is False
    assert len(res.attempts) == 2
    assert res.retry_count == 1


# 8 & 9. Non-Retryable Error Receives No Retry and No Fallback
@pytest.mark.anyio
async def test_08_09_non_retryable_error_no_retry_no_fallback() -> None:
    model1 = _make_model("m1", "p1")
    model2 = _make_model("m2", "p2", cost="0.002000")
    policy = _make_policy(
        allowed_models=(ModelId("m1"), ModelId("m2")), max_retries=2, max_fallbacks=1
    )
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov2 = ScriptedMockProvider("p2")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_AUTHENTICATION_FAILED,
            message="Auth failed",
            retryable=False,
        )
    ]

    def resolver(pid: ProviderId) -> LLMProvider:
        return prov1 if pid == "p1" else prov2

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1, model2],
        provider_resolver=resolver,
        sleep_fn=AsyncMock(),
    )

    assert res.success is False
    assert len(res.attempts) == 1
    assert res.attempts[0].error_code == ErrorCode.PROVIDER_AUTHENTICATION_FAILED
    assert len(prov2.received_requests) == 0  # Fallback provider never invoked!


# 10, 11, 12, 16. Retryable Error Triggers Fallback after Exhaustion
@pytest.mark.anyio
async def test_10_11_12_16_fallback_after_retry_exhaustion() -> None:
    model1 = _make_model("m1", "p1", cost="0.001000")
    model2 = _make_model("m2", "p2", cost="0.002000")
    policy = _make_policy(
        allowed_models=(ModelId("m1"), ModelId("m2")), max_retries=1, max_fallbacks=1
    )
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov2 = ScriptedMockProvider("p2")

    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Unavailable 1",
            retryable=True,
        ),
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a2"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Unavailable 2",
            retryable=True,
        ),
    ]

    prov2.outcomes = [
        ProviderResponse(
            request_id=req.request_id,
            attempt_id=AttemptId("a3"),
            model_id=ModelId("m2"),
            provider_id=ProviderId("p2"),
            content="Fallback output",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(10, 10, 20, UsageSource.PROVIDER_REPORTED),
            latency_ms=60,
        )
    ]

    def resolver(pid: ProviderId) -> LLMProvider:
        return prov1 if pid == "p1" else prov2

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1, model2],
        provider_resolver=resolver,
        sleep_fn=AsyncMock(),
    )

    assert res.success is True
    assert res.fallback_used is True
    assert res.selected_model_id == "m2"
    assert res.selected_provider_id == "p2"
    assert res.initial_model_id == "m1"
    assert res.decision is not None
    assert res.decision.routing_reason == RoutingReason.FALLBACK_AFTER_TRANSIENT_FAILURE
    assert len(res.attempts) == 3
    assert res.attempts[2].attempt_kind == ExecutionAttemptKind.FALLBACK


# 13. Ineligible Fallback Candidate Never Executes
@pytest.mark.anyio
async def test_13_ineligible_fallback_candidate_never_executes() -> None:
    from routeforge.contracts import QualityProfile

    model1 = _make_model("m1", "p1", cost="0.001000")
    # model2 has quality 0.2, below policy minimum 0.5
    model2 = ModelDefinition(
        model_id=ModelId("m2"),
        provider_id=ProviderId("p2"),
        display_name="m2",
        capabilities=model1.capabilities,
        governance_allowed=model1.governance_allowed,
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.002000"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.002000"),
        estimated_latency_ms=100,
        quality_profiles=(
            QualityProfile(
                task_type="general",
                predicted_quality=0.2,  # Too low
                source="test",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )

    policy = _make_policy(
        allowed_models=(ModelId("m1"), ModelId("m2")), max_retries=0, max_fallbacks=1
    )
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov2 = ScriptedMockProvider("p2")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout",
            retryable=True,
        )
    ]

    def resolver(pid: ProviderId) -> LLMProvider:
        return prov1 if pid == "p1" else prov2

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1, model2],
        provider_resolver=resolver,
        sleep_fn=AsyncMock(),
    )

    assert res.success is False
    assert len(prov2.received_requests) == 0  # Ineligible candidate was never executed!


# 14. Pinned Policy Prevents Fallback
@pytest.mark.anyio
async def test_14_pinned_policy_prevents_fallback() -> None:
    model1 = _make_model("m1", "p1", cost="0.001000")
    model2 = _make_model("m2", "p2", cost="0.002000")
    policy = _make_policy(
        allowed_models=(ModelId("m1"), ModelId("m2")),
        max_retries=0,
        max_fallbacks=1,
        pinned_model=ModelId("m1"),
    )
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov2 = ScriptedMockProvider("p2")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="Timeout",
            retryable=True,
        )
    ]

    def resolver(pid: ProviderId) -> LLMProvider:
        return prov1 if pid == "p1" else prov2

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1, model2],
        provider_resolver=resolver,
        sleep_fn=AsyncMock(),
    )

    assert res.success is False
    assert len(prov2.received_requests) == 0  # Pinned model failed -> no fallback!


# 15. No Eligible Fallback Returns Final Provider Failure
@pytest.mark.anyio
async def test_15_no_eligible_fallback_returns_final_provider_failure() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy(allowed_models=(ModelId("m1"),), max_retries=0, max_fallbacks=1)
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            message="Unavailable",
            retryable=True,
        )
    ]

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
        sleep_fn=AsyncMock(),
    )

    assert res.success is False
    assert res.error_code == ErrorCode.PROVIDER_UNAVAILABLE


# 18, 19, 20. Attempt IDs Unique, Idempotency Key Preserved, Deterministic Ordering
@pytest.mark.anyio
async def test_18_19_20_attempt_ids_idempotency_and_audit_ordering() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy(max_retries=2, fallback_enabled=False)
    req = _make_request(request_id="req-unique-123")

    prov1 = ScriptedMockProvider("p1")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("dummy1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="t1",
            retryable=True,
        ),
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("dummy2"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="t2",
            retryable=True,
        ),
        ProviderResponse(
            request_id=req.request_id,
            attempt_id=AttemptId("dummy3"),
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            content="Success 3",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(10, 10, 20, UsageSource.PROVIDER_REPORTED),
            latency_ms=30,
        ),
    ]

    res = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
        sleep_fn=AsyncMock(),
    )

    assert res.success is True
    assert len(prov1.received_requests) == 3

    # Idempotency key preserved across all attempts
    keys = {r.idempotency_key for r in prov1.received_requests}
    assert len(keys) == 1
    assert "req-unique-123-idempotency" in keys

    # Attempt IDs are unique and sequential
    attempt_ids = [str(r.attempt_id) for r in prov1.received_requests]
    assert attempt_ids == [
        "req-unique-123-attempt-1",
        "req-unique-123-attempt-2",
        "req-unique-123-attempt-3",
    ]

    # Audit records deterministic ordering
    audit_numbers = [a.attempt_number for a in res.attempts]
    assert audit_numbers == [1, 2, 3]


# 21. Injected Sleep Avoids Real Test Delays
@pytest.mark.anyio
async def test_21_injected_sleep_avoids_delays() -> None:
    model1 = _make_model("m1", "p1")
    policy = _make_policy(max_retries=1, initial_backoff_ms=5000)  # 5 sec delay!
    req = _make_request()

    prov1 = ScriptedMockProvider("p1")
    prov1.outcomes = [
        ProviderError(
            request_id=req.request_id,
            attempt_id=AttemptId("a1"),
            provider_id=ProviderId("p1"),
            model_id=ModelId("m1"),
            code=ErrorCode.PROVIDER_TIMEOUT,
            message="t",
            retryable=True,
        ),
    ]

    sleep_mock = AsyncMock()
    start_t = datetime.now(UTC)
    _ = await execute_inference(
        request=req,
        policy=policy,
        candidate_models=[model1],
        provider_resolver=lambda _: prov1,
        sleep_fn=sleep_mock,
    )
    elapsed_sec = (datetime.now(UTC) - start_t).total_seconds()

    # Fast test execution without waiting 5 seconds wall clock time!
    assert elapsed_sec < 1.0
    sleep_mock.assert_called_once_with(5.0)
