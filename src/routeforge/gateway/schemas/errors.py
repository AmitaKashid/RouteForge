"""Pydantic schemas for OpenAI-style HTTP gateway error responses."""

from pydantic import Field, field_validator

from routeforge.gateway.schemas.base import GatewayBaseModel


class ApiErrorDetail(GatewayBaseModel):
    """Detailed error object matching OpenAI wire protocol."""

    message: str = Field(description="Human-readable error explanation.")
    type: str = Field(description="Error type classification (e.g. invalid_request_error).")
    param: str | None = Field(default=None, description="Request parameter causing error, if any.")
    code: str = Field(description="Machine-readable error code string.")

    @field_validator("message", "code")
    @classmethod
    def validate_nonblank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Error message and code fields must be nonblank strings.")
        return v


class ApiErrorMetadata(GatewayBaseModel):
    """RouteForge-specific error extension metadata."""

    request_id: str | None = Field(
        default=None, description="Correlation ID for the failed request."
    )


class ApiErrorResponse(GatewayBaseModel):
    """Top-level HTTP error response wrapper."""

    error: ApiErrorDetail
    routeforge: ApiErrorMetadata = Field(default_factory=ApiErrorMetadata)
