"""Redis integration tests for circuit breaker atomicity, concurrency, and key isolation."""

import asyncio
import os

import pytest
from redis.asyncio import Redis

from routeforge.contracts import CircuitBreakerPolicy, ProviderOperatingState
from routeforge.resilience import CircuitState, RedisCircuitBreaker

REDIS_URL = os.getenv("ROUTEFORGE_TEST_REDIS_URL", "redis://localhost:6379/0")


async def is_redis_available() -> bool:
    try:
        client = Redis.from_url(REDIS_URL)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.mark.anyio
async def test_redis_circuit_breaker_concurrency_and_atomicity() -> None:
    if not await is_redis_available():
        pytest.skip(
            f"Redis unavailable at {REDIS_URL}. Skipping Redis circuit breaker integration tests."
        )

    redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.flushdb()

    cb = RedisCircuitBreaker(redis_client=redis_client)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=5, open_duration_seconds=30)

    # 1. Concurrent terminal failure increments
    tasks = [
        cb.record_terminal_failure("mock", "econ-1", policy, "PROVIDER_TIMEOUT", now=1000.0)
        for _ in range(5)
    ]
    await asyncio.gather(*tasks)

    # At least one task should return state OPEN
    final_snap = await cb.get_routing_state("mock", "econ-1", policy, now=1001.0)
    assert final_snap.consecutive_failures == 5
    assert final_snap.circuit_state == CircuitState.OPEN
    assert final_snap.provider_state == ProviderOperatingState.UNAVAILABLE

    # 2. Single probe acquisition under concurrency
    now_probe = 1035.0
    probe_tasks = [
        cb.acquire_half_open_probe("mock", "econ-1", now=now_probe, ttl_seconds=30)
        for _ in range(10)
    ]
    probe_results = await asyncio.gather(*probe_tasks)
    # Exactly one probe acquisition must succeed
    assert sum(1 for r in probe_results if r is True) == 1

    # 3. Successful probe clears state and lock
    succ_snap = await cb.record_success("mock", "econ-1", now=now_probe + 1.0)
    assert succ_snap.circuit_state == CircuitState.CLOSED
    assert succ_snap.consecutive_failures == 0

    # Clean up
    await redis_client.flushdb()
    await redis_client.aclose()
