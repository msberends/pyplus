"""
Live cart panel — qty steppers with optimistic updates, sync indicators, mobile bar.
"""

from __future__ import annotations

import asyncio
import json as _json

from nicegui import ui

from pyplus.i18n import t
from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url


def create_cart_panel(session) -> None:
    """Render the cart panel and wire it to the session's live cart."""
    cart_service = getattr(session, "cart_service", None)
    savings_by_sku: dict = {}  # sku → savings.Saving for the current cart
    promo_by_sku: dict = {}  # sku → Promotion for items currently on offer
    image_by_sku: dict = {}  # sku → catalogue image (fallback when cart line has none)
    cat_by_sku: dict = {}  # sku → category breadcrumb (for grouping/sorting)
    prefs = session.settings

    # Keyed rows: sku → refs dict. Rows are reused across cart changes (created /
    # deleted / moved as the SKU set changes, sub-parts updated in place otherwise)
    # so product images are NEVER torn down and re-fetched on a qty change or add.
    _rows: dict[str, dict] = {}
    _headers: list = []  # category header label elements (grouping mode)
    _structure: list = [None]  # signature of the last rendered order, to skip re-layout

    def _cart_item(sku: str):
        return next((it for it in session.cart.items if it.sku == sku), None)

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
            body_inner = ui.element("div")  # stable container holding rows + headers
            empty_holder = ui.element("div")  # holds the empty-cart placeholder

            # ── Per-row slot fillers (update one row's sub-part in place) ──

            def _fill_image(refs, item) -> None:
                holder = refs["img_holder"]
                holder.clear()
                url = item.image_url or image_by_sku.get(item.sku, "")
                if url:
                    with holder:
                        ui.image(thumbnail_url(url, 44)).style(
                            "width:100%;height:100%;object-fit:contain;border-radius:inherit"
                        ).props(f'alt="{_alt(item.product)}"')

            def _fill_perunit(refs, item) -> None:
                slot = refs["perunit_slot"]
                slot.clear()
                if item.quantity > 1:
                    with slot:
                        ui.label(f"€ {item.price:.2f}/st".replace(".", ",")).style(
                            "font-size:10px;color:var(--c-text-4);text-align:right"
                        )

            def _fill_promo(refs, item) -> None:
                slot = refs["promo_slot"]
                slot.clear()
                promo = promo_by_sku.get(item.sku)
                # Emphasise the row itself when its product is on offer — these are the
                # "responsible" products behind the korting banner. The class is toggled
                # regardless of the tag preference; the textual tag still respects it.
                if promo is not None:
                    refs["row"].classes(add="sp-cart-item-promo")
                else:
                    refs["row"].classes(remove="sp-cart-item-promo")
                if promo is None or not prefs.show_promo_tags:
                    return
                from pyplus.services.promos import promo_tag_label

                with slot:
                    ui.label(promo_tag_label(promo)).classes("sp-promo-tag").style(
                        "margin-top:2px"
                    ).tooltip("In de aanbieding")

            def _fill_saving(refs, item) -> None:
                slot = refs["saving_slot"]
                slot.clear()
                saving = savings_by_sku.get(item.sku)
                if saving is None or item.sku in session.syncing_skus:
                    return

                def _open(s=saving):
                    # Read the current image at click time — _load_images may backfill
                    # image_by_sku after this hint was filled.
                    it = _cart_item(s.sku)
                    img = (it.image_url if it else "") or image_by_sku.get(s.sku, "")
                    _show_swap_dialog(session, cart_service, s, img)

                with slot:
                    with (
                        ui.element("div")
                        .classes("sp-cart-saving-hint")
                        .style(
                            "display:flex;align-items:center;gap:.25rem;margin-top:2px;cursor:pointer"
                        )
                        .on(
                            "click",
                            lambda _, f=_open: f(),
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

            def _fill_stepper(refs, item) -> None:
                from pyplus.ui.components.controls import stepper_button

                slot = refs["stepper_slot"]
                slot.clear()
                sku = item.sku
                syncing = sku in session.syncing_skus
                refs["syncing"] = syncing
                with slot, ui.element("div").classes("sp-qty"):
                    if syncing:
                        with ui.element("div").style(
                            "width:36px;height:36px;display:flex;align-items:center;justify-content:center"
                        ):
                            ui.spinner(size="14px", color="primary")
                        refs["qty"] = ui.label(str(item.quantity)).classes("sp-qty-count")
                        ui.element("div").style("width:36px;height:36px")
                    else:
                        stepper_button(
                            "−",
                            aria_label=t("a11y.qty_decrease"),
                            on_click=lambda _, s=sku: (
                                cart_service.remove(s) if cart_service else None
                            ),
                        )
                        refs["qty"] = ui.label(str(item.quantity)).classes("sp-qty-count")
                        stepper_button(
                            "+",
                            aria_label=t("a11y.qty_increase"),
                            on_click=lambda _, s=sku: cart_service.add(s) if cart_service else None,
                        )

            def _build_row(item) -> dict:
                """Create one cart row (with stable slots) in the current container."""
                from pyplus.ui.format import plus_product_url

                refs: dict = {"sku": item.sku}
                with ui.element("div").classes("sp-cart-item") as row:
                    refs["row"] = row
                    refs["img_holder"] = (
                        ui.element("div").classes("sp-cart-item-img").style("overflow:hidden")
                    )
                    with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
                        product_url = plus_product_url(sku=item.sku)
                        if product_url:
                            ui.link(item.product, product_url, new_tab=True).classes(
                                "sp-cart-item-name"
                            ).style(
                                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                                "text-decoration:none;color:inherit;display:block"
                            ).tooltip("Bekijken op plus.nl")
                        else:
                            ui.label(item.product).classes("sp-cart-item-name").style(
                                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                            )
                        if item.unit:
                            ui.label(item.unit).classes("sp-cart-item-unit")
                        refs["promo_slot"] = ui.element("div").style("display:contents")
                        refs["saving_slot"] = ui.element("div").style("display:contents")
                    with ui.element("div").style(
                        "display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0"
                    ):
                        refs["price"] = ui.label(
                            f"€ {item.price_total:.2f}".replace(".", ",")
                        ).classes("sp-cart-item-price")
                        refs["perunit_slot"] = ui.element("div").style("display:contents")
                        refs["stepper_slot"] = ui.element("div").style("display:contents")
                _fill_image(refs, item)
                _fill_perunit(refs, item)
                _fill_stepper(refs, item)
                _fill_promo(refs, item)
                _fill_saving(refs, item)
                return refs

            def _update_row(refs, item) -> None:
                """Update an existing row's sub-parts in place (image untouched).

                Promo tag depends on neither qty nor sync (filled at build / by
                _load_promos); the saving hint only needs re-filling when the sync
                state flips (it hides while syncing). So a plain qty tick touches
                just the qty/price/per-unit labels — no slot churn, no image work.
                """
                refs["price"].set_text(f"€ {item.price_total:.2f}".replace(".", ","))
                _fill_perunit(refs, item)
                now_sync = item.sku in session.syncing_skus
                if now_sync != refs.get("syncing"):
                    _fill_stepper(refs, item)  # toggle stepper ⇄ spinner
                    _fill_saving(refs, item)  # hide/show hint for the new sync state
                else:
                    q = refs.get("qty")
                    if q is not None:
                        q.set_text(str(item.quantity))

            def _sync() -> None:
                """Reconcile rows against the current cart without rebuilding images.

                Same order as last time → update rows in place. Order/SKU set changed
                → add/remove/move only the affected rows; reused rows keep their image.
                """
                cart = session.cart
                items = _sort_items(list(cart.items), prefs.cart_sort)
                if not items:
                    for refs in list(_rows.values()):
                        refs["row"].delete()
                    _rows.clear()
                    for h in _headers:
                        h.delete()
                    _headers.clear()
                    _structure[0] = ()
                    empty_holder.clear()
                    with empty_holder:
                        with ui.element("div").classes("sp-lane-placeholder"):
                            ui.label("🛒").classes("sp-lane-placeholder-icon")
                            ui.label(t("cart.empty")).style(
                                "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                            )
                    return
                empty_holder.clear()

                plan: list = []  # ("h", label) | ("i", item)
                if prefs.cart_group_by_category:
                    for cat, group in _group_items(items, cat_by_sku):
                        plan.append(("h", cat))
                        for it in group:
                            plan.append(("i", it))
                else:
                    for it in items:
                        plan.append(("i", it))

                structure = tuple(
                    (typ, payload if typ == "h" else payload.sku) for typ, payload in plan
                )
                if structure == _structure[0]:
                    # Same layout — just refresh row contents in place.
                    for typ, payload in plan:
                        if typ == "i":
                            _update_row(_rows[payload.sku], payload)
                    return

                # Structural change — reconcile order, adding/removing only what changed.
                _structure[0] = structure
                desired = {payload.sku for typ, payload in plan if typ == "i"}
                for sku in list(_rows):
                    if sku not in desired:
                        _rows[sku]["row"].delete()
                        del _rows[sku]
                for h in _headers:
                    h.delete()
                _headers.clear()

                new_skus = False
                for idx, (typ, payload) in enumerate(plan):
                    if typ == "h":
                        with body_inner:
                            hl = ui.label(payload).classes("sp-cat-header")
                        hl.move(body_inner, idx)
                        _headers.append(hl)
                    else:
                        sku = payload.sku
                        if sku in _rows:
                            _update_row(_rows[sku], payload)
                            _rows[sku]["row"].move(body_inner, idx)
                        else:
                            with body_inner:
                                refs = _build_row(payload)
                            refs["row"].move(body_inner, idx)
                            _rows[sku] = refs
                            new_skus = True

                # New items may need promo/category/image metadata fetched. Promos are
                # loaded regardless of the tag preference — they also drive the on-offer
                # row emphasis (cache-only read, so still fast-open compliant).
                if new_skus:
                    asyncio.ensure_future(_load_promos())
                    asyncio.ensure_future(_load_images())
                    if prefs.cart_group_by_category:
                        asyncio.ensure_future(_load_categories())

            async def _load_categories() -> None:
                """Load category breadcrumbs for grouping (cache-only); re-sync if changed."""
                skus = [it.sku for it in session.cart.items if it.sku]
                if not skus:
                    return
                from pyplus.services.categories import get_category_index

                idx = await get_category_index(
                    getattr(session, "store_number", 0) or 0, session.user_id, skus
                )
                if idx and any(cat_by_sku.get(k) != v for k, v in idx.items()):
                    cat_by_sku.update(idx)
                    _sync()

            async def _load_promos() -> None:
                """Load the (cache-only) promo index and tag matching rows in place."""
                store = getattr(session, "store_number", 0) or 0
                if not store:
                    return
                from pyplus.services.promos import get_promo_index

                idx = await get_promo_index(store)
                if idx:
                    promo_by_sku.update(idx)
                for sku, refs in list(_rows.items()):
                    item = _cart_item(sku)
                    if item:
                        _fill_promo(refs, item)

            async def _load_images() -> None:
                """Backfill catalogue images for cart lines lacking one — one row at a time."""
                store = getattr(session, "store_number", 0) or 0
                skus = [
                    it.sku
                    for it in session.cart.items
                    if it.sku and not it.image_url and not image_by_sku.get(it.sku)
                ]
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
                        refs = _rows.get(sku)
                        item = _cart_item(sku)
                        if refs and item:
                            _fill_image(refs, item)  # updates only this row's thumbnail

            _sync()
            asyncio.ensure_future(_load_promos())  # drives on-offer row emphasis + tags
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

            # Promotional discount banner — styled like the Aanbiedingen lane (green
            # tag) so it reads clearly as money saved on offers, not just a number.
            with ui.element("div").classes("sp-cart-savings-banner") as savings_row:
                ui.icon("local_offer", size="15px")
                savings_label = ui.label("").classes("sp-cart-savings")
                ui.label(t("cart.savings_from")).classes("sp-cart-savings-from")
            savings_row.set_visibility(False)

            # Statiegeld line — a cost already counted in the total, not a discount.
            # Neutral styling keeps it visually distinct from the green korting banner.
            with ui.element("div").classes("sp-cart-deposit-line") as deposit_row:
                ui.icon("recycling", size="15px")
                deposit_label = ui.label("").classes("sp-cart-deposit-amount")
                ui.label(t("cart.deposit_note")).classes("sp-cart-deposit-note")
            deposit_row.set_visibility(False)

            # ── Savings / optimise ─────────────────────────────────────
            optimise_btn = (
                ui.button(
                    t("cart.optimise"),
                    icon="savings",
                    on_click=lambda: _show_optimise_dialog(
                        session, cart_service, savings_by_sku, image_by_sku
                    ),
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
                    on_click=lambda: _copy_shopping_list(session),
                ).props("flat round dense size=sm color=grey-6").tooltip(t("exports.copy"))

    # ── Reactive wiring ─────────────────────────────────────────────────

    # Debounce the (DB-querying) savings recompute. The cart listener fires up to
    # ~4× per tap (optimistic write, syncing-on, server reconcile, syncing-off);
    # coalesce those into one computation shortly after the last change.
    _savings_task: list = [None]

    def _schedule_savings() -> None:
        if not prefs.show_cart_savings:
            return
        if _savings_task[0] is not None and not _savings_task[0].done():
            _savings_task[0].cancel()

        async def _run() -> None:
            try:
                await asyncio.sleep(0.35)
            except asyncio.CancelledError:
                return
            await _recompute_savings()

        _savings_task[0] = asyncio.create_task(_run())

    def _on_cart() -> None:
        cart = session.cart
        n = cart.total_items
        count_badge.set_text(str(n))
        count_badge.set_visibility(n > 0)
        total_str = f"€ {cart.final_total:.2f}".replace(".", ",")
        total_label.set_text(total_str)
        if cart.savings > 0.01:
            savings_label.set_text(
                f"€ {cart.savings:.2f} {t('cart.savings').lower()}".replace(".", ",")
            )
            savings_row.set_visibility(True)
        else:
            savings_row.set_visibility(False)

        if cart.deposit > 0.01:
            deposit_label.set_text(
                f"€ {cart.deposit:.2f} {t('cart.deposit').lower()}".replace(".", ",")
            )
            deposit_row.set_visibility(True)
        else:
            deposit_row.set_visibility(False)

        # Reconcile the keyed rows: qty/sync changes update in place (images keep
        # their DOM element), only added/removed/reordered rows touch the structure.
        _sync()

        # Savings depend on quantities too, so recompute on any change — debounced.
        _schedule_savings()

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
        # Update the per-row saving hints in place — no list refresh, no image churn.
        for sku, refs in list(_rows.items()):
            item = _cart_item(sku)
            if item:
                _fill_saving(refs, item)

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


def _confirm_clear_cart(cart_service) -> None:
    with (
        ui.dialog(value=True) as dlg,
        ui.card().style("max-width:320px;width:100%;padding:1.25rem"),
    ):
        ui.label(t("cart.clear_confirm_title")).style(
            "font-size:16px;font-weight:700;color:var(--c-text)"
        )
        ui.label(t("cart.clear_confirm_body")).style(
            "font-size:13px;color:var(--c-text-3);margin:.375rem 0 .875rem"
        )
        with ui.row().style("justify-content:flex-end;gap:.5rem;width:100%"):
            # Autofocus the safe (non-destructive) action on a confirm-delete dialog.
            ui.button(t("action.cancel"), on_click=dlg.close).props(
                "flat rounded no-caps autofocus"
            )

            async def _yes() -> None:
                dlg.close()
                if cart_service:
                    await cart_service.clear_all()

            ui.button(t("cart.clear"), on_click=lambda: _yes()).props(
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
            product_unit=s.new_subtitle or f"Per {s.new_pack}",
            product_price=per_unit,
            product_image=s.new_image,
        )
    amt = f"{s.saving:.2f}".replace(".", ",")
    ui.notify(t("cart.save_amount", amount=amt).capitalize(), type="positive", position="top")


def _swap_product_row(
    label: str,
    image: str,
    name: str,
    subtitle: str,
    qty: int,
    unit_price: float,
    total: float,
    highlight: bool,
) -> None:
    """One product row in the swap dialog — formatted like a staples/promo row:
    image · name + subtitle · quantity × unit price + total."""
    border = "var(--c-brand)" if highlight else "var(--c-border)"
    with ui.element("div").style(
        "display:flex;align-items:center;gap:.625rem;padding:.5rem .625rem;"
        f"border:1px solid {border};border-radius:var(--r-sm)"
    ):
        if image:
            ui.image(thumbnail_url(image, 44)).style(
                "width:44px;height:44px;object-fit:contain;border-radius:var(--r-sm);"
                "background:var(--c-surface-2);flex-shrink:0"
            ).props(f'alt="{_alt(name)}"')
        else:
            ui.element("div").style(
                "width:44px;height:44px;border-radius:var(--r-sm);"
                "background:var(--c-border);flex-shrink:0"
            )
        with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
            ui.label(label).style(
                "font-size:10px;font-weight:600;text-transform:uppercase;"
                "letter-spacing:.03em;color:var(--c-text-4)"
            )
            ui.label(name).style(
                "font-size:13px;font-weight:600;color:var(--c-text);line-height:1.3;"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            )
            if subtitle:
                ui.label(subtitle).style("font-size:11px;color:var(--c-text-3);line-height:1.2")
        with ui.element("div").style(
            "display:flex;flex-direction:column;align-items:flex-end;flex-shrink:0"
        ):
            ui.label(f"{qty}× € {unit_price:.2f}".replace(".", ",")).style(
                "font-size:10px;color:var(--c-text-4)"
            )
            ui.label(f"€ {total:.2f}".replace(".", ",")).style(
                "font-size:14px;font-weight:700;color:var(--c-text)"
            )


def _show_swap_dialog(session, cart_service, s, cur_image: str) -> None:
    """Confirm a cheaper-pack swap, showing the current and suggested product as rows."""
    with ui.dialog(value=True) as dlg:
        with ui.card().style(
            "min-width:300px;max-width:420px;width:100%;padding:0;overflow:hidden"
        ):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label(t("cart.swap_title")).style(
                    "font-size:16px;font-weight:700;color:var(--c-text)"
                )
                ui.button(icon="close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            with ui.element("div").style(
                "padding:.75rem 1rem;display:flex;flex-direction:column;gap:.5rem"
            ):
                _swap_product_row(
                    t("cart.swap_current"),
                    cur_image,
                    s.name,
                    s.cur_subtitle or s.cur_pack,
                    s.cur_qty,
                    s.cur_unit_price,
                    s.cur_cost,
                    highlight=False,
                )
                ui.icon("south", size="18px").style("color:var(--c-text-4);align-self:center")
                _swap_product_row(
                    t("cart.swap_suggested"),
                    s.new_image,
                    s.name,
                    s.new_subtitle or s.new_pack,
                    s.new_qty,
                    s.new_unit_price,
                    s.new_cost,
                    highlight=True,
                )
                amt = f"{s.saving:.2f}".replace(".", ",")
                with ui.element("div").style(
                    "display:flex;align-items:center;gap:.25rem;align-self:center;margin-top:.125rem"
                ):
                    ui.icon("savings", size="14px").style("color:var(--c-brand-dark)")
                    ui.label(t("cart.save_amount", amount=amt).capitalize()).style(
                        "font-size:13px;font-weight:700;color:var(--c-brand-dark)"
                    )

            with ui.element("div").style(
                "display:flex;justify-content:flex-end;gap:.5rem;"
                "padding:.75rem 1rem;border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.cancel"), on_click=dlg.close).props("flat rounded no-caps")

                async def _confirm() -> None:
                    dlg.close()
                    await _apply_saving(session, cart_service, s)

                ui.button(t("cart.swap_confirm"), on_click=lambda: _confirm()).props(
                    "unelevated rounded no-caps color=primary"
                )


def _show_optimise_dialog(
    session, cart_service, savings_by_sku: dict, image_by_sku: dict | None = None
) -> None:
    savings = sorted(savings_by_sku.values(), key=lambda s: s.saving, reverse=True)
    image_by_sku = image_by_sku or {}

    def _cur_image(sku: str) -> str:
        it = next((i for i in session.cart.items if i.sku == sku), None)
        return (it.image_url if it else "") or image_by_sku.get(sku, "")

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
                    # Each swap: current → suggested rows (like the per-row dialog),
                    # with its own savings line + per-product apply button.
                    with ui.element("div").style(
                        "display:flex;flex-direction:column;gap:.375rem;padding:.625rem 0;"
                        "border-bottom:1px solid var(--c-border)"
                    ):
                        _swap_product_row(
                            t("cart.swap_current"),
                            _cur_image(s.sku),
                            s.name,
                            s.cur_subtitle or s.cur_pack,
                            s.cur_qty,
                            s.cur_unit_price,
                            s.cur_cost,
                            highlight=False,
                        )
                        ui.icon("south", size="16px").style(
                            "color:var(--c-text-4);align-self:center"
                        )
                        _swap_product_row(
                            t("cart.swap_suggested"),
                            s.new_image,
                            s.name,
                            s.new_subtitle or s.new_pack,
                            s.new_qty,
                            s.new_unit_price,
                            s.new_cost,
                            highlight=True,
                        )
                        with ui.element("div").style(
                            "display:flex;align-items:center;gap:.5rem;margin-top:.125rem"
                        ):
                            amt = f"{s.saving:.2f}".replace(".", ",")
                            with ui.element("div").style(
                                "display:flex;align-items:center;gap:.25rem;flex:1"
                            ):
                                ui.icon("savings", size="14px").style("color:var(--c-brand-dark)")
                                ui.label(t("cart.save_amount", amount=amt)).style(
                                    "font-size:12px;font-weight:700;color:var(--c-brand-dark)"
                                )

                            async def _one(snap=s) -> None:
                                await _apply_saving(session, cart_service, snap)

                            ui.button(t("cart.swap_confirm"), on_click=lambda _, f=_one: f()).props(
                                "flat dense no-caps size=sm color=primary"
                            ).style("flex-shrink:0")

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
                        on_click=lambda: _all(),
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
        bar_savings = ui.label("").classes("sp-bar-savings")
        bar_savings.set_visibility(False)

    async def _open_sheet() -> None:
        with (
            ui.dialog(value=True)
            .props("maximized transition-show=slide-up transition-hide=slide-down")
            .style("align-items:flex-end;padding:0") as sheet
        ):
            with ui.card().style(
                "width:100%;border-radius:var(--r-xl) var(--r-xl) 0 0;"
                "padding:0;max-height:85vh;overflow:hidden;display:flex;flex-direction:column;"
                # nicegui-card defaults to align-items:flex-start, which lets the
                # handle + cart panel collapse to their content width and bleed off
                # the right on narrow phones — stretch children to the full width.
                "align-items:stretch"
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
        # Update the bar text FIRST. These run even when the listener fires from a
        # detached task (cart adds go through asyncio.ensure_future, so there is no
        # active slot/client context) — set_text targets each element's own client.
        bar_count.set_text(f"{n} {'stuk' if n == 1 else 'stuks'}")
        bar_total.set_text(f"€ {cart.final_total:.2f}".replace(".", ","))
        bar_savings.set_text(
            f"€ {cart.savings:.2f}".replace(".", ",") if cart.savings > 0.01 else ""
        )
        bar_savings.set_visibility(cart.savings > 0.01)
        # Best-effort "pop" on add. Creating a ui.timer needs a slot/client context,
        # which is absent in the detached add task — so guard it and never let it
        # block the text updates above (that blocked bar updates entirely before).
        if n > _prev_count[0]:
            try:
                cart_icon_wrap.classes(add="sp-cart-bump")
                ui.timer(0.25, lambda: cart_icon_wrap.classes(remove="sp-cart-bump"), once=True)
            except Exception:
                pass
        _prev_count[0] = n

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
