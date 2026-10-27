"""Public read endpoints: categories, search, product detail.

Every response carries an `X-Cache` header (HIT, MISS or BYPASS) so you can
watch the cache work from curl or the browser dev tools.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.cache.aside import CacheResult
from app.deps import get_search_params
from app.schemas import CategoryOut, ProductDetail, SearchParams, SearchResponse
from app.services import CatalogService

router = APIRouter(tags=["catalog"])


def get_catalog(request: Request) -> CatalogService:
    return request.app.state.catalog


def cached_json(result: CacheResult) -> JSONResponse:
    # The cached value is already plain JSON data, so we skip re-validating it
    # through Pydantic on every hit (that would waste the CPU the cache saved).
    return JSONResponse(content=result.value, headers={"X-Cache": result.status})


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(catalog: CatalogService = Depends(get_catalog)):
    return cached_json(await catalog.categories())


@router.get("/products", response_model=SearchResponse)
async def search_products(
    params: SearchParams = Depends(get_search_params), catalog: CatalogService = Depends(get_catalog)
):
    return cached_json(await catalog.search(params))


@router.get("/products/{product_id}", response_model=ProductDetail)
async def get_product(product_id: int, catalog: CatalogService = Depends(get_catalog)):
    result = await catalog.product_detail(product_id)
    if result.value is None:
        raise HTTPException(status_code=404, detail="product not found", headers={"X-Cache": result.status})
    return cached_json(result)
