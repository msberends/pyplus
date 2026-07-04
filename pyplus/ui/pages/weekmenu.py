"""Weekmenu page — full-width week-slot view."""

from __future__ import annotations

import logging

from nicegui import app, ui

log = logging.getLogger(__name__)


async def create_weekmenu_page() -> None:
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
        create_nav_rail(active="weekmenu", session=session)

        with ui.element("div").classes("sp-page-content sp-page-lane"):
            try:
                from pyplus.ui.components.meals import create_meals_lane

                await create_meals_lane(session)
            except Exception as exc:
                log.error("Weekmenu lane crashed: %s", exc)
                from pyplus.i18n import t

                with ui.element("div").classes("sp-lane"):
                    with ui.element("div").classes("sp-lane-header"):
                        ui.label(t("lane.meals.title")).classes("sp-lane-title")
                    with ui.element("div").classes("sp-lane-body sp-lane-error"):
                        ui.icon("error_outline", size="24px").style(
                            "color:var(--c-danger);opacity:.6"
                        )
                        ui.label("Er is iets misgegaan. Vernieuw de pagina.").style(
                            "font-size:13px;color:var(--c-text-3)"
                        )
