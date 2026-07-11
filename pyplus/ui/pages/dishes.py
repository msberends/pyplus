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
    avail: int = 0
    unavail: int = 0
    unknown: int = 0
    discontinued: list = field(default_factory=list)
    total_price: float = 0.0


@dataclass
class _PageState:
    """All page data, fetched once and filtered in-memory."""

    dishes: list = field(default_factory=list)
    dish_data: dict = field(default_factory=dict)  # dish_id -> _DishCardData
    loaded: bool = False


# ── Filters ───────────────────────────────────────────────────────────────────


@dataclass
class _DishFilters:
    search: str = ""
    meat_types: set = field(default_factory=set)
    starch_types: set = field(default_factory=set)
    cooking_methods: set = field(default_factory=set)
    prep_max: int | None = None
    is_cold: bool | None = None
    is_unhealthy: bool | None = None


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
        if filters.is_unhealthy is True and not d.is_unhealthy:
            continue
        result.append(d)
    return result


def _active_filter_count(filters: _DishFilters) -> int:
    return (
        len(filters.meat_types)
        + len(filters.starch_types)
        + len(filters.cooking_methods)
        + (1 if filters.prep_max is not None else 0)
        + (1 if filters.is_cold else 0)
        + (1 if filters.is_unhealthy else 0)
    )


def _render_filter_chips(filters: _DishFilters, refresh_fn) -> None:
    """Shared chip rendering used by both desktop and mobile filter sections."""
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

    prep_opts = {None: "Bereiding", **{m: prep_time_label(m) for m in PREP_TIME_BUCKETS}}
    prep_sel = (
        ui.select(prep_opts, value=filters.prep_max)
        .props("outlined dense options-dense")
        .style("width:130px;flex-shrink:0")
    )

    def _on_prep(e):
        filters.prep_max = prep_sel.value
        refresh_fn()

    prep_sel.on("update:model-value", _on_prep)

    cold_chip = (
        ui.chip("❄️ Koud", selectable=True, selected=filters.is_cold is True)
        .props(f"{'color=info' if filters.is_cold else 'outline'} size=sm clickable")
        .style("font-size:11px")
    )

    def _toggle_cold(e):
        filters.is_cold = True if filters.is_cold is None else None
        refresh_fn()

    cold_chip.on("update:selected", _toggle_cold)

    unhealthy_chip = (
        ui.chip("🍔 Ongezond", selectable=True, selected=filters.is_unhealthy is True)
        .props(f"{'color=warning' if filters.is_unhealthy else 'outline'} size=sm clickable")
        .style("font-size:11px")
    )

    def _toggle_unhealthy(e):
        filters.is_unhealthy = True if filters.is_unhealthy is None else None
        refresh_fn()

    unhealthy_chip.on("update:selected", _toggle_unhealthy)


def _render_filters(filters: _DishFilters, refresh_fn) -> None:
    # Desktop filter bar
    with (
        ui.element("div")
        .classes("sp-filters-desktop")
        .style(
            "display:flex;flex-wrap:wrap;align-items:center;gap:.375rem;"
            "margin-bottom:1.25rem;padding:.75rem 1rem;"
            "background:var(--c-surface);border:1px solid var(--c-border);"
            "border-radius:var(--r-xl)"
        )
    ):
        search_input = (
            ui.input(placeholder="Zoek gerecht…", value=filters.search)
            .props("outlined dense clearable")
            .style("width:180px;flex-shrink:0")
        )

        def _on_search_desktop(e):
            val = e.value if hasattr(e, "value") else search_input.value
            filters.search = val or ""
            refresh_fn()

        search_input.on("update:model-value", _on_search_desktop)
        search_input.on("clear", lambda: (_on_search_desktop(type("E", (), {"value": ""})()),))

        _render_filter_chips(filters, refresh_fn)

    # Mobile filter bar
    with (
        ui.element("div")
        .classes("sp-filters-mobile")
        .style("display:none;flex-direction:column;gap:.5rem;margin-bottom:1rem")
    ):
        with ui.element("div").style("display:flex;gap:.5rem;align-items:center"):
            mobile_search = (
                ui.input(placeholder="Zoek gerecht…", value=filters.search)
                .props("outlined dense clearable")
                .style("flex:1")
            )

            def _on_search_mobile(e):
                val = e.value if hasattr(e, "value") else mobile_search.value
                filters.search = val or ""
                refresh_fn()

            mobile_search.on("update:model-value", _on_search_mobile)
            mobile_search.on("clear", lambda: (_on_search_mobile(type("E", (), {"value": ""})()),))

            @ui.refreshable
            def _filter_badge():
                count = _active_filter_count(filters)
                label = f"Filters ({count})" if count else "Filters"
                return label

            filter_btn = (
                ui.button(
                    "Filters",
                    icon="sym_r_tune",
                )
                .props("flat dense no-caps")
                .style("font-size:12px;flex-shrink:0")
            )

        with (
            ui.expansion(value=False)
            .classes("sp-mobile-filter-expand")
            .style(
                "background:var(--c-surface);border:1px solid var(--c-border);"
                "border-radius:var(--r-lg)"
            )
            .props("dense") as expansion
        ):
            with ui.element("div").style("display:flex;flex-wrap:wrap;gap:.375rem;padding:.5rem"):
                _render_filter_chips(filters, refresh_fn)

        filter_btn.on("click", lambda: expansion.set_value(not expansion.value))


