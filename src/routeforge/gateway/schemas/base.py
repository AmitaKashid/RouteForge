"""Gateway-specific Pydantic base model configuration."""

from pydantic import BaseModel, ConfigDict


class GatewayBaseModel(BaseModel):
    """Base Pydantic model for external gateway wire schemas enforcing strict validation."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )
