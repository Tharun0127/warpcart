"""Cache key building.

Rules every key follows:
- Prefixed with `wc:` (app) and a schema version (`v1`). If the shape of the
  cached JSON ever changes, bumping SCHEMA_VERSION makes the app ignore all
  old entries at once; they simply age out via their TTL.
- Deterministic: the same logical request always produces the same key, no
  matter how the query string was written (order, case, spacing, "10" vs
  "10.00").
"""
import hashlib
import json
from decimal import Decimal

from app.schemas import SearchParams

KEY_PREFIX = "wc"
SCHEMA_VERSION = "v1"


def _key(*parts: object) -> str:
    return ":".join([KEY_PREFIX, SCHEMA_VERSION, *map(str, parts)])


def product_key(product_id: int) -> str:
    return _key("product", product_id)


def lock_key(cache_key: str) -> str:
    """Lock guarding the rebuild of one cache key (stampede protection)."""
    return f"{cache_key}:lock"


def categories_key() -> str:
    return _key("categories")


def _format_price(value: Decimal | None) -> str | None:
    # Decimal("10") and Decimal("10.00") are the same price, so render both as "10.00".
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))


def normalize_search_params(params: SearchParams) -> dict:
    """Turn search params into a canonical dict.

    Text normalisation (lower-case, collapsed spaces) already happened in the
    SearchParams validator, so the SQL query and the key agree. We repeat the
    cheap parts here so this function is safe to call with any SearchParams.
    """
    keyword = " ".join((params.q or "").lower().split()) or None
    category = (params.category or "").strip().lower() or None
    return {
        "q": keyword,
        "category": category,
        "min_price": _format_price(params.min_price),
        "max_price": _format_price(params.max_price),
        "page": params.page,
        "page_size": params.page_size,
    }


def hash_search_params(params: SearchParams) -> str:
    """sha256 of the canonical JSON. sort_keys makes dict order irrelevant.

    We hash instead of putting raw values in the key so keys have a fixed,
    short length and user input (spaces, colons, unicode) never leaks into
    the key structure.
    """
    canonical = json.dumps(normalize_search_params(params), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# Searches with no category filter can contain products from every category,
# so they live in their own scope that every product update bumps.
ALL_CATEGORIES_SCOPE = "all"


def search_scope(params: SearchParams) -> str:
    """Which version counter a search belongs to: its category, or "all"."""
    return normalize_search_params(params)["category"] or ALL_CATEGORIES_SCOPE


def search_version_key(scope: str) -> str:
    return _key("searchver", scope)


def search_key(params: SearchParams, version: int) -> str:
    """Search key that includes the current version of its scope.

    Bumping the version (INCR) changes every future key in that scope, so old
    entries are never read again and simply expire by TTL. That gives us
    "invalidate all searches in category X" in O(1), without KEYS or SCAN.
    """
    return _key("search", search_scope(params), version, hash_search_params(params))
