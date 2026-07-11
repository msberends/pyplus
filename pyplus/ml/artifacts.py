"""Save/load precomputed ML results from the ml_artifacts DB table via pickle."""

from __future__ import annotations

import hashlib
import logging
import pickle
from typing import Any

log = logging.getLogger(__name__)


async def save_artifact(user_id: int, kind: str, obj: Any, input_data: bytes = b"") -> None:
    input_hash = hashlib.sha256(input_data).hexdigest() if input_data else ""
    blob = pickle.dumps(obj, protocol=5)

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await repo.upsert_ml_artifact(db, user_id, kind, blob, input_hash)
    log.debug("Saved ML artifact '%s' for user=%d (%d bytes)", kind, user_id, len(blob))


async def recompute_recommender(user_id: int) -> None:
    """Recompute the recommender artifact so plan_week sees current dish metadata."""
    import datetime
    import json

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.interface import UserSettings
    from pyplus.ml.recommender import compute_all_scores

    async with AsyncSessionLocal() as db:
        user = await repo.get_user_by_id(db, user_id)
        settings_json = await repo.get_user_settings_json(db, user_id)
        dishes = await repo.get_dishes(db, user_id)
        all_ings = await repo.get_all_dish_ingredients_for_user(db, user_id)
    if user is None:
        return

    try:
        settings = UserSettings.model_validate_json(settings_json)
    except Exception:
        settings = UserSettings()

    store_number = user.store_number or 0
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    weights = {
        "afwisseling": settings.ml_afwisseling,
        "vaste_dagen": settings.ml_vaste_dagen,
        "voordeel": settings.ml_voordeel,
        "voorraad": settings.ml_voorraad,
        "ingredient_overlap": settings.ml_ingredient_overlap,
        "budget": settings.ml_budget,
        "rating": settings.ml_rating_weight,
    }

    async with AsyncSessionLocal() as db:
        history_rows = await repo.get_weekmenu_history(
            db, user_id, limit_weeks=settings.ml_history_window_weeks
        )
        sku_prices = await repo.get_all_ingredient_prices(db, user_id)
        promo_row = await repo.get_promotions_cache(db, store_number, week_start, False)

    promo_skus: set[str] = set()
    if promo_row:
        from plus.models import Promotion

        promos_data = json.loads(promo_row.payload_json)
        promo_skus = {
            p.sku for p in (Promotion(**p) for p in promos_data.get("promotions", [])) if p.sku
        }

    replenish_artifact = await load_artifact(user_id, "replenishment")
    due_skus: set[str] = set()
    if isinstance(replenish_artifact, dict):
        due_skus = {sku for sku, s in replenish_artifact.items() if getattr(s, "is_due", False)}

    dishes_with_ings = [(d, all_ings.get(d.id, [])) for d in dishes]
    artifact = compute_all_scores(
        dishes_with_ingredients=dishes_with_ings,
        weekmenu_history=history_rows,
        promo_skus=promo_skus,
        replenish_due_skus=due_skus,
        weights=weights,
        reference_week=week_start,
        settings=settings,
        ingredient_prices=sku_prices,
    )
    await save_artifact(user_id, "recommender", artifact)
    log.info("Recomputed recommender for user=%d (%d dishes)", user_id, len(dishes))


async def load_artifact(user_id: int, kind: str) -> Any | None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await repo.get_ml_artifact(db, user_id, kind)
    if row is None:
        return None
    try:
        return pickle.loads(row.blob)
    except Exception as exc:
        log.warning("Failed to load ML artifact '%s' for user=%d: %s", kind, user_id, exc)
        return None
