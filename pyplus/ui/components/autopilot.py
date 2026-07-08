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
        from pyplus.services.autopilot import prepare_plan

        result = await prepare_plan(user_id, store_number=session.store_number)

        today = datetime.date.today()
        next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
        async with AsyncSessionLocal() as db:
            await repo.upsert_autopilot_plan(
                db,
                user_id,
                next_monday,
                result.to_json(),
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


# ── Draft plan ───────────────────────────────────────────────────────────────


async def _render_draft(plan, result, session, user_id: int, body, settings=None) -> None:
    store = session.store_number or 0
    cat_map: dict[str, str] = {}
    product_cache: dict = {}
    if store:
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.services.categories import parse_categories, top_category

        all_skus = [i.sku for i in result.items if i.sku]
        if all_skus:
            async with AsyncSessionLocal() as db:
                product_cache = await repo.get_product_cache_by_skus(db, store, all_skus)
            for sku, pc in product_cache.items():
                cats = parse_categories(getattr(pc, "categories_json", None))
                cat_map[sku] = top_category(cats)

    plan._sub_display = getattr(settings, "autopilot_sub_display", 5)
    plan._product_cache = product_cache

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

        review_items = [i for i in result.items if i.needs_review]
        if review_items:
            _render_review_section(review_items, plan, result, session, user_id, _draft_content)

        items_by_source: dict[str, list] = {}
        for item in result.items:
            if item.needs_review:
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
                    t(section_title_key), icon, section_items, cat_map, plan, result, _draft_content
                )

    _draft_content()


