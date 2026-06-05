"""
Live cart panel — qty steppers with optimistic updates, sync indicators, mobile bar.
"""

from __future__ import annotations

import asyncio
import json as _json

from nicegui import ui

from pyplus.i18n import t
from pyplus.ui.format import thumbnail_url


def create_cart_panel(session) -> None:
    """Render the cart panel and wire it to the session's live cart."""
    cart_service = getattr(session, "cart_service", None)
    savings_by_sku: dict = {}  # sku → savings.Saving for the current cart
    promo_by_sku: dict = {}  # sku → Promotion for items currently on offer
    image_by_sku: dict = {}  # sku → catalogue image (fallback when cart line has none)
    cat_by_sku: dict = {}  # sku → category breadcrumb (for grouping/sorting)
    prefs = session.settings

    # Per-item label/image refs for in-place updates (cleared on full refresh)
    _qty_labels: dict[str, "ui.label"] = {}
    _price_labels: dict[str, "ui.label"] = {}
    _image_els: dict[str, "ui.image"] = {}   # sku → image element (for backfill updates)
    _rendered_skus: list[str] = []

    with ui.element("div").classes("sp-cart-panel"):
        # ── Header ─────────────────────────────────────────────────────
        with ui.element("div").classes("sp-cart-header"):
            ui.label(t("cart.title")).classes("sp-cart-title")
            count_badge = (
                ui.label("").classes("sp-badge sp-badge-available").style("font-size:11px")
            )
            count_badge.set_visibility(False)

        # ── Scrollable item list ────────────────────────────────────────
        with ui.element("div").classes("sp-cart-body"):

            def _render_item(item) -> None:
                qty_lbl, price_lbl, img_el = _render_cart_item(
                    item,
                    session,
                    cart_service,
                    savings_by_sku.get(item.sku),
                    promo_by_sku.get(item.sku),
                    image_by_sku.get(item.sku),
                )
                _qty_labels[item.sku] = qty_lbl
                _price_labels[item.sku] = price_lbl
                if img_el is not None:
                    _image_els[item.sku] = img_el
                _rendered_skus.append(item.sku)

            @ui.refreshable
            def _items() -> None:
                _qty_labels.clear()
                _price_labels.clear()
                _image_els.clear()
                _rendered_skus.clear()
                cart = session.cart
                if not cart.items:
                    with ui.element("div").classes("sp-lane-placeholder"):
                        ui.label("🛒").classes("sp-lane-placeholder-icon")
                        ui.label(t("cart.empty")).style(
                            "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                        )
                    return

                items = _sort_items(list(cart.items), prefs.cart_sort)
                if prefs.cart_group_by_category:
                    for cat, group in _group_items(items, cat_by_sku):
                        ui.label(cat).classes("sp-cat-header")
                        for item in group:
                            _render_item(item)
                else:
                    for item in items:
                        _render_item(item)

            _items()

            async def _load_categories() -> None:
                """Load category breadcrumbs once for grouping (cache-only)."""
                skus = [it.sku for it in session.cart.items if it.sku]
                if not skus:
                    return
                from pyplus.services.categories import get_category_index

                idx = await get_category_index(
                    getattr(session, "store_number", 0) or 0, session.user_id, skus
                )
                if idx:
                    cat_by_sku.update(idx)
                    _items.refresh()

            async def _load_promos() -> None:
                """Load the (cache-only) promo index once and tag matching items."""
                store = getattr(session, "store_number", 0) or 0
                if not store:
                    return
                from pyplus.services.promos import get_promo_index

                idx = await get_promo_index(store)
                if idx:
                    promo_by_sku.update(idx)
                    _items.refresh()

            async def _load_images() -> None:
                """Backfill product images from the catalogue for cart lines that
                arrive from PLUS without an ImageURL."""
                store = getattr(session, "store_number", 0) or 0
                skus = [it.sku for it in session.cart.items if it.sku and not it.image_url]
                if not store or not skus:
                    return
                from pyplus.db import repo
                from pyplus.db.engine import AsyncSessionLocal

                try:
                    async with AsyncSessionLocal() as db:
                        cat = await repo.get_product_cache_by_skus(db, store, skus)
                        cached = await repo.get_ingredient_skus_by_skus(db, session.user_id, skus)
                except Exception:
                    return
                for sku in skus:
                    img = (cat.get(sku).image_url if cat.get(sku) else "") or (
                        cached.get(sku).image_url if cached.get(sku) else ""
                    )
                    if img and image_by_sku.get(sku) != img:
                        image_by_sku[sku] = img
                        # Update the image element in-place if it exists;
                        # only fall back to full refresh when the element
                        # is not yet rendered (e.g. backfill on initial load).
                        el = _image_els.get(sku)
                        if el is not None:
                            el.set_source(thumbnail_url(img, 44))
                        else:
                            _items.refresh()
                            return

            if prefs.show_promo_tags:
                asyncio.ensure_future(_load_promos())
            asyncio.ensure_future(_load_images())
            if prefs.cart_group_by_category:
                asyncio.ensure_future(_load_categories())

        # ── Footer ──────────────────────────────────────────────────────
        with ui.element("div").classes("sp-cart-footer"):
            with ui.element("div").classes("sp-cart-total-row"):
                ui.label(t("cart.total")).style(
                    "font-size:13px;font-weight:600;color:var(--c-text-3)"
                )
                total_label = ui.label("€ 0,00").classes("sp-cart-total")

            with ui.element("div").style(
                "display:flex;align-items:center;gap:.375rem;margin-bottom:.375rem"
            ) as savings_row:
                ui.icon("savings", size="14px").style("color:var(--c-brand-dark)")
                savings_label = ui.label("")
                savings_label.classes("sp-cart-savings")
            savings_row.set_visibility(False)

            # ── Savings / optimise ─────────────────────────────────────
            optimise_btn = (
                ui.button(
                    t("cart.optimise"),
                    icon="savings",
                    on_click=lambda: _show_optimise_dialog(session, cart_service, savings_by_sku),
                )
                .props("flat rounded no-caps color=primary")
                .classes("sp-optimise-btn")
            )
            optimise_btn.set_visibility(False)

            with ui.element("div").style(
                "display:flex;gap:.375rem;align-items:center;margin-top:.5rem"
            ):
                ui.button(
                    t("cart.clear"),
                    icon="delete_outline",
                    on_click=lambda: _confirm_clear_cart(cart_service),
                ).props("flat rounded no-caps color=negative").style(
                    "font-size:13px;font-weight:600;height:40px;flex-shrink:0"
                )
                ui.button(
                    t("cart.checkout"),
                    on_click=lambda: ui.navigate.to(
                        "https://www.plus.nl/winkelwagen", new_tab=True
                    ),
                ).props("unelevated rounded color=primary no-caps").style(
                    "flex:1;font-size:13px;font-weight:600;height:40px"
                )

            # ── Export row ─────────────────────────────────────────────
            with ui.element("div").style(
                "display:flex;justify-content:center;gap:.25rem;margin-top:.375rem"
            ):
                ui.button(
                    icon="list_alt",
                    on_click=lambda: _download_shopping_list(session),
                ).props("flat round dense size=sm color=grey-6").tooltip(t("exports.text"))
                ui.button(
                    icon="content_copy",
                    on_click=lambda: asyncio.ensure_future(_copy_shopping_list(session)),
                ).props("flat round dense size=sm color=grey-6").tooltip(t("exports.copy"))

    # ── Reactive wiring ─────────────────────────────────────────────────

    def _on_cart() -> None:
        cart = session.cart
        n = cart.total_items
        count_badge.set_text(str(n))
        count_badge.set_visibility(n > 0)
        total_str = f"€ {cart.final_total:.2f}".replace(".", ",")
        total_label.set_text(total_str)
        if cart.savings > 0.01:
            savings_label.set_text(
                f"−€ {cart.savings:.2f} {t('cart.savings').lower()}".replace(".", ",")
            )
            savings_row.set_visibility(True)
        else:
            savings_row.set_visibility(False)

        # Only full-refresh when the set of cart SKUs changes (items added/removed).
        # For qty-only changes update the labels in-place so images don't re-render.
        current_skus = frozenset(it.sku for it in cart.items)
        if current_skus != frozenset(_rendered_skus):
            _items.refresh()
        else:
            for item in cart.items:
                if item.sku in _qty_labels:
                    _qty_labels[item.sku].set_text(str(item.quantity))
                if item.sku in _price_labels:
                    _price_labels[item.sku].set_text(
                        f"€ {item.price_total:.2f}".replace(".", ",")
                    )

        asyncio.ensure_future(_load_images())
        if prefs.cart_group_by_category:
            asyncio.ensure_future(_load_categories())
        if prefs.show_cart_savings:
            asyncio.ensure_future(_recompute_savings())

    async def _recompute_savings() -> None:
        """Recompute cheaper-pack swaps for the current cart (off the render path)."""
        store = getattr(session, "store_number", 0) or 0
        items = list(session.cart.items)
        new: dict = {}
        if store and items:
            try:
                from pyplus.db import repo
                from pyplus.db.engine import AsyncSessionLocal
                from pyplus.services.savings import find_savings

                async with AsyncSessionLocal() as db:
                    alts = await repo.get_pack_alternatives(
                        db, store, [it.sku for it in items if it.sku]
                    )
                for s in find_savings(items, alts):
                    new[s.sku] = s
            except Exception:
                new = {}
        if new == savings_by_sku:
            return
        savings_by_sku.clear()
        savings_by_sku.update(new)
        total = sum(s.saving for s in savings_by_sku.values())
        optimise_btn.set_visibility(bool(savings_by_sku))
        if savings_by_sku:
            optimise_btn.set_text(
                f"{t('cart.optimise')} · "
                + t("cart.save_amount", amount=f"{total:.2f}".replace(".", ","))
            )
        _items.refresh()

    def _on_error(msg: str) -> None:
        ui.notify(msg, type="warning", position="top-right", timeout=3000, close_button=True)

    session.add_cart_listener(_on_cart)
    session.add_error_listener(_on_error)
    _on_cart()


def _sort_items(items: list, sort: str) -> list:
    """Order cart items per the user's choice; 'cart' keeps the PLUS order."""
    if sort == "name":
        return sorted(items, key=lambda it: (it.product or "").casefold())
    if sort == "price":
        return sorted(items, key=lambda it: it.price_total, reverse=True)
    return items  # "cart" — preserve PLUS/insertion order


def _group_items(items: list, cat_by_sku: dict) -> list[tuple[str, list]]:
    """Bucket items by their top-level category, preserving the given item order
    within each group. Returns [(category, items), …] in display order."""
    from pyplus.services.categories import group_order, top_category

    buckets: dict[str, list] = {}
    for it in items:
        cat = top_category(cat_by_sku.get(it.sku, []))
        buckets.setdefault(cat, []).append(it)
    return [(cat, buckets[cat]) for cat in group_order(list(buckets))]


def _render_cart_item(
    item, session, cart_service, saving=None, promo=None, image=None
) -> tuple:
    """Render one cart item row: thumbnail | name+unit | price + stepper.

    Returns (qty_label, price_label, img_element) for targeted in-place updates.
    """
    is_syncing = item.sku in session.syncing_skus
    sku = item.sku
    img_url = item.image_url or image or ""

    img_el = None
    with ui.element("div").classes("sp-cart-item"):
        # Thumbnail
        if img_url:
            img_el = ui.image(thumbnail_url(img_url, 44)).classes("sp-cart-item-img")
        else:
            ui.element("div").classes("sp-cart-item-img")

        # Name + unit (middle flex)
        with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
            from pyplus.ui.format import plus_product_url

            product_url = plus_product_url(sku=sku)
            if product_url:
                ui.link(item.product, product_url, new_tab=True).classes("sp-cart-item-name").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                    "text-decoration:none;color:inherit;display:block"
                ).tooltip("Bekijken op plus.nl")
            else:
                ui.label(item.product).classes("sp-cart-item-name").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )
            if item.unit:
                ui.label(item.unit).classes("sp-cart-item-unit")

            # On-offer tag (type of promotion, e.g. "1+1 GRATIS")
            if promo is not None:
                from pyplus.services.promos import promo_tag_label

                ui.label(promo_tag_label(promo)).classes("sp-promo-tag").style(
                    "margin-top:2px"
                ).tooltip("In de aanbieding")

            # Cheaper-pack hint
            if saving is not None and not is_syncing:
                with (
                    ui.element("div")
                    .classes("sp-cart-saving-hint")
                    .style(
                        "display:flex;align-items:center;gap:.25rem;margin-top:2px;cursor:pointer"
                    )
                    .on(
                        "click",
                        lambda _, s=saving: asyncio.ensure_future(
                            _apply_saving(session, cart_service, s)
                        ),
                    )
                    .tooltip(
                        t(
                            "cart.swap_desc",
                            cur_qty=saving.cur_qty,
                            cur_pack=saving.cur_pack,
                            new_qty=saving.new_qty,
                            new_pack=saving.new_pack,
                        )
                    )
                ):
                    ui.icon("savings", size="12px").style("color:var(--c-brand-dark)")
                    amt = f"{saving.saving:.2f}".replace(".", ",")
                    ui.label(f"{t('cart.save_amount', amount=amt)} →").style(
                        "font-size:10px;font-weight:600;color:var(--c-brand-dark);"
                        "text-decoration:underline"
                    )

        # Price + stepper (right column)
        with ui.element("div").style(
            "display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0"
        ):
            price_lbl = ui.label(
                f"€ {item.price_total:.2f}".replace(".", ",")
            ).classes("sp-cart-item-price")
            if item.quantity > 1:
                ui.label(
                    f"€ {item.price:.2f}/st".replace(".", ",")
                ).style("font-size:10px;color:var(--c-text-4);text-align:right")

            qty_lbl = _render_stepper(sku, item.quantity, is_syncing, session, cart_service)

    return qty_lbl, price_lbl, img_el


