"""Left nav rail component (desktop) / bottom nav (mobile)."""

from __future__ import annotations

from nicegui import ui

from pyplus.i18n import t

_NAV_ITEMS = [
    ("sym_r_calendar_month", "/weekmenu", t("nav.weekmenu"), t("nav.short.weekmenu")),
    ("sym_r_sell", "/promos", t("nav.promos"), t("nav.short.promos")),
    ("sym_r_shopping_basket", "/staples", t("nav.staples"), t("nav.short.staples")),
    ("sym_r_shopping_cart", "/cart", t("nav.cart"), t("nav.short.cart")),
    ("sym_r_robot_2", "/autopilot", t("nav.autopilot"), t("nav.short.autopilot")),
    ("sym_r_skillet", "/dishes", t("nav.dishes"), t("nav.short.dishes")),
    ("sym_r_settings", "/settings", t("nav.settings"), t("nav.short.settings")),
]


def create_nav_rail(active: str = "weekmenu", user_display_name: str = "", session=None) -> None:
    """Render the left navigation rail."""
    with ui.element("div").classes("sp-nav-rail"):
        # Logo mark
        with (
            ui.element("div")
            .classes("sp-nav-logo")
            .style("display:flex;align-items:center;justify-content:center;cursor:pointer")
            .on("click", lambda: ui.navigate.to("/weekmenu"))
        ):
            ui.icon("sym_r_storefront", size="20px").style("color:white")

        # Nav buttons
        cart_badge = None
        for icon, path, label, short_label in _NAV_ITEMS:
            page_slug = path.lstrip("/")
            is_active = active == page_slug
            cls = "sp-nav-btn"
            if page_slug == "autopilot":
                cls += " sp-nav-btn--autopilot"
            if is_active:
                cls += " active"
            classes = cls
            with (
                ui.element("a")
                .props(f'href="{path}" title="{short_label.replace(chr(10), " ")}"')
                .classes(classes)
                .style("position:relative")
            ):
                ui.icon(icon, size="22px")
                ui.label(short_label).classes("sp-nav-label")
                if path == "/cart" and session is not None:
                    cart_badge = (
                        ui.badge("0", color="primary")
                        .props("floating")
                        .style("font-size:10px;min-width:18px;height:18px;top:2px;right:0px")
                    )
                    cart_badge.set_visibility(session.cart.total_items > 0)
                    cart_badge.set_text(str(session.cart.total_items))

        if cart_badge is not None and session is not None:
            _badge = cart_badge

            def _update_nav_badge() -> None:
                n = session.cart.total_items
                _badge.set_text(str(n))
                _badge.set_visibility(n > 0)

            session.add_cart_listener(_update_nav_badge)

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
            ui.element("div")
            .classes("sp-nav-btn sp-nav-logout")
            .on("click", _logout)
            .props('title="Uitloggen"')
        ):
            ui.icon("sym_r_logout", size="22px")
