"""
Week-menu dish recommendation model — pure functions, no async, no DB access.

Produces a score per (dish_id, slot) using four signals weighted by user settings:

  afwisseling  — recency/variety: up-weight dishes not cooked recently
  vaste_dagen  — day-of-week habit: dishes often cooked on a specific day
  voordeel     — promotional advantage: dishes with ingredients on sale
  voorraad     — staple reuse: dishes that use staples predicted as due

compute_all_scores() is called by recompute_ml and stored as an ML artifact.
plan_week() greedily fills empty slots from the precomputed scores.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_DINNER_SLOTS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
_LUNCH_SLOTS = ["lunch1", "lunch2", "lunch3", "lunch4", "lunch5"]
_ALL_SLOTS = _DINNER_SLOTS + _LUNCH_SLOTS


@dataclass
class RecommenderArtifact:
    """Precomputed dish scores — {dish_id: {slot: score}}."""

    scores: dict[int, dict[str, float]] = field(default_factory=dict)
    computed_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


def compute_all_scores(
    dishes_with_ingredients: list[tuple],  # (Dish, list[DishIngredient])
    weekmenu_history: list,  # list[Weekmenu] (eager-loaded, with week_start)
    promo_skus: set[str],
    replenish_due_skus: set[str],
    weights: dict[str, float],
    reference_week: datetime.date,
) -> RecommenderArtifact:
    """
    Score every dish for every slot.

    weights keys: afwisseling, vaste_dagen, voordeel, voorraad
    """
    w_afw = weights.get("afwisseling", 0.8)
    w_dag = weights.get("vaste_dagen", 0.5)
    w_vdl = weights.get("voordeel", 0.6)
    w_vrrd = weights.get("voorraad", 0.4)

    # Build lookup: dish_id → list of (week_start, slot) historical placements
    history_by_dish: dict[int, list[tuple[datetime.date, str]]] = defaultdict(list)
    # And per-slot totals: slot → total placements (for day-of-week fraction)
    slot_totals: dict[str, int] = defaultdict(int)
    for row in weekmenu_history:
        if row.dish_id is not None:
            history_by_dish[row.dish_id].append((row.week_start, row.slot))
            slot_totals[row.slot] += 1

    artifact = RecommenderArtifact()

    for dish, ingredients in dishes_with_ingredients:
        dish_skus = {ing.sku for ing in ingredients if ing.sku and not ing.optional}
        slot_scores: dict[str, float] = {}

        for slot in _ALL_SLOTS:
            score = 0.0

            # ── Signal 1: Recency (afwisseling) ──────────────────────────────
            placements = history_by_dish.get(dish.id, [])
            if placements:
                latest = max(ws for ws, _ in placements)
                weeks_ago = (reference_week - latest).days / 7.0
                score += w_afw * min(weeks_ago / 4.0, 1.0)
            else:
                score += w_afw  # never cooked → maximum novelty

            # ── Signal 2: Day-of-week habit (vaste_dagen) ─────────────────────
            in_slot = sum(1 for _, s in placements if s == slot)
            total = max(slot_totals.get(slot, 1), 1)
            score += w_dag * (in_slot / total)

            # ── Signal 3: Promotional advantage (voordeel) ────────────────────
            if dish_skus:
                overlap = len(dish_skus & promo_skus) / len(dish_skus)
                score += w_vdl * overlap

            # ── Signal 4: Staple reuse (voorraad) ─────────────────────────────
            if dish_skus and replenish_due_skus:
                overlap = len(dish_skus & replenish_due_skus) / len(dish_skus)
                score += w_vrrd * overlap

            slot_scores[slot] = score

        artifact.scores[dish.id] = slot_scores

    return artifact


def plan_week(
    artifact: RecommenderArtifact,
    dish_ids: list[int],
    current_slots: dict[str, int | None],  # slot → dish_id | None
    n_dinner: int = 7,
    n_lunch: int = 5,
) -> dict[str, int]:
    """
    Greedily assign dishes to empty slots from precomputed scores.

    Returns {slot: dish_id} for all slots that were filled.
    Does not overwrite slots that already have a dish.
    """
    result: dict[str, int] = {}
    used_ids: set[int] = {v for v in current_slots.values() if v is not None}

    def _fill(slots: list[str]) -> None:
        for slot in slots:
            if current_slots.get(slot) is not None:
                continue  # already filled
            candidates = [
                (artifact.scores.get(did, {}).get(slot, 0.0), did)
                for did in dish_ids
                if did not in used_ids
            ]
            if not candidates:
                break
            _, best_id = max(candidates)
            result[slot] = best_id
            used_ids.add(best_id)

    _fill(_DINNER_SLOTS[:n_dinner])
    _fill(_LUNCH_SLOTS[:n_lunch])
    return result
