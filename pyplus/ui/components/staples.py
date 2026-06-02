"""
Lane ② — Vaste boodschappen: the user's curated staple products.

Each row shows a cart-synced stepper.  The "Voeg alles toe" button adds every
product not yet in the cart at its default_qty in one shot.
"""

from __future__ import annotations

import asyncio
import logging

from nicegui import ui

from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import FixedProduct, IngredientSku
from pyplus.i18n import t

log = logging.getLogger(__name__)


async def create_staples_lane(session) -> None:
    """Render Lane ② — Vaste boodschappen."""
    cart_service = getattr(session, "cart_service", None)

    products: list = []
    sku_cache: dict = {}
    load_error = ""
    try:
        async with AsyncSessionLocal() as db:
            products = await repo.get_fixed_products(db, session.user_id)
            sku_cache = await repo.get_ingredient_skus_by_skus(
                db, session.user_id, [p.sku for p in products if p.sku]
            )
    except Exception as exc:
        log.error("Staples lane load failed: %s", exc)
        load_error = "Vaste boodschappen konden niet worden geladen."

    # Load replenishment artifact if ML is enabled
    replenish_scores: dict = {}
    try:
        from pyplus.db import repo as _repo
        from pyplus.db.engine import AsyncSessionLocal as _ASSL
        from pyplus.ml.interface import UserSettings

        async with _ASSL() as _db:
            _sj = await _repo.get_user_settings_json(_db, session.user_id)
        _settings = UserSettings.model_validate_json(_sj) if _sj else UserSettings()
        if _settings.ml_enabled and _settings.ml_replenish:
            from pyplus.ml.artifacts import load_artifact

            _art = await load_artifact(session.user_id, "replenishment")
            if _art:
                replenish_scores = _art
    except Exception:
        pass

    with ui.element("div").classes("sp-lane"):
        # ── Header ────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between"
            ):
                ui.label(t("lane.staples.title")).classes("sp-lane-title")
                if products:
                    ui.button(
                        "Voeg alles toe",
                        icon="add_shopping_cart",
                        on_click=lambda: asyncio.ensure_future(
                            _add_all(products, sku_cache, session, cart_service)
                        ),
                    ).props("flat dense no-caps color=primary size=sm").style(
                        "font-size:12px;font-weight:600"
                    )

        # ── Body ──────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-body sp-staples-body"):
            if load_error:
                with ui.element("div").classes("sp-lane-error"):
                    ui.icon("error_outline", size="24px").style("color:var(--c-danger);opacity:.6")
                    ui.label(load_error).style("font-size:13px;color:var(--c-text-3)")
                return

            if not products:
                with ui.element("div").classes("sp-lane-placeholder"):
                    ui.label("📋").classes("sp-lane-placeholder-icon")
                    ui.label("Nog geen vaste boodschappen.").style(
                        "font-size:13px;color:var(--c-text-3);margin-top:.25rem"
                    )
            else:
                # Sort: due items first when replenishment is active
                if replenish_scores:
                    from pyplus.ml.replenish import sort_fixed_products_by_due

                    sorted_products = [
                        p
                        for sku in sort_fixed_products_by_due(
                            [p.sku for p in products], replenish_scores
                        )
                        for p in products
                        if p.sku == sku
                    ]
                else:
                    sorted_products = products

                @ui.refreshable
                def _list() -> None:
                    for fp in sorted_products:
                        rs = replenish_scores.get(fp.sku)
                        _render_row(fp, sku_cache.get(fp.sku), session, cart_service, rs)

                _list()
                session.add_cart_listener(lambda: _list.refresh())


