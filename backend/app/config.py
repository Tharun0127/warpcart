"""All runtime settings, read from environment variables.

Keeping every knob in one place makes it easy to see what can be tuned
(for example turning the cache off for a benchmark run).
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://warpcart:warpcart@localhost:5431/warpcart"
    redis_url: str = "redis://localhost:6371/0"

    # Auth (only the admin endpoint is protected)
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # --- Caching -------------------------------------------------------
    # Master switch so benchmarks can compare "no cache" against "cache".
    cache_enabled: bool = True
    # TTLs per data type. Reasons are in docs/DECISIONS.md ("TTL strategy").
    ttl_product_seconds: int = 300
    ttl_search_seconds: int = 60
    ttl_categories_seconds: int = 3600
    ttl_not_found_seconds: int = 30
    # +/-10% random jitter so keys written together do not all expire together.
    ttl_jitter_ratio: float = 0.1

    # Stampede protection: "lock" (SET NX PX), "xfetch" (probabilistic early
    # expiration) or "none". See app/cache/aside.py and docs/DECISIONS.md.
    stampede_strategy: Literal["lock", "xfetch", "none"] = "lock"
    # Must be longer than the slowest loader, or two requests could rebuild.
    stampede_lock_ttl_ms: int = 3000
    stampede_retry_ms: int = 20
    stampede_max_wait_ms: int = 2000
    # beta > 1 refreshes earlier, beta < 1 later. 1.0 is the paper's default.
    xfetch_beta: float = 1.0

    # Graceful degradation: give up on Redis quickly, then skip it for a while.
    # 1s, not lower: under a burst the event loop itself can delay reading a
    # Redis reply by a few hundred ms, and that must not look like "Redis down".
    redis_timeout_seconds: float = 1.0
    redis_retry_after_seconds: float = 5.0

    # Connection pool per worker process
    db_pool_size: int = 10
    db_max_overflow: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
