"""
Promotion relevance model — pure functions, no async, no DB access.

Scores each promotion by how relevant it is to this user, then returns a
sorted list for Lane ③.

Scoring signals (additive):
  1. ever_bought  (breadth catalogue, incl. in-store) — strong base signal
  2. frequency    (dated online orders) — boosts high-cadence products
  3. in weekmenu  — strong boost: user needs this ingredient THIS week
  4. category     — minor affinity boost for known categories

Dating-gap: ever_bought captures in-store purchases; frequency only applies
when dates_complete.  Both are used so in-store-only products still surface
in the deals lane.
"""

from __future__ import annotations


def score_promotion(
    promo,  # plus.models.Promotion
    history_by_sku: dict,  # sku → PurchaseRecord
    weekmenu_skus: set[str],
) -> float:
    """Return a relevance score ≥ 0.  Higher = more relevant."""
    if promo.is_free_delivery:
        return 0.05  # informational; keep at bottom

    if not promo.is_single_product or not promo.sku:
        # Group deal — can't inspect individual SKUs without fetching products.
        # Give a small base score so they still appear.
        return 0.2

    record = history_by_sku.get(promo.sku)
    score = 0.0

    if record:
        if record.ever_bought:
            score += 1.0

        if record.dates_complete and record.frequency:
            score += min(record.frequency, 3.0) * 0.5

        if promo.sku in weekmenu_skus:
            score += 4.0  # strong: needed this week

    return score


def sort_promotions_by_relevance(
    promotions: list,  # list[Promotion]
    history_by_sku: dict,  # sku → PurchaseRecord
    weekmenu_skus: set[str],
) -> list:
    """Return promotions sorted by relevance (most relevant first)."""
    scored = [(p, score_promotion(p, history_by_sku, weekmenu_skus)) for p in promotions]
    scored.sort(key=lambda t: t[1], reverse=True)
    return [p for p, _ in scored]
