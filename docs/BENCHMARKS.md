# Warpcart benchmarks

All numbers were measured on one machine: Windows 11, Docker Desktop
(16 vCPU, 8 GB RAM given to the Linux VM), everything in Docker Compose.
The API runs 4 uvicorn workers. Locust runs inside the API container, so it
shares CPU with the server; the setup is identical for every run, which makes
the runs comparable with each other (not with production hardware).

<!-- CACHE_RESULTS_START -->
## Headline: cache off vs cache on

Locust, 50 concurrent users with zero think time, 60 s per run, starting from
an **empty** Redis each time (`FLUSHDB`), so warm-up misses are included.
Traffic: 80% product detail on popular products (Zipf over the top 1,000),
15% search, 5% admin price/stock updates. Both runs use the same build; only
`CACHE_ENABLED` changes. Reproduce with `sh backend/benchmarks/run_all.sh`.

| Run | p50 | p95 | p99 | req/s | Hit ratio |
|---|---|---|---|---|---|
| Cache off | 65 ms | 160 ms | 240 ms | 778 | n/a |
| **Cache on** | **35 ms** | **120 ms** | **160 ms** | **1,184** (+52%) | **80.1%** |
| Cache on, no admin writes (supplementary) | 24 ms | 44 ms | 63 ms | 2,406 | 98.6% |

Per endpoint:

| Run | Endpoint | Requests | p50 | p95 | p99 | req/s | Hit ratio |
|---|---|---|---|---|---|---|---|
| cache off | GET /products/[id] | 36,825 | 64 ms | 150 ms | 220 ms | 623 | n/a |
| cache off | GET /products?search | 6,836 | 89 ms | 210 ms | 300 ms | 116 | n/a |
| cache off | PATCH /admin/products/[id] | 2,296 | 25 ms | 170 ms | 250 ms | 39 | n/a |
| cache on | GET /products/[id] | 55,860 | 31 ms | 73 ms | 110 ms | 945 | 92.6% |
| cache on | GET /products?search | 10,579 | 68 ms | 160 ms | 200 ms | 179 | 14.2% |
| cache on | PATCH /admin/products/[id] | 3,550 | 65 ms | 120 ms | 140 ms | 60 | n/a |
| cache on, no writes | GET /products/[id] | 119,679 | 24 ms | 38 ms | 48 ms | 2,025 | 99.2% |
| cache on, no writes | GET /products?search | 22,460 | 35 ms | 56 ms | 100 ms | 380 | 95.4% |

Raw CSVs: [`cache_off`](../backend/benchmarks/results/cache_off_stats.csv),
[`cache_on`](../backend/benchmarks/results/cache_on_stats.csv),
[`cache_on_readonly`](../backend/benchmarks/results/cache_on_readonly_stats.csv).

### Reading the numbers honestly

- **Product detail is the big win:** 92.6% hits, p50 halves (64 → 31 ms), p99
  halves (220 → 110 ms). Zipf traffic means a small hot set gets most reads,
  which is exactly what cache-aside is good at.
- **Search hit ratio is only 14% with writes on, and that is invalidation
  working as designed.** 5% writes means ~60 updates per second spread over the
  hot products, which sit in every category. Each update bumps its category's
  search version and the `all` version, so practically every search key is
  orphaned within a second. With writes off, search hit ratio is 95.4%. The
  lesson: invalidation granularity has to match the write rate. A real
  catalog gets far fewer than 60 price changes per second; if it did, we
  would invalidate less precisely (TTL only for search, or version per
  price band) and accept a few seconds of staleness. See DECISIONS.md.
- **Admin writes got slower at p50 (25 → 65 ms)** but faster at p95/p99. With
  the cache on, the server handles 52% more total requests on the same CPUs,
  and each write now also does a MULTI/EXEC to Redis. The tail improves
  because the database is less busy.
- **Why "only" +52% throughput:** the API is CPU-bound in Python. A hit still
  costs a Redis GET, a metrics pipeline, JSON parsing and a response. Search
  misses (most searches, see above) cost far more CPU than hits and dominate.
  The read-only run (+209% vs cache off) shows the ceiling when invalidation
  is not fighting the cache.

### Measurement caveats

- Locust runs inside the API container and shares its CPUs. We tested 4
  Locust processes; they *lowered* API throughput by stealing CPU, so we use 1.
- The host is a Windows laptop running Docker Desktop. Absolute numbers moved
  by up to 2x between sessions depending on background load (we saw the same
  uncached code do 400 and 780 req/s on different occasions). **Only compare
  numbers from the same session**; all rows in the tables above come from
  back-to-back runs.

## Stampede test

