# Interview questions: caching, answered with Warpcart

Each answer is written the way you would say it out loud, using this project as the example.

---

### 1. What is cache-aside, and why did you pick it?

"Cache-aside means the application is in charge. When a request comes in for product 42, my code first asks Redis for `wc:v1:product:42`. If it's there, I return it and Postgres is never touched. If it's not, I run the SQL query, store the result in Redis with a TTL, and return it. Redis itself knows nothing about my database.

I picked it because it only caches what people actually read. I have 500,000 products, but traffic follows a Zipf curve, so a small hot set gets most of the reads. Write-through would fill Redis with products nobody looks at. And because the app owns the logic, if Redis disappears I can just skip it and go to Postgres. The code is in `app/cache/aside.py`."

### 2. How do you build cache keys for search, where the query string can be written many ways?

"`?q=Lamp&page=1` and `?page=1&q=%20lamp` are the same search, so they must map to the same key, otherwise my hit ratio collapses. In `app/cache/keys.py` I normalise everything first: lower-case, collapse spaces, fill in defaults like page 1, and format prices as `10.00` so `10` and `10.00` match. Then I dump that as JSON with sorted keys and take a sha256 hash.

Hashing gives me a fixed-length key, and user input can never inject a colon or a weird character into the key structure. There are unit tests in `tests/test_keys.py` proving that differently formatted but equivalent searches get the same key, and different searches get different keys."

### 3. How did you choose TTLs?

"Different data changes at different speeds and has a different cost of being stale, so each type gets its own TTL. Product detail is 5 minutes. Writes invalidate it explicitly, so the TTL is just a safety net for changes that bypass the API. Search is 60 seconds because there are thousands of combinations and they go stale in subtle ways. Categories are an hour because nothing in the app changes them. A 'not found' result is cached for 30 seconds to stop people hammering non-existent IDs.

On top of that I add plus or minus 10% random jitter, so keys written together in a burst don't all expire in the same second. The reasoning is in DECISIONS.md under 'TTL strategy'."

### 4. How do you invalidate cached search results when a product changes, without using KEYS?

"This is the trickiest part. When an admin changes product 42's price, I don't know which of thousands of cached searches contain it. KEYS would scan the whole keyspace and block Redis, so it's banned. SCAN doesn't block, but it's still slow.

Instead, every category has a version number in Redis, like `wc:v1:searchver:books`, and the version is part of the search key: `wc:v1:search:books:7:<hash>`. When a book changes, I `INCR` that counter to 8. Every new search now builds a key with 8 in it, so the old version-7 keys are simply never read again, and they expire on their own after 60 seconds. It's one O(1) command no matter how many search keys exist. Searches with no category filter live in an `all` scope that every update bumps."

### 5. What did the benchmarks show about that invalidation design?

"Something I didn't expect at first. Product detail had a 92.6% hit ratio, but search was only 14% with writes on. With writes off, search jumped to 95%. My benchmark sends about 60 admin updates per second across the hot products, and those products are in every category, so every category's version gets bumped about once a second. The cache was correct, it just never got to live long.

The takeaway is that invalidation granularity has to match your write rate. A real catalog doesn't change 60 prices a second. If it did, I'd invalidate search less precisely, maybe rely only on the TTL, and accept a few seconds of staleness."

### 6. Do you invalidate before or after the database write? Why?

"After the commit. If I deleted the cache key first, another request could slip in, read the old row from Postgres because my transaction hasn't committed yet, and put the old value right back into the cache.

There's still a tiny race even after commit: a reader loads the old row, my update commits and deletes the key, and then the reader writes its old value. For search keys the versioning protects me, because the reader reads the version before it queries, so its stale result lands under an old version nobody reads. For the product key, the window is milliseconds and the 5-minute TTL caps the damage. The fix would be a delayed second delete or a per-product version, and I'd mention that as a next step."

### 7. What is a cache stampede?

"Say product 1 is on the homepage and its cache entry expires. In the next few milliseconds, 500 requests come in, all see a miss, and all run the same query against Postgres at once. The database gets hit with 500 identical queries exactly when it is busiest. That's a stampede, also called the thundering herd or dog-piling."

### 8. How did you protect against it?

"With a Redis lock. On a miss, every request tries `SET wc:v1:product:1:lock <random token> NX PX 3000`. NX means only one request can succeed. That one runs the query and fills the cache. The others wait 20 milliseconds, check the cache again, and keep doing that for up to 2 seconds. Usually the value appears after about one query's time, and they return it as a hit.

