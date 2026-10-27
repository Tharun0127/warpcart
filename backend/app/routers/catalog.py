"""Public read endpoints: categories, search, product detail."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.deps import get_search_params, get_session
from app.schemas import CategoryOut, ProductDetail, SearchParams, SearchResponse

router = APIRouter(tags=["catalog"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_session)):
    return await repository.list_categories(session)


@router.get("/products", response_model=SearchResponse)
async def search_products(
    params: SearchParams = Depends(get_search_params), session: AsyncSession = Depends(get_session)
):
    items, has_more = await repository.search_products(session, params)
    return SearchResponse(items=items, page=params.page, page_size=params.page_size, has_more=has_more)


@router.get("/products/{product_id}", response_model=ProductDetail)
async def get_product(product_id: int, session: AsyncSession = Depends(get_session)):
    product = await repository.get_product(session, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product
