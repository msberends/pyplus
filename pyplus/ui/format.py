"""Small presentation helpers shared across UI components.

Kept free of NiceGUI imports so it stays trivially unit-testable.
"""

from __future__ import annotations

import datetime
import urllib.parse

_PRODUCT_BASE = "https://www.plus.nl/product/"
_SEARCH_BASE = "https://www.plus.nl/zoekresultaten?SearchTerm="

_MEAT_EMOJI = {
    "vega": "🌱",
    "vegetarisch": "🌱",
    "kip": "🐓",
    "rund": "🐄",
    "varken": "🐖",
    "vis": "🐟",
    "gecombineerd": "🍽️",
}
_MEAT_LABEL = {
    "vega": "Vegetarisch",
    "vegetarisch": "Vegetarisch",
    "kip": "Kip",
    "rund": "Rund",
    "varken": "Varken",
    "vis": "Vis",
    "gecombineerd": "Gecombineerd",
}


def plus_product_url(slug: str = "", sku: str = "") -> str:
    """Return a clickable plus.nl URL for a product.

    Prefers the canonical /product/<slug> page; falls back to a search by SKU
    when the slug is unknown so the link still lands the user on the product.
    """
    if slug:
        return f"{_PRODUCT_BASE}{slug.strip('/')}"
    if sku:
        return f"{_SEARCH_BASE}{urllib.parse.quote(sku)}"
    return ""


def prep_time_label(minutes: int | None) -> str:
    """Human bucket label for a dish prep time (matches the R app's buckets)."""
    if not minutes:
        return ""
    return {
        20: "≤20 min",
        40: "20–40 min",
        60: "40–60 min",
        120: "60+ min",
    }.get(minutes, f"{minutes} min")


def meat_emoji(meat_type: str | None) -> str:
    return _MEAT_EMOJI.get((meat_type or "").lower(), "")


def meat_label(meat_type: str | None) -> str:
    return _MEAT_LABEL.get((meat_type or "").lower(), "")


def veg_emoji(veg_count: int | None) -> str:
    if veg_count is None:
        return ""
    if veg_count <= 0:
        return "➖"
    return "🥦" * min(veg_count, 3)


def humanize_since(dt: datetime.datetime | None) -> str:
    """Dutch relative-time label for a naive-UTC timestamp, e.g. "3 uur geleden".

    Returns "nooit" when dt is None.
    """
    if dt is None:
        return "nooit"
    now = datetime.datetime.utcnow()
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "zojuist"
    if secs < 60:
        return "zojuist"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min geleden"
    hours = mins // 60
    if hours < 24:
        return f"{hours} uur geleden"
    days = hours // 24
    if days == 1:
        return "gisteren"
    if days < 7:
        return f"{days} dagen geleden"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} {'week' if weeks == 1 else 'weken'} geleden"
    return dt.strftime("%-d %b %Y")


def dish_meta_chips(dish) -> list[str]:
    """Compact text chips summarising a dish's planning metadata, e.g.
    ["🐓 Kip", "⏱ 20–40 min", "🥦🥦"]. Empty when nothing is set.
    """
    chips: list[str] = []
    meat = meat_emoji(dish.meat_type)
    if meat:
        chips.append(f"{meat} {meat_label(dish.meat_type)}".strip())
    prep = prep_time_label(dish.prep_minutes)
    if prep:
        chips.append(f"⏱ {prep}")
    veg = veg_emoji(dish.veg_count)
    if veg:
        chips.append(veg)
    return chips