# ── Data loading ──────────────────────────────────────────────────────────────


async def _load_page_data(state: _PageState, user_id: int, session, include_archived: bool) -> None:
    """Fetch all dish data in ~4 queries total."""
    async with AsyncSessionLocal() as db:
        state.dishes = await repo.get_dishes(db, user_id, include_archived=include_archived)

        all_ings = await repo.get_all_dish_ingredients_for_user(
            db, user_id, include_archived=include_archived
        )

        all_skus: set[str] = set()
        for ings in all_ings.values():
            for ing in ings:
                if ing.sku:
                    all_skus.add(ing.sku)

        sku_cache = await repo.get_ingredient_skus_by_skus(db, user_id, list(all_skus))

        store = session.store_number or 0
        product_cache: dict = {}
        has_catalogue = False
        if store:
            has_catalogue = await repo.count_product_cache(db, store) > 0
            if has_catalogue:
                product_cache = await repo.get_product_cache_by_skus(db, store, list(all_skus))

    dish_data: dict[int, _DishCardData] = {}
    for dish in state.dishes:
        ings = all_ings.get(dish.id, [])
        non_optional = [i for i in ings if not i.optional]

        avail = unavail = unknown = 0
        for ing in non_optional:
            row = sku_cache.get(ing.sku)
            if row is None or row.last_seen_available is None:
                unknown += 1
            elif row.last_seen_available:
                avail += 1
            else:
                unavail += 1

        discontinued: list[str] = []
        if has_catalogue:
            for ing in non_optional:
                if ing.sku and (
                    ing.sku not in product_cache or not product_cache[ing.sku].is_available
                ):
                    discontinued.append(ing.sku)

        total_price = 0.0
        for ing in non_optional:
            cached_sku = sku_cache.get(ing.sku)
            if cached_sku and cached_sku.last_price:
                total_price += cached_sku.last_price

        dish_data[dish.id] = _DishCardData(
            ingredients=ings,
            avail=avail,
            unavail=unavail,
            unknown=unknown,
            discontinued=discontinued,
            total_price=total_price,
        )

    state.dish_data = dish_data
    state.loaded = True


# ── Page entry ─────────────────────────────────────────────────────────────────


async def create_dishes_page() -> None:
    user_id = app.storage.user.get("user_id")
    session = manager.get(user_id) if user_id else None
    if session is None:
        app.storage.browser["_login_next"] = "/dishes"
        ui.navigate.to("/login")
        return

    apply_theme()

    state = _PageState()
    filters = _DishFilters()

    with ui.element("div").classes("sp-cockpit-root"):
        create_nav_rail(active="dishes", user_display_name=session.display_name)

        with ui.element("div").classes("sp-page-content"):
            # Page header
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "margin-bottom:1rem;flex-wrap:wrap;gap:.5rem"
            ):
                ui.label(t("dishes.title")).style(
                    "font-size:22px;font-weight:700;color:var(--c-text);letter-spacing:-.3px"
                )
                with ui.row().style("gap:.5rem;align-items:center"):
                    show_archived = ui.checkbox("Archief tonen").style("font-size:13px")
                    ui.button(
                        t("dishes.new"),
                        on_click=lambda: _open_editor(user_id, session, None, _reload_and_refresh),
                    ).props("unelevated rounded color=primary no-caps").style(
                        "font-size:13px;font-weight:600;height:44px;border-radius:var(--r-md)"
                    )

            _render_filters(filters, lambda: dish_grid_refresh.refresh())

            @ui.refreshable
            def dish_grid_refresh() -> None:
                _render_dish_grid_sync(state, filters, session, _reload_and_refresh)

            async def _reload_and_refresh():
                await _load_page_data(state, user_id, session, show_archived.value)
                dish_grid_refresh.refresh()

            await _load_page_data(state, user_id, session, show_archived.value)
            dish_grid_refresh()

            show_archived.on(
                "update:model-value",
                lambda _: asyncio.ensure_future(_reload_and_refresh()),
            )


def _render_dish_grid_sync(state: _PageState, filters, session, reload_fn) -> None:
    if not state.dishes:
        with ui.element("div").style(
            "display:flex;flex-direction:column;align-items:center;padding:4rem 2rem;gap:.75rem"
        ):
            ui.label("🍽️").style("font-size:3rem;opacity:.3")
            ui.label("Nog geen gerechten.").style("font-size:15px;color:var(--c-text-3)")
            ui.button(
                t("dishes.new"),
                on_click=lambda: _open_editor(session.user_id, session, None, reload_fn),
            ).props("unelevated rounded color=primary no-caps")
        return

    filtered = _apply_filters(state.dishes, filters)
    if not filtered:
        ui.label("Geen gerechten gevonden met deze filters.").style(
            "font-size:14px;color:var(--c-text-3);padding:2rem 0"
        )
        return

    with ui.element("div").classes("sp-dish-grid"):
        for dish in filtered:
            _render_dish_card(dish, state.dish_data.get(dish.id), session, reload_fn)


