"""Reusable substitute-product dialog — used from dishes page and weekmenu cart-add."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable

from nicegui import ui

from pyplus.i18n import t
from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url

if TYPE_CHECKING:
    from plus.models import Product

log = logging.getLogger(__name__)

_REASON_LABELS = {
    "category": "substitute.reason_category",
    "name": "substitute.reason_name",
    "brand": "substitute.reason_brand",
    "bought": "substitute.reason_bought",
}

_DEBOUNCE = 0.3


def show_substitute_dialog(
    session,
    *,
    sku: str,
    product_name: str,
    product_image: str = "",
    categories: list[str] | None = None,
    price: float = 0.0,
    brand: str = "",
    mode: str = "relink",
    on_select: Callable[["Product"], None] | None = None,
) -> None:
    """Open the substitute finder dialog.

    mode="relink"  — updates DishIngredient.sku permanently (dishes page)
    mode="cart"    — calls on_select(product) so the caller can swap for this cart-add
    """
    categories = categories or []
    chosen: list[Product] = []

    with ui.dialog(value=True) as dlg:
        with ui.card().style(
            "min-width:320px;max-width:460px;width:100%;padding:0;overflow:hidden"
        ):
            # ── Header ──────────────────────────────────────────────
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label(t("substitute.dialog_title")).style(
                    "font-size:16px;font-weight:700;color:var(--c-text)"
                )
                ui.button(icon="close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            # ── Original product summary ────────────────────────────
            with ui.element("div").style(
                "display:flex;align-items:center;gap:.625rem;"
                "padding:.75rem 1rem;border-bottom:1px solid var(--c-border);"
                "background:var(--c-surface-2)"
            ):
                if product_image:
                    ui.image(thumbnail_url(product_image, 40)).style(
                        "width:40px;height:40px;border-radius:var(--r-sm);flex-shrink:0"
                    ).props(f'alt="{_alt(product_name)}"')
                with ui.element("div").style("min-width:0;flex:1"):
                    ui.label(product_name).style(
                        "font-size:13px;font-weight:600;color:var(--c-text);"
                        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                    )
                    with ui.element("div").style(
                        "display:flex;align-items:center;gap:.375rem;margin-top:2px"
                    ):
                        if price > 0:
                            ui.label(f"€\xa0{price:.2f}".replace(".", ",")).style(
                                "font-size:12px;color:var(--c-text-3)"
                            )
                        ui.label(t("status.unavailable")).style(
                            "font-size:11px;color:var(--c-danger);font-weight:600"
                        )

            # ── Search bar ──────────────────────────────────────────
            with ui.element("div").style("padding:.625rem 1rem 0"):
                search_input = (
                    ui.input(placeholder=t("substitute.search_placeholder"))
                    .props("outlined dense clearable")
                    .style("width:100%")
                )

            # ── Scrollable results area ─────────────────────────────
            with ui.element("div").style(
                "padding:.5rem 1rem;max-height:50vh;overflow-y:auto;min-height:120px"
            ):
                spinner_row = ui.element("div").style(
                    "display:flex;align-items:center;gap:.5rem;padding:.75rem 0"
                )
                with spinner_row:
                    ui.spinner(size="16px", color="primary")
                    ui.label(t("substitute.loading")).style("font-size:12px;color:var(--c-text-3)")

                @ui.refreshable
                def _results_list(candidates=None, is_search=False) -> None:
                    if candidates is None:
                        return
                    if not candidates:
                        ui.label(t("substitute.no_results")).style(
                            "font-size:13px;color:var(--c-text-3);padding:.5rem 0"
                        )
                        return
                    header = (
                        t("substitute.suggestions_header")
                        if not is_search
                        else f"{len(candidates)} resultaten"
                    )
                    ui.label(header).style(
                        "font-size:11px;font-weight:700;color:var(--c-text-3);"
                        "text-transform:uppercase;letter-spacing:.04em;margin-bottom:.25rem"
                    )
                    for cand in candidates:
                        _render_candidate_row(cand, chosen, dlg, mode, on_select, session, sku)

                _results_list()

            # ── Footer ──────────────────────────────────────────────
            with ui.element("div").style(
                "display:flex;justify-content:flex-end;gap:.5rem;"
                "padding:.75rem 1rem;border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.cancel"), on_click=dlg.close).props("flat rounded no-caps")

    # ── Load suggestions async ──────────────────────────────────────
    async def _load_suggestions() -> None:
        from pyplus.services.substitutes import find_substitutes

        try:
            settings = session.settings
            results = await find_substitutes(
                session.store_number,
                sku,
                product_name=product_name,
                brand=brand,
                categories=categories,
                price=price,
                user_id=session.user_id,
                settings=settings,
            )
            spinner_row.set_visibility(False)
            _results_list.refresh(candidates=results, is_search=False)
        except Exception as exc:
            log.warning("Substitute search failed: %s", exc)
            spinner_row.set_visibility(False)
            _results_list.refresh(candidates=[], is_search=False)

    asyncio.ensure_future(_load_suggestions())

    # ── Manual search handler ───────────────────────────────────────
    _debounce_task: list[asyncio.Task | None] = [None]

    async def _on_search(e) -> None:
        query = (e.value if hasattr(e, "value") else search_input.value) or ""
        query = query.strip()
        if _debounce_task[0] and not _debounce_task[0].done():
            _debounce_task[0].cancel()

        if len(query) < 3:
            spinner_row.set_visibility(True)
            _results_list.refresh(candidates=None)
            await _load_suggestions()
            return

        async def _debounced() -> None:
            await asyncio.sleep(_DEBOUNCE)
            from pyplus.services.search import search_products

            spinner_row.set_visibility(True)
            _results_list.refresh(candidates=None)
            try:
                from pyplus.services.substitutes import SubstituteCandidate

                found = await search_products(
                    session, query, limit=session.settings.sub_max_results
                )
                found = [p for p in found if p.sku != sku and p.is_available]
                candidates = [
                    SubstituteCandidate(product=p, score=0.0, match_reason="name") for p in found
                ]
                spinner_row.set_visibility(False)
                _results_list.refresh(candidates=candidates, is_search=True)
            except Exception as exc:
                log.warning("Manual substitute search failed: %s", exc)
                spinner_row.set_visibility(False)
                _results_list.refresh(candidates=[], is_search=True)

        _debounce_task[0] = asyncio.create_task(_debounced())

    search_input.on("update:model-value", _on_search)


def _render_candidate_row(
    cand, chosen: list, dlg, mode: str, on_select, session, original_sku: str
) -> None:
    product = cand.product
    reason_key = _REASON_LABELS.get(cand.match_reason, "substitute.reason_name")

    with ui.element("div").style(
        "display:flex;align-items:center;gap:.5rem;padding:.375rem 0;"
        "border-bottom:1px solid var(--c-border)"
    ):
        if product.image_url:
            ui.image(thumbnail_url(product.image_url, 36)).style(
                "width:36px;height:36px;border-radius:var(--r-sm);flex-shrink:0"
            ).props(f'alt="{_alt(product.name)}"')
        else:
            ui.element("div").style(
                "width:36px;height:36px;border-radius:var(--r-sm);"
                "background:var(--c-border);flex-shrink:0"
            )

        with ui.element("div").style("min-width:0;flex:1"):
            ui.label(product.name).style(
                "font-size:13px;font-weight:500;color:var(--c-text);"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            )
            with ui.element("div").style(
                "display:flex;align-items:center;gap:.375rem;margin-top:1px"
            ):
                if product.subtitle:
                    ui.label(product.subtitle).style("font-size:11px;color:var(--c-text-3)")
                ui.label(f"€\xa0{product.price:.2f}".replace(".", ",")).style(
                    "font-size:12px;font-weight:600;color:var(--c-text-2)"
                )
            ui.label(t(reason_key)).style("font-size:10px;color:var(--c-text-4);font-style:italic")

        def _pick(p=product) -> None:
            chosen.clear()
            chosen.append(p)
            if mode == "cart" and on_select:
                on_select(p)
                dlg.close()
            elif mode == "relink":
                asyncio.ensure_future(_do_relink(session, original_sku, p, dlg))

        ui.button(t("substitute.select"), on_click=_pick).props(
            "unelevated rounded dense no-caps size=sm color=primary"
        ).style("flex-shrink:0")


async def _do_relink(session, original_sku: str, product, dlg) -> None:
    """Persist the substitute: update IngredientSku + DishIngredient rows."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.services.dishes import cache_ingredient_sku_from_product

    try:
        async with AsyncSessionLocal() as db:
            await cache_ingredient_sku_from_product(db, session.user_id, product)
            await repo.relink_ingredient_sku(db, session.user_id, original_sku, product.sku)
        dlg.close()
        ui.notify(f"{product.name} gekoppeld", type="positive")
    except Exception as exc:
        log.error("Relink failed: %s", exc)
        ui.notify(t("status.error"), type="negative")
