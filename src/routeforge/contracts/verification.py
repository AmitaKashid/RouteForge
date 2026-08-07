"""Verification policy domain data contracts."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from routeforge.contracts.common import ModelId


class VerificationStrategy(StrEnum):
    """Supported deterministic comparison strategies for quality verification."""

    NORMALIZED_EXACT = "NORMALIZED_EXACT"
    JSON_FIELD_AGREEMENT = "JSON_FIELD_AGREEMENT"


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    """Configuration governing asynchronous quality verification for a feature.

    Attributes:
        enabled: Whether quality verification is active.
        sample_rate_basis_points: Sampling rate in basis points (0 to 10000, 10000 = 100%).
        reference_model_id: Model ID used as the fixed reference.
        strategy: Comparison strategy used to evaluate selected vs reference response.
        minimum_score: Passing score threshold (between Decimal("0") and Decimal("1")).
    """

    enabled: bool = False
    sample_rate_basis_points: int = 0
    reference_model_id: ModelId | None = None
    strategy: VerificationStrategy | None = None
    minimum_score: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sample_rate_basis_points, int) or isinstance(
            self.sample_rate_basis_points, bool
        ):
            raise ValueError("sample_rate_basis_points must be an integer.")
        if not (0 <= self.sample_rate_basis_points <= 10000):
            raise ValueError("sample_rate_basis_points must be between 0 and 10000.")

        if self.enabled:
            if not self.reference_model_id or not str(self.reference_model_id).strip():
                raise ValueError("An enabled verification policy requires reference_model_id.")
            if self.strategy is None:
                raise ValueError("An enabled verification policy requires strategy.")
            if self.minimum_score is None:
                raise ValueError("An enabled verification policy requires minimum_score.")
            if not isinstance(self.minimum_score, Decimal):
                raise ValueError("minimum_score must be a Decimal.")
            if not (Decimal("0") <= self.minimum_score <= Decimal("1")):
                raise ValueError("minimum_score must be between 0 and 1.")
