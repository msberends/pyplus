"""
Cart-wide unit-price optimiser.

For each cart line, look at the same product in other pack sizes (same brand +
name in the store catalogue) and find the cheapest way to cover the same amount.
Surfaces explicit, user-confirmed swap suggestions — e.g.

    2× Douwe Egberts 250 g (€11,10)  →  1× 500 g (€9,99)   bespaar €1,11

When only a subset of items maps to full packs (e.g. 5 bottles → 1×4-pack),
only those items are replaced; the remainder stays in the cart untouched.

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
    cur_qty: int  # number of items being REPLACED (not total cart qty)
    cur_pack: str  # display label e.g. "250 g"
    cur_cost: float  # cost of the items being replaced
    new_sku: str
    new_qty: int
    new_pack: str
    new_cost: float
    keep_qty: int = 0  # items of the original SKU to keep in cart
    cur_subtitle: str = ""  # full pack subtitle of the current product
    new_subtitle: str = ""  # full pack subtitle of the suggested product
    new_image: str = ""  # catalogue image of the suggested product

    @property
    def saving(self) -> float:
        return round(self.cur_cost - self.new_cost, 2)

    @property
    def cur_unit_price(self) -> float:
        return round(self.cur_cost / self.cur_qty, 2) if self.cur_qty else 0.0

    @property
    def new_unit_price(self) -> float:
        return round(self.new_cost / self.new_qty, 2) if self.new_qty else 0.0


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

    Two strategies per candidate:
      1. Pure swap: replace ALL items with candidate packs (total coverage ≥ need).
      2. Partial swap: replace only the items that map to full packs, keep remainder.
         E.g. 5×single → 1×4-pack + keep 1 single. Only 4 are replaced.
    """
    if cur_qty < 1 or cur_price <= 0:
        return None
    cur_base, base_unit = _pack_base(cur_subtitle)
    if cur_base is None:
        return None

    need = cur_qty * cur_base
    cur_cost_full = round(cur_qty * cur_price, 2)

    best: Saving | None = None
    best_saving: float = 0.0

    for cand in group:
        if not getattr(cand, "is_available", True):
            continue
        cand_price = getattr(cand, "price", 0.0) or 0.0
        if cand_price <= 0:
            continue
        cand_base, cand_unit = _pack_base(getattr(cand, "subtitle", ""))
        if cand_base is None or cand_unit != base_unit:
            continue

        # Strategy 1: pure swap — replace all items, coverage ≥ need.
        # Works when N packs of the candidate cover everything (e.g. 2×300g → 1×650g).
        n_pure = max(1, math.ceil(need / cand_base))
        if n_pure <= _MAX_PACKS and not (cand.sku == sku and n_pure == cur_qty):
            cost_pure = round(n_pure * cand_price, 2)
            saving_pure = cur_cost_full - cost_pure
            if saving_pure >= _MIN_SAVING and saving_pure > best_saving:
                best = Saving(
                    sku=sku,
                    name=name,
                    cur_qty=cur_qty,
                    cur_pack=_pack_label(cur_subtitle),
                    cur_cost=cur_cost_full,
                    new_sku=cand.sku,
                    new_qty=n_pure,
                    new_pack=_pack_label(getattr(cand, "subtitle", "")),
                    new_cost=cost_pure,
                    keep_qty=0,
                    cur_subtitle=cur_subtitle or "",
                    new_subtitle=getattr(cand, "subtitle", "") or "",
                    new_image=getattr(cand, "image_url", "") or "",
                )
                best_saving = saving_pure

        # Strategy 2: partial swap — replace only items that map to full packs.
        # E.g. 5 bottles → replace 4 with 1×4-pack, keep 1 bottle.
        # Only when the candidate covers more than one original item.
        if cand_base > cur_base and cand.sku != sku:
            n_packs = int(need // cand_base)
            if n_packs < 1 or n_packs > _MAX_PACKS:
                continue
            # How many original items does n_packs of the candidate replace?
            items_replaced = int(n_packs * cand_base / cur_base)
            keep = cur_qty - items_replaced
            if keep <= 0:
                continue  # no remainder → pure swap handles this
            cost_replaced = round(items_replaced * cur_price, 2)
            cost_new = round(n_packs * cand_price, 2)
            saving_partial = cost_replaced - cost_new
            if saving_partial >= _MIN_SAVING and saving_partial > best_saving:
                best = Saving(
                    sku=sku,
                    name=name,
                    cur_qty=items_replaced,
                    cur_pack=_pack_label(cur_subtitle),
                    cur_cost=cost_replaced,
                    new_sku=cand.sku,
                    new_qty=n_packs,
                    new_pack=_pack_label(getattr(cand, "subtitle", "")),
                    new_cost=cost_new,
                    keep_qty=keep,
                    cur_subtitle=cur_subtitle or "",
                    new_subtitle=getattr(cand, "subtitle", "") or "",
                    new_image=getattr(cand, "image_url", "") or "",
                )
                best_saving = saving_partial
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
