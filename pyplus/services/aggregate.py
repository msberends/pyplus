"""
Cross-dish pack-optimisation aggregation engine.

Given a set of dishes selected for the week, aggregate ingredients by SKU,
convert units within the same family (g↔kg, ml↔l), and determine whether
buying one larger pack covers multiple dishes cheaper than buying per-dish.

Chicken example (from the brief):
  Dish A: 300 g kip · Dish B: 300 g kip · pack = 650 g @ €3.99
  → total 600 g → 1× 650 g instead of 2× 650 g → saves €3.99
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pyplus.db.models import Dish, DishIngredient, IngredientSku

# ── Unit normalisation ─────────────────────────────────────────────────────────


def _to_base(amount: float, unit: str) -> tuple[float, str]:
    """Normalise amount to base unit (g or ml or stuks). Raises ValueError if unknown."""
    u = unit.lower().strip()
    if u in ("g", "gram"):
        return amount, "g"
    if u == "kg":
        return amount * 1000.0, "g"
    if u == "ml":
        return amount, "ml"
    if u in ("l", "liter", "litre"):
        return amount * 1000.0, "ml"
    if u == "cl":
        return amount * 10.0, "ml"
    if u in ("stuks", "stuk", "st"):
        return amount, "stuks"
    raise ValueError(f"Cannot normalise unit: {unit!r}")


def fmt_amount(amount: float, unit: str) -> str:
    """Format a normalised amount for display (e.g. 1200 g → '1.2 kg')."""
    if unit == "g" and amount >= 1000:
        return f"{amount / 1000:.3g} kg"
    if unit == "ml" and amount >= 1000:
        return f"{amount / 1000:.3g} l"
    n = int(amount) if amount == int(amount) else round(amount, 1)
    return f"{n} {unit}"


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class AggLine:
    sku: str
    display_name: str
    required_amount: float  # normalised total (e.g. 600 g)
    required_unit: str  # base unit
    pack_size_base: float | None  # pack size in base unit
    pack_unit: str | None  # display unit for pack size
    packs_optimised: int  # packs when aggregated across dishes
    packs_per_dish: int  # packs if ordered once per contributing dish
    pack_price: float | None
    savings: float  # €  (packs_per_dish − packs_optimised) × price
    leftover_base: float  # surplus after packs_optimised
    dish_names: list[str]  # names of dishes contributing this ingredient

    @property
    def has_saving(self) -> bool:
        return self.packs_optimised < self.packs_per_dish and self.savings > 0.001

    def packs_to_add(self, overrides: "set[str]") -> int:
        return self.packs_per_dish if self.sku in overrides else self.packs_optimised


@dataclass
class AggResult:
    lines: list[AggLine] = field(default_factory=list)
    total_savings: float = 0.0

    def items_to_add(self, overrides: "set[str] | None" = None) -> list[tuple[str, int]]:
        ov = overrides or set()
        return [(ln.sku, ln.packs_to_add(ov)) for ln in self.lines if ln.packs_to_add(ov) > 0]


# ── Engine ─────────────────────────────────────────────────────────────────────


def aggregate(
    dishes_with_ingredients: list[tuple[Dish, list[DishIngredient]]],
    sku_cache: dict[str, IngredientSku],
    *,
    include_optional: bool = False,
) -> AggResult:
    """
    Produce an AggResult for the selected dishes.

    dishes_with_ingredients: (Dish, [DishIngredient]) pairs for every selected slot.
    sku_cache: ingredient_skus rows keyed by sku — provides pack_size, price, etc.
    """
    # Collect per-SKU contributions from each dish.
    # groups[sku] = {display_name, base_unit, pack_size_base, pack_price, pack_unit,
    #                compatible, contributions: [{dish_name, base_amount, per_dish_packs}]}
    groups: dict[str, dict] = {}

    for dish, ingredients in dishes_with_ingredients:
        for ing in ingredients:
            if not ing.sku:
                continue
            if ing.optional and not include_optional:
                continue

            cached = sku_cache.get(ing.sku)
            pack_price = cached.last_price if cached else None

            # Resolve pack size in base units.
            pack_size_base: float | None = None
            pack_unit: str | None = None
            if cached and cached.pack_size and cached.pack_unit:
                try:
                    pack_size_base, _ = _to_base(cached.pack_size, cached.pack_unit)
                    pack_unit = cached.pack_unit
                except ValueError:
                    pass

            # Normalise ingredient amount.
            try:
                base_amount, base_unit = _to_base(ing.amount, ing.amount_unit)
            except ValueError:
                base_amount = ing.amount
                base_unit = ing.amount_unit
                pack_size_base = None  # can't compare pack to unknown unit

            if ing.sku not in groups:
                groups[ing.sku] = {
                    "display_name": ing.display_name,
                    "base_unit": base_unit,
                    "pack_size_base": pack_size_base,
                    "pack_unit": pack_unit,
                    "pack_price": pack_price,
                    "compatible": True,
                    "contributions": [],
                }

            grp = groups[ing.sku]

            # Mark incompatible if unit families differ across dishes.
            if grp["base_unit"] != base_unit:
                grp["compatible"] = False

            # Per-dish pack count: how many packs just for this dish.
            ps = grp["pack_size_base"] or pack_size_base
            if ps and ps > 0 and grp["compatible"]:
                per_dish_packs = max(1, math.ceil(base_amount / ps))
            else:
                per_dish_packs = 1

            grp["contributions"].append(
                {
                    "dish_name": dish.name,
                    "base_amount": base_amount,
                    "per_dish_packs": per_dish_packs,
                }
            )

    # Build AggResult lines.
    result = AggResult()

    for sku, grp in groups.items():
        contribs = grp["contributions"]
        dish_names = [c["dish_name"] for c in contribs]
        packs_per_dish = sum(c["per_dish_packs"] for c in contribs)
        ps = grp["pack_size_base"]
        pack_price = grp["pack_price"]

        if grp["compatible"] and ps and ps > 0:
            total_base = sum(c["base_amount"] for c in contribs)
            packs_optimised = max(1, math.ceil(total_base / ps))
            leftover_base = packs_optimised * ps - total_base
            saved_packs = packs_per_dish - packs_optimised
            savings = saved_packs * pack_price if (pack_price and saved_packs > 0) else 0.0
        else:
            total_base = sum(c["base_amount"] for c in contribs)
            packs_optimised = packs_per_dish
            leftover_base = 0.0
            savings = 0.0

        line = AggLine(
            sku=sku,
            display_name=grp["display_name"],
            required_amount=total_base,
            required_unit=grp["base_unit"],
            pack_size_base=ps,
            pack_unit=grp["pack_unit"],
            packs_optimised=packs_optimised,
            packs_per_dish=packs_per_dish,
            pack_price=pack_price,
            savings=savings,
            leftover_base=leftover_base,
            dish_names=dish_names,
        )
        result.lines.append(line)
        result.total_savings += savings

    result.lines.sort(key=lambda ln: ln.display_name.lower())
    return result
