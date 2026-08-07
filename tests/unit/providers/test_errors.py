"""Unit tests for ProviderExecutionError wrapper."""

from routeforge.contracts import AttemptId, ErrorCode, ModelId, ProviderError, ProviderId, RequestId
from routeforge.providers import ProviderExecutionError


def test_provider_execution_error_properties() -> None:
    err = ProviderError(
        request_id=RequestId("req_1"),
        attempt_id=AttemptId("att_1"),
        provider_id=ProviderId("mock"),
        model_id=ModelId("m1"),
        code=ErrorCode.PROVIDER_TIMEOUT,
        message="Request timed out after 5000ms.",
        retryable=True,
        provider_status_code=504,
    )
    exc = ProviderExecutionError(err)

    assert exc.error == err
    assert exc.error.code == ErrorCode.PROVIDER_TIMEOUT
    assert exc.error.retryable is True
    assert "PROVIDER_TIMEOUT" in str(exc)
    assert "Request timed out" in str(exc)
