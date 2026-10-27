# Decisions

Every important choice in Warpcart, the alternatives, and why we picked what we picked.

## Data and seeding

### Seed with COPY and pre-built Faker pools
- **Chosen:** call Faker once to build small pools (brands, colours, sentences), combine them with `random`, and load with asyncpg `copy_records_to_table` in 50k-row batches.
- **Alternatives:** one Faker call per field per row; SQLAlchemy `insert().values([...])`; `executemany`.
- **Why:** Faker per row would take many minutes for 500k rows. COPY is the fastest bulk path into Postgres. Batches keep memory flat.

### Idempotent seed: "exact count or reload"
- **Chosen:** if the table already holds exactly the target count, skip; if it holds a partial load, TRUNCATE and reload. Fixed random seed, so data is identical across runs.
- **Alternatives:** `ON CONFLICT DO NOTHING` per product; a "seeded" flag table.
- **Why:** an interrupted COPY leaves a partial table; reloading is simpler and safer than patching gaps. A fixed seed makes benchmarks reproducible.

### Money is `Numeric(10,2)` and serialised as a string
- **Why:** floats cannot represent `19.99` exactly. Returning `"19.99"` keeps JSON clients from silently rounding.

## Baseline API and indexes

### `ORDER BY id LIMIT page_size + 1` instead of `COUNT(*)`
- **Chosen:** fetch one extra row to know if another page exists.
- **Alternative:** total count for page numbers.
- **Why:** infinite scroll only needs "is there more?". Counting all matches of a keyword over 500k rows can cost more than the page itself.

### pg_trgm GIN index for keyword search
- **Chosen:** `gin (name gin_trgm_ops)` serving `name ILIKE '%keyword%'`.
- **Alternatives:** Postgres full-text search (`tsvector`); Elasticsearch; B-tree on `lower(name)`.
- **Why:** users type fragments ("wirel"), and leading-wildcard LIKE cannot use a B-tree. Full-text search matches whole words/stems, not substrings. Elasticsearch is a whole extra system and out of scope. Measured result: 160 ms → 12 ms (see BENCHMARKS.md).

### `(category_id, price)` and `(price)` B-trees
- **Why:** the two common filters. The composite index also serves the FK join and lets Postgres `BitmapAnd` it with the trigram index.

### Offset pagination capped at page 500
- **Alternative:** keyset (cursor) pagination.
- **Why:** offsets keep the cache key simple (`page=3`) and the spec asks for pagination, not huge deep scrolling. The cap stops someone asking for page 1,000,000 (an expensive OFFSET).

## Caching

### Cache-aside (lazy loading), not read-through or write-through
- **Chosen:** the app checks Redis, and on a miss loads from Postgres and writes to Redis (`app/cache/aside.py`).
- **Alternatives:** read-through (the cache loads data itself), write-through (every write also writes the cache), refresh-ahead.
- **Why:** cache-aside only caches what is actually read (500k products, but traffic hits a small hot set), works with plain Redis, and the app keeps working if Redis disappears. Write-through would fill Redis with products nobody reads.

### Cache the JSON response, not ORM objects
- **Chosen:** store the exact JSON payload (`model_dump(mode="json")`) and return it with `JSONResponse` without re-validating.
- **Why:** the load test showed the server is CPU-bound on per-request Python work (ORM mapping, Pydantic). A hit should skip all of that, not just the SQL.

### Deterministic, hashed search keys
- **Chosen:** normalise params (lower-case, collapsed spaces, prices as `10.00`, defaults filled in), dump as sorted JSON, sha256, keep 32 hex chars: `wc:v1:search:<hash>`.
- **Alternatives:** raw query string as the key; key built from raw values joined with colons.
- **Why:** `?q=Lamp&page=1` and `?page=1&q=lamp` are the same search and must share one entry, otherwise the hit ratio collapses. Hashing gives fixed-length keys and stops user input (colons, spaces, unicode) from changing the key structure. 128 bits of hash makes collisions practically impossible.

### `wc:v1:` prefix with a schema version
- **Why:** if the shape of cached JSON changes in a deploy, bumping `v1` → `v2` makes the new code ignore old entries instead of crashing on them. Old keys expire by TTL.

