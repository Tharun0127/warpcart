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

    async def close(self) -> None:
        await self.redis.aclose()
