"""Request and response shapes."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str


class ProductSummary(BaseModel):
    id: int
    sku: str
    name: str
    brand: str
    # Decimal is serialised as a string ("19.99") so money never goes through float.
    price: Decimal
    stock: int
    rating: Decimal
    category_slug: str
    category_name: str


class ProductDetail(ProductSummary):
    description: str
    created_at: datetime
    updated_at: datetime


class SearchParams(BaseModel):
    q: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=80)
    min_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    max_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("q", "category")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """Lower-case and collapse whitespace.

        Search is case-insensitive (ILIKE), so "  Green   LAMP " and "green lamp"
        mean the same thing. Normalising here means the SQL and the cache key
        both see the same canonical value, so they produce one cache entry.
        """
        if value is None:
            return None
        cleaned = " ".join(value.lower().split())
        return cleaned or None

    @model_validator(mode="after")
    def check_price_range(self) -> "SearchParams":
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price must be <= max_price")
        return self


class SearchResponse(BaseModel):
    items: list[ProductSummary]
    page: int
    page_size: int
    has_more: bool


class ProductUpdate(BaseModel):
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_one_field(self) -> "ProductUpdate":
        if self.price is None and self.stock is None:
            raise ValueError("provide price and/or stock")
        return self


class EndpointMetrics(BaseModel):
    endpoint: str
    requests: int
    hits: int
    misses: int
    bypassed: int
    degraded: int
    hit_ratio: float | None
    avg_latency_ms: float | None


class CacheMetricsOut(BaseModel):
    cache_enabled: bool
    stampede_strategy: str
    redis_available: bool
    endpoints: list[EndpointMetrics]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
