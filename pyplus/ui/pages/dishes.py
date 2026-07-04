"""
Dishes management page — list view + full editor dialog.

Core requirement from the brief: ingredient→SKU binding is strict, assisted,
visual, and relinkable. Availability is surfaced informally; the cart-add
resolution (substitutions) happens at add-to-cart time in M7.
"""

from __future__ import annotations

import asyncio
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


@dataclass
class _DishCardData:
    """Pre-fetched data for rendering a dish card without DB calls."""

    ingredients: list = field(default_factory=list)
    img_urls: list = field(default_factory=list)
    avail: int = 0
    unavail: int = 0
    unknown: int = 0
    discontinued: list = field(default_factory=list)


# ── Filters ───────────────────────────────────────────────────────────────────


@dataclass
class _DishFilters:
    search: str = ""
    meat_types: set = field(default_factory=set)
    starch_types: set = field(default_factory=set)
    cooking_methods: set = field(default_factory=set)
    prep_max: int | None = None
    is_cold: bool | None = None
    availability: str | None = None  # None=all, "ok", "issue"


def _apply_filters(dishes: list, filters: _DishFilters) -> list:
    import json as _json

    result = []
    search = filters.search.lower().strip()
    for d in dishes:
        if search and search not in d.name.lower():
            continue
        if filters.meat_types and (d.meat_type or "") not in filters.meat_types:
            continue
        if filters.starch_types and (d.starch_type or "") not in filters.starch_types:
            continue
        if filters.cooking_methods:
            try:
                cm = set(_json.loads(d.cooking_methods or "[]"))
            except Exception:
                cm = set()
            if not (filters.cooking_methods & cm):
                continue
        if filters.prep_max is not None and d.prep_minutes is not None:
            if d.prep_minutes > filters.prep_max:
                continue
        if filters.is_cold is True and not d.is_cold:
            continue
        result.append(d)
    return result


def _render_filters(filters: _DishFilters, refresh_fn) -> None:
    from pyplus.db.models import COOKING_METHODS, MEAT_TYPES, PREP_TIME_BUCKETS, STARCH_TYPES
    from pyplus.ui.format import (
        cooking_emoji,
        cooking_label,
        meat_emoji,
        meat_label,
        prep_time_label,
        starch_emoji,
        starch_label,
    )

    with ui.element("div").style(
        "display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;"
        "margin-bottom:1.25rem;padding:.75rem 1rem;"
        "background:var(--c-surface);border:1px solid var(--c-border);"
        "border-radius:var(--r-xl)"
    ):
        # Search
        search_input = (
            ui.input(placeholder="Zoek gerecht…", value=filters.search)
            .props("outlined dense clearable")
            .style("width:180px;flex-shrink:0")
        )

        def _on_search(e):
            val = e.value if hasattr(e, "value") else search_input.value
            filters.search = val or ""
            refresh_fn()

        search_input.on("update:model-value", _on_search)
        search_input.on("clear", lambda: (_on_search(type("E", (), {"value": ""})()),))

        # Separator
        ui.element("div").style("width:1px;height:24px;background:var(--c-border);flex-shrink:0")

        # Meat type chips
        for mt in MEAT_TYPES:
            lbl = f"{meat_emoji(mt)} {meat_label(mt)}"
            is_on = mt in filters.meat_types
            chip = (
                ui.chip(lbl, selectable=True, selected=is_on)
                .props(f"{'color=primary' if is_on else 'outline'} size=sm clickable")
                .style("font-size:11px")
            )

            def _toggle_meat(e, m=mt):
                if m in filters.meat_types:
                    filters.meat_types.discard(m)
                else:
                    filters.meat_types.add(m)
                refresh_fn()

            chip.on("update:selected", _toggle_meat)

        ui.element("div").style("width:1px;height:24px;background:var(--c-border);flex-shrink:0")

        # Starch chips
        for st in STARCH_TYPES:
            lbl = f"{starch_emoji(st)} {starch_label(st)}"
            is_on = st in filters.starch_types
            chip = (
                ui.chip(lbl, selectable=True, selected=is_on)
                .props(f"{'color=primary' if is_on else 'outline'} size=sm clickable")
                .style("font-size:11px")
            )

            def _toggle_starch(e, s=st):
                if s in filters.starch_types:
                    filters.starch_types.discard(s)
                else:
                    filters.starch_types.add(s)
                refresh_fn()

            chip.on("update:selected", _toggle_starch)

        ui.element("div").style("width:1px;height:24px;background:var(--c-border);flex-shrink:0")

        # Cooking method chips
        for cm in COOKING_METHODS:
            lbl = f"{cooking_emoji(cm)} {cooking_label(cm)}"
            is_on = cm in filters.cooking_methods
            chip = (
                ui.chip(lbl, selectable=True, selected=is_on)
                .props(f"{'color=primary' if is_on else 'outline'} size=sm clickable")
                .style("font-size:11px")
            )

            def _toggle_cm(e, c=cm):
                if c in filters.cooking_methods:
                    filters.cooking_methods.discard(c)
                else:
                    filters.cooking_methods.add(c)
                refresh_fn()

            chip.on("update:selected", _toggle_cm)

        ui.element("div").style("width:1px;height:24px;background:var(--c-border);flex-shrink:0")

        # Prep time select
        prep_opts = {None: "Bereidingstijd", **{m: prep_time_label(m) for m in PREP_TIME_BUCKETS}}
        prep_sel = (
            ui.select(prep_opts, value=filters.prep_max)
            .props("outlined dense options-dense")
            .style("width:130px;flex-shrink:0")
        )

        def _on_prep(e):
            filters.prep_max = prep_sel.value
            refresh_fn()

        prep_sel.on("update:model-value", _on_prep)

        # Cold toggle
        cold_chip = (
            ui.chip("❄️ Koud", selectable=True, selected=filters.is_cold is True)
            .props(f"{'color=info' if filters.is_cold else 'outline'} size=sm clickable")
            .style("font-size:11px")
        )

        def _toggle_cold(e):
            filters.is_cold = True if filters.is_cold is None else None
            refresh_fn()

        cold_chip.on("update:selected", _toggle_cold)


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

        with ui.element("div").classes("sp-page-content"):
            # ── Page header ────────────────────────────────────────────
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem"
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

            # ── Filters ───────────────────────────────────────────────
            filters = _DishFilters()
            _render_filters(filters, lambda: dish_grid_refresh.refresh())

            # ── Dish grid ─────────────────────────────────────────────
            @ui.refreshable
            async def dish_grid_refresh() -> None:
                await _render_dish_grid(
                    user_id, session, show_archived.value, filters, dish_grid_refresh
                )

            await dish_grid_refresh()

            show_archived.on(
                "update:model-value",
                lambda _: dish_grid_refresh.refresh(),
            )


