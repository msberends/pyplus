"""
Live cart panel — qty steppers with optimistic updates, sync indicators, mobile bar.
"""

from __future__ import annotations

import asyncio
import json as _json

from nicegui import ui

from pyplus.i18n import t


def create_cart_panel(session) -> None:
    """Render the cart panel and wire it to the session's live cart."""
    cart_service = getattr(session, "cart_service", None)

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

            @ui.refreshable
            def _items() -> None:
                cart = session.cart
                if not cart.items:
                    with ui.element("div").classes("sp-lane-placeholder"):
                        ui.label("🛒").classes("sp-lane-placeholder-icon")
                        ui.label(t("cart.empty")).style(
                            "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                        )
                    return

                for item in cart.items:
                    _render_cart_item(item, session, cart_service)

            _items()

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

            ui.button(
                t("cart.checkout"),
                on_click=lambda: ui.navigate.to("https://www.plus.nl/winkelwagen", new_tab=True),
            ).props("unelevated rounded color=primary no-caps").classes("sp-checkout-btn")

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
        _items.refresh()

    def _on_error(msg: str) -> None:
        ui.notify(msg, type="warning", position="top-right", timeout=3000, close_button=True)

    session.add_cart_listener(_on_cart)
    session.add_error_listener(_on_error)
    _on_cart()


def _render_cart_item(item, session, cart_service) -> None:
    """Render one cart item row: thumbnail | name+unit | price + stepper."""
    is_syncing = item.sku in session.syncing_skus
    sku = item.sku

    with ui.element("div").classes("sp-cart-item"):
        # Thumbnail
        if item.image_url:
            ui.image(item.image_url).classes("sp-cart-item-img")
        else:
            ui.element("div").classes("sp-cart-item-img")

        # Name + unit (middle flex)
        with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
            ui.label(item.product).classes("sp-cart-item-name").style(
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            )
            if item.unit:
                ui.label(item.unit).classes("sp-cart-item-unit")

        # Price + stepper (right column)
        with ui.element("div").style(
            "display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0"
        ):
            ui.label(f"€ {item.price_total:.2f}".replace(".", ",")).classes("sp-cart-item-price")

            _render_stepper(sku, item.quantity, is_syncing, session, cart_service)


def _render_stepper(sku: str, qty: int, syncing: bool, session, cart_service) -> None:
    """Inline qty stepper: [−] n [+] with optional spinner when syncing."""
    with ui.element("div").classes("sp-qty"):
        if syncing:
            # Show spinner in place of buttons during API call
            with ui.element("div").style(
                "width:28px;height:28px;display:flex;align-items:center;justify-content:center"
            ):
                ui.spinner(size="14px", color="primary")
            ui.label(str(qty)).classes("sp-qty-count")
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

            ui.label(str(qty)).classes("sp-qty-count")

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
        with ui.dialog(value=True).props("maximized").style("align-items:flex-end;padding:0"):
            with ui.card().style(
                "width:100%;border-radius:var(--r-xl) var(--r-xl) 0 0;"
                "padding:0;max-height:85vh;overflow:hidden"
            ):
                with ui.element("div").style(
                    "display:flex;justify-content:center;padding:.625rem 0 .25rem"
                ):
                    ui.element("div").style(
                        "width:36px;height:4px;background:var(--c-border-strong);"
                        "border-radius:var(--r-full)"
                    )
                create_cart_panel(session)

    bar.on("click", lambda: asyncio.ensure_future(_open_sheet()))

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
    ui.download(text.encode("utf-8"), "boodschappenlijst.txt", media_type="text/plain")


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
