"""
Week-menu dish recommendation model — pure functions, no async, no DB access.

Produces a score per (dish_id, slot) using six signals weighted by user settings:

  afwisseling       — recency/variety with exponential decay
  vaste_dagen       — day-of-week habit with decay-weighted counting
  voordeel          — promotional advantage: ingredients on sale
  voorraad          — staple reuse: ingredients predicted as due
  ingredient_overlap — shared ingredients across the week (waste reduction)
  budget            — prefer cheaper dishes

compute_all_scores() is called by recompute_ml and stored as an ML artifact.
plan_week() uses constraint satisfaction + configurable selection to fill empty slots.
"""

from __future__ import annotations

import datetime
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyplus.ml.interface import UserSettings

_DINNER_SLOTS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
_LUNCH_SLOTS = ["lunch1", "lunch2", "lunch3", "lunch4", "lunch5"]
_ALL_SLOTS = _DINNER_SLOTS + _LUNCH_SLOTS
_LN2 = math.log(2)


@dataclass
class DishMeta:
    """Lightweight dish attributes cached in the artifact for plan_week filtering."""

    meat_type: str | None = None
    starch_type: str | None = None
    prep_minutes: int | None = None
    veg_count: int | None = None
    cooking_methods: list[str] = field(default_factory=list)
    is_cold: bool = False
    ingredient_skus: frozenset[str] = field(default_factory=frozenset)
    estimated_cost: float | None = None
    last_cooked_weeks_ago: float | None = None


@dataclass
class RecommenderArtifact:
    """Precomputed dish scores — {dish_id: {slot: score}}."""

    scores: dict[int, dict[str, float]] = field(default_factory=dict)
    computed_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    )
    dish_meta: dict[int, DishMeta] = field(default_factory=dict)
    never_cooked_ids: set[int] = field(default_factory=set)


