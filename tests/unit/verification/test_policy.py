"""Unit tests for VerificationPolicy domain contract validation."""

from decimal import Decimal

import pytest

from routeforge.contracts import ModelId
from routeforge.contracts.verification import VerificationPolicy, VerificationStrategy


def test_valid_disabled_verification_policy() -> None:
    policy = VerificationPolicy(enabled=False, sample_rate_basis_points=0)
    assert policy.enabled is False
    assert policy.sample_rate_basis_points == 0


def test_enabled_verification_policy_requires_reference_model() -> None:
    with pytest.raises(ValueError, match="reference_model_id"):
        VerificationPolicy(
            enabled=True,
            sample_rate_basis_points=1000,
            reference_model_id=None,
            strategy=VerificationStrategy.NORMALIZED_EXACT,
            minimum_score=Decimal("1.0"),
        )


def test_enabled_verification_policy_requires_strategy() -> None:
    with pytest.raises(ValueError, match="strategy"):
        VerificationPolicy(
            enabled=True,
            sample_rate_basis_points=1000,
            reference_model_id=ModelId("mock-premium"),
            strategy=None,
            minimum_score=Decimal("1.0"),
        )


def test_enabled_verification_policy_requires_minimum_score() -> None:
    with pytest.raises(ValueError, match="minimum_score"):
        VerificationPolicy(
            enabled=True,
            sample_rate_basis_points=1000,
            reference_model_id=ModelId("mock-premium"),
            strategy=VerificationStrategy.NORMALIZED_EXACT,
            minimum_score=None,
        )


def test_invalid_sample_rate_basis_points() -> None:
    with pytest.raises(ValueError, match="sample_rate_basis_points"):
        VerificationPolicy(enabled=False, sample_rate_basis_points=-1)

    with pytest.raises(ValueError, match="sample_rate_basis_points"):
        VerificationPolicy(enabled=False, sample_rate_basis_points=10001)


def test_valid_enabled_verification_policy() -> None:
    policy = VerificationPolicy(
        enabled=True,
        sample_rate_basis_points=5000,
        reference_model_id=ModelId("mock-premium"),
        strategy=VerificationStrategy.JSON_FIELD_AGREEMENT,
        minimum_score=Decimal("0.90000"),
    )
    assert policy.enabled is True
    assert policy.sample_rate_basis_points == 5000
    assert policy.reference_model_id == ModelId("mock-premium")
    assert policy.strategy == VerificationStrategy.JSON_FIELD_AGREEMENT
    assert policy.minimum_score == Decimal("0.90000")
