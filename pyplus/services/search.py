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
    """Resolve a search query to products, preferring the instant local catalogue.

    Order: (1) local product_cache; (2) live PLUS search API on a miss, whose
    results are cached for next time.
    """
    query = (query or "").strip()
    if len(query) < 2:
        return []

    store_number = getattr(session, "store_number", 0) or 0

    cached = await search_catalogue(store_number, query, limit)
    if cached:
        return cached

    # Cold cache / no local hit — go to the live API.
    try:
        live = await session.client.search_products_api(query, store_number)
    except Exception as exc:
        log.warning("Live search fallback failed (q=%r): %s", query, exc)
        return []

    if live and store_number:
        try:
            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                await repo.upsert_product_cache(db, store_number, live)
        except Exception as exc:
            log.debug("Could not cache live search results: %s", exc)

    return live[:limit]
