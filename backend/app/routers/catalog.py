"""Public read endpoints: categories, search, product detail, cache metrics.

Every catalog response carries an `X-Cache` header (HIT, MISS, BYPASS or
DEGRADED) so you can watch the cache work from curl or the browser dev tools.
"""
import time
from collections.abc import Awaitable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.cache.aside import CacheResult
from app.cache.metrics import CacheMetrics
from app.deps import get_search_params
from app.schemas import CacheMetricsOut, CategoryOut, ProductDetail, SearchParams, SearchResponse
from app.services import CatalogService

router = APIRouter(tags=["catalog"])


def get_catalog(request: Request) -> CatalogService:
    return request.app.state.catalog


def get_metrics(request: Request) -> CacheMetrics:
    return request.app.state.metrics


async def measured(endpoint: str, work: Awaitable[CacheResult], metrics: CacheMetrics) -> CacheResult:
    """Run the cache/database work, then record its status and latency."""
    started = time.perf_counter()
    result = await work
    await metrics.record(endpoint, result.status, (time.perf_counter() - started) * 1000)
    return result


def cached_json(result: CacheResult) -> JSONResponse:
    # The cached value is already plain JSON data, so we skip re-validating it
    # through Pydantic on every hit (that would waste the CPU the cache saved).
    return JSONResponse(content=result.value, headers={"X-Cache": result.status})


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    catalog: CatalogService = Depends(get_catalog), metrics: CacheMetrics = Depends(get_metrics)
):
    return cached_json(await measured("categories", catalog.categories(), metrics))


@router.get("/products", response_model=SearchResponse)
async def search_products(
    params: SearchParams = Depends(get_search_params),
    catalog: CatalogService = Depends(get_catalog),
    metrics: CacheMetrics = Depends(get_metrics),
):
    return cached_json(await measured("search", catalog.search(params), metrics))


@router.get("/products/{product_id}", response_model=ProductDetail)
async def get_product(
    product_id: int, catalog: CatalogService = Depends(get_catalog), metrics: CacheMetrics = Depends(get_metrics)
):
    result = await measured("product_detail", catalog.product_detail(product_id), metrics)
    if result.value is None:
        raise HTTPException(status_code=404, detail="product not found", headers={"X-Cache": result.status})
    return cached_json(result)


@router.get("/metrics/cache", response_model=CacheMetricsOut)
async def cache_metrics(request: Request, metrics: CacheMetrics = Depends(get_metrics)):
    settings = request.app.state.settings
    endpoints = await metrics.snapshot()
    return CacheMetricsOut(
        cache_enabled=settings.cache_enabled,
        stampede_strategy=settings.stampede_strategy,
        redis_available=endpoints is not None,
        endpoints=endpoints or [],
    )
