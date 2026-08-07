"""Redis-backed passive provider circuit breaker implementation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from routeforge.contracts import (
    CircuitBreakerPolicy,
    ModelId,
    ProviderId,
    ProviderOperatingState,
)


class CircuitState(StrEnum):
    """Passive circuit breaker lifecycle states."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class ProviderHealthSnapshot:
    """Immutable application-layer snapshot of provider-model circuit health."""

    provider_id: ProviderId
    model_id: ModelId
    circuit_state: CircuitState
    provider_state: ProviderOperatingState
    consecutive_failures: int
    open_until: float | None = None
    last_error_code: str | None = None
    last_success_at: float | None = None


def get_circuit_redis_key(provider_id: ProviderId | str, model_id: ModelId | str) -> str:
    """Format Redis hash key for provider-model circuit breaker state."""
    p_str = str(provider_id).lower()
    m_str = str(model_id).lower()
    return f"routeforge:circuit:{p_str}:{m_str}"


def get_probe_redis_key(provider_id: ProviderId | str, model_id: ModelId | str) -> str:
    """Format Redis string key for half-open probe lock."""
    p_str = str(provider_id).lower()
    m_str = str(model_id).lower()
    return f"routeforge:circuit:{p_str}:{m_str}:probe"


RECORD_FAILURE_LUA = """
local key = KEYS[1]
local probe_key = KEYS[2]
local failure_threshold = tonumber(ARGV[1])
local open_duration = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local error_code = ARGV[4]

local state = redis.call("HGET", key, "state") or "CLOSED"
local count = tonumber(redis.call("HGET", key, "consecutive_failures") or "0") + 1
redis.call("HSET", key, "consecutive_failures", count)
redis.call("HSET", key, "last_error_code", error_code)

if count >= failure_threshold or state == "HALF_OPEN" then
    local open_until = now + open_duration
    redis.call("HSET", key, "state", "OPEN")
    redis.call("HSET", key, "opened_at", now)
    redis.call("HSET", key, "open_until", open_until)
    redis.call("DEL", probe_key)
    return {"OPEN", count, tostring(open_until)}
else
    redis.call("HSET", key, "state", "CLOSED")
    return {"CLOSED", count, "0"}
end
"""

RECORD_SUCCESS_LUA = """
local key = KEYS[1]
local probe_key = KEYS[2]
local now = tonumber(ARGV[1])

redis.call("HSET", key, "state", "CLOSED")
redis.call("HSET", key, "consecutive_failures", 0)
redis.call("HSET", key, "opened_at", 0)
redis.call("HSET", key, "open_until", 0)
redis.call("HSET", key, "last_success_at", now)
redis.call("DEL", probe_key)
return {"CLOSED", 0, "0"}
"""


