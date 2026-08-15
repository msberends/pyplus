"""
Unit tests for the aggregation engine (services/aggregate.py).

Test cases include the canonical chicken example from the brief plus
unit-conversion edges and single-dish / unresolvable cases.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

from pyplus.services.aggregate import aggregate, fmt_amount, normalize_product_family

# ── Helpers to build mock model objects ───────────────────────────────────────


def _dish(dish_id: int, name: str) -> MagicMock:
    d = MagicMock()
    d.id = dish_id
    d.name = name
    return d


def _ing(sku: str, display_name: str, amount: float, unit: str, optional: bool = False):
    i = MagicMock()
    i.sku = sku
    i.display_name = display_name
    i.amount = amount
    i.amount_unit = unit
    i.optional = optional
    return i


def _sku_cache(sku: str, pack_size: float, pack_unit: str, price: float):
    s = MagicMock()
    s.sku = sku
    s.pack_size = pack_size
    s.pack_unit = pack_unit
    s.last_price = price
    return s


def test_include_optional_flag():
    """Optional ingredients are excluded by default and included on request."""
    dish = _dish(1, "Pasta")
    ings = [
        _ing("100", "Pasta", 250, "g"),
        _ing("200", "Parmezaan", 50, "g", optional=True),
    ]
    cache = {
        "100": _sku_cache("100", 500, "g", 1.0),
        "200": _sku_cache("200", 100, "g", 2.5),
    }

    default = aggregate([(dish, ings)], cache)
    assert {ln.sku for ln in default.lines} == {"100"}

    with_opt = aggregate([(dish, ings)], cache, include_optional=True)
    assert {ln.sku for ln in with_opt.lines} == {"100", "200"}


def test_resolved_flexible_ingredient_aggregates():
    """A flexible placeholder resolved to a real SKU feeds aggregation like any other."""
    from dataclasses import dataclass

    @dataclass
    class EffIng:  # mirrors meals._EffIng duck-typing
        sku: str
        display_name: str
        amount: float
        amount_unit: str
        optional: bool = False

    dish = _dish(1, "Curry")
    resolved = [EffIng(sku="900", display_name="Kipfilet", amount=300, amount_unit="g")]
    cache = {"900": _sku_cache("900", 650, "g", 3.99)}

    res = aggregate([(dish, resolved)], cache, include_optional=True)
    assert len(res.lines) == 1
    assert res.lines[0].sku == "900"


# ── fmt_amount ────────────────────────────────────────────────────────────────


def test_fmt_amount_g():
    assert fmt_amount(300.0, "g") == "300 g"


def test_fmt_amount_g_to_kg():
    assert fmt_amount(1200.0, "g") == "1.2 kg"


def test_fmt_amount_ml():
    assert fmt_amount(500.0, "ml") == "500 ml"


def test_fmt_amount_ml_to_l():
    assert fmt_amount(1500.0, "ml") == "1.5 l"


def test_fmt_amount_stuks():
    assert fmt_amount(2.0, "stuks") == "2 stuks"


# ── Canonical chicken example ─────────────────────────────────────────────────


def test_chicken_optimisation():
    """
    Dish A: 300 g chicken · Dish B: 300 g chicken
    Pack: 650 g @ €3.99
    Expected: 1× 650 g pack instead of 2×, saving €3.99, 50 g leftover.
    """
    dish_a = _dish(1, "Kip tandoori")
    dish_b = _dish(2, "Kip kerrie")
    ing_a = _ing("kip-650", "Kip (filet)", 300.0, "g")
    ing_b = _ing("kip-650", "Kip (filet)", 300.0, "g")

    sku_cache = {"kip-650": _sku_cache("kip-650", 650.0, "g", 3.99)}

    result = aggregate(
        [(dish_a, [ing_a]), (dish_b, [ing_b])],
        sku_cache,
    )

    assert len(result.lines) == 1
    line = result.lines[0]

    assert line.sku == "kip-650"
    assert line.packs_optimised == 1
    assert line.packs_per_dish == 2
    assert line.has_saving is True
    assert math.isclose(line.savings, 3.99, rel_tol=1e-6)
    assert math.isclose(line.leftover_base, 50.0, rel_tol=1e-6)
    assert math.isclose(result.total_savings, 3.99, rel_tol=1e-6)


# ── packs_to_add respects override ────────────────────────────────────────────


def test_override_reverts_to_per_dish():
    dish_a = _dish(1, "Gerecht A")
    dish_b = _dish(2, "Gerecht B")
    sku_cache = {"x": _sku_cache("x", 650.0, "g", 3.99)}

    result = aggregate(
        [(dish_a, [_ing("x", "Kip", 300.0, "g")]), (dish_b, [_ing("x", "Kip", 300.0, "g")])],
        sku_cache,
    )
    line = result.lines[0]

    # Without override: optimised
    assert line.packs_to_add(set()) == 1
    # With override: per-dish
    assert line.packs_to_add({"x"}) == 2


# ── Single-dish ingredient (no optimisation) ──────────────────────────────────


def test_single_dish_no_saving():
    dish = _dish(1, "Soep")
    sku_cache = {"tomaat": _sku_cache("tomaat", 400.0, "g", 1.49)}
    result = aggregate([(dish, [_ing("tomaat", "Tomaten", 400.0, "g")])], sku_cache)

    assert len(result.lines) == 1
    line = result.lines[0]
    assert line.packs_optimised == 1
    assert line.packs_per_dish == 1
    assert not line.has_saving
    assert result.total_savings == 0.0


# ── Unit conversion: kg input → g pack ───────────────────────────────────────


def test_kg_to_g_conversion():
    """An ingredient specified in kg should aggregate with g pack correctly."""
    dish = _dish(1, "Gerecht")
    sku_cache = {"aardappel": _sku_cache("aardappel", 1000.0, "g", 1.20)}
    # 0.5 kg = 500 g → 1× 1000 g pack needed
    result = aggregate(
        [(dish, [_ing("aardappel", "Aardappels", 0.5, "kg")])],
        sku_cache,
    )
    line = result.lines[0]
    assert line.packs_optimised == 1
    assert math.isclose(line.required_amount, 500.0, rel_tol=1e-6)
    assert line.required_unit == "g"


def test_two_dishes_kg_and_g():
    """Mix of g and kg inputs for the same SKU should aggregate correctly."""
    dish_a = _dish(1, "A")
    dish_b = _dish(2, "B")
    sku_cache = {"pasta": _sku_cache("pasta", 500.0, "g", 1.39)}
    # 200 g + 0.3 kg (= 300 g) = 500 g → exactly 1 pack, 0 leftover
    result = aggregate(
        [
            (dish_a, [_ing("pasta", "Pasta", 200.0, "g")]),
            (dish_b, [_ing("pasta", "Pasta", 0.3, "kg")]),
        ],
        sku_cache,
    )
    line = result.lines[0]
    assert line.packs_optimised == 1
    assert math.isclose(line.required_amount, 500.0, rel_tol=1e-6)
    assert math.isclose(line.leftover_base, 0.0, abs_tol=1e-6)


# ── Incompatible units: g + ml same SKU → no crash, fallback ─────────────────


def test_incompatible_units_fallback():
    """g and ml on the same SKU → compatible=False → packs_optimised == packs_per_dish."""
    dish_a = _dish(1, "A")
    dish_b = _dish(2, "B")
    sku_cache = {"weird": _sku_cache("weird", 500.0, "g", 2.00)}
    result = aggregate(
        [(dish_a, [_ing("weird", "X", 200.0, "g")]), (dish_b, [_ing("weird", "X", 100.0, "ml")])],
        sku_cache,
    )
    line = result.lines[0]
    assert not line.has_saving
    assert line.packs_optimised == line.packs_per_dish


# ── Optional ingredients excluded by default ──────────────────────────────────


def test_optional_excluded():
    dish = _dish(1, "D")
    sku_cache = {"opt": _sku_cache("opt", 100.0, "g", 1.00)}
    result = aggregate([(dish, [_ing("opt", "Opt", 200.0, "g", optional=True)])], sku_cache)
    assert len(result.lines) == 0


def test_optional_included_when_flag_set():
    dish = _dish(1, "D")
    sku_cache = {"opt": _sku_cache("opt", 100.0, "g", 1.00)}
    result = aggregate(
        [(dish, [_ing("opt", "Opt", 200.0, "g", optional=True)])],
        sku_cache,
        include_optional=True,
    )
    assert len(result.lines) == 1


# ── Empty SKU is skipped ──────────────────────────────────────────────────────


def test_empty_sku_skipped():
    dish = _dish(1, "D")
    result = aggregate(
        [(dish, [_ing("", "Flexibel ingrediënt", 1.0, "stuks")])],
        {},
    )
    assert len(result.lines) == 0


# ── No pack size → packs_optimised equals packs_per_dish ─────────────────────


def test_no_pack_size_no_saving():
    """If the SKU cache has no pack_size, we can't optimise — no saving claimed."""
    dish_a = _dish(1, "A")
    dish_b = _dish(2, "B")
    cached = MagicMock()
    cached.pack_size = None
    cached.pack_unit = None
    cached.last_price = 2.00

    result = aggregate(
        [(dish_a, [_ing("x", "Y", 300.0, "g")]), (dish_b, [_ing("x", "Y", 300.0, "g")])],
        {"x": cached},
    )
    assert result.total_savings == 0.0
    line = result.lines[0]
    assert not line.has_saving


# ── normalize_product_family ──────────────────────────────────────────────────


def test_normalize_strips_pack_count_suffix():
    assert (
        normalize_product_family("PLUS Boerentrots Kipfilet 2 stuks") == "PLUS Boerentrots Kipfilet"
    )


def test_normalize_strips_voordeelverpakking():
    assert normalize_product_family("PLUS Kipfilet Voordeelverpakking") == "PLUS Kipfilet"


def test_normalize_strips_trailing_weight():
    assert (
        normalize_product_family("PLUS Boerentrots Kipfiletblokjes fijn 600 gram")
        == "PLUS Boerentrots Kipfiletblokjes fijn"
    )


def test_normalize_strips_compact_stuks_count():
    assert normalize_product_family(
        "PLUS Boerentrots Krokante kipfiletschnitzels 2st"
    ) == normalize_product_family("PLUS Boerentrots Krokante kipfiletschnitzels 5st")


def test_normalize_leaves_plain_name_untouched():
    assert normalize_product_family("PLUS Boerentrots Kipfilet") == "PLUS Boerentrots Kipfilet"


def test_normalize_no_qualifier_no_change():
    # A name with no trailing pack qualifier shouldn't be mangled.
    assert normalize_product_family("PLUS Prei") == "PLUS Prei"
