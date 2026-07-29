"""
Lane ① — Deze week: 7 dinner + 5 lunch slots with pack-optimised cart add.

State lives in _MealsState (plain Python, not reactive).  The @ui.refreshable
_render() function re-draws from the current state on demand.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass, field

from nicegui import ui

from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import Dish
from pyplus.i18n import t
from pyplus.services.aggregate import AggLine, AggResult, aggregate, fmt_amount
from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url

log = logging.getLogger(__name__)

_DINNER_SLOTS = ["ma", "di", "wo", "do", "vr"]
_WEEKEND_SLOTS = ["za", "zo"]
_LUNCH_SLOTS = ["lunch1", "lunch2", "lunch3", "lunch4", "lunch5"]
_EXTRA_SLOTS = _LUNCH_SLOTS  # 5 extra slots below the dinner grid
_ALL_SLOTS = _DINNER_SLOTS + _WEEKEND_SLOTS + _LUNCH_SLOTS

_DAY_LABEL = {
    "ma": "Maandag",
    "di": "Dinsdag",
    "wo": "Woensdag",
    "do": "Donderdag",
    "vr": "Vrijdag",
    "za": "Zaterdag",
    "zo": "Zondag",
    "lunch1": "Extra (maandag)",
    "lunch2": "Extra (dinsdag)",
    "lunch3": "Extra (woensdag)",
    "lunch4": "Extra (donderdag)",
    "lunch5": "Extra (vrijdag)",
}
_MONTHS_NL = {
    1: "januari",
    2: "februari",
    3: "maart",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "augustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "december",
}

# The dish picker packs "<name><US><properties>" into each option label, where
# <US> is the unit-separator control char. The custom option slot below splits
# on it so the name renders as the prominent primary label and the planning
# properties as a smaller, greyish caption on their own line.
_OPT_SEP = "\u001f"
_PICKER_OPTION_SLOT = """
<q-item v-bind="props.itemProps">
  <q-item-section>
    <q-item-label>{{ props.opt.label.split(String.fromCharCode(31))[0] }}</q-item-label>
    <q-item-label caption v-if="props.opt.label.includes(String.fromCharCode(31))">
      {{ props.opt.label.split(String.fromCharCode(31))[1] }}
    </q-item-label>
  </q-item-section>