def _render_stepper(sku: str, qty: int, syncing: bool, session, cart_service) -> "ui.label":
    """Inline qty stepper: [−] n [+] with optional spinner when syncing. Returns qty label."""
    qty_lbl = None
    with ui.element("div").classes("sp-qty"):
        if syncing:
            # Show spinner in place of buttons during API call
            with ui.element("div").style(
                "width:28px;height:28px;display:flex;align-items:center;justify-content:center"
            ):
                ui.spinner(size="14px", color="primary")
            qty_lbl = ui.label(str(qty)).classes("sp-qty-count")
            ui.element("div").style("width:28px;height:28px")
        else:
            # Decrement / remove
            with (
                ui.element("div")
                .classes("sp-qty-btn")
                .on(
                    "click",
                    lambda _, s=sku: asyncio.ensure_future(
                        cart_service.remove(s) if cart_service else asyncio.sleep(0)
                    ),
                )
            ):
                ui.label("−").style(
                    "font-size:15px;font-weight:700;line-height:1;pointer-events:none"
                )

            qty_lbl = ui.label(str(qty)).classes("sp-qty-count")

            # Increment
            with (
                ui.element("div")
                .classes("sp-qty-btn")
                .on(
                    "click",
                    lambda _, s=sku: asyncio.ensure_future(
                        cart_service.add(s) if cart_service else asyncio.sleep(0)
                    ),
                )
            ):
                ui.label("+").style(
                    "font-size:15px;font-weight:700;line-height:1;pointer-events:none"
                )
    return qty_lbl


