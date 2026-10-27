"""The cache-aside (lazy loading) pattern.

    1. Look in Redis.
    2. Hit  -> return it. The database is never touched.
    3. Miss -> run the loader (a database query), store the result with a TTL,
               return it.

The application owns this logic; Redis is just a key-value store. That is
the difference from read-through caching, where the cache itself knows how
to load data.
"""
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.cache.store import CacheStore
from app.config import Settings

HIT = "HIT"
MISS = "MISS"
BYPASS = "BYPASS"  # cache switched off with CACHE_ENABLED=false


@dataclass
class CacheResult:
    value: Any
    status: str


def ttl_with_jitter(base_seconds: int, jitter_ratio: float, rng: random.Random = random) -> int:
    """Spread expiry times by +/- jitter_ratio.

    Without jitter, 1,000 keys cached during a traffic spike would all expire
    in the same second, and the database would get 1,000 misses at once.
    """
    spread = base_seconds * jitter_ratio
    return max(1, round(base_seconds + rng.uniform(-spread, spread)))


class CacheAside:
    def __init__(self, store: CacheStore, settings: Settings):
        self.store = store
        self.settings = settings

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        ttl_seconds: int,
        empty_ttl_seconds: int | None = None,
    ) -> CacheResult:
        """Return the cached value for `key`, loading and caching it on a miss.

        A loader result of None ("not found") is cached too, for the shorter
        `empty_ttl_seconds`. That stops repeated requests for ids that do not
        exist from hitting the database every time (cache penetration).
        """
        if not self.settings.cache_enabled:
            return CacheResult(await loader(), BYPASS)

        cached = await self.store.get_json(key)
        if cached is not None:
            return CacheResult(cached["value"], HIT)

        value = await loader()
        ttl = ttl_seconds if value is not None else (empty_ttl_seconds or ttl_seconds)
        # Wrap the value so a cached "not found" (None) is distinguishable
        # from "not in cache" (Redis returns nil).
        await self.store.set_json(key, {"value": value}, ttl_with_jitter(ttl, self.settings.ttl_jitter_ratio))
        return CacheResult(value, MISS)
