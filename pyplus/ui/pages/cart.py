"""Winkelwagen page — cart grouped by PLUS category, origin chips per item, product search."""

from __future__ import annotations

import datetime
import logging

from nicegui import app, ui

log = logging.getLogger(__name__)


async def create_cart_page() -> None:
    user_id = app.storage.user.get("user_id")
    from pyplus.session import manager

    session = manager.get(user_id) if user_id else None
    if session is None:
        app.storage.browser["_login_next"] = "/cart"
        ui.navigate.to("/login")
        return

    from pyplus.ui.theme import apply_theme

    apply_theme()

    from pyplus.ui.components.nav import create_nav_rail

    with ui.element("div").classes("sp-cockpit-root"):
        create_nav_rail(active="cart", session=session)

        with ui.element("div").classes("sp-page-content"):
            # Autopilot rollback banner
            await _maybe_show_autopilot_banner(user_id, session)

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
                                ui.icon("sym_r_error", size="24px").style(
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


async def _maybe_show_autopilot_banner(user_id: int, session) -> None:
    has_autopilot = any(it.source and "autopilot:" in it.source for it in session.cart.items)
    if not has_autopilot:
        return

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.i18n import t

    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    async with AsyncSessionLocal() as db:
        plan = await repo.get_autopilot_plan(db, user_id, week_start)

    if plan is None or plan.status != "confirmed" or not plan.cart_snapshot_json:
        return

    import json

    snapshot = json.loads(plan.cart_snapshot_json)

    async def _rollback() -> None:
        for entry in snapshot:
            await session.cart_service.remove(entry["sku"], entry["qty"])
        async with AsyncSessionLocal() as db:
            await repo.update_autopilot_plan_status(db, plan.id, "rolled_back")
        ui.notify(t("autopilot.rollback_confirm", n=len(snapshot)), type="info")
        ui.navigate.to("/cart")

    with ui.element("div").style(
        "display:flex;align-items:center;gap:.5rem;padding:.5rem .75rem;"
        "background:var(--c-accent-tint);border:1px solid var(--c-accent-border);"
        "border-radius:var(--r-lg);margin-bottom:.5rem"
    ):
        ui.icon("sym_r_robot_2", size="18px").style("color:var(--c-accent)")
        ui.label(f"Autopilot heeft {len(snapshot)} producten toegevoegd").style(
            "font-size:12px;color:var(--c-text-2);flex:1"
        )
        ui.button(
            t("autopilot.rollback"),
            icon="sym_r_undo",
            on_click=_rollback,
        ).props("flat color=negative size=sm dense")