</q-item>
"""


# ── Helpers ────────────────────────────────────────────────────────────────────


def _current_monday() -> datetime.date:
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    return tomorrow - datetime.timedelta(days=tomorrow.weekday())


def _format_week(week_start: datetime.date) -> str:
    week_end = week_start + datetime.timedelta(days=6)
    wn = week_start.isocalendar()[1]
    ms = _MONTHS_NL[week_start.month]
    if week_start.month == week_end.month:
        return f"Week {wn} · {week_start.day}–{week_end.day} {ms}"
    me = _MONTHS_NL[week_end.month]
    return f"Week {wn} · {week_start.day} {ms}–{week_end.day} {me}"


_DATED_SLOTS = _DINNER_SLOTS + _WEEKEND_SLOTS  # Ma–Zo all have calendar dates


def _slot_date(slot: str, week_start: datetime.date) -> datetime.date | None:
    if slot in _DATED_SLOTS:
        return week_start + datetime.timedelta(days=_DATED_SLOTS.index(slot))
    return None


_RELATIVE_DAYS = {-2: "Eergisteren", -1: "Gisteren", 0: "Vandaag", 1: "Morgen", 2: "Overmorgen"}


def _relative_label(d: datetime.date | None) -> str | None:
    if d is None:
        return None
    return _RELATIVE_DAYS.get((d - datetime.date.today()).days)


def _week_title(week_start: datetime.date) -> str:
    today = datetime.date.today()
    this_monday = today - datetime.timedelta(days=today.weekday())
    diff = (week_start - this_monday).days // 7
    if diff == 0:
        return "Deze week"
    if diff == -1:
        return "Vorige week"
    if diff == 1:
        return "Komende week"
    return _format_week(week_start)


# ── State ──────────────────────────────────────────────────────────────────────


@dataclass
class _MealsState:
    week_start: datetime.date
    slots: dict[str, Dish | None] = field(default_factory=dict)
    dishes: list[Dish] = field(default_factory=list)


async def _load_slots(state: _MealsState, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        rows = await repo.get_weekmenu(db, user_id, state.week_start)
        if not state.dishes:
            state.dishes = await repo.get_dishes(db, user_id)
    state.slots = {s: None for s in _ALL_SLOTS}
    for row in rows:
        if row.slot in state.slots:
            state.slots[row.slot] = row.dish  # may be None if dish was deleted


# ── Public entry point ─────────────────────────────────────────────────────────


async def create_meals_lane(session) -> None:
    """Render Lane ①."""
    state = _MealsState(week_start=_current_monday())
    load_error = ""
    try:
        # The slot/dish load and the weather load are independent — run concurrently.
        _, state._weather = await asyncio.gather(
            _load_slots(state, session.user_id),
            _load_weather(session, state.week_start),
        )
    except Exception as exc:
        log.error("Meals lane load failed: %s", exc)
        load_error = "Weekmenu kon niet worden geladen."

    with ui.element("div").classes("sp-lane"):
        # ── Header ────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;gap:.5rem"
            ):
                title_lbl = ui.label(_week_title(state.week_start)).classes("sp-lane-title")
                if not load_error:
                    with ui.element("div").style("display:flex;align-items:center;gap:0px"):
                        ui.button(
                            icon="sym_r_chevron_left",
                            on_click=lambda: _navigate(
                                session.user_id, state, -1, week_lbl, title_lbl, _render, session
                            ),
                        ).props("flat round dense size=sm color=grey-6")
                        week_lbl = ui.label(_format_week(state.week_start)).style(
                            "font-size:11px;color:var(--c-text-3);font-weight:500;"
                            "white-space:nowrap;min-width:130px;text-align:center"
                        )
                        ui.button(
                            icon="sym_r_chevron_right",
                            on_click=lambda: _navigate(
                                session.user_id, state, +1, week_lbl, title_lbl, _render, session
                            ),
                        ).props("flat round dense size=sm color=grey-6")
            with ui.element("div").classes("sp-weekmenu-actions"):
                plan_btn = (
                    ui.button(
                        t("lane.meals.plan_week"),
                        icon="sym_r_auto_awesome",
                        on_click=lambda: _plan_week(session, state, _render),
                    )
                    .props("flat dense no-caps size=sm color=primary")
                    .classes("sp-weekmenu-action-btn")
                )
                plan_btn.set_visibility(False)
                asyncio.ensure_future(_check_recommender_available(session, plan_btn))
                ui.button(
                    "Agenda",
                    icon="sym_r_event",
                    on_click=lambda: _show_ical_dialog(session, state.week_start),
                ).props("flat dense no-caps size=sm color=grey-8").classes(
                    "sp-weekmenu-action-btn"
                )
                ui.button(
                    t("weekmenu.manage_dishes"),
                    icon="sym_r_skillet",
                    on_click=lambda: ui.navigate.to("/dishes"),
                ).props("flat dense no-caps size=sm color=grey-8").classes(
                    "sp-weekmenu-action-btn"
                )

            def _subtitle_text() -> str:
                _dinner_all = _DINNER_SLOTS + _WEEKEND_SLOTS
                _d = sum(1 for s in _dinner_all if state.slots.get(s) is not None)
                _e = sum(1 for s in _EXTRA_SLOTS if state.slots.get(s) is not None)
                if _d + _e == 0:
                    return "Nog geen gerechten gepland"
                return f"{_d} van 7 avonden · {_e} van 5 extra"

            _subtitle_lbl = ui.label(_subtitle_text()).classes("sp-lane-subtitle")

        # ── Body: slot grid ────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-body sp-meals-body"):
            if load_error:
                with ui.element("div").classes("sp-lane-error"):
                    ui.icon("sym_r_error", size="24px").style("color:var(--c-danger);opacity:.6")
                    ui.label(load_error).style("font-size:13px;color:var(--c-text-3)")
                return

            @ui.refreshable
            def _render() -> None:
                _subtitle_lbl.set_text(_subtitle_text())
                _render_all_slots(session, state, _render)

            _render()

            # ── Add-to-cart button ─────────────────────────────────────────
            ui.separator().style("margin:.5rem 0")
            ui.button(
                t("lane.meals.add_all"),
                icon="sym_r_add_shopping_cart",
                on_click=lambda: _add_weekmenu_to_cart(session, state),
            ).props("unelevated rounded color=primary no-caps").style(
                "width:100%;font-size:13px;font-weight:600;height:44px"
            )


# ── Slot rendering ─────────────────────────────────────────────────────────────


async def _load_weather(session, week_start: datetime.date) -> dict[datetime.date, float]:
    if not session.settings.weather_enabled:
        return {}
    lat = session.settings.weather_latitude
    lon = session.settings.weather_longitude
    if lat is None or lon is None:
        return {}
    async with AsyncSessionLocal() as db:
        return await repo.get_weather_range(
            db, lat, lon, week_start, week_start + datetime.timedelta(days=6)
        )


def _render_all_slots(session, state: _MealsState, refresh_fn) -> None:
    from pyplus.ui.format import dish_meta_chips

    show_meta = session.settings.show_dish_metadata

    def _opt_label(d) -> str:
        if not show_meta:
            return d.name
        chips = dish_meta_chips(d)
        return f"{d.name}{_OPT_SEP}{'  '.join(chips)}" if chips else d.name

    options = {d.id: _opt_label(d) for d in state.dishes}
    weather = getattr(state, "_weather", {})

    # Dinner section header with dishes link
    with ui.element("div").style(
        "display:flex;align-items:center;justify-content:space-between;margin-bottom:.375rem"
    ):
        _section_header(t("lane.meals.dinner"))
        ui.link(t("weekmenu.manage_dishes"), "/dishes").style(
            "font-size:11px;font-weight:600;color:var(--c-brand-dark);"
            "text-decoration:none;white-space:nowrap"
        )

    with ui.element("div").classes("sp-weekmenu-grid"):
        for slot in _DINNER_SLOTS:
            d = _slot_date(slot, state.week_start)
            date_str = f"{d.day} {_MONTHS_NL[d.month]}" if d else ""
            temp = weather.get(d) if d else None
            _slot_card(slot, _DAY_LABEL[slot], date_str, temp, state, options, session, refresh_fn)
    with ui.element("div").classes("sp-weekmenu-weekend-grid"):
        for slot in _WEEKEND_SLOTS:
            d = _slot_date(slot, state.week_start)
            date_str = f"{d.day} {_MONTHS_NL[d.month]}" if d else ""
            temp = weather.get(d) if d else None
            _slot_card(slot, _DAY_LABEL[slot], date_str, temp, state, options, session, refresh_fn)

    ui.element("div").style("height:.5rem")
    _section_header(t("lane.meals.lunch"))
    with ui.element("div").classes("sp-weekmenu-extra-grid"):
        for slot in _EXTRA_SLOTS:
            d = _slot_date(slot, state.week_start)
            date_str = f"{d.day} {_MONTHS_NL[d.month]}" if d else ""
            temp = weather.get(d) if d else None
            _slot_card(slot, _DAY_LABEL[slot], date_str, temp, state, options, session, refresh_fn)


def _section_header(label: str) -> None:
    ui.label(label).style(
        "font-size:11px;font-weight:700;color:var(--c-text-3);"
        "letter-spacing:.08em;text-transform:uppercase;"
        "margin:.25rem 0 .2rem;display:block"
    )


def _slot_card(slot, day_label, date_str, temp, state, options, session, refresh_fn) -> None:
    """Render a single slot as a day card (used inside the weekmenu grid)."""
    dish = state.slots.get(slot)
    is_filled = dish is not None
    card_cls = "sp-weekmenu-card sp-weekmenu-card--filled" if is_filled else "sp-weekmenu-card"

    with ui.element("div").classes(card_cls):
        # Card header: day label + date + temperature
        with ui.element("div").classes("sp-weekmenu-card__head"):
            with ui.element("div"):
                ui.label(day_label).classes("sp-weekmenu-card__day")
                if date_str:
                    rel = _relative_label(_slot_date(slot, state.week_start))
                    label = f"{date_str} · {rel}" if rel else date_str
                    ui.label(label).classes("sp-weekmenu-card__date")
            if temp is not None:
                import math

                hot = session.settings.weather_hot_threshold
                temp_rounded = math.floor(temp + 0.5)
                t_color = "var(--c-warning-dark)" if temp_rounded >= hot else "var(--c-text-4)"
                ui.label(f"{temp_rounded}°").style(
                    f"font-size:11px;font-weight:700;color:{t_color};flex-shrink:0"
                )

        # Card body
        with ui.element("div").classes("sp-weekmenu-card__body"):
            if dish is None:
                picker = (
                    ui.select(
                        options,
                        value=None,
                        with_input=True,
                        label=t("lane.meals.empty_slot"),
                        on_change=lambda e, s=slot: asyncio.ensure_future(
                            _pick_dish(session.user_id, s, e.value, state, refresh_fn)
                        ),
                    )
                    .props("outlined dense options-dense")
                    .style("width:100%")
                    .classes("sp-meals-picker")
                )
                picker.add_slot("option", _PICKER_OPTION_SLOT)
            else:
                from pyplus.ui.format import dish_meta_chips

                ui.label(dish.name).classes("sp-weekmenu-card__dish")
                chips = dish_meta_chips(dish)
                if chips:
                    ui.label("  ".join(chips)).classes("sp-weekmenu-card__meta")

        # Card footer with action buttons (only for filled slots)
        if is_filled and dish is not None:
            with ui.element("div").classes("sp-weekmenu-card__foot"):
                with ui.element("div").style("display:flex;gap:1px"):
                    ui.button(
                        icon="sym_r_close",
                        on_click=lambda s=slot, d=dish: (
                            _confirm_clear(session, s, d, state, refresh_fn)
                            if session.settings.confirm_clear_slot
                            else asyncio.ensure_future(
                                _clear_slot(session.user_id, s, state, refresh_fn)
                            )
                        ),
                    ).props("flat round dense size=xs color=grey-6").tooltip(t("lane.meals.clear"))
                    if dish.prep_notes:
                        ui.button(
                            icon="sym_r_menu_book",
                            on_click=lambda d=dish: _show_prep_notes(d),
                        ).props("flat round dense size=xs color=grey-6").tooltip(
                            t("lane.meals.view_prep")
                        )
                ui.button(
                    icon="sym_r_add_shopping_cart",
                    on_click=lambda d=dish: asyncio.ensure_future(
                        _add_one_slot_to_cart(session, d, state)
                    ),
                ).props("flat round dense size=xs color=primary").tooltip(
                    t("weekmenu.add_ingredients")
                )


async def _add_one_slot_to_cart(session, dish: Dish, state: _MealsState) -> None:
    """Add one dish's ingredients via the full add flow (availability check + dialog)."""
    mini_state = _MealsState(week_start=state.week_start)
    mini_state.slots = {"ma": dish}
    mini_state.dishes = state.dishes
    await _add_weekmenu_to_cart(session, mini_state)


