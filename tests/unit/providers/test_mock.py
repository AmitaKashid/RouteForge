"""Unit tests for DeterministicMockProvider, MockScenario, and MockOutcome."""

import asyncio
from decimal import Decimal

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
from routeforge.providers import (
    DeterministicMockProvider,
    MockOutcome,
    MockScenario,
    ProviderExecutionError,
)


def create_test_model(
    model_id_str: str = "mock-model",
    provider_id_str: str = "mock",
    enabled: bool = True,
) -> ModelDefinition:
    qp = QualityProfile(task_type="general", predicted_quality=0.8, source="e", version="v1")
    return ModelDefinition(
        model_id=ModelId(model_id_str),
        provider_id=ProviderId(provider_id_str),
        display_name="Mock Model",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.10"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.20"),
        estimated_latency_ms=100,
        quality_profiles=(qp,),
        enabled=enabled,
        configuration_version="v1",
    )


def create_test_request(
    request_id_str: str = "req_1",
    attempt_id_str: str = "att_1",
    model_id_str: str = "mock-model",
    prompt: str = "Hello world",
    output_format: OutputFormat = OutputFormat.TEXT,
) -> ProviderRequest:
    return ProviderRequest(
        request_id=RequestId(request_id_str),
        attempt_id=AttemptId(attempt_id_str),
        model_id=ModelId(model_id_str),
        messages=(ChatMessage(role=ChatRole.USER, content=prompt),),
        output_format=output_format,
        timeout_ms=5000,
        idempotency_key="idem_1",
    )


def test_mock_scenario_validation() -> None:
    with pytest.raises(ValueError, match="latency_ms cannot be negative"):
        MockScenario(latency_ms=-1)

    with pytest.raises(ValueError, match="Successful scenario content must be a non-empty string"):
        MockScenario(outcome=MockOutcome.SUCCESS, content="   ")

    with pytest.raises(ValueError, match="must either both be supplied or both omitted"):
        MockScenario(input_tokens=10, output_tokens=None)

    with pytest.raises(ValueError, match="input_tokens cannot be negative"):
        MockScenario(input_tokens=-5, output_tokens=10)

    with pytest.raises(ValueError, match="provider_status_code must be positive"):
        MockScenario(provider_status_code=0)


def test_default_success_execution() -> None:
    provider = DeterministicMockProvider()
    model = create_test_model()
    request = create_test_request()

    response = asyncio.run(provider.complete(request, model))

    assert response.request_id == request.request_id
    assert response.attempt_id == request.attempt_id
    assert response.model_id == model.model_id
    assert response.provider_id == ProviderId("mock")
    assert response.finish_reason == FinishReason.STOP
    assert response.usage.source == UsageSource.LOCALLY_ESTIMATED
    assert response.latency_ms == 50

    # Repeated execution yields identical content and token count
    response2 = asyncio.run(provider.complete(request, model))
    assert response2.content == response.content
    assert response2.usage.total_tokens == response.usage.total_tokens


def test_explicit_success_scenario() -> None:
    scenario = MockScenario(
        outcome=MockOutcome.SUCCESS,
        content="Custom explicit content",
        latency_ms=120,
        input_tokens=15,
        output_tokens=3,
        provider_request_id="prov_req_100",
    )
    provider = DeterministicMockProvider(default_scenario=scenario)
    model = create_test_model()
    request = create_test_request()

    response = asyncio.run(provider.complete(request, model))

    assert response.content == "Custom explicit content"
    assert response.latency_ms == 120
    assert response.provider_request_id == "prov_req_100"
    assert response.usage.input_tokens == 15
    assert response.usage.output_tokens == 3
    assert response.usage.total_tokens == 18
    assert response.usage.source == UsageSource.LOCALLY_ESTIMATED


def test_scenario_resolution_by_key() -> None:
    scen_att1 = MockScenario(content="Attempt 1 response")
    scen_att2 = MockScenario(outcome=MockOutcome.TIMEOUT)

    key1 = (RequestId("req_1"), AttemptId("att_1"))
    key2 = (RequestId("req_1"), AttemptId("att_2"))

    scenarios = {key1: scen_att1, key2: scen_att2}
    provider = DeterministicMockProvider(scenarios=scenarios)
    model = create_test_model()

    req1 = create_test_request(request_id_str="req_1", attempt_id_str="att_1")
    req2 = create_test_request(request_id_str="req_1", attempt_id_str="att_2")
    req_other = create_test_request(request_id_str="req_1", attempt_id_str="att_3")

    # Attempt 1 succeeds with explicit content
    resp1 = asyncio.run(provider.complete(req1, model))
    assert resp1.content == "Attempt 1 response"

    # Attempt 2 fails with timeout
    with pytest.raises(ProviderExecutionError) as exc:
        asyncio.run(provider.complete(req2, model))
    assert exc.value.error.code == ErrorCode.PROVIDER_TIMEOUT

    # Unconfigured key uses default scenario (built-in success)
    resp_other = asyncio.run(provider.complete(req_other, model))
    assert resp_other.finish_reason == FinishReason.STOP


