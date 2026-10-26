"""Unit tests for organic-equivalent matching (services/organic.py)."""

from __future__ import annotations

from plus.models import Product
from pyplus.services.organic import best_organic_match, is_organic

_MILK = ["Zuivel, eieren, boter", "Verse zuivel", "Melk, karnemelk"]
_VEG = ["Aardappelen, groente, fruit", "Groente", "Witlof"]


def _p(sku, name, brand, subtitle="Per 1000 ml", price=1.0, cats=None) -> Product:
    return Product(
        sku=sku,
        name=name,
        subtitle=subtitle,
        brand=brand,
        slug="",
        image_url="",
        price=price,
        is_available=True,
        categories=_MILK if cats is None else cats,
    )


def test_own_brand_twin_matches():
    src = _p("1", "PLUS Halfvolle melk", "PLUS")
    bio = _p("2", "Biologisch PLUS Halfvolle melk", "Biologisch PLUS", price=1.39)
    other = _p("3", "Biologisch PLUS Karnemelk", "Biologisch PLUS")
    assert best_organic_match(src, [other, bio]) is bio


def test_other_brand_with_bio_marker_matches():
    src = _p("1", "Campina Halfvolle melk", "Campina")
    arla = _p("2", "Arla Bio halfvolle melk", "Arla")
    assert best_organic_match(src, [arla]) is arla


def test_different_category_never_matches():
    src = _p("1", "PLUS Witlof", "PLUS", "Per 500 gram", cats=_VEG)
    milk = _p("2", "Biologisch PLUS Witlof", "Biologisch PLUS", "Per 500 g")  # wrong leaf
    assert best_organic_match(src, [milk]) is None


def test_different_product_in_same_category_is_rejected():
    src = _p("1", "PLUS Halfvolle melk", "PLUS")
    karnemelk = _p("2", "Biologisch PLUS Karnemelk", "Biologisch PLUS")
    assert best_organic_match(src, [karnemelk]) is None


def test_closest_pack_size_wins_a_tie():
    src = _p("1", "PLUS Halfvolle melk", "PLUS", "Per 1500 ml")
    litre = _p("2", "Biologisch PLUS Halfvolle melk", "Biologisch PLUS", "Per 1000 ml", 1.3)
    big = _p("3", "Biologisch PLUS Halfvolle melk", "Biologisch PLUS", "Per 1500 ml", 1.9)
    assert best_organic_match(src, [litre, big]) is big


def test_source_without_category_has_no_match():
    src = _p("1", "PLUS Halfvolle melk", "PLUS", cats=[])
    bio = _p("2", "Biologisch PLUS Halfvolle melk", "Biologisch PLUS")
    assert best_organic_match(src, [bio]) is None


def test_is_organic_by_flag_or_name():
    assert is_organic("PLUS Halfvolle melk", "PLUS", flagged=True)
    assert is_organic("Biologisch PLUS Uien geel biologisch", "Biologisch PLUS")
    assert is_organic("BIO+ Fusilli volkoren", "BIO+")
    assert is_organic("Arla Bio halfvolle melk", "Arla")
    assert not is_organic("PLUS Halfvolle melk", "PLUS")
    assert not is_organic("BioToday Tahin naturel", "BioToday")  # brand alone: facet decides