def _show_prep_notes(dish: Dish) -> None:
    with ui.dialog(value=True) as dlg:
        with ui.card().style("max-width:440px;width:100%;padding:0;overflow:hidden"):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1rem .625rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label(dish.name).style(
                    "font-size:16px;font-weight:700;color:var(--c-text);letter-spacing:-.2px"
                )
                ui.button(icon="sym_r_close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )
            with ui.element("div").style("padding:1rem"):
                ui.label(dish.prep_notes).style(
                    "font-size:14px;color:var(--c-text-2);white-space:pre-wrap;line-height:1.6"
                )


# ── Slot mutations ─────────────────────────────────────────────────────────────


async def _navigate(
    user_id: int,
    state: _MealsState,
    delta_weeks: int,
    week_lbl,
    title_lbl,
    refresh_fn,
    session=None,
) -> None:
    state.week_start += datetime.timedelta(weeks=delta_weeks)
    await _load_slots(state, user_id)
    if session:
        state._weather = await _load_weather(session, state.week_start)
    week_lbl.set_text(_format_week(state.week_start))
    title_lbl.set_text(_week_title(state.week_start))
    refresh_fn.refresh()


async def _pick_dish(
    user_id: int,
    slot: str,
    dish_id: int | None,
    state: _MealsState,
    refresh_fn,
) -> None:
    if dish_id is None:
        return
    async with AsyncSessionLocal() as db:
        await repo.set_weekmenu_slot(db, user_id, slot, state.week_start, dish_id)
        dish = await repo.get_dish(db, user_id, dish_id)
    state.slots[slot] = dish
    refresh_fn.refresh()


async def _clear_slot(
    user_id: int,
    slot: str,
    state: _MealsState,
    refresh_fn,
) -> None:
    async with AsyncSessionLocal() as db:
        await repo.set_weekmenu_slot(db, user_id, slot, state.week_start, None)
    state.slots[slot] = None
    refresh_fn.refresh()


def _confirm_clear(session, slot: str, dish, state: _MealsState, refresh_fn) -> None:
    """Confirmation dialog before removing a dish from a week-menu slot."""
    with ui.dialog(value=True) as dlg, ui.card().style("max-width:340px;padding:1.25rem"):
        ui.label("Gerecht verwijderen?").style("font-size:16px;font-weight:700;color:var(--c-text)")
        ui.label(f"'{dish.name}' uit dit dagdeel halen?").style(
            "font-size:13px;color:var(--c-text-3);margin:.375rem 0 .875rem"
        )
        with ui.row().style("justify-content:flex-end;gap:.5rem;width:100%"):
            ui.button(t("action.cancel"), on_click=dlg.close).props("flat rounded no-caps")

            async def _yes() -> None:
                dlg.close()
                await _clear_slot(session.user_id, slot, state, refresh_fn)

            ui.button(t("lane.meals.clear"), on_click=lambda: asyncio.ensure_future(_yes())).props(
                "unelevated rounded no-caps color=negative"
            )


# ── Aggregation + cart add ─────────────────────────────────────────────────────


@dataclass
class _EffIng:
    """A resolved ingredient fed to aggregate() (duck-types DishIngredient)."""

    sku: str
    display_name: str
    amount: float
    amount_unit: str
    optional: bool = False


async def _add_weekmenu_to_cart(session, state: _MealsState) -> None:
    """Resolve unavailable/flexible/optional ingredients, then show the aggregation dialog."""
    filled = [(slot, dish) for slot, dish in state.slots.items() if dish is not None]
    if not filled:
        ui.notify("Geen gerechten geselecteerd", type="info", position="top")
        return

    dishes_with_ings: list[tuple[Dish, list]] = []
    async with AsyncSessionLocal() as db:
        for _, dish in filled:
            ings = await repo.get_ingredients(db, dish.id)
            dishes_with_ings.append((dish, ings))

    # ── Availability check ────────────────────────────────────────────
    all_skus = {
        ing.sku
        for _, ings in dishes_with_ings
        for ing in ings
        if ing.sku and not ing.optional and not ing.flexible
    }
    unavail_skus: set[str] = set()
    product_info: dict[str, object] = {}
    if all_skus:
        async with AsyncSessionLocal() as db:
            pc = await repo.get_product_cache_by_skus(db, session.store_number or 0, list(all_skus))
            for sku in all_skus:
                row = pc.get(sku)
                if row is None or not row.is_available:
                    unavail_skus.add(sku)
                if row:
                    product_info[sku] = row

    if unavail_skus:
        _show_unavail_resolve_dialog(session, dishes_with_ings, unavail_skus, product_info)
        return

    _continue_to_flex_optional(session, dishes_with_ings)


def _continue_to_flex_optional(
    session, dishes_with_ings: list[tuple[Dish, list]], replacements: dict | None = None
) -> None:
    """After availability is resolved, proceed to flex/optional resolution."""
    replacements = replacements or {}

    # Collect the ingredients that need a decision, deduped by row id (a dish in
    # two slots shares the same DishIngredient rows).
    flex_unique: dict[int, object] = {}
    opt_unique: dict[int, object] = {}
    for _, ings in dishes_with_ings:
        for ing in ings:
            if ing.flexible:
                flex_unique.setdefault(ing.id, ing)
            elif ing.optional and ing.sku:
                opt_unique.setdefault(ing.id, ing)

    if flex_unique or opt_unique:
        _show_resolve_dialog(
            session,
            dishes_with_ings,
            list(flex_unique.values()),
            list(opt_unique.values()),
            replacements=replacements,
        )
    else:
        asyncio.ensure_future(
            _finalize_aggregation(session, dishes_with_ings, {}, set(), replacements=replacements)
        )


async def _finalize_aggregation(
    session,
    dishes_with_ings: list[tuple[Dish, list]],
    flex_choice: dict[int, object],
    opt_excluded: set[int],
    replacements: dict | None = None,
) -> None:
    """Apply flexible/optional decisions, aggregate, and show the confirm dialog."""
    replacements = replacements or {}
    resolved: list[tuple[Dish, list]] = []
    for dish, ings in dishes_with_ings:
        eff: list = []
        for ing in ings:
            if ing.flexible:
                chosen = flex_choice.get(ing.id)
                if chosen is not None:
                    eff.append(
                        _EffIng(
                            sku=chosen.sku,
                            display_name=chosen.name,
                            amount=ing.amount,
                            amount_unit=ing.amount_unit,
                        )
                    )
            elif ing.optional:
                if ing.id not in opt_excluded:
                    eff.append(ing)
            elif ing.sku in replacements:
                sub = replacements[ing.sku]
                eff.append(
                    _EffIng(
                        sku=sub.sku,
                        display_name=sub.name,
                        amount=ing.amount,
                        amount_unit=ing.amount_unit,
                    )
                )
            else:
                eff.append(ing)
        resolved.append((dish, eff))

    sku_set = {e.sku for _, es in resolved for e in es if e.sku}
    sku_cache: dict[str, object] = {}
    async with AsyncSessionLocal() as db:
        for sku in sku_set:
            cached = await repo.get_ingredient_sku(db, session.user_id, sku)
            if cached:
                sku_cache[sku] = cached
        # Persist + cache any newly chosen flexible products so pack/price are known.
        from pyplus.services.dishes import cache_ingredient_sku_from_product

        for prod in flex_choice.values():
            if prod is not None and prod.sku and prod.sku not in sku_cache:
                await cache_ingredient_sku_from_product(db, session.user_id, prod)
                cached = await repo.get_ingredient_sku(db, session.user_id, prod.sku)
                if cached:
                    sku_cache[prod.sku] = cached

    agg = aggregate(resolved, sku_cache, include_optional=True)  # type: ignore[arg-type]
    if not agg.lines:
        ui.notify(
            "Geen ingrediënten gevonden — controleer de product-koppelingen in Gerechten",
            type="warning",
            position="top",
        )
        return

    _show_agg_dialog(session, agg)


def _show_unavail_resolve_dialog(
    session,
    dishes_with_ings: list[tuple[Dish, list]],
    unavail_skus: set[str],
    product_info: dict,
) -> None:
    """Show a dialog listing unavailable ingredients with Vervangen/Overslaan options."""
    from pyplus.services.categories import parse_categories

    unavail_ings: dict[str, dict] = {}
    for dish, ings in dishes_with_ings:
        for ing in ings:
            if ing.sku in unavail_skus and ing.sku not in unavail_ings:
                pc = product_info.get(ing.sku)
                unavail_ings[ing.sku] = {
                    "name": ing.display_name,
                    "sku": ing.sku,
                    "image": (pc.image_url if pc else "") or "",
                    "subtitle": (pc.subtitle if pc else "") or "",
                    "price": (pc.price if pc else 0.0) or 0.0,
                    "brand": (pc.brand if pc else "") or "",
                    "categories": parse_categories(pc.categories_json) if pc else [],
                }

    replacements: dict[str, object] = {}
    skipped: set[str] = set()

    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().style(
            "min-width:340px;max-width:480px;width:100%;padding:0;overflow:hidden"
        ):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label(t("substitute.unavail_title")).style(
                    "font-size:16px;font-weight:700;color:var(--c-text)"
                )
                ui.button(icon="sym_r_close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            with ui.element("div").style("padding:.5rem 1rem"):
                ui.label(t("substitute.unavail_body", n=len(unavail_ings))).style(
                    "font-size:13px;color:var(--c-text-3)"
                )

            with ui.element("div").style("padding:.5rem 1rem;max-height:50vh;overflow-y:auto"):

                @ui.refreshable
                def _unavail_list() -> None:
                    for sku, info in unavail_ings.items():
                        _render_unavail_row(
                            sku, info, replacements, skipped, session, _unavail_list
                        )

                _unavail_list()

            with ui.element("div").style(
                "display:flex;justify-content:flex-end;gap:.5rem;"
                "padding:.75rem 1rem;border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.cancel"), on_click=dlg.close).props("flat rounded no-caps")

                def _proceed() -> None:
                    dlg.close()
                    final_skipped = unavail_skus - set(replacements.keys()) - skipped
                    all_skipped = skipped | final_skipped
                    filtered = []
                    for dish, ings in dishes_with_ings:
                        kept = [i for i in ings if i.sku not in all_skipped]
                        filtered.append((dish, kept))
                    _continue_to_flex_optional(session, filtered, replacements)

                ui.button(
                    t("substitute.continue"),
                    icon="sym_r_arrow_forward",
                    on_click=_proceed,
                ).props("unelevated rounded color=primary no-caps").style("font-weight:600")


def _render_unavail_row(
    sku: str, info: dict, replacements: dict, skipped: set, session, refresh_fn
) -> None:
    replaced = sku in replacements
    is_skipped = sku in skipped

    with ui.element("div").style(
        "display:flex;align-items:center;gap:.5rem;padding:.5rem 0;"
        "border-bottom:1px solid var(--c-border)"
    ):
        if info["image"]:
            ui.image(thumbnail_url(info["image"], 36)).style(
                "width:36px;height:36px;border-radius:var(--r-sm);flex-shrink:0;"
                + ("opacity:.4;" if is_skipped else "")
            ).props(f'alt="{_alt(info["name"])}"')
        else:
            ui.element("div").style(
                "width:36px;height:36px;border-radius:var(--r-sm);"
                "background:var(--c-border);flex-shrink:0"
            )

        with ui.element("div").style("min-width:0;flex:1"):
            name_style = (
                "font-size:13px;color:var(--c-text-3);text-decoration:line-through"
                if is_skipped
                else "font-size:13px;font-weight:500;color:var(--c-text)"
            )
            ui.label(info["name"]).style(name_style)
            if replaced:
                sub = replacements[sku]
                ui.label(f"→ {sub.name}").style(
                    "font-size:11px;color:var(--c-brand-dark);font-weight:600"
                )
            elif not is_skipped:
                ui.label(t("status.unavailable")).style("font-size:11px;color:var(--c-danger)")

        with ui.element("div").style("display:flex;gap:.25rem;flex-shrink:0"):
            if not replaced and not is_skipped:
                from pyplus.ui.components.substitutes import show_substitute_dialog

                def _sub(s=sku, i=info):
                    def _on_pick(product):
                        replacements[s] = product
                        refresh_fn.refresh()

                    show_substitute_dialog(
                        session,
                        sku=s,
                        product_name=i["name"],
                        product_image=i["image"],
                        product_subtitle=i.get("subtitle", ""),
                        categories=i["categories"],
                        price=i["price"],
                        brand=i["brand"],
                        mode="cart",
                        on_select=_on_pick,
                    )

                ui.button(t("substitute.replace_btn"), on_click=_sub).props(
                    "flat dense no-caps size=sm color=primary"
                )

                def _skip(s=sku):
                    skipped.add(s)
                    refresh_fn.refresh()

                ui.button(t("substitute.skip"), on_click=_skip).props("flat dense no-caps size=sm")

            elif replaced:

                def _undo(s=sku):
                    replacements.pop(s, None)
                    refresh_fn.refresh()

                ui.button(icon="sym_r_undo", on_click=_undo).props(
                    "flat dense size=sm color=grey"
                ).tooltip("Ongedaan maken")

            elif is_skipped:

                def _unskip(s=sku):
                    skipped.discard(s)
                    refresh_fn.refresh()

                ui.button(icon="sym_r_undo", on_click=_unskip).props(
                    "flat dense size=sm color=grey"
                ).tooltip("Terugzetten")


def _show_resolve_dialog(
    session,
    dishes_with_ings,
    flexibles: list,
    optionals: list,
    replacements: dict | None = None,
) -> None:
    """Ask the user to pick a product for each flexible ingredient and to
    include/skip each optional one, before aggregating."""
    replacements = replacements or {}
    flex_choice: dict[int, object] = {}  # ing.id → chosen Product
    fstate: dict[int, dict] = {
        f.id: {"query": "", "results": [], "searching": False} for f in flexibles
    }
    opt_excluded: set[int] = set()  # optional ing.ids the user unticked

    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().style(
            "min-width:360px;max-width:520px;width:100%;padding:0;overflow:hidden"
        ):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:1rem 1.25rem .75rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label("Ingrediënten kiezen").style(
                    "font-size:17px;font-weight:700;color:var(--c-text);letter-spacing:-.2px"
                )
                ui.button(icon="sym_r_close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            with ui.scroll_area().style("max-height:62vh"):
                with ui.element("div").style("padding:.75rem 1rem"):
                    # ── Flexible ingredients ───────────────────────────────
                    if flexibles:
                        ui.label("Flexibele ingrediënten — kies een product").style(
                            "font-size:12px;font-weight:600;color:var(--c-text-2);"
                            "margin-bottom:.5rem;display:block"
                        )

                        @ui.refreshable
                        def _flex_list() -> None:
                            for f in flexibles:
                                _render_flex_picker(
                                    session, f, fstate[f.id], flex_choice, _flex_list
                                )

                        _flex_list()

                    # ── Optional ingredients ───────────────────────────────
                    if optionals:
                        ui.label("Optionele ingrediënten — vink aan wat mee moet").style(
                            "font-size:12px;font-weight:600;color:var(--c-text-2);"
                            "margin:.75rem 0 .5rem;display:block"
                        )
                        for o in optionals:
                            with ui.element("div").style(
                                "display:flex;align-items:center;gap:.5rem;padding:.25rem 0"
                            ):
                                cb = ui.checkbox(value=True).props("dense")

                                def _toggle(e, oid=o.id):
                                    if e.value:
                                        opt_excluded.discard(oid)
                                    else:
                                        opt_excluded.add(oid)

                                cb.on("update:model-value", _toggle)
                                ui.label(o.display_name).style(
                                    "font-size:13px;color:var(--c-text);flex:1"
                                )

            with ui.element("div").style(
                "display:flex;gap:.5rem;padding:.75rem 1rem;border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.cancel"), on_click=dlg.close).props(
                    "flat rounded no-caps"
                ).style("flex:1")

                async def _continue() -> None:
                    dlg.close()
                    await _finalize_aggregation(
                        session,
                        dishes_with_ings,
                        flex_choice,
                        opt_excluded,
                        replacements=replacements,
                    )

                ui.button(
                    "Doorgaan",
                    icon="sym_r_arrow_forward",
                    on_click=lambda: _continue(),
                ).props("unelevated rounded color=primary no-caps").style("flex:2;font-weight:600")


def _render_flex_picker(session, flex_ing, st: dict, flex_choice: dict, refresh_fn) -> None:
    """One flexible-ingredient row: its label + a product search/select."""
    chosen = flex_choice.get(flex_ing.id)
    with ui.element("div").style(
        "padding:.5rem .625rem;border:1px solid var(--c-border);border-radius:var(--r-md);"
        "margin-bottom:.5rem;background:var(--c-surface)"
    ):
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.375rem;margin-bottom:.375rem"
        ):
            ui.icon("sym_r_tune", size="15px").style("color:var(--c-brand-dark)")
            ui.label(flex_ing.display_name).style(
                "font-size:12px;font-weight:600;color:var(--c-text-2);flex:1;min-width:0"
            )

        if chosen is not None:
            with ui.element("div").style("display:flex;align-items:center;gap:.5rem"):
                if chosen.image_url:
                    ui.image(thumbnail_url(chosen.image_url, 32)).style(
                        "width:32px;height:32px;object-fit:contain;border-radius:4px;"
                        "background:var(--c-border);flex-shrink:0"
                    )
                ui.label(chosen.name).style(
                    "font-size:13px;color:var(--c-text);flex:1;min-width:0;"
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )

                def _clear(fid=flex_ing.id):
                    flex_choice.pop(fid, None)
                    refresh_fn.refresh()

                ui.button("Wijzigen", on_click=_clear).props(
                    "flat dense no-caps size=sm color=primary"
                ).style("font-size:12px")
            return

        # Search input + results. The input is kept alive and only the results
        # box below is redrawn per keystroke, so the field never loses focus.
        with ui.element("div").style("position:relative"):
            search_field = (
                ui.input(placeholder=t("dishes.ingredient_search"), value=st["query"])
                .props("outlined dense clearable")
                .style("width:100%")
            )
            results_box = ui.element("div")

            def _draw_results(s=st, box=results_box):
                box.clear()
                with box:
                    if s["searching"]:
                        ui.label("Zoeken…").style(
                            "padding:.375rem .5rem;font-size:12px;color:var(--c-text-3)"
                        )
                    elif s["results"]:
                        with ui.element("div").style(
                            "border:1px solid var(--c-border);border-radius:var(--r-md);"
                            "margin-top:.25rem;max-height:180px;overflow-y:auto"
                        ):
                            for prod in s["results"][:8]:

                                def _pick(p=prod, fid=flex_ing.id):
                                    flex_choice[fid] = p
                                    st["results"] = []
                                    st["query"] = ""
                                    refresh_fn.refresh()

                                with (
                                    ui.element("div")
                                    .style(
                                        "display:flex;align-items:center;gap:.5rem;"
                                        "padding:.375rem .5rem;cursor:pointer"
                                    )
                                    .on("click", _pick)
                                ):
                                    if prod.image_url:
                                        ui.image(thumbnail_url(prod.image_url, 28)).style(
                                            "width:28px;height:28px;object-fit:contain;"
                                            "border-radius:4px;background:var(--c-border);flex-shrink:0"
                                        ).props(f'alt="{_alt(prod.name)}"')
                                    ui.label(prod.name).style(
                                        "font-size:12px;flex:1;min-width:0;overflow:hidden;"
                                        "text-overflow:ellipsis;white-space:nowrap"
                                    )
                                    dot = (
                                        "var(--c-brand-dark)"
                                        if prod.is_available
                                        else "var(--c-danger)"
                                    )
                                    ui.element("div").style(
                                        f"width:6px;height:6px;border-radius:50%;"
                                        f"background:{dot};flex-shrink:0"
                                    )

            async def _on_search(e, s=st, field=search_field):
                # update:model-value carries no `.value` here — use the field's
                # synced value as the source of truth.
                s["query"] = (e.value if hasattr(e, "value") else field.value) or ""
                if len(s["query"].strip()) >= 2:
                    s["searching"] = True
                    _draw_results()
                    try:
                        from pyplus.services.search import search_products

                        s["results"] = await search_products(session, s["query"])
                    except Exception:
                        s["results"] = []
                    s["searching"] = False
                else:
                    s["results"] = []
                _draw_results()

            search_field.on("update:model-value", _on_search)
            _draw_results()


