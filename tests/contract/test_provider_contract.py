"""Reusable provider contract test suite for verifying LLMProvider implementations."""

import asyncio
from decimal import Decimal

from routeforge.contracts import (
    AttemptId,
    Capability,
    ChatMessage,
    ChatRole,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderId,
    ProviderRequest,
    ProviderResponse,
    QualityProfile,
    RequestId,
)
from routeforge.providers import (
    DeterministicMockProvider,
    LLMProvider,
    MockOutcome,
    MockScenario,
    ProviderExecutionError,
)


def assert_provider_contract_success(
    provider: LLMProvider,
    request: ProviderRequest,
    model: ModelDefinition,
) -> ProviderResponse:
    """Assertion helper verifying successful provider contract execution invariants."""
    assert provider.provider_id != ""

    response = asyncio.run(provider.complete(request, model))

    assert isinstance(response, ProviderResponse)
    assert response.request_id == request.request_id
    assert response.attempt_id == request.attempt_id
    assert response.model_id == model.model_id
    assert response.provider_id == provider.provider_id
    assert isinstance(response.content, str)
    assert response.latency_ms >= 0
    return response


def assert_provider_contract_failure(
    provider: LLMProvider,
    request: ProviderRequest,
    model: ModelDefinition,
) -> ProviderExecutionError:
    """Assertion helper verifying provider error boundary invariants."""
    try:
        asyncio.run(provider.complete(request, model))
        raise AssertionError("Expected ProviderExecutionError was not raised.")
    except ProviderExecutionError as exc:
        assert exc.error.request_id == request.request_id
        assert exc.error.attempt_id == request.attempt_id
        assert exc.error.provider_id == provider.provider_id
        assert exc.error.message != ""
        return exc


def test_mock_provider_satisfies_contract() -> None:
    qp = QualityProfile(task_type="general", predicted_quality=0.8, source="e", version="v1")
    model = ModelDefinition(
        model_id=ModelId("mock-model"),
        provider_id=ProviderId("mock"),
        display_name="Mock Model",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=4096,
        estimated_input_cost_per_million_tokens_usd=Decimal("0.10"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0.20"),
        estimated_latency_ms=100,
        quality_profiles=(qp,),
        enabled=True,
        configuration_version="v1",
    )
    request = ProviderRequest(
        request_id=RequestId("req_contract_1"),
        attempt_id=AttemptId("att_contract_1"),
        model_id=ModelId("mock-model"),
        messages=(ChatMessage(role=ChatRole.USER, content="Test contract prompt"),),
        output_format=OutputFormat.TEXT,
        timeout_ms=5000,
        idempotency_key="idem_contract",
    )

    # Success assertion
    provider_success = DeterministicMockProvider()
    resp = assert_provider_contract_success(provider_success, request, model)
    assert resp.content != ""

    # Failure assertion
    provider_failure = DeterministicMockProvider(
        default_scenario=MockScenario(outcome=MockOutcome.TIMEOUT)
    )
    exc = assert_provider_contract_failure(provider_failure, request, model)
    assert exc.error.code == "PROVIDER_TIMEOUT"
