"""Unit tests for category parsing/grouping and cart sort/group helpers."""

from __future__ import annotations

from types import SimpleNamespace

from pyplus.services.categories import (
    OVERIG,
    group_order,
    parse_categories,
    top_category,
)
from pyplus.ui.components.cart import _group_items, _sort_items


def test_parse_categories():
    assert parse_categories('["A", "B", "C"]') == ["A", "B", "C"]
    assert parse_categories("") == []
    assert parse_categories(None) == []
    assert parse_categories("not json") == []
    assert parse_categories('{"x": 1}') == []  # not a list


def test_top_category():
    assert top_category(["Verse maaltijden", "Italiaans", "Lasagne"]) == "Verse maaltijden"
    assert top_category([]) == OVERIG


def test_group_order_alpha_with_overig_last():
    order = group_order(["Zuivel", OVERIG, "Brood", "appels"])
    assert order == ["appels", "Brood", "Zuivel", OVERIG]


def _item(sku, product, price_total):
    return SimpleNamespace(sku=sku, product=product, price_total=price_total)


def test_sort_items():
    items = [_item("1", "Banaan", 3.0), _item("2", "Appel", 1.0), _item("3", "Carrot", 2.0)]
    assert [i.sku for i in _sort_items(items, "cart")] == ["1", "2", "3"]  # unchanged
    assert [i.product for i in _sort_items(items, "name")] == ["Appel", "Banaan", "Carrot"]
    assert [i.sku for i in _sort_items(items, "price")] == ["1", "3", "2"]  # high → low


def test_group_items_buckets_and_order():
    items = [
        _item("1", "Melk", 1.0),
        _item("2", "Kaas", 2.0),
        _item("3", "Onbekend", 1.0),
    ]
    cat_by_sku = {"1": ["Zuivel", "Melk"], "2": ["Zuivel", "Kaas"]}  # 3 has none → Overig
    groups = _group_items(items, cat_by_sku)
    assert [g[0] for g in groups] == ["Zuivel", OVERIG]
    assert [i.sku for i in groups[0][1]] == ["1", "2"]
    assert [i.sku for i in groups[1][1]] == ["3"]


def test_format_until_countdown():
    import datetime as dt

    from pyplus.ui.pages.settings import _format_until

    tz = dt.timezone(dt.timedelta(hours=2))
    now = dt.datetime.now(tz)
    assert _format_until(now - dt.timedelta(minutes=5)) == "binnenkort"
    assert _format_until(now + dt.timedelta(days=2, hours=3, minutes=40)).startswith("over 2d 3u")
    assert _format_until(now + dt.timedelta(hours=5, minutes=10)).startswith("over 5u")
    assert _format_until(now + dt.timedelta(minutes=20)).startswith("over ")
