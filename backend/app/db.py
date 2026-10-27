"""Database engine and session factory.

The engine is created per application instance (not at import time) so tests
can build an app pointed at a separate test database.
"""
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    # expire_on_commit=False: we read attributes after commit in the admin endpoint.
    return async_sessionmaker(engine, expire_on_commit=False)
