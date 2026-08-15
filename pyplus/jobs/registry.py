"""
Named background jobs — each runnable by both the in-app APScheduler
and the CLI (`python -m pyplus.jobs <name>`).

All jobs:
 • Check sync_state for an in-progress lock (skip if another instance is running)
 • Write "in_progress" before starting, "ok" or "error" when done
 • Are idempotent — safe to re-run at any time

Dependency order for full_preload:
  refresh_purchase_catalogue + refresh_orders + refresh_products + refresh_promotions
  → recompute_ml → weekly_ntfy (Thursday 07:00)
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging

log = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 1800  # 30 min — stale lock threshold


# ── Lock helpers ───────────────────────────────────────────────────────────────


async def _is_locked(user_id: int, resource: str) -> bool:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await repo.get_sync_state(db, user_id, resource)
    if row and row.last_status == "in_progress" and row.last_synced_at:
        age = (
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - row.last_synced_at
        ).total_seconds()
        if age < _LOCK_TTL_SECONDS:
            log.info("[%s] user=%d already in progress, skipping", resource, user_id)
            return True
    return False


async def _catalogue_is_stale(user_id: int, max_age_days: int = 7) -> bool:
    """True when the product catalogue has never synced OK or is older than max_age_days."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await repo.get_sync_state(db, user_id, "catalogue")
    if not row or row.last_status != "ok" or not row.last_synced_at:
        return True
    age_days = (
        datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - row.last_synced_at
    ).total_seconds() / 86400
    return age_days >= max_age_days