def _show_agg_dialog(session, agg: AggResult) -> None:
    overrides: set[str] = set()  # SKUs the user toggled to "per gerecht"

    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().style(
            "min-width:340px;max-width:500px;width:100%;padding:0;overflow:hidden"
        ):
            # Header
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:1rem 1.25rem .75rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label(t("agg.summary_title")).style(
                    "font-size:17px;font-weight:700;color:var(--c-text);letter-spacing:-.2px"
                )
                ui.button(icon="sym_r_close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            # Body
            with ui.scroll_area().style("max-height:62vh"):
                with ui.element("div").style("padding:.75rem 1rem"):
                    n_dishes = len({n for ln in agg.lines for n in ln.dish_names})
                    ui.label(f"{len(agg.lines)} ingrediënten · {n_dishes} gerechten").style(
                        "font-size:12px;color:var(--c-text-3);margin-bottom:.625rem;display:block"
                    )

                    @ui.refreshable
                    def _lines() -> None:
                        for line in agg.lines:
                            _render_agg_line(line, overrides, _lines)

                    _lines()

                    if agg.total_savings > 0.001:
                        with ui.element("div").style(
                            "display:flex;align-items:center;justify-content:flex-end;"
                            "gap:.375rem;margin-top:.75rem;padding:.5rem .625rem;"
                            "background:var(--c-brand-tint);border-radius:var(--r-md)"
                        ):
                            ui.icon("sym_r_savings", size="15px").style("color:var(--c-brand-dark)")
                            total_str = f"{agg.total_savings:.2f}".replace(".", ",")
                            ui.label(f"Totaal korting: € {total_str}").style(
                                "font-size:13px;font-weight:700;color:var(--c-brand-dark)"
                            )

            # Footer
            with ui.element("div").style(
                "display:flex;gap:.5rem;padding:.75rem 1rem;border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.cancel"), on_click=dlg.close).props(
                    "flat rounded no-caps"
                ).style("flex:1")
                ui.button(
                    t("agg.confirm"),
                    icon="sym_r_add_shopping_cart",
                    on_click=lambda: _confirm_add(session, agg, overrides, dlg),
                ).props("unelevated rounded color=primary no-caps").style("flex:2;font-weight:600")


