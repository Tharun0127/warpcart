"""Cache metrics kept in Redis counters.

One Redis hash per endpoint, e.g. wc:v1:metrics:product_detail, with fields:
    requests, HIT, MISS, BYPASS, DEGRADED, latency_ms_total

Why Redis and not a Python dict: the API runs 4 worker processes. A dict
would only count the requests that one process served. Redis gives one
shared set of numbers, and HINCRBY is atomic, so concurrent workers never
lose an increment.

These keys have no TTL on purpose, so `volatile-lru` never evicts them.
"""
import logging

from app.cache.keys import _key
from app.cache.store import CacheStore, CacheUnavailable

logger = logging.getLogger("warpcart.cache")

ENDPOINTS = ("product_detail", "search", "categories")
STATUSES = ("HIT", "MISS", "BYPASS", "DEGRADED")


def metrics_key(endpoint: str) -> str:
    return _key("metrics", endpoint)


def summarize(endpoint: str, raw: dict[str, str]) -> dict:
    """Turn raw counter strings into the numbers the dashboard shows."""
    counts = {status: int(raw.get(status, 0)) for status in STATUSES}
    requests = int(raw.get("requests", 0))
    latency_total = float(raw.get("latency_ms_total", 0))
    lookups = counts["HIT"] + counts["MISS"]
    return {
        "endpoint": endpoint,
        "requests": requests,
        "hits": counts["HIT"],
        "misses": counts["MISS"],
        "bypassed": counts["BYPASS"],
        "degraded": counts["DEGRADED"],
        # Only real cache lookups count toward the ratio; BYPASS/DEGRADED
        # requests never asked the cache.
        "hit_ratio": round(counts["HIT"] / lookups, 4) if lookups else None,
        "avg_latency_ms": round(latency_total / requests, 3) if requests else None,
    }


class CacheMetrics:
    def __init__(self, store: CacheStore):
        self.store = store

    async def record(self, endpoint: str, status: str, latency_ms: float) -> None:
        # Metrics must never break a request: if Redis is down we just skip.
        try:
            await self.store.hincr_many(metrics_key(endpoint), {"requests": 1, status: 1},
                                        {"latency_ms_total": latency_ms})
        except CacheUnavailable:
            pass

    async def snapshot(self) -> list[dict] | None:
        """Summaries for every endpoint, or None if Redis is unreachable."""
        try:
            raws = await self.store.hgetall_many([metrics_key(e) for e in ENDPOINTS])
        except CacheUnavailable:
            return None
        return [summarize(endpoint, raw) for endpoint, raw in zip(ENDPOINTS, raws)]

    async def reset(self) -> None:
        # The key names are known up front, so no KEYS/SCAN is needed.
        await self.store.delete(*[metrics_key(e) for e in ENDPOINTS])
