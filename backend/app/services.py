"""Catalog use-cases: glue between the routers, the cache and the database.

Each read method builds a cache key, defines a loader (the DB query to run
on a miss) and hands both to the cache-aside helper.
"""
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker

from app import repository
from app.cache import keys
from app.cache.aside import CacheAside, CacheResult
from app.config import Settings
from app.schemas import SearchParams, SearchResponse


class CatalogService:
    def __init__(self, session_factory: async_sessionmaker, cache: CacheAside, settings: Settings):
        self.session_factory = session_factory
        self.cache = cache
        self.settings = settings

    async def product_detail(self, product_id: int) -> CacheResult:
        async def load() -> dict | None:
            # The session is opened inside the loader, so a cache hit never
            # even checks a connection out of the pool.
            async with self.session_factory() as session:
                product = await repository.get_product(session, product_id)
            return product.model_dump(mode="json") if product else None

        return await self.cache.get_or_load(
            keys.product_key(product_id), load,
            ttl_seconds=self.settings.ttl_product_seconds,
            empty_ttl_seconds=self.settings.ttl_not_found_seconds,
        )

    async def search(self, params: SearchParams) -> CacheResult:
        async def load() -> dict:
            async with self.session_factory() as session:
                items, has_more = await repository.search_products(session, params)
            response = SearchResponse(items=items, page=params.page, page_size=params.page_size, has_more=has_more)
            return response.model_dump(mode="json")

        return await self.cache.get_or_load(
            keys.search_key(params), load, ttl_seconds=self.settings.ttl_search_seconds
        )

    async def categories(self) -> CacheResult:
        async def load() -> list[dict]:
            async with self.session_factory() as session:
                return [c.model_dump() for c in await repository.list_categories(session)]

        return await self.cache.get_or_load(
            keys.categories_key(), load, ttl_seconds=self.settings.ttl_categories_seconds
        )

    async def update_product(self, product_id: int, price: Decimal | None, stock: int | None) -> dict | None:
        async with self.session_factory() as session:
            product = await repository.update_product(session, product_id, price=price, stock=stock)
        return product.model_dump(mode="json") if product else None
