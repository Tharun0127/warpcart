"""Unit tests for which keys an update invalidates (no Redis needed)."""
from app.cache import invalidation
from app.cache.keys import search_version_key


def test_update_deletes_only_that_products_detail_key():
    assert invalidation.keys_to_delete(42) == ["wc:v1:product:42"]


def test_update_bumps_its_category_and_the_all_scope():
    assert invalidation.scopes_to_bump("books") == ["books", "all"]


def test_version_keys_are_namespaced():
    assert search_version_key("books") == "wc:v1:searchver:books"
