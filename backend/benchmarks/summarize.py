"""Turn a Locust CSV run + the API's cache metrics into Markdown table rows.

Usage (inside the api container, after a locust run):
  python -m benchmarks.summarize benchmarks/results/cache_on "cache on"
  python -m benchmarks.summarize --reset   # clear metrics before the next run
"""
import csv
import json
import os
import sys
import urllib.request

import redis

from app.cache.metrics import ENDPOINTS, metrics_key

API_URL = os.getenv("BENCH_API_URL", "http://localhost:8000")
ROW_NAMES = {"/products/[id]": "product_detail", "/products?search": "search"}


def reset_metrics() -> None:
    client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    client.delete(*[metrics_key(e) for e in ENDPOINTS])


def fetch_hit_ratios() -> dict[str, float | None]:
    with urllib.request.urlopen(f"{API_URL}/metrics/cache") as response:
        body = json.load(response)
    ratios = {e["endpoint"]: e["hit_ratio"] for e in body["endpoints"]}
    hits = sum(e["hits"] for e in body["endpoints"])
    lookups = hits + sum(e["misses"] for e in body["endpoints"])
    ratios["Aggregated"] = hits / lookups if lookups else None
    return ratios


def fmt_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def summarize(prefix: str, label: str) -> None:
    ratios = fetch_hit_ratios()
    with open(f"{prefix}_stats.csv", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["Name"]
            ratio = ratios.get(ROW_NAMES.get(name, name))
            print(
                f"| {label} | {name} | {int(row['Request Count']):,} | {row['50%']} ms | {row['95%']} ms | "
                f"{row['99%']} ms | {float(row['Requests/s']):.0f} | {fmt_ratio(ratio)} |"
            )


if __name__ == "__main__":
    if sys.argv[1:] == ["--reset"]:
        reset_metrics()
    else:
        summarize(sys.argv[1], sys.argv[2])
