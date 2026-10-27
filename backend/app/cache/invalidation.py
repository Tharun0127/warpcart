"""Cache invalidation after a product changes.

Two things can be stale after an admin update:
1. The product's own detail entry  -> delete that one key.
2. Every cached search that might contain the product. We cannot know which
   search keys those are without scanning Redis (KEYS/SCAN is O(n) and blocks
   or crawls on a big keyspace). Instead each category has a version number
   that is part of its search keys. Bumping it makes all old search keys for
   that category unreachable in one O(1) command.

Searches without a category filter ("all" scope) can include any product, so
every update bumps that scope too.
"""
from app.cache import keys
from app.cache.store import CacheStore


def keys_to_delete(product_id: int) -> list[str]:
    return [keys.product_key(product_id)]


def scopes_to_bump(category_slug: str) -> list[str]:
    return [category_slug, keys.ALL_CATEGORIES_SCOPE]


async def invalidate_product(store: CacheStore, product_id: int, category_slug: str) -> None:
    """Run after the database transaction has committed.

    Doing it after commit matters: if we invalidated first, a reader could
    reload the OLD row from Postgres (not yet committed) and cache it again.
    """
    version_keys = [keys.search_version_key(scope) for scope in scopes_to_bump(category_slug)]
    await store.delete_and_incr(keys_to_delete(product_id), version_keys)
