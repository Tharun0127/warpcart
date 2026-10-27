"""All SQL lives here. These functions know nothing about caching.

The cache layer calls them as "loaders" on a cache miss, which keeps the two
concerns separate and lets us run with the cache switched off.
"""
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product
from app.schemas import CategoryOut, ProductDetail, ProductSummary, SearchParams

SUMMARY_COLUMNS = (
    Product.id, Product.sku, Product.name, Product.brand, Product.price, Product.stock,
    Product.rating, Category.slug.label("category_slug"), Category.name.label("category_name"),
)


def escape_like(text: str) -> str:
    """Stop user input like '50%' from acting as a LIKE wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_categories(session: AsyncSession) -> list[CategoryOut]:
    rows = await session.execute(select(Category.id, Category.name, Category.slug).order_by(Category.name))
    return [CategoryOut(**row._mapping) for row in rows]


async def get_product(session: AsyncSession, product_id: int) -> ProductDetail | None:
    query = (
        select(*SUMMARY_COLUMNS, Product.description, Product.created_at, Product.updated_at)
        .join(Category, Product.category_id == Category.id)
        .where(Product.id == product_id)
    )
    row = (await session.execute(query)).first()
    return ProductDetail(**row._mapping) if row else None


async def search_products(session: AsyncSession, params: SearchParams) -> tuple[list[ProductSummary], bool]:
    """Return one page of results and whether another page exists.

    We fetch page_size + 1 rows instead of running COUNT(*): counting every
    match of a keyword over 500k rows costs more than the page itself, and
    infinite scroll only needs to know "is there more?".
    """
    query = select(*SUMMARY_COLUMNS).join(Category, Product.category_id == Category.id)
    keyword = (params.q or "").strip()
    if keyword:
        query = query.where(Product.name.ilike(f"%{escape_like(keyword)}%", escape="\\"))
    if params.category:
        query = query.where(Category.slug == params.category.strip().lower())
    if params.min_price is not None:
        query = query.where(Product.price >= params.min_price)
    if params.max_price is not None:
        query = query.where(Product.price <= params.max_price)

    offset = (params.page - 1) * params.page_size
    query = query.order_by(Product.id).offset(offset).limit(params.page_size + 1)
    rows = (await session.execute(query)).all()
    items = [ProductSummary(**row._mapping) for row in rows[: params.page_size]]
    return items, len(rows) > params.page_size


async def update_product(
    session: AsyncSession, product_id: int, price: Decimal | None = None, stock: int | None = None
) -> ProductDetail | None:
    """Update price and/or stock and commit. Returns the fresh product, or None if missing."""
    values: dict = {"updated_at": func.now()}
    if price is not None:
        values["price"] = price
    if stock is not None:
        values["stock"] = stock
    result = await session.execute(update(Product).where(Product.id == product_id).values(**values))
    if result.rowcount == 0:
        await session.rollback()
        return None
    await session.commit()
    return await get_product(session, product_id)
