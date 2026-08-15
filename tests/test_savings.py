"""Unit tests for the cart unit-price optimiser (services/savings.py)."""

from __future__ import annotations

from dataclasses import dataclass

from pyplus.services.savings import best_swap, find_savings


@dataclass
class _Cand:  # duck-types ProductCache / Product
    sku: str
    subtitle: str
    price: float
    name: str = ""


@dataclass
class _Item:  # duck-types CartItem
    sku: str
    product: str
    quantity: int
    price: float
    unit: str


def test_bigger_pack_cheaper_per_unit():
    # 2× DE 250 g (€5.55 each = €11.10) → 1× 500 g (€9.99) saves €1.11
    group = [
        _Cand("159124", "Per 250 g", 5.55, "DE koffie"),
        _Cand("159159", "Per 500 g", 9.99, "DE koffie"),
    ]
    s = best_swap("159124", "DE koffie", 2, 5.55, "Per 250 g", group)
    assert s is not None
    assert s.new_sku == "159159"
    assert s.new_qty == 1
    assert s.saving == 1.11


def test_smaller_pack_cheaper_per_unit():
    # 1× 3000 ml (€2.29) → 2× 1500 ml (€0.48 = €0.96) is cheaper per litre
    group = [
        _Cand("461330", "Per 500 ml", 0.39, "PLUS water"),
        _Cand("357162", "Per 1500 ml", 0.48, "PLUS water"),
        _Cand("461332", "Per 3000 ml", 2.29, "PLUS water"),
    ]
    s = best_swap("461332", "PLUS water", 1, 2.29, "Per 3000 ml", group)
    assert s is not None
    assert s.new_sku == "357162"
    assert s.new_qty == 2


def test_no_saving_when_already_cheapest():
    group = [
        _Cand("a", "Per 1000 ml", 0.75, "Melk"),
        _Cand("b", "Per 2000 ml", 1.49, "Melk"),  # 0.745/L — only €0.01 cheaper, below threshold
    ]
    assert best_swap("a", "Melk", 2, 0.75, "Per 1000 ml", group) is None


def test_no_suggestion_without_pack_info():
    group = [_Cand("a", "Per stuk", 1.0, "Iets"), _Cand("b", "Per stuk", 2.0, "Iets")]
    assert best_swap("a", "Iets", 3, 1.0, "Per stuk", group) is None


def test_find_savings_sorts_and_filters():
    items = [
        _Item("159124", "DE koffie", 2, 5.55, "Per 250 g"),
        _Item("x", "Onbekend", 1, 1.0, "Per stuk"),
    ]
    alts = {
        "159124": [
            _Cand("159124", "Per 250 g", 5.55, "DE koffie"),
            _Cand("159159", "Per 500 g", 9.99, "DE koffie"),
        ],
        "x": [_Cand("x", "Per stuk", 1.0, "Onbekend")],
    }
    out = find_savings(items, alts)
    assert len(out) == 1
    assert out[0].sku == "159124"


# ── Product-family matching (pack-size variants with different naming) ────────


def test_pack_count_suffix_matches_plain_name():
    # "X 2 stuks" (350 g pack) vs plain "X" (600 g pack) — same product family,
    # different SKU and a name that isn't an exact string match. 2× 350 g need
    # (700 g) covered by 2× 600 g at a cheaper rate is a real saving.
    group = [
        _Cand("563318", "Per 350 g", 5.25, "PLUS Boerentrots Kipfilet 2 stuks"),
        _Cand("563320", "Per 600 g", 4.00, "PLUS Boerentrots Kipfilet"),
    ]
    s = best_swap("563318", "PLUS Boerentrots Kipfilet 2 stuks", 2, 5.25, "Per 350 g", group)
    assert s is not None
    assert s.new_sku == "563320"


def test_voordeelverpakking_suffix_matches_plain_name():
    group = [
        _Cand("a", "Per 200 g", 3.99, "PLUS Kipfilet Voordeelverpakking"),
        _Cand("b", "Per 600 g", 8.29, "PLUS Kipfilet"),
    ]
    s = best_swap("a", "PLUS Kipfilet Voordeelverpakking", 3, 3.99, "Per 200 g", group)
    assert s is not None
    assert s.new_sku == "b"


def test_same_brand_different_product_does_not_match():
    # Same-brand candidates that are simply a *different* product must not be
    # treated as pack-size variants just because they're unit-compatible.
    group = [
        _Cand("a", "Per 300 g", 4.25, "PLUS Rundergehakt"),
        _Cand("b", "Per 300 g", 5.49, "PLUS Boerentrots Kipfiletblokjes fijn"),
    ]
    assert best_swap("a", "PLUS Rundergehakt", 2, 4.25, "Per 300 g", group) is None


def test_mid_pack_size_suffix_matches_base_name():
    # "X" (300 g) vs "X 600 gram" (the size appended directly to the name,
    # not just the subtitle) — still the same family once normalised.
    group = [
        _Cand("a", "Per 300 g", 5.49, "PLUS Boerentrots Kipfiletblokjes fijn"),
        _Cand("b", "Per 600 g", 8.19, "PLUS Boerentrots Kipfiletblokjes fijn 600 gram"),
    ]
    s = best_swap("a", "PLUS Boerentrots Kipfiletblokjes fijn", 2, 5.49, "Per 300 g", group)
    assert s is not None
    assert s.new_sku == "b"
