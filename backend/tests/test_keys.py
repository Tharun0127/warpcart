"""Unit tests for cache key generation and TTL jitter (no Redis needed)."""
import random
from decimal import Decimal

from app.cache.aside import ttl_with_jitter
from app.cache.keys import hash_search_params, product_key, search_key
from app.schemas import SearchParams


def test_product_key_is_namespaced_and_versioned():
    assert product_key(42) == "wc:v1:product:42"


def test_same_logical_search_gives_same_key_regardless_of_formatting():
    a = SearchParams(q="  Green   LAMP ", category="Furniture", min_price="10", max_price=Decimal("99.5"))
    b = SearchParams(q="green lamp", category="furniture", min_price=Decimal("10.00"), max_price="99.50")
    assert hash_search_params(a) == hash_search_params(b)


def test_default_page_equals_explicit_page_one():
    assert hash_search_params(SearchParams(q="tent")) == hash_search_params(SearchParams(q="tent", page=1, page_size=20))


def test_empty_keyword_is_same_as_no_keyword():
    assert hash_search_params(SearchParams(q="   ")) == hash_search_params(SearchParams())


def test_different_searches_give_different_keys():
    base = SearchParams(q="tent", category="outdoors", min_price="10", max_price="50", page=1)
    variants = [
        base.model_copy(update={"q": "tents"}),
        base.model_copy(update={"category": "sports"}),
        base.model_copy(update={"min_price": Decimal("11")}),
        base.model_copy(update={"max_price": None}),
        base.model_copy(update={"page": 2}),
        base.model_copy(update={"page_size": 50}),
    ]
    hashes = {hash_search_params(v) for v in variants} | {hash_search_params(base)}
    assert len(hashes) == len(variants) + 1


def test_min_and_max_price_are_not_interchangeable():
    assert hash_search_params(SearchParams(min_price="10")) != hash_search_params(SearchParams(max_price="10"))


def test_key_has_fixed_length_whatever_the_input():
    long_query = SearchParams(q="x" * 80 +" : * ? ünïcødé")
    assert len(hash_search_params(long_query)) == 32
    assert ":" not in hash_search_params(long_query)


def test_search_key_is_deterministic_across_calls():
    params = SearchParams(q="watch", page=3)
    assert search_key(params) == search_key(params)


def test_ttl_jitter_stays_within_ratio_and_varies():
    rng = random.Random(0)
    ttls = [ttl_with_jitter(300, 0.1, rng) for _ in range(1000)]
    assert min(ttls) >= 270 and max(ttls) <= 330
    assert len(set(ttls)) > 20  # actually spread out, not all identical


def test_ttl_jitter_never_returns_zero():
    assert ttl_with_jitter(1, 0.9, random.Random(1)) >= 1
