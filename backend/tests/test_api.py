"""Behaviour of the catalog and admin endpoints (independent of caching)."""
import pytest


async def admin_headers(client) -> dict:
    response = await client.post("/auth/token", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_categories_are_listed(client):
    response = await client.get("/categories")
    assert response.status_code == 200
    assert [c["slug"] for c in response.json()] == ["books", "electronics", "toys"]


async def test_product_detail_returns_product(client):
    response = await client.get("/products/1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["category_slug"] == "electronics"
    assert body["price"] == "10.00"  # money is a string, never a float


async def test_missing_product_returns_404(client):
    response = await client.get("/products/999999")
    assert response.status_code == 404


async def test_search_by_keyword_category_and_price(client):
    response = await client.get(
        "/products", params={"q": "wireless", "category": "books", "min_price": 30, "max_price": 90}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items, "expected some matches"
    for item in items:
        assert "Wireless" in item["name"]
        assert item["category_slug"] == "books"
        assert 30 <= float(item["price"]) <= 90


async def test_search_pagination_reports_has_more(client):
    first = (await client.get("/products", params={"page_size": 25})).json()
    assert first["has_more"] is True and len(first["items"]) == 25
    last = (await client.get("/products", params={"page_size": 25, "page": 3})).json()
    assert last["has_more"] is False and len(last["items"]) == 10
    ids = [i["id"] for i in first["items"]]
    assert ids == sorted(ids)


async def test_like_wildcards_in_keyword_are_treated_literally(client):
    response = await client.get("/products", params={"q": "%"})
    assert response.json()["items"] == []


@pytest.mark.parametrize("params", [{"min_price": 50, "max_price": 10}, {"page": 0}, {"page_size": 1000}])
async def test_invalid_search_params_are_rejected(client, params):
    response = await client.get("/products", params=params)
    assert response.status_code == 422


async def test_admin_update_requires_token(client):
    response = await client.patch("/admin/products/1", json={"price": "5.00"})
    assert response.status_code == 401


async def test_admin_login_rejects_bad_password(client):
    response = await client.post("/auth/token", json={"username": "admin", "password": "nope"})
    assert response.status_code == 401


async def test_admin_can_update_price_and_stock(client):
    headers = await admin_headers(client)
    response = await client.patch("/admin/products/2", json={"price": "12.34", "stock": 7}, headers=headers)
    assert response.status_code == 200
    assert response.json()["price"] == "12.34"
    assert response.json()["stock"] == 7


async def test_admin_update_validates_body(client):
    headers = await admin_headers(client)
    assert (await client.patch("/admin/products/2", json={}, headers=headers)).status_code == 422
    assert (await client.patch("/admin/products/2", json={"price": "-1"}, headers=headers)).status_code == 422
    assert (await client.patch("/admin/products/999999", json={"stock": 1}, headers=headers)).status_code == 404
