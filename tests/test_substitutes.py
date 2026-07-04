"""Unit tests for the substitute product scoring logic."""

from __future__ import annotations

from dataclasses import dataclass, field

from pyplus.ml.interface import UserSettings
from pyplus.services.substitutes import (
    _category_match_depth,
    _name_similarity,
    _passes_price_filter,
    _tokenize_name,
    score_candidate,
)


@dataclass
class _FakeProduct:
    sku: str = "999"
    name: str = "Test Product"
    subtitle: str = ""
    brand: str = ""
    slug: str = ""
    image_url: str = ""
    price: float = 2.50
    is_available: bool = True
    store_number: int = 0
    categories: list[str] = field(default_factory=list)


# ── _tokenize_name ────────────────────────────────────────────────────────────


def test_tokenize_removes_stop_words():
    tokens = _tokenize_name("Kaas van de boerderij")
    assert "kaas" in tokens
    assert "boerderij" in tokens
    assert "van" not in tokens
    assert "de" not in tokens


def test_tokenize_short_words_dropped():
    tokens = _tokenize_name("AH a x melk")
    assert "a" not in tokens  # single char dropped
    assert "x" not in tokens
    assert "ah" in tokens  # 2+ chars kept
    assert "melk" in tokens


def test_tokenize_empty():
    assert _tokenize_name("") == set()


# ── _name_similarity ─────────────────────────────────────────────────────────


def test_name_similarity_identical():
    a = {"tomaat", "cherry"}
    assert _name_similarity(a, a) == 1.0


def test_name_similarity_disjoint():
    assert _name_similarity({"appel"}, {"peer"}) == 0.0


def test_name_similarity_partial():
    sim = _name_similarity({"cherry", "tomaat", "biologisch"}, {"cherry", "tomaat", "roma"})
    assert 0.4 < sim < 0.6  # 2/4 Jaccard


def test_name_similarity_empty():
    assert _name_similarity(set(), {"x"}) == 0.0
    assert _name_similarity({"x"}, set()) == 0.0


# ── _category_match_depth ────────────────────────────────────────────────────


def test_category_exact_deepest():
    src = ["Groente", "Tomaten", "Cherrytomaten"]
    cand = ["Groente", "Tomaten", "Cherrytomaten"]
    assert _category_match_depth(src, cand) == 3


def test_category_partial():
    src = ["Groente", "Tomaten", "Cherrytomaten"]
    cand = ["Groente", "Tomaten", "Pomodori"]
    assert _category_match_depth(src, cand) == 2


def test_category_only_top():
    src = ["Groente", "Tomaten"]
    cand = ["Groente", "Sla"]
    assert _category_match_depth(src, cand) == 1


def test_category_no_match():
    assert _category_match_depth(["Zuivel"], ["Brood"]) == 0


def test_category_empty():
    assert _category_match_depth([], ["Groente"]) == 0
    assert _category_match_depth(["Groente"], []) == 0


# ── _passes_price_filter ─────────────────────────────────────────────────────


def test_price_filter_any():
    assert _passes_price_filter(5.0, 2.0, "any")
    assert _passes_price_filter(1.0, 2.0, "any")


def test_price_filter_cheaper():
    assert _passes_price_filter(1.50, 2.00, "cheaper")
    assert not _passes_price_filter(2.50, 2.00, "cheaper")
    assert not _passes_price_filter(2.00, 2.00, "cheaper")


def test_price_filter_similar():
    assert _passes_price_filter(2.10, 2.00, "similar")  # within 25%
    assert _passes_price_filter(1.60, 2.00, "similar")
    assert not _passes_price_filter(3.00, 2.00, "similar")  # >25%


# ── score_candidate ──────────────────────────────────────────────────────────


def test_score_same_category_high():
    settings = UserSettings()
    source_cats = ["Groente", "Tomaten"]
    product = _FakeProduct(categories=["Groente", "Tomaten"])
    s = score_candidate({"tomaat"}, source_cats, 2.0, "", product, False, settings)
    assert s > 0


def test_score_brand_boost():
    settings = UserSettings(sub_prefer_same_brand=True)
    p1 = _FakeProduct(brand="AH", categories=["Groente"])
    p2 = _FakeProduct(brand="Jumbo", categories=["Groente"])
    s1 = score_candidate(set(), ["Groente"], 2.0, "AH", p1, False, settings)
    s2 = score_candidate(set(), ["Groente"], 2.0, "AH", p2, False, settings)
    assert s1 > s2


def test_score_bought_boost():
    settings = UserSettings(sub_prefer_bought=True)
    product = _FakeProduct(categories=["Groente"])
    s_bought = score_candidate(set(), ["Groente"], 2.0, "", product, True, settings)
    s_not = score_candidate(set(), ["Groente"], 2.0, "", product, False, settings)
    assert s_bought > s_not


def test_score_bought_off():
    settings = UserSettings(sub_prefer_bought=False)
    product = _FakeProduct(categories=["Groente"])
    s_bought = score_candidate(set(), ["Groente"], 2.0, "", product, True, settings)
    s_not = score_candidate(set(), ["Groente"], 2.0, "", product, False, settings)
    assert s_bought == s_not


def test_score_custom_weights():
    settings = UserSettings(sub_weight_category=10.0, sub_weight_name=0.0)
    product = _FakeProduct(name="Heel ander product", categories=["Groente", "Tomaten"])
    s = score_candidate({"komkommer"}, ["Groente", "Tomaten"], 2.0, "", product, False, settings)
    # Category weight dominates — score should be high even without name overlap
    assert s > 5.0


def test_score_zero_price():
    settings = UserSettings()
    product = _FakeProduct(price=3.0, categories=[])
    s = score_candidate(set(), [], 0.0, "", product, False, settings)
    # price_proximity returns 1.0 when source_price is 0
    assert s >= settings.sub_weight_price
