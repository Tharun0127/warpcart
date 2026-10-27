"""Realistic catalog traffic for Warpcart.

Mix (by task weight):
- 80% product detail reads, skewed towards popular products (Zipf-like:
  product #1 is requested far more often than product #1000).
- 15% searches drawn from a fixed set of popular queries (keywords,
  categories, price bands, first few pages), like real users repeating
  common searches.
- 5% admin price/stock updates on popular products, which forces cache
  invalidation while reads are happening.

Run headless inside the api container, e.g.:
  locust -f benchmarks/locustfile.py --headless -u 50 -r 25 -t 60s \
         --host http://localhost:8000 --csv benchmarks/results/cache_on
"""
import itertools
import random

from locust import FastHttpUser, constant, task

HOT_PRODUCT_COUNT = 1000
HOT_PRODUCT_IDS = list(range(1, HOT_PRODUCT_COUNT + 1))
# Zipf weights (s=1): rank r gets weight 1/r. A small head gets most traffic.
HOT_PRODUCT_WEIGHTS = [1 / rank for rank in range(1, HOT_PRODUCT_COUNT + 1)]

KEYWORDS = [None, "wireless", "portable", "lamp", "guitar", "pro", "green", "tent", "watch", "smart"]
CATEGORIES = [None, "electronics", "audio", "books", "outdoors", "furniture", "toys", "shoes"]
PRICE_BANDS = [(None, None), (None, 50), (50, 200), (200, None)]
PAGES = [1, 1, 1, 2, 3]  # page 1 is by far the most common

SEARCHES = [
    {"q": q, "category": c, "min_price": lo, "max_price": hi}
    for q, c, (lo, hi) in itertools.product(KEYWORDS, CATEGORIES, PRICE_BANDS)
]


def pick_hot_product() -> int:
    return random.choices(HOT_PRODUCT_IDS, weights=HOT_PRODUCT_WEIGHTS, k=1)[0]


class Shopper(FastHttpUser):
    # No think time: each simulated user fires requests back to back, so
    # requests/sec shows the server's capacity under a fixed concurrency.
    wait_time = constant(0)

    def on_start(self) -> None:
        response = self.client.post("/auth/token", json={"username": "admin", "password": "admin123"})
        self.admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    @task(80)
    def view_popular_product(self) -> None:
        self.client.get(f"/products/{pick_hot_product()}", name="/products/[id]")

    @task(15)
    def search(self) -> None:
        params = {k: v for k, v in random.choice(SEARCHES).items() if v is not None}
        params["page"] = random.choice(PAGES)
        self.client.get("/products", params=params, name="/products?search")

    @task(5)
    def admin_update(self) -> None:
        body = {"price": f"{random.uniform(5, 500):.2f}", "stock": random.randint(0, 500)}
        self.client.patch(
            f"/admin/products/{pick_hot_product()}", json=body, headers=self.admin_headers,
            name="/admin/products/[id]",
        )