def _render_row(
    fp: FixedProduct,
    cached: IngredientSku | None,
    session,
    cart_service,
    replenish_score=None,
) -> None:
    cart_qty = next((it.quantity for it in session.cart.items if it.sku == fp.sku), 0)
    is_syncing = fp.sku in session.syncing_skus

    # Resolved display info (from sku_cache if available)
    name = cached.name if cached else fp.display_name
    subtitle = cached.subtitle if cached else ""
    price = cached.last_price or 0.0 if cached else 0.0
    image = cached.image_url if cached else ""

    is_due = replenish_score is not None and replenish_score.is_due
    row_style = "background:var(--c-brand-tint);border-radius:var(--r-sm)" if is_due else ""

    with ui.element("div").classes("sp-staples-item").style(row_style):
        # Availability dot
        if cached and cached.last_seen_available is not None:
            dot_cls = "sp-avail-dot-ok" if cached.last_seen_available else "sp-avail-dot-no"
            ui.element("div").classes(f"sp-avail-dot {dot_cls}")
        else:
            ui.element("div").classes("sp-avail-dot")

        # Name + subtitle + replenishment reason
        with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
            ui.label(name).style(
                "font-size:13px;font-weight:500;color:var(--c-text);"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3"
            )
            reason_line = subtitle
            if replenish_score and replenish_score.reason:
                reason_line = replenish_score.reason
            if reason_line:
                ui.label(reason_line).style("font-size:11px;color:var(--c-text-3);line-height:1.2")

        # Price
        if price > 0:
            ui.label(f"€ {price:.2f}".replace(".", ",")).style(
                "font-size:12px;color:var(--c-text-3);flex-shrink:0;margin-right:.25rem"
            )

        # Stepper
        _render_stepper(fp, cart_qty, is_syncing, name, subtitle, price, image, cart_service)


def _render_stepper(fp, cart_qty, syncing, name, subtitle, price, image, cart_service) -> None:
    if syncing:
        with ui.element("div").style(
            "width:32px;height:32px;display:flex;align-items:center;justify-content:center"
        ):
            ui.spinner(size="14px", color="primary")
        return

    if cart_qty == 0:
        default_qty = fp.default_qty or 1
        with (
            ui.element("div")
            .classes("sp-search-add-btn")
            .on(
                "click",
                lambda _, f=fp, n=name, s=subtitle, p=price, img=image, q=default_qty: (
                    asyncio.ensure_future(
                        cart_service.add(
                            f.sku,
                            q,
                            product_name=n,
                            product_unit=s,
                            product_price=p,
                            product_image=img,
                        )
                    )
                    if cart_service
                    else None
                ),
            )
        ):
            ui.label("+").style(
                "font-size:18px;font-weight:700;color:var(--c-brand-dark);line-height:1;pointer-events:none"
            )
    else:
        with ui.element("div").classes("sp-qty"):
            with (
                ui.element("div")
                .classes("sp-qty-btn")
                .on(
                    "click",
                    lambda _, f=fp: (
                        asyncio.ensure_future(cart_service.remove(f.sku)) if cart_service else None
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
                    lambda _, f=fp, n=name, s=subtitle, p=price, img=image: (
                        asyncio.ensure_future(
                            cart_service.add(
                                f.sku,
                                product_name=n,
                                product_unit=s,
                                product_price=p,
                                product_image=img,
                            )
                        )
                        if cart_service
                        else None
                    ),
                )
            ):
                ui.label("+").style(
                    "font-size:15px;font-weight:700;line-height:1;pointer-events:none"
                )


async def _add_all(
    products: list[FixedProduct],
    sku_cache: dict[str, IngredientSku],
    session,
    cart_service,
) -> None:
    """Add all products not already in the cart at their default_qty."""
    if not cart_service:
        return

    cart_skus = {it.sku for it in session.cart.items}

    for fp in products:
        if not fp.sku or fp.sku in cart_skus:
            continue
        cached = sku_cache.get(fp.sku)
        name = cached.name if cached else fp.display_name
        subtitle = cached.subtitle if cached else ""
        price = cached.last_price or 0.0 if cached else 0.0
        image = cached.image_url if cached else ""
        await cart_service.add(
            fp.sku,
            fp.default_qty or 1,
            product_name=name,
            product_unit=subtitle,
            product_price=price,
            product_image=image,
        )
