"""
Lane ② — Vaste boodschappen: the user's curated staple products.

Each row shows a cart-synced stepper.  The "Alles toevoegen" button adds every
product not yet in the cart at its default_qty in one shot.
"""

from __future__ import annotations

import asyncio
import logging

from nicegui import ui

from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import FixedProduct, IngredientSku
from pyplus.i18n import t

log = logging.getLogger(__name__)


async def create_staples_lane(session) -> None:
    """Render Lane ② — Vaste boodschappen."""
    cart_service = getattr(session, "cart_service", None)
    store = session.store_number or 0
    list_ref: dict = {"fn": None}  # current row-list refresher (for cart-change updates)

    # Register the cart listener once; it points at whichever _list is current.
    session.add_cart_listener(lambda: list_ref["fn"].refresh() if list_ref["fn"] else None)

    with ui.element("div").classes("sp-lane"):
        # ── Header ────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;gap:.5rem"
            ):
                ui.label(t("lane.staples.title")).classes("sp-lane-title")
                with ui.element("div").style("display:flex;align-items:center;gap:.25rem"):
                    add_btn = (
                        ui.button(icon="add")
                        .props("flat round dense size=sm color=primary")
                        .tooltip("Vaste boodschap toevoegen")
                    )
                    addall_holder = ui.element("div")

        body = ui.element("div").classes("sp-lane-body sp-staples-body")

        @ui.refreshable
        async def _body() -> None:
            # ── Load data ──────────────────────────────────────────────
            products: list = []
            sku_cache: dict = {}
            catalogue: dict = {}
            catalogue_known = False
            load_error = ""
            purchased: dict = {}
            try:
                async with AsyncSessionLocal() as db:
                    products = await repo.get_fixed_products(db, session.user_id)
                    skus = [p.sku for p in products if p.sku]
                    sku_cache = await repo.get_ingredient_skus_by_skus(db, session.user_id, skus)
                    # Purchase history is an extra image source for products the
                    # store no longer carries ("niet verkrijgbaar").
                    purchased = await repo.get_purchased_products_by_skus(db, session.user_id, skus)
                    if store:
                        catalogue = await repo.get_product_cache_by_skus(db, store, skus)
                        catalogue_known = await repo.count_product_cache(db, store) > 0
            except Exception as exc:
                log.error("Staples lane load failed: %s", exc)
                load_error = "Vaste boodschappen konden niet worden geladen."

            prefs = session.settings
            replenish_scores = await _load_replenish(session) if prefs.show_replenish_hints else {}

            # Promotions this item may be part of (cache-only, no PLUS call).
            promo_index: dict = {}
            if store and prefs.show_promo_tags:
                from pyplus.services.promos import get_promo_index

                promo_index = await get_promo_index(store)

            # ── "Alles toevoegen" lives in the header; rebuild it each load ──
            addall_holder.clear()
            with addall_holder:
                if products:
                    ui.button(
                        "Alles toevoegen",
                        icon="add_shopping_cart",
                        on_click=lambda: asyncio.ensure_future(
                            _add_all(products, sku_cache, session, cart_service)
                        ),
                    ).props("flat dense no-caps color=primary size=sm").style(
                        "font-size:12px;font-weight:600"
                    )

            if load_error:
                with ui.element("div").classes("sp-lane-error"):
                    ui.icon("error_outline", size="24px").style("color:var(--c-danger);opacity:.6")
                    ui.label(load_error).style("font-size:13px;color:var(--c-text-3)")
                return

            # ── Add-product search (toggled by the header + button) ────────
            _render_add_search(session, store, _body)

            if not products:
                with ui.element("div").classes("sp-lane-placeholder"):
                    ui.label("📋").classes("sp-lane-placeholder-icon")
                    ui.label("Nog geen vaste boodschappen.").style(
                        "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                    )
                return

            from pyplus.services.categories import group_order, parse_categories, top_category

            def _cats(fp) -> list[str]:
                row = catalogue.get(fp.sku)
                cats = parse_categories(getattr(row, "categories_json", None)) if row else []
                if not cats and purchased.get(fp.sku):
                    cats = parse_categories(purchased[fp.sku].categories_json)
                return cats

            def _name_key(fp) -> str:
                row, c = catalogue.get(fp.sku), sku_cache.get(fp.sku)
                return (
                    (row.name if row else None) or (c.name if c else None) or fp.display_name or ""
                ).casefold()

            def _price_key(fp) -> float:
                row, c = catalogue.get(fp.sku), sku_cache.get(fp.sku)
                return (row.price if row else None) or (c.last_price if c else 0.0) or 0.0

            # Base ordering per the user's chosen sort.
            if prefs.staples_sort == "name":
                sorted_products = sorted(products, key=_name_key)
            elif prefs.staples_sort == "price":
                sorted_products = sorted(products, key=_price_key, reverse=True)
            elif replenish_scores:  # "smart" — soonest-due first
                from pyplus.ml.replenish import sort_fixed_products_by_due

                sorted_products = [
                    p
                    for sku in sort_fixed_products_by_due(
                        [p.sku for p in products], replenish_scores
                    )
                    for p in products
                    if p.sku == sku
                ]
            else:
                sorted_products = products

            def _row(fp) -> None:
                _render_row(
                    fp,
                    sku_cache.get(fp.sku),
                    catalogue.get(fp.sku),
                    catalogue_known,
                    session,
                    cart_service,
                    replenish_scores.get(fp.sku),
                    _body,
                    promo_index.get(fp.sku),
                    purchased.get(fp.sku),
                )

            @ui.refreshable
            def _list() -> None:
                if prefs.staples_group_by_category:
                    buckets: dict = {}
                    for fp in sorted_products:
                        buckets.setdefault(top_category(_cats(fp)), []).append(fp)
                    for cat in group_order(list(buckets)):
                        ui.label(cat).classes("sp-cat-header")
                        for fp in buckets[cat]:
                            _row(fp)
                else:
                    for fp in sorted_products:
                        _row(fp)

            list_ref["fn"] = _list
            _list()

        # The + button toggles the add-search visibility via module state.
        add_btn.on("click", lambda: _toggle_add_search(_body))

        with body:
            await _body()


# Add-search open/closed state, keyed per render via a simple flag on the closure.
_ADD_OPEN: dict[int, bool] = {}


def _toggle_add_search(body_refresh) -> None:
    key = id(body_refresh)
    _ADD_OPEN[key] = not _ADD_OPEN.get(key, False)
    body_refresh.refresh()


def _render_add_search(session, store: int, body_refresh) -> None:
    if not _ADD_OPEN.get(id(body_refresh)):
        return

    state = {"results": [], "searching": False}

    with ui.element("div").style(
        "padding:.375rem .25rem .5rem;border-bottom:1px solid var(--c-border);margin-bottom:.25rem"
    ):
        with ui.element("div").style("position:relative"):
            field = (
                ui.input(placeholder="Zoek een product om toe te voegen…")
                .props("outlined dense clearable autofocus")
                .style("width:100%")
            )

            @ui.refreshable
            def _results() -> None:
                if state["searching"]:
                    ui.label("Zoeken…").style(
                        "padding:.375rem .5rem;font-size:12px;color:var(--c-text-3)"
                    )
                    return
                for prod in state["results"][:8]:

                    async def _pick(p=prod) -> None:
                        async with AsyncSessionLocal() as db:
                            await repo.add_fixed_product(db, session.user_id, p.sku, p.name)
                            from pyplus.services.dishes import cache_ingredient_sku_from_product

                            await cache_ingredient_sku_from_product(db, session.user_id, p)
                        _ADD_OPEN[id(body_refresh)] = False
                        ui.notify(f"{p.name} toegevoegd", type="positive", position="top")
                        body_refresh.refresh()

                    with (
                        ui.element("div")
                        .style(
                            "display:flex;align-items:center;gap:.5rem;padding:.3rem .5rem;cursor:pointer"
                        )
                        .on("click", _pick)
                    ):
                        if prod.image_url:
                            ui.image(prod.image_url).style(
                                "width:28px;height:28px;object-fit:contain;border-radius:4px;"
                                "background:var(--c-border);flex-shrink:0"
                            )
                        ui.label(prod.name).style(
                            "font-size:12px;flex:1;min-width:0;overflow:hidden;"
                            "text-overflow:ellipsis;white-space:nowrap"
                        )

            _results()

            async def _on_input(e, fld=field) -> None:
                # update:model-value carries no `.value` here — fall back to the
                # field's synced value so typing actually drives the search.
                q = (e.value if hasattr(e, "value") else fld.value) or ""
                if len(q.strip()) < 2:
                    state["results"] = []
                    _results.refresh()
                    return
                state["searching"] = True
                _results.refresh()
                try:
                    from pyplus.services.search import search_products

                    state["results"] = await search_products(session, q)
                except Exception:
                    state["results"] = []
                state["searching"] = False
                _results.refresh()

            field.on("update:model-value", _on_input)


async def _load_replenish(session) -> dict:
    """Load the replenishment artifact when ML replenishment is enabled."""
    try:
        from pyplus.db import repo as _repo
        from pyplus.db.engine import AsyncSessionLocal as _ASSL
        from pyplus.ml.interface import UserSettings

        async with _ASSL() as _db:
            _sj = await _repo.get_user_settings_json(_db, session.user_id)
        _settings = UserSettings.model_validate_json(_sj) if _sj else UserSettings()
        if _settings.ml_enabled and _settings.ml_replenish:
            from pyplus.ml.artifacts import load_artifact

            return await load_artifact(session.user_id, "replenishment") or {}
    except Exception:
        pass
    return {}


def _render_row(
    fp: FixedProduct,
    cached: IngredientSku | None,
    catalogue_row,
    catalogue_known: bool,
    session,
    cart_service,
    replenish_score=None,
    body_refresh=None,
    promo=None,
    purchased=None,
) -> None:
    cart_qty = next((it.quantity for it in session.cart.items if it.sku == fp.sku), 0)
    is_syncing = fp.sku in session.syncing_skus

    # Prefer the store catalogue (fresh, store-accurate) over the per-user sku_cache.
    name = (catalogue_row.name if catalogue_row else None) or (
        cached.name if cached else fp.display_name
    )
    subtitle = (catalogue_row.subtitle if catalogue_row else None) or (
        cached.subtitle if cached else ""
    )
    if catalogue_row:
        price = catalogue_row.price or 0.0
    else:
        price = cached.last_price or 0.0 if cached else 0.0
    # Image: catalogue → pinned sku cache → purchase history. The last source
    # keeps a picture for "niet verkrijgbaar" products no longer in the catalogue.
    image = (
        (catalogue_row.image_url if catalogue_row else None)
        or (cached.image_url if cached else None)
        or (purchased.image_url if purchased else "")
    )
    slug = (catalogue_row.slug if catalogue_row else None) or (cached.slug if cached else "")

    # Availability: catalogue is authoritative. Not in catalogue (once synced) =
    # the store no longer carries it → "vervallen". In catalogue = use its flag.
    discontinued = catalogue_known and catalogue_row is None
    if catalogue_row is not None:
        available = catalogue_row.is_available
    elif cached and cached.last_seen_available is not None:
        available = cached.last_seen_available
    else:
        available = None

    from pyplus.i18n import t
    from pyplus.ui.format import plus_product_url

    product_url = plus_product_url(slug, fp.sku)

    is_due = replenish_score is not None and replenish_score.is_due
    row_style = "background:var(--c-brand-tint);border-radius:var(--r-sm)" if is_due else ""

    with ui.element("div").classes("sp-staples-item").style(row_style):
        # Product thumbnail (with availability dot overlaid in the corner)
        with ui.element("div").style("position:relative;width:34px;height:34px;flex-shrink:0"):
            if image:
                ui.image(image).style(
                    "width:34px;height:34px;border-radius:var(--r-sm);"
                    "object-fit:contain;background:var(--c-surface-2)"
                )
            else:
                ui.element("div").style(
                    "width:34px;height:34px;border-radius:var(--r-sm);background:var(--c-border)"
                )
            if not discontinued and available is not None:
                dot_cls = "sp-avail-dot-ok" if available else "sp-avail-dot-no"
                ui.element("div").classes(f"sp-avail-dot {dot_cls}").style(
                    "position:absolute;top:-2px;right:-2px"
                )

        # Name + subtitle + replenishment reason
        with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
            if product_url:
                ui.link(name, product_url, new_tab=True).style(
                    "font-size:13px;font-weight:500;color:var(--c-text);text-decoration:none;"
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3;"
                    "display:block"
                ).tooltip("Bekijken op plus.nl")
            else:
                ui.label(name).style(
                    "font-size:13px;font-weight:500;color:var(--c-text);"
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3"
                )
            if discontinued:
                ui.label(t("status.discontinued")).classes("sp-badge sp-badge-unavailable").style(
                    "font-size:10px;margin-top:1px;display:inline-block"
                )
            else:
                reason_line = subtitle
                if replenish_score and replenish_score.reason:
                    reason_line = replenish_score.reason
                if reason_line:
                    ui.label(reason_line).style(
                        "font-size:11px;color:var(--c-text-3);line-height:1.2"
                    )

        # On-offer tag (type of promotion, e.g. "1+1 GRATIS")
        if promo is not None and not discontinued:
            from pyplus.services.promos import promo_tag_label

            ui.label(promo_tag_label(promo)).classes("sp-promo-tag").style(
                "flex-shrink:0;margin-right:.25rem"
            ).tooltip("In de aanbieding")

        # Price
        if price > 0 and not discontinued:
            ui.label(f"€ {price:.2f}".replace(".", ",")).style(
                "font-size:12px;color:var(--c-text-3);flex-shrink:0;margin-right:.25rem"
            )

        # Stepper — only for products that can actually be bought. A
        # "Niet verkrijgbaar" product has no add control.
        if not discontinued:
            _render_stepper(fp, cart_qty, is_syncing, name, subtitle, price, image, cart_service)

        # Remove from staples
        if body_refresh is not None:

            async def _delete(s=fp.sku) -> None:
                async with AsyncSessionLocal() as db:
                    await repo.remove_fixed_product(db, session.user_id, s)
                body_refresh.refresh()

            ui.button(icon="close", on_click=lambda: asyncio.ensure_future(_delete())).props(
                "flat round dense size=xs color=grey-5"
            ).tooltip("Verwijderen uit vaste boodschappen")


def _render_stepper(fp, cart_qty, syncing, name, subtitle, price, image, cart_service) -> None:
    if syncing:
        with ui.element("div").style(
            "width:32px;height:32px;display:flex;align-items:center;justify-content:center"
        ):
            ui.spinner(size="14px", color="primary")
        return

    if cart_qty == 0:
        default_qty = fp.default_qty or 1
        with (
            ui.element("div")
            .classes("sp-search-add-btn")
            .on(
                "click",
                lambda _, f=fp, n=name, s=subtitle, p=price, img=image, q=default_qty: (
                    asyncio.ensure_future(
                        cart_service.add(
                            f.sku,
                            q,
                            product_name=n,
                            product_unit=s,
                            product_price=p,
                            product_image=img,
                        )
                    )
                    if cart_service
                    else None
                ),
            )
        ):
            ui.label("+").style(
                "font-size:18px;font-weight:700;color:var(--c-brand-dark);line-height:1;pointer-events:none"
            )
    else:
        with ui.element("div").classes("sp-qty"):
            with (
                ui.element("div")
                .classes("sp-qty-btn")
                .on(
                    "click",
                    lambda _, f=fp: (
                        asyncio.ensure_future(cart_service.remove(f.sku)) if cart_service else None
                    ),
                )
            ):
                ui.label("−").style(
                    "font-size:15px;font-weight:700;line-height:1;pointer-events:none"
                )
            ui.label(str(cart_qty)).classes("sp-qty-count")
            with (
                ui.element("div")
                .classes("sp-qty-btn")
                .on(
                    "click",
                    lambda _, f=fp, n=name, s=subtitle, p=price, img=image: (
                        asyncio.ensure_future(
                            cart_service.add(
                                f.sku,
                                product_name=n,
                                product_unit=s,
                                product_price=p,
                                product_image=img,
                            )
                        )
                        if cart_service
                        else None
                    ),
                )
            ):
                ui.label("+").style(
                    "font-size:15px;font-weight:700;line-height:1;pointer-events:none"
                )


async def _add_all(
    products: list[FixedProduct],
    sku_cache: dict[str, IngredientSku],
    session,
    cart_service,
) -> None:
    """Add all products not already in the cart at their default_qty."""
    if not cart_service:
        return

    cart_skus = {it.sku for it in session.cart.items}

    for fp in products:
        if not fp.sku or fp.sku in cart_skus:
            continue
        cached = sku_cache.get(fp.sku)
        name = cached.name if cached else fp.display_name
        subtitle = cached.subtitle if cached else ""
        price = cached.last_price or 0.0 if cached else 0.0
        image = cached.image_url if cached else ""
        await cart_service.add(
            fp.sku,
            fp.default_qty or 1,
            product_name=name,
            product_unit=subtitle,
            product_price=price,
            product_image=image,
        )