def _confirm_clear_cart(cart_service) -> None:
    with ui.dialog(value=True) as dlg, ui.card().style(
        "max-width:320px;width:100%;padding:1.25rem"
    ):
        ui.label(t("cart.clear_confirm_title")).style(
            "font-size:16px;font-weight:700;color:var(--c-text)"
        )
        ui.label(t("cart.clear_confirm_body")).style(
            "font-size:13px;color:var(--c-text-3);margin:.375rem 0 .875rem"
        )
        with ui.row().style("justify-content:flex-end;gap:.5rem;width:100%"):
            ui.button(t("action.cancel"), on_click=dlg.close).props("flat rounded no-caps")

            async def _yes() -> None:
                dlg.close()
                if cart_service:
                    await cart_service.clear_all()

            ui.button(t("cart.clear"), on_click=lambda: asyncio.ensure_future(_yes())).props(
                "unelevated rounded no-caps color=negative"
            )


async def _apply_saving(session, cart_service, s) -> None:
    """Swap to the cheaper pack: drop the current sku, add the alternative."""
    if not cart_service:
        return
    per_unit = round(s.new_cost / s.new_qty, 2) if s.new_qty else 0.0
    if s.new_sku == s.sku:
        await cart_service.set_quantity(s.sku, s.new_qty)
    else:
        await cart_service.set_quantity(s.sku, 0)
        await cart_service.add(
            s.new_sku,
            s.new_qty,
            product_name=s.name,
            product_unit=f"Per {s.new_pack}",
            product_price=per_unit,
        )
    amt = f"{s.saving:.2f}".replace(".", ",")
    ui.notify(t("cart.save_amount", amount=amt).capitalize(), type="positive", position="top")