def _render_agg_line(line: AggLine, overrides: set[str], refresh_fn) -> None:
    is_override = line.sku in overrides
    packs = line.packs_per_dish if is_override else line.packs_optimised

    with ui.element("div").style("padding:.5rem 0;border-bottom:1px solid var(--c-border)"):
        with ui.element("div").style("display:flex;align-items:center;gap:.5rem"):
            # Name + source dishes
            with ui.element("div").style("flex:1;min-width:0"):
                ui.label(line.display_name).style(
                    "font-size:13px;font-weight:600;color:var(--c-text)"
                )
                src = " · ".join(dict.fromkeys(line.dish_names))  # deduplicate, keep order
                ui.label(src).style("font-size:11px;color:var(--c-text-4);margin-top:1px")

            # Pack count badge
            badge_cls = (
                "sp-badge sp-badge-available"
                if line.has_saving and not is_override
                else "sp-badge sp-badge-stale"
                if is_override
                else "sp-badge"
            )
            with ui.element("div").classes(badge_cls).style("flex-shrink:0"):
                ui.label(f"{packs}×").style("font-size:12px")

        # Optimisation detail (only for lines that yield a saving)
        if line.has_saving:
            req = fmt_amount(line.required_amount, line.required_unit)
            n_src = len(line.dish_names)
            if not is_override:
                # Show the optimised suggestion
                lines_text = []
                if line.pack_price is not None:
                    opt_price = line.packs_optimised * line.pack_price
                    src_price = line.packs_per_dish * line.pack_price
                    pack_label = fmt_amount(line.pack_size_base or 0, line.pack_unit or "")
                    opt_str = f"€ {opt_price:.2f}".replace(".", ",")
                    src_str = f"€ {src_price:.2f}".replace(".", ",")
                    lines_text.append(
                        f"{n_src} gerechten × → {req} "
                        f"→ {line.packs_optimised}× {pack_label} ({opt_str}) "
                        f"i.p.v. {line.packs_per_dish}× ({src_str})"
                    )
                    sav_str = f"€ {line.savings:.2f}".replace(".", ",")
                    lines_text.append(f"bespaart {sav_str}")
                    if line.leftover_base > 0.01:
                        lft = fmt_amount(line.leftover_base, line.required_unit)
                        lines_text.append(f"{lft} over")
                else:
                    lines_text.append(
                        f"{n_src} gerechten → {req} "
                        f"→ {line.packs_optimised}× i.p.v. {line.packs_per_dish}×"
                    )

                with ui.element("div").style("margin-top:.25rem"):
                    ui.label(" · ".join(lines_text)).style(
                        "font-size:11px;color:var(--c-brand-dark);line-height:1.5"
                    )
                    ui.button(
                        t("agg.per_dish"),
                        on_click=lambda s=line.sku: _toggle_override(s, overrides, refresh_fn),
                    ).props("flat dense no-caps size=xs").style(
                        "font-size:11px;color:var(--c-text-3);padding:0 2px"
                    )
            else:
                # Per-dish mode active — show revert link
                with ui.element("div").style(
                    "margin-top:.25rem;display:flex;align-items:center;gap:.375rem"
                ):
                    ui.label("Per gerecht").style("font-size:11px;color:var(--c-text-3)")
                    ui.button(
                        "Terug naar geoptimaliseerd",
                        on_click=lambda s=line.sku: _toggle_override(s, overrides, refresh_fn),
                    ).props("flat dense no-caps size=xs color=primary").style(
                        "font-size:11px;padding:0 2px"
                    )


