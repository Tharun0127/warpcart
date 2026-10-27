"""Login and the single admin write endpoint."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.auth import check_credentials, create_access_token, require_admin
from app.deps import get_session
from app.schemas import LoginRequest, ProductDetail, ProductUpdate, TokenResponse

router = APIRouter(tags=["admin"])


@router.post("/auth/token", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    settings = request.app.state.settings
    if not check_credentials(settings, body.username, body.password):
        raise HTTPException(status_code=401, detail="bad credentials")
    return TokenResponse(access_token=create_access_token(settings, body.username))


@router.patch("/admin/products/{product_id}", response_model=ProductDetail)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin),
):
    product = await repository.update_product(session, product_id, price=body.price, stock=body.stock)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product
