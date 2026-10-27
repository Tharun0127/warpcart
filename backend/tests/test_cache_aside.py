"""Integration tests: cache-aside against real Redis and Postgres."""
from app.cache.keys import product_key


async def test_product_detail_miss_then_hit(client, redis_client):
    first = await client.get("/products/1")
    second = await client.get("/products/1")
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()
    assert await redis_client.exists(product_key(1))


async def test_hit_is_served_from_redis_not_the_database(client, redis_client):
    await client.get("/products/1")
    # Change the row behind the cache's back (no invalidation). A hit must
    # still return the cached copy, proving the DB was not consulted.
    await redis_client.set(product_key(1), '{"value": {"id": 1, "name": "from-cache"}}', ex=60)
    response = await client.get("/products/1")
    assert response.headers["X-Cache"] == "HIT"
    assert response.json()["name"] == "from-cache"


async def test_search_results_are_cached_under_normalized_key(client):
    first = await client.get("/products", params={"q": "Wireless", "category": "Books"})
    second = await client.get("/products", params={"q": "  wireless ", "category": "books", "page": 1})
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()


async def test_not_found_is_cached_briefly(client, redis_client):
    first = await client.get("/products/999999")
    second = await client.get("/products/999999")
    assert first.status_code == second.status_code == 404
    assert second.headers["X-Cache"] == "HIT"
    ttl = await redis_client.ttl(product_key(999999))
    assert 0 < ttl <= 33  # 30s not-found TTL + 10% jitter


async def test_each_data_type_gets_its_own_ttl(client, redis_client):
    await client.get("/products/1")
    await client.get("/products", params={"q": "classic"})
    await client.get("/categories")

    product_ttl = await redis_client.ttl(product_key(1))
    search_keys = [k async for k in redis_client.scan_iter(match="wc:v1:search:*")]
    search_ttl = await redis_client.ttl(search_keys[0])
    categories_ttl = await redis_client.ttl("wc:v1:categories")

    assert 270 <= product_ttl <= 330
    assert 54 <= search_ttl <= 66
    assert 3240 <= categories_ttl <= 3960


async def test_cache_disabled_bypasses_redis_entirely(client_factory, redis_client):
    client = await client_factory(cache_enabled=False)
    first = await client.get("/products/1")
    second = await client.get("/products/1")
    assert first.headers["X-Cache"] == second.headers["X-Cache"] == "BYPASS"
    # Only metrics counters are written; nothing is cached.
    stored = [k async for k in redis_client.scan_iter(match="*")]
    assert stored and all(k.startswith("wc:v1:metrics:") for k in stored)
