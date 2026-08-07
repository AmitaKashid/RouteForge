"""Deterministic mock provider implementation for test and fixture execution."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from routeforge.contracts import (
    AttemptId,
    ErrorCode,
    FinishReason,
    ModelDefinition,
    ModelId,
    ProviderError,
    ProviderId,
    ProviderRequest,
    ProviderResponse,
    RequestId,
    TokenUsage,
    UsageSource,
)
from routeforge.providers.errors import ProviderExecutionError
from routeforge.providers.interfaces import LLMProvider


class MockOutcome(StrEnum):
    """Deterministic mock scenario outcome types."""

    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    UNAVAILABLE = "UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


@dataclass(frozen=True, slots=True)
class MockScenario:
    """Configured outcome scenario for a mock completion attempt."""

    outcome: MockOutcome = MockOutcome.SUCCESS
    content: str | None = None
    latency_ms: int = 50
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_request_id: str | None = None
    provider_status_code: int | None = None

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative.")

        if self.outcome == MockOutcome.SUCCESS and self.content is not None:
            if not isinstance(self.content, str) or not self.content.strip():
                raise ValueError("Successful scenario content must be a non-empty string.")

        if (self.input_tokens is None) != (self.output_tokens is None):
            raise ValueError(
                "input_tokens and output_tokens must either both be supplied or both omitted."
            )

        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("input_tokens cannot be negative.")

        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("output_tokens cannot be negative.")

        if self.provider_status_code is not None and self.provider_status_code <= 0:
            raise ValueError("provider_status_code must be positive.")


_FAILURE_MAP: dict[MockOutcome, tuple[ErrorCode, bool]] = {
    MockOutcome.TIMEOUT: (ErrorCode.PROVIDER_TIMEOUT, True),
    MockOutcome.RATE_LIMITED: (ErrorCode.PROVIDER_RATE_LIMITED, True),
    MockOutcome.CONNECTION_ERROR: (ErrorCode.PROVIDER_CONNECTION_ERROR, True),
    MockOutcome.UNAVAILABLE: (ErrorCode.PROVIDER_UNAVAILABLE, True),
    MockOutcome.AUTHENTICATION_FAILED: (ErrorCode.PROVIDER_AUTHENTICATION_FAILED, False),
    MockOutcome.INVALID_REQUEST: (ErrorCode.PROVIDER_INVALID_REQUEST, False),
    MockOutcome.MALFORMED_RESPONSE: (ErrorCode.PROVIDER_MALFORMED_RESPONSE, False),
}


def _estimate_tokens(text: str) -> int:
    """Estimate token count from non-whitespace lexical units."""
    if not text:
        return 0
    words = re.findall(r"\S+", text)
    return len(words)


def _generate_deterministic_content(model_id: ModelId, request: ProviderRequest) -> str:
    """Generate reproducible fixture content using SHA-256 digest of canonical request data."""
    parts = [str(model_id), str(request.output_format.value)]
    for msg in request.messages:
        parts.append(f"{msg.role.value}:{msg.content}")

    raw_bytes = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()[:12]
    return f"mock-response:{model_id}:{digest}"


class DeterministicMockProvider(LLMProvider):
    """Deterministic mock provider for controlled success and error scenarios."""

    def __init__(
        self,
        *,
        scenarios: Mapping[tuple[RequestId, AttemptId], MockScenario] | None = None,
        default_scenario: MockScenario | None = None,
    ) -> None:
        self._scenarios: dict[tuple[RequestId, AttemptId], MockScenario] = (
            dict(scenarios) if scenarios is not None else {}
        )
        self._default_scenario: MockScenario = (
            default_scenario if default_scenario is not None else MockScenario()
        )

    @property
    def provider_id(self) -> ProviderId:
        """Return the unique provider identifier for mock provider."""
        return ProviderId("mock")

    async def complete(
        self,
        request: ProviderRequest,
        model: ModelDefinition,
    ) -> ProviderResponse:
        """Execute mock completion attempt deterministically against configured scenario."""
        # 1. Model & Request Consistency Validation
        if model.provider_id != ProviderId("mock"):
            err = ProviderError(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                provider_id=self.provider_id,
                model_id=model.model_id,
                code=ErrorCode.PROVIDER_UNSUPPORTED_MODEL,
                message=(
                    f"Model '{model.model_id}' provider ID '{model.provider_id}' is not 'mock'."
                ),
                retryable=False,
            )
            raise ProviderExecutionError(err)

        if request.model_id != model.model_id:
            err = ProviderError(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                provider_id=self.provider_id,
                model_id=model.model_id,
                code=ErrorCode.PROVIDER_UNSUPPORTED_MODEL,
                message=(
                    f"Request model_id '{request.model_id}' does not match "
                    f"model definition model_id '{model.model_id}'."
                ),
                retryable=False,
            )
            raise ProviderExecutionError(err)

        if not model.enabled:
            err = ProviderError(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                provider_id=self.provider_id,
                model_id=model.model_id,
                code=ErrorCode.PROVIDER_UNAVAILABLE,
                message=f"Model '{model.model_id}' is disabled.",
                retryable=False,
            )
            raise ProviderExecutionError(err)

        # 2. Scenario Resolution
        key = (request.request_id, request.attempt_id)
        scenario = self._scenarios.get(key, self._default_scenario)

        # 3. Execution Outcome
        if scenario.outcome != MockOutcome.SUCCESS:
            error_code, retryable = _FAILURE_MAP[scenario.outcome]
            err = ProviderError(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                provider_id=self.provider_id,
                model_id=model.model_id,
                code=error_code,
                message=f"Mock provider scenario failed with outcome '{scenario.outcome}'.",
                retryable=retryable,
                provider_status_code=scenario.provider_status_code,
            )
            raise ProviderExecutionError(err)

        # 4. Success Response Generation
        content = (
            scenario.content
            if scenario.content is not None
            else _generate_deterministic_content(model.model_id, request)
        )

        if scenario.input_tokens is not None and scenario.output_tokens is not None:
            input_tokens = scenario.input_tokens
            output_tokens = scenario.output_tokens
        else:
            input_tokens = sum(_estimate_tokens(msg.content) for msg in request.messages)
            output_tokens = _estimate_tokens(content)

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            source=UsageSource.LOCALLY_ESTIMATED,
        )

        return ProviderResponse(
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            model_id=model.model_id,
            provider_id=self.provider_id,
            content=content,
            finish_reason=FinishReason.STOP,
            usage=usage,
            latency_ms=scenario.latency_ms,
            provider_request_id=scenario.provider_request_id,
        )