def _render_star_display(rating: float) -> None:
    with ui.element("div").style("display:flex;gap:1px;flex-shrink:0;align-items:center"):
        for i in range(1, 6):
            if rating >= i:
                icon = "star"
                color = "#f59e0b"
            elif rating >= i - 0.5:
                icon = "star_half"
                color = "#f59e0b"
            else:
                icon = "star_border"
                color = "var(--c-border-strong)"
            ui.icon(icon, size="14px").style(f"color:{color}")


def _render_star_input(value: float, on_change) -> None:
    with (
        ui.element("div")
        .classes("sp-star-input")
        .style("display:flex;gap:2px;align-items:center;cursor:pointer")
    ):
        for i in range(1, 6):
            half_val = i - 0.5
            full_val = float(i)
            with ui.element("div").style("position:relative;width:22px;height:22px;cursor:pointer"):
                if value >= full_val:
                    icon = "star"
                    color = "#f59e0b"
                elif value >= half_val:
                    icon = "star_half"
                    color = "#f59e0b"
                else:
                    icon = "star_border"
                    color = "var(--c-border-strong)"
                ui.icon(icon, size="22px").style(
                    f"color:{color};position:absolute;top:0;left:0;pointer-events:none"
                )
                ui.element("div").style(
                    "position:absolute;top:0;left:0;width:50%;height:100%;z-index:1"
                ).on("click", lambda e, v=half_val: on_change(v))
                ui.element("div").style(
                    "position:absolute;top:0;right:0;width:50%;height:100%;z-index:1"
                ).on("click", lambda e, v=full_val: on_change(v))
        if value and value > 0:
            with (
                ui.element("div")
                .style(
                    "width:16px;height:16px;cursor:pointer;display:flex;"
                    "align-items:center;justify-content:center;margin-left:2px"
                )
                .on("click", lambda e: on_change(None))
                .tooltip("Waardering wissen")
            ):
                ui.icon("sym_r_close", size="12px").style("color:var(--c-text-4)")


def _render_dish_card(dish, data: _DishCardData | None, session, reload_fn) -> None:
    from pyplus.ui.format import (
        cooking_emoji,
        meat_emoji,
        parse_cooking_methods,
        prep_time_label,
        starch_emoji,
        veg_emoji,
    )

    user_id = session.user_id
    d = data or _DishCardData()
    total = len(d.ingredients)
    show_meta = session.settings.show_dish_metadata

    has_issue = bool(d.discontinued or d.unavail > 0)

    with (
        ui.element("div")
        .classes("sp-dish-card")
        .style("opacity:.6" if dish.archived else "")
        .on("click", lambda di=dish: _open_editor(user_id, session, di.id, reload_fn))
    ):
        # Title row + rating
        with ui.element("div").style(
            "display:flex;align-items:flex-start;justify-content:space-between;gap:.375rem"
        ):
            with ui.element("div").style("flex:1;min-width:0"):
                ui.label(dish.name).classes("sp-dish-card-name")
                if dish.group_name and dish.group_name != dish.name:
                    ui.label(f"Groep: {dish.group_name}").style(
                        "font-size:10px;color:var(--c-text-4);margin-top:1px;"
                        "white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
                    )
            if dish.rating and dish.rating > 0:
                _render_star_display(dish.rating)

        if show_meta:
            prop_parts: list[str] = []
            me = meat_emoji(dish.meat_type)
            if me:
                prop_parts.append(me)
            se = starch_emoji(dish.starch_type)
            if se and dish.starch_type != "geen_anders":
                prop_parts.append(se)
            ve = veg_emoji(dish.veg_count)
            if ve and ve != "➖":
                prop_parts.append(ve)
            prep = prep_time_label(dish.prep_minutes)
            if prep:
                prop_parts.append(f"⏱ {prep}")
            cooking_methods = parse_cooking_methods(dish)
            for m in cooking_methods:
                ce = cooking_emoji(m)
                if ce:
                    prop_parts.append(ce)
            if dish.is_cold:
                prop_parts.append("❄️")
            if dish.is_unhealthy:
                prop_parts.append("🍔")
            if prop_parts:
                ui.label(" · ".join(prop_parts)).style(
                    "font-size:11px;color:var(--c-text-3);margin-top:2px"
                )

        # Bottom line: count + price + availability
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.375rem;margin-top:auto;padding-top:4px"
        ):
            parts = [f"{total} ingrediënt{'en' if total != 1 else ''}"]
            if d.total_price > 0:
                parts.append(f"· ≈ €\xa0{d.total_price:.2f}".replace(".", ","))
            ui.label(" ".join(parts)).style("font-size:11px;color:var(--c-text-4)")
            if total > 0 and has_issue:
                n = len(d.discontinued) if d.discontinued else d.unavail
                label_key = (
                    "dishes.discontinued_count" if d.discontinued else "dishes.partial_unavail"
                )
                ui.label(t(label_key, n=n)).classes("sp-badge sp-badge-unavailable").style(
                    "font-size:10px"
                )


# ── CRUD helpers ───────────────────────────────────────────────────────────────


