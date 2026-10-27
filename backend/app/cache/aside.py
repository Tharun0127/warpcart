"""The cache-aside (lazy loading) pattern, with stampede protection.

    1. Look in Redis.
    2. Hit  -> return it. The database is never touched.
    3. Miss -> run the loader (a database query), store the result with a TTL,
               return it.

The application owns this logic; Redis is just a key-value store. That is
the difference from read-through caching, where the cache itself knows how
to load data.

Stampede protection (STAMPEDE_STRATEGY):
- "lock":   on a miss, only the request that wins a Redis lock (SET NX PX)
            queries the database. The others wait briefly and re-read the
            cache.
- "xfetch": probabilistic early expiration. Each read may decide to refresh
            the value a little BEFORE it expires; the closer to expiry and
            the slower the query, the more likely. One early refresher
            usually renews the key before the crowd ever sees a miss.
- "none":   plain cache-aside, for comparison.
"""
import asyncio
import logging
import math
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.cache import invalidation, keys
from app.cache.store import CacheStore, CacheUnavailable
from app.config import Settings

logger = logging.getLogger("warpcart.cache")

HIT = "HIT"
MISS = "MISS"
BYPASS = "BYPASS"  # cache switched off with CACHE_ENABLED=false
DEGRADED = "DEGRADED"  # Redis is down; served straight from Postgres

Loader = Callable[[], Awaitable[Any]]


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


def should_refresh_early(now: float, expires_at: float, compute_seconds: float, beta: float,
                         rand: float) -> bool:
    """XFetch (Vattani et al., "Optimal Probabilistic Cache Stampede Prevention").

    -log(rand) is a random number that is usually small but occasionally
    large. Scaling it by how long the value takes to compute (delta) and
    beta gives "how early this request is willing to refresh". Most requests
    say "not yet"; as expiry approaches, one of them says "now" and refreshes
    while everyone else keeps getting the cached value.
    """
    rand = max(rand, 1e-12)  # log(0) is undefined
    return now - compute_seconds * beta * math.log(rand) >= expires_at


class CacheAside:
    def __init__(self, store: CacheStore, settings: Settings):
        self.store = store
        self.settings = settings

    # --- helpers used by the service layer -----------------------------------
    async def search_version(self, scope: str) -> int:
        if not self.settings.cache_enabled:
            return 0
        try:
            return await self.store.get_int(keys.search_version_key(scope))
        except CacheUnavailable:
            return 0  # get_or_load will also see Redis down and go to Postgres

    async def invalidate_product(self, product_id: int, category_slug: str) -> None:
        if not self.settings.cache_enabled:
            return
        try:
            await invalidation.invalidate_product(self.store, product_id, category_slug)
        except CacheUnavailable:
            # The write already succeeded in Postgres, so we must not fail the
            # request. Stale entries (if Redis comes back with data) are
            # bounded by their TTL.
            logger.warning("could not invalidate product %s: Redis unavailable", product_id)

    # --- the main entry point -------------------------------------------------
    async def get_or_load(
        self,
        key: str,
        loader: Loader,
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
        ttls = (ttl_seconds, empty_ttl_seconds or ttl_seconds)
        try:
            return await self._get_or_load(key, loader, ttls)
        except CacheUnavailable:
            return CacheResult(await loader(), DEGRADED)

    async def _get_or_load(self, key: str, loader: Loader, ttls: tuple[int, int]) -> CacheResult:
        entry = await self.store.get_json(key)
        if entry is not None and not self._wants_early_refresh(entry):
            return CacheResult(entry["value"], HIT)

        if self.settings.stampede_strategy == "lock":
            return await self._load_with_lock(key, loader, ttls)
        return CacheResult(await self._load_and_store(key, loader, ttls), MISS)

    def _wants_early_refresh(self, entry: dict) -> bool:
        if self.settings.stampede_strategy != "xfetch" or "expires_at" not in entry:
            return False
        return should_refresh_early(
            time.time(), entry["expires_at"], entry.get("compute_seconds", 0.0),
            self.settings.xfetch_beta, random.random(),
        )

    async def _load_and_store(self, key: str, loader: Loader, ttls: tuple[int, int]) -> Any:
        started = time.perf_counter()
        value = await loader()
        compute_seconds = time.perf_counter() - started

        base_ttl = ttls[0] if value is not None else ttls[1]
        ttl = ttl_with_jitter(base_ttl, self.settings.ttl_jitter_ratio)
        # Wrap the value so a cached "not found" (None) is distinguishable
        # from "not in cache" (Redis returns nil). expires_at and
        # compute_seconds are what XFetch needs to decide on early refresh.
        entry = {"value": value, "expires_at": time.time() + ttl, "compute_seconds": compute_seconds}
        await self.store.set_json(key, entry, ttl)
        return value

    async def _load_with_lock(self, key: str, loader: Loader, ttls: tuple[int, int]) -> CacheResult:
        lock_key = keys.lock_key(key)
        token = uuid.uuid4().hex
        if await self.store.acquire_lock(lock_key, token, self.settings.stampede_lock_ttl_ms):
            try:
                return CacheResult(await self._load_and_store(key, loader, ttls), MISS)
            finally:
                await self.store.release_lock(lock_key, token)

        # Someone else is rebuilding. Poll the cache until their value lands.
        deadline = time.monotonic() + self.settings.stampede_max_wait_ms / 1000
        while time.monotonic() < deadline:
            await asyncio.sleep(self.settings.stampede_retry_ms / 1000)
            entry = await self.store.get_json(key)
            if entry is not None:
                return CacheResult(entry["value"], HIT)

        # The lock holder is too slow or died. Serve from the database rather
        # than make the user wait longer; do not cache, the holder will.
        logger.warning("stampede lock wait timed out for %s; loading directly", key)
        return CacheResult(await loader(), MISS)
