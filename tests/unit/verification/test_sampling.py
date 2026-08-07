"""Unit tests for deterministic quality verification sampling."""

from routeforge.contracts import PolicyId, PolicyVersion, RequestId
from routeforge.verification.sampling import should_sample_verification


def test_zero_basis_points_never_samples() -> None:
    for i in range(100):
        req_id = RequestId(f"req_{i}")
        assert (
            should_sample_verification(
                request_id=req_id,
                policy_id=PolicyId("policy-1"),
                policy_version=PolicyVersion("v1"),
                sample_rate_basis_points=0,
            )
            is False
        )


def test_ten_thousand_basis_points_always_samples() -> None:
    for i in range(100):
        req_id = RequestId(f"req_{i}")
        assert (
            should_sample_verification(
                request_id=req_id,
                policy_id=PolicyId("policy-1"),
                policy_version=PolicyVersion("v1"),
                sample_rate_basis_points=10000,
            )
            is True
        )


def test_identical_inputs_yield_identical_decisions() -> None:
    req_id = RequestId("req_static_123")
    p_id = PolicyId("policy-classification")
    p_ver = PolicyVersion("v1")

    decision1 = should_sample_verification(
        request_id=req_id,
        policy_id=p_id,
        policy_version=p_ver,
        sample_rate_basis_points=5000,
    )
    decision2 = should_sample_verification(
        request_id=req_id,
        policy_id=p_id,
        policy_version=p_ver,
        sample_rate_basis_points=5000,
    )

    assert decision1 == decision2


def test_changed_policy_version_can_change_bucket() -> None:
    req_id = RequestId("req_same_1")
    p_id = PolicyId("policy-1")

    # Run over multiple versions to observe bucket variation
    results = [
        should_sample_verification(
            request_id=req_id,
            policy_id=p_id,
            policy_version=PolicyVersion(f"v{v}"),
            sample_rate_basis_points=5000,
        )
        for v in range(50)
    ]
    # Expect both True and False across different versions
    assert True in results
    assert False in results


def test_deterministic_without_randomness() -> None:
    # Multiple calls with fixed parameters MUST match without seed dependency
    res = [
        should_sample_verification(
            request_id=RequestId("test_req"),
            policy_id=PolicyId("p"),
            policy_version=PolicyVersion("v1"),
            sample_rate_basis_points=2500,
        )
        for _ in range(10)
    ]
    assert len(set(res)) == 1
