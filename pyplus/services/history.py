"""
Purchase history service — builds PurchaseRecord objects from DB caches.

Reads ONLY from local DB caches (purchased_products_cache and order_* tables).
Never calls the PLUS API directly — that's the job of refresh_purchase_catalogue
and refresh_orders (M10 jobs).

If caches are cold (empty), returns [] — the ML layer handles cold-start.
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict

from sqlalchemy import select

from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import OrderCache, OrderItemCache, PurchasedProductCache
from pyplus.ml.interface import PurchaseRecord

log = logging.getLogger(__name__)


async def build_purchase_history(user_id: int) -> list[PurchaseRecord]:
    """
    Fuse purchase-history catalogue (breadth) + order history (cadence).

    Returns a PurchaseRecord per unique SKU ever bought by this user.
    """
    async with AsyncSessionLocal() as db:
        # ── Breadth signal: all products ever bought (online + in-store) ──
        cat_result = await db.execute(
            select(PurchasedProductCache).where(PurchasedProductCache.user_id == user_id)
        )
        catalogue = list(cat_result.scalars().all())

        # ── Cadence signal: dated online orders ───────────────────────────
        items_result = await db.execute(
            select(OrderItemCache, OrderCache.delivery_date)
            .join(
                OrderCache,
                (OrderCache.order_id == OrderItemCache.order_id)
                & (OrderCache.user_id == OrderItemCache.user_id),
            )
            .where(
                OrderItemCache.user_id == user_id,
                OrderItemCache.quantity > 0,
                OrderCache.delivery_date.is_not(None),
            )
        )
        order_rows = items_result.all()

    # Index catalogue by SKU
    cat_by_sku: dict[str, PurchasedProductCache] = {r.sku: r for r in catalogue}

    # Build per-SKU order history: {sku: [delivery_date, ...]}
    orders_by_sku: dict[str, list[datetime.date]] = defaultdict(list)
    for item, delivery_date in order_rows:
        if delivery_date is not None:
            orders_by_sku[item.sku].append(
                delivery_date
                if isinstance(delivery_date, datetime.date)
                else datetime.date.fromisoformat(str(delivery_date))
            )

    # Combine into PurchaseRecord objects
    all_skus = set(cat_by_sku.keys()) | set(orders_by_sku.keys())
    records: list[PurchaseRecord] = []

    for sku in all_skus:
        cat = cat_by_sku.get(sku)
        dates = sorted(orders_by_sku.get(sku, []))

        name = (
            cat.name
            if cat
            else (next((item.name for item, _ in order_rows if item.sku == sku), sku))
        )
        category = None
        if cat:
            import json

            cats = json.loads(cat.categories_json or "[]")
            category = cats[0] if cats else None

        order_count = len(dates)
        last_bought = dates[-1] if dates else None

        # Frequency: buys/week from inter-purchase gaps
        frequency: float | None = None
        if len(dates) >= 2:
            gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
            mean_gap = sum(gaps) / len(gaps)
            frequency = 7.0 / mean_gap if mean_gap > 0 else None

        dates_complete = order_count >= 2

        records.append(
            PurchaseRecord(
                sku=sku,
                name=name,
                category=category,
                ever_bought=sku in cat_by_sku,
                last_bought=last_bought,
                order_count=order_count,
                frequency=frequency,
                dates_complete=dates_complete,
            )
        )

    log.debug(
        "build_purchase_history user=%d → %d records (%d from catalogue, %d with dates)",
        user_id,
        len(records),
        len(cat_by_sku),
        sum(1 for r in records if r.dates_complete),
    )
    return records