def _show_optimise_dialog(session, cart_service, savings_by_sku: dict) -> None:
    savings = sorted(savings_by_sku.values(), key=lambda s: s.saving, reverse=True)
    with ui.dialog(value=True) as dlg:
        with ui.card().style(
            "min-width:300px;max-width:440px;width:100%;padding:0;overflow:hidden"
        ):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label(t("cart.optimise_title")).style(
                    "font-size:16px;font-weight:700;color:var(--c-text)"
                )
                ui.button(icon="close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            with ui.element("div").style("padding:.5rem 1rem;max-height:60vh;overflow-y:auto"):
                if not savings:
                    ui.label(t("cart.optimise_none")).style(
                        "font-size:13px;color:var(--c-text-3);padding:.5rem 0"
                    )
                for s in savings:
                    with ui.element("div").style(
                        "display:flex;align-items:center;gap:.5rem;padding:.5rem 0;"
                        "border-bottom:1px solid var(--c-border)"
                    ):
                        with ui.element("div").style("flex:1;min-width:0"):
                            ui.label(s.name).style(
                                "font-size:13px;font-weight:600;color:var(--c-text);"
                                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                            )
                            ui.label(
                                t(
                                    "cart.swap_desc",
                                    cur_qty=s.cur_qty,
                                    cur_pack=s.cur_pack,
                                    new_qty=s.new_qty,
                                    new_pack=s.new_pack,
                                )
                            ).style("font-size:11px;color:var(--c-text-3)")
                        amt = f"{s.saving:.2f}".replace(".", ",")
                        ui.label(t("cart.save_amount", amount=amt)).style(
                            "font-size:12px;font-weight:700;color:var(--c-brand-dark);flex-shrink:0"
                        )

                        async def _one(snap=s) -> None:
                            await _apply_saving(session, cart_service, snap)

                        ui.button(
                            t("cart.apply"), on_click=lambda _, f=_one: asyncio.ensure_future(f())
                        ).props("flat dense no-caps size=sm color=primary").style("flex-shrink:0")

            if savings:
                total = sum(s.saving for s in savings)
                with ui.element("div").style(
                    "display:flex;align-items:center;gap:.5rem;padding:.75rem 1rem;"
                    "border-top:1px solid var(--c-border)"
                ):
                    ui.label(
                        t("cart.optimise_total", amount=f"{total:.2f}".replace(".", ","))
                    ).style("font-size:13px;font-weight:700;color:var(--c-brand-dark);flex:1")

                    async def _all() -> None:
                        dlg.close()
                        for snap in list(savings):
                            await _apply_saving(session, cart_service, snap)

                    ui.button(
                        t("cart.apply_all"),
                        icon="done_all",
                        on_click=lambda: asyncio.ensure_future(_all()),
                    ).props("unelevated rounded no-caps color=primary size=sm")


def create_mobile_cart_bar(session) -> None:
    """
    Compact sticky bottom bar for mobile (invisible on desktop via CSS).
    Tapping it opens a full-screen cart sheet.
    """
    with ui.element("div").classes("sp-mobile-cart-bar") as bar:
        with ui.element("div").style(
            "display:flex;align-items:center;justify-content:center;"
            "width:28px;height:28px;background:var(--c-brand);border-radius:var(--r-sm);flex-shrink:0"
        ) as cart_icon_wrap:
            ui.icon("shopping_cart", size="16px").style("color:white")

        bar_count = ui.label("0 stuks").style("font-size:13px;font-weight:700;color:var(--c-text)")
        ui.element("div").style("width:1px;height:16px;background:var(--c-border);margin:0 .5rem")
        bar_total = ui.label("€ –").style("font-size:15px;font-weight:700;color:var(--c-text)")
        bar_savings = ui.label("").style(
            "font-size:12px;font-weight:600;color:var(--c-brand-dark);margin-left:auto"
        )

    async def _open_sheet() -> None:
        with (
            ui.dialog(value=True)
            .props("maximized transition-show=slide-up transition-hide=slide-down")
            .style("align-items:flex-end;padding:0") as sheet
        ):
            with ui.card().style(
                "width:100%;border-radius:var(--r-xl) var(--r-xl) 0 0;"
                "padding:0;max-height:85vh;overflow:hidden;display:flex;flex-direction:column"
            ):
                # Grab handle + explicit close — tapping either dismisses the sheet
                # (a maximized dialog has no backdrop to tap, so it needs its own).
                with (
                    ui.element("div")
                    .style(
                        "display:flex;align-items:center;justify-content:center;position:relative;"
                        "padding:.625rem 0 .25rem;cursor:pointer;flex-shrink:0"
                    )
                    .on("click", sheet.close)
                ):
                    ui.element("div").style(
                        "width:36px;height:4px;background:var(--c-border-strong);"
                        "border-radius:var(--r-full)"
                    )
                    ui.button(icon="close", on_click=sheet.close).props(
                        "flat round dense size=sm color=grey"
                    ).style("position:absolute;right:.5rem;top:.25rem")
                with ui.element("div").style("flex:1;min-height:0;overflow:hidden;display:flex"):
                    create_cart_panel(session)

    bar.on("click", _open_sheet)

    _prev_count: list[int] = [0]

    def _on_cart() -> None:
        cart = session.cart
        n = cart.total_items
        if n > _prev_count[0]:
            # New item added — brief "pop" animation on the cart icon
            cart_icon_wrap.classes(add="sp-cart-bump")
            ui.timer(0.25, lambda: cart_icon_wrap.classes(remove="sp-cart-bump"), once=True)
        _prev_count[0] = n
        bar_count.set_text(f"{n} {'stuk' if n == 1 else 'stuks'}")
        bar_total.set_text(f"€ {cart.final_total:.2f}".replace(".", ","))
        bar_savings.set_text(
            f"−€ {cart.savings:.2f}".replace(".", ",") if cart.savings > 0.01 else ""
        )

    session.add_cart_listener(_on_cart)
    _on_cart()


# ── Export helpers ─────────────────────────────────────────────────────────────


def _download_shopping_list(session) -> None:
    from pyplus.services.exports import build_text_list

    text = build_text_list(session.cart)
    ui.download(
        text.encode("utf-8"), "boodschappenlijst.txt", media_type="text/plain; charset=utf-8"
    )


async def _copy_shopping_list(session) -> None:
    from pyplus.services.exports import build_text_list

    text = build_text_list(session.cart)
    try:
        await ui.run_javascript(f"navigator.clipboard.writeText({_json.dumps(text)})")
        ui.notify(
            "Lijst gekopieerd",
            type="positive",
            position="top",
            timeout=2000,
            close_button=False,
        )
    except Exception:
        ui.notify("Kopiëren niet gelukt in deze browser", type="warning", position="top")