async def _set_status(
    user_id: int,
    resource: str,
    status: str,
    detail: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await repo.upsert_sync_state(db, user_id, resource, status, detail, duration_seconds)


# ── Promotions ─────────────────────────────────────────────────────────────────


async def refresh_promotions(*, user_id: int, client, store_number: int) -> None:
    """
    Fetch current-week promotions from PLUS → store in promotions_cache.
    The cache is keyed by (store_number, week_start) so it benefits all users
    at the same store.
    """
    resource = "promotions"
    if await _is_locked(user_id, resource):
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        result = await client.get_promotions_api(next_week=False)

        # Resolve each group deal's children up front so the cart can flag them as
        # on-offer: the promo index maps every child SKU → its parent deal, and the
        # deals lane can open "Bekijken" straight from cache (no live call). Single-
        # product deals already carry their own SKU. Per-deal failures are tolerated
        # — a missing child list just means no hint / a live fetch on expand.
        children: dict[str, list] = {}
        for promo in result.promotions:
            if promo.is_single_product or not promo.slug:
                continue
            try:
                prods = await client.get_promotion_products_api(promo.slug)
                children[promo.slug] = [
                    dataclasses.asdict(p) for p in prods if p.sku and not p.sku.startswith("0")
                ]
            except Exception as exc:
                log.warning("[promotions] children fetch failed for %s: %s", promo.slug, exc)

        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
        payload = dataclasses.asdict(result)
        payload["children"] = children
        payload_json = json.dumps(payload)

        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await repo.upsert_promotions_cache(db, store_number, week_start, False, payload_json)

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", duration_seconds=elapsed)
        log.info(
            "[promotions] user=%d store=%d — %d promotions cached (%d group deals w/ children)",
            user_id,
            store_number,
            len(result.promotions),
            len(children),
        )
    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[promotions] user=%d FAILED: %s", user_id, exc)
        raise


# ── Purchase catalogue ─────────────────────────────────────────────────────────


async def refresh_purchase_catalogue(*, user_id: int, client) -> None:
    """Fetch all previously-bought products → purchased_products_cache."""
    resource = "purchase_catalogue"
    if await _is_locked(user_id, resource):
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        products = await client.get_purchase_history_api(all_pages=True)

        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await repo.upsert_purchased_products(db, user_id, products)

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", duration_seconds=elapsed)
        log.info("[purchase_catalogue] user=%d — %d products cached", user_id, len(products))
    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[purchase_catalogue] user=%d FAILED: %s", user_id, exc)
        raise


# ── Order history ──────────────────────────────────────────────────────────────


async def refresh_orders(*, user_id: int, client) -> None:
    """
    Incrementally sync online orders.

    1. Fetch full order list (all summaries — the API returns them all at once).
    2. Store/update summaries.
    3. Fetch line-item details only for orders not already cached.
    """
    resource = "orders"
    if await _is_locked(user_id, resource):
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        orders = await client.get_order_list_api(offset=0)

        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await repo.upsert_order_summaries(db, user_id, orders)
            already_cached = await repo.get_cached_order_ids(db, user_id)

        new_orders = [o for o in orders if o.order_id not in already_cached]
        for o in new_orders:
            try:
                detail = await client.get_order_detail_api(o.order_id)
                async with AsyncSessionLocal() as db:
                    await repo.upsert_order_items(db, user_id, o.order_id, detail.items)
            except Exception as exc:
                log.warning(
                    "[orders] user=%d detail fetch failed for %s: %s", user_id, o.order_id[:8], exc
                )

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", duration_seconds=elapsed)
        log.info(
            "[orders] user=%d — %d summaries, %d new detail fetches",
            user_id,
            len(orders),
            len(new_orders),
        )
    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[orders] user=%d FAILED: %s", user_id, exc)
        raise


# ── Product availability ───────────────────────────────────────────────────────


async def refresh_products(*, user_id: int, client, store_number: int) -> None:
    """
    Re-validate prices and availability for the user's ingredient and fixed-product SKUs.

    Searches by cached product name, updates ingredient_skus with latest price/availability.
    Limits to the most recently-updated SKUs to keep the job fast.
    """
    resource = "products"
    if await _is_locked(user_id, resource):
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            # Collect all unique SKUs in use
            dishes = await repo.get_dishes(db, user_id)
            sku_names: dict[str, str] = {}  # sku → display name
            for dish in dishes:
                for ing in await repo.get_ingredients(db, dish.id):
                    if ing.sku:
                        sku_names[ing.sku] = ing.display_name
            fps = await repo.get_fixed_products(db, user_id)
            for fp in fps:
                if fp.sku and fp.sku not in sku_names:
                    sku_names[fp.sku] = fp.display_name

            # Prioritise SKUs that haven't been checked recently
            cached = await repo.get_ingredient_skus_by_skus(db, user_id, list(sku_names.keys()))

        # Sort by oldest check first — process all SKUs (no cap)
        ordered = sorted(
            sku_names.keys(),
            key=lambda s: (
                (cached[s].last_checked_at or datetime.datetime.min)
                if s in cached
                else datetime.datetime.min
            ),
        )

        from pyplus.services.dishes import _parse_pack_from_subtitle

        updated = 0
        not_found = 0
        for sku in ordered:
            name = sku_names[sku]
            try:
                # Primary: search by cached display name, look for exact SKU match
                results = await client.search_products_api(name, store_number)
                match = next((p for p in results if p.sku == sku), None)

                # Fallback: search by SKU string directly (handles renamed products)
                if match is None:
                    results_by_sku = await client.search_products_api(sku, store_number)
                    match = next((p for p in results_by_sku if p.sku == sku), None)

                if match:
                    existing = cached.get(sku)
                    # Re-derive pack size from the freshly-fetched subtitle rather than
                    # blindly carrying the old value forward — otherwise a SKU whose
                    # subtitle didn't parse (or wasn't captured) at link-time stays
                    # pack_size=None forever, silently disabling pack optimisation for it.
                    pack_size, pack_unit = _parse_pack_from_subtitle(match.subtitle or "")
                    if pack_size is None and existing:
                        pack_size, pack_unit = existing.pack_size, existing.pack_unit
                    async with AsyncSessionLocal() as db:
                        await repo.upsert_ingredient_sku(
                            db,
                            user_id,
                            sku,
                            name=match.name,
                            subtitle=match.subtitle,
                            slug=getattr(match, "slug", "") or "",
                            image_url=match.image_url,
                            pack_size=pack_size,
                            pack_unit=pack_unit,
                            last_price=match.price,
                            last_seen_available=match.is_available,
                        )
                    updated += 1
                elif sku in cached:
                    # Not found at this store — mark unavailable so the UI can warn
                    existing = cached[sku]
                    async with AsyncSessionLocal() as db:
                        await repo.upsert_ingredient_sku(
                            db,
                            user_id,
                            sku,
                            name=existing.name or name,
                            subtitle=existing.subtitle or "",
                            image_url=existing.image_url or "",
                            pack_size=existing.pack_size,
                            pack_unit=existing.pack_unit,
                            last_price=existing.last_price,
                            last_seen_available=False,
                        )
                    not_found += 1
                    log.info(
                        "[products] user=%d sku=%s — not found at store, marked unavailable",
                        user_id,
                        sku,
                    )

            except Exception as exc:
                log.warning("[products] user=%d sku=%s: %s", user_id, sku, exc)

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", duration_seconds=elapsed)
        log.info(
            "[products] user=%d — %d updated, %d not found / %d total",
            user_id,
            updated,
            not_found,
            len(ordered),
        )
    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[products] user=%d FAILED: %s", user_id, exc)
        raise


# ── Product catalogue (full store catalogue) ────────────────────────────────────


async def refresh_product_catalogue(*, user_id: int, client, store_number: int) -> None:
    """
    Download the full store catalogue via direct API → product_cache.

    Store-scoped and shared by all users at the same store (like promotions).
    Powers instant local search without per-keystroke PLUS calls. Runs weekly —
    the catalogue changes slowly; prices/availability are refreshed separately by
    refresh_products for the user's own SKUs.
    """
    resource = "catalogue"
    if await _is_locked(user_id, resource):
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        products = await client.get_all_products_api(store_number=store_number)

        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            written = await repo.upsert_product_cache(db, store_number, products)

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", f"{written} products", duration_seconds=elapsed)
        log.info(
            "[catalogue] user=%d store=%d — %d products cached", user_id, store_number, written
        )
    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[catalogue] user=%d FAILED: %s", user_id, exc)
        raise


# ── ML recompute ───────────────────────────────────────────────────────────────


async def recompute_ml(*, user_id: int) -> None:
    """
    Precompute all ML artifacts from the warmed caches.

    Reads ONLY from local DB — no PLUS API calls.
    Dependency: run after refresh_purchase_catalogue + refresh_orders +
                refresh_promotions + refresh_products.
    """
    resource = "ml"
    if await _is_locked(user_id, resource):
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.ml.artifacts import save_artifact
        from pyplus.ml.interface import UserSettings
        from pyplus.ml.promo_match import sort_promotions_by_relevance
        from pyplus.ml.recommender import compute_all_scores
        from pyplus.ml.replenish import compute_replenishment_score
        from pyplus.services.history import build_purchase_history

        # ── Load user context ─────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            user = await repo.get_user_by_id(db, user_id)
            settings_json = await repo.get_user_settings_json(db, user_id)
        if user is None:
            log.warning("[ml] user=%d not found — skipping", user_id)
            return

        store_number = user.store_number or 0
        try:
            settings = UserSettings.model_validate_json(settings_json)
        except Exception:
            settings = UserSettings()

        weights = {
            "afwisseling": settings.ml_afwisseling,
            "vaste_dagen": settings.ml_vaste_dagen,
            "voordeel": settings.ml_voordeel,
            "voorraad": settings.ml_voorraad,
            "variatie": settings.ml_variatie,
            "ingredient_overlap": settings.ml_ingredient_overlap,
            "budget": settings.ml_budget,
            "rating": settings.ml_rating_weight,
        }

        # ── Build purchase history ────────────────────────────────────────
        history = await build_purchase_history(user_id)
        history_by_sku = {r.sku: r for r in history}

        # ── Replenishment scores ──────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            fps = await repo.get_fixed_products(db, user_id)
        today = datetime.date.today()
        replenish_scores = {
            fp.sku: compute_replenishment_score(history_by_sku.get(fp.sku), today)
            for fp in fps
            if fp.sku
        }
        await save_artifact(user_id, "replenishment", replenish_scores)

        due_skus = {sku for sku, s in replenish_scores.items() if s.is_due}

        # ── Promo-match scores ────────────────────────────────────────────
        week_start = today - datetime.timedelta(days=today.weekday())
        async with AsyncSessionLocal() as db:
            promo_row = await repo.get_promotions_cache(db, store_number, week_start, False)
        if promo_row:
            from plus.models import Promotion

            promos_data = json.loads(promo_row.payload_json)
            promotions = [Promotion(**p) for p in promos_data.get("promotions", [])]
            # Weekmenu SKUs for the current week
            async with AsyncSessionLocal() as db:
                wm_rows = await repo.get_weekmenu(db, user_id, week_start)
                dish_ings = await repo.get_all_dish_ingredients_for_user(db, user_id)
            wm_dish_ids = {r.dish_id for r in wm_rows if r.dish_id}
            weekmenu_skus = {
                ing.sku
                for did, ings in dish_ings.items()
                if did in wm_dish_ids
                for ing in ings
                if ing.sku
            }
            promo_skus_set = {p.sku for p in promotions if p.sku}
            sorted_promos = sort_promotions_by_relevance(promotions, history_by_sku, weekmenu_skus)
            promo_order = [p.slug for p in sorted_promos]
            await save_artifact(user_id, "promo_match", promo_order)
        else:
            promo_skus_set = set()
            log.debug("[ml] user=%d no promotions cache — skipping promo_match", user_id)

        # ── Recommender scores ────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            dishes = await repo.get_dishes(db, user_id)
            all_ings = await repo.get_all_dish_ingredients_for_user(db, user_id)
            history_rows = await repo.get_weekmenu_history(
                db, user_id, limit_weeks=settings.ml_history_window_weeks
            )
            sku_prices = await repo.get_all_ingredient_prices(db, user_id)

        dishes_with_ings = [(d, all_ings.get(d.id, [])) for d in dishes]
        artifact = compute_all_scores(
            dishes_with_ingredients=dishes_with_ings,
            weekmenu_history=history_rows,
            promo_skus=promo_skus_set,
            replenish_due_skus=due_skus,
            weights=weights,
            reference_week=week_start,
            settings=settings,
            ingredient_prices=sku_prices,
        )
        await save_artifact(user_id, "recommender", artifact)

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", duration_seconds=elapsed)
        log.info(
            "[ml] user=%d — replenish:%d, promo_match:%s, recommender:%d dishes",
            user_id,
            len(replenish_scores),
            "yes" if promo_row else "skipped",
            len(dishes),
        )

    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[ml] user=%d FAILED: %s", user_id, exc)
        raise


# ── Weekly ntfy alert ─────────────────────────────────────────────────────────

_NTFY_SCORE_THRESHOLD = 1.0  # minimum relevance score to include in alert
_NTFY_MAX_PROMOS = 5  # max product names in the message body


def _build_ntfy_message(relevant_with_scores: list, base_url: str = "") -> tuple[str, str]:
    """Return (body, click_url) for the weekly promo ntfy push."""
    count = len(relevant_with_scores)
    top = relevant_with_scores[:_NTFY_MAX_PROMOS]
    names = [p.name or p.sku for p, _ in top]

    if count == 1:
        body = f"1 product dat je vaak koopt is volgende week in de aanbieding:\n• {names[0]}"
    else:
        body = (
            f"{count} producten die je vaak koopt zijn volgende week in de aanbieding:\n"
            + "\n".join(f"• {n}" for n in names)
        )
        if count > _NTFY_MAX_PROMOS:
            body += f"\n… en {count - _NTFY_MAX_PROMOS} meer"

    click_url = f"{base_url.rstrip('/')}/weekmenu" if base_url else ""
    return body, click_url


async def _push_ntfy(
    settings, body: str, *, title: str = "PyPLUS aanbieding", click_url: str = ""
) -> None:
    """POST body to the user's configured ntfy endpoint. Raises on HTTP ≥ 400."""
    import base64

    import httpx

    from pyplus.security.secrets import decrypt

    headers: dict[str, str] = {
        "Title": title,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if click_url:
        headers["Click"] = click_url
    if settings.ntfy_username:
        pw = decrypt(settings.ntfy_password_enc) if settings.ntfy_password_enc else ""
        token = base64.b64encode(f"{settings.ntfy_username}:{pw}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    url = f"{settings.ntfy_url.rstrip('/')}/{settings.ntfy_topic}"
    async with httpx.AsyncClient() as http:
        r = await http.post(url, content=body.encode(), headers=headers, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"ntfy returned HTTP {r.status_code}")


async def weekly_ntfy(*, user_id: int, client=None, store_number: int = 0) -> None:
    """
    Send a weekly ntfy push alert listing next-week PLUS promotions that match
    the user's purchase history.

    Reads next-week promotions from promotions_cache (is_next_week=True).
    If the cache is cold and a client is provided, fetches and caches them first.
    Skips silently when:
      - ntfy is not configured or disabled in Settings
      - no relevant promotions above the score threshold
      - already sent a push within the last 6 days (spam prevention)
    """
    resource = "ntfy_weekly"
    if await _is_locked(user_id, resource):
        return

    # Spam prevention: at most one push per user per week
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        state = await repo.get_sync_state(db, user_id, resource)
    if state and state.last_status == "ok" and state.last_synced_at:
        days_since = (
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - state.last_synced_at
        ).total_seconds() / 86400
        if days_since < 6:
            log.info(
                "[ntfy] user=%d already pushed this week (%.0f days ago) — skipping",
                user_id,
                days_since,
            )
            return

    await _set_status(user_id, resource, "in_progress")
    try:
        # Load user settings
        async with AsyncSessionLocal() as db:
            settings_json = await repo.get_user_settings_json(db, user_id)
            user = await repo.get_user_by_id(db, user_id)

        from pyplus.ml.interface import UserSettings

        try:
            settings = UserSettings.model_validate_json(settings_json)
        except Exception:
            settings = UserSettings()

        if not settings.ntfy_weekly_alert or not settings.ntfy_url or not settings.ntfy_topic:
            log.info("[ntfy] user=%d ntfy not configured or disabled — skipping", user_id)
            await _set_status(user_id, resource, "ok", "disabled")
            return

        # Resolve store number (prefer arg over user record)
        resolved_store = store_number or (user.store_number if user else 0) or 0

        # Load next-week promotions (keyed by this Monday + is_next_week=True)
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())

        async with AsyncSessionLocal() as db:
            promo_row = await repo.get_promotions_cache(db, resolved_store, week_start, True)

        if promo_row is None:
            if client is not None:
                # Fetch and cache next-week promos
                result = await client.get_promotions_api(next_week=True)
                payload_json = json.dumps(dataclasses.asdict(result))
                async with AsyncSessionLocal() as db:
                    await repo.upsert_promotions_cache(
                        db, resolved_store, week_start, True, payload_json
                    )
                promotions_raw = result.promotions
            else:
                log.info(
                    "[ntfy] user=%d no next-week promo cache and no client — skipping", user_id
                )
                await _set_status(user_id, resource, "ok", "no_cache")
                return
        else:
            from plus.models import Promotion

            promos_data = json.loads(promo_row.payload_json)
            promotions_raw = [Promotion(**p) for p in promos_data.get("promotions", [])]

        if not promotions_raw:
            log.info("[ntfy] user=%d next-week promo cache is empty — skipping", user_id)
            await _set_status(user_id, resource, "ok", "empty")
            return

        # Build purchase history for scoring
        from pyplus.services.history import build_purchase_history

        history = await build_purchase_history(user_id)
        history_by_sku = {r.sku: r for r in history}

        # Weekmenu SKUs for *next* week (planning horizon for boost signal)
        next_monday = week_start + datetime.timedelta(weeks=1)
        async with AsyncSessionLocal() as db:
            wm_rows = await repo.get_weekmenu(db, user_id, next_monday)
            dish_ings = await repo.get_all_dish_ingredients_for_user(db, user_id)
        wm_dish_ids = {r.dish_id for r in wm_rows if r.dish_id}
        weekmenu_skus = {
            ing.sku
            for did, ings in dish_ings.items()
            if did in wm_dish_ids
            for ing in ings
            if ing.sku
        }

        # Score single-product promos that have a SKU
        from pyplus.ml.promo_match import score_promotion

        scored = [
            (p, score_promotion(p, history_by_sku, weekmenu_skus))
            for p in promotions_raw
            if p.is_single_product and p.sku
        ]
        relevant = [(p, s) for p, s in scored if s >= _NTFY_SCORE_THRESHOLD]
        relevant.sort(key=lambda t: t[1], reverse=True)

        if not relevant:
            log.info(
                "[ntfy] user=%d no promos above threshold %.1f — skipping",
                user_id,
                _NTFY_SCORE_THRESHOLD,
            )
            await _set_status(user_id, resource, "ok", "no_match")
            return

        # Build and push message
        from pyplus.config import settings as app_settings
        from pyplus.security.net import UnsafeUrlError, assert_safe_url

        # SSRF guard: ntfy_url is user-controlled; never POST to an internal address.
        try:
            await assert_safe_url(settings.ntfy_url)
        except UnsafeUrlError as exc:
            log.warning("[ntfy] user=%d unsafe ntfy_url — skipping push: %s", user_id, exc)
            await _set_status(user_id, resource, "error", "unsafe_url")
            return

        body, click_url = _build_ntfy_message(relevant, base_url=app_settings.base_url)
        await _push_ntfy(settings, body, click_url=click_url)

        await _set_status(user_id, resource, "ok")
        log.info("[ntfy] user=%d pushed alert — %d relevant promos", user_id, len(relevant))

    except Exception as exc:
        await _set_status(user_id, resource, "error", str(exc)[:500])
        log.error("[ntfy] user=%d FAILED: %s", user_id, exc)
        raise


# ── Weather cache ─────────────────────────────────────────────────────────────


async def refresh_weather(*, user_id: int) -> None:
    """Fetch 14-day forecast + today from Open-Meteo for the user's configured location."""
    resource = "weather"
    if await _is_locked(user_id, resource):
        return

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.interface import UserSettings

    async with AsyncSessionLocal() as db:
        settings_json = await repo.get_user_settings_json(db, user_id)
    try:
        settings = UserSettings.model_validate_json(settings_json)
    except Exception:
        settings = UserSettings()

    if not settings.weather_enabled or settings.weather_latitude is None:
        log.debug("[weather] user=%d weather not configured — skipping", user_id)
        return

    t0 = datetime.datetime.now(datetime.UTC)
    await _set_status(user_id, resource, "in_progress")
    try:
        import httpx

        lat = round(settings.weather_latitude, 2)
        lon = round(settings.weather_longitude, 2)

        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max",
                    "timezone": "Europe/Amsterdam",
                    "past_days": 0,
                    "forecast_days": 14,
                },
                timeout=15,
            )
        data = r.json()
        dates = data.get("daily", {}).get("time", [])
        temps = data.get("daily", {}).get("temperature_2m_max", [])

        async with AsyncSessionLocal() as db:
            for d_str, temp in zip(dates, temps):
                day = datetime.date.fromisoformat(d_str)
                await repo.upsert_weather(db, day, lat, lon, float(temp))

        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "ok", duration_seconds=elapsed)
        log.info(
            "[weather] user=%d — %d days cached for (%.2f, %.2f)", user_id, len(dates), lat, lon
        )
    except Exception as exc:
        elapsed = (datetime.datetime.now(datetime.UTC) - t0).total_seconds()
        await _set_status(user_id, resource, "error", str(exc)[:500], duration_seconds=elapsed)
        log.error("[weather] user=%d FAILED: %s", user_id, exc)
        raise