def _render_infobox() -> None:
    with ui.element("div").style(
        "display:flex;align-items:flex-start;gap:.5rem;padding:.625rem .75rem;"
        "background:#eee8f5;border-radius:var(--r-md);border:1px solid #d5cef0;"
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
    ):
        clear_cart = settings and getattr(settings, "autopilot_clear_cart", False)

        async def _do_confirm() -> None:
            if clear_cart:
                await session.cart_service.clear_all()

            cart_snapshot = []
            for item in result.items:
                if item.needs_review:
                    continue
                ok = await session.cart_service.add(
                    item.sku,
                    item.qty,
                    product_name=item.name,
                    product_price=item.price,
                    product_image=item.image_url,
                    source=item.source,
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

            added = len(cart_snapshot)
            cost = sum(i.price * i.qty for i in result.items if not i.needs_review)
            ui.notify(
                t("autopilot.confirmed_summary", n=added, cost=f"{cost:.2f}"),
                type="positive",
            )
            ui.navigate.to("/autopilot")

        async def _confirm() -> None:
            if clear_cart:
                _show_clear_confirm_dialog(_do_confirm)
            else:
                await _do_confirm()

        ui.button(
            t("autopilot.confirm"),
            icon="sym_r_add_shopping_cart",
            on_click=_confirm,
        ).props("unelevated dense no-caps size=sm color=deep-purple").style(
            "font-size:12px;font-weight:600"
        )

        async def _regenerate() -> None:
            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal
            from pyplus.services.autopilot import prepare_plan

            new_result = await prepare_plan(user_id, store_number=session.store_number)
            today = datetime.date.today()
            ws = today + datetime.timedelta(days=(7 - today.weekday()))
            async with AsyncSessionLocal() as db:
                await repo.upsert_autopilot_plan(db, user_id, ws, new_result.to_json())
            ui.navigate.to("/autopilot")

        ui.button(
            t("autopilot.regenerate"),
            icon="sym_r_refresh",
            on_click=_regenerate,
        ).props("flat dense no-caps size=sm").style("font-size:12px;font-weight:600")

        async def _delete() -> None:
            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                await repo.update_autopilot_plan_status(db, plan.id, "expired")
            ui.navigate.to("/autopilot")

        ui.button(
            t("autopilot.delete_plan"),
            on_click=_delete,
        ).props("flat dense no-caps color=negative size=sm").style("font-size:12px;font-weight:600")


def _show_clear_confirm_dialog(on_confirm) -> None:
    with ui.dialog(value=True) as dlg, ui.card().style("min-width:320px;max-width:420px"):
        ui.label(t("cart.clear_confirm_title")).style(
            "font-size:15px;font-weight:600;margin-bottom:.5rem"
        )
        ui.label(
            "De instelling 'Winkelwagen legen voor autopilot' staat aan. "
            "Je huidige winkelwagen wordt geleegd voordat de producten worden toegevoegd."
        ).style("font-size:13px;color:var(--c-text-3)")
        with ui.element("div").style(
            "display:flex;justify-content:flex-end;gap:.5rem;margin-top:.75rem"
        ):
            ui.button(t("action.cancel"), on_click=dlg.close).props("flat dense no-caps color=grey")

            async def _ok():
                dlg.close()
                await on_confirm()

            ui.button(t("action.confirm"), on_click=_ok).props(
                "unelevated dense no-caps color=deep-purple"
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
            _stat_pill(
                "sym_r_sell",
                f"{summary.promo_swaps} actie-wisselingen",
                bg="#fff3e0",
                fg="#92400e",
            )
        if summary.promo_savings > 0:
            _stat_pill(
                "sym_r_savings",
                f"bespaar {_eur(summary.promo_savings)}",
                bg="#e8f5e9",
                fg="#2e7d32",
            )
        if summary.needs_review_count > 0:
            _stat_pill(
                "sym_r_rate_review",
                t("autopilot.review_needed", n=summary.needs_review_count),
                bg="#fffbeb",
                fg="#f57c00",
            )
        elif summary.total_items > 0:
            _stat_pill(
                "sym_r_check_circle",
                t("autopilot.all_ready"),
                bg="#eee8f5",
                fg="var(--c-accent)",
            )
        if summary.free_delivery_met:
            _stat_pill(
                "sym_r_local_shipping",
                "Gratis bezorging inbegrepen",
                bg="#eee8f5",
                fg="var(--c-accent)",
            )


def _stat_pill(icon: str, text: str, bg: str = "#f5f4f1", fg: str = "var(--c-text-2)") -> None:
    with ui.element("div").style(
        f"display:inline-flex;align-items:center;gap:.25rem;padding:2px 8px;"
        f"background:{bg};border-radius:99px;font-size:11px;font-weight:600;color:{fg}"
    ):
        ui.icon(icon, size="14px")
        ui.label(text)


# ── Section cards (collapsible, interactive grid) ─────────────────────────


def _render_section_card(
    title: str, icon: str, items: list, cat_map: dict, plan, result, refresh_fn
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

        ordered = group_order(list(buckets))
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
            .style("background:#fff3e0;border-bottom-color:#f5d6a0")
        ):
            ui.icon("sym_r_sell", size="18px").style("color:#92400e")
            ui.label(
                f"{t('autopilot.section.promo_swaps')} · {len(items)} wisselingen"
                f" · bespaar {_eur(total_savings)}"
            ).style("font-size:13px;font-weight:600;color:#92400e;flex:1")
        with ui.element("div").style(
            "padding:.25rem .625rem .625rem;display:flex;flex-direction:column;gap:.5rem"
        ):
            for item in items:
                _render_promo_swap_card(item, plan, result, refresh_fn)


def _render_promo_swap_card(item, plan, result, refresh_fn) -> None:
    pc = getattr(plan, "_product_cache", {}).get(item.sku)
    subtitle = (pc.subtitle if pc else None) or ""

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
            with ui.element("div").style(
                "display:flex;gap:.5rem;align-items:center;margin-top:2px"
            ):
                ui.label(_eur(item.price)).style(
                    "font-size:12px;font-weight:600;color:var(--c-text)"
                )
                if item.promo_savings > 0:
                    ui.label(f"bespaar {_eur(item.promo_savings)}").style(
                        "font-size:11px;font-weight:700;color:var(--c-accent)"
                    )

        with ui.element("div").style("display:flex;gap:.375rem;flex-shrink:0"):
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


# ── Review section (substitutes) ────────────────────────────────────────────


def _render_review_section(items: list, plan, result, session, user_id: int, refresh_fn) -> None:
    with ui.element("div").classes("sp-ap-review"):
        with ui.element("div").classes("sp-ap-review__header"):
            ui.icon("sym_r_rate_review", size="18px").style("color:#f57c00")
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
        "var(--c-brand)" if score_pct >= 70 else "#f59e0b" if score_pct >= 40 else "#ef4444"
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