async def _render_dish_grid(user_id, session, include_archived, filters, refresh_fn) -> None:
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

    filtered = _apply_filters(dishes, filters)
    if not filtered and dishes:
        ui.label("Geen gerechten gevonden met deze filters.").style(
            "font-size:14px;color:var(--c-text-3);padding:2rem 0"
        )
        return

    # Pre-fetch all ingredient images + availability in one batch
    dish_data: dict[int, _DishCardData] = {}
    async with AsyncSessionLocal() as db:
        for dish in filtered:
            ings = await repo.get_ingredients(db, dish.id)
            avail, unavail, unknown = await repo.get_dish_availability(db, user_id, dish.id)
            disc = await repo.get_dish_discontinued_skus(db, session.store_number or 0, dish.id)
            img_urls = []
            for ing in ings:
                cached = await repo.get_ingredient_sku(db, user_id, ing.sku)
                img_urls.append(cached.image_url if cached and cached.image_url else "")
            dish_data[dish.id] = _DishCardData(
                ingredients=ings,
                img_urls=img_urls,
                avail=avail,
                unavail=unavail,
                unknown=unknown,
                discontinued=disc,
            )

    with ui.element("div").style(
        "display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:1.25rem"
    ):
        for dish in filtered:
            _render_dish_card(dish, dish_data.get(dish.id), session, refresh_fn)