# ── Autopilot prepare ─────────────────────────────────────────────────────────


async def autopilot_prepare(*, user_id: int, **_kwargs) -> None:
    """Generate an autopilot shopping plan and send ntfy notification."""
    resource = "autopilot_weekly"
    if await _is_locked(user_id, resource):
        return

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.interface import UserSettings

    async with AsyncSessionLocal() as db:
        state = await repo.get_sync_state(db, user_id, resource)
    if state and state.last_status == "ok" and state.last_synced_at:
        days_since = (
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - state.last_synced_at
        ).total_seconds() / 86400
        if days_since < 6:
            log.info("[autopilot] user=%d already ran this week — skipping", user_id)
            return

    await _set_status(user_id, resource, "in_progress")
    try:
        async with AsyncSessionLocal() as db:
            settings_json = await repo.get_user_settings_json(db, user_id)
            user = await repo.get_user_by_id(db, user_id)
        try:
            settings = UserSettings.model_validate_json(settings_json)
        except Exception:
            settings = UserSettings()

        if not settings.ml_autopilot:
            log.info("[autopilot] user=%d autopilot not enabled — skipping", user_id)
            await _set_status(user_id, resource, "ok", "disabled")
            return

        store_number = (user.store_number if user else 0) or 0

        from pyplus.services.autopilot import prepare_plan

        result = await prepare_plan(user_id, store_number=store_number)

        today = datetime.date.today()
        week_start = today + datetime.timedelta(days=(7 - today.weekday()))

        async with AsyncSessionLocal() as db:
            await repo.upsert_autopilot_plan(
                db,
                user_id,
                week_start,
                result.to_json(),
            )
            await repo.expire_old_autopilot_plans(
                db,
                user_id,
                week_start - datetime.timedelta(weeks=1),
            )

        if settings.autopilot_ntfy and settings.ntfy_url and settings.ntfy_topic:
            from pyplus.config import settings as app_settings
            from pyplus.security.net import UnsafeUrlError, assert_safe_url

            try:
                await assert_safe_url(settings.ntfy_url)
            except UnsafeUrlError as exc:
                log.warning("[autopilot] user=%d unsafe ntfy_url: %s", user_id, exc)
            else:
                body, click_url = _build_autopilot_ntfy(result, app_settings.base_url)
                await _push_ntfy(
                    settings,
                    body,
                    title="PyPLUS boodschappenplan",
                    click_url=click_url,
                )

        await _set_status(user_id, resource, "ok")
        log.info(
            "[autopilot] user=%d plan ready — %d items, %d need review",
            user_id,
            result.summary.total_items,
            result.summary.needs_review_count,
        )

    except Exception as exc:
        await _set_status(user_id, resource, "error", str(exc)[:500])
        log.error("[autopilot] user=%d FAILED: %s", user_id, exc)
        raise


