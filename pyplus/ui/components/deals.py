"""
Lane ③ — Aanbiedingen voor jou: this week's PLUS promotions.

Open path (M10+): reads from promotions_cache first.
  • Cache fresh  → renders instantly, no PLUS call.
  • Cache stale  → renders stale immediately, refreshes in background.
  • Cache absent → shows skeleton, fetches live, saves to cache.

Savings counter comes from Cart.savings (PLUS API Receipt.Discount) — already
wired in cart.py.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import logging
from dataclasses import dataclass, field

from nicegui import ui

from plus.models import Promotion, PromotionProduct
from pyplus.i18n import t
from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url

log = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 6  # promotions are stable within a day; refresh threshold


@dataclass
class _DealsState:
    promotions: list[Promotion] | None = None  # None = still loading
    error: str = ""  # non-empty = load failed
    expanded: set[str] = field(default_factory=set)
    promo_products: dict[str, list[PromotionProduct]] = field(default_factory=dict)
    # slug → cached children (job-warmed); drives the "Bekijken (N)" count and lets
    # expand open instantly without a live call. Enrichment happens lazily on expand.
    cached_children: dict[str, list[PromotionProduct]] = field(default_factory=dict)
    loading_slug: str = ""
    card_refreshers: dict = field(default_factory=dict)  # slug → per-card @ui.refreshable


def create_deals_lane(session) -> None:
    """Render Lane ③ — Aanbiedingen voor jou."""
    cart_service = getattr(session, "cart_service", None)
    state = _DealsState()

    with ui.element("div").classes("sp-lane"):
        # ── Header ────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            with ui.element("div").style("display:flex;align-items:center;gap:.5rem"):
                ui.label(t("lane.deals.title")).classes("sp-lane-title")
                loading_spinner = ui.spinner(size="14px", color="primary").style(
                    "margin-left:.25rem"
                )

        # ── Body ──────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-body sp-deals-body"):

            @ui.refreshable
            def _render() -> None:
                if state.error:
                    with ui.element("div").classes("sp-lane-error"):
                        ui.icon("error_outline", size="24px").style(
                            "color:var(--c-danger);opacity:.6"
                        )
                        ui.label(state.error).style("font-size:13px;color:var(--c-text-3)")
                        ui.button(
                            "Opnieuw proberen",
                            icon="refresh",
                            on_click=lambda: asyncio.ensure_future(_reset_and_retry()),
                        ).props("flat rounded no-caps color=primary size=sm").style(
                            "font-size:12px;margin-top:.125rem"
                        )
                elif state.promotions is None:
                    _render_skeleton()
                elif not state.promotions:
                    with ui.element("div").classes("sp-lane-placeholder"):
                        ui.label("🏷️").classes("sp-lane-placeholder-icon")
                        ui.label(t("lane.deals.empty")).style(
                            "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                        )
                else:
                    fd_promos = [p for p in state.promotions if p.is_free_delivery]
                    regular = [p for p in state.promotions if not p.is_free_delivery]

                    if not fd_promos and not regular:
                        with ui.element("div").classes("sp-lane-placeholder"):
                            ui.label("🏷️").classes("sp-lane-placeholder-icon")
                            ui.label(t("lane.deals.empty")).style(
                                "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                            )

                    def _card_for(promo) -> None:
                        @ui.refreshable
                        def _card(p=promo) -> None:
                            _render_promo(p, state, session, cart_service, _card)

                        state.card_refreshers[promo.slug] = _card
                        _card()

                    if fd_promos:
                        with ui.element("div").classes("sp-fd-header"):
                            ui.icon("local_shipping", size="18px")
                            ui.label(t("deals.free_delivery"))
                        for promo in fd_promos:
                            _card_for(promo)
                        if regular:
                            ui.element("hr").classes("sp-fd-divider")

                    if session.settings.deals_group_by_category:
                        seen: list[str] = []
                        groups: dict[str, list] = {}
                        for promo in regular:
                            label = promo.category_label or "Overig"
                            if label not in groups:
                                groups[label] = []
                                seen.append(label)
                            groups[label].append(promo)
                        for label in seen:
                            ui.label(label).classes("sp-cat-header")
                            for promo in groups[label]:
                                _card_for(promo)
                    else:
                        for promo in regular:
                            _card_for(promo)

            _render()

            # Re-render only affected promo cards when cart changes.
            # Tracking the previous in-cart / syncing sets per single-product promo
            # prevents needless full-lane rebuilds (which would re-fetch all images).
            _last_promo_in_cart: list[frozenset] = [frozenset()]
            _last_promo_syncing: list[frozenset] = [frozenset()]

            def _on_cart_for_deals() -> None:
                if not state.promotions:
                    return
                cart_qty_map = {it.sku: it.quantity for it in session.cart.items}
                syncing = session.syncing_skus
                single_skus = {p.sku for p in state.promotions if p.is_single_product and p.sku}
                in_cart_now = frozenset(s for s in single_skus if cart_qty_map.get(s, 0) > 0)
                syncing_now = frozenset(single_skus & syncing)

                changed_in_cart = in_cart_now.symmetric_difference(_last_promo_in_cart[0])
                changed_syncing = syncing_now.symmetric_difference(_last_promo_syncing[0])
                changed_skus = changed_in_cart | changed_syncing

                if changed_skus:
                    _last_promo_in_cart[0] = in_cart_now
                    _last_promo_syncing[0] = syncing_now
                    for promo in state.promotions:
                        if promo.is_single_product and promo.sku in changed_skus:
                            card = state.card_refreshers.get(promo.slug)
                            if card is not None:
                                card.refresh()
                # qty-only changes within already-in-cart promos: no refresh needed;
                # the stepper qty label is not shown prominently in deal cards.

            session.add_cart_listener(_on_cart_for_deals)

    async def _load() -> None:
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())

        # Job-warmed group-deal children (cache-only): gives us the child count for
        # the "Bekijken (N)" label and an instant expand. Empty when the cache is cold.
        from pyplus.services.promos import get_promo_children

        state.cached_children = await get_promo_children(session.store_number, week_start)

        # ── 1. Try DB cache ────────────────────────────────────────────────
        cached = await _read_cache(session.store_number, week_start)
        if cached is not None:
            state.promotions = await _apply_ml_sort(session, cached)
            loading_spinner.set_visibility(False)
            _render.refresh()

            # Stale? Refresh silently in background — UI already shows cached data.
            if await _cache_is_stale(session.store_number, week_start):
                asyncio.ensure_future(_background_refresh(session, state, week_start, _render))
            return

        # ── 2. No cache — fetch live, paint on completion ──────────────────
        try:
            result = await session.client.get_promotions_api()
            state.promotions = result.promotions
            asyncio.ensure_future(_save_cache(session.store_number, week_start, result.promotions))
        except Exception as exc:
            log.warning("Promotions load failed: %s", exc)
            state.promotions = []
            state.error = "Aanbiedingen konden niet worden geladen."

        if state.promotions and not state.error:
            state.promotions = await _apply_ml_sort(session, state.promotions)
        loading_spinner.set_visibility(False)
        _render.refresh()

    async def _reset_and_retry() -> None:
        state.error = ""
        state.promotions = None  # show skeleton
        loading_spinner.set_visibility(True)
        _render.refresh()
        await _load()

    loading_spinner.set_visibility(True)
    asyncio.ensure_future(_load())


def _render_skeleton() -> None:
    for _ in range(4):
        with ui.element("div").style(
            "display:flex;gap:.625rem;padding:.5rem 0;border-bottom:1px solid var(--c-border)"
        ):
            ui.element("div").classes("skeleton").style(
                "width:52px;height:52px;border-radius:var(--r-sm);flex-shrink:0"
            )
            with ui.element("div").style("flex:1;display:flex;flex-direction:column;gap:6px"):
                ui.element("div").classes("skeleton").style(
                    "height:14px;border-radius:var(--r-xs);width:60%"
                )
                ui.element("div").classes("skeleton").style(
                    "height:11px;border-radius:var(--r-xs);width:40%"
                )
                ui.element("div").classes("skeleton").style(
                    "height:11px;border-radius:var(--r-xs);width:30%"
                )


def _render_promo(promo: Promotion, state: _DealsState, session, cart_service, refresh_fn) -> None:
    """Render one promotion entry."""
    is_expanded = promo.slug in state.expanded
    cart_qty = 0
    if promo.is_single_product and promo.sku:
        cart_qty = next((it.quantity for it in session.cart.items if it.sku == promo.sku), 0)
        is_syncing = promo.sku in session.syncing_skus
    else:
        is_syncing = False

    is_fd = promo.is_free_delivery
    card_cls = "sp-promo-card sp-promo-card-fd" if is_fd else "sp-promo-card"
    ribbon_cls = "sp-promo-ribbon-fd" if is_fd else "sp-promo-ribbon"
    accent = "var(--c-accent)" if is_fd else "var(--c-brand-dark)"

    with ui.element("div").classes(card_cls):
        # Card header row: image | deal info | action
        with ui.element("div").style("display:flex;align-items:center;gap:.625rem"):
            # Thumbnail
            if promo.image_url:
                ui.image(thumbnail_url(promo.image_url, 52)).classes("sp-promo-img").props(
                    f'alt="{_alt(promo.name or promo.brand)}"'
                )
            else:
                ui.element("div").classes("sp-promo-img").style("background:var(--c-border)")

            # Info block
            with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
                # Deal label ribbon
                if promo.label:
                    ui.label(promo.label).classes(ribbon_cls).style(
                        "display:inline-block;margin-bottom:.2rem"
                    )

                name = promo.name or promo.brand
                if promo.url:
                    ui.link(name, promo.url, new_tab=True).style(
                        "font-size:13px;font-weight:600;color:var(--c-text);text-decoration:none;"
                        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3;"
                        "display:block"
                    ).tooltip("Bekijken op plus.nl")
                else:
                    ui.label(name).style(
                        "font-size:13px;font-weight:600;color:var(--c-text);"
                        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3"
                    )
                if promo.subtitle:
                    ui.label(promo.subtitle).style(
                        f"font-size:11px;color:{'var(--c-accent)' if is_fd else 'var(--c-text-3)'};"
                        "line-height:1.2"
                    )
                # Prices
                with ui.element("div").style(
                    "display:flex;align-items:center;gap:.375rem;margin-top:.2rem"
                ):
                    if promo.price_new > 0:
                        ui.label(f"€ {promo.price_new:.2f}".replace(".", ",")).style(
                            f"font-size:13px;font-weight:700;color:{accent}"
                        )
                    if promo.price_was > 0 and promo.price_new > 0:
                        ui.label(f"€ {promo.price_was:.2f}".replace(".", ",")).style(
                            "font-size:11px;color:var(--c-text-4);text-decoration:line-through"
                        )

            # Right action
            with ui.element("div").style("flex-shrink:0;display:flex;align-items:center"):
                if promo.is_single_product and promo.sku:
                    _render_promo_stepper(promo, cart_qty, is_syncing, cart_service)
                else:
                    # Group deal: expand/collapse button. Show the child count up front
                    # ("Bekijken (N)") from the warmed cache; fall back to the fetched
                    # list once expanded, or a bare "Bekijken" when the count is unknown.
                    n_products = (
                        len(state.promo_products.get(promo.slug))
                        if (promo.slug in state.promo_products)
                        else len(state.cached_children.get(promo.slug, []))
                    )
                    label = f"Bekijken ({n_products})" if n_products else "Bekijken"
                    icon = "expand_less" if is_expanded else "expand_more"
                    with ui.element("div").style(
                        "display:flex;flex-direction:column;align-items:center;gap:1px"
                    ):
                        ui.button(
                            icon=icon,
                            on_click=lambda _, s=promo.slug: asyncio.ensure_future(
                                _toggle_expand(s, state, session, refresh_fn)
                            ),
                        ).props("flat round dense size=sm color=grey")
                        if not is_expanded:
                            ui.label(label).style(
                                "font-size:10px;color:var(--c-text-3);line-height:1"
                            )

        # Expanded products for group deals
        if is_expanded and promo.slug in state.promo_products:
            products = state.promo_products[promo.slug]
            if products:
                with ui.element("div").classes("sp-promo-products"):
                    for prod in products:
                        if prod.sku:
                            _render_promo_product(
                                prod, session, cart_service, show_ribbon=not is_fd
                            )
            else:
                ui.label("Geen producten gevonden").style(
                    "font-size:12px;color:var(--c-text-3);padding:.375rem .5rem"
                )
        elif is_expanded and state.loading_slug == promo.slug:
            with ui.element("div").style(
                "display:flex;align-items:center;gap:.375rem;padding:.5rem .5rem"
            ):
                ui.spinner(size="14px", color="primary")
                ui.label("Producten laden…").style("font-size:12px;color:var(--c-text-3)")


def _render_promo_stepper(promo: Promotion, cart_qty: int, syncing: bool, cart_service) -> None:
    from pyplus.ui.components.controls import add_button, stepper_button

    if syncing:
        with ui.element("div").style(
            "width:36px;height:36px;display:flex;align-items:center;justify-content:center"
        ):
            ui.spinner(size="14px", color="primary")
        return

    name = promo.name or promo.brand
    price = promo.price_new or promo.price_was

    def _add(_=None) -> None:
        if cart_service:
            asyncio.ensure_future(
                cart_service.add(
                    promo.sku,
                    product_name=name,
                    product_unit="",
                    product_price=price,
                    product_image=promo.image_url,
                )
            )

    if cart_qty == 0:
        add_button(aria_label=t("a11y.add_to_cart"), on_click=_add)
    else:
        with ui.element("div").classes("sp-qty"):
            stepper_button(
                "−",
                aria_label=t("a11y.qty_decrease"),
                on_click=lambda _: asyncio.ensure_future(
                    cart_service.remove(promo.sku) if cart_service else asyncio.sleep(0)
                ),
            )
            ui.label(str(cart_qty)).classes("sp-qty-count")
            stepper_button("+", aria_label=t("a11y.qty_increase"), on_click=_add)


def _render_promo_product(
    prod: PromotionProduct, session, cart_service, *, show_ribbon: bool = True
) -> None:
    """One product inside an expanded group deal."""
    cart_qty = next((it.quantity for it in session.cart.items if it.sku == prod.sku), 0)
    is_syncing = prod.sku in session.syncing_skus

    with ui.element("div").classes("sp-search-result").style("padding:.375rem .5rem"):
        if prod.image_url:
            ui.image(thumbnail_url(prod.image_url, 36)).classes("sp-search-img").style(
                "width:36px;height:36px"
            ).props(f'alt="{_alt(prod.name)}"')
        else:
            ui.element("div").classes("sp-search-img").style(
                "width:36px;height:36px;background:var(--c-border)"
            )

        with ui.element("div").classes("sp-search-info"):
            if prod.url:
                ui.link(prod.name, prod.url, new_tab=True).classes("sp-search-name").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                    "text-decoration:none;color:inherit;display:block"
                ).tooltip("Bekijken op plus.nl")
            else:
                ui.label(prod.name).classes("sp-search-name").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )
            with ui.element("div").style("display:flex;align-items:center;gap:.375rem"):
                if prod.subtitle:
                    ui.label(prod.subtitle).classes("sp-search-unit")
                if prod.price_new > 0:
                    ui.label(f"€ {prod.price_new:.2f}".replace(".", ",")).classes(
                        "sp-search-price"
                    ).style("color:var(--c-brand-dark)")
                if prod.label and show_ribbon:
                    ui.label(prod.label).classes("sp-promo-ribbon").style(
                        "font-size:9px;padding:1px 5px"
                    )

        with ui.element("div").classes("sp-search-right"):
            if not prod.is_available:
                # Can't be bought → just say so, no add control (and no green
                # check on the available ones — the add button speaks for itself).
                ui.label(t("status.discontinued")).classes("sp-badge sp-badge-unavailable").style(
                    "font-size:10px;padding:1px 6px;white-space:nowrap"
                )
            elif is_syncing:
                with ui.element("div").style(
                    "width:36px;height:36px;display:flex;align-items:center;justify-content:center"
                ):
                    ui.spinner(size="14px", color="primary")
            else:
                from pyplus.ui.components.controls import add_button, stepper_button

                def _add(_=None, p=prod) -> None:
                    if cart_service:
                        asyncio.ensure_future(
                            cart_service.add(
                                p.sku,
                                product_name=p.name,
                                product_unit=p.subtitle,
                                product_price=p.price_new or p.price_original,
                                product_image=p.image_url,
                            )
                        )

                if cart_qty == 0:
                    add_button(aria_label=t("a11y.add_to_cart"), on_click=_add)
                else:
                    with ui.element("div").classes("sp-qty"):
                        stepper_button(
                            "−",
                            aria_label=t("a11y.qty_decrease"),
                            on_click=lambda _, p=prod: asyncio.ensure_future(
                                cart_service.remove(p.sku) if cart_service else asyncio.sleep(0)
                            ),
                        )
                        ui.label(str(cart_qty)).classes("sp-qty-count")
                        stepper_button("+", aria_label=t("a11y.qty_increase"), on_click=_add)


# ── Cache helpers ──────────────────────────────────────────────────────────────


async def _read_cache(store_number: int, week_start: datetime.date) -> list[Promotion] | None:
    """Return cached promotions for this store+week, or None if not cached."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await repo.get_promotions_cache(db, store_number, week_start, False)
    if row is None:
        return None
    try:
        data = json.loads(row.payload_json)
        return [Promotion(**p) for p in data["promotions"]]
    except Exception as exc:
        log.warning("Cache deserialization failed: %s", exc)
        return None