def test_deterministic_response_generation() -> None:
    provider = DeterministicMockProvider()
    model = create_test_model()

    req_a = create_test_request(prompt="What is 2+2?")
    req_b = create_test_request(prompt="What is 2+2?")
    req_c = create_test_request(prompt="What is 3+3?")

    resp_a = asyncio.run(provider.complete(req_a, model))
    resp_b = asyncio.run(provider.complete(req_b, model))
    resp_c = asyncio.run(provider.complete(req_c, model))

    assert resp_a.content == resp_b.content
    assert resp_a.content != resp_c.content


def test_token_estimation_algorithm() -> None:
    provider = DeterministicMockProvider()
    model = create_test_model()
    # Prompt has 3 words ("One two three"), output generated deterministically
    req = create_test_request(prompt="One two three")

    resp = asyncio.run(provider.complete(req, model))

    assert resp.usage.input_tokens == 3
    assert resp.usage.output_tokens > 0
    assert resp.usage.total_tokens == resp.usage.input_tokens + resp.usage.output_tokens


@pytest.mark.parametrize(
    ("outcome", "expected_code", "expected_retryable"),
    [
        (MockOutcome.TIMEOUT, ErrorCode.PROVIDER_TIMEOUT, True),
        (MockOutcome.RATE_LIMITED, ErrorCode.PROVIDER_RATE_LIMITED, True),
        (MockOutcome.CONNECTION_ERROR, ErrorCode.PROVIDER_CONNECTION_ERROR, True),
        (MockOutcome.UNAVAILABLE, ErrorCode.PROVIDER_UNAVAILABLE, True),
        (MockOutcome.AUTHENTICATION_FAILED, ErrorCode.PROVIDER_AUTHENTICATION_FAILED, False),
        (MockOutcome.INVALID_REQUEST, ErrorCode.PROVIDER_INVALID_REQUEST, False),
        (MockOutcome.MALFORMED_RESPONSE, ErrorCode.PROVIDER_MALFORMED_RESPONSE, False),
    ],
)
def test_all_failure_outcomes(
    outcome: MockOutcome,
    expected_code: ErrorCode,
    expected_retryable: bool,
) -> None:
    scenario = MockScenario(outcome=outcome, provider_status_code=400)
    provider = DeterministicMockProvider(default_scenario=scenario)
    model = create_test_model()
    request = create_test_request()

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(provider.complete(request, model))

    err = exc_info.value.error
    assert err.code == expected_code
    assert err.retryable is expected_retryable
    assert err.request_id == request.request_id
    assert err.attempt_id == request.attempt_id
    assert err.provider_id == ProviderId("mock")
    assert err.model_id == model.model_id
    assert err.provider_status_code == 400


def test_model_and_request_consistency_validations() -> None:
    provider = DeterministicMockProvider()
    req = create_test_request(model_id_str="mock-model")

    # 1. Non-mock provider ID rejected
    bad_provider_model = create_test_model(provider_id_str="openai")
    with pytest.raises(ProviderExecutionError) as exc1:
        asyncio.run(provider.complete(req, bad_provider_model))
    assert exc1.value.error.code == ErrorCode.PROVIDER_UNSUPPORTED_MODEL
    assert exc1.value.error.retryable is False

    # 2. Mismatched model ID rejected
    mismatched_model = create_test_model(model_id_str="other-model")
    with pytest.raises(ProviderExecutionError) as exc2:
        asyncio.run(provider.complete(req, mismatched_model))
    assert exc2.value.error.code == ErrorCode.PROVIDER_UNSUPPORTED_MODEL
    assert exc2.value.error.retryable is False

    # 3. Disabled model rejected
    disabled_model = create_test_model(model_id_str="mock-model", enabled=False)
    with pytest.raises(ProviderExecutionError) as exc3:
        asyncio.run(provider.complete(req, disabled_model))
    assert exc3.value.error.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert exc3.value.error.retryable is False


def test_input_mutation_isolation() -> None:
    scenario = MockScenario(content="Response")
    key = (RequestId("req_1"), AttemptId("att_1"))
    scenarios_input = {key: scenario}

    provider = DeterministicMockProvider(scenarios=scenarios_input)
    scenarios_input.clear()

    req = create_test_request(request_id_str="req_1", attempt_id_str="att_1")
    model = create_test_model()

    resp = asyncio.run(provider.complete(req, model))
    assert resp.content == "Response"