def compute_all_scores(
    dishes_with_ingredients: list[tuple],
    weekmenu_history: list,
    promo_skus: set[str],
    replenish_due_skus: set[str],
    weights: dict[str, float],
    reference_week: datetime.date,
    settings: UserSettings | None = None,
    ingredient_prices: dict[str, float] | None = None,
) -> RecommenderArtifact:
    """Score every dish for every slot using six weighted signals."""
    w_afw = weights.get("afwisseling", 0.8)
    w_dag = weights.get("vaste_dagen", 0.5)
    w_vdl = weights.get("voordeel", 0.6)
    w_vrrd = weights.get("voorraad", 0.4)
    w_ovlp = weights.get("ingredient_overlap", 0.0)
    w_bdgt = weights.get("budget", 0.0)

    halflife = settings.ml_trend_decay_halflife if settings else 8.0
    if halflife <= 0:
        halflife = 8.0
    ingredient_prices = ingredient_prices or {}

    history_by_dish: dict[int, list[tuple[datetime.date, str]]] = defaultdict(list)
    slot_totals_weighted: dict[str, float] = defaultdict(float)
    for row in weekmenu_history:
        if row.dish_id is not None:
            history_by_dish[row.dish_id].append((row.week_start, row.slot))
            weeks_ago = (reference_week - row.week_start).days / 7.0
            decay = math.exp(-_LN2 * weeks_ago / halflife) if weeks_ago >= 0 else 1.0
            slot_totals_weighted[row.slot] += decay

    all_dish_skus: dict[int, set[str]] = {}
    max_cost = 0.0
    dish_costs: dict[int, float] = {}
    for dish, ingredients in dishes_with_ingredients:
        skus = {ing.sku for ing in ingredients if ing.sku and not ing.optional}
        all_dish_skus[dish.id] = skus
        if ingredient_prices:
            cost = sum(ingredient_prices.get(s, 0.0) for s in skus)
            dish_costs[dish.id] = cost
            max_cost = max(max_cost, cost)

    artifact = RecommenderArtifact()
    never_cooked: set[int] = set()

    for dish, ingredients in dishes_with_ingredients:
        dish_skus = all_dish_skus[dish.id]
        slot_scores: dict[str, float] = {}

        placements = history_by_dish.get(dish.id, [])
        if not placements:
            never_cooked.add(dish.id)

        import json as _json

        raw_cm = getattr(dish, "cooking_methods", "[]") or "[]"
        try:
            cm_list = _json.loads(raw_cm) if isinstance(raw_cm, str) else list(raw_cm)
        except Exception:
            cm_list = []

        meta = DishMeta(
            meat_type=getattr(dish, "meat_type", None),
            starch_type=getattr(dish, "starch_type", None),
            prep_minutes=getattr(dish, "prep_minutes", None),
            veg_count=getattr(dish, "veg_count", None),
            cooking_methods=cm_list,
            is_cold=bool(getattr(dish, "is_cold", False)),
            ingredient_skus=frozenset(dish_skus),
            estimated_cost=dish_costs.get(dish.id),
        )

        if placements:
            latest = max(ws for ws, _ in placements)
            weeks_ago = (reference_week - latest).days / 7.0
            meta.last_cooked_weeks_ago = weeks_ago

        for slot in _ALL_SLOTS:
            score = 0.0

            # Signal 1: Recency with exponential decay
            if placements:
                weeks_ago_val = meta.last_cooked_weeks_ago or 0.0
                score += w_afw * (1.0 - math.exp(-_LN2 * weeks_ago_val / halflife))
            else:
                score += w_afw

            # Signal 2: Day-of-week habit with decay-weighted counting
            slot_weight = 0.0
            for ws, s in placements:
                if s == slot:
                    wa = (reference_week - ws).days / 7.0
                    slot_weight += math.exp(-_LN2 * wa / halflife) if wa >= 0 else 1.0
            total_w = max(slot_totals_weighted.get(slot, 1.0), 0.01)
            score += w_dag * (slot_weight / total_w)

            # Signal 3: Promotional advantage
            if dish_skus:
                score += w_vdl * (len(dish_skus & promo_skus) / len(dish_skus))

            # Signal 4: Staple reuse
            if dish_skus and replenish_due_skus:
                score += w_vrrd * (len(dish_skus & replenish_due_skus) / len(dish_skus))

            # Signal 5: Ingredient overlap (average Jaccard with all other dishes)
            if w_ovlp > 0 and dish_skus:
                jaccard_sum = 0.0
                n_others = 0
                for other_id, other_skus in all_dish_skus.items():
                    if other_id != dish.id and other_skus:
                        inter = len(dish_skus & other_skus)
                        union = len(dish_skus | other_skus)
                        jaccard_sum += inter / union if union else 0.0
                        n_others += 1
                if n_others:
                    score += w_ovlp * (jaccard_sum / n_others)

            # Signal 6: Budget (prefer cheaper)
            if w_bdgt > 0 and max_cost > 0 and dish.id in dish_costs:
                score += w_bdgt * (1.0 - dish_costs[dish.id] / max_cost)

            slot_scores[slot] = score

        artifact.scores[dish.id] = slot_scores
        artifact.dish_meta[dish.id] = meta

    artifact.never_cooked_ids = never_cooked
    return artifact


def _is_vega(meat_type: str | None) -> bool:
    return (meat_type or "").lower() == "vega"


def _is_fish(meat_type: str | None) -> bool:
    return (meat_type or "").lower() == "vis"


def _is_red_meat(meat_type: str | None) -> bool:
    return (meat_type or "").lower() in ("rund", "varken")


def _filter_candidates_for_slot(
    dish_ids: list[int],
    slot: str,
    artifact: RecommenderArtifact,
    settings: UserSettings | None,
) -> list[int]:
    """Apply per-day preference filters to narrow the candidate pool for one slot."""
    if settings is None:
        return dish_ids

    from pyplus.ml.interface import DayPreference

    pref = DayPreference.model_validate(settings.day_preferences.get(slot, {}))

    if not pref.enabled:
        return []

    result = []
    for did in dish_ids:
        meta = artifact.dish_meta.get(did)
        if meta is None:
            result.append(did)
            continue

        if pref.max_prep_minutes is not None and meta.prep_minutes is not None:
            if meta.prep_minutes > pref.max_prep_minutes:
                continue

        mt = (meta.meat_type or "").lower()
        if mt and pref.blocked_meat_types and mt in [x.lower() for x in pref.blocked_meat_types]:
            continue
        if (
            mt
            and pref.allowed_meat_types
            and mt not in [x.lower() for x in pref.allowed_meat_types]
        ):
            continue

        st = (meta.starch_type or "").lower()
        if (
            st
            and pref.blocked_starch_types
            and st in [x.lower() for x in pref.blocked_starch_types]
        ):
            continue
        if (
            pref.preferred_starch_types
            and st
            and st not in [x.lower() for x in pref.preferred_starch_types]
        ):
            continue

        if settings.ml_repeat_cooldown_weeks > 0 and meta.last_cooked_weeks_ago is not None:
            if meta.last_cooked_weeks_ago < settings.ml_repeat_cooldown_weeks:
                continue

        if settings.ml_confidence_threshold > 0:
            score = artifact.scores.get(did, {}).get(slot, 0.0)
            if score < settings.ml_confidence_threshold:
                continue

        result.append(did)
    return result