async def _duplicate(user_id: int, dish_id: int, reload_fn) -> None:
    async with AsyncSessionLocal() as db:
        await repo.duplicate_dish(db, user_id, dish_id)
    ui.notify("Gerecht gedupliceerd", type="positive", timeout=2000)
    await reload_fn()


async def _toggle_archive(user_id: int, dish, reload_fn, dlg=None) -> None:
    async with AsyncSessionLocal() as db:
        await repo.archive_dish(db, user_id, dish.id, not dish.archived)
    action = "hersteld" if dish.archived else "gearchiveerd"
    ui.notify(f"Gerecht {action}", type="info", timeout=2000)
    if dlg:
        dlg.close()
    await reload_fn()


# ── Dish editor dialog ─────────────────────────────────────────────────────────


@dataclass
class _IngRow:
    """Mutable state for one ingredient row in the editor."""

    id: int | None
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
    flexible: bool = False
    subtitle: str = ""
    price: float = 0.0
    discontinued: bool = False
    relinking: bool = False
    search_query: str = ""
    search_results: list = field(default_factory=list)
    searching: bool = False


async def _open_editor(user_id: int, session, dish_id: int | None, reload_fn) -> None:
    """Open the dish editor dialog for creating or editing a dish."""
    async with AsyncSessionLocal() as db:
        all_group_names = await repo.get_dish_group_names(db, user_id)

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
        unhealthy_val = dish.is_unhealthy
        dinner_val = dish.is_dinner
        rating_val = dish.rating
        group_val = dish.group_name or dish.name
        cooldown_val = dish.cooldown_weeks
        original_name = dish.name
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
        unhealthy_val = False
        dinner_val = True
        rating_val = None
        group_val = ""
        cooldown_val = None
        original_name = ""

    meta = {
        "prep_minutes": prep_val,
        "meat_type": meat_val,
        "starch_type": starch_val,
        "veg_count": veg_val,
        "cooking_methods": list(cooking_val),
        "is_cold": cold_val,
        "is_unhealthy": unhealthy_val,
        "is_dinner": dinner_val,
        "rating": rating_val,
        "group_name": group_val,
        "cooldown_weeks": cooldown_val,
        "_original_name": original_name,
    }

    rows: list[_IngRow] = []
    if raw_ings:
        async with AsyncSessionLocal() as db:
            skus = [ing.sku for ing in raw_ings if ing.sku]
            sku_cache = await repo.get_ingredient_skus_by_skus(db, user_id, skus)

            for ing in sorted(raw_ings, key=lambda x: (x.sort_order, x.id)):
                cached = sku_cache.get(ing.sku)
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
                        price=cached.last_price if cached and cached.last_price else 0.0,
                    )
                )
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
            "width:640px;max-width:95vw;max-height:90vh;padding:0;"
            "display:flex;flex-direction:column;overflow:hidden"
        ):
            # Header
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1.25rem;border-bottom:1px solid var(--c-border);"
                "flex-shrink:0;gap:.5rem"
            ):
                with ui.element("div").style(
                    "display:flex;align-items:center;gap:.375rem;min-width:0"
                ):
                    title = t("dishes.edit") if dish else t("dishes.new")
                    ui.label(title).style(
                        "font-size:17px;font-weight:700;color:var(--c-text);"
                        "white-space:nowrap;letter-spacing:-.2px"
                    )
                    if dish:
                        with ui.button(icon="sym_r_more_vert").props("flat dense round size=sm"):
                            with ui.menu():
                                ui.menu_item(
                                    t("dishes.duplicate"),
                                    on_click=lambda: (
                                        dlg.close(),
                                        asyncio.ensure_future(
                                            _duplicate(user_id, dish.id, reload_fn)
                                        ),
                                    ),
                                )
                                label = (
                                    t("dishes.restore") if dish.archived else t("dishes.archive")
                                )
                                ui.menu_item(
                                    label,
                                    on_click=lambda: asyncio.ensure_future(
                                        _toggle_archive(user_id, dish, reload_fn, dlg)
                                    ),
                                )

                with ui.element("div").style(
                    "display:flex;align-items:center;gap:.5rem;flex-shrink:0"
                ):
                    ui.button(
                        icon="sym_r_close",
                        on_click=dlg.close,
                    ).props("flat round color=grey")

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
                            reload_fn,
                        )

                    ui.button(
                        t("action.save"),
                        on_click=_save,
                    ).props("unelevated rounded no-caps color=primary").style(
                        "font-size:13px;font-weight:600;min-width:80px"
                    )

            # Scrollable body
            with ui.element("div").style(
                "flex:1;overflow-y:auto;overflow-x:hidden;min-width:0;width:100%;padding:1.25rem 1.25rem .75rem"
            ):
                name_input = (
                    ui.input(label=t("dishes.name_label"), value=name_val)
                    .props("outlined dense")
                    .style("width:100%;margin-bottom:.625rem")
                )

                notes_input = (
                    ui.textarea(
                        label=t("dishes.prep_notes_label"),
                        value=notes_val,
                    )
                    .props("outlined dense autogrow")
                    .style("width:100%;margin-bottom:.125rem")
                )
                ui.label(t("dishes.prep_notes_hint")).style(
                    "font-size:11px;color:var(--c-text-4);margin-bottom:.75rem"
                )

                _render_meta_fields(
                    meta,
                    all_group_names=all_group_names,
                    global_cooldown=session.settings.ml_repeat_cooldown_weeks,
                )

                # Ingredients section header
                with ui.element("div").style(
                    "display:flex;align-items:baseline;justify-content:space-between;"
                    "margin-bottom:.5rem;margin-top:.25rem"
                ):
                    ui.label(t("dishes.ingredients")).style(
                        "font-size:14px;font-weight:600;color:var(--c-text)"
                    )

                    @ui.refreshable
                    def _total_price_label() -> None:
                        total = sum(r.price for r in rows if r.price > 0 and not r.optional)
                        if total > 0:
                            ui.label(f"≈ €\xa0{total:.2f}".replace(".", ",")).style(
                                "font-size:12px;color:var(--c-text-4);font-weight:500"
                            )

                    _total_price_label()

                @ui.refreshable
                def _ingredient_list() -> None:
                    _total_price_label.refresh()
                    if not rows:
                        with ui.element("div").style(
                            "display:flex;flex-direction:column;align-items:center;"
                            "padding:1.5rem 0;gap:.25rem"
                        ):
                            ui.label("🛒").style("font-size:1.5rem;opacity:.3")
                            ui.label("Nog geen ingrediënten.").style(
                                "font-size:13px;color:var(--c-text-4)"
                            )
                        return
                    for idx, row in enumerate(rows):
                        _render_ingredient_row(row, idx, rows, session, user_id, _ingredient_list)

                _ingredient_list()

            # Pinned footer
            with ui.element("div").style(
                "display:flex;gap:.25rem;align-items:center;flex-shrink:0;"
                "padding:.625rem 1.25rem;border-top:1px solid var(--c-border);"
                "background:var(--c-surface)"
            ):
                ui.button(
                    f"+ {t('dishes.add_ingredient')}",
                    on_click=lambda: _add_new_row(rows, _ingredient_list),
                ).props("flat no-caps color=primary dense").style("font-size:12px")
                ui.button(
                    f"+ {t('dishes.add_flexible')}",
                    on_click=lambda: _add_flexible_row(rows, _ingredient_list),
                ).props("flat no-caps color=secondary dense").style("font-size:12px").tooltip(
                    t("dishes.flexible_hint")
                )


