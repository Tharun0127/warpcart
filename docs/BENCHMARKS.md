# Warpcart benchmarks

All numbers were measured on one machine: Windows 11, Docker Desktop
(16 vCPU, 8 GB RAM given to the Linux VM), everything in Docker Compose.
The API runs 4 uvicorn workers. Locust runs inside the API container, so it
shares CPU with the server; the setup is identical for every run, which makes
the runs comparable with each other (not with production hardware).

<!-- CACHE_RESULTS_START -->
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