async def _cache_is_stale(store_number: int, week_start: datetime.date) -> bool:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await repo.get_promotions_cache(db, store_number, week_start, False)
    if row is None:
        return True
    age = (
        datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - row.fetched_at
    ).total_seconds()
    return age > _CACHE_TTL_HOURS * 3600


async def _save_cache(
    store_number: int, week_start: datetime.date, promotions: list[Promotion]
) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # Preserve the job-warmed group-deal children — this lane's refresh only
        # updates the promotions list (prices/sort); the children (slug → products)
        # stay valid for the week. Dropping them would silently break the cart's
        # on-offer hint for child SKUs until the next refresh_promotions run.
        existing = await repo.get_promotions_cache(db, store_number, week_start, False)
        children: dict = {}
        if existing is not None:
            try:
                children = json.loads(existing.payload_json).get("children", {}) or {}
            except Exception:
                children = {}
        payload = json.dumps(
            {
                "promotions": [dataclasses.asdict(p) for p in promotions],
                "children": children,
            }
        )
        await repo.upsert_promotions_cache(db, store_number, week_start, False, payload)


async def _background_refresh(session, state: _DealsState, week_start, render_fn) -> None:
    """Silently refresh promotions from PLUS and update the lane when done."""
    try:
        result = await session.client.get_promotions_api()
        state.promotions = result.promotions
        await _save_cache(session.store_number, week_start, result.promotions)
        render_fn.refresh()
    except Exception as exc:
        log.warning("Background promotions refresh failed: %s", exc)


