"""Vaste boodschappen page — full-width staples view."""

from __future__ import annotations

import logging

from nicegui import app, ui

log = logging.getLogger(__name__)


async def create_staples_page() -> None:
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
        create_nav_rail(active="staples", session=session)

        with ui.element("div").classes("sp-page-content sp-page-lane"):
            try:
                from pyplus.ui.components.staples import create_staples_lane

                await create_staples_lane(session)
            except Exception as exc:
                log.error("Staples lane crashed: %s", exc)
                from pyplus.i18n import t

                with ui.element("div").classes("sp-lane"):
                    with ui.element("div").classes("sp-lane-header"):
                        ui.label(t("lane.staples.title")).classes("sp-lane-title")
                    with ui.element("div").classes("sp-lane-body sp-lane-error"):
                        ui.icon("sym_r_error", size="24px").style(
                            "color:var(--c-danger);opacity:.6"
                        )
                        ui.label("Er is iets misgegaan. Vernieuw de pagina.").style(
                            "font-size:13px;color:var(--c-text-3)"
                        )
