"""
Search lane component (Lane ④) — instant product search with add-to-cart.
"""

from __future__ import annotations

import asyncio
import logging

from nicegui import ui

from pyplus.i18n import t
from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url

log = logging.getLogger(__name__)

_DEBOUNCE = 0.25  # seconds


def create_search_lane(session) -> None:
    """Render Lane ④ — Zoeken inside a `.sp-lane` container."""
    cart_service = getattr(session, "cart_service", None)
    _debounce_task: list[asyncio.Task] = [None]  # mutable container for closure
    _results: list = []  # current search results (shared mutable state)

    # Per-result qty label refs — only populated for SKUs currently in cart.
    # Used to update counts in-place without rebuilding the whole row (and its image).
    _qty_labels: dict[str, ui.label] = {}
    # SKU sets from the last full render — used to detect structural changes.
    _last_in_cart: list[frozenset] = [frozenset()]  # result SKUs rendered as in-cart
    _last_syncing: list[frozenset] = [frozenset()]  # result SKUs rendered as syncing

    with (
        ui.element("div").classes("sp-lane").style("display:flex;flex-direction:column;height:100%")
    ):
        # ── Header ─────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            ui.label(t("lane.search.title")).classes("sp-lane-title")

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
                    _qty_labels.clear()
                    if not _results:
                        return
                    cart_qty_map = {it.sku: it.quantity for it in session.cart.items}
                    syncing = session.syncing_skus
                    for product in _results:
                        qty_lbl = _render_product_row(product, cart_qty_map, syncing, cart_service)
                        if qty_lbl is not None:
                            _qty_labels[product.sku] = qty_lbl
                    result_skus = {p.sku for p in _results}
                    _last_in_cart[0] = frozenset(result_skus & cart_qty_map.keys())
                    _last_syncing[0] = frozenset(result_skus & syncing)

                _results_list()

    # ── Debounced search handler ─────────────────────────────────────────
    _generation: list[int] = [0]  # incremented each keypress; stale results are discarded

    async def _search(query: str, gen: int) -> None:
        query = query.strip()
        if len(query) < 3:
            _results.clear()
            status_label.set_text("")
            _results_list.refresh()
            return

        try:
            from pyplus.services.search import search_products

            prefs = session.settings
            found = await search_products(session, query, limit=prefs.search_result_limit)
            if gen != _generation[0]:
                return  # a newer keypress is already in flight — discard
            if prefs.hide_unavailable_search:
                found = [p for p in found if p.is_available]
            _results.clear()
            _results.extend(found)
            if found:
                status_label.set_text(f"{len(found)} resultaten")
            else:
                status_label.set_text(t("lane.search.no_results"))
        except Exception as exc:
            if gen != _generation[0]:
                return
            log.warning("Search error: %s", exc)
            _results.clear()
            status_label.set_text(t("status.error"))
        finally:
            if gen == _generation[0]:
                search_spinner.set_visibility(False)
                _results_list.refresh()

    async def _on_input(e) -> None:
        query = e.value if hasattr(e, "value") else search_input.value
        if _debounce_task[0] and not _debounce_task[0].done():
            _debounce_task[0].cancel()

        # Immediately clear stale results so the previous query's output never
        # lingers while the debounce is waiting for the next search to fire.
        _generation[0] += 1
        gen = _generation[0]
        stripped = (query or "").strip()
        if len(stripped) >= 3:
            _results.clear()
            _results_list.refresh()
            search_spinner.set_visibility(True)
            status_label.set_text(t("status.loading"))
        else:
            _results.clear()
            _results_list.refresh()
            search_spinner.set_visibility(False)
            status_label.set_text("")

        async def _debounced():
            await asyncio.sleep(_DEBOUNCE)
            await _search(query, gen)

        _debounce_task[0] = asyncio.create_task(_debounced())

    search_input.on("update:model-value", _on_input)
    search_input.on("clear", lambda _: asyncio.ensure_future(_search("")))

    # ── Cart listener: update steppers without rebuilding rows ───────────
    # A full refresh is only needed when a result SKU crosses the 0↔in-cart
    # boundary (the DOM structure changes between [+] button and [−]n[+]).
    # For qty-only changes the count label is updated in-place.
    def _on_cart() -> None:
        if not _results:
            return
        cart_qty_map = {it.sku: it.quantity for it in session.cart.items}
        result_skus = {p.sku for p in _results}
        in_cart_now = frozenset(s for s in result_skus if cart_qty_map.get(s, 0) > 0)

        # Only the in-cart boundary (0 ⇄ in-cart) changes a row's structure. Syncing
        # toggles are deliberately ignored: refreshing the whole list on every sync
        # on/off would tear down and re-fetch every result image (visible flicker).
        if in_cart_now != _last_in_cart[0]:
            _results_list.refresh()
        else:
            for sku, lbl in _qty_labels.items():
                lbl.set_text(str(cart_qty_map.get(sku, 0)))

    session.add_cart_listener(_on_cart)


def _render_product_row(
    product, cart_qty_map: dict, syncing: set, cart_service
) -> "ui.label | None":
    """One product result row: image | name+subtitle+price | stepper.

    Returns the qty count label if the product is currently in the cart,
    None otherwise (no label to update in-place).
    """
    cart_qty = cart_qty_map.get(product.sku, 0)
    is_syncing = product.sku in syncing

    with ui.element("div").classes("sp-search-result"):
        # Thumbnail
        if product.image_url:
            ui.image(thumbnail_url(product.image_url, 44)).classes("sp-search-img").props(
                f'alt="{_alt(product.name)}"'
            )
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
                ui.label(f"€\xa0{product.price:.2f}".replace(".", ",")).classes("sp-search-price")

        # Right side: stepper
        with ui.element("div").classes("sp-search-right"):
            return _render_search_stepper(product.sku, cart_qty, is_syncing, cart_service, product)