def _render_dish_card(dish, data: _DishCardData | None, session, refresh_fn) -> None:
    from pyplus.ui.format import (
        cooking_emoji,
        meat_emoji,
        meat_label,
        parse_cooking_methods,
        prep_time_label,
        starch_emoji,
        starch_label,
        veg_emoji,
    )

    user_id = session.user_id
    d = data or _DishCardData()
    total = len(d.ingredients)
    show_meta = session.settings.show_dish_metadata

    with (
        ui.element("div")
        .classes("sp-dish-card")
        .style("opacity:.6" if dish.archived else "")
        .on("click", lambda di=dish: _open_editor(user_id, session, di.id, refresh_fn))
    ):
        # ── Top zone: thumbnails + badges (flex-grows to align titles) ────
        with ui.element("div").style("flex:1"):
            with ui.element("div").style(
                "display:flex;align-items:flex-start;justify-content:space-between"
            ):
                with ui.element("div").style(
                    "display:flex;gap:5px;align-items:center;flex-wrap:wrap"
                ):
                    for url in d.img_urls:
                        if url:
                            ui.image(url).style(
                                "width:38px;height:38px;border-radius:var(--r-sm);"
                                "object-fit:contain;background:var(--c-surface);"
                                "border:1px solid var(--c-border)"
                            )
                        else:
                            ui.element("div").style(
                                "width:38px;height:38px;border-radius:var(--r-sm);"
                                "background:var(--c-surface);border:1px solid var(--c-border)"
                            )

                if show_meta:
                    with ui.element("div").style(
                        "display:flex;gap:5px;align-items:center;flex-shrink:0;margin-left:.5rem"
                    ):
                        st = getattr(dish, "starch_type", None)
                        if st and starch_emoji(st):
                            ui.label(f"{starch_emoji(st)} {starch_label(st)}").style(
                                "font-size:10px;color:var(--c-text-2);"
                                "background:#f5f0e8;border-radius:var(--r-full);"
                                "padding:2px 9px;font-weight:500;white-space:nowrap"
                            )
                        if getattr(dish, "is_cold", False):
                            ui.label("❄️").style(
                                "font-size:14px;background:#e0f2fe;"
                                "border-radius:var(--r-full);"
                                "padding:2px 7px;line-height:1.3"
                            ).tooltip("Koud gerecht")

        # ── Bottom zone: title + meta + count + actions (pinned) ──────────
        ui.label(dish.name).classes("sp-dish-card-name").style(
            "margin-bottom:.25rem;margin-top:.75rem"
        )

        if show_meta:
            parts: list[str] = []
            me = meat_emoji(dish.meat_type)
            if me:
                parts.append(f"{me} {meat_label(dish.meat_type)}")
            for m in parse_cooking_methods(dish):
                ce = cooking_emoji(m)
                if ce:
                    parts.append(ce)
            prep = prep_time_label(dish.prep_minutes)
            if prep:
                parts.append(f"⏱ {prep}")
            ve = veg_emoji(dish.veg_count)
            if ve:
                parts.append(ve)
            if parts:
                ui.label(" · ".join(parts)).style(
                    "font-size:11px;color:var(--c-text-3);margin-bottom:.375rem"
                )

        with ui.element("div").style(
            "display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem"
        ):
            ui.label(f"{total} ingrediënt{'en' if total != 1 else ''}").style(
                "font-size:11px;color:var(--c-text-4)"
            )
            if total > 0:
                if d.discontinued:
                    ui.label(t("dishes.discontinued_count", n=len(d.discontinued))).classes(
                        "sp-badge sp-badge-unavailable"
                    ).style("font-size:10px").tooltip(t("status.discontinued"))
                elif d.unavail > 0:
                    ui.label(t("dishes.partial_unavail", n=d.unavail)).classes(
                        "sp-badge sp-badge-unavailable"
                    ).style("font-size:10px")
                elif d.unknown == total:
                    pass
                else:
                    ui.label(t("dishes.fully_available")).classes(
                        "sp-badge sp-badge-available"
                    ).style("font-size:10px")

        with ui.element("div").style(
            "display:flex;gap:.375rem;padding-top:.375rem;border-top:1px solid var(--c-border)"
        ):
            ui.button(
                t("action.edit"),
                on_click=lambda di=dish: _open_editor(user_id, session, di.id, refresh_fn),
            ).props("flat dense no-caps color=primary").style("font-size:11px")
            ui.button(
                t("dishes.duplicate"),
                on_click=lambda di=dish: _duplicate(user_id, di.id, refresh_fn),
            ).props("flat dense no-caps color=grey").style("font-size:11px")
            label = t("dishes.restore") if dish.archived else t("dishes.archive")
            ui.button(
                label,
                on_click=lambda di=dish: _toggle_archive(user_id, di, refresh_fn),
            ).props("flat dense no-caps color=negative").style("font-size:11px")


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
    subtitle: str = ""  # product pack subtitle, e.g. "Per 400 ml" (display only)
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
        starch_val = dish.starch_type
        veg_val = dish.veg_count
        import json as _json

        try:
            cooking_val = _json.loads(dish.cooking_methods or "[]")
        except Exception:
            cooking_val = []
        cold_val = dish.is_cold
    else:
        dish = None
        raw_ings = []
        name_val = ""
        notes_val = ""
        prep_val = None
        meat_val = None
        starch_val = None
        veg_val = None
        cooking_val = []
        cold_val = False

    meta = {
        "prep_minutes": prep_val,
        "meat_type": meat_val,
        "starch_type": starch_val,
        "veg_count": veg_val,
        "cooking_methods": list(cooking_val),
        "is_cold": cold_val,
    }

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
                        subtitle=cached.subtitle if cached else "",
                    )
                )
            # Flag ingredients missing or unavailable in the store catalogue.
            store = session.store_number or 0
            if store and await repo.count_product_cache(db, store) > 0:
                present = await repo.get_product_cache_by_skus(
                    db, store, [r.sku for r in rows if r.sku]
                )
                for r in rows:
                    if r.sku and (r.sku not in present or not present[r.sku].is_available):
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

            # Pinned footer — add-ingredient actions stay reachable on phones
            # even when the ingredient list scrolls past the viewport.
            with ui.element("div").style(
                "display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;flex-shrink:0;"
                "padding:.75rem 1.25rem;border-top:1px solid var(--c-border);background:var(--c-surface)"
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


def _infer_starch_type(name: str, ingredients: list[_IngRow]) -> str | None:
    """Guess starch type from the dish name or ingredient names."""
    name_lower = name.lower()
    ing_names = " ".join(r.display_name.lower() for r in ingredients if r.display_name)
    combined = f"{name_lower} {ing_names}"

    if any(w in combined for w in ("aardappel", "aardappelen", "puree", "frites", "krieltje")):
        return "aardappels"
    if any(
        w in combined
        for w in (
            "pasta",
            "spaghetti",
            "penne",
            "macaroni",
            "fusilli",
            "tagliatelle",
            "lasagne",
            "linguine",
            "farfalle",
            "rigatoni",
            "orzo",
        )
    ):
        return "pasta"
    if any(w in combined for w in ("rijst", "nasi", "bami")):
        return "rijst"
    if any(w in combined for w in ("noedel", "noodle", "mie", "ramen", "udon", "soba")):
        return "noedels"
    if any(
        w in combined
        for w in (
            "deeg",
            "bladerdeeg",
            "filodeeg",
            "pizza",
            "brood",
            "wrap",
            "tortilla",
            "taco",
            "naan",
            "pita",
        )
    ):
        return "deeg"
    return None


def _render_meta_fields(meta: dict) -> None:
    """Render the optional prep-time / meat / starch / cooking / cold / vegetable fields."""
    from pyplus.db.models import COOKING_METHODS, MEAT_TYPES, PREP_TIME_BUCKETS, STARCH_TYPES
    from pyplus.ui.format import (
        cooking_emoji,
        cooking_label,
        meat_emoji,
        meat_label,
        prep_time_label,
        starch_emoji,
        starch_label,
        veg_emoji,
    )

    unset = t("dishes.meta_unset")

    prep_opts = {None: unset} | {m: prep_time_label(m) for m in PREP_TIME_BUCKETS}
    meat_opts = {None: unset} | {m: f"{meat_emoji(m)} {meat_label(m)}".strip() for m in MEAT_TYPES}
    starch_opts = {None: unset} | {
        s: f"{starch_emoji(s)} {starch_label(s)}".strip() for s in STARCH_TYPES
    }
    veg_opts = {None: unset} | {n: (veg_emoji(n) or "➖") for n in (0, 1, 2, 3)}

    with ui.element("div").style(
        "display:grid;grid-template-columns:repeat(2,1fr);gap:.625rem;margin-bottom:1rem"
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

        starch_sel = (
            ui.select(starch_opts, value=meta["starch_type"], label=t("dishes.starch_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        starch_sel.on("update:model-value", lambda e: meta.update(starch_type=e.value))

        veg_sel = (
            ui.select(veg_opts, value=meta["veg_count"], label=t("dishes.veg_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        veg_sel.on("update:model-value", lambda e: meta.update(veg_count=e.value))

    # Cooking methods — checkboxes (not combined, each separate)
    ui.label(t("dishes.cooking_methods_label")).style(
        "font-size:12px;font-weight:600;color:var(--c-text-2);margin-bottom:.25rem"
    )
    with ui.element("div").style("display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:.75rem"):
        for method in COOKING_METHODS:
            checked = method in meta.get("cooking_methods", [])
            cb = ui.checkbox(
                f"{cooking_emoji(method)} {cooking_label(method)}",
                value=checked,
            ).props("dense")

            def _on_cooking(e, m=method, c=cb) -> None:
                methods = meta.get("cooking_methods", [])
                if c.value and m not in methods:
                    methods.append(m)
                elif not c.value and m in methods:
                    methods.remove(m)
                meta["cooking_methods"] = methods

            cb.on("update:model-value", _on_cooking)

    # Is cold checkbox
    cold_cb = (
        ui.checkbox(f"❄️ {t('dishes.is_cold_label')}", value=meta.get("is_cold", False))
        .props("dense")
        .style("margin-bottom:1rem")
    )
    cold_cb.on(
        "update:model-value",
        lambda e: meta.update(is_cold=bool(cold_cb.value)),
    )


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


async def _open_substitute_for_row(row: _IngRow, session, user_id: int, refresh_fn) -> None:
    """Open the substitute dialog for a discontinued ingredient row."""
    from pyplus.services.categories import parse_categories
    from pyplus.ui.components.substitutes import show_substitute_dialog

    cats: list[str] = []
    price = 0.0
    brand = ""

    async with AsyncSessionLocal() as db:
        pc = await repo.get_product_cache_by_skus(db, session.store_number or 0, [row.sku])
        cached_sku = await repo.get_ingredient_sku(db, user_id, row.sku)
    if row.sku in pc:
        cats = parse_categories(pc[row.sku].categories_json)
        price = pc[row.sku].price or 0.0
        brand = pc[row.sku].brand or ""
    elif cached_sku:
        price = cached_sku.last_price or 0.0

    def _on_pick(product):
        from pyplus.services.dishes import _parse_pack_from_subtitle

        row.sku = product.sku
        row.display_name = product.name
        row.image_url = product.image_url
        row.subtitle = product.subtitle or ""
        row.discontinued = False
        pack_size, pack_unit = _parse_pack_from_subtitle(product.subtitle)
        if pack_unit and row.amount_unit == "stuks":
            row.amount_unit = pack_unit
        row.pack_size = pack_size
        row.pack_unit = pack_unit

        async def _cache():
            from pyplus.services.dishes import cache_ingredient_sku_from_product

            async with AsyncSessionLocal() as db:
                await cache_ingredient_sku_from_product(db, user_id, product)

        asyncio.ensure_future(_cache())
        refresh_fn.refresh()

    show_substitute_dialog(
        session,
        sku=row.sku,
        product_name=row.display_name,
        product_image=row.image_url,
        categories=cats,
        price=price,
        brand=brand,
        mode="cart",
        on_select=_on_pick,
    )


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
        # Top row: [image] [name/search] [amount] [unit] [up/down/relink/delete]
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
                # Search field. The input is rendered once and kept alive; only
                # the results box below it is cleared/redrawn per keystroke, so
                # the field never loses focus while typing.
                with ui.element("div").style("flex:1;position:relative"):
                    search_field = (
                        ui.input(
                            placeholder=t("dishes.ingredient_search"),
                            value=row.search_query,
                        )
                        .props("outlined dense clearable autofocus")
                        .style("width:100%")
                    )
                    results_box = ui.element("div").style(
                        "position:absolute;top:42px;left:0;right:0;z-index:999"
                    )

                    def _draw_results(r=row, box=results_box):
                        box.clear()
                        with box:
                            if r.searching:
                                with ui.element("div").style(
                                    "background:white;border:1px solid var(--c-border);"
                                    "border-radius:var(--r-md);box-shadow:var(--shadow-md)"
                                ):
                                    ui.label("Zoeken…").style(
                                        "padding:.5rem .75rem;font-size:12px;color:var(--c-text-3)"
                                    )
                            elif r.search_results:
                                with ui.element("div").style(
                                    "background:white;border:1px solid var(--c-border);"
                                    "border-radius:var(--r-md);box-shadow:var(--shadow-md);"
                                    "max-height:200px;overflow-y:auto"
                                ):
                                    for prod in r.search_results[:8]:
                                        _render_search_result(prod, r, session, user_id, refresh_fn)

                    async def _on_search(e, r=row, field=search_field):
                        # update:model-value events don't carry `.value` in this
                        # NiceGUI version — read the synced field value instead.
                        r.search_query = (e.value if hasattr(e, "value") else field.value) or ""
                        if len(r.search_query.strip()) >= 2:
                            r.searching = True
                            _draw_results()
                            try:
                                from pyplus.services.search import search_products

                                r.search_results = await search_products(session, r.search_query)
                            except Exception:
                                r.search_results = []
                            r.searching = False
                        else:
                            r.search_results = []
                        _draw_results()

                    search_field.on("update:model-value", _on_search)
                    _draw_results()
            else:
                # Pinned product display
                with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
                    ui.label(row.display_name).style(
                        "font-size:13px;font-weight:500;overflow:hidden;"
                        "text-overflow:ellipsis;white-space:nowrap"
                    )
                    # Product pack unit, e.g. "Per 400 ml" — shown for every
                    # SKU-bound ingredient, like the staples and cart lanes do.
                    unit_text = row.subtitle or (
                        f"Per {row.pack_size:g} {row.pack_unit}"
                        if row.pack_size and row.pack_unit
                        else ""
                    )
                    if unit_text:
                        ui.label(unit_text).style(
                            "font-size:11px;color:var(--c-text-3);overflow:hidden;"
                            "text-overflow:ellipsis;white-space:nowrap"
                        )
                    if row.discontinued:
                        with ui.element("div").style(
                            "display:flex;align-items:center;gap:.375rem;margin-top:1px"
                        ):
                            ui.label(t("status.discontinued")).classes(
                                "sp-badge sp-badge-unavailable"
                            ).style("font-size:10px;display:inline-block").tooltip(
                                "Nu niet verkrijgbaar — kan later terugkomen"
                            )

                            async def _open_sub(r=row):
                                await _open_substitute_for_row(r, session, user_id, refresh_fn)

                            ui.button(
                                t("substitute.replace_btn"),
                                icon="find_replace",
                                on_click=_open_sub,
                            ).props("flat dense no-caps size=sm color=primary")

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

            # Unit — static. It is fixed by the linked product (its pack), so it
            # is shown read-only rather than as an editable select.
            ui.label(row.amount_unit or "").style(
                "font-size:12px;color:var(--c-text-3);flex-shrink:0;min-width:34px;text-align:left"
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

        # Second line: a clearly-labelled optional toggle (the previous bare
        # checkbox was easy to miss).
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.375rem;padding-left:48px"
        ):
            opt_check = ui.checkbox(t("dishes.optional"), value=row.optional).props("dense")
            opt_check.tooltip(t("dishes.optional_hint"))
            opt_check.on(
                "update:model-value",
                lambda e, r=row: setattr(r, "optional", bool(e.value)),
            )


def _render_search_result(prod, row: _IngRow, session, user_id: int, refresh_fn) -> None:
    """One row in the ingredient-search dropdown; clicking it links the SKU."""

    async def _pick(p=prod, r=row):
        r.sku = p.sku
        r.display_name = p.name
        r.image_url = p.image_url
        r.subtitle = p.subtitle or ""
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
        from pyplus.services.dishes import cache_ingredient_sku_from_product

        async with AsyncSessionLocal() as db:
            await cache_ingredient_sku_from_product(db, user_id, p)
        refresh_fn.refresh()

    avail_color = "var(--c-brand-dark)" if prod.is_available else "var(--c-danger)"
    with (
        ui.element("div")
        .style(
            "display:flex;align-items:center;gap:.5rem;"
            "padding:.375rem .75rem;cursor:pointer;transition:background .1s"
        )
        .on("click", _pick)
        .on("mouseenter", lambda el: el.style("background:var(--c-surface-2)"))
        .on("mouseleave", lambda el: el.style("background:none"))
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
                ui.label(prod.subtitle).style("font-size:11px;color:var(--c-text-3)")
        ui.element("div").style(
            f"width:6px;height:6px;border-radius:50%;background:{avail_color};flex-shrink:0"
        )


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

    import json as _json

    cooking_json = _json.dumps(meta.get("cooking_methods", []))

    # Auto-infer starch if not set by user
    if not meta.get("starch_type"):
        inferred = _infer_starch_type(name, rows)
        if inferred:
            meta["starch_type"] = inferred

    async with AsyncSessionLocal() as db:
        if dish_id is None:
            dish = await repo.create_dish(
                db,
                user_id,
                name=name,
                prep_notes=notes,
                prep_minutes=meta.get("prep_minutes"),
                meat_type=meta.get("meat_type"),
                starch_type=meta.get("starch_type"),
                cooking_methods=cooking_json,
                is_cold=bool(meta.get("is_cold", False)),
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
                starch_type=meta.get("starch_type"),
                cooking_methods=cooking_json,
                is_cold=bool(meta.get("is_cold", False)),
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