def _apply_week_constraints(
    candidates: list[int],
    assigned: list[tuple[str, int]],
    slot: str,
    remaining_slots: int,
    artifact: RecommenderArtifact,
    settings: UserSettings | None,
) -> list[int]:
    """Remove candidates that would violate cross-week diversity constraints."""
    if settings is None or not candidates:
        return candidates

    wc = settings.week_constraints
    meat_counts: dict[str, int] = defaultdict(int)
    starch_counts: dict[str, int] = defaultdict(int)
    vega_count = 0
    fish_count = 0
    red_meat_count = 0

    for _, did in assigned:
        m = artifact.dish_meta.get(did)
        if m:
            mt = (m.meat_type or "").lower()
            if mt:
                meat_counts[mt] += 1
            if _is_vega(m.meat_type):
                vega_count += 1
            if _is_fish(m.meat_type):
                fish_count += 1
            if _is_red_meat(m.meat_type):
                red_meat_count += 1
            st = (m.starch_type or "").lower()
            if st:
                starch_counts[st] += 1

    sequence_meats = [(artifact.dish_meta.get(did) or DishMeta()).meat_type for _, did in assigned]
    sequence_starches = [
        (artifact.dish_meta.get(did) or DishMeta()).starch_type for _, did in assigned
    ]

    result = []
    for did in candidates:
        meta = artifact.dish_meta.get(did)
        if meta is None:
            result.append(did)
            continue

        mt = (meta.meat_type or "").lower()
        st = (meta.starch_type or "").lower()

        # Max same meat type
        if mt and meat_counts.get(mt, 0) >= wc.max_same_meat_type:
            continue

        # Max vega days
        if _is_vega(meta.meat_type) and vega_count >= wc.max_vega_days:
            continue

        # Force vega if min_vega not yet met and slots are running out
        slots_left = remaining_slots
        vega_needed = wc.min_vega_days - vega_count
        if vega_needed > 0 and vega_needed >= slots_left and not _is_vega(meta.meat_type):
            continue

        # Force fish if min_fish not yet met and slots are running out
        fish_needed = wc.min_fish_days - fish_count
        if fish_needed > 0 and fish_needed >= slots_left and not _is_fish(meta.meat_type):
            continue

        # Max consecutive same meat
        if mt and wc.max_consecutive_same_meat < 7 and sequence_meats:
            tail = sequence_meats[-(wc.max_consecutive_same_meat - 1) :]
            if (
                all((t or "").lower() == mt for t in tail)
                and len(tail) == wc.max_consecutive_same_meat - 1
            ):
                continue

        # Max consecutive same starch
        if st and wc.max_consecutive_same_starch < 7 and sequence_starches:
            tail = sequence_starches[-(wc.max_consecutive_same_starch - 1) :]
            if (
                all((t or "").lower() == st for t in tail)
                and len(tail) == wc.max_consecutive_same_starch - 1
            ):
                continue

        # Max red meat (rund/varken) days
        if _is_red_meat(meta.meat_type) and red_meat_count >= wc.max_red_meat_days:
            continue

        result.append(did)

    return result


