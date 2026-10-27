"""Integration tests: stampede protection against real Redis and Postgres.

We count how many times the database loader actually runs by wrapping
repository.get_product. A small sleep inside the wrapper widens the window in
which concurrent requests can pile up, like a slow query under load would.
"""
import asyncio

import pytest

from app import repository
from app.cache.keys import lock_key, product_key


@pytest.fixture
def count_db_loads(monkeypatch):
    calls = {"count": 0}
    real_get_product = repository.get_product

    async def slow_counting_get_product(session, product_id):
        calls["count"] += 1
        await asyncio.sleep(0.05)
        return await real_get_product(session, product_id)

    monkeypatch.setattr(repository, "get_product", slow_counting_get_product)
    return calls


async def fire(client, path: str, n: int) -> list:
    return await asyncio.gather(*(client.get(path) for _ in range(n)))


async def test_lock_lets_only_one_of_500_requests_hit_the_database(client_factory, redis_client, count_db_loads):
    client = await client_factory(stampede_strategy="lock")
    await client.get("/products/1")          # warm the key
    await redis_client.delete(product_key(1))  # the hot key "expires"
    count_db_loads["count"] = 0

    responses = await fire(client, "/products/1", 500)

    assert all(r.status_code == 200 for r in responses)
    assert count_db_loads["count"] == 1
    statuses = [r.headers["X-Cache"] for r in responses]
    assert statuses.count("MISS") == 1 and statuses.count("HIT") == 499
    assert not await redis_client.exists(lock_key(product_key(1)))  # lock released


async def test_without_protection_many_requests_hit_the_database(client_factory, redis_client, count_db_loads):
    client = await client_factory(stampede_strategy="none")
    responses = await fire(client, "/products/1", 50)
    assert all(r.status_code == 200 for r in responses)
    assert count_db_loads["count"] > 1  # this is the stampede


async def test_waiters_fall_back_to_the_database_if_the_lock_holder_never_finishes(
    client_factory, redis_client, count_db_loads
):
    client = await client_factory(stampede_strategy="lock", stampede_max_wait_ms=100)
    # Simulate a lock held by a crashed worker.
    await redis_client.set(lock_key(product_key(1)), "someone-else", px=10_000)

    response = await client.get("/products/1")

    assert response.status_code == 200
    assert count_db_loads["count"] == 1
    assert not await redis_client.exists(product_key(1))  # only the lock holder caches


async def test_xfetch_refreshes_a_key_that_is_about_to_expire(client_factory, redis_client, count_db_loads):
    client = await client_factory(stampede_strategy="xfetch", xfetch_beta=1_000_000)
    await client.get("/products/1")
    assert count_db_loads["count"] == 1
    # With a huge beta every read is "close enough" to expiry to refresh early.
    response = await client.get("/products/1")
    assert response.headers["X-Cache"] == "MISS"
    assert count_db_loads["count"] == 2


async def test_xfetch_serves_hits_when_far_from_expiry(client_factory, count_db_loads):
    client = await client_factory(stampede_strategy="xfetch", xfetch_beta=1.0)
    await client.get("/products/1")
    hits = [r.headers["X-Cache"] for r in await fire(client, "/products/1", 20)]
    assert hits == ["HIT"] * 20
    assert count_db_loads["count"] == 1