def _toggle_override(sku: str, overrides: set[str], refresh_fn) -> None:
    overrides.discard(sku) if sku in overrides else overrides.add(sku)
    refresh_fn.refresh()


async def _check_recommender_available(session, btn) -> None:
    """Show the Plan mijn week button only when ML is enabled + artifact exists."""
    try:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.ml.artifacts import load_artifact
        from pyplus.ml.interface import UserSettings

        async with AsyncSessionLocal() as db:
            settings_json = await repo.get_user_settings_json(db, session.user_id)
        try:
            settings = UserSettings.model_validate_json(settings_json)
        except Exception:
            settings = UserSettings()

        if not settings.ml_enabled or not settings.ml_recommender:
            return

        artifact = await load_artifact(session.user_id, "recommender")
        if artifact is not None:
            btn.set_visibility(True)
    except Exception as exc:
        log.debug("Recommender check failed: %s", exc)


async def _plan_week(session, state: "_MealsState", refresh_fn) -> None:
    """Fill empty slots using the recommender artifact."""
    try:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.ml.artifacts import load_artifact, recompute_recommender
        from pyplus.ml.recommender import plan_week

        await recompute_recommender(session.user_id)
        artifact = await load_artifact(session.user_id, "recommender")
        if artifact is None:
            ui.notify(
                "Geen suggesties beschikbaar — herbereken via Instellingen",
                type="info",
                position="top",
            )
            return

        async with AsyncSessionLocal() as db:
            dishes = await repo.get_dishes(db, session.user_id)

        current = {slot: (dish.id if dish else None) for slot, dish in state.slots.items()}
        suggestions = plan_week(
            artifact, [d.id for d in dishes], current, settings=session.settings, n_lunch=0
        )

        if not suggestions:
            ui.notify("Alle slots zijn al gevuld", type="info", position="top")
            return

        # Save suggestions to DB and update state
        dish_by_id = {d.id: d for d in dishes}
        async with AsyncSessionLocal() as db:
            for slot, dish_id in suggestions.items():
                await repo.set_weekmenu_slot(db, session.user_id, slot, state.week_start, dish_id)
                state.slots[slot] = dish_by_id.get(dish_id)

        refresh_fn.refresh()
        n = len(suggestions)
        ui.notify(
            f"{n} {'slot' if n == 1 else 'slots'} ingevuld",
            type="positive",
            position="top",
            timeout=2000,
        )
    except Exception as exc:
        log.warning("Plan week failed: %s", exc)
        ui.notify("Kan weekmenu niet plannen", type="warning", position="top")


