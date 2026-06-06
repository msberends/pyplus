"""
Promotion lookup by SKU — for surfacing "this item is on offer" in the cart and
staples lanes.

Reads only from the promotions_cache (the same cache the deals lane warms), so it
is safe on the open path — it never calls PLUS. Only single-product promotions
carry a SKU in the cache; group-deal children are fetched lazily on expand and are
deliberately not matched here (matching them would require live PLUS calls).
"""

from __future__ import annotations

import datetime
import json
import logging

from plus.models import Promotion, PromotionProduct

log = logging.getLogger(__name__)


def _current_week_start() -> datetime.date:
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


async def _load_payload(store_number: int, week_start: datetime.date | None) -> dict | None:
    """Load + parse this week's cached promotions payload (cache-only). None on miss."""
    if not store_number:
        return None
    week_start = week_start or _current_week_start()

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            row = await repo.get_promotions_cache(db, store_number, week_start, False)
    except Exception as exc:
        log.debug("promo cache load failed: %s", exc)
        return None
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)
    except Exception as exc:
        log.debug("promo cache parse failed: %s", exc)
        return None


async def get_promo_index(
    store_number: int, week_start: datetime.date | None = None
) -> dict[str, Promotion]:
    """Map ``sku → Promotion`` for this week's promotions, including group-deal children.

    Single-product deals carry their own SKU; group-deal children are resolved by the
    ``refresh_promotions`` job and stored under ``children`` (slug → child products).
    Both are folded into one index so the cart's on-offer hint lights up for any SKU
    that participates in a deal. Returns an empty dict when the cache is cold.
    """
    data = await _load_payload(store_number, week_start)
    if data is None:
        return {}

    try:
        promos = [Promotion(**p) for p in data["promotions"]]
    except Exception as exc:
        log.debug("promo index parse failed: %s", exc)
        return {}

    index: dict[str, Promotion] = {}
    # Group-deal children first; single-product entries override them (more specific).
    by_slug = {p.slug: p for p in promos if p.slug}
    for slug, prods in (data.get("children") or {}).items():
        parent = by_slug.get(slug)
        if parent is None or parent.is_free_delivery:
            continue
        for prod in prods:
            sku = prod.get("sku") if isinstance(prod, dict) else None
            if sku:
                index[sku] = parent
    for p in promos:
        if p.is_single_product and p.sku and not p.is_free_delivery:
            index[p.sku] = p
    return index


async def get_promo_children(
    store_number: int, week_start: datetime.date | None = None
) -> dict[str, list[PromotionProduct]]:
    """Map ``slug → cached child products`` for this week's group deals (cache-only).

    Lets the deals lane open "Bekijken" instantly from cache instead of a live PLUS
    call. Returns an empty dict when the cache is cold or predates child caching.
    """
    data = await _load_payload(store_number, week_start)
    if data is None:
        return {}
    out: dict[str, list[PromotionProduct]] = {}
    for slug, prods in (data.get("children") or {}).items():
        items: list[PromotionProduct] = []
        for p in prods:
            try:
                items.append(PromotionProduct(**p))
            except Exception:
                continue
        if items:
            out[slug] = items
    return out


async def get_free_delivery_info(
    store_number: int, week_start: datetime.date | None = None
) -> tuple[str, float] | None:
    """Return ``(sku, threshold)`` for this week's free delivery offer, or None.

    The threshold is parsed from the subtitle when it contains a '€' amount;
    falls back to 9.0 (PLUS.nl default).
    """
    data = await _load_payload(store_number, week_start)
    if data is None:
        return None
    try:
        promos = [Promotion(**p) for p in data["promotions"]]
    except Exception:
        return None
    for p in promos:
        if p.is_free_delivery and p.sku:
            threshold = 9.0
            if p.subtitle:
                import re

                m = re.search(r"€\s*(\d+(?:[.,]\d+)?)", p.subtitle)
                if m:
                    threshold = float(m.group(1).replace(",", "."))
            return p.sku, threshold
    return None


def promo_tag_label(promo: Promotion) -> str:
    """The short deal-type label to show on a tag, e.g. ``1+1 GRATIS``."""
    return (promo.label or "Aanbieding").strip()
