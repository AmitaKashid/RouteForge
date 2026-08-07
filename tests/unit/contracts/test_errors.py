"""Unit tests for domain error codes and RouteForgeError dataclass."""

from types import MappingProxyType

import pytest

from routeforge.contracts.common import RequestId
from routeforge.contracts.errors import (
    CandidateRejectionReason,
    ErrorCode,
    RouteForgeError,
    RoutingReason,
)


def test_rejection_and_routing_enums() -> None:
    assert CandidateRejectionReason.QUALITY_BELOW_THRESHOLD == "QUALITY_BELOW_THRESHOLD"
    assert RoutingReason.CHEAPEST_ELIGIBLE_MODEL == "CHEAPEST_ELIGIBLE_MODEL"
    assert ErrorCode.INVALID_REQUEST == "INVALID_REQUEST"


def test_routeforge_error_valid() -> None:
    err = RouteForgeError(
        code=ErrorCode.INVALID_REQUEST,
        message="Request payload was invalid.",
        retryable=False,
        request_id=RequestId("req_123"),
        details={"field": "messages"},
    )
    assert err.code == ErrorCode.INVALID_REQUEST
    assert err.message == "Request payload was invalid."
    assert err.retryable is False
    assert err.request_id == RequestId("req_123")
    assert isinstance(err.details, MappingProxyType)
    assert err.details["field"] == "messages"


def test_routeforge_error_blank_message_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be empty or whitespace-only"):
        RouteForgeError(
            code=ErrorCode.INTERNAL_ERROR,
            message="   ",
            retryable=True,
        )