def render_ical_subscription_body(user_id: int) -> None:
    """Render the iCal subscription URL widget (inline, no dialog wrapper).

    Shared between the meals lane dialog and the settings page.
    """
    from pyplus.security.tokens import make_ical_token

    token = make_ical_token(user_id)

    if token is None:
        with ui.element("div").style(
            "display:flex;align-items:flex-start;gap:.5rem;padding:.625rem .75rem;"
            "background:var(--c-warning-tint);border-radius:var(--r-md);border:1px solid var(--c-warning-border)"
        ):
            ui.icon("sym_r_warning", size="16px").style(
                "color:var(--c-warning-text);flex-shrink:0;margin-top:1px"
            )
            ui.label(
                "Geen PYPLUS_SECRET_KEY ingesteld. Stel deze in om abonneer-links te activeren."
            ).style("font-size:13px;color:var(--c-warning-text);line-height:1.5")
        return

    ui.label("Deze URL toevoegen aan je agenda-app:").style(
        "font-size:13px;font-weight:600;color:var(--c-text);margin-bottom:.5rem;display:block"
    )

    from pyplus.config import settings as app_settings

    path = f"/menu.ics?uid={user_id}&token={token}"

    # If a public base URL is configured, build the link server-side immediately.
    base = (app_settings.base_url or "").rstrip("/")
    initial = f"{base}{path}" if base else ""

    with ui.element("div").style(
        "display:flex;align-items:center;gap:.375rem;margin-bottom:.75rem"
    ):
        url_display = (
            ui.input(value=initial)
            .props("outlined dense readonly")
            .classes("ical-url-field")
            .style("flex:1;font-size:12px")
        )
        # The copy must happen inside the tap gesture (iOS Safari blocks
        # clipboard writes that come back via a server round-trip), so it runs as
        # a client-side js_handler with an execCommand fallback for non-HTTPS. The
        # Python handler only shows the confirmation toast.
        copy_btn = (
            ui.button(icon="sym_r_content_copy")
            .props("flat round dense size=sm color=primary")
            .tooltip("URL kopiëren")
        )
        copy_btn.on(
            "click",
            handler=lambda: ui.notify(
                "URL gekopieerd", type="positive", position="top", timeout=1500
            ),
            js_handler=_COPY_JS,
        )

    async def _set_url() -> None:
        # No configured base URL → resolve the origin from the live page. Deferred
        # via a timer so the client connection is ready when run_javascript fires.
        try:
            origin = await ui.run_javascript("window.location.origin", timeout=5.0)
        except Exception:
            origin = ""
        if origin:
            url_display.set_value(f"{origin}{path}")

    if not initial:
        ui.timer(0.2, _set_url, once=True)

    ui.label(
        "iOS: Agenda → Accounts → Voeg account toe → Andere → Agenda-abonnement\n"
        "Android: Google Agenda → Andere agenda → Via URL"
    ).style(
        "font-size:11px;color:var(--c-text-3);line-height:1.5;white-space:pre-line;display:block"
    )


