"""
Product category helpers — for grouping/sorting the cart and staples by the
PLUS category breadcrumb captured in the catalogue cache.

Categories are stored as an ordered list (broad → specific). The top-level entry
is the natural grouping key; products without a known category fall under
``OVERIG`` so nothing silently disappears from a grouped view.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

OVERIG = "Overig"  # bucket for products with no known category


def parse_categories(raw: str | None) -> list[str]:
    """Decode a categories_json column into an ordered list of names."""
    try:
        value = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in value] if isinstance(value, list) else []


def top_category(cats: list[str]) -> str:
    """The broadest (grouping) category, or OVERIG when none is known."""
    return cats[0] if cats else OVERIG


async def get_category_index(
    store_number: int, user_id: int, skus: list[str]
) -> dict[str, list[str]]:
    """Map ``sku → category breadcrumb`` from the catalogue, then purchase history.

    Cache-only (no PLUS call) so it is safe on the open path. Returns an empty
    dict when the store is unknown or nothing is cached.
    """
    skus = [s for s in skus if s]
    if not store_number or not skus:
        return {}

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            catalogue = await repo.get_product_cache_by_skus(db, store_number, skus)
            purchased = await repo.get_purchased_products_by_skus(db, user_id, skus)
    except Exception as exc:
        log.debug("category index load failed: %s", exc)
        return {}

    index: dict[str, list[str]] = {}
    for sku in skus:
        cats = parse_categories(getattr(catalogue.get(sku), "categories_json", None))
        if not cats and purchased.get(sku):
            cats = parse_categories(purchased[sku].categories_json)
        if cats:
            index[sku] = cats
    return index


async def get_category_order_map() -> dict[str, float]:
    """PLUS's own top-level category order, ``{name: sort_order}``.

    Cache-only (no PLUS call) so it is safe on the open path. Returns an empty
    dict when the sync job hasn't run yet.
    """
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            row = await repo.get_menu_category_order_cache(db)
    except Exception as exc:
        log.debug("category order map load failed: %s", exc)
        return {}
    if not row:
        return {}
    try:
        entries = json.loads(row.payload_json)
    except (ValueError, TypeError):
        return {}
    return {e["name"]: e["sort_order"] for e in entries if e.get("name")}


def group_order(categories: list[str], order_map: dict[str, float] | None = None) -> list[str]:
    """Stable display order for category headers.

    Without ``order_map``: alphabetical, OVERIG last (existing behaviour). With
    ``order_map`` (PLUS's own order): known categories sort by SortOrder;
    categories missing from the map (stale/empty cache, or an unmatched name)
    fall back to alphabetical, placed after all known ones. OVERIG always last.
    """
    uniq = {c for c in categories if c and c != OVERIG}
    if not order_map:
        ordered = sorted(uniq, key=str.casefold)
    else:
        known = sorted((c for c in uniq if c in order_map), key=lambda c: order_map[c])
        unknown = sorted((c for c in uniq if c not in order_map), key=str.casefold)
        ordered = known + unknown
    if OVERIG in categories:
        ordered.append(OVERIG)
    return ordered
