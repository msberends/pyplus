"""Dish service — business logic layer on top of the DB repo."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plus.models import Product

log = logging.getLogger(__name__)


async def cache_ingredient_sku_from_product(db, user_id: int, product: "Product") -> None:
    """
    Persist product info into ingredient_skus when the user pins a SKU to an ingredient.

    Called immediately after the user picks a search result in the dish editor.
    """
    from pyplus.db import repo

    # Infer pack size from subtitle, e.g. "Per 650 g" → 650 g
    pack_size, pack_unit = _parse_pack_from_subtitle(product.subtitle)

    await repo.upsert_ingredient_sku(
        db,
        user_id,
        product.sku,
        name=product.name,
        subtitle=product.subtitle,
        slug=getattr(product, "slug", "") or "",
        image_url=product.image_url,
        pack_size=pack_size,
        pack_unit=pack_unit,
        last_price=product.price,
        last_seen_available=product.is_available,
    )


def _parse_pack_from_subtitle(subtitle: str) -> tuple[float | None, str | None]:
    """
    Attempt to extract pack size from a subtitle like "Per 650 g" or "Per 1 liter".
    Also handles multi-pack formats like "Per 4 × 330 ml" → (1320, "ml").
    Returns (size, unit) or (None, None) if not parseable.
    """
    import re

    # Multi-pack: "Per 4 × 330 ml", "4 x 330 ml", "4x330ml"
    m = re.search(
        r"(?:per\s+)?(\d+)\s*[×xX]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|liter|cl|stuks?|stuk)",
        subtitle,
        re.IGNORECASE,
    )
    if m:
        count = int(m.group(1))
        size_str = m.group(2).replace(",", ".")
        unit_raw = m.group(3).lower()
        unit_map = {"liter": "l", "stuks": "stuks", "stuk": "stuks"}
        unit = unit_map.get(unit_raw, unit_raw)
        try:
            return count * float(size_str), unit
        except ValueError:
            pass

    # Single: "Per 650 g", "Per 1 liter"
    m = re.search(
        r"(?:per\s+)?(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|liter|cl|stuks?|stuk)",
        subtitle,
        re.IGNORECASE,
    )
    if not m:
        return None, None
    size_str = m.group(1).replace(",", ".")
    unit_raw = m.group(2).lower()
    unit_map = {"liter": "l", "stuks": "stuks", "stuk": "stuks"}
    unit = unit_map.get(unit_raw, unit_raw)
    try:
        return float(size_str), unit
    except ValueError:
        return None, None