def _build_autopilot_ntfy(result, base_url: str) -> tuple[str, str]:
    """Return (body, click_url) for the autopilot ntfy push."""
    s = result.summary
    cost = f"€ {s.estimated_cost:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    product_word = "product" if s.total_items == 1 else "producten"
    lines = [
        "Je boodschappenplan staat klaar!",
        f"{s.total_items} {product_word} · {cost}",
    ]
    pending: list[str] = []
    non_flex_review = s.needs_review_count - getattr(s, "flex_count", 0)
    if non_flex_review > 0:
        word = "vervangingsproduct" if non_flex_review == 1 else "vervangingsproducten"
        pending.append(f"{non_flex_review} {word}")
    if getattr(s, "flex_count", 0) > 0:
        word = "flexibel ingrediënt" if s.flex_count == 1 else "flexibele ingrediënten"
        pending.append(f"{s.flex_count} {word}")
    if getattr(s, "optional_count", 0) > 0:
        word = "optioneel ingrediënt" if s.optional_count == 1 else "optionele ingrediënten"
        pending.append(f"{s.optional_count} {word}")
    if pending:
        lines.append(f"{', '.join(pending)} om te beoordelen")
    else:
        lines.append("Alles automatisch ingevuld")
    click_url = f"{base_url.rstrip('/')}/autopilot" if base_url else ""
    return "\n".join(lines), click_url


