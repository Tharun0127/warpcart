"""Cache metrics: unit tests for the maths, integration tests for the endpoint."""
from app.cache.metrics import summarize


def test_summary_computes_hit_ratio_and_average_latency():
    raw = {"requests": "10", "HIT": "8", "MISS": "2", "latency_ms_total": "25.0"}
    summary = summarize("search", raw)
    assert summary["hit_ratio"] == 0.8
    assert summary["avg_latency_ms"] == 2.5


def test_bypassed_requests_do_not_count_toward_hit_ratio():
    raw = {"requests": "5", "HIT": "1", "MISS": "1", "BYPASS": "3", "latency_ms_total": "5"}
    assert summarize("search", raw)["hit_ratio"] == 0.5


def test_empty_counters_give_none_instead_of_dividing_by_zero():
    summary = summarize("categories", {})
    assert summary["requests"] == 0
    assert summary["hit_ratio"] is None and summary["avg_latency_ms"] is None


def by_endpoint(body: dict) -> dict:
    return {e["endpoint"]: e for e in body["endpoints"]}


async def test_metrics_endpoint_counts_hits_and_misses(client):
    for _ in range(4):
        await client.get("/products/1")   # 1 miss, 3 hits
    await client.get("/products", params={"q": "classic"})  # 1 miss

    body = (await client.get("/metrics/cache")).json()
    assert body["cache_enabled"] is True and body["redis_available"] is True
    detail = by_endpoint(body)["product_detail"]
    assert (detail["requests"], detail["hits"], detail["misses"]) == (4, 3, 1)
    assert detail["hit_ratio"] == 0.75
    assert detail["avg_latency_ms"] > 0
    assert by_endpoint(body)["search"]["misses"] == 1
    assert by_endpoint(body)["categories"]["requests"] == 0


async def test_metrics_are_shared_across_app_instances(client_factory):
    # Two app instances stand in for two worker processes.
    first, second = await client_factory(), await client_factory()
    await first.get("/products/1")
    await second.get("/products/1")
    detail = by_endpoint((await first.get("/metrics/cache")).json())["product_detail"]
    assert (detail["requests"], detail["hits"], detail["misses"]) == (2, 1, 1)


async def test_metrics_endpoint_reports_redis_down(client_factory):
    client = await client_factory(redis_url="redis://localhost:1/0")
    await client.get("/products/1")
    body = (await client.get("/metrics/cache")).json()
    assert body["redis_available"] is False and body["endpoints"] == []
