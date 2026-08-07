"""Model registry domain data contracts."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from routeforge.contracts.common import (
    Capability,
    GovernanceClassification,
    ModelId,
    ProviderId,
)


class ProviderOperatingState(StrEnum):
    """Real-time provider operational health state."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class QualityProfile:
    """Quality estimate profile for a model on a specific task type."""

    task_type: str
    predicted_quality: float
    source: str
    version: str

    def __post_init__(self) -> None:
        if not self.task_type or not self.task_type.strip():
            raise ValueError("task_type cannot be empty or whitespace-only.")
        if not (0.0 <= self.predicted_quality <= 1.0):
            raise ValueError("predicted_quality must be between 0.0 and 1.0.")
        if not self.source or not self.source.strip():
            raise ValueError("source cannot be empty or whitespace-only.")
        if not self.version or not self.version.strip():
            raise ValueError("version cannot be empty or whitespace-only.")


@dataclass(frozen=True)
class ModelDefinition:
    """Immutably defined model capability and cost definition."""

    model_id: ModelId
    provider_id: ProviderId
    display_name: str
    capabilities: tuple[Capability, ...]
    governance_allowed: tuple[GovernanceClassification, ...]
    context_window_tokens: int
    estimated_input_cost_per_million_tokens_usd: Decimal
    estimated_output_cost_per_million_tokens_usd: Decimal
    estimated_latency_ms: int
    quality_profiles: tuple[QualityProfile, ...]
    enabled: bool
    configuration_version: str

    def __post_init__(self) -> None:
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("model_id cannot be empty.")
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("provider_id cannot be empty.")
        if not self.display_name or not self.display_name.strip():
            raise ValueError("display_name cannot be empty.")
        if not self.configuration_version or not self.configuration_version.strip():
            raise ValueError("configuration_version cannot be empty.")

        if self.context_window_tokens <= 0:
            raise ValueError("context_window_tokens must be positive.")
        if self.estimated_latency_ms <= 0:
            raise ValueError("estimated_latency_ms must be positive.")

        if self.estimated_input_cost_per_million_tokens_usd < Decimal("0"):
            raise ValueError("estimated_input_cost_per_million_tokens_usd must not be negative.")
        if self.estimated_output_cost_per_million_tokens_usd < Decimal("0"):
            raise ValueError("estimated_output_cost_per_million_tokens_usd must not be negative.")

        if not isinstance(self.capabilities, tuple):
            object.__setattr__(self, "capabilities", tuple(self.capabilities))
        if not isinstance(self.governance_allowed, tuple):
            object.__setattr__(self, "governance_allowed", tuple(self.governance_allowed))
        if not isinstance(self.quality_profiles, tuple):
            object.__setattr__(self, "quality_profiles", tuple(self.quality_profiles))

        if not self.quality_profiles:
            raise ValueError("ModelDefinition must contain at least one QualityProfile.")
