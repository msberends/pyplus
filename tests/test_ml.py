"""
Unit tests for M11 ML layer.

Covers:
  - PurchaseRecord / UserSettings (interface)
  - replenish: due-score, reason strings, dating-gap rule
  - promo_match: scoring, sort order, in-weekmenu boost
  - recommender: recency, day-of-week habit, plan_week slot filling
  - services/history: build_purchase_history merge logic
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyplus.ml.interface import PurchaseRecord, UserSettings
from pyplus.ml.promo_match import score_promotion, sort_promotions_by_relevance
from pyplus.ml.recommender import compute_all_scores, plan_week
from pyplus.ml.replenish import (
    ReplenishScore,
    compute_replenishment_score,
    sort_fixed_products_by_due,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _rec(
    sku, ever_bought=True, last_bought=None, order_count=0, frequency=None, dates_complete=False
):
    return PurchaseRecord(
        sku=sku,
        name=sku,
        category=None,
        ever_bought=ever_bought,
        last_bought=last_bought,
        order_count=order_count,
        frequency=frequency,
        dates_complete=dates_complete,
    )


def _promo(slug, sku="", is_single=True, is_delivery=False):
    p = MagicMock()
    p.slug = slug
    p.sku = sku
    p.is_single_product = is_single
    p.is_free_delivery = is_delivery
    return p


def _dish(dish_id, name):
    d = MagicMock()
    d.id = dish_id
    d.name = name
    d.is_dinner = True
    d.rating = None
    d.is_unhealthy = False
    d.is_restaurant = False
    return d


def _ing(sku, optional=False):
    i = MagicMock()
    i.sku = sku
    i.optional = optional
    return i


def _wm_row(week_start, slot, dish_id):
    r = MagicMock()
    r.week_start = week_start
    r.slot = slot
    r.dish_id = dish_id
    return r


# ── UserSettings ──────────────────────────────────────────────────────────────


def test_usersettings_defaults_all_off():
    s = UserSettings()
    assert s.ml_enabled is False
    assert s.ml_autopilot is False


def test_usersettings_roundtrip():
    s = UserSettings(ml_enabled=True, ml_replenish=False, ntfy_topic="pyplus")
    restored = UserSettings.model_validate_json(s.model_dump_json())
    assert restored.ml_enabled is True
    assert restored.ml_replenish is False
    assert restored.ntfy_topic == "pyplus"


# ── Replenishment ─────────────────────────────────────────────────────────────


def test_replenish_due():
    today = datetime.date(2026, 6, 2)
    record = _rec(
        "melk",
        last_bought=datetime.date(2026, 5, 25),
        order_count=5,
        frequency=1.0,
        dates_complete=True,
    )
    score = compute_replenishment_score(record, today)
    # 8 days since last, interval = 7 → due_score = 8/7 > 1
    assert score.is_due is True
    assert score.due_score > 1.0
    assert "wekelijks" in score.reason
    assert "8 dagen geleden" in score.reason
    assert score.dates_complete is True


def test_replenish_not_yet_due():
    today = datetime.date(2026, 6, 2)
    record = _rec(
        "melk",
        last_bought=datetime.date(2026, 6, 1),
        order_count=5,
        frequency=1.0,
        dates_complete=True,
    )
    score = compute_replenishment_score(record, today)
    # 1 day since last, interval = 7 → due_score = 1/7 ≈ 0.14
    assert score.is_due is False
    assert score.due_score < 1.0


def test_replenish_dating_gap():
    """In-store only: dates_complete=False → soft 'vaak gekocht' signal, not marked due."""
    today = datetime.date(2026, 6, 2)
    record = _rec("kaas", ever_bought=True, dates_complete=False)
    score = compute_replenishment_score(record, today)
    assert score.is_due is False
    assert score.dates_complete is False
    assert "vaak gekocht" in score.reason


def test_replenish_none_record():
    score = compute_replenishment_score(None, datetime.date.today())
    assert score.due_score == 0.0
    assert score.is_due is False


def test_replenish_sort_due_first():
    due = ReplenishScore("a", due_score=1.5, reason="", is_due=True, dates_complete=True)
    soft = ReplenishScore("b", due_score=0.3, reason="", is_due=False, dates_complete=False)
    not_due = ReplenishScore("c", due_score=0.5, reason="", is_due=False, dates_complete=True)

    ordered = sort_fixed_products_by_due(["a", "b", "c"], {"a": due, "b": soft, "c": not_due})
    assert ordered[0] == "a"


# ── Promo-match ───────────────────────────────────────────────────────────────


def test_promo_score_ever_bought():
    promo = _promo("slug1", sku="x")
    history = {"x": _rec("x", ever_bought=True)}
    score = score_promotion(promo, history, set())
    assert score >= 1.0


def test_promo_score_never_bought():
    promo = _promo("slug1", sku="x")
    score = score_promotion(promo, {}, set())
    assert score == 0.0


def test_promo_score_in_weekmenu_boost():
    promo = _promo("slug1", sku="kip")
    history = {"kip": _rec("kip", ever_bought=True)}
    score_without = score_promotion(promo, history, set())
    score_with = score_promotion(promo, history, {"kip"})
    assert score_with > score_without + 3.0  # weekmenu boost is +4


def test_promo_score_free_delivery_low():
    promo = _promo("delivery", is_delivery=True)
    assert score_promotion(promo, {}, set()) < 0.1


def test_promo_sort_relevance():
    p_relevant = _promo("r", sku="r_sku")
    p_irrelevant = _promo("i", sku="i_sku")
    history = {
        "r_sku": _rec(
            "r_sku",
            ever_bought=True,
            frequency=2.0,
            dates_complete=True,
            order_count=10,
            last_bought=datetime.date(2026, 6, 1),
        )
    }
    sorted_promos = sort_promotions_by_relevance([p_irrelevant, p_relevant], history, set())
    assert sorted_promos[0] is p_relevant


# ── Recommender ───────────────────────────────────────────────────────────────


def test_recommender_no_history_max_novelty():
    """With no weekmenu history, all dishes get the full afwisseling weight."""
    dish = _dish(1, "Kip")
    artifact = compute_all_scores(
        [(dish, [_ing("sku1")])],
        weekmenu_history=[],
        promo_skus=set(),
        replenish_due_skus=set(),
        weights={"afwisseling": 0.8, "vaste_dagen": 0.5, "voordeel": 0.6, "voorraad": 0.4},
        reference_week=datetime.date(2026, 6, 2),
    )
    assert 1 in artifact.scores
    assert "ma" in artifact.scores[1]
    # Should get full afwisseling score since never cooked
    assert artifact.scores[1]["ma"] >= 0.8


def test_recommender_recent_dish_lower_score():
    """A dish cooked last week should score lower than one cooked 8 weeks ago."""
    dish = _dish(1, "Pasta")
    ref = datetime.date(2026, 6, 2)  # Monday
    last_week = ref - datetime.timedelta(weeks=1)
    eight_weeks_ago = ref - datetime.timedelta(weeks=8)

    history_recent = [_wm_row(last_week, "ma", 1)]
    history_old = [_wm_row(eight_weeks_ago, "ma", 1)]

    weights = {"afwisseling": 1.0, "vaste_dagen": 0.0, "voordeel": 0.0, "voorraad": 0.0}

    art_recent = compute_all_scores([(dish, [])], history_recent, set(), set(), weights, ref)
    art_old = compute_all_scores([(dish, [])], history_old, set(), set(), weights, ref)

    assert art_recent.scores[1]["ma"] < art_old.scores[1]["ma"]


def test_plan_week_fills_empty_slots():
    dish1 = _dish(1, "A")
    dish2 = _dish(2, "B")
    artifact = compute_all_scores(
        [(dish1, []), (dish2, [])],
        weekmenu_history=[],
        promo_skus=set(),
        replenish_due_skus=set(),
        weights={"afwisseling": 1.0, "vaste_dagen": 0.0, "voordeel": 0.0, "voorraad": 0.0},
        reference_week=datetime.date(2026, 6, 2),
    )
    current = {
        "ma": None,
        "di": None,
        "wo": None,
        "do": None,
        "vr": None,
        "za": None,
        "zo": None,
        "lunch1": None,
        "lunch2": None,
        "lunch3": None,
        "lunch4": None,
        "lunch5": None,
    }
    result = plan_week(artifact, [1, 2], current, n_dinner=2, n_lunch=0)
    # Should fill 2 dinner slots with different dishes
    assert len(result) == 2
    assert len(set(result.values())) == 2  # no duplicates


def test_plan_week_never_suggests_restaurant_dish():
    """A dish flagged is_restaurant must never be picked, even as the only candidate."""
    dish1 = _dish(1, "A")
    dish2 = _dish(2, "McDonald's")
    dish2.is_restaurant = True
    artifact = compute_all_scores(
        [(dish1, []), (dish2, [])],
        weekmenu_history=[],
        promo_skus=set(),
        replenish_due_skus=set(),
        weights={"afwisseling": 1.0, "vaste_dagen": 0.0, "voordeel": 0.0, "voorraad": 0.0},
        reference_week=datetime.date(2026, 6, 2),
    )
    current = {"ma": None, "di": None}
    result = plan_week(artifact, [1, 2], current, n_dinner=2, n_lunch=0)
    assert 2 not in result.values()


def test_plan_week_respects_existing():
    """Already-filled slots are not overwritten."""
    dish1 = _dish(1, "A")
    artifact = compute_all_scores(
        [(dish1, [])],
        [],
        set(),
        set(),
        {"afwisseling": 1.0, "vaste_dagen": 0.0, "voordeel": 0.0, "voorraad": 0.0},
        datetime.date(2026, 6, 2),
    )
    current = {"ma": 99, "di": None}  # ma already filled
    result = plan_week(artifact, [1], current, n_dinner=2, n_lunch=0)
    assert "ma" not in result  # should not overwrite


# ── services/history ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_history_fuses_sources():
    """ever_bought from catalogue, dates from order cache."""
    from pyplus.services.history import build_purchase_history

    cat_row = MagicMock()
    cat_row.sku = "melk"
    cat_row.name = "Melk"
    cat_row.categories_json = "[]"

    item1 = MagicMock()
    item1.sku = "melk"
    item1.name = "Melk"
    item1.quantity = 1
    item2 = MagicMock()
    item2.sku = "melk"
    item2.name = "Melk"
    item2.quantity = 1
    d1 = datetime.date(2026, 5, 1)
    d2 = datetime.date(2026, 5, 15)

    with patch("pyplus.services.history.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        cat_exec = MagicMock()
        cat_exec.scalars.return_value.all.return_value = [cat_row]

        order_exec = MagicMock()
        order_exec.all.return_value = [(item1, d1), (item2, d2)]

        mock_db.execute = AsyncMock(side_effect=[cat_exec, order_exec])

        records = await build_purchase_history(user_id=1)

    assert len(records) == 1
    r = records[0]
    assert r.sku == "melk"
    assert r.ever_bought is True
    assert r.last_bought == d2
    assert r.order_count == 2
    assert r.dates_complete is True
    assert r.frequency is not None  # 14-day gap → ~0.5 buys/week


@pytest.mark.asyncio
async def test_build_history_in_store_only():
    """Item in catalogue but not in any order → ever_bought=True, no dates."""
    from pyplus.services.history import build_purchase_history

    cat_row = MagicMock()
    cat_row.sku = "kaas"
    cat_row.name = "Kaas"
    cat_row.categories_json = "[]"

    with patch("pyplus.services.history.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        cat_exec = MagicMock()
        cat_exec.scalars.return_value.all.return_value = [cat_row]
        order_exec = MagicMock()
        order_exec.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[cat_exec, order_exec])

        records = await build_purchase_history(user_id=1)

    assert len(records) == 1
    r = records[0]
    assert r.ever_bought is True
    assert r.last_bought is None
    assert r.frequency is None
    assert r.dates_complete is False
