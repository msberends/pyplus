"""Left nav rail component (desktop) / bottom nav (mobile)."""

from __future__ import annotations

from nicegui import ui

from pyplus.i18n import t

_NAV_ITEMS = [
    ("home", "/cockpit", t("nav.cockpit")),
    ("restaurant", "/dishes", t("nav.dishes")),
    ("settings", "/settings", t("nav.settings")),
]


def create_nav_rail(active: str = "cockpit", user_display_name: str = "") -> None:
    """Render the left navigation rail."""
    with ui.element("div").classes("sp-nav-rail"):
        # Logo mark
        with (
            ui.element("div")
            .classes("sp-nav-logo")
            .style("display:flex;align-items:center;justify-content:center;cursor:pointer")
            .on("click", lambda: ui.navigate.to("/cockpit"))
        ):
            ui.label("SP").style("font-size:12px;font-weight:800;color:white;letter-spacing:-0.5px")

        # Nav buttons
        for icon, path, label in _NAV_ITEMS:
            page_slug = path.lstrip("/")
            is_active = active == page_slug
            classes = "sp-nav-btn" + (" active" if is_active else "")
            with ui.element("a").props(f'href="{path}" title="{label}"').classes(classes):
                ui.icon(icon, size="22px")

        # Spacer pushes logout to the bottom
        ui.element("div").classes("sp-nav-spacer")

        # Logout
        async def _logout() -> None:
            from nicegui import app

            user_id = app.storage.user.get("user_id")
            if user_id:
                from pyplus.session import manager

                await manager.close(user_id)
                app.storage.user.clear()
            ui.navigate.to("/login")

        with (
            ui.element("div").classes("sp-nav-btn").on("click", _logout).props('title="Uitloggen"')
        ):
            ui.icon("logout", size="22px")