### TTL strategy (one TTL per data type)

| Data | TTL | Why |
|---|---|---|
| Product detail | 300 s | Changes rarely, and every admin write invalidates it explicitly, so the TTL is only a safety net for writes that bypass the API (e.g. a manual SQL fix). Five minutes bounds that staleness. |
| Search results | 60 s | Many keys (every combination of filters and pages), each reads many products, and price changes affect ordering/filters. Short TTL keeps memory down and bounds staleness for results that category invalidation does not catch (e.g. a page boundary shifting). |
| Categories | 3600 s | 30 rows that never change at runtime (no endpoint edits them). Long TTL, near-100% hit ratio. |
| Not found (`null`) | 30 s | Caching misses stops repeated requests for non-existent ids hammering Postgres (cache penetration). Kept short so a newly created product shows up quickly. |

All TTLs get **±10% random jitter** so keys written together in a burst do not all expire in the same second (synchronised expiry is a stampede waiting to happen).

### Cache "not found" with a wrapper object
- **Chosen:** store `{"value": ...}` so a cached `null` is different from "key absent".
- **Why:** without the wrapper, a cached "not found" and a cache miss look the same, and the DB would be queried every time.

### `X-Cache: HIT | MISS | BYPASS` response header
- **Why:** makes the cache observable from curl/devtools and lets tests assert behaviour without peeking into Redis.

### `CACHE_ENABLED` flag
- **Why:** the benchmarks compare the same build with and without caching. With the flag off, Redis is never called (status `BYPASS`).

## Invalidation

### Delete the product key, version the search keys
- **Chosen:** on update, `DEL wc:v1:product:<id>` and `INCR wc:v1:searchver:<category>` + `INCR wc:v1:searchver:all`, in one MULTI/EXEC. Search keys look like `wc:v1:search:<scope>:<version>:<hash>`.
- **Alternatives:**
  - `KEYS wc:v1:search:*` and delete matches: O(n) and blocks Redis; banned by the spec.
  - `SCAN` + delete: non-blocking but still O(n) per update, and slow with many keys.
  - A Redis SET per category listing its search keys: works, but the set must be maintained on every write and can drift from reality when keys expire.
  - Only rely on TTL: simplest, but users see a wrong price for up to 60 s.
- **Why:** versioning is O(1) per update no matter how many search keys exist. Orphaned old-version keys are never read again and expire by their 60 s TTL, so memory cleans itself.
- **Cost:** one extra Redis `GET` per search to read the version. Cheap (sub-millisecond) compared to a search query.

### Why searches without a category get their own "all" scope
A search with no category filter can contain a product from any category. Bumping the "all" scope on every update keeps those correct. The trade-off is that "all" searches are invalidated more often than category searches; under the benchmark's 5% write rate this is acceptable and is visible in the hit ratio.

### Invalidate after commit, and read the version before loading
- Invalidating before the transaction commits would let a concurrent reader re-cache the old row.
- A search reads its version **before** querying Postgres. If an update lands mid-query, the reader writes under the old version, which is already unreachable. So the classic "stale write after invalidation" race cannot poison search keys.
- The product detail key still has that race in theory (reader loads old row → admin commits and deletes → reader writes old row). The window is a few milliseconds and the 300 s TTL bounds the damage. A fix would be a delayed second delete or a per-product version; we documented it instead of adding complexity (see INTERVIEW.md).

### Redis configuration: no persistence, `volatile-lru`, 256 MB
- **Why:** it is a cache; losing it on restart is fine, and persistence costs I/O. `volatile-lru` only evicts keys with a TTL, so cache entries get evicted under memory pressure but TTL-less bookkeeping keys (like search version counters) never are.

## Testing

### Integration tests run inside the API container against real Postgres and Redis
- **Chosen:** separate `warpcart_test` database (migrated with Alembic, reseeded per test) and Redis DB 15 (flushed per test).
- **Alternatives:** SQLite + fakeredis.
- **Why:** the spec requires real services, and fakes would hide exactly the behaviour we want to prove (pg_trgm, `SET NX PX`, connection errors). Running inside the container avoids Windows/host networking differences.