def _select_dish(
    candidates: list[tuple[float, int]],
    method: str,
    exploration_rate: float,
    temperature: float,
    rng: random.Random,
) -> int:
    """Pick one dish_id from scored candidates using the configured selection method."""
    if not candidates:
        raise ValueError("No candidates")

    if method == "epsilon_greedy":
        if rng.random() < exploration_rate:
            return rng.choice(candidates)[1]
        return max(candidates)[1]

    if method == "softmax":
        temp = max(temperature, 0.01)
        max_s = max(s for s, _ in candidates)
        exps = [math.exp((s - max_s) / temp) for s, _ in candidates]
        total = sum(exps)
        probs = [e / total for e in exps]
        r = rng.random()
        cumulative = 0.0
        for i, p in enumerate(probs):
            cumulative += p
            if r <= cumulative:
                return candidates[i][1]
        return candidates[-1][1]

    if method == "thompson":
        sampled = []
        for s, did in candidates:
            alpha = max(s * 10, 0.1)
            beta = max((1.0 - s) * 10, 0.1)
            sampled.append(
                (
                    rng.gammavariate(alpha, 1)
                    / (rng.gammavariate(alpha, 1) + rng.gammavariate(beta, 1)),
                    did,
                )
            )
        return max(sampled)[1]

    # Default: greedy
    return max(candidates)[1]


def plan_week(
    artifact: RecommenderArtifact,
    dish_ids: list[int],
    current_slots: dict[str, int | None],
    settings: UserSettings | None = None,
    n_dinner: int = 7,
    n_lunch: int = 5,
    rng_seed: int | None = None,
    weather_temps: dict[str, float] | None = None,
) -> dict[str, int]:
    """
    Assign dishes to empty slots with constraint satisfaction + configurable selection.

    Returns {slot: dish_id} for all slots that were filled.
    Does not overwrite slots that already have a dish.
    """
    rng = random.Random(rng_seed)
    method = settings.ml_selection_method if settings else "greedy"
    exploration_rate = settings.ml_exploration_rate if settings else 0.0
    temperature = settings.ml_temperature if settings else 1.0
    novelty_ratio = settings.ml_novelty_ratio if settings else 0.0

    result: dict[str, int] = {}
    used_ids: set[int] = {v for v in current_slots.values() if v is not None}
    assigned: list[tuple[str, int]] = [
        (slot, did) for slot, did in current_slots.items() if did is not None
    ]

    weather_temps = weather_temps or {}
    hot_threshold = settings.weather_hot_threshold if settings else 25.0
    w_no_oven = settings.ml_weather_no_oven if settings else 0.0
    w_cold = settings.ml_weather_cold if settings else 0.0

    def _weather_adjust(base: float, did: int, slot: str) -> float:
        """Apply weather-based score adjustments on hot days."""
        if not settings or not settings.weather_enabled or not weather_temps:
            return base
        temp = weather_temps.get(slot)
        if temp is None or temp < hot_threshold:
            return base
        meta = artifact.dish_meta.get(did)
        if meta is None:
            return base
        if w_no_oven > 0:
            methods = [m.lower() for m in meta.cooking_methods]
            if "oven" in methods or "airfryer" in methods:
                base *= max(0.0, 1.0 - w_no_oven)
        if w_cold > 0 and meta.is_cold:
            base *= 1.0 + w_cold
        return base

    def _fill(slots: list[str]) -> None:
        total_slots = len(slots)
        for i, slot in enumerate(slots):
            if current_slots.get(slot) is not None:
                continue

            available = [did for did in dish_ids if did not in used_ids]
            if not available:
                break

            filtered = _filter_candidates_for_slot(available, slot, artifact, settings)
            remaining = total_slots - i
            constrained = _apply_week_constraints(
                filtered or available, assigned, slot, remaining, artifact, settings
            )

            if not constrained:
                constrained = available

            # Apply novelty boost
            novel_count = sum(1 for _, d in assigned if d in artifact.never_cooked_ids)
            total_assigned = len(assigned) or 1

            if novelty_ratio > 0 and (novel_count / total_assigned) < novelty_ratio:
                scored = []
                for did in constrained:
                    base = artifact.scores.get(did, {}).get(slot, 0.0)
                    if did in artifact.never_cooked_ids:
                        base *= 2.0
                    base = _weather_adjust(base, did, slot)
                    scored.append((base, did))
            else:
                scored = [
                    (_weather_adjust(artifact.scores.get(did, {}).get(slot, 0.0), did, slot), did)
                    for did in constrained
                ]

            if not scored:
                break

            best_id = _select_dish(scored, method, exploration_rate, temperature, rng)
            result[slot] = best_id
            used_ids.add(best_id)
            assigned.append((slot, best_id))

    _fill(_DINNER_SLOTS[:n_dinner])
    _fill(_LUNCH_SLOTS[:n_lunch])
    return result