Script: [`benchmarks/stampede.py`](../backend/benchmarks/stampede.py).
Warm product 1, delete its key (the TTL "expires"), fire **500 concurrent**
requests at the API (4 worker processes), then count how often the
product-detail SQL ran using Postgres's own `pg_stat_statements`, so the count
comes from the database, not from our code.

| Strategy | DB queries for 500 requests | Responses |
|---|---|---|
| `lock` (default) | **1** | 1 MISS, 499 HIT, all 200 |
| `none` | 32 | 32 MISS, 468 HIT |
| `xfetch` | 79 | 79 MISS, 421 HIT |

`xfetch` refreshes a key *before* it expires; when the key is already gone
it behaves like `none`. That is why `lock` is the default. Full output:
[`results/stampede.txt`](../backend/benchmarks/results/stampede.txt). The
same property is asserted in `tests/test_stampede.py` (exactly 1 loader call
for 500 concurrent requests).
<!-- CACHE_RESULTS_END -->

## 1. Indexing: EXPLAIN ANALYZE before and after

Data set: 500,000 products in 30 categories (seeded with `scripts/seed.py`).
Queries are shaped exactly like the SQL `app/repository.py` generates
(`ORDER BY id LIMIT page_size + 1`). The query file is
[`backend/benchmarks/explain_queries.sql`](../backend/benchmarks/explain_queries.sql).
Full plans: [before](explain/before_indexes.txt), [after](explain/after_indexes.txt).

"Before" = migration `0001` (primary keys and unique constraints only).
"After" = migration `0002`, which adds:

| Index | Type | Serves |
|---|---|---|
| `ix_products_name_trgm` | GIN, `gin_trgm_ops` (pg_trgm) | `name ILIKE '%keyword%'` (leading wildcard, so a B-tree cannot help) |
| `ix_products_category_price` | B-tree `(category_id, price)` | category filter + price range, and the FK join |
| `ix_products_price` | B-tree `(price)` | price range without a category |

| Query | Before: plan | Before | After: plan | After | Speed-up |
|---|---|---|---|---|---|
| Q1 keyword `%green sneakers%` (356 matches) | Parallel PK index walk, filter removes 434k rows | 160.4 ms | Bitmap scan on trigram GIN | 11.6 ms | ~14x |
| Q2 category `cameras` + price 2000..2100 | Parallel seq scan | 28.7 ms | Bitmap scan on `(category_id, price)` | 1.5 ms | ~19x |
| Q3 rare price range 2400..2500, no category | PK index walk + filter | 2.8 ms | PK index walk + filter (planner keeps it) | 3.4 ms | none |
| Q4 keyword `rugged` + `outdoors` + price 10..60 | Parallel seq scan | 129.1 ms | BitmapAnd of trigram GIN and `(category_id, price)` | 7.1 ms | ~18x |
| Q5 product detail by id | PK index scan | 0.08 ms | PK index scan | 0.14 ms | already optimal |

What this shows:

- Leading-wildcard `ILIKE` is the expensive read. Without pg_trgm Postgres has
  to look at every row; with it, it looks at a few hundred candidates.
- Q4 is the nicest plan: Postgres combines two different indexes with a
  `BitmapAnd`, so it only visits rows that match both the keyword and the
  category/price filter.
- Q3 did not improve, and that is fine. With `ORDER BY id LIMIT 21`, walking
  the primary key and stopping after 21 matches is already cheap when matches
  are spread evenly. The planner correctly ignored `ix_products_price`.
- Product detail is a primary-key lookup and is already ~0.1 ms inside
  Postgres. So for detail pages, a cache does not save "query time"; it saves
  everything around the query: the network round trip, pool checkout, ORM
  row mapping and Pydantic validation. The load test below measures that.

## 2. Baseline load test (no cache code at all, phase 2)

Locust, 50 concurrent users with zero think time, 60 s, traffic mix 80%
product detail on popular products (Zipf), 15% search, 5% admin updates
([`locustfile.py`](../backend/benchmarks/locustfile.py)).
Raw CSV: [`phase2_baseline_stats.csv`](../backend/benchmarks/results/phase2_baseline_stats.csv).

| Endpoint | Requests | p50 | p95 | p99 | req/s |
|---|---|---|---|---|---|
| GET /products/[id] | 36,778 | 50 ms | 92 ms | 130 ms | 618 |
| GET /products?search | 6,846 | 85 ms | 150 ms | 280 ms | 115 |
| PATCH /admin/products/[id] | 2,320 | 100 ms | 180 ms | 230 ms | 39 |
| **All** | 45,994 | **54 ms** | **120 ms** | **180 ms** | **773** |

Even a 0.1 ms primary-key query shows up as a 50 ms median under load: the
server is CPU-bound on per-request Python work (SQLAlchemy, Pydantic,
connection pool), and requests queue behind each other. That is exactly the
work a cache hit skips.
