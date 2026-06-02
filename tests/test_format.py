"""Unit tests for pyplus.ui.format presentation helpers (pure functions)."""

import datetime
from dataclasses import dataclass

from pyplus.ui import format as fmt


@dataclass
class _Dish:
    prep_minutes: int | None = None
    meat_type: str | None = None
    veg_count: int | None = None


def test_plus_product_url_prefers_slug():
    assert fmt.plus_product_url("melk-halfvol-1l", "12345") == (
        "https://www.plus.nl/product/melk-halfvol-1l"
    )


def test_plus_product_url_falls_back_to_sku_search():
    assert fmt.plus_product_url("", "12345") == (
        "https://www.plus.nl/zoekresultaten?SearchTerm=12345"
    )


def test_plus_product_url_empty():
    assert fmt.plus_product_url("", "") == ""


def test_prep_time_label_buckets():
    assert fmt.prep_time_label(20) == "≤20 min"
    assert fmt.prep_time_label(120) == "60+ min"
    assert fmt.prep_time_label(None) == ""
    assert fmt.prep_time_label(0) == ""


def test_veg_emoji():
    assert fmt.veg_emoji(0) == "➖"
    assert fmt.veg_emoji(2) == "🥦🥦"
    assert fmt.veg_emoji(5) == "🥦🥦🥦"  # clamped to 3
    assert fmt.veg_emoji(None) == ""


def test_dish_meta_chips_full():
    chips = fmt.dish_meta_chips(_Dish(prep_minutes=40, meat_type="kip", veg_count=2))
    assert chips == ["🐓 Kip", "⏱ 20–40 min", "🥦🥦"]


def test_dish_meta_chips_empty():
    assert fmt.dish_meta_chips(_Dish()) == []


def test_humanize_since():
    now = datetime.datetime.utcnow()
    assert fmt.humanize_since(None) == "nooit"
    assert fmt.humanize_since(now) == "zojuist"
    assert fmt.humanize_since(now - datetime.timedelta(hours=3)) == "3 uur geleden"
    assert fmt.humanize_since(now - datetime.timedelta(days=1)) == "gisteren"
