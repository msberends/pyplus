"""
Search lane component (Lane ④) — instant product search with add-to-cart.
"""

from __future__ import annotations

import asyncio
import logging

from nicegui import ui

from pyplus.i18n import t

log = logging.getLogger(__name__)

_DEBOUNCE = 0.25  # seconds


def create_search_lane(session) -> None:
    """Render Lane ④ — Zoeken inside a `.sp-lane` container."""
    cart_service = getattr(session, "cart_service", None)
    _debounce_task: list[asyncio.Task] = [None]  # mutable container for closure
    _results: list = []  # current search results (shared mutable state)

    with (
        ui.element("div").classes("sp-lane").style("display:flex;flex-direction:column;height:100%")
    ):
        # ── Header ─────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            ui.label(t("lane.search.title")).classes("sp-lane-title")
            ui.label(t("lane.search.placeholder").replace("…", "")).classes("sp-lane-subtitle")

        # ── Body ────────────────────────────────────────────────────────
        with (
            ui.element("div")
            .classes("sp-lane-body")
            .style("flex:1;display:flex;flex-direction:column;gap:.625rem;overflow:hidden")
        ):
            # Search input
            with ui.element("div").style("position:relative"):
                search_input = (
                    ui.input(placeholder=t("lane.search.placeholder"))
                    .props("outlined dense clearable")
                    .style("width:100%")
                )
                # Search icon inside the input (Quasar prepend slot)
                search_input.props("prepend-icon=search")

            # Status / skeleton area
            status_row = ui.element("div").style(
                "display:flex;align-items:center;gap:.5rem;min-height:20px"
            )
            with status_row:
                search_spinner = ui.spinner(size="16px", color="primary")
                search_spinner.set_visibility(False)
                status_label = ui.label("").style("font-size:12px;color:var(--c-text-3)")

            # Results list (scrollable)
            with ui.element("div").style("flex:1;overflow-y:auto;min-height:0"):

                @ui.refreshable
                def _results_list() -> None:
                    if not _results:
                        return
                    for product in _results:
                        _render_product_row(product, session, cart_service)

                _results_list()

    # ── Debounced search handler ─────────────────────────────────────────

    async def _search(query: str) -> None:
        query = query.strip()
        if len(query) < 2:
            _results.clear()
            status_label.set_text("")
            _results_list.refresh()
            return

        # Show spinner
        search_spinner.set_visibility(True)
        status_label.set_text(t("status.loading"))

        try:
            from pyplus.services.search import search_products

            found = await search_products(session, query)
            _results.clear()
            _results.extend(found)
            if found:
                status_label.set_text(f"{len(found)} resultaten")
            else:
                status_label.set_text(t("lane.search.no_results"))
        except Exception as exc:
            log.warning("Search error: %s", exc)
            _results.clear()
            status_label.set_text(t("status.error"))
        finally:
            search_spinner.set_visibility(False)
            _results_list.refresh()

    async def _on_input(e) -> None:
        query = e.value if hasattr(e, "value") else search_input.value
        # Cancel previous debounce task
        if _debounce_task[0] and not _debounce_task[0].done():
            _debounce_task[0].cancel()

        async def _debounced():
            await asyncio.sleep(_DEBOUNCE)
            await _search(query)

        _debounce_task[0] = asyncio.create_task(_debounced())

    search_input.on("update:model-value", _on_input)
    search_input.on("clear", lambda _: asyncio.ensure_future(_search("")))

    # Re-render search results when cart changes (keeps steppers in sync with cart qtys)
    session.add_cart_listener(lambda: _results_list.refresh() if _results else None)


def _render_product_row(product, session, cart_service) -> None:
    """One product result row: image | name+subtitle+price | badge + stepper."""
    # Current qty of this product in the cart
    cart_qty = next((it.quantity for it in session.cart.items if it.sku == product.sku), 0)
    is_syncing = product.sku in session.syncing_skus

    with ui.element("div").classes("sp-search-result"):
        # Thumbnail
        if product.image_url:
            ui.image(product.image_url).classes("sp-search-img")
        else:
            ui.element("div").classes("sp-search-img").style(
                "background:var(--c-border);border-radius:var(--r-sm)"
            )

        # Info block
        with ui.element("div").classes("sp-search-info"):
            from pyplus.ui.format import plus_product_url

            product_url = plus_product_url(getattr(product, "slug", ""), product.sku)
            if product_url:
                ui.link(product.name, product_url, new_tab=True).classes("sp-search-name").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                    "text-decoration:none;color:var(--c-text);display:block"
                ).tooltip("Bekijken op plus.nl")
            else:
                ui.label(product.name).classes("sp-search-name").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )
            with ui.element("div").style("display:flex;align-items:center;gap:.5rem"):
                if product.subtitle:
                    ui.label(product.subtitle).classes("sp-search-unit")
                ui.label(f"€ {product.price:.2f}".replace(".", ",")).classes("sp-search-price")

        # Right side: availability + stepper
        with ui.element("div").classes("sp-search-right"):
            # Availability badge
            if product.is_available:
                ui.label("✓").classes("sp-badge sp-badge-available").style(
                    "font-size:10px;padding:1px 6px"
                )
            else:
                ui.label("uitv").classes("sp-badge sp-badge-unavailable").style(
                    "font-size:10px;padding:1px 6px"
                )

            # Stepper (shows [+] when not in cart, [−] n [+] when in cart)
            _render_search_stepper(product.sku, cart_qty, is_syncing, cart_service, product)


def _render_search_stepper(sku: str, cart_qty: int, syncing: bool, cart_service, product) -> None:
    if syncing:
        with ui.element("div").style(
            "width:32px;height:32px;display:flex;align-items:center;justify-content:center"
        ):
            ui.spinner(size="14px", color="primary")
        return

    if cart_qty == 0:
        # Just a [+] button
        with (
            ui.element("div")
            .classes("sp-search-add-btn")
            .on(
                "click",
                lambda _, s=sku, p=product: asyncio.ensure_future(
                    cart_service.add(
                        s,
                        product_name=p.name,
                        product_unit=p.subtitle,
                        product_price=p.price,
                        product_image=p.image_url,
                    )
                    if cart_service
                    else asyncio.sleep(0)
                ),
            )
        ):
            ui.label("+").style(
                "font-size:18px;font-weight:700;color:var(--c-brand-dark);line-height:1;pointer-events:none"
            )
    else:
        # Full stepper [−] n [+]
        with ui.element("div").classes("sp-qty"):
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
            ui.label(str(cart_qty)).classes("sp-qty-count")
            with (
                ui.element("div")
                .classes("sp-qty-btn")
                .on(
                    "click",
                    lambda _, s=sku, p=product: asyncio.ensure_future(
                        cart_service.add(
                            s,
                            product_name=p.name,
                            product_unit=p.subtitle,
                            product_price=p.price,
                            product_image=p.image_url,
                        )
                        if cart_service
                        else asyncio.sleep(0)
                    ),
                )
            ):
                ui.label("+").style(
                    "font-size:15px;font-weight:700;line-height:1;pointer-events:none"
                )
