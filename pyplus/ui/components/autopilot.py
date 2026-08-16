"""Autopilot page — plan review, substitute resolution, confirm + rollback."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging

from nicegui import ui

from pyplus.i18n import t
from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url

log = logging.getLogger(__name__)

_ICON = "sym_r_robot_2"

_NORM_UNITS = {"g": ("kg", 1000), "ml": ("l", 1000), "cl": ("l", 100)}


def _unit_price_label(price: float, subtitle: str) -> str:
    if price <= 0 or not subtitle:
        return ""
    from pyplus.services.dishes import _parse_pack_from_subtitle

    size, unit = _parse_pack_from_subtitle(subtitle)
    if not size or not unit or size <= 0:
        return ""

    def fmt(v: float) -> str:
        return f"€ {v:.2f}".replace(".", ",")

    if unit in ("stuks", "stuk"):
        if size == 1:
            return ""
        return f"{fmt(price / size)} / stuk"
    norm_unit, factor = _NORM_UNITS.get(unit, (unit, 1))
    size_norm = size / factor
    per_norm = price / size_norm if size_norm > 0 else 0
    if norm_unit == "kg" and per_norm > 20:
        per_100 = price / (size / 100) if unit == "g" else 0
        if per_100 > 0:
            return f"{fmt(per_100)} / 100 g"
    if norm_unit == "l" and per_norm > 10:
        per_100 = (
            price / (size / 100) if unit == "ml" else price / (size / 10) if unit == "cl" else 0
        )
        if per_100 > 0:
            return f"{fmt(per_100)} / 100 ml"
    return f"{fmt(per_norm)} / {norm_unit}"


_WEIGHT_UNITS = {"g", "kg"}
_VOLUME_UNITS = {"ml", "cl", "l", "liter"}


def _unit_price_pair(
    new_price: float,
    new_subtitle: str,
    orig_price: float,
    orig_subtitle: str,
) -> tuple[str, str]:
    """Format unit prices for a pair of products using a shared unit for comparison."""
    from pyplus.services.dishes import _parse_pack_from_subtitle

    new_size, new_unit = _parse_pack_from_subtitle(new_subtitle)
    orig_size, orig_unit = _parse_pack_from_subtitle(orig_subtitle)

    if (
        not new_size
        or not new_unit
        or not orig_size
        or not orig_unit
        or new_price <= 0
        or orig_price <= 0
    ):
        return _unit_price_label(new_price, new_subtitle), _unit_price_label(
            orig_price, orig_subtitle
        )

    def fmt(v: float) -> str:
        return f"€ {v:.2f}".replace(".", ",")

    both_weight = new_unit in _WEIGHT_UNITS and orig_unit in _WEIGHT_UNITS
    both_volume = new_unit in _VOLUME_UNITS and orig_unit in _VOLUME_UNITS

    if not both_weight and not both_volume:
        return _unit_price_label(new_price, new_subtitle), _unit_price_label(
            orig_price, orig_subtitle
        )

    new_norm = _NORM_UNITS.get(new_unit, (new_unit, 1))
    orig_norm = _NORM_UNITS.get(orig_unit, (orig_unit, 1))
    new_size_norm = new_size / new_norm[1]
    orig_size_norm = orig_size / orig_norm[1]

    new_per_norm = new_price / new_size_norm if new_size_norm > 0 else 0
    orig_per_norm = orig_price / orig_size_norm if orig_size_norm > 0 else 0

    if both_weight:
        if new_per_norm > 20 or orig_per_norm > 20:
            new_per_100 = new_price / (new_size / 100) if new_size > 0 else 0
            orig_per_100 = orig_price / (orig_size / 100) if orig_size > 0 else 0
            if new_per_100 > 0 and orig_per_100 > 0:
                return f"{fmt(new_per_100)} / 100 g", f"{fmt(orig_per_100)} / 100 g"
        return f"{fmt(new_per_norm)} / kg", f"{fmt(orig_per_norm)} / kg"

    if new_per_norm > 10 or orig_per_norm > 10:

        def _to_ml(size: float, unit: str) -> float:
            if unit == "ml":
                return size
            if unit == "cl":
                return size * 10
            if unit in ("l", "liter"):
                return size * 1000
            return size

        new_ml = _to_ml(new_size, new_unit)
        orig_ml = _to_ml(orig_size, orig_unit)
        new_per_100 = new_price / (new_ml / 100) if new_ml > 0 else 0
        orig_per_100 = orig_price / (orig_ml / 100) if orig_ml > 0 else 0
        if new_per_100 > 0 and orig_per_100 > 0:
            return f"{fmt(new_per_100)} / 100 ml", f"{fmt(orig_per_100)} / 100 ml"
    return f"{fmt(new_per_norm)} / l", f"{fmt(orig_per_norm)} / l"


def _eur(amount: float) -> str:
    """Format amount as Dutch euro string: '€ 1,23'."""
    return f"€ {amount:.2f}".replace(".", ",")


_SOURCE_SECTIONS = [
    ("autopilot:menu", "autopilot.section.weekmenu", "sym_r_calendar_month"),
    ("autopilot:staple", "autopilot.section.staples", "sym_r_shopping_basket"),
    ("autopilot:promo", "autopilot.section.promo_swaps", "sym_r_sell"),
    ("autopilot:filler", "autopilot.section.fillers", "sym_r_local_shipping"),
]


# ── Public entry point ──────────────────────────────────────────────────────


async def create_autopilot_lane(session) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ml.interface import UserSettings

    user_id = session.user_id

    async with AsyncSessionLocal() as db:
        settings_json = await repo.get_user_settings_json(db, user_id)
    try:
        settings = UserSettings.model_validate_json(settings_json)
    except Exception:
        settings = UserSettings()

    with ui.element("div").classes("sp-lane"):
        with ui.element("div").classes("sp-lane-header"):
            with ui.element("div").style("display:flex;align-items:center;gap:.5rem"):
                ui.icon(_ICON, size="24px").style("color:var(--c-accent)")
                ui.label(t("autopilot.title")).classes("sp-lane-title")

        with ui.element("div").classes("sp-lane-body") as body:
            if not settings.ml_enabled:
                _render_disabled(t("autopilot.no_ml"))
                return
            if not settings.ml_autopilot:
                _render_disabled(t("autopilot.not_enabled"))
                return

            await _render_plan_view(body, session, user_id, settings)


# ── Disabled / empty states ─────────────────────────────────────────────────


def _render_disabled(message: str) -> None:
    with ui.element("div").classes("sp-lane-placeholder"):
        ui.icon(_ICON).classes("sp-lane-placeholder-icon")
        ui.label(message).style(
            "font-size:13px;color:var(--c-text-3);text-align:center;max-width:320px"
        )
        ui.button(
            t("nav.settings"),
            on_click=lambda: ui.navigate.to("/settings"),
        ).props("flat size=sm").style("color:var(--c-accent)")


def _render_no_plan(session, user_id: int, settings, body) -> None:
    with ui.element("div").classes("sp-lane-placeholder"):
        ui.icon(_ICON).classes("sp-lane-placeholder-icon")
        ui.label(t("autopilot.no_plan")).style(
            "font-size:13px;color:var(--c-text-3);text-align:center"
        )
        ui.label(t("autopilot.no_plan_hint_generate")).style(
            "font-size:12px;color:var(--c-text-3);text-align:center;margin-top:2px"
        )

    spinner_slot = ui.element("div")

    async def _generate() -> None:
        spinner_slot.clear()
        with spinner_slot:
            with ui.element("div").style(
                "display:flex;align-items:center;gap:.5rem;justify-content:center;padding:1rem"
            ):
                ui.spinner(size="sm", color="deep-purple")
                ui.label(t("autopilot.generating")).style("font-size:13px;color:var(--c-text-3)")

        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.services.autopilot import AutopilotResult, PlanSummary, prepare_menu_only

        menu = await prepare_menu_only(user_id, store_number=session.store_number)
        preview = AutopilotResult(items=[], summary=PlanSummary(), menu_assignments=menu)

        today = datetime.date.today()
        next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
        async with AsyncSessionLocal() as db:
            await repo.upsert_autopilot_plan(
                db,
                user_id,
                next_monday,
                preview.to_json(),
                status="menu_preview",
            )

        ui.navigate.to("/autopilot")

    ui.button(
        t("autopilot.generate"),
        icon=_ICON,
        on_click=_generate,
    ).props("unelevated dense no-caps size=sm color=deep-purple").style(
        "font-size:12px;font-weight:600;align-self:center"
    )


# ── Plan view router ────────────────────────────────────────────────────────


async def _render_plan_view(body, session, user_id: int, settings) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    today = datetime.date.today()
    next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
    week_start = next_monday

    async with AsyncSessionLocal() as db:
        plan = await repo.get_autopilot_plan(db, user_id, week_start)

    if plan is None or plan.status == "expired":
        _render_no_plan(session, user_id, settings, body)
        return

    from pyplus.services.autopilot import AutopilotResult

    try:
        result = AutopilotResult.from_json(plan.plan_json)
    except Exception:
        _render_no_plan(session, user_id, settings, body)
        return

    if plan.status == "menu_preview":
        await _render_menu_preview(plan, result, session, user_id, settings, body)
        return

    if plan.status == "confirmed":
        if session.cart.total_items == 0:
            async with AsyncSessionLocal() as db:
                await repo.update_autopilot_plan_status(db, plan.id, "expired")
            _render_no_plan(session, user_id, settings, body)
            return
        _render_confirmed(plan, result, session, user_id, body)
        return

    if plan.status == "rolled_back":
        _render_status_badge(t("autopilot.status_rolled_back"), "var(--c-text-3)")
        _render_no_plan(session, user_id, settings, body)
        return

    # ── Draft plan — full review UI ──────────────────────────────────
    await _render_draft(plan, result, session, user_id, body, settings)


# ── Menu preview (interactive weekmenu confirmation) ───────────────────────


_SLOT_DAY_OFFSET = {
    "ma": 0,
    "di": 1,
    "wo": 2,
    "do": 3,
    "vr": 4,
    "za": 5,
    "zo": 6,
}


def _render_slot_row(slot, week_start, options, confirmed_menu, option_slot) -> None:
    offset = _SLOT_DAY_OFFSET.get(slot)
    if offset is not None:
        d = week_start + datetime.timedelta(days=offset)
        day_text = f"{_DAY_FULL.get(slot, slot)} {d.day} {_MONTHS_NL[d.month]}"
    else:
        day_text = _EXTRA_LABEL.get(slot.replace("lunch", "extra "), slot)

    with ui.element("div").style("display:flex;align-items:center;gap:.5rem;min-width:0"):
        ui.label(day_text).style(
            "font-size:12px;font-weight:600;color:var(--c-text-2);flex-shrink:0;min-width:140px"
        )
        picker = (
            ui.select(
                options,
                value=confirmed_menu.get(slot),
                with_input=True,
                clearable=True,
                on_change=lambda e, s=slot: confirmed_menu.__setitem__(s, e.value),
            )
            .props("outlined dense options-dense borderless")
            .style("flex:1;min-width:0")
        )
        picker.add_slot("option", option_slot)


async def _render_menu_preview(plan, result, session, user_id: int, settings, body) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.ui.components.meals import (
        _DINNER_SLOTS,
        _EXTRA_SLOTS,
        _PICKER_OPTION_SLOT,
        _WEEKEND_SLOTS,
    )

    today = datetime.date.today()
    next_monday = today + datetime.timedelta(days=(7 - today.weekday()))

    async with AsyncSessionLocal() as db:
        user_dishes = await repo.get_dishes(db, user_id)

    options = {d.id: d.name for d in user_dishes}
    suggested = result.menu_assignments or {}
    confirmed_menu: dict[str, int | None] = {}

    all_slots = _DINNER_SLOTS + _WEEKEND_SLOTS + _EXTRA_SLOTS
    for slot in all_slots:
        dish_id = suggested.get(slot)
        confirmed_menu[slot] = dish_id if dish_id and dish_id in options else None

    with ui.element("div").style(
        "display:flex;align-items:flex-start;gap:.5rem;padding:.625rem .75rem;"
        "background:var(--c-accent-tint);border-radius:var(--r-md);"
        "border:1px solid var(--c-accent-border);margin-bottom:.75rem"
    ):
        ui.icon(_ICON, size="16px").style("color:var(--c-accent);flex-shrink:0;margin-top:1px")
        ui.label(t("autopilot.menu_preview_info")).style(
            "font-size:12px;color:var(--c-accent);line-height:1.55"
        )

    spinner_slot = ui.element("div")

    async def _confirm_menu() -> None:
        spinner_slot.clear()
        with spinner_slot:
            with ui.element("div").style(
                "display:flex;align-items:center;gap:.5rem;justify-content:center;padding:1rem"
            ):
                ui.spinner(size="sm", color="deep-purple")
                ui.label(t("autopilot.generating")).style("font-size:13px;color:var(--c-text-3)")

        from pyplus.services.autopilot import prepare_plan

        fixed = {s: d for s, d in confirmed_menu.items() if d is not None}
        full_result = await prepare_plan(
            user_id, store_number=session.store_number, fixed_menu=fixed
        )

        async with AsyncSessionLocal() as db:
            await repo.upsert_autopilot_plan(
                db, user_id, next_monday, full_result.to_json(), status="draft"
            )

        ui.navigate.to("/autopilot")

    async def _cancel_preview() -> None:
        async with AsyncSessionLocal() as db:
            await repo.update_autopilot_plan_status(db, plan.id, "expired")
        ui.navigate.to("/autopilot")

    # ── Slot rows inside a single card (matches draft weekmenu overview density)
    _dinner_slots = _DINNER_SLOTS + _WEEKEND_SLOTS

    with ui.element("div").style(
        "display:flex;flex-direction:column;gap:0;padding:.625rem .75rem;"
        "background:var(--c-surface-2);border-radius:var(--r-md);"
        "border:1px solid var(--c-border);margin-bottom:.75rem"
    ):
        ui.label("Weekmenu").style(
            "font-size:11px;font-weight:700;color:var(--c-accent);"
            "letter-spacing:.04em;text-transform:uppercase;margin-bottom:.5rem"
        )
        with ui.element("div").style("display:flex;flex-direction:column;gap:.25rem"):
            for slot in _dinner_slots:
                _render_slot_row(slot, next_monday, options, confirmed_menu, _PICKER_OPTION_SLOT)

        has_extras = any(confirmed_menu.get(s) for s in _EXTRA_SLOTS)
        if has_extras:
            ui.element("div").style("height:.375rem")
            for slot in _EXTRA_SLOTS:
                if confirmed_menu.get(slot):
                    _render_slot_row(
                        slot, next_monday, options, confirmed_menu, _PICKER_OPTION_SLOT
                    )

    # ── Action bar ──────────────────────────────────────────────────
    with ui.element("div").style("display:flex;flex-wrap:wrap;gap:.5rem;align-items:center"):
        ui.button(
            t("autopilot.menu_preview_confirm"),
            icon="sym_r_check",
            on_click=_confirm_menu,
        ).props("unelevated dense no-caps size=sm color=deep-purple").style(
            "font-size:12px;font-weight:600"
        )
        ui.button(
            t("autopilot.menu_preview_cancel"),
            icon="sym_r_close",
            on_click=_cancel_preview,
        ).props("flat dense no-caps size=sm").style("font-size:12px;font-weight:600")


# ── Draft plan ───────────────────────────────────────────────────────────────


async def _render_draft(plan, result, session, user_id: int, body, settings=None) -> None:
    store = session.store_number or 0
    cat_map: dict[str, str] = {}
    product_cache: dict = {}
    if store:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.services.categories import parse_categories, top_category

        all_skus = list(
            dict.fromkeys(
                [i.sku for i in result.items if i.sku]
                + [i.original_sku for i in result.items if i.original_sku]
            )
        )
        if all_skus:
            async with AsyncSessionLocal() as db:
                product_cache = await repo.get_product_cache_by_skus(db, store, all_skus)
            for sku, pc in product_cache.items():
                cats = parse_categories(getattr(pc, "categories_json", None))
                cat_map[sku] = top_category(cats)

    plan._sub_display = getattr(settings, "autopilot_sub_display", 5)
    plan._product_cache = product_cache

    order_map: dict = {}
    if getattr(settings, "category_order", "alpha") == "plus":
        from pyplus.services.categories import get_category_order_map

        order_map = await get_category_order_map()

    _render_infobox()

    # Refreshable draft content — avoids full page reload on every change
    @ui.refreshable
    def _draft_content():
        if not result.items:

            async def _expire():
                from pyplus.db import repo
                from pyplus.db.engine import AsyncSessionLocal

                async with AsyncSessionLocal() as db:
                    await repo.update_autopilot_plan_status(db, plan.id, "expired")
                ui.navigate.to("/autopilot")

            asyncio.ensure_future(_expire())
            return

        _render_action_bar_top(plan, result, session, user_id, settings, _draft_content)
        _render_summary_bar(result.summary)

        menu_items = [i for i in result.items if "autopilot:menu" in (i.source or "")]
        if menu_items:
            _render_weekmenu_overview(menu_items)

        flex_items = [i for i in result.items if i.is_flexible]
        if flex_items:
            _render_flex_section(flex_items, plan, result, session, _draft_content)

        optional_items = [i for i in result.items if i.is_optional]
        if optional_items:
            _render_optional_section(optional_items, plan, result, _draft_content)

        review_items = [i for i in result.items if i.needs_review and not i.is_flexible]
        if review_items:
            _render_review_section(review_items, plan, result, session, user_id, _draft_content)

        items_by_source: dict[str, list] = {}
        for item in result.items:
            if item.needs_review or item.is_optional or item.is_flexible:
                continue
            src = item.source.split(",")[0].strip() if item.source else "other"
            items_by_source.setdefault(src, []).append(item)

        for source_key, section_title_key, icon in _SOURCE_SECTIONS:
            section_items = items_by_source.get(source_key, [])
            if not section_items:
                continue
            if source_key == "autopilot:promo":
                _render_promo_section(section_items, plan, result, _draft_content)
            else:
                _render_section_card(
                    t(section_title_key),
                    icon,
                    section_items,
                    cat_map,
                    plan,
                    result,
                    _draft_content,
                    order_map,
                )

    _draft_content()


def _render_infobox() -> None:
    with ui.element("div").style(
        "display:flex;align-items:flex-start;gap:.5rem;padding:.625rem .75rem;"
        "background:var(--c-accent-tint);border-radius:var(--r-md);border:1px solid var(--c-accent-border);"
        "margin-bottom:.75rem"
    ):
        ui.icon(_ICON, size="16px").style("color:var(--c-accent);flex-shrink:0;margin-top:1px")
        ui.label(t("autopilot.infobox")).style(
            "font-size:12px;color:var(--c-accent);line-height:1.55"
        )


_DAY_ORDER = ["ma", "di", "wo", "do", "vr", "za", "zo"]
_DAY_SHORT = {
    "maandag": "ma",
    "dinsdag": "di",
    "woensdag": "wo",
    "donderdag": "do",
    "vrijdag": "vr",
    "zaterdag": "za",
    "zondag": "zo",
}
_DAY_FULL = {
    "ma": "Maandag",
    "di": "Dinsdag",
    "wo": "Woensdag",
    "do": "Donderdag",
    "vr": "Vrijdag",
    "za": "Zaterdag",
    "zo": "Zondag",
}
_EXTRA_LABEL = {
    "extra 1": "Extra (maandag)",
    "extra 2": "Extra (dinsdag)",
    "extra 3": "Extra (woensdag)",
    "extra 4": "Extra (donderdag)",
    "extra 5": "Extra (vrijdag)",
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


def _render_weekmenu_overview(menu_items: list) -> None:
    import re

    day_dishes: dict[str, set[str]] = {}
    extra_dishes: dict[str, set[str]] = {}

    for item in menu_items:
        if not item.context:
            continue
        for part in re.split(r"\),\s*", item.context):
            part = part.strip().rstrip(")")
            m = re.match(r"^(.+)\s*\(([^)]+)$", part.strip())
            if not m:
                continue
            dish_name, day_label = m.group(1).strip(), m.group(2)
            short = _DAY_SHORT.get(day_label)
            if short:
                day_dishes.setdefault(short, set()).add(dish_name)
            elif day_label.startswith("extra"):
                extra_dishes.setdefault(day_label, set()).add(dish_name)

    if not day_dishes and not extra_dishes:
        return

    today = datetime.date.today()
    week_start = today + datetime.timedelta(days=(7 - today.weekday()))

    with ui.element("div").style(
        "display:flex;flex-direction:column;gap:0;padding:.625rem .75rem;"
        "background:var(--c-surface-2);border-radius:var(--r-md);"
        "border:1px solid var(--c-border);margin-bottom:.75rem"
    ):
        ui.label("Weekmenu").style(
            "font-size:11px;font-weight:700;color:var(--c-accent);"
            "letter-spacing:.04em;text-transform:uppercase;margin-bottom:.5rem"
        )
        with ui.element("div").style("display:flex;flex-direction:column;gap:.25rem"):
            for idx, day in enumerate(_DAY_ORDER):
                dishes = day_dishes.get(day)
                if not dishes:
                    continue
                d = week_start + datetime.timedelta(days=idx)
                date_str = f"{d.day} {_MONTHS_NL[d.month]}"
                with ui.element("div").style(
                    "display:flex;align-items:baseline;gap:.5rem;min-width:0"
                ):
                    ui.label(f"{_DAY_FULL[day]} {date_str}").style(
                        "font-size:12px;font-weight:600;color:var(--c-text-2);"
                        "flex-shrink:0;min-width:130px"
                    )
                    ui.label(" · ".join(sorted(dishes))).style(
                        "font-size:12px;color:var(--c-text);min-width:0"
                    )
            for label in sorted(extra_dishes):
                dishes = extra_dishes[label]
                display = _EXTRA_LABEL.get(label, label)
                with ui.element("div").style(
                    "display:flex;align-items:baseline;gap:.5rem;min-width:0"
                ):
                    ui.label(display).style(
                        "font-size:12px;font-weight:600;color:var(--c-text-2);"
                        "flex-shrink:0;min-width:130px"
                    )
                    ui.label(" · ".join(sorted(dishes))).style(
                        "font-size:12px;color:var(--c-text);min-width:0"
                    )


def _render_action_bar_top(plan, result, session, user_id: int, settings, refresh_fn) -> None:
    with ui.element("div").style(
        "display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin-bottom:.75rem"
    ) as action_bar:
        clear_cart = settings and getattr(settings, "autopilot_clear_cart", False)

        async def _do_confirm() -> None:
            if clear_cart:
                await session.cart_service.clear_all()

            kind_map = {
                "menu": "menu",
                "staple": "staple",
                "promo": "promotion",
                "filler": "filler",
            }
            cart_snapshot = []
            for item in result.items:
                if item.needs_review:
                    continue
                if item.is_optional:
                    continue
                kind = kind_map.get((item.source or "").split(":")[-1], "menu")
                ok = await session.cart_service.add(
                    item.sku,
                    item.qty,
                    product_name=item.name,
                    product_price=item.price,
                    product_image=item.image_url,
                    source=kind,
                    detail=item.context,
                    via_autopilot=True,
                    check_stock=False,
                )
                if ok:
                    cart_snapshot.append({"sku": item.sku, "qty": item.qty})

            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal

            if result.menu_assignments:
                today = datetime.date.today()
                ws = today + datetime.timedelta(days=(7 - today.weekday()))
                async with AsyncSessionLocal() as db:
                    for slot, dish_id in result.menu_assignments.items():
                        await repo.set_weekmenu_slot(db, user_id, slot, ws, dish_id)
                    await db.commit()

            async with AsyncSessionLocal() as db:
                await repo.update_autopilot_plan_status(
                    db,
                    plan.id,
                    "confirmed",
                    cart_snapshot_json=json.dumps(cart_snapshot, ensure_ascii=False),
                )
                staple_skus = [
                    i.sku for i in result.items if i.source == "autopilot:staple" and i.sku
                ]
                await repo.stamp_fixed_products_added(db, user_id, staple_skus)

            added = len(cart_snapshot)
            cost = sum(
                i.price * i.qty for i in result.items if not i.needs_review and not i.is_optional
            )
            ui.notify(
                t("autopilot.confirmed_summary", n=added, cost=f"{cost:.2f}"),
                type="positive",
            )
            ui.navigate.to("/autopilot")

        def _confirm() -> None:
            n = sum(i.qty for i in result.items if not i.needs_review and not i.is_optional)
            cost = _eur(
                sum(
                    i.price * i.qty
                    for i in result.items
                    if not i.needs_review and not i.is_optional
                )
            )
            confirm_body = t("autopilot.confirm_body", n=n, cost=cost)
            if clear_cart:
                confirm_body += (
                    "\n\nDe instelling 'Winkelwagen legen voor autopilot' staat aan. "
                    "Je huidige winkelwagen wordt eerst geleegd."
                )
            _show_confirm_dialog(
                t("autopilot.confirm_title"),
                confirm_body,
                _do_confirm,
                confirm_label=t("autopilot.confirm"),
            )

        ui.button(
            t("autopilot.confirm"),
            icon="sym_r_add_shopping_cart",
            on_click=_confirm,
        ).props("unelevated dense no-caps size=sm color=deep-purple").style(
            "font-size:12px;font-weight:600"
        )

        regen_spinner = ui.element("div").style("display:none")

        async def _regenerate() -> None:
            action_bar.style(
                "display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin-bottom:.75rem;"
                "pointer-events:none;opacity:.5"
            )
            regen_spinner.style("display:flex;align-items:center;gap:.5rem")
            with regen_spinner:
                ui.spinner(size="sm", color="deep-purple")
                ui.label(t("autopilot.generating")).style("font-size:13px;color:var(--c-text-3)")
            try:
                from pyplus.db import repo
                from pyplus.db.engine import AsyncSessionLocal
                from pyplus.services.autopilot import (
                    AutopilotResult,
                    PlanSummary,
                    prepare_menu_only,
                )

                menu = await prepare_menu_only(user_id, store_number=session.store_number)
                preview = AutopilotResult(items=[], summary=PlanSummary(), menu_assignments=menu)
                today = datetime.date.today()
                ws = today + datetime.timedelta(days=(7 - today.weekday()))
                async with AsyncSessionLocal() as db:
                    await repo.upsert_autopilot_plan(
                        db, user_id, ws, preview.to_json(), status="menu_preview"
                    )
            except Exception:
                log.exception("Regenerate plan failed")
                ui.notify(t("autopilot.regenerate_error"), type="negative")
            ui.run_javascript("window.location.href = '/autopilot'")

        ui.button(
            t("autopilot.regenerate"),
            icon="sym_r_refresh",
            on_click=_regenerate,
        ).props("flat dense no-caps size=sm").style("font-size:12px;font-weight:600")

        async def _do_delete() -> None:
            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                await repo.update_autopilot_plan_status(db, plan.id, "expired")
            ui.navigate.to("/autopilot")

        def _delete() -> None:
            _show_confirm_dialog(
                t("autopilot.delete_confirm_title"),
                t("autopilot.delete_confirm_body"),
                _do_delete,
                confirm_color="negative",
            )

        ui.button(
            t("autopilot.delete_plan"),
            on_click=_delete,
        ).props("flat dense no-caps color=negative size=sm").style("font-size:12px;font-weight:600")


def _show_confirm_dialog(
    title: str,
    body: str,
    on_confirm,
    confirm_label: str | None = None,
    confirm_color: str = "deep-purple",
) -> None:
    with ui.dialog(value=True) as dlg, ui.card().style("min-width:320px;max-width:420px"):
        ui.label(title).style("font-size:15px;font-weight:600;margin-bottom:.5rem")
        ui.label(body).style("font-size:13px;color:var(--c-text-3);white-space:pre-line")
        with ui.element("div").style(
            "display:flex;justify-content:flex-end;gap:.5rem;margin-top:.75rem"
        ):
            ui.button(t("action.cancel"), on_click=dlg.close).props("flat dense no-caps color=grey")

            async def _ok():
                dlg.close()
                await on_confirm()

            ui.button(confirm_label or t("action.confirm"), on_click=_ok).props(
                f"unelevated dense no-caps color={confirm_color}"
            )


# ── Summary bar ──────────────────────────────────────────────────────────────


def _render_summary_bar(summary) -> None:
    with ui.element("div").style(
        "display:flex;flex-wrap:wrap;gap:.5rem .75rem;align-items:baseline;"
        "margin-bottom:.75rem;padding:.625rem .75rem;"
        "background:var(--c-surface-2);border:1px solid var(--c-border);border-radius:var(--r-md)"
    ):
        ui.label(f"{summary.total_items} producten").style(
            "font-size:15px;font-weight:700;color:var(--c-text)"
        )
        ui.label("·").style("font-size:15px;color:var(--c-text-3)")
        ui.label(_eur(summary.estimated_cost)).style(
            "font-size:15px;font-weight:700;color:var(--c-text)"
        )

        if summary.promo_swaps > 0:
            swap_word = "besparingsproduct" if summary.promo_swaps == 1 else "besparingsproducten"
            _stat_pill(
                "sym_r_sell",
                f"{summary.promo_swaps} {swap_word}",
                bg="var(--c-warning-tint-2)",
                fg="var(--c-warning-text)",
            )
        if summary.promo_savings > 0:
            _stat_pill(
                "sym_r_savings",
                f"bespaar {_eur(summary.promo_savings)}",
                bg="var(--c-positive-tint)",
                fg="var(--c-positive-text)",
            )
        if summary.flex_count > 0:
            _stat_pill(
                "sym_r_tune",
                t(
                    "autopilot.flex_pending_one"
                    if summary.flex_count == 1
                    else "autopilot.flex_pending",
                    n=summary.flex_count,
                ),
                bg="color-mix(in srgb, var(--c-brand) 10%, transparent)",
                fg="var(--c-brand-dark)",
            )
        if summary.optional_count > 0:
            _stat_pill(
                "sym_r_add_circle_outline",
                f"{summary.optional_count} optioneel",
                bg="var(--c-surface-2)",
                fg="var(--c-text-3)",
            )
        non_flex_review = summary.needs_review_count - summary.flex_count
        if non_flex_review > 0:
            _stat_pill(
                "sym_r_rate_review",
                t(
                    "autopilot.review_needed_one"
                    if non_flex_review == 1
                    else "autopilot.review_needed",
                    n=non_flex_review,
                ),
                bg="var(--c-warning-tint)",
                fg="var(--c-warning-icon)",
            )
        elif summary.total_items > 0 and summary.flex_count == 0:
            _stat_pill(
                "sym_r_check_circle",
                t("autopilot.all_ready"),
                bg="var(--c-accent-tint)",
                fg="var(--c-accent)",
            )
        if summary.free_delivery_met:
            _stat_pill(
                "sym_r_local_shipping",
                "Gratis bezorging inbegrepen",
                bg="var(--c-accent-tint)",
                fg="var(--c-accent)",
            )


def _stat_pill(icon: str, text: str, bg: str = "var(--c-bg)", fg: str = "var(--c-text-2)") -> None:
    with ui.element("div").style(
        f"display:inline-flex;align-items:center;gap:.25rem;padding:2px 8px;"
        f"background:{bg};border-radius:99px;font-size:11px;font-weight:600;color:{fg}"
    ):
        ui.icon(icon, size="14px")
        ui.label(text)


# ── Section cards (collapsible, interactive grid) ─────────────────────────


def _render_section_card(
    title: str,
    icon: str,
    items: list,
    cat_map: dict,
    plan,
    result,
    refresh_fn,
    order_map: dict | None = None,
) -> None:
    n_items = sum(i.qty for i in items)
    total = sum(i.price * i.qty for i in items)
    header_text = f"{title} · {n_items} producten · {_eur(total)}"

    with ui.element("div").classes("sp-ap-section"):
        with (
            ui.element("div")
            .classes("sp-ap-section__header sp-ap-section__header--collapsible")
            .style("cursor:pointer")
        ) as header:
            ui.icon(icon, size="18px").style("color:var(--c-accent)")
            ui.label(header_text).style("font-size:13px;font-weight:600;color:var(--c-text);flex:1")
            chevron = ui.icon("sym_r_expand_more", size="20px").style(
                "color:var(--c-text-3);transition:transform .2s var(--ease)"
            )

        from pyplus.services.categories import group_order

        buckets: dict[str, list] = {}
        for item in items:
            cat = cat_map.get(item.sku, "Overig")
            buckets.setdefault(cat, []).append(item)

        ordered = group_order(list(buckets), order_map)
        content = ui.element("div").style(
            "padding:.25rem .625rem .625rem;display:none;animation:sp-ap-expand .2s var(--ease)"
        )
        with content:
            if len(ordered) <= 1:
                with ui.element("div").classes("sp-ap-grid"):
                    for item in items:
                        _render_item_card(item, plan, result, refresh_fn)
            else:
                for cat in ordered:
                    ui.label(cat).classes("sp-ap-cat")
                    with ui.element("div").classes("sp-ap-grid"):
                        for item in buckets[cat]:
                            _render_item_card(item, plan, result, refresh_fn)

        _collapsed = {"value": True}

        def _toggle():
            _collapsed["value"] = not _collapsed["value"]
            if _collapsed["value"]:
                content.style("display:none")
                chevron.style(
                    "color:var(--c-text-3);transition:transform .2s var(--ease);transform:rotate(0)"
                )
            else:
                content.style(
                    "padding:.25rem .625rem .625rem;display:block;"
                    "animation:sp-ap-expand .2s var(--ease)"
                )
                chevron.style(
                    "color:var(--c-text-3);transition:transform .2s var(--ease);"
                    "transform:rotate(180deg)"
                )

        header.on("click", _toggle)


def _render_context_html(item) -> None:
    """Render context with product names in bold where applicable."""
    from html import escape

    ctx = item.context or ""
    if item.is_promo_swap and item.original_name:
        escaped = escape(item.original_name)
        ctx_escaped = escape(ctx)
        ctx_html = ctx_escaped.replace(escaped, f"<b>{escaped}</b>")
        ui.html(f'<span class="sp-ap-card__ctx">{ctx_html}</span>')
    elif item.original_name and item.original_name in ctx:
        escaped = escape(item.original_name)
        ctx_escaped = escape(ctx)
        ctx_html = ctx_escaped.replace(escaped, f"<b>{escaped}</b>")
        ui.html(f'<span class="sp-ap-card__ctx">{ctx_html}</span>')
    else:
        ui.label(ctx).classes("sp-ap-card__ctx")


def _render_item_card(item, plan, result, refresh_fn) -> None:
    pc = getattr(plan, "_product_cache", {}).get(item.sku)
    subtitle = (pc.subtitle if pc else None) or ""

    with ui.element("div").classes("sp-ap-card"):
        # Remove button
        ui.button(
            icon="sym_r_close",
            on_click=lambda i=item: _remove_item(i, plan, result, refresh_fn),
        ).props("flat round dense size=xs color=grey-5").classes("sp-ap-card__delete")

        if item.image_url:
            ui.image(thumbnail_url(item.image_url, 64, fit="pad")).classes("sp-ap-card__img").props(
                f'alt="{_alt(item.name)}"'
            )
        else:
            ui.element("div").classes("sp-ap-card__img")

        ui.label(item.name).classes("sp-ap-card__name")

        if subtitle:
            ui.label(subtitle).style("font-size:9px;color:var(--c-text-4);text-align:center")

        if item.context:
            _render_context_html(item)

        ui.label(_eur(item.price * item.qty)).classes("sp-ap-card__price")

        if item.is_promo_swap and item.promo_savings > 0:
            ui.label(f"bespaar {_eur(item.promo_savings)}").classes("sp-ap-card__promo")

        # Qty stepper
        with ui.element("div").classes("sp-ap-card__stepper"):
            ui.button(
                icon="sym_r_remove",
                on_click=lambda i=item: _decrease_qty(i, plan, result, refresh_fn),
            ).props("flat round dense size=xs").style(
                "color:var(--c-accent);min-width:24px;height:24px"
            )
            ui.label(str(item.qty)).style(
                "font-size:12px;font-weight:700;color:var(--c-text);min-width:16px;text-align:center"
            )
            ui.button(
                icon="sym_r_add",
                on_click=lambda i=item: _increase_qty(i, plan, result, refresh_fn),
            ).props("flat round dense size=xs").style(
                "color:var(--c-accent);min-width:24px;height:24px"
            )


def _render_promo_section(items: list, plan, result, refresh_fn) -> None:
    total_savings = sum(i.promo_savings for i in items)
    with ui.element("div").classes("sp-ap-section"):
        with (
            ui.element("div")
            .classes("sp-ap-section__header")
            .style(
                "background:var(--c-warning-tint-2);border-bottom-color:var(--c-warning-border-2)"
            )
        ):
            ui.icon("sym_r_sell", size="18px").style("color:var(--c-warning-text)")
            ui.label(
                f"{t('autopilot.section.promo_swaps')} · {len(items)} wisselingen"
                f" · bespaar {_eur(total_savings)}"
            ).style("font-size:13px;font-weight:600;color:var(--c-warning-text);flex:1")
        with ui.element("div").style(
            "padding:.25rem .625rem .625rem;display:flex;flex-direction:column;gap:.5rem"
        ):
            for item in items:
                _render_promo_swap_card(item, plan, result, refresh_fn)


def _render_promo_swap_card(item, plan, result, refresh_fn) -> None:
    cache = getattr(plan, "_product_cache", {})
    pc = cache.get(item.sku)
    subtitle = (pc.subtitle if pc else None) or ""
    orig_pc = cache.get(item.original_sku) if item.original_sku else None
    orig_subtitle = (orig_pc.subtitle if orig_pc else None) or ""
    orig_price = (
        item.price + (item.promo_savings / max(item.qty, 1)) if item.promo_savings > 0 else 0.0
    )

    with ui.element("div").style(
        "display:flex;align-items:center;gap:.625rem;padding:.625rem .75rem;"
        "background:var(--c-surface-2);border-radius:var(--r-md);"
        "border:1px solid var(--c-border)"
    ):
        if item.image_url:
            ui.image(thumbnail_url(item.image_url, 48, fit="pad")).style(
                "width:48px;height:48px;border-radius:var(--r-sm);flex-shrink:0;object-fit:contain"
            ).props(f'alt="{_alt(item.name)}"')

        with ui.element("div").style("flex:1;min-width:0"):
            ui.label(item.name).style("font-size:13px;font-weight:600;color:var(--c-text)")
            if subtitle:
                ui.label(subtitle).style("font-size:11px;color:var(--c-text-3)")
            if item.original_name:
                from html import escape

                ui.html(
                    f'<span style="font-size:11px;color:var(--c-text-3)">'
                    f"Vervangt <b>{escape(item.original_name)}</b></span>"
                )
                if orig_subtitle:
                    ui.label(orig_subtitle).style("font-size:10px;color:var(--c-text-4)")
            with ui.element("div").style(
                "display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin-top:2px"
            ):
                ui.label(_eur(item.price)).style(
                    "font-size:12px;font-weight:600;color:var(--c-text)"
                )
                if item.promo_savings > 0:
                    ui.label(f"bespaar {_eur(item.promo_savings)}").style(
                        "font-size:11px;font-weight:700;color:var(--c-accent)"
                    )
            if orig_price > 0:
                new_unit, orig_unit = _unit_price_pair(
                    item.price, subtitle, orig_price, orig_subtitle
                )
            else:
                new_unit = _unit_price_label(item.price, subtitle)
                orig_unit = ""
            if new_unit or orig_unit:
                with ui.element("div").style(
                    "display:flex;gap:.375rem;align-items:center;flex-wrap:wrap;margin-top:1px"
                ):
                    if orig_unit:
                        ui.label(f"was {orig_unit}").style(
                            "font-size:10px;color:var(--c-text-4);text-decoration:line-through"
                        )
                    if new_unit:
                        ui.label(f"nu {new_unit}").style(
                            "font-size:10px;font-weight:600;color:var(--c-accent)"
                        )

        with ui.element("div").style("display:flex;flex-direction:column;gap:.25rem;flex-shrink:0"):
            ui.button(
                "Akkoord",
                on_click=lambda i=item: _accept_promo_swap(i, plan, result, refresh_fn),
            ).props("unelevated dense no-caps size=xs color=deep-purple").style("font-size:11px")
            ui.button(
                "Afwijzen",
                on_click=lambda i=item: _reject_promo_swap(i, plan, result, refresh_fn),
            ).props("flat dense no-caps size=xs color=grey").style("font-size:11px")


def _accept_promo_swap(item, plan, result, refresh_fn) -> None:
    item.is_promo_swap = False
    item.source = "autopilot:menu"
    result.summary.promo_swaps = max(0, result.summary.promo_swaps - 1)
    result.summary.promo_savings = round(
        max(0, result.summary.promo_savings - item.promo_savings), 2
    )
    item.context = ""
    item.promo_savings = 0.0
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


def _reject_promo_swap(item, plan, result, refresh_fn) -> None:
    if item.original_sku and item.original_name:
        old_price = item.price + (item.promo_savings / max(item.qty, 1))
        result.summary.estimated_cost = round(
            result.summary.estimated_cost - (item.price * item.qty) + (old_price * item.qty), 2
        )
        item.sku = item.original_sku
        item.name = item.original_name
        item.price = old_price
        item.image_url = ""
        item.is_promo_swap = False
        item.source = "autopilot:menu"
        item.context = ""
        result.summary.promo_swaps = max(0, result.summary.promo_swaps - 1)
        result.summary.promo_savings = round(
            max(0, result.summary.promo_savings - item.promo_savings), 2
        )
        item.promo_savings = 0.0
        item.original_sku = None
        item.original_name = None
    else:
        _remove_item(item, plan, result, refresh_fn)
        return
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


def _increase_qty(item, plan, result, refresh_fn) -> None:
    item.qty += 1
    result.summary.total_items += 1
    result.summary.estimated_cost = round(result.summary.estimated_cost + item.price, 2)
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


def _decrease_qty(item, plan, result, refresh_fn) -> None:
    if item.qty <= 1:
        _remove_item(item, plan, result, refresh_fn)
        return
    item.qty -= 1
    result.summary.total_items -= 1
    result.summary.estimated_cost = round(result.summary.estimated_cost - item.price, 2)
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


def _remove_item(item, plan, result, refresh_fn) -> None:
    if item in result.items:
        result.items.remove(item)
    result.summary.total_items = max(0, result.summary.total_items - item.qty)
    result.summary.estimated_cost = round(
        max(0, result.summary.estimated_cost - item.price * item.qty), 2
    )
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


# ── Optional ingredients section ────────────────────────────────────────────


def _render_optional_section(items: list, plan, result, refresh_fn) -> None:
    with ui.element("div").classes("sp-ap-optional"):
        with ui.element("div").classes("sp-ap-optional__header"):
            ui.icon("sym_r_add_circle_outline", size="18px").style("color:var(--c-text-3)")
            ui.label(f"{t('autopilot.section.optional')} ({len(items)})").style(
                "font-size:13px;font-weight:600;color:var(--c-text);flex:1"
            )
            ui.label(t("autopilot.optional_hint")).style("font-size:11px;color:var(--c-text-3)")

        for item in items:
            _render_optional_row(item, plan, result, refresh_fn)


def _render_optional_row(item, plan, result, refresh_fn) -> None:
    cache = getattr(plan, "_product_cache", {})
    pc = cache.get(item.sku)
    subtitle = (pc.subtitle if pc else None) or ""
    price_label = _eur(item.price) if item.price > 0 else ""

    with ui.element("div").classes("sp-ap-optional-row"):
        cb = ui.checkbox(value=False).props("dense color=deep-purple")

        def _toggle(e, it=item):
            if e.value:
                it.is_optional = False
                result.summary.optional_count = max(0, result.summary.optional_count - 1)
                result.summary.total_items += it.qty
                result.summary.estimated_cost = round(
                    result.summary.estimated_cost + it.price * it.qty, 2
                )
            else:
                it.is_optional = True
                result.summary.optional_count += 1
                result.summary.total_items = max(0, result.summary.total_items - it.qty)
                result.summary.estimated_cost = round(
                    result.summary.estimated_cost - it.price * it.qty, 2
                )
            _persist_plan_update(plan, result)
            refresh_fn.refresh()

        cb.on("update:model-value", _toggle)

        if item.image_url:
            ui.image(thumbnail_url(item.image_url, 36, fit="pad")).style(
                "width:36px;height:36px;border-radius:var(--r-sm);flex-shrink:0;object-fit:contain"
            ).props(f'alt="{_alt(item.name)}"')

        with ui.element("div").style("flex:1;min-width:0"):
            ui.label(item.name).style(
                "font-size:13px;font-weight:600;color:var(--c-text);"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            )
            if subtitle:
                ui.label(subtitle).style("font-size:11px;color:var(--c-text-3)")
            if item.context:
                ui.label(item.context).style("font-size:10px;color:var(--c-text-4)")

        if price_label:
            ui.label(price_label).style(
                "font-size:12px;font-weight:600;color:var(--c-text-3);flex-shrink:0"
            )


# ── Flexible ingredients section ───────────────────────────────────────────


def _render_flex_section(items: list, plan, result, session, refresh_fn) -> None:
    pending = sum(1 for i in items if i.needs_review)
    with ui.element("div").classes("sp-ap-flex"):
        with ui.element("div").classes("sp-ap-flex__header"):
            ui.icon("sym_r_tune", size="18px").style("color:var(--c-brand-dark)")
            ui.label(f"{t('autopilot.section.flexible')} ({len(items)})").style(
                "font-size:14px;font-weight:600;color:var(--c-text);flex:1"
            )
            if pending > 0:
                ui.label(t("autopilot.flex_hint")).style("font-size:11px;color:var(--c-text-3)")

        for item in items:
            _render_flex_card(item, plan, result, session, refresh_fn)


def _render_flex_card(item, plan, result, session, refresh_fn) -> None:
    with ui.element("div").classes("sp-ap-flex-card"):
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem"
        ):
            ui.icon("sym_r_tune", size="16px").style("color:var(--c-brand-dark);flex-shrink:0")
            ui.label(item.flex_label or item.name).style(
                "font-size:13px;font-weight:600;color:var(--c-text);flex:1;min-width:0"
            )
            if item.context:
                ui.label(item.context).style("font-size:10px;color:var(--c-text-4);flex-shrink:0")

        if not item.needs_review and item.sku:
            cache = getattr(plan, "_product_cache", {})
            pc = cache.get(item.sku)
            subtitle = (pc.subtitle if pc else None) or ""
            with ui.element("div").style(
                "display:flex;align-items:center;gap:.5rem;padding:.375rem .5rem;"
                "background:var(--c-accent-surface);border:1px solid var(--c-accent-border);"
                "border-radius:var(--r-md)"
            ):
                if item.image_url:
                    ui.image(thumbnail_url(item.image_url, 32, fit="pad")).style(
                        "width:32px;height:32px;object-fit:contain;border-radius:4px;flex-shrink:0"
                    ).props(f'alt="{_alt(item.name)}"')
                with ui.element("div").style("flex:1;min-width:0"):
                    ui.label(item.name).style(
                        "font-size:13px;color:var(--c-text);overflow:hidden;"
                        "text-overflow:ellipsis;white-space:nowrap"
                    )
                    if subtitle:
                        ui.label(subtitle).style("font-size:11px;color:var(--c-text-3)")
                if item.price > 0:
                    ui.label(_eur(item.price)).style(
                        "font-size:12px;font-weight:600;color:var(--c-text-3);flex-shrink:0"
                    )

                def _clear_flex(it=item):
                    it.sku = ""
                    it.name = it.flex_label
                    it.price = 0.0
                    it.image_url = ""
                    it.needs_review = True
                    it.is_flexible = True
                    result.summary.flex_count += 1
                    result.summary.needs_review_count += 1
                    result.summary.total_items = max(0, result.summary.total_items - it.qty)
                    result.summary.estimated_cost = round(
                        result.summary.estimated_cost - it.price * it.qty, 2
                    )
                    _persist_plan_update(plan, result)
                    refresh_fn.refresh()

                ui.button(t("autopilot.flex_change"), on_click=_clear_flex).props(
                    "flat dense no-caps size=sm color=primary"
                ).style("font-size:12px;flex-shrink:0")
            return

        # Search picker for unresolved flex items
        _flex_state: dict = {"query": "", "results": [], "searching": False}

        with ui.element("div").style("position:relative"):
            search_field = (
                ui.input(
                    placeholder=t("autopilot.flex_search_placeholder"),
                    value=_flex_state["query"],
                )
                .props("outlined dense clearable")
                .style("width:100%")
            )
            results_box = ui.element("div")

            def _draw_results(st=_flex_state, box=results_box):
                box.clear()
                with box:
                    if st["searching"]:
                        ui.label("Zoeken…").style(
                            "padding:.375rem .5rem;font-size:12px;color:var(--c-text-3)"
                        )
                    elif st["results"]:
                        with ui.element("div").style(
                            "border:1px solid var(--c-border);border-radius:var(--r-md);"
                            "margin-top:.25rem;max-height:200px;overflow-y:auto"
                        ):
                            for prod in st["results"][:8]:

                                def _pick(p=prod, it=item, s=st):
                                    it.sku = p.sku
                                    it.name = p.name
                                    it.price = getattr(p, "price", 0.0)
                                    it.image_url = getattr(p, "image_url", "") or ""
                                    it.needs_review = False
                                    it.is_flexible = False
                                    result.summary.flex_count = max(
                                        0, result.summary.flex_count - 1
                                    )
                                    result.summary.needs_review_count = max(
                                        0, result.summary.needs_review_count - 1
                                    )
                                    result.summary.total_items += it.qty
                                    result.summary.estimated_cost = round(
                                        result.summary.estimated_cost + it.price * it.qty, 2
                                    )
                                    _persist_plan_update(plan, result)
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
                                            "border-radius:4px;background:var(--c-border);"
                                            "flex-shrink:0"
                                        ).props(f'alt="{_alt(prod.name)}"')
                                    ui.label(prod.name).style(
                                        "font-size:12px;flex:1;min-width:0;overflow:hidden;"
                                        "text-overflow:ellipsis;white-space:nowrap"
                                    )
                                    if hasattr(prod, "price") and prod.price > 0:
                                        ui.label(_eur(prod.price)).style(
                                            "font-size:11px;color:var(--c-text-3);flex-shrink:0"
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

            async def _on_search(e, st=_flex_state, field=search_field):
                st["query"] = (e.value if hasattr(e, "value") else field.value) or ""
                if len(st["query"].strip()) >= 2:
                    st["searching"] = True
                    _draw_results()
                    try:
                        from pyplus.services.search import search_products

                        st["results"] = await search_products(session, st["query"])
                    except Exception:
                        st["results"] = []
                    st["searching"] = False
                else:
                    st["results"] = []
                _draw_results()

            search_field.on("update:model-value", _on_search)
            _draw_results()

        ui.button(
            t("autopilot.remove_item"),
            icon="sym_r_delete_outline",
            on_click=lambda it=item: _remove_flex_item(it, plan, result, refresh_fn),
        ).props("flat dense no-caps size=xs color=negative").style(
            "font-size:11px;margin-top:.375rem"
        )


def _remove_flex_item(item, plan, result, refresh_fn) -> None:
    if item in result.items:
        result.items.remove(item)
    if item.needs_review:
        result.summary.needs_review_count = max(0, result.summary.needs_review_count - 1)
    else:
        result.summary.total_items = max(0, result.summary.total_items - item.qty)
        result.summary.estimated_cost = round(
            result.summary.estimated_cost - item.price * item.qty, 2
        )
    result.summary.flex_count = max(0, result.summary.flex_count - 1)
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


# ── Review section (substitutes) ────────────────────────────────────────────


def _render_review_section(items: list, plan, result, session, user_id: int, refresh_fn) -> None:
    with ui.element("div").classes("sp-ap-review"):
        with ui.element("div").classes("sp-ap-review__header"):
            ui.icon("sym_r_rate_review", size="18px").style("color:var(--c-warning-icon)")
            ui.label(f"{t('autopilot.section.substitutes')} ({len(items)})").style(
                "font-size:14px;font-weight:600;color:var(--c-text);flex:1"
            )
            ui.label(t("autopilot.review_hint")).style("font-size:11px;color:var(--c-text-3)")

        for item in items:
            _render_review_card(item, plan, result, session, user_id, refresh_fn)


def _render_review_card(item, plan, result, session, user_id: int, refresh_fn) -> None:
    with ui.element("div").classes("sp-ap-review-card"):
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.625rem;margin-bottom:.625rem"
        ):
            if item.image_url:
                ui.image(thumbnail_url(item.image_url, 44, fit="pad")).style(
                    "width:44px;height:44px;border-radius:var(--r-sm);flex-shrink:0;"
                    "object-fit:contain"
                ).props(f'alt="{_alt(item.name)}"')
            with ui.element("div").style("flex:1;min-width:0"):
                ui.label(item.original_name or item.name).style(
                    "font-size:13px;font-weight:600;color:var(--c-text)"
                )
                if item.context:
                    ui.label(item.context).style(
                        "font-size:10px;color:var(--c-text-3);margin-top:1px"
                    )
                ui.label("Niet beschikbaar").style(
                    "font-size:10px;font-weight:700;color:var(--c-danger);"
                    "letter-spacing:.02em;margin-top:2px"
                )
            ui.button(
                t("autopilot.remove_item"),
                icon="sym_r_delete_outline",
                on_click=lambda i=item: _skip_item(i, plan, result, refresh_fn),
            ).props("flat dense no-caps size=xs color=negative").style("font-size:11px")

        if item.substitute_options:
            ui.label(t("autopilot.pick_alternative")).style(
                "font-size:10px;font-weight:700;color:var(--c-text-4);"
                "letter-spacing:.06em;text-transform:uppercase;margin-bottom:.375rem"
            )
            max_show = getattr(plan, "_sub_display", 5)
            with ui.element("div").classes("sp-ap-sub-grid"):
                for opt in item.substitute_options[:max_show]:
                    _render_substitute_card(item, opt, plan, result, refresh_fn)
        else:
            ui.label("Geen alternatieven gevonden.").style(
                "font-size:12px;color:var(--c-text-3);font-style:italic"
            )


def _render_substitute_card(parent_item, opt: dict, plan, result, refresh_fn) -> None:
    score = opt.get("score", 0)
    score_pct = min(100, int(score * 10))
    subtitle = opt.get("subtitle", "")

    _score_color = (
        "var(--c-brand)"
        if score_pct >= 70
        else "var(--c-warning)"
        if score_pct >= 40
        else "var(--c-danger-red)"
    )

    with (
        ui.element("div")
        .classes("sp-ap-card sp-ap-card--sub")
        .on(
            "click",
            lambda o=opt: _accept_substitute(parent_item, o, plan, result, refresh_fn),
        )
    ):
        # Score badge (top-right)
        with ui.element("div").classes("sp-ap-card__score").style(f"color:{_score_color}"):
            ui.label(f"{score_pct}%")

        if opt.get("image_url"):
            ui.image(thumbnail_url(opt["image_url"], 56, fit="pad")).classes("sp-ap-card__img")
        else:
            ui.element("div").classes("sp-ap-card__img")

        ui.label(opt["name"]).classes("sp-ap-card__name")

        if subtitle:
            ui.label(subtitle).style("font-size:9px;color:var(--c-text-4);text-align:center")

        ui.label(_eur(opt["price"])).classes("sp-ap-card__price")

        ui.button(
            t("autopilot.accept"),
            on_click=lambda o=opt: _accept_substitute(parent_item, o, plan, result, refresh_fn),
        ).props("unelevated dense no-caps size=xs color=deep-purple").style(
            "font-size:10px;margin-top:auto;width:100%"
        )


def _accept_substitute(item, opt: dict, plan, result, refresh_fn) -> None:
    item.sku = opt["sku"]
    item.name = opt["name"]
    item.price = opt["price"]
    item.image_url = opt.get("image_url", "")
    item.needs_review = False
    item.substitute_options = []
    result.summary.needs_review_count = max(0, result.summary.needs_review_count - 1)
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


def _skip_item(item, plan, result, refresh_fn) -> None:
    if item in result.items:
        result.items.remove(item)
    result.summary.total_items = max(0, result.summary.total_items - item.qty)
    result.summary.needs_review_count = max(0, result.summary.needs_review_count - 1)
    _persist_plan_update(plan, result)
    refresh_fn.refresh()


def _persist_plan_update(plan, result) -> None:
    asyncio.ensure_future(_do_persist(plan, result))


async def _do_persist(plan, result) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        plan.plan_json = result.to_json()
        await repo.upsert_autopilot_plan(
            db,
            plan.user_id,
            plan.week_start,
            plan.plan_json,
        )


# ── Confirmed / rolled-back states ──────────────────────────────────────────


def _render_status_badge(text: str, color: str) -> None:
    with ui.element("div").style(
        f"display:flex;align-items:center;gap:.375rem;padding:.5rem 0;"
        f"font-size:12px;color:{color};font-weight:600"
    ):
        ui.icon("sym_r_info", size="16px")
        ui.label(text)


def _render_confirmed(plan, result, session, user_id: int, body) -> None:
    _render_status_badge(t("autopilot.status_confirmed"), "var(--c-accent)")
    _render_summary_bar(result.summary)

    if plan.cart_snapshot_json:

        async def _rollback() -> None:
            snapshot = json.loads(plan.cart_snapshot_json)
            for entry in snapshot:
                await session.cart_service.remove(entry["sku"], entry["qty"])

            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                await repo.update_autopilot_plan_status(db, plan.id, "rolled_back")

            ui.notify(t("autopilot.rollback_confirm", n=len(snapshot)), type="info")
            ui.navigate.to("/autopilot")

        ui.button(
            t("autopilot.rollback"),
            icon="sym_r_undo",
            on_click=_rollback,
        ).props("flat color=negative size=sm").classes("q-mt-sm")
