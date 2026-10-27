"""Shared test fixtures.

Integration tests use REAL Postgres and Redis from docker compose, but never
touch the real data:
- Postgres: a separate `warpcart_test` database, migrated with Alembic and
  filled with a small, known set of products before each test.
- Redis: logical DB 15, flushed before each test.
"""
import asyncio
import os
from contextlib import AsyncExitStack
from decimal import Decimal

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.config import Settings
from app.main import create_app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://warpcart:warpcart@localhost:5431/warpcart_test"
)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6371/15")
PLAIN_DSN = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

TEST_CATEGORIES = [(1, "Electronics", "electronics"), (2, "Books", "books"), (3, "Toys", "toys")]


def make_test_products() -> list[tuple]:
    """20 products per category with predictable names and prices."""
    rows = []
    product_id = 1
    for category_id, _, slug in TEST_CATEGORIES:
        for n in range(1, 21):
            name = f"{'Wireless' if n % 2 else 'Classic'} {slug.title()} Item {n}"
            rows.append((product_id, f"T-{product_id:04d}", name, "TestBrand",
                         f"Description of {name}", category_id, Decimal(f"{n * 10}.00"), n, Decimal("4.5")))
            product_id += 1
    return rows


async def _create_test_database() -> None:
    admin_dsn = PLAIN_DSN.rsplit("/", 1)[0] + "/postgres"
    db_name = PLAIN_DSN.rsplit("/", 1)[1]
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Create and migrate the test database once per test session."""
    asyncio.run(_create_test_database())
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
async def seeded_db(migrated_db) -> str:
    """Reset the test data before every test so tests never depend on each other."""
    conn = await asyncpg.connect(PLAIN_DSN)
    try:
        await conn.execute("TRUNCATE products, categories RESTART IDENTITY CASCADE")
        await conn.executemany("INSERT INTO categories (id, name, slug) VALUES ($1, $2, $3)", TEST_CATEGORIES)
        await conn.executemany(
            "INSERT INTO products (id, sku, name, brand, description, category_id, price, stock, rating)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            make_test_products(),
        )
    finally:
        await conn.close()
    return migrated_db


@pytest.fixture
async def redis_client():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


def make_test_settings(**overrides) -> Settings:
    values = {"database_url": TEST_DATABASE_URL, "redis_url": TEST_REDIS_URL,
              "db_pool_size": 5, "db_max_overflow": 50}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def client_factory(seeded_db, redis_client):
    """Build an app (with any settings overrides) and an HTTP client for it."""
    async with AsyncExitStack() as stack:
        async def make(**overrides) -> AsyncClient:
            app = create_app(make_test_settings(**overrides))
            await stack.enter_async_context(LifespanManager(app))
            transport = ASGITransport(app=app)
            return await stack.enter_async_context(AsyncClient(transport=transport, base_url="http://test"))

        yield make


@pytest.fixture
async def client(client_factory) -> AsyncClient:
    return await client_factory()
