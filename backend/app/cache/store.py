"""Thin wrapper around redis.asyncio used by the cache layer.

Values are stored as JSON strings. Keeping all Redis calls in one class gives
us one place for timeouts and error handling.

Graceful degradation: every Redis error is turned into CacheUnavailable, which
callers treat as "skip the cache and go to Postgres". After a failure we stop
calling Redis for a few seconds (a tiny circuit breaker). Without that, every
request would wait for a connection timeout while Redis is down, making the
API slower than having no cache at all.
"""
import json
import logging
import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("warpcart.cache")

# Compare-and-delete: only the request that took the lock may release it.
# A plain DEL could delete a lock that expired and was taken by someone else.
RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class CacheUnavailable(Exception):
    """Redis could not be reached; the caller should fall back to the database."""


class CacheStore:
    def __init__(self, redis: Redis, retry_after_seconds: float = 5.0):
        self.redis = redis
        self.retry_after_seconds = retry_after_seconds
        self._down_until = 0.0

    @classmethod
    def from_url(cls, url: str, timeout_seconds: float, retry_after_seconds: float) -> "CacheStore":
        # Short timeouts: a cache that takes seconds to answer is worse than no cache.
        redis = Redis.from_url(
            url, decode_responses=True,
            socket_timeout=timeout_seconds, socket_connect_timeout=timeout_seconds,
        )
        return cls(redis, retry_after_seconds)

    # --- circuit breaker ---------------------------------------------------
    async def _call(self, coro_factory):
        if time.monotonic() < self._down_until:
            raise CacheUnavailable("redis marked down, skipping")
        try:
            result = await coro_factory()
        except (RedisError, OSError) as exc:
            if self._down_until == 0.0:
                logger.warning("Redis unavailable (%s); serving from Postgres for %.0fs",
                               exc.__class__.__name__, self.retry_after_seconds)
            self._down_until = time.monotonic() + self.retry_after_seconds
            raise CacheUnavailable(str(exc)) from exc
        if self._down_until:
            logger.warning("Redis is reachable again; cache re-enabled")
            self._down_until = 0.0
        return result

    # --- values --------------------------------------------------------------
    async def get_json(self, key: str) -> Any | None:
        raw = await self._call(lambda: self.redis.get(key))
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        payload = json.dumps(value, separators=(",", ":"))
        await self._call(lambda: self.redis.set(key, payload, ex=ttl_seconds))

    async def delete(self, *keys: str) -> None:
        await self._call(lambda: self.redis.delete(*keys))

    async def get_int(self, key: str) -> int:
        raw = await self._call(lambda: self.redis.get(key))
        return int(raw) if raw is not None else 0

    async def delete_and_incr(self, delete_keys: list[str], incr_keys: list[str]) -> None:
        # MULTI/EXEC so the delete and the version bumps happen together in
        # one round trip; no reader sees "product deleted, searches not yet".
        async def run():
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.delete(*delete_keys)
                for key in incr_keys:
                    pipe.incr(key)
                return await pipe.execute()

        await self._call(run)

    # --- locks ---------------------------------------------------------------
    async def acquire_lock(self, key: str, token: str, ttl_ms: int) -> bool:
        """SET key token NX PX ttl: succeeds for exactly one caller.

        PX makes the lock expire by itself, so a crashed worker can never
        hold it forever.
        """
        return bool(await self._call(lambda: self.redis.set(key, token, nx=True, px=ttl_ms)))

    async def release_lock(self, key: str, token: str) -> None:
        await self._call(lambda: self.redis.eval(RELEASE_LOCK_SCRIPT, 1, key, token))

    async def close(self) -> None:
        await self.redis.aclose()
