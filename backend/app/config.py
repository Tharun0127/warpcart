"""All runtime settings, read from environment variables.

Keeping every knob in one place makes it easy to see what can be tuned
(for example turning the cache off for a benchmark run).
"""
from functools import lru_cache

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

    # Connection pool per worker process
    db_pool_size: int = 10
    db_max_overflow: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
