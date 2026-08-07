"""Unit tests for M5.2 circuit breaker state transitions, policies, and deterministic mappings."""

from typing import Any

import pytest

from routeforge.contracts import (
    CircuitBreakerPolicy,
    ProviderOperatingState,
)
from routeforge.resilience import CircuitState, RedisCircuitBreaker


class DummyRedisClient:
    """In-memory Redis stub for unit tests simulating Redis hash and lock commands."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, Any]] = {}
        self.locks: dict[str, tuple[str, float]] = {}
        self.scripts: list[Any] = []

    async def hgetall(self, key: str) -> dict[bytes, bytes]:
        data = self.hashes.get(key, {})
        return {k.encode("utf-8"): str(v).encode("utf-8") for k, v in data.items()}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.locks:
            return False
        self.locks[key] = (value, float(ex or 0))
        return True

    async def delete(self, key: str) -> None:
        self.locks.pop(key, None)

    def register_script(self, script_text: str) -> Any:
        async def script_runner(keys: list[str], args: list[Any]) -> list[Any]:
            probe_key = keys[1] if len(keys) > 1 else None
            hash_key = keys[0]

            h_data = self.hashes.setdefault(hash_key, {})
            current_state = h_data.get("state", "CLOSED")

            if "RECORD_FAILURE" in script_text or "failure_threshold" in script_text:
                threshold = int(args[0])
                duration = float(args[1])
                now_val = float(args[2])
                err_code = str(args[3])

                cnt = int(h_data.get("consecutive_failures", 0)) + 1
                h_data["consecutive_failures"] = cnt
                h_data["last_error_code"] = err_code

                if cnt >= threshold or current_state == "HALF_OPEN":
                    open_until = now_val + duration
                    h_data["state"] = "OPEN"
                    h_data["opened_at"] = now_val
                    h_data["open_until"] = open_until
                    if probe_key:
                        self.locks.pop(probe_key, None)
                    return ["OPEN", cnt, str(open_until)]
                else:
                    h_data["state"] = "CLOSED"
                    return ["CLOSED", cnt, "0"]

            elif "RECORD_SUCCESS" in script_text or "last_success_at" in script_text:
                now_val = float(args[0])
                h_data["state"] = "CLOSED"
                h_data["consecutive_failures"] = 0
                h_data["opened_at"] = 0
                h_data["open_until"] = 0
                h_data["last_success_at"] = now_val
                if probe_key:
                    self.locks.pop(probe_key, None)
                return ["CLOSED", 0, "0"]

            return ["CLOSED", 0, "0"]

        return script_runner


@pytest.mark.anyio
async def test_no_redis_record_maps_to_closed_and_healthy() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    snap = await cb.get_routing_state("openai", "gpt-4o", policy, now=1000.0)
    assert snap.circuit_state == CircuitState.CLOSED
    assert snap.provider_state == ProviderOperatingState.HEALTHY
    assert snap.consecutive_failures == 0


@pytest.mark.anyio
async def test_disabled_circuit_policy_always_produces_closed() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    disabled_policy = CircuitBreakerPolicy(
        enabled=False, failure_threshold=3, open_duration_seconds=30
    )

    # Put OPEN in Redis
    redis_stub.hashes["routeforge:circuit:openai:gpt-4o"] = {"state": "OPEN", "open_until": 2000.0}

    snap = await cb.get_routing_state("openai", "gpt-4o", disabled_policy, now=1000.0)
    assert snap.circuit_state == CircuitState.CLOSED
    assert snap.provider_state == ProviderOperatingState.HEALTHY


@pytest.mark.anyio
async def test_first_counted_terminal_failure_increments_counter() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    snap = await cb.record_terminal_failure(
        "openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0
    )
    assert snap.consecutive_failures == 1
    assert snap.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_success_resets_consecutive_failures() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0)
    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1001.0)

    snap_success = await cb.record_success("openai", "gpt-4o", now=1002.0)
    assert snap_success.consecutive_failures == 0
    assert snap_success.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_threshold_failure_transitions_to_open() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0)
    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1001.0)
    snap = await cb.record_terminal_failure(
        "openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1002.0
    )

    assert snap.circuit_state == CircuitState.OPEN
    assert snap.provider_state == ProviderOperatingState.UNAVAILABLE
    assert snap.open_until == 1032.0


@pytest.mark.anyio
async def test_open_maps_to_unavailable_and_expiry_transitions_to_half_open() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0)
    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1001.0)
    await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1002.0)

    # Before expiry (1002 + 30 = 1032)
    snap_before = await cb.get_routing_state("openai", "gpt-4o", policy, now=1020.0)
    assert snap_before.circuit_state == CircuitState.OPEN
    assert snap_before.provider_state == ProviderOperatingState.UNAVAILABLE

    # After expiry
    snap_after = await cb.get_routing_state("openai", "gpt-4o", policy, now=1035.0)
    assert snap_after.circuit_state == CircuitState.HALF_OPEN
    assert snap_after.provider_state == ProviderOperatingState.DEGRADED


@pytest.mark.anyio
async def test_half_open_probe_acquisition_and_recovery() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    # Transition to OPEN
    for t in range(3):
        await cb.record_terminal_failure(
            "openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0 + t
        )

    # Advance time beyond cooldown -> HALF_OPEN
    now = 1035.0
    snap_ho = await cb.get_routing_state("openai", "gpt-4o", policy, now=now)
    assert snap_ho.circuit_state == CircuitState.HALF_OPEN

    # Acquire probe
    acq1 = await cb.acquire_half_open_probe("openai", "gpt-4o", now=now, ttl_seconds=30)
    assert acq1 is True

    # Second probe acquisition attempt should fail (single probe lock)
    acq2 = await cb.acquire_half_open_probe("openai", "gpt-4o", now=now, ttl_seconds=30)
    assert acq2 is False

    # Successful probe closes circuit
    snap_recovered = await cb.record_success("openai", "gpt-4o", now=now + 1.0)
    assert snap_recovered.circuit_state == CircuitState.CLOSED
    assert snap_recovered.provider_state == ProviderOperatingState.HEALTHY


@pytest.mark.anyio
async def test_failed_retryable_probe_reopens_circuit() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    # OPEN circuit
    for t in range(3):
        await cb.record_terminal_failure(
            "openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0 + t
        )

    # Advance time -> HALF_OPEN
    now = 1035.0
    await cb.acquire_half_open_probe("openai", "gpt-4o", now=now, ttl_seconds=30)

    # Failed probe with retryable error reopens immediately
    snap_reopen = await cb.record_terminal_failure(
        "openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=now + 1.0
    )
    assert snap_reopen.circuit_state == CircuitState.OPEN
    assert snap_reopen.open_until == (now + 1.0 + 30.0)


@pytest.mark.anyio
async def test_provider_model_isolation() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    # Trigger threshold failures on openai:gpt-4o
    for t in range(3):
        await cb.record_terminal_failure(
            "openai", "gpt-4o", policy, "PROVIDER_TIMEOUT", now=1000.0 + t
        )

    # Verify gpt-4o is OPEN while gpt-3.5-turbo remains CLOSED
    snap_gpt4 = await cb.get_routing_state("openai", "gpt-4o", policy, now=1005.0)
    snap_gpt35 = await cb.get_routing_state("openai", "gpt-3.5-turbo", policy, now=1005.0)
    snap_anthropic = await cb.get_routing_state("anthropic", "claude-3-haiku", policy, now=1005.0)

    assert snap_gpt4.circuit_state == CircuitState.OPEN
    assert snap_gpt35.circuit_state == CircuitState.CLOSED
    assert snap_anthropic.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_null_redis_client_fallback_behavior() -> None:
    cb = RedisCircuitBreaker(redis_client=None)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    snap_get = await cb.get_routing_state("openai", "gpt-4o", policy)
    assert snap_get.circuit_state == CircuitState.CLOSED

    probe_acquired = await cb.acquire_half_open_probe("openai", "gpt-4o")
    assert probe_acquired is True

    await cb.release_half_open_probe("openai", "gpt-4o")

    await cb.release_half_open_probe("openai", "gpt-4o")

    snap_fail = await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT")
    assert snap_fail.circuit_state == CircuitState.CLOSED

    snap_succ = await cb.record_success("openai", "gpt-4o")
    assert snap_succ.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_get_routing_state_half_open_direct_hash() -> None:
    redis_stub = DummyRedisClient()
    redis_stub.hashes["routeforge:circuit:openai:gpt-4o"] = {
        "state": "HALF_OPEN",
        "consecutive_failures": "3",
        "open_until": "1000.0",
    }
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=True, failure_threshold=3, open_duration_seconds=30)

    snap = await cb.get_routing_state("openai", "gpt-4o", policy, now=1005.0)
    assert snap.circuit_state == CircuitState.HALF_OPEN
    assert snap.provider_state == ProviderOperatingState.DEGRADED


@pytest.mark.anyio
async def test_record_terminal_failure_disabled_policy() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=False, failure_threshold=3, open_duration_seconds=30)

    snap = await cb.record_terminal_failure("openai", "gpt-4o", policy, "PROVIDER_TIMEOUT")
    assert snap.circuit_state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_get_routing_state_disabled_policy() -> None:
    redis_stub = DummyRedisClient()
    cb = RedisCircuitBreaker(redis_client=redis_stub)
    policy = CircuitBreakerPolicy(enabled=False, failure_threshold=3, open_duration_seconds=30)

    snap = await cb.get_routing_state("openai", "gpt-4o", policy)
    assert snap.circuit_state == CircuitState.CLOSED
    assert snap.provider_state == ProviderOperatingState.HEALTHY
