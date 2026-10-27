"""Stampede benchmark against the running API (4 worker processes).

1. Warm a hot product's cache key.
2. Delete it from Redis, as if its TTL just ran out.
3. Fire 500 concurrent GET /products/<id> requests.
4. Ask Postgres (pg_stat_statements) how many times the product-detail query
   actually ran.

Run inside the api container:
  python -m benchmarks.stampede                 # uses the API's current STAMPEDE_STRATEGY
  python -m benchmarks.stampede --requests 500 --product-id 1
"""
import argparse
import asyncio
import collections
import os
import time

import asyncpg
import httpx
from redis.asyncio import Redis

from app.cache.keys import product_key

API_URL = os.getenv("BENCH_API_URL", "http://localhost:8000")
PLAIN_DSN = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# The detail query is the only one that filters products by primary key.
DETAIL_QUERY_FILTER = "%FROM products JOIN categories%WHERE products.id = $1%"


async def count_detail_queries(conn: asyncpg.Connection) -> int:
    calls = await conn.fetchval(
        "SELECT COALESCE(SUM(calls), 0) FROM pg_stat_statements WHERE query LIKE $1", DETAIL_QUERY_FILTER
    )
    return int(calls)


async def run(requests: int, product_id: int) -> None:
    conn = await asyncpg.connect(PLAIN_DSN)
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    limits = httpx.Limits(max_connections=requests, max_keepalive_connections=requests)
    async with httpx.AsyncClient(base_url=API_URL, limits=limits, timeout=30) as client:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        await client.get(f"/products/{product_id}")  # warm
        await redis.delete(product_key(product_id))  # "expire" the hot key
        await conn.execute("SELECT pg_stat_statements_reset()")

        started = time.perf_counter()
        responses = await asyncio.gather(*(client.get(f"/products/{product_id}") for _ in range(requests)))
        elapsed = time.perf_counter() - started

        db_queries = await count_detail_queries(conn)
    await conn.close()
    await redis.aclose()

    statuses = collections.Counter(r.status_code for r in responses)
    cache = collections.Counter(r.headers.get("X-Cache") for r in responses)
    # Same container, same env, so this matches what the API is running with.
    print(f"strategy={os.getenv('STAMPEDE_STRATEGY', 'lock')} requests={requests} wall_time={elapsed:.2f}s")
    print(f"http_status={dict(statuses)} x_cache={dict(cache)}")
    print(f"DB_DETAIL_QUERIES={db_queries}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--product-id", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(run(args.requests, args.product_id))


if __name__ == "__main__":
    main()
