"""
Dishes management page — list view + full editor dialog.

Core requirement from the brief: ingredient→SKU binding is strict, assisted,
visual, and relinkable. Availability is surfaced informally; the cart-add
resolution (substitutions) happens at add-to-cart time in M7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from nicegui import app, ui

from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.i18n import t
from pyplus.session import manager
from pyplus.ui.components.nav import create_nav_rail
from pyplus.ui.theme import apply_theme

log = logging.getLogger(__name__)

_UNITS = ["stuks", "g", "kg", "ml", "l", "tl", "el", "mok", "snufje", "plak", "teen", "takje"]


# ── Page entry ─────────────────────────────────────────────────────────────────


async def create_dishes_page() -> None:
    user_id = app.storage.user.get("user_id")
    session = manager.get(user_id) if user_id else None
    if session is None:
        ui.navigate.to("/login")
        return

    apply_theme()

    with ui.element("div").classes("sp-cockpit-root"):
        create_nav_rail(active="dishes", user_display_name=session.display_name)

        with ui.element("div").style(
            "flex:1;overflow-y:auto;padding:1.5rem;background:var(--c-bg)"
        ):
            # ── Page header ────────────────────────────────────────────
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "margin-bottom:1.25rem"
            ):
                ui.label(t("dishes.title")).style(
                    "font-size:22px;font-weight:700;color:var(--c-text);letter-spacing:-.3px"
                )
                with ui.row().style("gap:.5rem;align-items:center"):
                    show_archived = ui.checkbox("Archief tonen").style("font-size:13px")
                    ui.button(
                        t("dishes.new"),
                        on_click=lambda: _open_editor(user_id, session, None, dish_grid_refresh),
                    ).props("unelevated rounded color=primary no-caps").style(
                        "font-size:13px;font-weight:600"
                    )

            # ── Dish grid ──────────────────────────────────────────────
            @ui.refreshable
            async def dish_grid_refresh() -> None:
                await _render_dish_grid(user_id, session, show_archived.value, dish_grid_refresh)

            await dish_grid_refresh()

            # Re-render when archive toggle changes
            show_archived.on(
                "update:model-value",
                lambda _: dish_grid_refresh.refresh(),
            )


async def _render_dish_grid(user_id, session, include_archived, refresh_fn) -> None:
    async with AsyncSessionLocal() as db:
        dishes = await repo.get_dishes(db, user_id, include_archived=include_archived)

    if not dishes:
        with ui.element("div").style(
            "display:flex;flex-direction:column;align-items:center;padding:4rem 2rem;gap:.75rem"
        ):
            ui.label("🍽️").style("font-size:3rem;opacity:.3")
            ui.label("Nog geen gerechten.").style("font-size:15px;color:var(--c-text-3)")
            ui.button(
                t("dishes.new"),
                on_click=lambda: _open_editor(user_id, session, None, refresh_fn),
            ).props("unelevated rounded color=primary no-caps")
        return

    with ui.element("div").style(
        "display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1rem"
    ):
        for dish in dishes:
            await _render_dish_card(dish, user_id, session, refresh_fn)


async def _render_dish_card(dish, user_id, session, refresh_fn) -> None:
    async with AsyncSessionLocal() as db:
        ingredients = await repo.get_ingredients(db, dish.id)
        avail, unavail, unknown = await repo.get_dish_availability(db, user_id, dish.id)
        discontinued = await repo.get_dish_discontinued_skus(db, session.store_number or 0, dish.id)

    total = len(ingredients)

    with ui.element("div").classes("sp-dish-card").style("opacity:.6" if dish.archived else ""):
        # Ingredient thumbnails (first 4)
        with ui.element("div").style("display:flex;gap:4px;margin-bottom:.625rem;height:40px"):
            async with AsyncSessionLocal() as db:
                for ing in ingredients[:4]:
                    cached = await repo.get_ingredient_sku(db, user_id, ing.sku)
                    img_url = cached.image_url if cached else ""
            for ing in ingredients[:4]:
                async with AsyncSessionLocal() as db:
                    cached = await repo.get_ingredient_sku(db, user_id, ing.sku)
                    img_url = cached.image_url if cached and cached.image_url else ""
                if img_url:
                    ui.image(img_url).style(
                        "width:40px;height:40px;border-radius:var(--r-sm);"
                        "object-fit:contain;background:var(--c-border)"
                    )
                else:
                    ui.element("div").style(
                        "width:40px;height:40px;border-radius:var(--r-sm);"
                        "background:var(--c-border);flex-shrink:0"
                    )
            if total > 4:
                ui.label(f"+{total - 4}").style(
                    "font-size:11px;color:var(--c-text-4);align-self:center;padding-left:2px"
                )

        # Name
        ui.label(dish.name).classes("sp-dish-card-name").style("margin-bottom:.25rem")

        # Planning metadata chips (prep time / meat / vegetables)
        from pyplus.ui.format import dish_meta_chips

        chips = dish_meta_chips(dish)
        if chips:
            with ui.element("div").style(
                "display:flex;flex-wrap:wrap;gap:.25rem;margin-bottom:.5rem"
            ):
                for chip in chips:
                    ui.label(chip).style(
                        "font-size:11px;color:var(--c-text-2);background:var(--c-surface-2);"
                        "border-radius:var(--r-sm);padding:1px 7px"
                    )

        # Ingredient count + availability
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.5rem;margin-bottom:.625rem"
        ):
            ui.label(f"{total} ingrediënt{'en' if total != 1 else ''}").style(
                "font-size:12px;color:var(--c-text-3)"
            )

            if total > 0:
                if discontinued:
                    ui.label(t("dishes.discontinued_count", n=len(discontinued))).classes(
                        "sp-badge sp-badge-unavailable"
                    ).style("font-size:10px").tooltip(t("status.discontinued"))
                elif unavail > 0:
                    ui.label(t("dishes.partial_unavail", n=unavail)).classes(
                        "sp-badge sp-badge-unavailable"
                    ).style("font-size:10px")
                elif unknown == total:
                    pass  # no badge — availability never checked
                else:
                    ui.label(t("dishes.fully_available")).classes(
                        "sp-badge sp-badge-available"
                    ).style("font-size:10px")

        # Action buttons
        with ui.element("div").style("display:flex;gap:.375rem"):
            ui.button(
                t("action.edit"),
                on_click=lambda d=dish: _open_editor(user_id, session, d.id, refresh_fn),
            ).props("flat dense no-caps color=primary").style("font-size:12px")

            ui.button(
                t("dishes.duplicate"),
                on_click=lambda d=dish: _duplicate(user_id, d.id, refresh_fn),
            ).props("flat dense no-caps color=grey").style("font-size:12px")

            label = t("dishes.restore") if dish.archived else t("dishes.archive")
            ui.button(
                label,
                on_click=lambda d=dish: _toggle_archive(user_id, d, refresh_fn),
            ).props("flat dense no-caps color=negative").style("font-size:12px")


# ── CRUD helpers ───────────────────────────────────────────────────────────────


async def _duplicate(user_id: int, dish_id: int, refresh_fn) -> None:
    async with AsyncSessionLocal() as db:
        await repo.duplicate_dish(db, user_id, dish_id)
    ui.notify("Gerecht gedupliceerd", type="positive", timeout=2000)
    await refresh_fn.refresh()


async def _toggle_archive(user_id: int, dish, refresh_fn) -> None:
    async with AsyncSessionLocal() as db:
        await repo.archive_dish(db, user_id, dish.id, not dish.archived)
    action = "hersteld" if dish.archived else "gearchiveerd"
    ui.notify(f"Gerecht {action}", type="info", timeout=2000)
    await refresh_fn.refresh()


# ── Dish editor dialog ─────────────────────────────────────────────────────────


@dataclass
class _IngRow:
    """Mutable state for one ingredient row in the editor."""

    id: int | None  # None for newly added, not yet saved
    dish_id: int | None
    sku: str
    display_name: str
    image_url: str
    amount: float
    amount_unit: str
    pack_size: float | None
    pack_unit: str | None
    optional: bool
    sort_order: int
    flexible: bool = False  # placeholder: product chosen at add-to-cart time
    # Transient — not stored
    discontinued: bool = False  # not in store catalogue (no longer carried)
    relinking: bool = False
    search_query: str = ""
    search_results: list = field(default_factory=list)
    searching: bool = False


async def _open_editor(user_id: int, session, dish_id: int | None, refresh_fn) -> None:
    """Open the dish editor dialog for creating or editing a dish."""
    # Load existing dish
    if dish_id is not None:
        async with AsyncSessionLocal() as db:
            dish = await repo.get_dish(db, user_id, dish_id)
            raw_ings = await repo.get_ingredients(db, dish_id)
        if not dish:
            ui.notify("Gerecht niet gevonden", type="negative")
            return
        name_val = dish.name
        notes_val = dish.prep_notes
        prep_val = dish.prep_minutes
        meat_val = dish.meat_type
        veg_val = dish.veg_count
    else:
        dish = None
        raw_ings = []
        name_val = ""
        notes_val = ""
        prep_val = None
        meat_val = None
        veg_val = None

    # Mutable holder for the optional planning metadata, mutated by the selects below.
    meta = {"prep_minutes": prep_val, "meat_type": meat_val, "veg_count": veg_val}

    # Build mutable ingredient row state
    rows: list[_IngRow] = []
    if raw_ings:
        async with AsyncSessionLocal() as db:
            for ing in sorted(raw_ings, key=lambda x: (x.sort_order, x.id)):
                cached = await repo.get_ingredient_sku(db, user_id, ing.sku)
                rows.append(
                    _IngRow(
                        id=ing.id,
                        dish_id=ing.dish_id,
                        sku=ing.sku,
                        display_name=ing.display_name,
                        image_url=cached.image_url if cached else "",
                        amount=ing.amount,
                        amount_unit=ing.amount_unit,
                        pack_size=ing.pack_size,
                        pack_unit=ing.pack_unit,
                        optional=ing.optional,
                        flexible=ing.flexible,
                        sort_order=ing.sort_order,
                    )
                )
            # Flag ingredients the store catalogue no longer carries.
            store = session.store_number or 0
            if store and await repo.count_product_cache(db, store) > 0:
                present = await repo.get_product_cache_by_skus(
                    db, store, [r.sku for r in rows if r.sku]
                )
                for r in rows:
                    if r.sku and r.sku not in present:
                        r.discontinued = True

    # ── Dialog ────────────────────────────────────────────────────────
    with ui.dialog(value=True).props("persistent").classes("sp-editor-dialog") as dlg:
        with ui.card().style(
            "width:680px;max-width:95vw;max-height:90vh;padding:0;"
            "display:flex;flex-direction:column;overflow:hidden"
        ):
            # Header
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:1rem 1.25rem .875rem;border-bottom:1px solid var(--c-border);flex-shrink:0"
            ):
                title = t("dishes.edit") if dish else t("dishes.new")
                ui.label(title).style("font-size:17px;font-weight:700;color:var(--c-text)")
                with ui.row().style("gap:.5rem"):
                    ui.button(
                        t("action.cancel"),
                        on_click=dlg.close,
                    ).props("flat rounded no-caps color=grey")

                    async def _save() -> None:
                        await _save_dish(
                            user_id,
                            session,
                            dish_id,
                            name_input.value,
                            notes_input.value,
                            meta,
                            rows,
                            dlg,
                            refresh_fn,
                        )

                    ui.button(
                        t("action.save"),
                        on_click=_save,
                    ).props("unelevated rounded no-caps color=primary")

            # Scrollable body
            with ui.element("div").style("flex:1;overflow-y:auto;padding:1.25rem"):
                # Name
                name_input = (
                    ui.input(label=t("dishes.name_label"), value=name_val)
                    .props("outlined")
                    .style("width:100%;margin-bottom:.875rem")
                )

                # Prep notes
                notes_input = (
                    ui.textarea(
                        label=t("dishes.prep_notes_label"),
                        value=notes_val,
                    )
                    .props("outlined autogrow")
                    .style("width:100%;margin-bottom:1rem")
                )
                ui.label(t("dishes.prep_notes_hint")).style(
                    "font-size:11px;color:var(--c-text-4);margin-top:-.625rem;margin-bottom:1rem"
                )

                # Planning metadata (prep time / meat / vegetables) — all optional.
                _render_meta_fields(meta)

                # Ingredients header
                with ui.element("div").style(
                    "display:flex;align-items:center;justify-content:space-between;"
                    "margin-bottom:.625rem"
                ):
                    ui.label(t("dishes.ingredients")).style(
                        "font-size:14px;font-weight:600;color:var(--c-text)"
                    )

                # Ingredient rows
                @ui.refreshable
                def _ingredient_list() -> None:
                    if not rows:
                        ui.label("Nog geen ingrediënten.").style(
                            "font-size:13px;color:var(--c-text-4);padding:.5rem 0"
                        )
                        return
                    for idx, row in enumerate(rows):
                        _render_ingredient_row(row, idx, rows, session, user_id, _ingredient_list)

                _ingredient_list()

                # Add ingredient buttons
                with ui.element("div").style(
                    "display:flex;gap:.5rem;align-items:center;margin-top:.625rem"
                ):
                    ui.button(
                        f"+ {t('dishes.add_ingredient')}",
                        on_click=lambda: _add_new_row(rows, _ingredient_list),
                    ).props("flat no-caps color=primary").style("font-size:13px")
                    ui.button(
                        f"+ {t('dishes.add_flexible')}",
                        on_click=lambda: _add_flexible_row(rows, _ingredient_list),
                    ).props("flat no-caps color=secondary").style("font-size:13px").tooltip(
                        t("dishes.flexible_hint")
                    )


def _render_meta_fields(meta: dict) -> None:
    """Render the optional prep-time / meat / vegetable selects in one row."""
    from pyplus.db.models import MEAT_TYPES, PREP_TIME_BUCKETS
    from pyplus.ui.format import meat_emoji, meat_label, prep_time_label, veg_emoji

    unset = t("dishes.meta_unset")

    prep_opts = {None: unset} | {m: prep_time_label(m) for m in PREP_TIME_BUCKETS}
    meat_opts = {None: unset} | {m: f"{meat_emoji(m)} {meat_label(m)}".strip() for m in MEAT_TYPES}
    veg_opts = {None: unset} | {n: (veg_emoji(n) or "➖") for n in (0, 1, 2, 3)}

    with ui.element("div").style(
        "display:grid;grid-template-columns:repeat(3,1fr);gap:.625rem;margin-bottom:1rem"
    ):
        prep_sel = (
            ui.select(prep_opts, value=meta["prep_minutes"], label=t("dishes.prep_time_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        prep_sel.on("update:model-value", lambda e: meta.update(prep_minutes=e.value))

        meat_sel = (
            ui.select(meat_opts, value=meta["meat_type"], label=t("dishes.meat_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        meat_sel.on("update:model-value", lambda e: meta.update(meat_type=e.value))

        veg_sel = (
            ui.select(veg_opts, value=meta["veg_count"], label=t("dishes.veg_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        veg_sel.on("update:model-value", lambda e: meta.update(veg_count=e.value))


def _add_new_row(rows: list[_IngRow], refresh_fn) -> None:
    rows.append(
        _IngRow(
            id=None,
            dish_id=None,
            sku="",
            display_name="",
            image_url="",
            amount=1.0,
            amount_unit="stuks",
            pack_size=None,
            pack_unit=None,
            optional=False,
            sort_order=len(rows),
            relinking=True,  # start in search mode
        )
    )
    refresh_fn.refresh()


def _add_flexible_row(rows: list[_IngRow], refresh_fn) -> None:
    rows.append(
        _IngRow(
            id=None,
            dish_id=None,
            sku="",
            display_name="",
            image_url="",
            amount=1.0,
            amount_unit="stuks",
            pack_size=None,
            pack_unit=None,
            optional=False,
            sort_order=len(rows),
            flexible=True,
        )
    )
    refresh_fn.refresh()


def _render_flexible_row(row: _IngRow, idx: int, rows: list, refresh_fn) -> None:
    """A placeholder ingredient: free-text label now, product chosen at cart-add."""
    with ui.element("div").style(
        "display:flex;align-items:center;gap:.5rem;"
        "padding:.625rem .75rem;border:1px dashed var(--c-brand);"
        "border-radius:var(--r-md);margin-bottom:.5rem;background:var(--c-brand-tint)"
    ):
        ui.icon("tune", size="20px").style("color:var(--c-brand-dark);flex-shrink:0")

        with ui.element("div").style(
            "flex:1;min-width:0;display:flex;flex-direction:column;gap:2px"
        ):
            ui.label(t("dishes.flexible_badge")).style(
                "font-size:9px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;"
                "color:var(--c-brand-dark)"
            )
            label_input = (
                ui.input(placeholder=t("dishes.flexible_placeholder"), value=row.display_name)
                .props("dense borderless")
                .style("width:100%;font-size:13px")
            )
            label_input.on(
                "blur", lambda e, r=row: setattr(r, "display_name", label_input.value or "")
            )

        # Amount + unit (the placeholder still carries a quantity/unit)
        amount_input = (
            ui.input(value=_fmt_amount(row.amount))
            .props("outlined dense")
            .style("width:56px;flex-shrink:0")
        )

        def _amount_change(e, r=row):
            try:
                r.amount = float((e.value or "").replace(",", "."))
            except (ValueError, AttributeError):
                pass

        amount_input.on("blur", _amount_change)
        unit_select = (
            ui.select(_UNITS, value=row.amount_unit if row.amount_unit in _UNITS else _UNITS[0])
            .props("outlined dense options-dense")
            .style("width:72px;flex-shrink:0")
        )
        unit_select.on("update:model-value", lambda e, r=row: setattr(r, "amount_unit", e.value))

        with ui.element("div").style("display:flex;gap:2px;flex-shrink:0"):
            if idx > 0:
                ui.button(
                    icon="arrow_upward", on_click=lambda i=idx: _move_row(rows, i, -1, refresh_fn)
                ).props("flat dense size=sm")
            if idx < len(rows) - 1:
                ui.button(
                    icon="arrow_downward", on_click=lambda i=idx: _move_row(rows, i, +1, refresh_fn)
                ).props("flat dense size=sm")
            ui.button(icon="delete", on_click=lambda i=idx: _remove_row(rows, i, refresh_fn)).props(
                "flat dense size=sm color=negative"
            )


def _fmt_amount(amount: float) -> str:
    return str(int(amount) if amount == int(amount) else amount)


def _render_ingredient_row(
    row: _IngRow, idx: int, rows: list, session, user_id: int, refresh_fn
) -> None:
    if row.flexible:
        _render_flexible_row(row, idx, rows, refresh_fn)
        return
    with ui.element("div").style(
        "display:flex;flex-direction:column;gap:.5rem;"
        "padding:.625rem .75rem;border:1px solid var(--c-border);"
        "border-radius:var(--r-md);margin-bottom:.5rem;"
        "background:var(--c-surface)"
    ):
        # Top row: [image] [name/search] [amount] [unit] [optional] [up/down/delete]
        with ui.element("div").style("display:flex;align-items:center;gap:.5rem"):
            # Product image / placeholder
            if row.image_url and not row.relinking:
                ui.image(row.image_url).style(
                    "width:40px;height:40px;border-radius:var(--r-sm);"
                    "object-fit:contain;background:var(--c-border);flex-shrink:0"
                )
            else:
                ui.element("div").style(
                    "width:40px;height:40px;border-radius:var(--r-sm);"
                    "background:var(--c-border);flex-shrink:0"
                )

            # Name display / relink search
            if row.relinking or not row.sku:
                # Search field
                with ui.element("div").style("flex:1;position:relative"):

                    async def _on_search(e, r=row):
                        r.search_query = e.value if hasattr(e, "value") else ""
                        if len(r.search_query) >= 2:
                            r.searching = True
                            refresh_fn.refresh()
                            try:
                                from pyplus.services.search import search_products

                                r.search_results = await search_products(session, r.search_query)
                            except Exception:
                                r.search_results = []
                            r.searching = False
                        else:
                            r.search_results = []
                        refresh_fn.refresh()

                    search_field = (
                        ui.input(
                            placeholder=t("dishes.ingredient_search"),
                            value=row.search_query,
                        )
                        .props("outlined dense clearable")
                        .style("width:100%")
                    )
                    search_field.on("update:model-value", _on_search)

                    # Search results dropdown
                    if row.searching:
                        with ui.element("div").style(
                            "position:absolute;top:42px;left:0;right:0;z-index:999;"
                            "background:white;border:1px solid var(--c-border);"
                            "border-radius:var(--r-md);box-shadow:var(--shadow-md);max-height:200px;overflow-y:auto"
                        ):
                            ui.label("Zoeken…").style(
                                "padding:.5rem .75rem;font-size:12px;color:var(--c-text-3)"
                            )

                    elif row.search_results:
                        with ui.element("div").style(
                            "position:absolute;top:42px;left:0;right:0;z-index:999;"
                            "background:white;border:1px solid var(--c-border);"
                            "border-radius:var(--r-md);box-shadow:var(--shadow-md);max-height:200px;overflow-y:auto"
                        ):
                            for prod in row.search_results[:8]:

                                async def _pick(p=prod, r=row):
                                    r.sku = p.sku
                                    r.display_name = p.name
                                    r.image_url = p.image_url
                                    r.relinking = False
                                    r.discontinued = False
                                    r.search_query = ""
                                    r.search_results = []
                                    # Infer unit from subtitle
                                    from pyplus.services.dishes import _parse_pack_from_subtitle

                                    pack_size, pack_unit = _parse_pack_from_subtitle(p.subtitle)
                                    if pack_unit and r.amount_unit == "stuks":
                                        r.amount_unit = pack_unit
                                    r.pack_size = pack_size
                                    r.pack_unit = pack_unit
                                    # Cache to ingredient_skus
                                    from pyplus.services.dishes import (
                                        cache_ingredient_sku_from_product,
                                    )

                                    async with AsyncSessionLocal() as db:
                                        await cache_ingredient_sku_from_product(db, user_id, p)
                                    refresh_fn.refresh()

                                avail_color = (
                                    "var(--c-brand-dark)"
                                    if prod.is_available
                                    else "var(--c-danger)"
                                )
                                with (
                                    ui.element("div")
                                    .style(
                                        "display:flex;align-items:center;gap:.5rem;"
                                        "padding:.375rem .75rem;cursor:pointer;"
                                        "transition:background .1s"
                                    )
                                    .on("click", _pick)
                                    .on(
                                        "mouseenter",
                                        lambda el: el.style("background:var(--c-surface-2)"),
                                    )
                                    .on(
                                        "mouseleave",
                                        lambda el: el.style("background:none"),
                                    )
                                ):
                                    if prod.image_url:
                                        ui.image(prod.image_url).style(
                                            "width:32px;height:32px;object-fit:contain;"
                                            "border-radius:4px;background:var(--c-border);flex-shrink:0"
                                        )
                                    with ui.element("div").style("flex:1;min-width:0"):
                                        ui.label(prod.name).style(
                                            "font-size:13px;font-weight:500;overflow:hidden;"
                                            "text-overflow:ellipsis;white-space:nowrap"
                                        )
                                        if prod.subtitle:
                                            ui.label(prod.subtitle).style(
                                                "font-size:11px;color:var(--c-text-3)"
                                            )
                                    ui.element("div").style(
                                        f"width:6px;height:6px;border-radius:50%;"
                                        f"background:{avail_color};flex-shrink:0"
                                    )
            else:
                # Pinned product display
                with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
                    ui.label(row.display_name).style(
                        "font-size:13px;font-weight:500;overflow:hidden;"
                        "text-overflow:ellipsis;white-space:nowrap"
                    )
                    if row.discontinued:
                        ui.label(t("status.discontinued")).classes(
                            "sp-badge sp-badge-unavailable"
                        ).style("font-size:10px;display:inline-block").tooltip(
                            "Niet in catalogus — kies een ander product"
                        )
                    elif row.pack_size and row.pack_unit:
                        ui.label(f"Per {row.pack_size:g} {row.pack_unit}").style(
                            "font-size:11px;color:var(--c-text-3)"
                        )

            # Amount input
            amount_str = [str(int(row.amount) if row.amount == int(row.amount) else row.amount)]
            amount_input = (
                ui.input(value=amount_str[0])
                .props("outlined dense")
                .style("width:60px;flex-shrink:0")
            )

            def _amount_change(e, r=row, a=amount_str):
                try:
                    r.amount = float(e.value.replace(",", "."))
                except (ValueError, AttributeError):
                    pass

            amount_input.on("blur", _amount_change)
            amount_input.on("keydown.enter", _amount_change)

            # Unit select
            unit_select = (
                ui.select(
                    _UNITS,
                    value=row.amount_unit if row.amount_unit in _UNITS else _UNITS[0],
                )
                .props("outlined dense options-dense")
                .style("width:72px;flex-shrink:0")
            )
            unit_select.on(
                "update:model-value",
                lambda e, r=row: setattr(r, "amount_unit", e.value),
            )

            # Optional toggle
            opt_check = ui.checkbox("", value=row.optional).props("dense").style("flex-shrink:0")
            opt_check.tooltip("Optioneel")
            opt_check.on(
                "update:model-value",
                lambda e, r=row: setattr(r, "optional", bool(e.value)),
            )

            # Control buttons
            with ui.element("div").style("display:flex;gap:2px;flex-shrink:0"):
                # Move up
                if idx > 0:
                    ui.button(
                        icon="arrow_upward",
                        on_click=lambda i=idx: _move_row(rows, i, -1, refresh_fn),
                    ).props("flat dense size=sm")
                else:
                    ui.element("div").style("width:28px")

                # Move down
                if idx < len(rows) - 1:
                    ui.button(
                        icon="arrow_downward",
                        on_click=lambda i=idx: _move_row(rows, i, +1, refresh_fn),
                    ).props("flat dense size=sm")
                else:
                    ui.element("div").style("width:28px")

                # Relink
                if row.sku and not row.relinking:
                    ui.button(
                        icon="edit",
                        on_click=lambda r=row: (
                            setattr(r, "relinking", True),
                            setattr(r, "search_results", []),
                            refresh_fn.refresh(),
                        ),
                    ).props("flat dense size=sm color=primary").tooltip(t("dishes.relink"))

                # Delete
                ui.button(
                    icon="delete",
                    on_click=lambda i=idx: _remove_row(rows, i, refresh_fn),
                ).props("flat dense size=sm color=negative")


def _move_row(rows: list[_IngRow], idx: int, direction: int, refresh_fn) -> None:
    new_idx = idx + direction
    if 0 <= new_idx < len(rows):
        rows[idx], rows[new_idx] = rows[new_idx], rows[idx]
        for i, r in enumerate(rows):
            r.sort_order = i
        refresh_fn.refresh()


def _remove_row(rows: list[_IngRow], idx: int, refresh_fn) -> None:
    rows.pop(idx)
    refresh_fn.refresh()


async def _save_dish(
    user_id: int,
    session,
    dish_id: int | None,
    name: str,
    notes: str,
    meta: dict,
    rows: list[_IngRow],
    dlg,
    refresh_fn,
) -> None:
    name = name.strip()
    if not name:
        ui.notify("Voer een naam in", type="negative")
        return

    async with AsyncSessionLocal() as db:
        if dish_id is None:
            dish = await repo.create_dish(
                db,
                user_id,
                name=name,
                prep_notes=notes,
                prep_minutes=meta.get("prep_minutes"),
                meat_type=meta.get("meat_type"),
                veg_count=meta.get("veg_count"),
            )
        else:
            dish = await repo.update_dish(
                db,
                user_id,
                dish_id,
                name=name,
                prep_notes=notes,
                prep_minutes=meta.get("prep_minutes"),
                meat_type=meta.get("meat_type"),
                veg_count=meta.get("veg_count"),
            )

        if not dish:
            ui.notify(t("status.error"), type="negative")
            return

        # Sync ingredients: delete all then re-insert in order
        existing = await repo.get_ingredients(db, dish.id)
        for ing in existing:
            await db.delete(ing)
        await db.flush()

        for i, row in enumerate(rows):
            # Keep product-bound rows (have a sku) and flexible rows (have a label).
            if row.flexible:
                if not (row.display_name or "").strip():
                    continue  # empty flexible placeholder — drop it
            elif not row.sku:
                continue  # unbound product row — drop it
            await repo.add_ingredient(
                db,
                dish.id,
                sku="" if row.flexible else row.sku,
                display_name=row.display_name,
                amount=row.amount,
                amount_unit=row.amount_unit,
                pack_size=row.pack_size,
                pack_unit=row.pack_unit,
                optional=row.optional,
                flexible=row.flexible,
                sort_order=i,
            )

        await db.commit()

    ui.notify("Gerecht opgeslagen", type="positive", timeout=2000)
    dlg.close()
    await refresh_fn.refresh()
