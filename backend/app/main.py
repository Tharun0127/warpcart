"""FastAPI application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.routers import admin, catalog


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="Warpcart", lifespan=lifespan)
    app.include_router(catalog.router)
    app.include_router(admin.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
