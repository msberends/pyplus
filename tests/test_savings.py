"""Unit tests for the cart unit-price optimiser (services/savings.py)."""

from __future__ import annotations

from dataclasses import dataclass

from pyplus.services.savings import best_swap, find_savings


@dataclass
class _Cand:  # duck-types ProductCache / Product
    sku: str
    subtitle: str
    price: float


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
        _Cand("159124", "Per 250 g", 5.55),
        _Cand("159159", "Per 500 g", 9.99),
    ]
    s = best_swap("159124", "DE koffie", 2, 5.55, "Per 250 g", group)
    assert s is not None
    assert s.new_sku == "159159"
    assert s.new_qty == 1
    assert s.saving == 1.11


def test_smaller_pack_cheaper_per_unit():
    # 1× 3000 ml (€2.29) → 2× 1500 ml (€0.48 = €0.96) is cheaper per litre
    group = [
        _Cand("461330", "Per 500 ml", 0.39),
        _Cand("357162", "Per 1500 ml", 0.48),
        _Cand("461332", "Per 3000 ml", 2.29),
    ]
    s = best_swap("461332", "PLUS water", 1, 2.29, "Per 3000 ml", group)
    assert s is not None
    assert s.new_sku == "357162"
    assert s.new_qty == 2


def test_no_saving_when_already_cheapest():
    group = [
        _Cand("a", "Per 1000 ml", 0.75),
        _Cand("b", "Per 2000 ml", 1.49),  # 0.745/L — only €0.01 cheaper, below threshold
    ]
    assert best_swap("a", "Melk", 2, 0.75, "Per 1000 ml", group) is None


def test_no_suggestion_without_pack_info():
    group = [_Cand("a", "Per stuk", 1.0), _Cand("b", "Per stuk", 2.0)]
    assert best_swap("a", "Iets", 3, 1.0, "Per stuk", group) is None


def test_find_savings_sorts_and_filters():
    items = [
        _Item("159124", "DE koffie", 2, 5.55, "Per 250 g"),
        _Item("x", "Onbekend", 1, 1.0, "Per stuk"),
    ]
    alts = {
        "159124": [_Cand("159124", "Per 250 g", 5.55), _Cand("159159", "Per 500 g", 9.99)],
        "x": [_Cand("x", "Per stuk", 1.0)],
    }
    out = find_savings(items, alts)
    assert len(out) == 1
    assert out[0].sku == "159124"
