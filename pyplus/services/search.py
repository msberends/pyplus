"""
Product search — speed-first.

Serves instant results from the locally-synced store catalogue (product_cache,
warmed by the refresh_product_catalogue job via direct PLUS API). Falls back to a
live PLUS API call on a cold/miss and opportunistically caches what it gets back,
so the catalogue self-heals for products the bulk sync didn't cover.

Never scrapes HTML — every product originates from a JSON API response.
"""

from __future__ import annotations

import logging

from plus.models import Product

log = logging.getLogger(__name__)


def _row_to_product(row, store_number: int) -> Product:
    import json

    try:
        categories = json.loads(getattr(row, "categories_json", "") or "[]")
        if not isinstance(categories, list):
            categories = []
    except (ValueError, TypeError):
        categories = []
    return Product(
        sku=row.sku,
        name=row.name,
        subtitle=row.subtitle or "",
        brand=row.brand or "",
        slug=row.slug or "",
        image_url=row.image_url or "",
        price=row.price or 0.0,
        is_available=bool(row.is_available),
        store_number=store_number,
        categories=categories,
    )


async def search_catalogue(store_number: int, query: str, limit: int = 24) -> list[Product]:
    """Search the local catalogue only (no network). Empty when the cache is cold."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    if not store_number:
        return []
    async with AsyncSessionLocal() as db:
        rows = await repo.search_product_cache(db, store_number, query, limit)
    return [_row_to_product(r, store_number) for r in rows]


async def search_products(session, query: str, limit: int = 24) -> list[Product]:
    """Search the local product catalogue. No live API calls — the catalogue is
    kept fresh by the nightly sync job."""
    query = (query or "").strip()
    if len(query) < 2:
        return []

    store_number = getattr(session, "store_number", 0) or 0
    return await search_catalogue(store_number, query, limit)