async def _show_ical_dialog(session, week_start: datetime.date) -> None:
    """Show the iCal subscription URL dialog + one-off download option."""
    with ui.dialog(value=True) as dlg:
        with ui.card().style("max-width:460px;width:100%;padding:0;overflow:hidden"):
            # Header
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;"
                "padding:.875rem 1rem .625rem;border-bottom:1px solid var(--c-border)"
            ):
                ui.label("Agenda-abonnement").style(
                    "font-size:16px;font-weight:700;color:var(--c-text)"
                )
                ui.button(icon="sym_r_close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            with ui.element("div").style("padding:1rem"):
                render_ical_subscription_body(session.user_id)

                # One-off download
                ui.separator().style("margin:.75rem 0 .5rem")
                ui.label("Of download eenmalig:").style(
                    "font-size:12px;color:var(--c-text-3);margin-bottom:.375rem;display:block"
                )
                ui.button(
                    f"Download .ics (week {week_start.strftime('%-d %b')})",
                    icon="sym_r_download",
                    on_click=lambda ws=week_start, uid=session.user_id: _one_off_download(uid, ws),
                ).props("flat rounded no-caps color=primary size=sm").style("font-size:12px")

            # Footer
            with ui.element("div").style(
                "display:flex;justify-content:flex-end;padding:.625rem 1rem;"
                "border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.close"), on_click=dlg.close).props(
                    "flat rounded no-caps color=grey"
                )


# Client-side copy: reads the URL straight from the input and copies within the
# tap gesture. Prefers the async Clipboard API (HTTPS), falls back to a hidden
# textarea + execCommand for non-secure contexts / older iOS Safari.
_COPY_JS = """() => {
    const field = document.querySelector('.ical-url-field input');
    const text = field ? field.value : '';
    if (!text) return;
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
    } else {
        fallbackCopy(text);
    }
    function fallbackCopy(t) {
        const ta = document.createElement('textarea');
        ta.value = t;
        ta.contentEditable = true;
        ta.readOnly = false;
        ta.style.position = 'fixed';
        ta.style.top = '0';
        ta.style.left = '0';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        const range = document.createRange();
        range.selectNodeContents(ta);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        ta.setSelectionRange(0, t.length);
        try { document.execCommand('copy'); } catch (e) {}
        sel.removeAllRanges();
        document.body.removeChild(ta);
    }
}"""


async def _one_off_download(user_id: int, week_start: datetime.date) -> None:
    from pyplus.services.exports import build_ical

    try:
        ical_bytes = await build_ical(user_id, week_start)
        filename = f"pyplus-week-{week_start.isoformat()}.ics"
        ui.download(ical_bytes, filename, media_type="text/calendar")
    except Exception as exc:
        log.warning("iCal download failed: %s", exc)
        ui.notify("Download mislukt", type="warning", position="top")


async def _confirm_add(session, agg: AggResult, overrides: set[str], dlg) -> None:
    cart_service = getattr(session, "cart_service", None)
    if not cart_service:
        ui.notify(t("error.cart_add_failed"), type="warning")
        dlg.close()
        return

    dlg.close()

    for line in agg.lines:
        qty = line.packs_to_add(overrides)
        if qty > 0:
            await cart_service.add(
                line.sku,
                qty,
                product_name=line.display_name,
                product_unit=line.pack_unit or "",
                product_price=line.pack_price or 0.0,
                product_image="",
                source="menu",
            )
