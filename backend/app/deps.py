"""FastAPI dependencies shared by routers."""
from decimal import Decimal

from fastapi import HTTPException, Query
from pydantic import ValidationError

from app.schemas import SearchParams


def get_search_params(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    min_price: Decimal | None = Query(default=None),
    max_price: Decimal | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
) -> SearchParams:
    """Collect query-string filters into one validated object."""
    try:
        return SearchParams(
            q=q, category=category, min_price=min_price, max_price=max_price, page=page, page_size=page_size
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False, include_input=False))
