-- Representative read queries, shaped exactly like the SQL that
-- app/repository.py generates. Run before and after migration 0002:
--   docker compose exec -T db psql -U warpcart -f - < backend/benchmarks/explain_queries.sql
\pset pager off
\echo '=== Q1: keyword search, selective phrase (name ILIKE %green sneakers%) ==='
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT p.id, p.sku, p.name, p.brand, p.price, p.stock, p.rating, c.slug, c.name
FROM products p JOIN categories c ON p.category_id = c.id
WHERE p.name ILIKE '%green sneakers%'
ORDER BY p.id LIMIT 21 OFFSET 0;

\echo '=== Q2: category + selective price range (cameras, 2000..2100) ==='
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT p.id, p.sku, p.name, p.brand, p.price, p.stock, p.rating, c.slug, c.name
FROM products p JOIN categories c ON p.category_id = c.id
WHERE c.slug = 'cameras' AND p.price >= 2000 AND p.price <= 2100
ORDER BY p.id LIMIT 21 OFFSET 0;

\echo '=== Q3: rare price range only (2400..2500), no category ==='
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT p.id, p.sku, p.name, p.brand, p.price, p.stock, p.rating, c.slug, c.name
FROM products p JOIN categories c ON p.category_id = c.id
WHERE p.price >= 2400 AND p.price <= 2500
ORDER BY p.id LIMIT 21 OFFSET 0;

\echo '=== Q4: keyword + category + price (rugged, outdoors, 10..60) ==='
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT p.id, p.sku, p.name, p.brand, p.price, p.stock, p.rating, c.slug, c.name
FROM products p JOIN categories c ON p.category_id = c.id
WHERE p.name ILIKE '%rugged%' AND c.slug = 'outdoors' AND p.price >= 10 AND p.price <= 60
ORDER BY p.id LIMIT 21 OFFSET 0;

\echo '=== Q5: product detail by primary key (id = 123456) ==='
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT p.*, c.slug, c.name
FROM products p JOIN categories c ON p.category_id = c.id
WHERE p.id = 123456;