# ── Full preload ───────────────────────────────────────────────────────────────


async def full_preload(*, user_id: int, client, store_number: int) -> None:
    """Run all cache-warming jobs in dependency order for one user."""
    log.info("[full_preload] starting for user=%d store=%d", user_id, store_number)

    jobs: list = [
        (refresh_purchase_catalogue, {"user_id": user_id, "client": client}),
        (refresh_orders, {"user_id": user_id, "client": client}),
        (refresh_promotions, {"user_id": user_id, "client": client, "store_number": store_number}),
        (refresh_products, {"user_id": user_id, "client": client, "store_number": store_number}),
    ]

    # The full catalogue changes slowly and is a heavy download — only refresh it
    # when the cache is empty or older than ~7 days.
    if await _catalogue_is_stale(user_id, max_age_days=7):
        jobs.append(
            (
                refresh_product_catalogue,
                {"user_id": user_id, "client": client, "store_number": store_number},
            )
        )

    jobs.append((refresh_weather, {"user_id": user_id}))
    jobs.append((recompute_ml, {"user_id": user_id}))

    for job, kwargs in jobs:
        try:
            await job(**kwargs)
        except Exception as exc:
            log.warning(
                "[full_preload] user=%d %s failed: %s — continuing", user_id, job.__name__, exc
            )
    log.info("[full_preload] done for user=%d", user_id)
