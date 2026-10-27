"""Graceful degradation: the API keeps working when Redis is unreachable.

The app is pointed at a port where nothing listens, which is exactly what a
crashed Redis looks like to the client: connection refused.
"""
import logging

from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.store import CacheStore, CacheUnavailable

DEAD_REDIS = "redis://localhost:1/0"


async def test_reads_are_served_from_postgres_when_redis_is_down(client_factory, caplog):
    client = await client_factory(redis_url=DEAD_REDIS)
    with caplog.at_level(logging.WARNING, logger="warpcart.cache"):
        detail = await client.get("/products/1")
        search = await client.get("/products", params={"q": "wireless", "category": "toys"})
        categories = await client.get("/categories")
        missing = await client.get("/products/999999")

    assert detail.status_code == 200 and detail.json()["id"] == 1
    assert search.status_code == 200 and search.json()["items"]
    assert categories.status_code == 200 and len(categories.json()) == 3
    assert missing.status_code == 404
    assert {r.headers["X-Cache"] for r in (detail, search, categories, missing)} == {"DEGRADED"}
    assert "Redis unavailable" in caplog.text


async def test_admin_updates_still_work_when_redis_is_down(client_factory):
    client = await client_factory(redis_url=DEAD_REDIS)
    token = (await client.post("/auth/token", json={"username": "admin", "password": "admin123"})).json()
    response = await client.patch(
        "/admin/products/3", json={"price": "42.00"},
        headers={"Authorization": f"Bearer {token['access_token']}"},
    )
    assert response.status_code == 200
    assert (await client.get("/products/3")).json()["price"] == "42.00"


class FailingRedis:
    """Stand-in for a Redis client that is down; counts how often it is called."""

    def __init__(self):
        self.calls = 0

    async def get(self, key):
        self.calls += 1
        raise RedisConnectionError("connection refused")


async def test_circuit_breaker_stops_calling_redis_after_repeated_failures():
    redis = FailingRedis()
    store = CacheStore(redis, retry_after_seconds=60, failure_threshold=3)
    for _ in range(10):
        try:
            await store.get_json("any")
        except CacheUnavailable:
            pass
    # Only the first 3 calls reached Redis; the rest were skipped instantly
    # instead of each waiting for a connection timeout.
    assert redis.calls == 3


async def test_a_single_failure_does_not_open_the_breaker():
    class FlakyRedis(FailingRedis):
        async def get(self, key):
            self.calls += 1
            if self.calls == 1:
                raise RedisConnectionError("blip")
            return None

    redis = FlakyRedis()
    store = CacheStore(redis, retry_after_seconds=60, failure_threshold=3)
    try:
        await store.get_json("any")
    except CacheUnavailable:
        pass
    assert await store.get_json("any") is None  # second call went to Redis again
    assert redis.calls == 2


async def test_circuit_breaker_retries_after_the_cooldown():
    redis = FailingRedis()
    store = CacheStore(redis, retry_after_seconds=0)
    for _ in range(3):
        try:
            await store.get_json("any")
        except CacheUnavailable:
            pass
    assert redis.calls == 3
