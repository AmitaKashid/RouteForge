"""Ollama-compatible provider adapter implementation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import httpx

from routeforge.contracts import (
    ChatRole,
    ErrorCode,
    FinishReason,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderError,
    ProviderId,
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
    UsageSource,
)
from routeforge.providers.errors import ProviderExecutionError
from routeforge.providers.interfaces import LLMProvider

ROLE_MAP = {
    ChatRole.SYSTEM: "system",
    ChatRole.USER: "user",
    ChatRole.ASSISTANT: "assistant",
}

FINISH_REASON_MAP = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}


@dataclass(frozen=True, slots=True)
class OllamaProviderConfig:
    """Immutable configuration for Ollama provider adapter."""

    base_url: str = "http://localhost:11434"
    model_names: Mapping[ModelId, str] = field(default_factory=dict)
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.base_url or not self.base_url.strip():
            raise ValueError("base_url cannot be empty or whitespace-only.")
        if self.request_timeout_seconds <= 0.0:
            raise ValueError("request_timeout_seconds must be positive.")
        copied = dict(self.model_names)
        object.__setattr__(self, "model_names", MappingProxyType(copied))


class OllamaProvider(LLMProvider):
    """Provider adapter executing completion attempts against an Ollama server."""

    provider_id = ProviderId("ollama")

    def __init__(
        self,
        config: OllamaProviderConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or OllamaProviderConfig()
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(self._config.request_timeout_seconds),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client if created internally."""
        if not self._external_client:
            await self._client.aclose()

    async def __aenter__(self) -> "OllamaProvider":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def complete(
        self,
        request: ProviderRequest,
        model: ModelDefinition,
    ) -> ProviderResponse:
        """Execute one normalized completion attempt against an Ollama model."""
        if model.provider_id != self.provider_id:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_UNSUPPORTED_MODEL,
                    message=(
                        f"Model provider '{model.provider_id}' does not match provider 'ollama'."
                    ),
                    retryable=False,
                )
            )

        if request.model_id != model.model_id:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_INVALID_REQUEST,
                    message=(
                        f"Request model ID '{request.model_id}' does not match "
                        f"model definition ID '{model.model_id}'."
                    ),
                    retryable=False,
                )
            )

        if not model.enabled:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_UNAVAILABLE,
                    message=f"Model '{model.model_id}' is disabled.",
                    retryable=False,
                )
            )

        upstream_model_name = self._config.model_names.get(request.model_id)
        if not upstream_model_name:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_UNSUPPORTED_MODEL,
                    message=(
                        f"No Ollama model mapping configured for model ID '{request.model_id}'."
                    ),
                    retryable=False,
                )
            )

        messages_payload = [
            {
                "role": ROLE_MAP.get(msg.role, "user"),
                "content": msg.content,
            }
            for msg in request.messages
        ]

        payload: dict[str, object] = {
            "model": upstream_model_name,
            "messages": messages_payload,
            "stream": False,
        }

        if request.output_format == OutputFormat.JSON:
            payload["format"] = "json"

        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as err:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_TIMEOUT,
                    message=f"Ollama HTTP request timed out: {err}",
                    retryable=True,
                )
            ) from err
        except httpx.HTTPStatusError as err:
            status = err.response.status_code
            if status == 429:
                err_code = ErrorCode.PROVIDER_RATE_LIMITED
                retryable = True
            elif status == 404:
                err_code = ErrorCode.PROVIDER_UNSUPPORTED_MODEL
                retryable = False
            elif status == 400:
                err_code = ErrorCode.PROVIDER_INVALID_REQUEST
                retryable = False
            elif status in (500, 502, 503, 504):
                err_code = ErrorCode.PROVIDER_UNAVAILABLE
                retryable = True
            else:
                err_code = ErrorCode.PROVIDER_UNAVAILABLE
                retryable = status >= 500
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=err_code,
                    message=f"Ollama HTTP {status} error: {err}",
                    retryable=retryable,
                    provider_status_code=status,
                )
            ) from err
        except (httpx.ConnectError, httpx.NetworkError, httpx.RequestError) as err:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_CONNECTION_ERROR,
                    message=f"Ollama connection failure: {err}",
                    retryable=True,
                )
            ) from err
        except Exception as err:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message=f"Failed to parse Ollama JSON response: {err}",
                    retryable=False,
                )
            ) from err

        if not isinstance(data, dict):
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message="Ollama response is not a JSON object.",
                    retryable=False,
                )
            )

        if not data.get("done", False):
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message="Ollama response marked done=False.",
                    retryable=False,
                )
            )

        msg_obj = data.get("message")
        if not isinstance(msg_obj, dict):
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message="Ollama response missing message object.",
                    retryable=False,
                )
            )

        content = msg_obj.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message="Ollama response message content must be a non-empty string.",
                    retryable=False,
                )
            )

        prompt_eval_count = data.get("prompt_eval_count")
        eval_count = data.get("eval_count")
        if (
            not isinstance(prompt_eval_count, int)
            or prompt_eval_count < 0
            or not isinstance(eval_count, int)
            or eval_count < 0
        ):
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message="Ollama response token counts must be non-negative integers.",
                    retryable=False,
                )
            )

        total_duration_ns = data.get("total_duration")
        if not isinstance(total_duration_ns, int) or total_duration_ns < 0:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message="Ollama response total_duration must be a non-negative integer.",
                    retryable=False,
                )
            )

        latency_ms = int(total_duration_ns // 1_000_000)

        raw_done_reason = data.get("done_reason")
        if raw_done_reason is None or raw_done_reason == "stop":
            finish_reason = FinishReason.STOP
        elif raw_done_reason in FINISH_REASON_MAP:
            finish_reason = FINISH_REASON_MAP[raw_done_reason]
        else:
            raise ProviderExecutionError(
                ProviderError(
                    request_id=request.request_id,
                    attempt_id=request.attempt_id,
                    provider_id=self.provider_id,
                    model_id=request.model_id,
                    code=ErrorCode.PROVIDER_MALFORMED_RESPONSE,
                    message=f"Unknown Ollama done_reason '{raw_done_reason}'.",
                    retryable=False,
                )
            )

        return ProviderResponse(
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            provider_id=self.provider_id,
            model_id=request.model_id,
            content=content,
            finish_reason=finish_reason,
            usage=TokenUsage(
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
                total_tokens=prompt_eval_count + eval_count,
                source=UsageSource.PROVIDER_REPORTED,
            ),
            latency_ms=latency_ms,
        )
