"""
Autopilot plan generation — assembles a full shopping plan from ML artifacts,
staples, promo matches, and substitute scoring.  No PLUS API calls; reads only
from local DB caches.  The plan is stored as a draft for user review on /autopilot.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import asdict, dataclass, field

from pyplus.ml.interface import UserSettings

log = logging.getLogger(__name__)

_DAY_RANK = {
    "maandag": 0,
    "dinsdag": 1,
    "woensdag": 2,
    "donderdag": 3,
    "vrijdag": 4,
    "zaterdag": 5,
    "zondag": 6,
    "extra 1": 7,
    "extra 2": 8,
    "extra 3": 9,
    "extra 4": 10,
    "extra 5": 11,
}


def _sort_context_by_day(ctx: str) -> str:
    """Sort comma-separated context parts by weekday order."""
    import re

    parts = [p.strip() for p in ctx.split(", ") if p.strip()]
    staple_parts = [p for p in parts if not re.search(r"\([^)]+\)$", p)]
    day_parts = [p for p in parts if re.search(r"\([^)]+\)$", p)]

    def _day_key(part: str) -> int:
        m = re.search(r"\(([^)]+)\)$", part)
        return _DAY_RANK.get(m.group(1), 99) if m else 99

    day_parts.sort(key=_day_key)
    return ", ".join(day_parts + staple_parts)


_SLOT_DAY_LABELS = {
    "ma": "maandag",
    "di": "dinsdag",
    "wo": "woensdag",
    "do": "donderdag",
    "vr": "vrijdag",
    "za": "zaterdag",
    "zo": "zondag",
    "lunch1": "extra 1",
    "lunch2": "extra 2",
    "lunch3": "extra 3",
    "lunch4": "extra 4",
    "lunch5": "extra 5",
}


@dataclass
class PlanItem:
    sku: str
    name: str
    qty: int
    price: float
    image_url: str = ""
    source: str = ""
    context: str = ""
    original_sku: str | None = None
    original_name: str | None = None
    is_promo_swap: bool = False
    promo_savings: float = 0.0
    needs_review: bool = False
    substitute_options: list[dict] = field(default_factory=list)


@dataclass
class PlanSummary:
    total_items: int = 0
    estimated_cost: float = 0.0
    statiegeld_items: int = 0
    promo_swaps: int = 0
    promo_savings: float = 0.0
    needs_review_count: int = 0
    free_delivery_met: bool = False


@dataclass
class AutopilotResult:
    items: list[PlanItem]
    summary: PlanSummary
    menu_assignments: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "items": [asdict(i) for i in self.items],
                "summary": asdict(self.summary),
                "menu_assignments": self.menu_assignments,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> AutopilotResult:
        data = json.loads(raw)
        items = [PlanItem(**i) for i in data["items"]]
        summary = PlanSummary(**data["summary"])
        assignments = data.get("menu_assignments", {})
        return cls(items=items, summary=summary, menu_assignments=assignments)


async def prepare_plan(user_id: int, *, store_number: int = 0) -> AutopilotResult:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        user = await repo.get_user_by_id(db, user_id)
        settings_json = await repo.get_user_settings_json(db, user_id)
    if user is None:
        return AutopilotResult(items=[], summary=PlanSummary())

    store = store_number or user.store_number or 0
    try:
        settings = UserSettings.model_validate_json(settings_json)
    except Exception:
        settings = UserSettings()

    items: list[PlanItem] = []
    seen_skus: dict[str, PlanItem] = {}

    def _add(item: PlanItem) -> None:
        if item.sku in seen_skus:
            seen_skus[item.sku].qty += item.qty
            ctx = seen_skus[item.sku].context
            if item.context and item.context not in ctx:
                merged = f"{ctx}, {item.context}"
                seen_skus[item.sku].context = _sort_context_by_day(merged)
            src = seen_skus[item.sku].source
            if item.source and item.source not in src:
                seen_skus[item.sku].source = f"{src},{item.source}"
        else:
            seen_skus[item.sku] = item
            items.append(item)

    # ── 1. Plan week menu ─────────────────────────────────────────────────
    menu_assignments = await _fill_weekmenu(user_id, store, settings, _add)

    # ── 2. Top up staples ─────────────────────────────────────────────────
    if settings.ml_autopilot_staples:
        planned_qtys = {sku: it.qty for sku, it in seen_skus.items()}
        await _fill_staples(user_id, store, settings, _add, already_planned=planned_qtys)

    # ── 3. Check availability + find substitutes ──────────────────────────
    await _resolve_availability(items, store, user_id, settings)

    # ── 4. Promo-aware swaps ──────────────────────────────────────────────
    if settings.ml_autopilot_promos:
        await _apply_promo_swaps(items, user_id, store, settings)

    # ── 5. Free delivery fillers ──────────────────────────────────────────
    fd_met = False
    if settings.ml_autopilot_fillers:
        fd_met = await _fill_free_delivery(items, user_id, store, settings)

    # ── 6. Compute summary ────────────────────────────────────────────────
    summary = _compute_summary(items, fd_met)

    return AutopilotResult(items=items, summary=summary, menu_assignments=menu_assignments)


async def _fill_weekmenu(
    user_id: int,
    store: int,
    settings: UserSettings,
    add_fn,
) -> dict[str, int]:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.artifacts import load_artifact
    from pyplus.ml.recommender import RecommenderArtifact, plan_week

    today = datetime.date.today()
    # Plan for next week (the coming Monday), not the current week
    next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
    week_start = next_monday

    async with AsyncSessionLocal() as db:
        wm_rows = await repo.get_weekmenu(db, user_id, week_start)
        all_dishes = await repo.get_all_dish_ingredients_for_user(db, user_id)
        user_dishes = await repo.get_dishes(db, user_id)

    dish_names: dict[int, str] = {d.id: d.name for d in user_dishes}

    current_slots: dict[str, int | None] = {}
    for row in wm_rows:
        current_slots[row.slot] = row.dish_id

    new_assignments: dict[str, int] = {}
    if settings.ml_autopilot_dinner or settings.ml_autopilot_lunch:
        artifact = await load_artifact(user_id, "recommender")
        if isinstance(artifact, RecommenderArtifact):
            n_dinner = settings.ml_autopilot_max_dinner if settings.ml_autopilot_dinner else 0
            n_lunch = settings.ml_autopilot_max_lunch if settings.ml_autopilot_lunch else 0
            dish_ids = list(all_dishes.keys())
            weather_temps = await _load_weather_temps(user_id, settings, week_start)

            new_assignments = plan_week(
                artifact,
                dish_ids,
                current_slots,
                settings=settings,
                n_dinner=n_dinner,
                n_lunch=n_lunch,
                weather_temps=weather_temps,
            )

    filled_slots = {**current_slots, **new_assignments}

    for slot, dish_id in filled_slots.items():
        if dish_id is None or dish_id not in all_dishes:
            continue
        day_label = _SLOT_DAY_LABELS.get(slot, slot)
        d_name = dish_names.get(dish_id, f"Gerecht #{dish_id}")
        context = f"{d_name} ({day_label})"
        for ing in all_dishes[dish_id]:
            if not ing.sku or ing.flexible or ing.optional:
                continue
            qty = max(1, math.ceil(ing.amount / (ing.pack_size or ing.amount or 1)))
            add_fn(
                PlanItem(
                    sku=ing.sku,
                    name=ing.display_name,
                    qty=qty,
                    price=0.0,
                    source="autopilot:menu",
                    context=context,
                )
            )

    return new_assignments


async def _load_weather_temps(
    user_id: int,
    settings: UserSettings,
    week_start: datetime.date,
) -> dict[str, float]:
    if not settings.weather_enabled or not settings.weather_latitude:
        return {}
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    slot_days = {"ma": 0, "di": 1, "wo": 2, "do": 3, "vr": 4, "za": 5, "zo": 6}
    end = week_start + datetime.timedelta(days=6)
    async with AsyncSessionLocal() as db:
        temps = await repo.get_weather_range(
            db,
            settings.weather_latitude,
            settings.weather_longitude or 0.0,
            week_start,
            end,
        )
    result = {}
    for slot, offset in slot_days.items():
        d = week_start + datetime.timedelta(days=offset)
        if d in temps:
            result[slot] = temps[d]
    return result


def _staple_is_due(fp, today: datetime.date) -> bool:
    """Check if a staple is due based on its every_n_weeks cadence."""
    if fp.every_n_weeks <= 1:
        return True
    if fp.last_added_at is None:
        return True
    days_since = (today - fp.last_added_at).days
    return days_since >= fp.every_n_weeks * 7 - 1


async def _fill_staples(
    user_id: int,
    store: int,
    settings: UserSettings,
    add_fn,
    already_planned: dict[str, int] | None = None,
) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    already = already_planned or {}
    today = datetime.date.today()

    async with AsyncSessionLocal() as db:
        fps = await repo.get_fixed_products(db, user_id)

    for fp in fps:
        if fp.min_qty < 1:
            continue

        if not _staple_is_due(fp, today):
            continue

        existing = already.get(fp.sku, 0)
        needed = fp.min_qty - existing
        if needed < 1:
            continue
        add_fn(
            PlanItem(
                sku=fp.sku,
                name=fp.display_name,
                qty=needed,
                price=0.0,
                source="autopilot:staple",
                context=f"Aangevuld naar standaard {fp.min_qty}",
            )
        )


async def _resolve_availability(
    items: list[PlanItem],
    store: int,
    user_id: int,
    settings: UserSettings,
) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.services.categories import parse_categories
    from pyplus.services.substitutes import find_substitutes

    all_skus = [i.sku for i in items if i.sku]
    if not all_skus or not store:
        return

    async with AsyncSessionLocal() as db:
        cache = await repo.get_product_cache_by_skus(db, store, all_skus)

    for item in items:
        pc = cache.get(item.sku)
        if pc is not None:
            if item.price == 0.0:
                item.price = pc.price
            if not item.image_url:
                item.image_url = pc.image_url or ""

        if pc is not None and pc.is_available:
            continue

        # Product is unavailable — find substitutes
        cats = None
        if pc is not None and getattr(pc, "categories_json", None):
            cats = parse_categories(pc.categories_json)
        subs = await find_substitutes(
            store,
            item.sku,
            product_name=item.name,
            categories=cats,
            price=item.price,
            user_id=user_id,
            settings=settings,
        )
        if not subs:
            item.needs_review = True
            item.context = f"{item.context} — niet beschikbaar, geen alternatief gevonden"
            continue

        best = subs[0]
        original_context = item.context
        if best.score >= settings.sub_confidence_auto:
            item.original_sku = item.sku
            item.original_name = item.name
            item.sku = best.product.sku
            item.name = best.product.name
            item.price = best.product.price
            item.image_url = best.product.image_url
            item.context = original_context
        else:
            item.needs_review = True
            item.original_sku = item.sku
            item.original_name = item.name
            item.substitute_options = [
                {
                    "sku": s.product.sku,
                    "name": s.product.name,
                    "price": s.product.price,
                    "image_url": s.product.image_url,
                    "subtitle": getattr(s.product, "subtitle", ""),
                    "score": round(s.score, 2),
                    "reason": s.match_reason,
                }
                for s in subs[:5]
            ]
            item.context = original_context


async def _apply_promo_swaps(
    items: list[PlanItem],
    user_id: int,
    store: int,
    settings: UserSettings,
) -> None:
    if not settings.ml_promo_match:
        return

    from pyplus.services.promos import get_promo_index
    from pyplus.services.substitutes import find_substitutes

    promo_index = await get_promo_index(store)
    if not promo_index:
        return

    promo_skus = set(promo_index.keys())

    for item in items:
        if item.needs_review or item.is_promo_swap:
            continue
        if item.sku in promo_skus:
            continue

        subs = await find_substitutes(
            store,
            item.sku,
            product_name=item.name,
            user_id=user_id,
            settings=settings,
        )

        for sub in subs[:3]:
            if sub.product.sku not in promo_skus:
                continue
            promo = promo_index[sub.product.sku]
            if promo.is_free_delivery:
                continue
            savings = item.price - promo.price_new if promo.price_new > 0 else 0.0
            if savings <= 0:
                continue
            item.is_promo_swap = True
            item.promo_savings = round(savings * item.qty, 2)
            item.original_sku = item.sku
            item.original_name = item.name
            item.sku = sub.product.sku
            item.name = sub.product.name
            item.price = promo.price_new
            item.image_url = sub.product.image_url
            item.source = "autopilot:promo"
            item.context = (
                f"Vervangt {item.original_name} (bespaar € {item.promo_savings:.2f})".replace(
                    ".", ","
                )
            )
            break


async def _fill_free_delivery(
    items: list[PlanItem],
    user_id: int,
    store: int,
    settings: UserSettings,
) -> bool:
    import re

    from pyplus.services.promos import get_promo_index

    promo_index = await get_promo_index(store)
    fd_promos = [p for p in promo_index.values() if p.is_free_delivery]
    if not fd_promos:
        return False

    # Parse threshold from first free-delivery promo
    threshold_eur = None
    for promo in fd_promos:
        for text in [promo.subtitle, promo.label]:
            if not text:
                continue
            m = re.search(r"€\s*(\d+(?:[.,]\d+)?)", text)
            if m:
                threshold_eur = float(m.group(1).replace(",", "."))
                break
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*euro", text, re.IGNORECASE)
            if m:
                threshold_eur = float(m.group(1).replace(",", "."))
                break
        if threshold_eur:
            break

    if threshold_eur is None:
        return False

    current_total = sum(i.price * i.qty for i in items)
    if current_total >= threshold_eur:
        return True

    # Fill gap with staples sorted by replenishment score
    gap = threshold_eur - current_total
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.artifacts import load_artifact

    replenish = await load_artifact(user_id, "replenishment") or {}
    existing_skus = {i.sku for i in items}

    async with AsyncSessionLocal() as db:
        fps = await repo.get_fixed_products(db, user_id)
        all_skus = [fp.sku for fp in fps if fp.sku and fp.sku not in existing_skus]
        if not all_skus:
            return current_total >= threshold_eur
        cache = await repo.get_product_cache_by_skus(db, store, all_skus)

    candidates = []
    for fp in fps:
        if fp.sku in existing_skus or fp.sku not in cache:
            continue
        pc = cache[fp.sku]
        if not pc.is_available or pc.price <= 0:
            continue
        score = 0.0
        rep = replenish.get(fp.sku)
        if rep and hasattr(rep, "score"):
            score = rep.score
        candidates.append((score, pc, fp))

    candidates.sort(key=lambda t: t[0], reverse=True)

    added = 0.0
    for _score, pc, fp in candidates:
        if added >= gap:
            break
        items.append(
            PlanItem(
                sku=pc.sku,
                name=pc.name,
                qty=1,
                price=pc.price,
                image_url=pc.image_url or "",
                source="autopilot:filler",
                context="Bezorgvuller — gratis bezorging bereiken",
            )
        )
        existing_skus.add(pc.sku)
        added += pc.price

    return (current_total + added) >= threshold_eur


def _compute_summary(items: list[PlanItem], fd_met: bool) -> PlanSummary:
    total_qty = sum(i.qty for i in items)
    total_cost = sum(i.price * i.qty for i in items)
    statiegeld = sum(1 for i in items if "statiegeld" in i.name.lower())
    promo_swaps = sum(1 for i in items if i.is_promo_swap)
    promo_savings = sum(i.promo_savings for i in items if i.is_promo_swap)
    needs_review = sum(1 for i in items if i.needs_review)

    return PlanSummary(
        total_items=total_qty,
        estimated_cost=round(total_cost, 2),
        statiegeld_items=statiegeld,
        promo_swaps=promo_swaps,
        promo_savings=round(promo_savings, 2),
        needs_review_count=needs_review,
        free_delivery_met=fd_met,
    )
