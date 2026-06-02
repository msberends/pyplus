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

log = logging.getLogger(__name__)

_DINNER_SLOTS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
_LUNCH_SLOTS = ["lunch1", "lunch2", "lunch3", "lunch4", "lunch5"]
_ALL_SLOTS = _DINNER_SLOTS + _LUNCH_SLOTS

_DAY_LABEL = {
    "ma": "Ma",
    "di": "Di",
    "wo": "Wo",
    "do": "Do",
    "vr": "Vr",
    "za": "Za",
    "zo": "Zo",
    "lunch1": "1",
    "lunch2": "2",
    "lunch3": "3",
    "lunch4": "4",
    "lunch5": "5",
}
_MONTHS_NL = {
    1: "jan",
    2: "feb",
    3: "mrt",
    4: "apr",
    5: "mei",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "okt",
    11: "nov",
    12: "dec",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _current_monday() -> datetime.date:
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


def _format_week(week_start: datetime.date) -> str:
    week_end = week_start + datetime.timedelta(days=6)
    wn = week_start.isocalendar()[1]
    ms = _MONTHS_NL[week_start.month]
    if week_start.month == week_end.month:
        return f"Week {wn} · {week_start.day}–{week_end.day} {ms}"
    me = _MONTHS_NL[week_end.month]
    return f"Week {wn} · {week_start.day} {ms}–{week_end.day} {me}"


def _slot_date(slot: str, week_start: datetime.date) -> datetime.date | None:
    if slot in _DINNER_SLOTS:
        return week_start + datetime.timedelta(days=_DINNER_SLOTS.index(slot))
    return None


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
        await _load_slots(state, session.user_id)
    except Exception as exc:
        log.error("Meals lane load failed: %s", exc)
        load_error = "Weekmenu kon niet worden geladen."

    with ui.element("div").classes("sp-lane"):
        # ── Header ────────────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-header"):
            with ui.element("div").style(
                "display:flex;align-items:center;justify-content:space-between;gap:.5rem"
            ):
                ui.label(t("lane.meals.title")).classes("sp-lane-title")
                if not load_error:
                    with ui.element("div").style("display:flex;align-items:center;gap:0px"):
                        ui.button(
                            icon="chevron_left",
                            on_click=lambda: asyncio.ensure_future(
                                _navigate(session.user_id, state, -1, week_lbl, _render)
                            ),
                        ).props("flat round dense size=sm color=grey-6")
                        week_lbl = ui.label(_format_week(state.week_start)).style(
                            "font-size:11px;color:var(--c-text-3);font-weight:500;"
                            "white-space:nowrap;min-width:130px;text-align:center"
                        )
                        ui.button(
                            icon="chevron_right",
                            on_click=lambda: asyncio.ensure_future(
                                _navigate(session.user_id, state, +1, week_lbl, _render)
                            ),
                        ).props("flat round dense size=sm color=grey-6")
                        plan_btn = (
                            ui.button(
                                icon="auto_awesome",
                                on_click=lambda: asyncio.ensure_future(
                                    _plan_week(session, state, _render)
                                ),
                            )
                            .props("flat round dense size=sm color=primary")
                            .tooltip(t("lane.meals.plan_week"))
                        )
                        plan_btn.set_visibility(False)
                        asyncio.ensure_future(_check_recommender_available(session, plan_btn))
                        ui.button(
                            icon="event",
                            on_click=lambda: asyncio.ensure_future(
                                _show_ical_dialog(session, state.week_start)
                            ),
                        ).props("flat round dense size=sm color=grey-6").tooltip(
                            "Agenda-abonnement"
                        )
            ui.label(t("lane.meals.subtitle")).classes("sp-lane-subtitle")

        # ── Body: slot grid ────────────────────────────────────────────────
        with ui.element("div").classes("sp-lane-body sp-meals-body"):
            if load_error:
                with ui.element("div").classes("sp-lane-error"):
                    ui.icon("error_outline", size="24px").style("color:var(--c-danger);opacity:.6")
                    ui.label(load_error).style("font-size:13px;color:var(--c-text-3)")
                return

            @ui.refreshable
            def _render() -> None:
                _render_all_slots(session, state, _render)

            _render()

            # ── Add-to-cart button ─────────────────────────────────────────
            ui.separator().style("margin:.5rem 0")
            ui.button(
                t("lane.meals.add_all"),
                icon="add_shopping_cart",
                on_click=lambda: asyncio.ensure_future(_add_weekmenu_to_cart(session, state)),
            ).props("unelevated rounded color=primary no-caps").style(
                "width:100%;font-size:13px;font-weight:600;height:40px"
            )


# ── Slot rendering ─────────────────────────────────────────────────────────────


def _render_all_slots(session, state: _MealsState, refresh_fn) -> None:
    options = {d.id: d.name for d in state.dishes}

    _section_header(t("lane.meals.dinner"))
    for slot in _DINNER_SLOTS:
        d = _slot_date(slot, state.week_start)
        date_str = f"{d.day} {_MONTHS_NL[d.month]}" if d else ""
        _slot_row(slot, _DAY_LABEL[slot], date_str, state, options, session, refresh_fn)

    ui.element("div").style("height:.375rem")
    _section_header(t("lane.meals.lunch"))
    for slot in _LUNCH_SLOTS:
        _slot_row(slot, _DAY_LABEL[slot], "", state, options, session, refresh_fn)


def _section_header(label: str) -> None:
    ui.label(label).style(
        "font-size:10px;font-weight:700;color:var(--c-text-4);"
        "letter-spacing:.10em;text-transform:uppercase;"
        "margin:.25rem 0 .2rem;display:block"
    )


def _slot_row(slot, day_label, date_str, state, options, session, refresh_fn) -> None:
    dish = state.slots.get(slot)
    with ui.element("div").classes("sp-meals-slot"):
        # Day badge
        with ui.element("div").classes("sp-meals-day"):
            ui.label(day_label).style(
                "font-size:11px;font-weight:700;line-height:1;color:var(--c-text-2)"
            )
            if date_str:
                ui.label(date_str).style(
                    "font-size:9px;color:var(--c-text-4);line-height:1;margin-top:1px"
                )

        # Content
        if dish is None:
            with ui.element("div").style("flex:1;min-width:0"):
                ui.select(
                    options,
                    value=None,
                    with_input=True,
                    label=t("lane.meals.empty_slot"),
                    on_change=lambda e, s=slot: asyncio.ensure_future(
                        _pick_dish(session.user_id, s, e.value, state, refresh_fn)
                    ),
                ).props("outlined dense options-dense").classes("sp-meals-picker")
        else:
            _filled_chip(slot, dish, state, session, refresh_fn)


def _filled_chip(slot, dish, state, session, refresh_fn) -> None:
    with ui.element("div").classes("sp-meals-chip"):
        ui.label(dish.name).style(
            "font-size:13px;font-weight:600;color:var(--c-text);flex:1;"
            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0"
        )
        with ui.element("div").style("display:flex;gap:1px;flex-shrink:0"):
            ui.button(
                icon="swap_horiz",
                on_click=lambda s=slot: asyncio.ensure_future(
                    _clear_slot(session.user_id, s, state, refresh_fn)
                ),
            ).props("flat round dense size=xs color=grey-6").tooltip(t("lane.meals.swap"))
            ui.button(
                icon="close",
                on_click=lambda s=slot: asyncio.ensure_future(
                    _clear_slot(session.user_id, s, state, refresh_fn)
                ),
            ).props("flat round dense size=xs color=grey-6").tooltip(t("lane.meals.clear"))
            if dish.prep_notes:
                ui.button(
                    icon="menu_book",
                    on_click=lambda d=dish: _show_prep_notes(d),
                ).props("flat round dense size=xs color=grey-6").tooltip(t("lane.meals.view_prep"))


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
                ui.button(icon="close", on_click=dlg.close).props(
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
    refresh_fn,
) -> None:
    state.week_start += datetime.timedelta(weeks=delta_weeks)
    await _load_slots(state, user_id)
    week_lbl.set_text(_format_week(state.week_start))
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


# ── Aggregation + cart add ─────────────────────────────────────────────────────


async def _add_weekmenu_to_cart(session, state: _MealsState) -> None:
    """Compute aggregation for all filled slots and show the confirmation dialog."""
    filled = [(slot, dish) for slot, dish in state.slots.items() if dish is not None]
    if not filled:
        ui.notify("Geen gerechten geselecteerd", type="info", position="top")
        return

    # Load ingredients + SKU facts from DB.
    dishes_with_ings: list[tuple[Dish, list]] = []
    sku_set: set[str] = set()

    async with AsyncSessionLocal() as db:
        seen_dish_ids: set[int] = set()
        for _, dish in filled:
            if dish.id in seen_dish_ids:
                # Dish appears in multiple slots — still aggregate double quantity.
                ings = await repo.get_ingredients(db, dish.id)
                dishes_with_ings.append((dish, ings))
            else:
                seen_dish_ids.add(dish.id)
                ings = await repo.get_ingredients(db, dish.id)
                dishes_with_ings.append((dish, ings))
            sku_set.update(ing.sku for ing in ings if ing.sku)

        sku_cache: dict[str, object] = {}
        for sku in sku_set:
            cached = await repo.get_ingredient_sku(db, session.user_id, sku)
            if cached:
                sku_cache[sku] = cached

    agg = aggregate(dishes_with_ings, sku_cache)  # type: ignore[arg-type]

    if not agg.lines:
        ui.notify(
            "Geen ingrediënten gevonden — controleer de product-koppelingen in Gerechten",
            type="warning",
            position="top",
        )
        return

    _show_agg_dialog(session, agg)


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
                ui.button(icon="close", on_click=dlg.close).props(
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
                            ui.icon("savings", size="15px").style("color:var(--c-brand-dark)")
                            total_str = f"{agg.total_savings:.2f}".replace(".", ",")
                            ui.label(f"Totaal bespaard: € {total_str}").style(
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
                    icon="add_shopping_cart",
                    on_click=lambda: asyncio.ensure_future(
                        _confirm_add(session, agg, overrides, dlg)
                    ),
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
        from pyplus.ml.artifacts import load_artifact
        from pyplus.ml.recommender import plan_week

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
        suggestions = plan_week(artifact, [d.id for d in dishes], current)

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


async def _show_ical_dialog(session, week_start: datetime.date) -> None:
    """Show the iCal subscription URL dialog + one-off download option."""
    from pyplus.security.tokens import make_ical_token

    token = make_ical_token(session.user_id)

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
                ui.button(icon="close", on_click=dlg.close).props(
                    "flat round dense size=sm color=grey"
                )

            with ui.element("div").style("padding:1rem"):
                if token is None:
                    # Secret key not configured
                    with ui.element("div").style(
                        "display:flex;align-items:flex-start;gap:.5rem;padding:.625rem .75rem;"
                        "background:#fffbeb;border-radius:var(--r-md);border:1px solid #fde68a"
                    ):
                        ui.icon("warning", size="16px").style(
                            "color:#92400e;flex-shrink:0;margin-top:1px"
                        )
                        ui.label(
                            "Geen PYPLUS_SECRET_KEY ingesteld. "
                            "Stel deze in om abonneer-links te activeren."
                        ).style("font-size:13px;color:#92400e;line-height:1.5")
                else:
                    ui.label("Voeg deze URL toe aan je agenda-app:").style(
                        "font-size:13px;font-weight:600;color:var(--c-text);margin-bottom:.5rem;display:block"
                    )

                    # URL display + copy
                    url_box = ui.element("div").style(
                        "display:flex;align-items:center;gap:.375rem;margin-bottom:.75rem"
                    )
                    with url_box:
                        url_display = (
                            ui.input()
                            .props("outlined dense readonly")
                            .style("flex:1;font-size:12px")
                        )
                        ui.button(
                            icon="content_copy",
                            on_click=lambda: asyncio.ensure_future(
                                _copy_ical_url(url_display.value)
                            ),
                        ).props("flat round dense size=sm color=primary").tooltip("Kopieer URL")

                    # Fill in URL using JS to get the current origin
                    async def _set_url() -> None:
                        origin = await ui.run_javascript("window.location.origin")
                        url = f"{origin}/menu.ics?uid={session.user_id}&token={token}"
                        url_display.set_value(url)

                    asyncio.ensure_future(_set_url())

                    ui.label(
                        "iOS: Agenda → Accounts → Voeg account toe → Andere → Agenda-abonnement\n"
                        "Android: Google Agenda → Andere agenda → Via URL"
                    ).style(
                        "font-size:11px;color:var(--c-text-3);line-height:1.5;"
                        "white-space:pre-line;margin-bottom:.75rem;display:block"
                    )

                    ui.separator()

                # One-off download always available
                with ui.element("div").style("margin-top:.75rem"):
                    ui.label("Of download eenmalig:").style(
                        "font-size:12px;color:var(--c-text-3);margin-bottom:.375rem;display:block"
                    )
                    ui.button(
                        f"Download .ics (week {week_start.strftime('%-d %b')})",
                        icon="download",
                        on_click=lambda ws=week_start, uid=session.user_id: asyncio.ensure_future(
                            _one_off_download(uid, ws)
                        ),
                    ).props("flat rounded no-caps color=primary size=sm").style("font-size:12px")

            # Footer
            with ui.element("div").style(
                "display:flex;justify-content:flex-end;padding:.625rem 1rem;"
                "border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.close"), on_click=dlg.close).props(
                    "flat rounded no-caps color=grey"
                )


async def _copy_ical_url(url: str) -> None:
    import json as _json

    try:
        await ui.run_javascript(f"navigator.clipboard.writeText({_json.dumps(url)})")
        ui.notify("URL gekopieerd", type="positive", position="top", timeout=2000)
    except Exception:
        ui.notify("Kopiëren niet gelukt", type="warning", position="top")


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
            )
