"""Unit tests for API error Pydantic schemas."""

import pytest
from pydantic import ValidationError

from routeforge.gateway.schemas import (
    ApiErrorDetail,
    ApiErrorMetadata,
    ApiErrorResponse,
)


def test_api_error_response_valid() -> None:
    detail = ApiErrorDetail(
        message="Invalid request parameters.",
        type="invalid_request_error",
        param="messages",
        code="INVALID_REQUEST",
    )
    meta = ApiErrorMetadata(request_id="req_err_1")
    err_resp = ApiErrorResponse(error=detail, routeforge=meta)

    assert err_resp.error.message == "Invalid request parameters."
    assert err_resp.error.param == "messages"
    assert err_resp.routeforge.request_id == "req_err_1"


def test_api_error_detail_validation() -> None:
    # Blank message rejected
    with pytest.raises(ValidationError):
        ApiErrorDetail(message="   ", type="invalid_request_error", code="BAD")

    # Blank code rejected
    with pytest.raises(ValidationError):
        ApiErrorDetail(message="Valid msg", type="invalid_request_error", code="")

    # Unknown field rejected
    with pytest.raises(ValidationError):
        ApiErrorDetail.model_validate(
            {"message": "m", "type": "t", "code": "c", "extra_field": "val"}
        )
