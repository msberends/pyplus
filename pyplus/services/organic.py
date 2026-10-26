"""
Organic ("bio") equivalents for regular products.

For a product, find the organic product in the store catalogue that is the same
thing: same most-specific PLUS category, and the same name once brand words and
organic markers are stripped — e.g.

    PLUS Halfvolle melk  →  Biologisch PLUS Halfvolle melk
    PLUS Witlof          →  Biologisch PLUS Witlof

Organic membership comes from PLUS's own "Keurmerken: Biologisch" facet
(product_cache.is_organic, kept by the refresh_organic_flags job), topped up by
the name: the facet misses some products ("Biologisch PLUS Uien geel biologisch").
DB-only — no PLUS call — so it is safe on the open path. Deterministic, no ML.
"""

from __future__ import annotations

import time
from dataclasses import replace

from plus.models import Product
from pyplus.services.categories import parse_categories
from pyplus.services.savings import _pack_base
from pyplus.services.substitutes import _name_similarity, _tokenize_name

# Words that mark a product as organic rather than say what it is.
_ORGANIC_MARKERS = frozenset({"bio", "biologisch", "biologische", "organic", "eko"})
_MIN_SIMILARITY = 0.5  # Jaccard of the stripped names
_CACHE_TTL = 900.0  # s — the organic set changes weekly at most

_organic_cache: dict[int, tuple[float, list[Product]]] = {}


def is_organic(name: str, brand: str, flagged: bool = False) -> bool:
    """Organic by PLUS's facet flag or by an organic marker in the name/brand."""
    return flagged or bool(_tokenize_name(f"{name} {brand}") & _ORGANIC_MARKERS)


def _core_tokens(product: Product) -> set[str]:
    """Name tokens that describe the product itself (no brand, no organic marker)."""
    return _tokenize_name(product.name) - _tokenize_name(product.brand) - _ORGANIC_MARKERS


def _leaf(product: Product) -> str:
    return product.categories[-1] if product.categories else ""


def _pack_distance(a: Product, b: Product) -> float:
    """Relative pack-size difference (0 = same size); 1 when not comparable."""
    size_a, unit_a = _pack_base(a.subtitle)
    size_b, unit_b = _pack_base(b.subtitle)
    if not size_a or not size_b or unit_a != unit_b:
        return 1.0
    return abs(size_a - size_b) / max(size_a, size_b)


def best_organic_match(source: Product, candidates: list[Product]) -> Product | None:
    """Pick the organic candidate that is the same product as `source`, or None.

    Candidates must share the source's most-specific category and a stripped-name
    similarity of at least _MIN_SIMILARITY. Ties go to the closest pack size,
    then the lower price.
    """
    leaf = _leaf(source)
    core = _core_tokens(source)
    if not leaf or not core:
        return None
    best: tuple[float, float, float] | None = None
    best_product: Product | None = None
    for cand in candidates:
        if cand.sku == source.sku or _leaf(cand) != leaf:
            continue
        sim = _name_similarity(core, _core_tokens(cand))
        if sim < _MIN_SIMILARITY:
            continue
        key = (-sim, _pack_distance(source, cand), cand.price)
        if best is None or key < best:
            best, best_product = key, cand
    return best_product


def _to_product(row) -> Product:
    return Product(
        sku=row.sku,
        name=row.name,
        subtitle=row.subtitle or "",
        brand=row.brand or "",
        slug=row.slug or "",
        image_url=row.image_url or "",
        price=row.price or 0.0,
        is_available=bool(row.is_available),
        store_number=row.store_number,
        categories=parse_categories(row.categories_json),
    )


async def _organic_products(store_number: int) -> list[Product]:
    """The store's available organic products, cached in-process for _CACHE_TTL."""
    hit = _organic_cache.get(store_number)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rows = await repo.get_organic_products(db, store_number)
    products = [_to_product(r) for r in rows if is_organic(r.name, r.brand or "", r.is_organic)]
    _organic_cache[store_number] = (time.monotonic(), products)
    return products


async def get_organic_alternatives(store_number: int, skus: list[str]) -> dict[str, Product]:
    """Map each regular sku to its organic equivalent; skus without one are absent."""
    skus = [s for s in skus if s]
    if not store_number or not skus:
        return {}
    candidates = await _organic_products(store_number)
    if not candidates:
        return {}
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rows = await repo.get_product_cache_by_skus(db, store_number, skus)
    result: dict[str, Product] = {}
    for sku, row in rows.items():
        if is_organic(row.name, row.brand or "", row.is_organic):
            continue
        match = best_organic_match(_to_product(row), candidates)
        if match is not None:
            result[sku] = replace(match)
    return result
