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

from plus.models import Promotion

log = logging.getLogger(__name__)


def _current_week_start() -> datetime.date:
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


async def get_promo_index(
    store_number: int, week_start: datetime.date | None = None
) -> dict[str, Promotion]:
    """Map ``sku → Promotion`` for this week's single-product promotions.

    Returns an empty dict when the cache is cold or the store is unknown.
    """
    if not store_number:
        return {}
    week_start = week_start or _current_week_start()

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            row = await repo.get_promotions_cache(db, store_number, week_start, False)
    except Exception as exc:
        log.debug("promo index load failed: %s", exc)
        return {}

    if row is None:
        return {}

    try:
        data = json.loads(row.payload_json)
        promos = [Promotion(**p) for p in data["promotions"]]
    except Exception as exc:
        log.debug("promo index parse failed: %s", exc)
        return {}

    index: dict[str, Promotion] = {}
    for p in promos:
        if p.is_single_product and p.sku and not p.is_free_delivery:
            index[p.sku] = p
    return index


def promo_tag_label(promo: Promotion) -> str:
    """The short deal-type label to show on a tag, e.g. ``1+1 GRATIS``."""
    return (promo.label or "Aanbieding").strip()
