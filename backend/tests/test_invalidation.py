"""Integration tests: admin updates invalidate the right cache entries."""
from app.cache.keys import product_key, search_version_key


async def admin_headers(client) -> dict:
    response = await client.post("/auth/token", json={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_update_invalidates_product_detail(client, redis_client):
    assert (await client.get("/products/2")).headers["X-Cache"] == "MISS"
    assert (await client.get("/products/2")).headers["X-Cache"] == "HIT"

    await client.patch("/admin/products/2", json={"price": "99.99"}, headers=await admin_headers(client))

    assert not await redis_client.exists(product_key(2))
    response = await client.get("/products/2")
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["price"] == "99.99"


async def test_update_invalidates_searches_in_the_same_category(client):
    # Product 21 is the first "books" product (price 10.00).
    params = {"category": "books", "max_price": 15}
    before = await client.get("/products", params=params)
    assert [i["id"] for i in before.json()["items"]] == [21]
    assert (await client.get("/products", params=params)).headers["X-Cache"] == "HIT"

    await client.patch("/admin/products/21", json={"price": "500.00"}, headers=await admin_headers(client))

    after = await client.get("/products", params=params)
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["items"] == []  # no stale result: the product left the price band


async def test_update_invalidates_searches_without_a_category(client):
    params = {"q": "classic electronics item 2"}
    await client.get("/products", params=params)
    assert (await client.get("/products", params=params)).headers["X-Cache"] == "HIT"

    await client.patch("/admin/products/2", json={"stock": 0}, headers=await admin_headers(client))

    after = await client.get("/products", params=params)
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["items"][0]["stock"] == 0


async def test_update_leaves_other_categories_cached(client, redis_client):
    toys = {"category": "toys"}
    await client.get("/products", params=toys)

    await client.patch("/admin/products/21", json={"stock": 3}, headers=await admin_headers(client))

    assert (await client.get("/products", params=toys)).headers["X-Cache"] == "HIT"
    assert await redis_client.get(search_version_key("books")) == "1"
    assert await redis_client.get(search_version_key("all")) == "1"
    assert await redis_client.get(search_version_key("toys")) is None


async def test_failed_update_does_not_invalidate(client, redis_client):
    await client.patch("/admin/products/999999", json={"stock": 1}, headers=await admin_headers(client))
    assert await redis_client.get(search_version_key("all")) is None
