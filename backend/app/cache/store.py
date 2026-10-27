"""Thin wrapper around redis.asyncio used by the cache layer.

Values are stored as JSON strings. Keeping all Redis calls in one class gives
us one place to add timeouts and error handling.
"""
import json
from typing import Any

from redis.asyncio import Redis


class CacheStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def get_json(self, key: str) -> Any | None:
        raw = await self.redis.get(key)
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self.redis.set(key, json.dumps(value, separators=(",", ":")), ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        await self.redis.delete(*keys)

    async def get_int(self, key: str) -> int:
        raw = await self.redis.get(key)
        return int(raw) if raw is not None else 0

    async def delete_and_incr(self, delete_keys: list[str], incr_keys: list[str]) -> None:
        # MULTI/EXEC so the delete and the version bumps happen together in
        # one round trip; no reader sees "product deleted, searches not yet".
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(*delete_keys)
            for key in incr_keys:
                pipe.incr(key)
            await pipe.execute()

    async def close(self) -> None:
        await self.redis.aclose()
