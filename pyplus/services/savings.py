"""
Cart-wide unit-price optimiser.

For each cart line, look at the same product in other pack sizes (same brand +
name in the store catalogue) and find the cheapest way to cover the same amount.
Surfaces explicit, user-confirmed swap suggestions — e.g.

    2× Douwe Egberts 250 g (€11,10)  →  1× 500 g (€9,99)   bespaar €1,11

Pure logic — no DB or NiceGUI — so it is trivially unit-testable. The UI loads
the candidate groups (repo.get_pack_alternatives) and calls find_savings().
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyplus.services.aggregate import _to_base
from pyplus.services.dishes import _parse_pack_from_subtitle

_MIN_SAVING = 0.05  # € — ignore rounding-noise suggestions
_MAX_PACKS = 6  # don't suggest splitting into an absurd number of packs


@dataclass
class Saving:
    sku: str  # current cart sku
    name: str
    cur_qty: int
    cur_pack: str  # display label e.g. "250 g"
    cur_cost: float
    new_sku: str
    new_qty: int
    new_pack: str
    new_cost: float

    @property
    def saving(self) -> float:
        return round(self.cur_cost - self.new_cost, 2)


def _pack_base(subtitle: str) -> tuple[float | None, str | None]:
    """Pack size of one unit in base units (g/ml/stuks), parsed from a subtitle."""
    size, unit = _parse_pack_from_subtitle(subtitle or "")
    if size is None or unit is None:
        return None, None
    try:
        base, base_unit = _to_base(size, unit)
        return base, base_unit
    except ValueError:
        return None, None


def _pack_label(subtitle: str) -> str:
    size, unit = _parse_pack_from_subtitle(subtitle or "")
    if size is None:
        return (subtitle or "").replace("Per ", "").strip() or "?"
    return f"{size:g} {unit}"


def best_swap(
    sku: str,
    name: str,
    cur_qty: int,
    cur_price: float,
    cur_subtitle: str,
    group: list,
) -> Saving | None:
    """Cheapest alternative pack covering the same amount, or None.

    `group` items expose .sku, .subtitle, .price (plus.models.Product or
    db.models.ProductCache both qualify via duck-typing).
    """
    if cur_qty < 1 or cur_price <= 0:
        return None
    cur_base, base_unit = _pack_base(cur_subtitle)
    if cur_base is None:
        return None

    need = cur_qty * cur_base
    cur_cost = round(cur_qty * cur_price, 2)

    best: Saving | None = None
    for cand in group:
        cand_price = getattr(cand, "price", 0.0) or 0.0
        if cand_price <= 0:
            continue
        cand_base, cand_unit = _pack_base(getattr(cand, "subtitle", ""))
        if cand_base is None or cand_unit != base_unit:
            continue
        n = max(1, math.ceil(need / cand_base))
        if n > _MAX_PACKS:
            continue
        cost = round(n * cand_price, 2)
        # Must be a real change and genuinely cheaper.
        if cand.sku == sku and n == cur_qty:
            continue
        if cur_cost - cost < _MIN_SAVING:
            continue
        if best is None or cost < best.new_cost:
            best = Saving(
                sku=sku,
                name=name,
                cur_qty=cur_qty,
                cur_pack=_pack_label(cur_subtitle),
                cur_cost=cur_cost,
                new_sku=cand.sku,
                new_qty=n,
                new_pack=_pack_label(getattr(cand, "subtitle", "")),
                new_cost=cost,
            )
    return best


def find_savings(cart_items, alternatives: dict[str, list]) -> list[Saving]:
    """Compute the best swap for every cart line that has one. Sorted by € saved."""
    out: list[Saving] = []
    for item in cart_items:
        group = alternatives.get(item.sku)
        if not group:
            continue
        s = best_swap(item.sku, item.product, item.quantity, item.price, item.unit, group)
        if s:
            out.append(s)
    out.sort(key=lambda s: s.saving, reverse=True)
    return out