I proved it with `benchmarks/stampede.py`: delete the hot key, fire 500 concurrent requests at four worker processes, then ask Postgres's `pg_stat_statements` how many times the query ran. Answer: 1. Without the lock it was 32."

### 9. Why the random token and the Lua script when you release the lock?

"Because the lock has a 3-second expiry. Imagine my query takes 4 seconds. My lock expires, another request takes it, and then I finish and run a plain DEL. I'd delete *their* lock. So I store a random token as the value and release with a small Lua script that says 'only delete if the value is still my token'. Lua runs atomically in Redis, so nothing can sneak in between the check and the delete."

### 10. What's the second stampede strategy and when would you use it?

"Probabilistic early expiration, the XFetch algorithm. Each cached entry remembers when it expires and how long it took to compute. On every read, a request rolls a weighted dice: the closer we are to expiry and the slower the query, the more likely it decides to refresh *now*, early. In practice one request refreshes the key a bit before it expires while everyone else still gets hits, so the hot key never really expires.

The catch is it does nothing if the key is already gone, after a restart, an eviction or an invalidation. My benchmark shows that: 79 queries when I deleted the key. So the lock is my default and XFetch is behind `STAMPEDE_STRATEGY=xfetch`. You'd prefer XFetch when you can't afford anyone waiting on a lock and keys mostly expire by TTL."

### 11. What happens if Redis goes down?

"The site keeps working, just slower. Every Redis call goes through one wrapper, `CacheStore`, which turns any Redis error into a `CacheUnavailable` exception. The cache-aside code catches that and calls the database loader directly. The response header says `X-Cache: DEGRADED` and a warning is logged.

There's a test, `tests/test_redis_down.py`, that points the app at a port where nothing listens and checks that detail, search, categories, 404s and even admin updates all still work."

### 12. Isn't falling back to the DB dangerous? What did you add on top?

"Two things. First, short timeouts, one second, because waiting ten seconds for a dead cache is worse than having no cache. Second, a tiny circuit breaker: after three failures in a row, I stop calling Redis for five seconds and go straight to Postgres, so each request doesn't pay the timeout.

I originally opened the breaker after one failure with a 250 millisecond timeout. My own stampede test caught that: under 500 concurrent requests, the event loop was too busy to read one Redis reply in time. That turned the cache off and sent 70 queries to Postgres, which is the exact stampede I was trying to prevent. So the numbers came from a failing test, not a guess. The remaining risk is that all traffic lands on Postgres, and in production I'd add rate limiting for that."

### 13. How do you measure whether the cache is working?

"Three ways. Every response has an `X-Cache` header with HIT, MISS, BYPASS or DEGRADED, so you can see it in curl or dev tools. Every endpoint records hits, misses and total latency in a Redis hash with HINCRBY. I use Redis rather than a Python dict because I run four worker processes and a dict would only see a quarter of the traffic. HINCRBY is atomic, so workers never lose an increment. `GET /metrics/cache` computes the hit ratio and average latency, and the frontend dashboard polls it every two seconds. And then Locust measures end-to-end p50, p95, p99 and throughput with `CACHE_ENABLED` on and off."

### 14. What were the results, and what limited them?

"Cache on versus off: throughput went from 778 to 1,184 requests a second, p50 from 65 to 35 milliseconds, p99 from 240 to 160, and the overall hit ratio was 80%. With no writes it reached 2,406 requests a second.

Two honest caveats. One, the gain is limited because the API is CPU-bound in Python, and search misses cost much more than hits. Two, Locust runs on the same machine. I tried four Locust processes and throughput went *down*, because they stole CPU from the API. I also saw the same uncached code do 400 or 780 requests a second on different days, so I only compare numbers from back-to-back runs."

### 15. You added indexes before caching. Why does that order matter?

"Because a cache shouldn't hide a slow query, it should take load off a fast one. I built the API with no cache first and ran EXPLAIN ANALYZE. Keyword search used `ILIKE '%green sneakers%'`. With a leading wildcard a normal B-tree can't help, so Postgres filtered 434,000 rows in 160 ms. A pg_trgm GIN index brought it to 12 ms. A composite `(category_id, price)` index took category-plus-price filters from 29 ms to 1.5 ms.

If I'd cached first, every miss and every invalidation would still have paid 160 ms, and the stampede problem would be much worse. Product detail was already a 0.1 ms primary-key lookup. So caching it doesn't save database time, it saves everything around the query: the pool checkout, the ORM mapping and the validation. That's why I cache the final JSON and return it without re-validating."
