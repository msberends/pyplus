"""Small presentation helpers shared across UI components.

Kept free of NiceGUI imports so it stays trivially unit-testable.
"""

from __future__ import annotations

import datetime
import urllib.parse

_PRODUCT_BASE = "https://www.plus.nl/product/"
_SEARCH_BASE = "https://www.plus.nl/zoekresultaten?SearchTerm="
_CTFASSETS_HOST = "images.ctfassets.net"


def alt_text(name: str) -> str:
    """Sanitize a product name for use as an HTML alt / aria-label attribute value.

    Strips characters that would break the quoted NiceGUI props string.
    """
    return (name or "").replace('"', "").replace("\\", "").strip()


def thumbnail_url(url: str, size: int = 44, fit: str = "thumb") -> str:
    """Return a resized Contentful image URL (w=size×3, WebP).

    fit="thumb"  — center-crop to a square (default, compact rows/search).
    fit="pad"    — full image padded to a square (larger product cards).

    A 3× DPR factor covers HiDPI/Retina displays; still 10–30× smaller than
    the 2000 px originals PLUS.nl serves by default.  Non-ctfassets URLs are
    returned unchanged.
    """
    if not url or _CTFASSETS_HOST not in url:
        return url
    px = size * 3
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}w={px}&h={px}&fit={fit}&fm=webp"


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


_STARCH_EMOJI = {
    "aardappels": "🥔",
    "pasta": "🍝",
    "rijst": "🍚",
    "noedels": "🍜",
    "deeg": "🥟",
    "wraps": "🌯",
    "geen_anders": "➖",
}
_STARCH_LABEL = {
    "aardappels": "Aardappels",
    "pasta": "Pasta",
    "rijst": "Rijst",
    "noedels": "Noedels",
    "deeg": "Deeg",
    "wraps": "Wraps",
    "geen_anders": "Geen/anders",
}

_COOKING_EMOJI = {
    "kookplaat": "🍳",
    "oven": "♨️",
    "magnetron": "📡",
    "airfryer": "🌀",
}
_COOKING_LABEL = {
    "kookplaat": "Kookplaat",
    "oven": "Oven",
    "magnetron": "Magnetron",
    "airfryer": "Airfryer",
}


def starch_emoji(starch_type: str | None) -> str:
    return _STARCH_EMOJI.get((starch_type or "").lower(), "")


def starch_label(starch_type: str | None) -> str:
    return _STARCH_LABEL.get((starch_type or "").lower(), "")


def cooking_emoji(method: str | None) -> str:
    return _COOKING_EMOJI.get((method or "").lower(), "")


def cooking_label(method: str | None) -> str:
    return _COOKING_LABEL.get((method or "").lower(), "")


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
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
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


def parse_cooking_methods(dish) -> list[str]:
    """Parse the cooking_methods JSON list from a dish."""
    import json

    raw = getattr(dish, "cooking_methods", "[]") or "[]"
    try:
        return json.loads(raw) if isinstance(raw, str) else list(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def dish_meta_chips(dish) -> list[str]:
    """Compact text chips summarising a dish's planning metadata, e.g.
    ["🐓 Kip", "🥔 Aardappels", "🍳 Kookplaat", "⏱ 20–40 min", "🥦🥦", "❄️"].
    Empty when nothing is set.
    """
    chips: list[str] = []
    meat = meat_emoji(dish.meat_type)
    if meat:
        chips.append(f"{meat} {meat_label(dish.meat_type)}".strip())
    starch = starch_emoji(getattr(dish, "starch_type", None))
    if starch:
        chips.append(f"{starch} {starch_label(dish.starch_type)}".strip())
    for method in parse_cooking_methods(dish):
        emoji = cooking_emoji(method)
        if emoji:
            chips.append(f"{emoji} {cooking_label(method)}".strip())
    prep = prep_time_label(dish.prep_minutes)
    if prep:
        chips.append(f"⏱ {prep}")
    veg = veg_emoji(dish.veg_count)
    if veg:
        chips.append(veg)
    if getattr(dish, "is_cold", False):
        chips.append("❄️")
    return chips
