"""Unit tests for the seed data generator (no database needed)."""
import random
from datetime import datetime, timezone
from decimal import Decimal

from faker import Faker

from scripts.seed import CATEGORIES, build_pools, make_product

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _generate(count: int) -> list[tuple]:
    rng = random.Random(1)
    Faker.seed(1)
    pools = build_pools(Faker())
    _, _, nouns, prices = CATEGORIES[0]
    return [make_product(rng, pools, i, 1, nouns, prices, NOW) for i in range(1, count + 1)]


def test_there_are_30_categories_with_unique_slugs():
    assert len(CATEGORIES) == 30
    assert len({slug for _, slug, _, _ in CATEGORIES}) == 30


def test_generation_is_deterministic_so_reseeding_gives_identical_data():
    assert _generate(50) == _generate(50)


def test_generated_products_respect_category_price_range():
    low, high = CATEGORIES[0][3]
    for row in _generate(500):
        price = row[5]
        assert isinstance(price, Decimal)
        assert Decimal(low) <= price <= Decimal(high)
        assert row[0].startswith("WC-")
