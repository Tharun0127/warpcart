"""FastAPI application factory."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache.aside import CacheAside
from app.cache.metrics import CacheMetrics
from app.cache.store import CacheStore
from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.routers import admin, catalog
from app.services import CatalogService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings)
        session_factory = build_session_factory(engine)
        store = CacheStore.from_url(
            settings.redis_url, settings.redis_timeout_seconds, settings.redis_retry_after_seconds
        )

        app.state.settings = settings
        app.state.store = store
        app.state.metrics = CacheMetrics(store)
        app.state.catalog = CatalogService(session_factory, CacheAside(store, settings), settings)
        yield
        await store.close()
        await engine.dispose()

    app = FastAPI(title="Warpcart", lifespan=lifespan)
    app.include_router(catalog.router)
    app.include_router(admin.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
