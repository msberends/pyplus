"""Cockpit — the single-surface command center. Lanes filled out in M4-M8."""

from __future__ import annotations

import logging

from nicegui import app, ui

from pyplus.i18n import t
from pyplus.session import manager
from pyplus.ui.components.cart import create_cart_panel, create_mobile_cart_bar
from pyplus.ui.components.deals import create_deals_lane
from pyplus.ui.components.meals import create_meals_lane
from pyplus.ui.components.nav import create_nav_rail
from pyplus.ui.components.search import create_search_lane
from pyplus.ui.components.staples import create_staples_lane

log = logging.getLogger(__name__)


def _lane_error_fallback(title: str) -> None:
    """Render a minimal error lane when a component raises unexpectedly."""
    with ui.element("div").classes("sp-lane"):
        with ui.element("div").classes("sp-lane-header"):
            ui.label(title).classes("sp-lane-title")
        with ui.element("div").classes("sp-lane-body"):
            with ui.element("div").classes("sp-lane-error"):
                ui.icon("error_outline", size="24px").style("color:var(--c-danger);opacity:.6")
                ui.label("Er is iets misgegaan. Vernieuw de pagina.").style(
                    "font-size:13px;color:var(--c-text-3)"
                )


async def create_cockpit_page() -> None:
    """
    Render the cockpit. Redirects to /login if no active session.
    Must be called from within a NiceGUI async page handler.
    """
    user_id = app.storage.user.get("user_id")
    session = manager.get(user_id) if user_id else None

    if session is None:
        ui.navigate.to("/login")
        return

    from pyplus.ui.theme import apply_theme

    apply_theme()

    with ui.element("div").classes("sp-cockpit-root"):
        # ── Left nav rail ──────────────────────────────────────────────
        create_nav_rail(active="cockpit", user_display_name=session.display_name)

        # ── Main stage: left col (meals+deals) + middle col (staples+search) ──
        with ui.element("div").classes("sp-cockpit-stage"):
            with ui.element("div").classes("sp-cockpit-left-col"):
                try:
                    await create_meals_lane(session)
                except Exception as exc:
                    log.error("Meals lane crashed: %s", exc)
                    _lane_error_fallback(t("lane.meals.title"))

                try:
                    create_deals_lane(session)
                except Exception as exc:
                    log.error("Deals lane crashed: %s", exc)
                    _lane_error_fallback(t("lane.deals.title"))

            with ui.element("div").classes("sp-cockpit-mid-col"):
                try:
                    await create_staples_lane(session)
                except Exception as exc:
                    log.error("Staples lane crashed: %s", exc)
                    _lane_error_fallback(t("lane.staples.title"))

                try:
                    create_search_lane(session)
                except Exception as exc:
                    log.error("Search lane crashed: %s", exc)
                    _lane_error_fallback(t("lane.search.title"))

        # ── Right cart column (desktop) ────────────────────────────────
        with ui.element("div").classes("sp-cockpit-cart-col"):
            create_cart_panel(session)

    # ── Mobile bottom bar (CSS-hidden on desktop) ──────────────────────
    create_mobile_cart_bar(session)
