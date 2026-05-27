"""Redis-backed token-bucket rate limiter for vendor calls.

Uses Redis DB 2 (``REDIS_DB_RATELIMIT`` in settings) — already reserved at
M0 but first consumed by M3. One Lua script per rate-limit check makes the
read-modify-write atomic under concurrent Celery workers.

Per CLAUDE.md: never read ``os.environ`` directly. Connection details come
from ``app.config.settings``.
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis

from app.config import settings
from app.errors import IntegrationRateLimitError

# Lua: sliding-window counter. KEYS[1] = bucket key; ARGV[1] = limit;
# ARGV[2] = window seconds; ARGV[3] = now (ms). Returns (allowed:int,
# retry_after_seconds:float). Atomically increments + sets TTL on first hit.
_RATE_LIMIT_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local count = tonumber(redis.call('GET', key) or '0')
if count + 1 > limit then
  local ttl_ms = redis.call('PTTL', key)
  if ttl_ms < 0 then ttl_ms = window_seconds * 1000 end
  return {0, ttl_ms / 1000.0}
end
redis.call('INCR', key)
if count == 0 then
  redis.call('PEXPIRE', key, window_seconds * 1000)
end
return {1, 0.0}
"""

_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Lazy-init async Redis client bound to the rate-limit DB."""
    global _redis_client
    if _redis_client is None:
        kwargs: dict[str, object] = {
            "host": settings.redis_host,
            "port": settings.redis_port,
            "db": settings.redis_db_ratelimit,
            "decode_responses": False,
        }
        if settings.redis_password is not None:
            kwargs["password"] = settings.redis_password.get_secret_value()
        _redis_client = aioredis.Redis(**kwargs)  # type: ignore[arg-type]
    return _redis_client


def reset_client_for_tests() -> None:
    """Reset the async Redis client (test-only)."""
    global _redis_client
    _redis_client = None


async def check_rate_limit(
    vendor: str,
    bucket: str,
    *,
    max_per_period: int,
    period_seconds: int,
) -> None:
    """Raise ``IntegrationRateLimitError`` if the bucket is exhausted.

    The bucket key is namespaced as ``ratelimit:{vendor}:{bucket}`` to avoid
    collisions between different vendors and different per-vendor scopes
    (e.g. global vs per-talent).
    """
    client = get_redis_client()
    now_ms = int(time.time() * 1000)
    key = f"ratelimit:{vendor}:{bucket}"
    # SECURITY: ``client.eval`` is the Redis EVAL command (executes a Lua
    # script on the Redis server), NOT Python's ``eval()`` builtin. The Lua
    # source is the hard-coded module constant ``_RATE_LIMIT_LUA``; none of
    # it is interpolated from caller input. The string ARGV values are
    # bound as separate arguments (Redis params), not concatenated into the
    # script body — so this is safe from script-injection.
    result = await client.eval(  # type: ignore[misc]
        _RATE_LIMIT_LUA,
        1,
        key,
        str(max_per_period),
        str(period_seconds),
        str(now_ms),
    )
    allowed, retry_after = result  # type: ignore[misc]
    if int(allowed) == 0:
        raise IntegrationRateLimitError(
            f"Rate limit exceeded for {vendor}/{bucket}",
            detail={
                "vendor": vendor,
                "bucket": bucket,
                "retry_after_seconds": float(retry_after),
            },
        )