def _infer_starch_type(name: str, ingredients: list[_IngRow]) -> str | None:
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
    if any(w in combined for w in ("wrap", "tortilla", "taco", "pita", "naan", "flatbread")):
        return "wraps"
    if any(w in combined for w in ("deeg", "bladerdeeg", "filodeeg", "pizza", "brood")):
        return "deeg"
    return None


def _render_meta_fields(
    meta: dict,
    all_group_names: list[str] | None = None,
    global_cooldown: int = 0,
) -> None:
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

    with ui.element("div").classes("sp-meta-grid"):
        prep_sel = (
            ui.select(prep_opts, value=meta["prep_minutes"], label=t("dishes.prep_time_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        prep_sel.on("update:model-value", lambda e, s=prep_sel: meta.update(prep_minutes=s.value))

        meat_sel = (
            ui.select(meat_opts, value=meta["meat_type"], label=t("dishes.meat_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        meat_sel.on("update:model-value", lambda e, s=meat_sel: meta.update(meat_type=s.value))

        starch_sel = (
            ui.select(starch_opts, value=meta["starch_type"], label=t("dishes.starch_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        starch_sel.on(
            "update:model-value", lambda e, s=starch_sel: meta.update(starch_type=s.value)
        )

        veg_sel = (
            ui.select(veg_opts, value=meta["veg_count"], label=t("dishes.veg_label"))
            .props("outlined dense options-dense")
            .style("width:100%")
        )
        veg_sel.on("update:model-value", lambda e, s=veg_sel: meta.update(veg_count=s.value))

    with ui.element("div").classes("sp-meta-grid"):
        group_opts = {g: g for g in (all_group_names or [])}
        group_sel = (
            ui.select(
                group_opts,
                value=meta.get("group_name", ""),
                label=t("dishes.group_label"),
                with_input=True,
                new_value_mode="add-unique",
            )
            .props("outlined dense options-dense")
            .style("width:100%")
            .tooltip(t("dishes.group_hint"))
        )
        group_sel.on("update:model-value", lambda e, s=group_sel: meta.update(group_name=s.value))

        cooldown_input = (
            ui.number(
                value=meta.get("cooldown_weeks"),
                label=t("dishes.cooldown_label"),
                min=0,
                max=52,
            )
            .props("outlined dense clearable suffix=weken")
            .style("width:100%")
            .tooltip(t("dishes.cooldown_hint", n=global_cooldown))
        )
        cooldown_input.on(
            "update:model-value",
            lambda e, c=cooldown_input: meta.update(
                cooldown_weeks=int(c.value) if c.value is not None else None
            ),
        )

    with ui.element("div").style(
        "display:flex;align-items:center;gap:.25rem .75rem;flex-wrap:wrap;margin-bottom:.75rem"
    ):
        ui.label(t("dishes.cooking_methods_label")).style(
            "font-size:12px;font-weight:600;color:var(--c-text-2);margin-right:.25rem"
        )
        for method in COOKING_METHODS:
            checked = method in meta.get("cooking_methods", [])
            cb = (
                ui.checkbox(
                    f"{cooking_emoji(method)} {cooking_label(method)}",
                    value=checked,
                )
                .props("dense")
                .style("margin-right:-.25rem")
            )

            def _on_cooking(e, m=method, c=cb) -> None:
                methods = meta.get("cooking_methods", [])
                if c.value and m not in methods:
                    methods.append(m)
                elif not c.value and m in methods:
                    methods.remove(m)
                meta["cooking_methods"] = methods

            cb.on("update:model-value", _on_cooking)

        cold_cb = (
            ui.checkbox(f"❄️ {t('dishes.is_cold_label')}", value=meta.get("is_cold", False))
            .props("dense")
            .style("margin-right:-.25rem")
        )
        cold_cb.on(
            "update:model-value",
            lambda e: meta.update(is_cold=bool(cold_cb.value)),
        )

        unhealthy_cb = (
            ui.checkbox(
                f"🍔 {t('dishes.is_unhealthy_label')}", value=meta.get("is_unhealthy", False)
            )
            .props("dense")
            .style("margin-right:-.25rem")
        )
        unhealthy_cb.on(
            "update:model-value",
            lambda e: meta.update(is_unhealthy=bool(unhealthy_cb.value)),
        )

        dinner_cb = (
            ui.checkbox(
                f"🍽️ {t('dishes.is_dinner_label')}",
                value=meta.get("is_dinner", True),
            )
            .props("dense")
            .style("margin-right:-.25rem")
        )
        dinner_cb.on(
            "update:model-value",
            lambda e: meta.update(is_dinner=bool(dinner_cb.value)),
        )

    with ui.element("div").style("display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem"):
        ui.label(t("dishes.rating_label")).style(
            "font-size:12px;font-weight:600;color:var(--c-text-2)"
        )

        @ui.refreshable
        def _rating_input():
            def _on_rating(val):
                meta["rating"] = val
                _rating_input.refresh()

            _render_star_input(meta.get("rating") or 0, _on_rating)

        _rating_input()


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
            relinking=True,
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
    with (
        ui.element("div")
        .classes("sp-ing-row")
        .style(
            "padding:.5rem .625rem;border:1px dashed var(--c-brand);"
            "border-radius:var(--r-md);margin-bottom:.375rem;background:var(--c-brand-tint)"
        )
    ):
        with ui.element("div").style("display:flex;align-items:center;gap:.5rem;min-width:0"):
            ui.icon("sym_r_tune", size="18px").style("color:var(--c-brand-dark);flex-shrink:0")
            with ui.element("div").style(
                "flex:1;min-width:0;overflow:hidden;display:flex;flex-direction:column;gap:1px"
            ):
                ui.label(t("dishes.flexible_badge")).style(
                    "font-size:9px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;"
                    "color:var(--c-brand-dark)"
                )
                label_input = (
                    ui.input(placeholder=t("dishes.flexible_placeholder"), value=row.display_name)
                    .props("dense borderless")
                    .style("width:100%;font-size:13px;overflow:hidden")
                )
                label_input.on(
                    "blur", lambda e, r=row: setattr(r, "display_name", label_input.value or "")
                )

            ui.button(
                icon="sym_r_delete", on_click=lambda i=idx: _remove_row(rows, i, refresh_fn)
            ).props("flat dense round size=sm color=negative")

        with (
            ui.element("div")
            .classes("sp-ing-controls")
            .style("display:flex;align-items:center;gap:.375rem;flex-wrap:wrap")
        ):
            amount_input = (
                ui.input(value=_fmt_amount(row.amount))
                .props("outlined dense")
                .style("width:52px;flex-shrink:0")
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
                .style("width:90px;flex-shrink:0")
            )
            unit_select.on(
                "update:model-value", lambda e, r=row: setattr(r, "amount_unit", e.value)
            )

            with ui.element("div").style("display:flex;gap:1px;flex-shrink:0;margin-left:auto"):
                if idx > 0:
                    ui.button(
                        icon="sym_r_arrow_upward",
                        on_click=lambda i=idx: _move_row(rows, i, -1, refresh_fn),
                    ).props("flat dense round size=sm")
                if idx < len(rows) - 1:
                    ui.button(
                        icon="sym_r_arrow_downward",
                        on_click=lambda i=idx: _move_row(rows, i, +1, refresh_fn),
                    ).props("flat dense round size=sm")


def _fmt_amount(amount: float) -> str:
    return str(int(amount) if amount == int(amount) else amount)


async def _open_substitute_for_row(row: _IngRow, session, user_id: int, refresh_fn) -> None:
    from pyplus.services.categories import parse_categories
    from pyplus.ui.components.substitutes import show_substitute_dialog

    cats: list[str] = []
    price = 0.0
    brand = ""

    async with AsyncSessionLocal() as db:
        pc = await repo.get_product_cache_by_skus(db, session.store_number or 0, [row.sku])
        cached_sku = await repo.get_ingredient_sku(db, user_id, row.sku)
    subtitle = row.subtitle
    if row.sku in pc:
        cats = parse_categories(pc[row.sku].categories_json)
        price = pc[row.sku].price or 0.0
        brand = pc[row.sku].brand or ""
        subtitle = subtitle or pc[row.sku].subtitle or ""
    elif cached_sku:
        price = cached_sku.last_price or 0.0
        subtitle = subtitle or cached_sku.subtitle or ""

    def _on_pick(product):
        from pyplus.services.dishes import _parse_pack_from_subtitle

        row.sku = product.sku
        row.display_name = product.name
        row.image_url = product.image_url
        row.subtitle = product.subtitle or ""
        row.price = product.price or 0.0
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
        product_subtitle=subtitle,
        categories=cats,
        price=price,
        brand=brand,
        mode="cart",
        is_unavailable=row.discontinued,
        on_select=_on_pick,
    )


def _render_ingredient_row(
    row: _IngRow, idx: int, rows: list, session, user_id: int, refresh_fn
) -> None:
    if row.flexible:
        _render_flexible_row(row, idx, rows, refresh_fn)
        return
    with (
        ui.element("div")
        .classes("sp-ing-row")
        .style(
            "padding:.5rem .625rem;border:1px solid var(--c-border);"
            "border-radius:var(--r-md);margin-bottom:.375rem;"
            "background:var(--c-surface)"
        )
    ):
        # Top row: [image] [name/search] [action buttons]
        with ui.element("div").style("display:flex;align-items:center;gap:.5rem;min-width:0"):
            if row.image_url and not row.relinking:
                ui.image(row.image_url).style(
                    "width:36px;height:36px;border-radius:var(--r-sm);"
                    "object-fit:contain;background:white;flex-shrink:0"
                )
            else:
                ui.element("div").style(
                    "width:36px;height:36px;border-radius:var(--r-sm);"
                    "background:var(--c-surface-2);flex-shrink:0"
                )

            if row.relinking or not row.sku:
                search_field = (
                    ui.input(
                        placeholder=t("dishes.ingredient_search"),
                        value=row.search_query,
                    )
                    .props("outlined dense clearable autofocus")
                    .style("flex:1;min-width:0")
                )
            else:
                with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
                    ui.label(row.display_name).style(
                        "font-size:13px;font-weight:500;overflow:hidden;"
                        "text-overflow:ellipsis;white-space:nowrap"
                    )
                    sub_parts: list[str] = []
                    unit_text = row.subtitle or (
                        f"Per {row.pack_size:g} {row.pack_unit}"
                        if row.pack_size and row.pack_unit
                        else ""
                    )
                    if unit_text:
                        sub_parts.append(unit_text)
                    if row.price > 0:
                        sub_parts.append(f"€\xa0{row.price:.2f}".replace(".", ","))
                    if sub_parts:
                        ui.label(" · ".join(sub_parts)).style(
                            "font-size:11px;color:var(--c-text-3);overflow:hidden;"
                            "text-overflow:ellipsis;white-space:nowrap"
                        )

            # Action buttons — right-aligned
            with ui.element("div").style("display:flex;gap:1px;flex-shrink:0;align-items:center"):
                if row.sku and not row.relinking:
                    if row.discontinued:
                        ui.label(t("status.discontinued")).classes(
                            "sp-badge sp-badge-unavailable"
                        ).style("font-size:10px;margin-right:.25rem")

                    async def _open_sub(r=row):
                        await _open_substitute_for_row(r, session, user_id, refresh_fn)

                    ui.button(
                        icon="sym_r_find_replace",
                        on_click=_open_sub,
                    ).props("flat dense round size=sm color=primary").tooltip(
                        t("substitute.replace_btn")
                    )
                    ui.button(
                        icon="sym_r_edit",
                        on_click=lambda r=row: (
                            setattr(r, "relinking", True),
                            setattr(r, "search_results", []),
                            refresh_fn.refresh(),
                        ),
                    ).props("flat dense round size=sm").tooltip(t("dishes.relink"))

                ui.button(
                    icon="sym_r_delete",
                    on_click=lambda i=idx: _remove_row(rows, i, refresh_fn),
                ).props("flat dense round size=sm color=negative")

        # Inline results — rendered as a column sibling so they never clip on mobile
        if row.relinking or not row.sku:
            results_box = ui.element("div").style("min-width:0")

            def _draw_results(r=row, box=results_box):
                box.clear()
                with box:
                    if r.searching:
                        with ui.element("div").style(
                            "background:var(--c-surface-2);"
                            "border-radius:var(--r-md);padding:.5rem .75rem;margin-top:.25rem"
                        ):
                            ui.label("Zoeken…").style("font-size:12px;color:var(--c-text-3)")
                    elif r.search_results:
                        with ui.element("div").style(
                            "background:var(--c-surface);border:1px solid var(--c-border);"
                            "border-radius:var(--r-md);margin-top:.25rem;"
                            "max-height:45vh;overflow-y:auto"
                        ):
                            for prod in r.search_results[:8]:
                                _render_search_result(prod, r, session, user_id, refresh_fn)

            async def _on_search(e, r=row, field=search_field):
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

        # Controls row: [amount] [unit] [optional] [move buttons]
        with (
            ui.element("div")
            .classes("sp-ing-controls")
            .style("display:flex;align-items:center;gap:.375rem;flex-wrap:wrap")
        ):
            amount_str = [str(int(row.amount) if row.amount == int(row.amount) else row.amount)]
            amount_input = (
                ui.input(value=amount_str[0])
                .props("outlined dense")
                .style("width:52px;flex-shrink:0")
            )

            def _amount_change(e, r=row):
                try:
                    r.amount = float(e.value.replace(",", "."))
                except (ValueError, AttributeError):
                    pass

            amount_input.on("blur", _amount_change)
            amount_input.on("keydown.enter", _amount_change)

            ui.label(row.amount_unit or "").style(
                "font-size:12px;color:var(--c-text-3);flex-shrink:0;min-width:30px"
            )

            opt_check = ui.checkbox(t("dishes.optional"), value=row.optional).props("dense")
            opt_check.tooltip(t("dishes.optional_hint"))
            opt_check.on(
                "update:model-value",
                lambda e, r=row: setattr(r, "optional", bool(e.value)),
            )

            with ui.element("div").style("display:flex;gap:1px;flex-shrink:0;margin-left:auto"):
                if idx > 0:
                    ui.button(
                        icon="sym_r_arrow_upward",
                        on_click=lambda i=idx: _move_row(rows, i, -1, refresh_fn),
                    ).props("flat dense round size=sm")

                if idx < len(rows) - 1:
                    ui.button(
                        icon="sym_r_arrow_downward",
                        on_click=lambda i=idx: _move_row(rows, i, +1, refresh_fn),
                    ).props("flat dense round size=sm")


def _render_search_result(prod, row: _IngRow, session, user_id: int, refresh_fn) -> None:
    async def _pick(p=prod, r=row):
        r.sku = p.sku
        r.display_name = p.name
        r.image_url = p.image_url
        r.subtitle = p.subtitle or ""
        r.price = p.price or 0.0
        r.relinking = False
        r.discontinued = False
        r.search_query = ""
        r.search_results = []
        from pyplus.services.dishes import _parse_pack_from_subtitle

        pack_size, pack_unit = _parse_pack_from_subtitle(p.subtitle)
        if pack_unit and r.amount_unit == "stuks":
            r.amount_unit = pack_unit
        r.pack_size = pack_size
        r.pack_unit = pack_unit
        from pyplus.services.dishes import cache_ingredient_sku_from_product

        async with AsyncSessionLocal() as db:
            await cache_ingredient_sku_from_product(db, user_id, p)
        refresh_fn.refresh()

    avail_color = "var(--c-brand-dark)" if prod.is_available else "var(--c-danger)"
    with ui.element("div").classes("sp-search-result").on("click", _pick):
        if prod.image_url:
            ui.image(prod.image_url).style(
                "width:32px;height:32px;object-fit:contain;"
                "border-radius:var(--r-xs);background:white;flex-shrink:0"
            )
        with ui.element("div").style("flex:1;min-width:0"):
            ui.label(prod.name).style(
                "font-size:13px;font-weight:500;overflow:hidden;"
                "text-overflow:ellipsis;white-space:nowrap"
            )
            with ui.element("div").style("display:flex;align-items:center;gap:.375rem"):
                if prod.subtitle:
                    ui.label(prod.subtitle).style("font-size:11px;color:var(--c-text-3)")
                if prod.price > 0:
                    ui.label(f"€\xa0{prod.price:.2f}".replace(".", ",")).style(
                        "font-size:11px;font-weight:600;color:var(--c-text-2)"
                    )
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
    reload_fn,
) -> None:
    name = name.strip()
    if not name:
        ui.notify("Voer een naam in", type="negative")
        return

    import json as _json

    cooking_json = _json.dumps(meta.get("cooking_methods", []))

    if not meta.get("starch_type"):
        inferred = _infer_starch_type(name, rows)
        if inferred:
            meta["starch_type"] = inferred

    group_name = meta.get("group_name") or ""
    original_name = meta.get("_original_name", "")
    if group_name == original_name and name != original_name:
        group_name = name
    if not group_name:
        group_name = name
    cooldown_weeks = meta.get("cooldown_weeks")

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
                is_unhealthy=bool(meta.get("is_unhealthy", False)),
                is_dinner=bool(meta.get("is_dinner", True)),
                rating=meta.get("rating"),
                veg_count=meta.get("veg_count"),
                group_name=group_name,
                cooldown_weeks=cooldown_weeks,
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
                is_unhealthy=bool(meta.get("is_unhealthy", False)),
                is_dinner=bool(meta.get("is_dinner", True)),
                rating=meta.get("rating"),
                veg_count=meta.get("veg_count"),
                group_name=group_name,
                cooldown_weeks=cooldown_weeks,
            )

        if not dish:
            ui.notify(t("status.error"), type="negative")
            return

        existing = await repo.get_ingredients(db, dish.id)
        for ing in existing:
            await db.delete(ing)
        await db.flush()

        for i, row in enumerate(rows):
            if row.flexible:
                if not (row.display_name or "").strip():
                    continue
            elif not row.sku:
                continue
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
    await reload_fn()