def _render_search_stepper(
    sku: str, cart_qty: int, syncing: bool, cart_service, product
) -> "ui.label | None":
    """Returns the qty count label for in-cart items, None otherwise."""
    from pyplus.ui.components.controls import add_button, stepper_button

    if syncing:
        with ui.element("div").style(
            "width:36px;height:36px;display:flex;align-items:center;justify-content:center"
        ):
            ui.spinner(size="14px", color="primary")
        return None

    def _add(_=None) -> None:
        if cart_service:
            asyncio.ensure_future(
                cart_service.add(
                    sku,
                    product_name=product.name,
                    product_unit=product.subtitle,
                    product_price=product.price,
                    product_image=product.image_url,
                    source="search",
                )
            )

    if cart_qty == 0:
        add_button(aria_label=t("a11y.add_to_cart"), on_click=_add)
        return None

    # Full stepper [−] n [+]
    with ui.element("div").classes("sp-qty"):
        stepper_button(
            "−",
            aria_label=t("a11y.qty_decrease"),
            on_click=lambda _: asyncio.ensure_future(
                cart_service.remove(sku) if cart_service else asyncio.sleep(0)
            ),
        )
        qty_lbl = ui.label(str(cart_qty)).classes("sp-qty-count")
        stepper_button("+", aria_label=t("a11y.qty_increase"), on_click=_add)
    return qty_lbl


def create_search_bar(session) -> None:
    """Compact search bar — input + results, no lane wrapper or header."""
    cart_service = getattr(session, "cart_service", None)
    _debounce_task: list[asyncio.Task | None] = [None]
    _results: list = []
    _qty_labels: dict[str, ui.label] = {}
    _last_in_cart: list[frozenset] = [frozenset()]

    search_input = (
        ui.input(placeholder=t("lane.search.placeholder"))
        .props("outlined dense clearable")
        .style("width:100%")
    )
    search_input.props("prepend-icon=search")

    status_row = ui.element("div").style("display:flex;align-items:center;gap:.5rem;min-height:0")
    with status_row:
        search_spinner = ui.spinner(size="16px", color="primary")
        search_spinner.set_visibility(False)
        status_label = ui.label("").style("font-size:12px;color:var(--c-text-3)")

    with ui.element("div"):

        @ui.refreshable
        def _results_list() -> None:
            _qty_labels.clear()
            if not _results:
                return
            cart_qty_map = {it.sku: it.quantity for it in session.cart.items}
            syncing = session.syncing_skus
            for product in _results:
                qty_lbl = _render_product_row(product, cart_qty_map, syncing, cart_service)
                if qty_lbl is not None:
                    _qty_labels[product.sku] = qty_lbl
            _last_in_cart[0] = frozenset({p.sku for p in _results} & cart_qty_map.keys())

        _results_list()

    _generation: list[int] = [0]

    async def _search(query: str, gen: int) -> None:
        query = query.strip()
        if len(query) < 3:
            _results.clear()
            status_label.set_text("")
            _results_list.refresh()
            return
        try:
            from pyplus.services.search import search_products

            prefs = session.settings
            found = await search_products(session, query, limit=prefs.search_result_limit)
            if gen != _generation[0]:
                return
            if prefs.hide_unavailable_search:
                found = [p for p in found if p.is_available]
            _results.clear()
            _results.extend(found)
            if found:
                status_label.set_text(f"{len(found)} resultaten")
            else:
                status_label.set_text(t("lane.search.no_results"))
        except Exception as exc:
            if gen != _generation[0]:
                return
            log.warning("Search error: %s", exc)
            _results.clear()
            status_label.set_text(t("status.error"))
        finally:
            if gen == _generation[0]:
                search_spinner.set_visibility(False)
                _results_list.refresh()

    async def _on_input(e) -> None:
        query = e.value if hasattr(e, "value") else search_input.value
        if _debounce_task[0] and not _debounce_task[0].done():
            _debounce_task[0].cancel()
        _generation[0] += 1
        gen = _generation[0]
        stripped = (query or "").strip()
        if len(stripped) >= 3:
            _results.clear()
            _results_list.refresh()
            search_spinner.set_visibility(True)
            status_label.set_text(t("status.loading"))
        else:
            _results.clear()
            _results_list.refresh()
            search_spinner.set_visibility(False)
            status_label.set_text("")

        async def _debounced():
            await asyncio.sleep(_DEBOUNCE)
            await _search(query, gen)

        _debounce_task[0] = asyncio.create_task(_debounced())

    search_input.on("update:model-value", _on_input)
    search_input.on("clear", lambda _: asyncio.ensure_future(_search("", _generation[0])))

    def _on_cart() -> None:
        if not _results:
            return
        cart_qty_map = {it.sku: it.quantity for it in session.cart.items}
        in_cart_now = frozenset(s for s in {p.sku for p in _results} if cart_qty_map.get(s, 0) > 0)
        if in_cart_now != _last_in_cart[0]:
            _results_list.refresh()
        else:
            for sku, lbl in _qty_labels.items():
                lbl.set_text(str(cart_qty_map.get(sku, 0)))

    session.add_cart_listener(_on_cart)