async def _apply_ml_sort(session, promotions: list) -> list:
    """Re-sort promotions by ML promo_match scores if the feature is enabled."""
    try:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.ml.interface import UserSettings

        async with AsyncSessionLocal() as db:
            settings_json = await repo.get_user_settings_json(db, session.user_id)
        settings = (
            UserSettings.model_validate_json(settings_json) if settings_json else UserSettings()
        )

        if not settings.ml_enabled or not settings.ml_promo_match:
            return promotions

        from pyplus.ml.artifacts import load_artifact

        promo_order = await load_artifact(session.user_id, "promo_match")
        if not promo_order:
            return promotions

        # Sort by position in precomputed order list
        order_map = {slug: i for i, slug in enumerate(promo_order)}
        n = len(promo_order)
        return sorted(promotions, key=lambda p: order_map.get(p.slug, n))
    except Exception as exc:
        log.debug("promo_match sort failed: %s", exc)
        return promotions


async def _enrich_from_catalogue(session, products: list[PromotionProduct]) -> None:
    """Fill availability + a sensible price from the store catalogue.

    The promotion-detail endpoint returns IsAvailable=False and NewPrice=0 for all
    children, so we override from product_cache (store-accurate) when present.
    """
    store = getattr(session, "store_number", 0) or 0
    if not store or not products:
        return
    try:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            cat = await repo.get_product_cache_by_skus(db, store, [p.sku for p in products])
    except Exception as exc:
        log.debug("Promo catalogue enrich failed: %s", exc)
        return

    for p in products:
        row = cat.get(p.sku)
        if row is None:
            continue
        p.is_available = row.is_available
        if p.price_new <= 0 and row.price:
            p.price_new = row.price
        if not p.image_url and row.image_url:
            p.image_url = row.image_url


async def _toggle_expand(slug: str, state: _DealsState, session, refresh_fn) -> None:
    """Expand/collapse a group deal. Fetches products on first expand."""
    if slug in state.expanded:
        state.expanded.discard(slug)
        refresh_fn.refresh()
        return

    state.expanded.add(slug)

    if slug not in state.promo_products:
        state.loading_slug = slug
        refresh_fn.refresh()
        try:
            # Prefer the cache the promotions job warmed (loaded into state at lane
            # load — instant, no PLUS call); fall back to a live fetch when the cache
            # is cold or predates children.
            products = state.cached_children.get(slug)
            if products is None:
                products = await session.client.get_promotion_products_api(slug)
                products = [p for p in products if p.sku and not p.sku.startswith("0")]
            # The promo-detail API returns IsAvailable=False / NewPrice=0 for every
            # child — useless. Trust the store catalogue for availability + price.
            await _enrich_from_catalogue(session, products)
            state.promo_products[slug] = products
        except Exception as exc:
            log.warning("Promo products fetch failed (%s): %s", slug, exc)
            state.promo_products[slug] = []
        finally:
            state.loading_slug = ""

    refresh_fn.refresh()
