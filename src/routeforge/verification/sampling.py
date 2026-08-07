"""Deterministic quality verification sampling engine."""

import hashlib

from routeforge.contracts.common import PolicyId, PolicyVersion, RequestId


def should_sample_verification(
    *,
    request_id: RequestId,
    policy_id: PolicyId,
    policy_version: PolicyVersion,
    sample_rate_basis_points: int,
) -> bool:
    """Determine whether an inference request should be sampled for quality verification.

    Uses SHA-256 over canonical UTF-8 inputs to compute a deterministic bucket between
    0 and 9,999. Requests with bucket < sample_rate_basis_points are sampled.

    Args:
        request_id: Unique inference request ID.
        policy_id: Feature policy ID.
        policy_version: Feature policy version.
        sample_rate_basis_points: Sampling rate in basis points (0 to 10,000).

    Returns:
        True if sampled for verification, False otherwise.
    """
    if sample_rate_basis_points <= 0:
        return False
    if sample_rate_basis_points >= 10000:
        return True

    raw_input = f"{request_id}:{policy_id}:{policy_version}".encode()
    digest = hashlib.sha256(raw_input).digest()
    bucket = int.from_bytes(digest[:4], "big") % 10000
    return bucket < sample_rate_basis_points
