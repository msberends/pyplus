"""Winkelwagen page — cart grouped by PLUS category, origin chips per item, product search."""

from __future__ import annotations

import logging

from nicegui import app, ui

log = logging.getLogger(__name__)


async def create_cart_page() -> None:
    user_id = app.storage.user.get("user_id")
    from pyplus.session import manager

    session = manager.get(user_id) if user_id else None
    if session is None:
        ui.navigate.to("/login")
        return

    from pyplus.ui.theme import apply_theme

    apply_theme()

    from pyplus.ui.components.nav import create_nav_rail

    with ui.element("div").classes("sp-cockpit-root"):
        create_nav_rail(active="cart", session=session)

        with ui.element("div").classes("sp-page-content"):
            with ui.element("div").classes("sp-cart-two-col"):
                # Left: cart panel (PLUS category grouping, origin chips per row)
                with ui.element("div").classes("sp-cart-two-col__main"):
                    try:
                        from pyplus.ui.components.cart import create_cart_panel

                        create_cart_panel(session)
                    except Exception as exc:
                        log.error("Cart panel crashed: %s", exc)
                        from pyplus.i18n import t

                        with ui.element("div").classes("sp-lane"):
                            with ui.element("div").classes("sp-lane-header"):
                                ui.label(t("cart.title")).classes("sp-lane-title")
                            with ui.element("div").classes("sp-lane-body sp-lane-error"):
                                ui.icon("error_outline", size="24px").style(
                                    "color:var(--c-danger);opacity:.6"
                                )
                                ui.label("Er is iets misgegaan. Vernieuw de pagina.").style(
                                    "font-size:13px;color:var(--c-text-3)"
                                )

                # Right: search panel
                with ui.element("div").classes("sp-cart-two-col__search"):
                    try:
                        from pyplus.ui.components.search import create_search_lane

                        create_search_lane(session)
                    except Exception as exc:
                        log.error("Search lane crashed: %s", exc)