class RedisCircuitBreaker:
    """Redis-backed circuit breaker evaluating passive health per (provider_id, model_id)."""

    def __init__(
        self,
        redis_client: Any = None,
        clock_fn: Callable[[], float] | None = None,
    ) -> None:
        self.redis = redis_client
        self.clock_fn = clock_fn or (lambda: datetime.now(UTC).timestamp())
        self._record_failure_script: Any = None
        self._record_success_script: Any = None

    async def get_routing_state(
        self,
        provider_id: ProviderId | str,
        model_id: ModelId | str,
        policy: CircuitBreakerPolicy | None,
        now: float | None = None,
    ) -> ProviderHealthSnapshot:
        """Resolve current circuit state and map to ProviderOperatingState for routing."""
        p_id = ProviderId(str(provider_id))
        m_id = ModelId(str(model_id))
        current_time = now if now is not None else self.clock_fn()

        if policy is None or not policy.enabled:
            return ProviderHealthSnapshot(
                provider_id=p_id,
                model_id=m_id,
                circuit_state=CircuitState.CLOSED,
                provider_state=ProviderOperatingState.HEALTHY,
                consecutive_failures=0,
            )

        if self.redis is None:
            return ProviderHealthSnapshot(
                provider_id=p_id,
                model_id=m_id,
                circuit_state=CircuitState.CLOSED,
                provider_state=ProviderOperatingState.HEALTHY,
                consecutive_failures=0,
            )

        key = get_circuit_redis_key(p_id, m_id)
        raw_data = await self.redis.hgetall(key)
        if not raw_data:
            return ProviderHealthSnapshot(
                provider_id=p_id,
                model_id=m_id,
                circuit_state=CircuitState.CLOSED,
                provider_state=ProviderOperatingState.HEALTHY,
                consecutive_failures=0,
            )

        # Parse Redis string hash
        state_str = raw_data.get(b"state", raw_data.get("state", "CLOSED"))
        if isinstance(state_str, bytes):
            state_str = state_str.decode("utf-8")

        failures_raw = raw_data.get(
            b"consecutive_failures", raw_data.get("consecutive_failures", 0)
        )
        failures = int(failures_raw)

        open_until_raw = raw_data.get(b"open_until", raw_data.get("open_until", None))
        open_until = float(open_until_raw) if open_until_raw and float(open_until_raw) > 0 else None

        last_error_raw = raw_data.get(b"last_error_code", raw_data.get("last_error_code", None))
        last_error = (
            last_error_raw.decode("utf-8") if isinstance(last_error_raw, bytes) else last_error_raw
        )

        last_success_raw = raw_data.get(b"last_success_at", raw_data.get("last_success_at", None))
        last_success = (
            float(last_success_raw) if last_success_raw and float(last_success_raw) > 0 else None
        )

        if state_str == "OPEN":
            if open_until is not None and current_time < open_until:
                return ProviderHealthSnapshot(
                    provider_id=p_id,
                    model_id=m_id,
                    circuit_state=CircuitState.OPEN,
                    provider_state=ProviderOperatingState.UNAVAILABLE,
                    consecutive_failures=failures,
                    open_until=open_until,
                    last_error_code=last_error,
                    last_success_at=last_success,
                )
            else:
                # Open duration expired -> transition to HALF_OPEN
                return ProviderHealthSnapshot(
                    provider_id=p_id,
                    model_id=m_id,
                    circuit_state=CircuitState.HALF_OPEN,
                    provider_state=ProviderOperatingState.DEGRADED,
                    consecutive_failures=failures,
                    open_until=open_until,
                    last_error_code=last_error,
                    last_success_at=last_success,
                )

        if state_str == "HALF_OPEN":
            return ProviderHealthSnapshot(
                provider_id=p_id,
                model_id=m_id,
                circuit_state=CircuitState.HALF_OPEN,
                provider_state=ProviderOperatingState.DEGRADED,
                consecutive_failures=failures,
                open_until=open_until,
                last_error_code=last_error,
                last_success_at=last_success,
            )

        return ProviderHealthSnapshot(
            provider_id=p_id,
            model_id=m_id,
            circuit_state=CircuitState.CLOSED,
            provider_state=ProviderOperatingState.HEALTHY,
            consecutive_failures=failures,
            open_until=open_until,
            last_error_code=last_error,
            last_success_at=last_success,
        )

    async def acquire_half_open_probe(
        self,
        provider_id: ProviderId | str,
        model_id: ModelId | str,
        now: float | None = None,
        ttl_seconds: int = 30,
    ) -> bool:
        """Atomically acquire the single half-open probe reservation lock."""
        if self.redis is None:
            return True
        probe_key = get_probe_redis_key(provider_id, model_id)
        current_time = str(now if now is not None else self.clock_fn())
        # SET probe_key current_time NX EX ttl_seconds
        res = await self.redis.set(probe_key, current_time, nx=True, ex=ttl_seconds)
        return bool(res)

    async def release_half_open_probe(
        self,
        provider_id: ProviderId | str,
        model_id: ModelId | str,
    ) -> None:
        """Release the half-open probe reservation lock."""
        if self.redis is None:
            return
        probe_key = get_probe_redis_key(provider_id, model_id)
        await self.redis.delete(probe_key)

    async def record_terminal_failure(
        self,
        provider_id: ProviderId | str,
        model_id: ModelId | str,
        policy: CircuitBreakerPolicy | None,
        error_code: str,
        now: float | None = None,
    ) -> ProviderHealthSnapshot:
        """Record a terminal failure for (provider_id, model_id) atomically in Redis."""
        p_id = ProviderId(str(provider_id))
        m_id = ModelId(str(model_id))
        current_time = now if now is not None else self.clock_fn()

        if policy is None or not policy.enabled or self.redis is None:
            return ProviderHealthSnapshot(
                provider_id=p_id,
                model_id=m_id,
                circuit_state=CircuitState.CLOSED,
                provider_state=ProviderOperatingState.HEALTHY,
                consecutive_failures=0,
                last_error_code=error_code,
            )

        key = get_circuit_redis_key(p_id, m_id)
        probe_key = get_probe_redis_key(p_id, m_id)

        if self._record_failure_script is None:
            self._record_failure_script = self.redis.register_script(RECORD_FAILURE_LUA)

        res = await self._record_failure_script(
            keys=[key, probe_key],
            args=[policy.failure_threshold, policy.open_duration_seconds, current_time, error_code],
        )

        new_state_str, failures, open_until_str = res[0], int(res[1]), res[2]
        if isinstance(new_state_str, bytes):
            new_state_str = new_state_str.decode("utf-8")
        if isinstance(open_until_str, bytes):
            open_until_str = open_until_str.decode("utf-8")

        open_until = float(open_until_str) if float(open_until_str) > 0 else None
        c_state = CircuitState(new_state_str)
        p_state = (
            ProviderOperatingState.UNAVAILABLE
            if c_state == CircuitState.OPEN
            else ProviderOperatingState.HEALTHY
        )

        return ProviderHealthSnapshot(
            provider_id=p_id,
            model_id=m_id,
            circuit_state=c_state,
            provider_state=p_state,
            consecutive_failures=failures,
            open_until=open_until,
            last_error_code=error_code,
        )

    async def record_success(
        self,
        provider_id: ProviderId | str,
        model_id: ModelId | str,
        now: float | None = None,
    ) -> ProviderHealthSnapshot:
        """Record a successful execution for (provider_id, model_id) atomically in Redis."""
        p_id = ProviderId(str(provider_id))
        m_id = ModelId(str(model_id))
        current_time = now if now is not None else self.clock_fn()

        if self.redis is None:
            return ProviderHealthSnapshot(
                provider_id=p_id,
                model_id=m_id,
                circuit_state=CircuitState.CLOSED,
                provider_state=ProviderOperatingState.HEALTHY,
                consecutive_failures=0,
                last_success_at=current_time,
            )

        key = get_circuit_redis_key(p_id, m_id)
        probe_key = get_probe_redis_key(p_id, m_id)

        if self._record_success_script is None:
            self._record_success_script = self.redis.register_script(RECORD_SUCCESS_LUA)

        await self._record_success_script(
            keys=[key, probe_key],
            args=[current_time],
        )

        return ProviderHealthSnapshot(
            provider_id=p_id,
            model_id=m_id,
            circuit_state=CircuitState.CLOSED,
            provider_state=ProviderOperatingState.HEALTHY,
            consecutive_failures=0,
            last_success_at=current_time,
        )
