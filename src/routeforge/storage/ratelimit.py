"""Redis-backed atomic rate limiting for team requests and tokens per fixed 1-minute window."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as aioredis
from redis.exceptions import RedisError


class RedisUnavailableError(Exception):
    """Raised when Redis server is unreachable or fails during rate limit check."""

    pass


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a dual request and token rate-limit check."""

    allowed: bool
    exceeded_limit_type: str | None  # "requests" | "tokens" | None
    limit_requests: int
    remaining_requests: int
    limit_tokens: int
    remaining_tokens: int
    reset_timestamp: int
    retry_after_seconds: int


# Atomic Lua script evaluating both request-count and token-count limits
_RATE_LIMIT_LUA_SCRIPT = """
local req_key = KEYS[1]
local tok_key = KEYS[2]
local req_add = tonumber(ARGV[1])
local tok_add = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])
local max_tok = tonumber(ARGV[4])
local ttl_sec = tonumber(ARGV[5])

local cur_req = tonumber(redis.call('GET', req_key) or "0")
local cur_tok = tonumber(redis.call('GET', tok_key) or "0")

if cur_req + req_add > max_req then
    return {0, 1, cur_req, cur_tok}
end

if cur_tok + tok_add > max_tok then
    return {0, 2, cur_req, cur_tok}
end

local new_req = redis.call('INCRBY', req_key, req_add)
if new_req == req_add then
    redis.call('EXPIRE', req_key, ttl_sec)
end

local new_tok = redis.call('INCRBY', tok_key, tok_add)
if new_tok == tok_add then
    redis.call('EXPIRE', tok_key, ttl_sec)
end

return {1, 0, new_req, new_tok}
"""


def get_redis_url() -> str:
    """Resolve Redis connection URL from environment variable or local default."""
    return os.getenv("ROUTEFORGE_REDIS_URL", "redis://localhost:6379/0")


def calculate_minute_window(now: datetime) -> int:
    """Compute fixed-minute window index from timezone-aware UTC datetime."""
    return int(now.timestamp()) // 60


class RedisRateLimiter:
    """Atomic fixed-minute window rate limiter powered by Redis."""

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client

    async def _get_client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(get_redis_url(), decode_responses=True)
        return self._redis

    async def aclose(self) -> None:
        """Close underlying Redis connection pool if created locally."""
        if self._redis is not None:
            await self._redis.aclose()

    async def check_and_consume(
        self,
        team_id: str,
        requests_per_minute: int,
        tokens_per_minute: int,
        estimated_tokens: int,
        now: datetime | None = None,
    ) -> RateLimitResult:
        """Atomically check and consume request and token capacity for fixed minute window."""
        if now is None:
            now = datetime.now(UTC)

        window = calculate_minute_window(now)
        window_start = window * 60
        window_end = window_start + 60
        now_ts = int(now.timestamp())
        retry_after = max(1, window_end - now_ts)

        req_key = f"routeforge:rate:{team_id}:requests:{window}"
        tok_key = f"routeforge:rate:{team_id}:tokens:{window}"
        ttl_seconds = 120  # Keep key alive for 2 minutes to survive window boundary

        try:
            client = await self._get_client()
            res = await client.eval(
                _RATE_LIMIT_LUA_SCRIPT,
                2,
                req_key,
                tok_key,
                1,  # 1 request requested
                estimated_tokens,
                requests_per_minute,
                tokens_per_minute,
                ttl_seconds,
            )
        except (RedisError, Exception) as exc:
            raise RedisUnavailableError(f"Redis rate limit backend unavailable: {exc}") from exc

        # res is [allowed_flag, reason_flag, current_req, current_tok]
        allowed_flag = int(res[0])
        reason_flag = int(res[1])
        cur_req = int(res[2])
        cur_tok = int(res[3])

        if allowed_flag == 1:
            rem_req = max(0, requests_per_minute - cur_req)
            rem_tok = max(0, tokens_per_minute - cur_tok)
            return RateLimitResult(
                allowed=True,
                exceeded_limit_type=None,
                limit_requests=requests_per_minute,
                remaining_requests=rem_req,
                limit_tokens=tokens_per_minute,
                remaining_tokens=rem_tok,
                reset_timestamp=window_end,
                retry_after_seconds=retry_after,
            )
        else:
            limit_type = "requests" if reason_flag == 1 else "tokens"
            rem_req = max(0, requests_per_minute - cur_req)
            rem_tok = max(0, tokens_per_minute - cur_tok)
            return RateLimitResult(
                allowed=False,
                exceeded_limit_type=limit_type,
                limit_requests=requests_per_minute,
                remaining_requests=rem_req,
                limit_tokens=tokens_per_minute,
                remaining_tokens=rem_tok,
                reset_timestamp=window_end,
                retry_after_seconds=retry_after,
            )

    async def ping(self) -> bool:
        """Check Redis server health via PING command."""
        try:
            client = await self._get_client()
            res = await client.ping()
            return bool(res)
        except Exception:
            return False
