"""
Staple replenishment model — pure functions, no async, no DB access.

For each fixed product SKU, produces a ReplenishScore that the staples lane
uses to highlight items predicted as due.

Due logic:
  due_score = days_since_last_purchase / expected_interval_days
  due        = due_score ≥ threshold (default 1.0)

Dating-gap rule: when dates_complete=False (bought in-store, no usable dates),
return a soft "vaak gekocht" signal instead of inventing a cadence.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass
class ReplenishScore:
    sku: str
    due_score: float  # 0.0 = not due; ≥1.0 = due
    reason: str  # Dutch explanation, e.g. "wekelijks · 3 dagen geleden"
    is_due: bool
    dates_complete: bool  # mirrors PurchaseRecord.dates_complete


def _interval_label(interval_days: float) -> str:
    if interval_days <= 8:
        return "wekelijks"
    if interval_days <= 18:
        return "tweewekelijks"
    if interval_days <= 40:
        return "maandelijks"
    return "af en toe"


def _days_ago_label(days: int) -> str:
    if days == 0:
        return "vandaag"
    if days == 1:
        return "gisteren"
    return f"{days} dagen geleden"


def compute_replenishment_score(
    record,  # PurchaseRecord | None
    today: datetime.date,
    threshold: float = 1.0,
) -> ReplenishScore:
    """Compute due score for one product.  record may be None (not in purchase history)."""
    if record is None or not record.ever_bought:
        return ReplenishScore(
            sku=record.sku if record else "",
            due_score=0.0,
            reason="",
            is_due=False,
            dates_complete=False,
        )

    if not record.dates_complete or record.frequency is None or record.last_bought is None:
        # Soft signal: ever bought but no reliable cadence
        return ReplenishScore(
            sku=record.sku,
            due_score=0.3,
            reason="vaak gekocht",
            is_due=False,
            dates_complete=False,
        )

    interval_days = 7.0 / record.frequency  # expected days between purchases
    days_since = (today - record.last_bought).days
    due_score = days_since / interval_days if interval_days > 0 else 0.0
    is_due = due_score >= threshold

    reason = f"{_interval_label(interval_days)} · {_days_ago_label(days_since)}"
    return ReplenishScore(
        sku=record.sku,
        due_score=due_score,
        reason=reason,
        is_due=is_due,
        dates_complete=True,
    )


def sort_fixed_products_by_due(
    product_skus: list[str],
    scores: dict[str, ReplenishScore],
) -> list[str]:
    """Return SKUs sorted: due items first (by due_score desc), then rest."""

    def _key(sku: str) -> tuple:
        s = scores.get(sku)
        if s is None:
            return (0, 0.0)
        return (1 if s.is_due else 0, s.due_score)

    return sorted(product_skus, key=_key, reverse=True)
