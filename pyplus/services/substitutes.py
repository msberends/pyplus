"""Substitute product finder — deterministic scoring, no ML."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from plus.models import Product
from pyplus.services.categories import parse_categories

if TYPE_CHECKING:
    from pyplus.ml.interface import UserSettings

log = logging.getLogger(__name__)

_STOP_WORDS = frozenset(
    "de het een en van voor met uit bij per in op aan door te ook of als geen".split()
)


@dataclass
class SubstituteCandidate:
    product: Product
    score: float
    match_reason: str  # "category" | "name" | "brand" | "bought"


def _tokenize_name(name: str) -> set[str]:
    tokens = set(re.findall(r"[a-zA-Zà-ÿ]{2,}", name.lower()))
    return tokens - _STOP_WORDS


def _name_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _category_match_depth(source: list[str], candidate: list[str]) -> int:
    """Return 1-indexed depth of deepest shared category, or 0 for no match."""
    depth = 0
    for i, cat in enumerate(source):
        if cat in candidate:
            depth = i + 1
    return depth


def _price_proximity(source_price: float, candidate_price: float) -> float:
    if source_price <= 0:
        return 1.0
    return max(0.0, 1.0 - abs(candidate_price - source_price) / source_price)


def _passes_price_filter(candidate_price: float, source_price: float, price_range: str) -> bool:
    if source_price <= 0:
        return True
    if price_range == "cheaper":
        return candidate_price < source_price
    if price_range == "similar":
        return abs(candidate_price - source_price) <= source_price * 0.25
    return True


def score_candidate(
    source_name_tokens: set[str],
    source_categories: list[str],
    source_price: float,
    source_brand: str,
    candidate_product: Product,
    is_previously_bought: bool,
    settings: UserSettings,
) -> float:
    cand_cats = candidate_product.categories or []
    cand_tokens = _tokenize_name(candidate_product.name)

    cat_depth = _category_match_depth(source_categories, cand_cats)
    max_depth = max(len(source_categories), 1)
    cat_score = (cat_depth / max_depth) * settings.sub_weight_category

    name_score = _name_similarity(source_name_tokens, cand_tokens) * settings.sub_weight_name

    brand_score = 0.0
    brand_max = 0.0
    if source_brand:
        brand_max = settings.sub_weight_brand * (2.0 if settings.sub_prefer_same_brand else 1.0)
        if candidate_product.brand.lower() == source_brand.lower():
            brand_score = brand_max

    price_score = (
        _price_proximity(source_price, candidate_product.price) * settings.sub_weight_price
    )

    bought_score = 0.0
    bought_max = 0.0
    if settings.sub_prefer_bought:
        bought_max = settings.sub_weight_bought
        if is_previously_bought:
            bought_score = bought_max

    raw = cat_score + name_score + brand_score + price_score + bought_score

    # Normalise: express as fraction of the achievable max given available signals.
    # When source has no categories, the category weight (highest!) contributes 0
    # to both raw and max, so scores stay meaningful.
    cat_max = settings.sub_weight_category if source_categories else 0.0
    achievable_max = (
        cat_max + settings.sub_weight_name + brand_max + settings.sub_weight_price + bought_max
    )
    if achievable_max <= 0:
        return 0.0
    return (raw / achievable_max) * 10.0


def _primary_reason(
    source_categories: list[str],
    source_name_tokens: set[str],
    source_brand: str,
    candidate: Product,
    is_bought: bool,
) -> str:
    cand_cats = candidate.categories or []
    if _category_match_depth(source_categories, cand_cats) > 0:
        return "category"
    if source_brand and candidate.brand.lower() == source_brand.lower():
        return "brand"
    if is_bought:
        return "bought"
    return "name"


async def find_substitutes(
    store_number: int,
    sku: str,
    *,
    product_name: str,
    brand: str = "",
    categories: list[str] | None = None,
    price: float = 0.0,
    user_id: int | None = None,
    settings: UserSettings | None = None,
) -> list[SubstituteCandidate]:
    """Find and rank substitute products for an unavailable SKU."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.interface import UserSettings as _US

    if settings is None:
        settings = _US()
    categories = categories or []
    limit = settings.sub_max_results
    exclude = {sku}
    source_tokens = _tokenize_name(product_name)

    async with AsyncSessionLocal() as db:
        cat_rows = []
        if categories:
            cat_rows = await repo.find_category_matches(
                db, store_number, categories, exclude_skus=exclude, limit=limit * 3
            )

        name_rows = []
        if len(cat_rows) < limit:
            search_tokens = source_tokens - _tokenize_name(brand) if brand else source_tokens
            if not search_tokens:
                search_tokens = source_tokens
            keywords = " ".join(sorted(search_tokens)[:3])
            if keywords:
                name_rows = await repo.search_product_cache(
                    db, store_number, keywords, limit=limit * 2
                )
            if len(cat_rows) + len(name_rows) < limit and len(source_tokens) > 1:
                for token in sorted(source_tokens, key=len, reverse=True)[:2]:
                    if len(token) >= 4:
                        extra = await repo.search_product_cache(
                            db, store_number, token, limit=limit * 2
                        )
                        name_rows.extend(extra)
                        if len(cat_rows) + len(name_rows) >= limit:
                            break

        bought_skus: set[str] = set()
        if user_id is not None and settings.sub_prefer_bought:
            all_skus = [r.sku for r in cat_rows] + [r.sku for r in name_rows]
            if all_skus:
                bought_map = await repo.get_purchased_products_by_skus(db, user_id, all_skus)
                bought_skus = set(bought_map.keys())

    seen: set[str] = set(exclude)
    merged = []
    for row in cat_rows + name_rows:
        if row.sku in seen:
            continue
        seen.add(row.sku)
        if not row.is_available:
            continue
        cats = parse_categories(getattr(row, "categories_json", None))
        product = Product(
            sku=row.sku,
            name=row.name,
            subtitle=row.subtitle or "",
            brand=row.brand or "",
            slug=row.slug or "",
            image_url=row.image_url or "",
            price=row.price or 0.0,
            is_available=True,
            store_number=store_number,
            categories=cats,
        )
        merged.append(product)

    filtered = [p for p in merged if _passes_price_filter(p.price, price, settings.sub_price_range)]

    scored: list[SubstituteCandidate] = []
    for product in filtered:
        is_bought = product.sku in bought_skus
        s = score_candidate(source_tokens, categories, price, brand, product, is_bought, settings)
        reason = _primary_reason(categories, source_tokens, brand, product, is_bought)
        scored.append(SubstituteCandidate(product=product, score=s, match_reason=reason))

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]
