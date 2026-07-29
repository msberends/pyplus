"""Settings page — account, ML preferences, ntfy, exports."""

from __future__ import annotations

import asyncio
import logging

from nicegui import app, ui

from pyplus.i18n import t
from pyplus.ml.interface import DayPreference, UserSettings
from pyplus.session import manager
from pyplus.ui.components.nav import create_nav_rail
from pyplus.ui.theme import apply_theme

log = logging.getLogger(__name__)

_DAY_LABELS = {
    "ma": "Ma",
    "di": "Di",
    "wo": "Wo",
    "do": "Do",
    "vr": "Vr",
    "za": "Za",
    "zo": "Zo",
}


async def create_settings_page() -> None:
    user_id = app.storage.user.get("user_id")
    session = manager.get(user_id) if user_id else None
    if session is None:
        app.storage.browser["_login_next"] = "/settings"
        ui.navigate.to("/login")
        return

    apply_theme()

    # Load current settings from DB
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        settings_json = await repo.get_user_settings_json(db, user_id)
        user = await repo.get_user_by_id(db, user_id)
        sync_states = await repo.get_all_sync_states(db, user_id)
    try:
        settings = UserSettings.model_validate_json(settings_json)
    except Exception:
        settings = UserSettings()

    async def _save() -> None:
        async with AsyncSessionLocal() as db:
            await repo.save_user_settings_json(db, user_id, settings.model_dump_json())
        # Keep the live session in sync so changes take effect without re-login
        # (already-rendered lanes update on their next refresh / page visit).
        session.set_settings(settings)

    with ui.element("div").classes("sp-cockpit-root"):
        create_nav_rail(active="settings", user_display_name=session.display_name)

        with ui.element("div").classes("sp-page-content"):
            ui.label(t("settings.title")).style(
                "font-size:22px;font-weight:700;color:var(--c-text);"
                "letter-spacing:-.3px;margin-bottom:1.5rem;display:block"
            )

            # Two-column layout on desktop, single column on mobile
            with ui.element("div").style(
                # min(380px, 100%) lets the column collapse to the viewport width on
                # narrow phones instead of forcing a 380px column (horizontal scroll).
                "display:grid;grid-template-columns:repeat(auto-fit,minmax(min(380px,100%),1fr));"
                "gap:1rem;align-items:start"
            ):
                # ── Left column ────────────────────────────────────────────
                with ui.element("div").style("display:flex;flex-direction:column;gap:1rem"):
                    _section_card(
                        t("settings.account.title"),
                        lambda: _render_account(session, user, user_id),
                    )
                    _section_card(
                        t("settings.api.title"),
                        lambda: _render_api_key(user, user_id),
                    )
                    _section_card("Weergave & gedrag", lambda: _render_behaviour(settings, _save))
                    _section_card(
                        "Indeling & sortering",
                        lambda: _render_organisation(settings, _save),
                    )
                    _section_card(
                        t("settings.substitute.title"),
                        lambda: _render_substitutes(settings, _save),
                    )
                    _section_card(t("settings.ntfy.title"), lambda: _render_ntfy(settings, _save))
                    _section_card(
                        "Agenda-abonnement",
                        lambda: _render_ical(settings, user_id, session, _save),
                    )

                # ── Right column ───────────────────────────────────────────
                with ui.element("div").style("display:flex;flex-direction:column;gap:1rem"):
                    _section_card_autopilot(
                        t("settings.ml.autopilot"),
                        lambda: _render_ml_autopilot(settings, _save),
                    )
                    _section_card(
                        t("settings.ml.title"),
                        lambda: _render_ml(settings, user_id, _save),
                    )
                    _section_card(
                        t("settings.weather.title"),
                        lambda: _render_weather(settings, _save),
                    )

                    from pyplus.jobs.preload import scheduler_next_runs

                    next_runs = scheduler_next_runs()
                    _section_card(
                        "Gegevens & synchronisatie",
                        lambda: _render_sync_status(session, user_id, sync_states, next_runs),
                    )


def _section_card(title: str, body_fn) -> None:
    with ui.element("div").style(
        "background:var(--c-surface);border:1px solid var(--c-border);"
        "border-radius:var(--r-xl);padding:1.25rem;margin-bottom:1rem"
    ):
        ui.label(title).style(
            "font-size:15px;font-weight:700;color:var(--c-text);margin-bottom:.875rem;display:block"
        )
        body_fn()


def _section_card_autopilot(title: str, body_fn) -> None:
    with ui.element("div").style(
        "background:var(--c-surface);border:1px solid var(--c-accent-border);"
        "border-radius:var(--r-xl);padding:1.25rem;margin-bottom:1rem;"
        "box-shadow:inset 3px 0 0 0 var(--c-accent)"
    ):
        with ui.element("div").style(
            "display:flex;align-items:center;gap:.5rem;margin-bottom:.875rem"
        ):
            ui.icon("sym_r_robot_2", size="20px").style("color:var(--c-accent)")
            ui.label(title).style(
                "font-size:15px;font-weight:700;color:var(--c-accent);display:block"
            )
        body_fn()


def _infobox(
    text: str,
    icon: str = "sym_r_info",
    color: str = "var(--c-brand-tint)",
    border: str = "var(--c-brand-tint-2)",
    text_color: str = "var(--c-brand-dark)",
) -> None:
    """Styled information box for explaining settings to the user."""
    with ui.element("div").style(
        f"display:flex;align-items:flex-start;gap:.5rem;padding:.625rem .75rem;"
        f"background:{color};border-radius:var(--r-md);border:1px solid {border};"
        f"margin-bottom:.75rem"
    ):
        ui.icon(icon, size="16px").style(f"color:{text_color};flex-shrink:0;margin-top:1px")
        ui.label(text).style(f"font-size:12px;color:{text_color};line-height:1.55")


def _render_account(session, user, user_id: int) -> None:
    from pyplus.security import secrets

    # PLUS e-mail
    email = ""
    if user and user.plus_email_enc:
        email = secrets.decrypt(user.plus_email_enc) or ""
    if email:
        with ui.element("div").style("margin-bottom:.625rem"):
            ui.label("PLUS account").style(
                "font-size:11px;font-weight:600;color:var(--c-text-4);letter-spacing:.06em;text-transform:uppercase"
            )
            ui.label(email).style("font-size:14px;color:var(--c-text-2)")
    elif user and user.display_name:
        with ui.element("div").style("margin-bottom:.625rem"):
            ui.label("Ingelogd als").style(
                "font-size:11px;font-weight:600;color:var(--c-text-4);letter-spacing:.06em;text-transform:uppercase"
            )
            ui.label(user.display_name).style("font-size:14px;color:var(--c-text-2)")

    # Winkel
    if user and user.store_number:
        with ui.element("div").style("margin-bottom:1rem"):
            ui.label("Winkel").style(
                "font-size:11px;font-weight:600;color:var(--c-text-4);letter-spacing:.06em;text-transform:uppercase"
            )
            # Store name (e.g. "PLUS Wolters") is captured at login; fall back to the
            # bare number for users whose name hasn't been captured yet.
            store_label = (
                f"{user.store_name} (#{user.store_number})"
                if getattr(user, "store_name", "")
                else f"PLUS winkel #{user.store_number}"
            )
            ui.label(store_label).style("font-size:14px;color:var(--c-text-2)")
    else:
        ui.element("div").style("margin-bottom:1rem")

    # Display name — controls the greeting on the login screen.
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    name_input = (
        ui.input(
            label="Weergavenaam",
            value=(user.display_name if user else "") or "",
            placeholder="Bijv. je voornaam",
        )
        .props("outlined dense")
        .style("width:100%;max-width:320px;margin-bottom:.25rem")
    )
    ui.label("Gebruikt voor de begroeting bij het inloggen.").style(
        "font-size:11px;color:var(--c-text-4);margin-bottom:1rem;display:block"
    )

    async def _save_name() -> None:
        new_name = (name_input.value or "").strip()
        async with AsyncSessionLocal() as db:
            await repo.set_user_display_name(db, user_id, new_name)
        session.display_name = new_name or session.display_name
        ui.notify("Naam opgeslagen", type="positive", position="top", timeout=1500)

    name_input.on("blur", lambda _: asyncio.ensure_future(_save_name()))

    async def _logout() -> None:
        uid = app.storage.user.get("user_id")
        if uid:
            await manager.close(uid)
            app.storage.user.clear()
        ui.navigate.to("/login")

    ui.button(t("settings.logout"), icon="sym_r_logout", on_click=_logout).props(
        "flat rounded no-caps color=negative"
    ).style("font-size:13px")


def _render_api_key(user, user_id: int) -> None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    _infobox(t("settings.api.info"))

    has_key = user.api_key_hash is not None

    status_label = ui.label(
        t("settings.api.active") if has_key else t("settings.api.inactive")
    ).style(
        "font-size:12px;font-weight:600;display:block;margin-bottom:.75rem;"
        f"color:{'var(--c-brand-dark)' if has_key else 'var(--c-text-4)'}"
    )

    key_display = ui.element("div").style("display:none")

    async def _generate() -> None:
        from pyplus.api.auth import generate_api_key, hash_api_key

        key = generate_api_key()
        async with AsyncSessionLocal() as db:
            await repo.set_api_key_hash(db, user_id, hash_api_key(key))
        user.api_key_hash = "set"
        status_label.set_text(t("settings.api.active"))
        status_label.style(
            "font-size:12px;font-weight:600;display:block;margin-bottom:.75rem;"
            "color:var(--c-brand-dark)"
        )
        key_display.style("display:block;margin-bottom:.75rem")
        key_display.clear()
        with key_display:
            ui.label(t("settings.api.generated")).style(
                "font-size:11px;color:var(--c-warning-dark);margin-bottom:.375rem;display:block"
            )
            ui.input(value=key).props("outlined dense readonly").style(
                "width:100%;font-family:monospace;font-size:12px"
            )
        revoke_btn.set_visibility(True)

    async def _revoke() -> None:
        async with AsyncSessionLocal() as db:
            await repo.clear_api_key_hash(db, user_id)
        user.api_key_hash = None
        status_label.set_text(t("settings.api.inactive"))
        status_label.style(
            "font-size:12px;font-weight:600;display:block;margin-bottom:.75rem;"
            "color:var(--c-text-4)"
        )
        key_display.style("display:none")
        key_display.clear()
        revoke_btn.set_visibility(False)
        ui.notify(t("settings.api.revoked"), type="info", position="top", timeout=1500)

    with ui.row().style("gap:.625rem"):
        ui.button(
            t("settings.api.generate"),
            icon="sym_r_key",
            on_click=lambda: asyncio.ensure_future(_generate()),
        ).props("flat rounded no-caps color=primary size=sm").style("font-size:12px")

        revoke_btn = (
            ui.button(
                t("settings.api.revoke"),
                icon="sym_r_block",
                on_click=lambda: asyncio.ensure_future(_revoke()),
            )
            .props("flat rounded no-caps color=negative size=sm")
            .style("font-size:12px")
        )
        revoke_btn.set_visibility(has_key)


def _toggle_setting(settings: UserSettings, attr: str, label: str, hint: str, save_fn) -> None:
    """One labelled on/off row bound to a boolean UserSettings attribute."""
    with ui.row().style(
        "align-items:flex-start;gap:.75rem;padding:.5rem 0;border-top:1px solid var(--c-border)"
    ):
        sw = ui.switch(value=getattr(settings, attr)).props("color=primary size=sm")
        with ui.element("div").style("flex:1"):
            ui.label(label).style("font-size:13px;font-weight:600;color:var(--c-text)")
            if hint:
                ui.label(hint).style("font-size:11px;color:var(--c-text-3);line-height:1.5")

        async def _on_change(a=attr, s=sw) -> None:
            setattr(settings, a, bool(s.value))
            await save_fn()

        sw.on("update:model-value", lambda e: asyncio.ensure_future(_on_change()))


def _select_setting(
    settings: UserSettings, attr: str, label: str, hint: str, options: dict, save_fn
) -> None:
    """One labelled dropdown bound to a string UserSettings attribute."""
    with ui.element("div").style("padding:.5rem 0;border-top:1px solid var(--c-border)"):
        ui.label(label).style("font-size:13px;font-weight:600;color:var(--c-text)")
        if hint:
            ui.label(hint).style(
                "font-size:11px;color:var(--c-text-3);line-height:1.5;"
                "margin-bottom:.375rem;display:block"
            )
        sel = (
            ui.select(options, value=getattr(settings, attr))
            .props("outlined dense options-dense")
            .style("max-width:280px")
        )

        async def _on(a=attr, s=sel) -> None:
            setattr(settings, a, s.value)
            await save_fn()

        sel.on("update:model-value", lambda e: asyncio.ensure_future(_on()))


# Variety presets: (selection_method, temperature, label, description)
_VARIETY_PRESETS: dict[int, tuple[str, float | None, str, str]] = {
    1: ("greedy", None, "Voorspelbaar", "Elke week hetzelfde weekmenu — volledig deterministisch."),
    2: ("softmax", 0.2, "Stabiel", "Bijna altijd de beste keuze, zelden een verrassing."),
    3: (
        "softmax",
        0.5,
        "Gevarieerd",
        "Goede balans: vertrouwde gerechten met wekelijkse afwisseling.",
    ),
    4: ("softmax", 1.0, "Avontuurlijk", "Merkbaar wisselend — elk plan ziet er anders uit."),
    5: (
        "softmax",
        2.0,
        "Verrassend",
        "Heel vrij — alle redelijk scorende gerechten komen aan bod.",
    ),
}


def _detect_variety_level(settings: UserSettings) -> int:
    """Reverse-map current method+temperature to a preset level 1–5, or 0 if custom."""
    for level, (method, temp, _, _) in _VARIETY_PRESETS.items():
        if settings.ml_selection_method != method:
            continue
        if temp is None:
            return level
        if abs(settings.ml_temperature - temp) < 0.01:
            return level
    return 0  # custom / advanced


def _render_variety_control(settings: UserSettings, save_fn) -> None:
    """Prominent layman 1–5 variety slider — maps to method+temperature presets."""
    actual_level = _detect_variety_level(settings)
    display_level = actual_level if actual_level > 0 else 3

    preset = _VARIETY_PRESETS[display_level]

    with ui.element("div").style("padding:.75rem 0;border-top:1px solid var(--c-border)"):
        with ui.row().style(
            "align-items:center;justify-content:space-between;margin-bottom:.25rem"
        ):
            ui.label("Variatie in weekmenu").style(
                "font-size:13px;font-weight:600;color:var(--c-text)"
            )
            if actual_level == 0:
                ui.label("Aangepast").style(
                    "font-size:10px;font-weight:600;color:var(--c-accent);"
                    "background:var(--c-brand-tint);padding:1px 8px;border-radius:999px"
                )

        name_lbl = ui.label(preset[2]).style(
            "font-size:12px;font-weight:700;color:var(--c-accent);display:block"
        )
        desc_lbl = ui.label(preset[3]).style(
            "font-size:11px;color:var(--c-text-3);line-height:1.55;display:block;margin-bottom:.625rem"
        )

        with ui.row().style("align-items:center;gap:.5rem"):
            ui.label("Voorspelbaar").style(
                "font-size:10px;color:var(--c-text-4);white-space:nowrap;flex-shrink:0"
            )
            sld = (
                ui.slider(min=1, max=5, step=1, value=display_level)
                .props("color=primary snap markers")
                .style("flex:1;max-width:220px")
            )
            ui.label("Verrassend").style(
                "font-size:10px;color:var(--c-text-4);white-space:nowrap;flex-shrink:0"
            )

        def _update_display(e) -> None:
            v = int(sld.value)
            p = _VARIETY_PRESETS.get(v, _VARIETY_PRESETS[3])
            name_lbl.set_text(p[2])
            desc_lbl.set_text(p[3])

        sld.on("update:model-value", _update_display)

        async def _save_variety() -> None:
            v = int(sld.value)
            method, temp, _, _ = _VARIETY_PRESETS.get(v, _VARIETY_PRESETS[3])
            settings.ml_selection_method = method
            settings.ml_temperature = temp if temp is not None else 1.0
            await save_fn()

        sld.on("change", lambda e: asyncio.ensure_future(_save_variety()))


_CART_SORT_OPTS = {
    "cart": "Winkelwagen-volgorde",
    "name": "Naam (A–Z)",
    "price": "Prijs (hoog–laag)",
}
_STAPLES_SORT_OPTS = {
    "smart": "Slim (binnenkort op)",
    "name": "Naam (A–Z)",
    "price": "Prijs (hoog–laag)",
}


def _render_organisation(settings: UserSettings, save_fn) -> None:
    """Grouping + sorting for the cart and staples lanes."""
    ui.label("Bepaal hoe je winkelwagen en vaste boodschappen geordend zijn.").style(
        "font-size:12px;color:var(--c-text-3);margin-bottom:.25rem;display:block"
    )

    _subhead = "font-size:11px;font-weight:700;color:var(--c-text-4);letter-spacing:.06em;text-transform:uppercase;margin-top:.625rem;display:block"

    ui.label("Winkelwagen").style(_subhead)
    _toggle_setting(
        settings,
        "cart_group_by_category",
        "Groeperen per categorie",
        "Toon de winkelwagen onder kopjes per productgroep.",
        save_fn,
    )
    _select_setting(settings, "cart_sort", "Sortering", "", _CART_SORT_OPTS, save_fn)

    ui.label("Vaste boodschappen").style(_subhead)
    _toggle_setting(
        settings,
        "staples_group_by_category",
        "Groeperen per categorie",
        "Toon vaste boodschappen onder kopjes per productgroep.",
        save_fn,
    )
    _select_setting(settings, "staples_sort", "Sortering", "", _STAPLES_SORT_OPTS, save_fn)

    ui.label("Aanbiedingen").style(_subhead)
    _toggle_setting(
        settings,
        "deals_group_by_category",
        "Groeperen per categorie",
        "Toon aanbiedingen onder kopjes per productgroep (zoals PLUS ze indeelt).",
        save_fn,
    )


def _render_behaviour(settings: UserSettings, save_fn) -> None:
    """Display & behaviour preferences — purely client-side rendering toggles."""
    ui.label("Bepaal wat de app toont en hoe deze zich gedraagt.").style(
        "font-size:12px;color:var(--c-text-3);margin-bottom:.25rem;display:block"
    )
    _toggle_setting(
        settings,
        "show_dish_metadata",
        "Gerecht-eigenschappen tonen",
        "Toon vlees/bereidingstijd/groente bij gerechten en in het weekmenu.",
        save_fn,
    )
    _toggle_setting(
        settings,
        "show_promo_tags",
        "Aanbieding-labels tonen",
        "Markeer producten in je winkelwagen en vaste boodschappen die in de aanbieding zijn.",
        save_fn,
    )
    _toggle_setting(
        settings,
        "show_cart_savings",
        "Bespaartips tonen",
        "Stel goedkopere verpakkingen voor in de winkelwagen.",
        save_fn,
    )
    _toggle_setting(
        settings,
        "show_replenish_hints",
        "Voorraad-hints tonen",
        "Markeer vaste boodschappen die waarschijnlijk binnenkort op zijn (vereist slimme suggesties).",
        save_fn,
    )
    _toggle_setting(
        settings,
        "confirm_clear_slot",
        "Bevestigen voor verwijderen",
        "Vraag om bevestiging voordat een gerecht uit het weekmenu wordt gehaald.",
        save_fn,
    )
    _toggle_setting(
        settings,
        "hide_unavailable_search",
        "Niet-verkrijgbare zoekresultaten verbergen",
        "Toon in de zoekbalk alleen producten die nu te koop zijn.",
        save_fn,
    )

    # Numeric: max search results
    with ui.element("div").style("padding:.625rem 0 0;border-top:1px solid var(--c-border)"):
        ui.label("Aantal zoekresultaten").style(
            "font-size:13px;font-weight:600;color:var(--c-text)"
        )
        ui.label("Hoeveel producten de zoekbalk maximaal toont.").style(
            "font-size:11px;color:var(--c-text-3);line-height:1.5;margin-bottom:.5rem;display:block"
        )
        count_label = ui.label(str(settings.search_result_limit)).style(
            "font-size:12px;color:var(--c-text-2);font-weight:600"
        )
        sld = (
            ui.slider(min=6, max=48, step=6, value=settings.search_result_limit)
            .props("color=primary")
            .style("max-width:320px")
        )
        sld.on("update:model-value", lambda e: count_label.set_text(str(int(sld.value))))

        async def _save_limit() -> None:
            settings.search_result_limit = int(sld.value)
            await save_fn()

        sld.on("change", lambda e: asyncio.ensure_future(_save_limit()))


# ── Substitute Settings ──────────────────────────────────────────────────────


_PRICE_RANGE_OPTS = {
    "any": t("settings.substitute.price_any"),
    "similar": t("settings.substitute.price_similar"),
    "cheaper": t("settings.substitute.price_cheaper"),
}


def _render_substitutes(settings: UserSettings, save_fn) -> None:
    """Settings for the substitute product finder."""
    _infobox(t("settings.substitute.how_it_works"))
    _toggle_setting(
        settings,
        "sub_prefer_same_brand",
        t("settings.substitute.prefer_brand"),
        t("settings.substitute.prefer_brand_hint"),
        save_fn,
    )
    _toggle_setting(
        settings,
        "sub_prefer_bought",
        t("settings.substitute.prefer_bought"),
        t("settings.substitute.prefer_bought_hint"),
        save_fn,
    )
    _select_setting(
        settings,
        "sub_price_range",
        t("settings.substitute.price_range"),
        "",
        _PRICE_RANGE_OPTS,
        save_fn,
    )

    with ui.element("div").style("padding:.625rem 0 0;border-top:1px solid var(--c-border)"):
        ui.label(t("settings.substitute.max_results")).style(
            "font-size:13px;font-weight:600;color:var(--c-text)"
        )
        ui.label(t("settings.substitute.max_results_hint")).style(
            "font-size:11px;color:var(--c-text-3);line-height:1.5;margin-bottom:.5rem;display:block"
        )
        count_label = ui.label(str(settings.sub_max_results)).style(
            "font-size:12px;color:var(--c-text-2);font-weight:600"
        )
        sld = (
            ui.slider(min=4, max=24, step=4, value=settings.sub_max_results)
            .props("color=primary")
            .style("max-width:320px")
        )
        sld.on("update:model-value", lambda e: count_label.set_text(str(int(sld.value))))

        async def _save_limit() -> None:
            settings.sub_max_results = int(sld.value)
            await save_fn()

        sld.on("change", lambda e: asyncio.ensure_future(_save_limit()))


# ── ML Settings ───────────────────────────────────────────────────────────────


def _render_ml(settings: UserSettings, user_id: int, save_fn) -> None:
    # Master toggle
    with ui.row().style("align-items:flex-start;gap:.75rem;margin-bottom:.875rem"):
        master = ui.switch(value=settings.ml_enabled).props("color=primary")
        with ui.element("div"):
            ui.label(t("settings.ml.master")).style(
                "font-size:14px;font-weight:600;color:var(--c-text)"
            )
            ui.label(t("settings.ml.master_hint")).style(
                "font-size:12px;color:var(--c-text-3);line-height:1.5"
            )

    # Sub-toggles (indented, only interactive when master is on)
    with ui.element("div").style("padding-left:2.5rem").bind_visibility_from(master, "value"):

        def _sub_toggle(label: str, hint: str, attr: str) -> None:
            val = getattr(settings, attr)
            with ui.row().style(
                "align-items:flex-start;gap:.625rem;padding:.5rem 0;"
                "border-top:1px solid var(--c-border)"
            ):
                sw = ui.switch(value=val).props("color=primary size=sm")
                with ui.element("div"):
                    ui.label(label).style("font-size:13px;font-weight:600;color:var(--c-text)")
                    if hint:
                        ui.label(hint).style("font-size:11px;color:var(--c-text-3);line-height:1.5")

                async def _on_change(e, a=attr, s=sw) -> None:
                    setattr(settings, a, s.value)
                    await save_fn()

                sw.on(
                    "update:model-value",
                    lambda e, a=attr, s=sw: asyncio.ensure_future(_on_change(e, a, s)),
                )

        _sub_toggle(
            "Weekmenu-suggesties",
            "Stelt gerechten voor op basis van wat je eerder kookte en wat in de aanbieding is.",
            "ml_recommender",
        )
        _sub_toggle(
            t("settings.ml.replenish"),
            "Markeert vaste boodschappen die je waarschijnlijk binnenkort nodig hebt.",
            "ml_replenish",
        )
        _sub_toggle(
            "Aanbiedingen sorteren op relevantie",
            "Toont aanbiedingen die passen bij jouw aankoopgeschiedenis en weekmenu bovenaan.",
            "ml_promo_match",
        )

        _render_variety_control(settings, save_fn)

        # ── 📊 Weegfactoren ──────────────────────────────────────────────
        _render_ml_weights(settings, save_fn)

        # ── 📅 Dagvoorkeuren ─────────────────────────────────────────────
        _render_ml_day_preferences(settings, save_fn)

        # ── 🎯 Weekdoelen ────────────────────────────────────────────────
        _render_ml_week_constraints(settings, save_fn)

        # ── 🔬 Geavanceerd ───────────────────────────────────────────────
        _render_ml_advanced(settings, save_fn)

    async def _on_master(e) -> None:
        settings.ml_enabled = master.value
        await save_fn()

    master.on("update:model-value", lambda e: asyncio.ensure_future(_on_master(e)))

    # Recompute button
    ui.element("div").style("height:.75rem")

    recompute_label = ui.label("").style("font-size:12px;color:var(--c-text-3);display:none")

    async def _recompute() -> None:
        recompute_btn.props("loading=true")
        try:
            from pyplus.jobs.registry import recompute_ml

            await recompute_ml(user_id=user_id)
            recompute_label.set_text("Klaar.")
            recompute_label.style("display:block;color:var(--c-brand-dark)")
        except Exception:
            log.warning("ML recompute failed", exc_info=True)
            recompute_label.set_text("Mislukt — probeer het later opnieuw.")
            recompute_label.style("display:block;color:var(--c-danger)")
        finally:
            recompute_btn.props("loading=false")

    recompute_btn = (
        ui.button(
            "Herbereken suggesties",
            icon="sym_r_refresh",
            on_click=lambda: asyncio.ensure_future(_recompute()),
        )
        .props("flat rounded no-caps color=primary size=sm")
        .style("font-size:12px")
    )


def _render_ml_weights(settings: UserSettings, save_fn) -> None:
    """Signal weight sliders inside a collapsible expansion."""
    with (
        ui.expansion("Weegfactoren", icon="sym_r_tune", value=False)
        .style("border-top:1px solid var(--c-border);margin-top:.625rem")
        .props("dense")
    ):
        _infobox(
            "Elk signaal draagt bij aan de totaalscore van een gerecht per dagslot. "
            "De gewichten bepalen hoeveel invloed elk signaal heeft — zet een gewicht op 0% "
            "om een signaal volledig uit te schakelen. De totaalscore is een gewogen som; "
            "hogere waarden krijgen meer voorkeur bij het plannen. "
            "Wijzigingen gelden pas na 'Herbereken suggesties' hieronder.",
        )

        def _weight(label: str, attr: str, hint: str = "") -> None:
            with ui.element("div").style("padding:.375rem 0"):
                with ui.row().style("align-items:center;justify-content:space-between;width:100%"):
                    with ui.element("div").style("flex:1"):
                        ui.label(label).style("font-size:12px;color:var(--c-text-2)")
                        if hint:
                            ui.label(hint).style(
                                "font-size:10px;color:var(--c-text-4);line-height:1.4"
                            )
                    val_lbl = ui.label(f"{getattr(settings, attr):.0%}").style(
                        "font-size:11px;color:var(--c-text-3);font-weight:600"
                    )
                sl = ui.slider(min=0, max=1, step=0.05, value=getattr(settings, attr)).props(
                    "color=primary"
                )
                sl.on(
                    "update:model-value",
                    lambda e, lbl=val_lbl, s=sl: lbl.set_text(f"{float(s.value):.0%}"),
                )

                async def _save_weight(a=attr, s=sl) -> None:
                    setattr(settings, a, round(float(s.value), 2))
                    await save_fn()

                sl.on("change", lambda e, f=_save_weight: asyncio.ensure_future(f()))

        _weight(
            "Afwisseling / variatie",
            "ml_afwisseling",
            "Boost voor gerechten die je recent niet hebt klaargemaakt.",
        )
        _weight(
            "Vaste dagen (gewoontes)",
            "ml_vaste_dagen",
            "Boost als je een gerecht historisch vaak op deze weekdag klaarmaakt.",
        )
        _weight(
            "Voordeel (aanbiedingen)",
            "ml_voordeel",
            "Boost voor gerechten waarvan ingrediënten in de aanbieding zijn.",
        )
        _weight(
            "Voorraad (bijna op)",
            "ml_voorraad",
            "Boost voor gerechten die ingrediënten gebruiken die voorspeld bijna op zijn.",
        )
        _weight(
            "Categorie-spreiding",
            "ml_variatie",
            "Bevordert diversiteit in eiwit- en koolhydraatcategorieën over de week.",
        )
        _weight(
            t("settings.ml.ingredient_overlap"),
            "ml_ingredient_overlap",
            "Geeft voorkeur aan gerechten die ingrediënten delen — minder verspilling.",
        )
        _weight(
            t("settings.ml.budget"),
            "ml_budget",
            "Geeft voorkeur aan goedkopere gerechten op basis van ingrediëntprijzen.",
        )
        _weight(
            t("settings.ml.rating_weight"),
            "ml_rating_weight",
            "0% = sterren worden genegeerd · 100% = 1★ telt als ×0,33, 3★ neutraal, 5★ als ×1,67.",
        )
        _weight(
            "Weer: oven/airfryer vermijden",
            "ml_weather_no_oven",
            "Straft gerechten met oven of airfryer af op warme dagen (vereist Weer aan).",
        )
        _weight(
            "Weer: voorkeur koud",
            "ml_weather_cold",
            "Geeft voorkeur aan koude gerechten op warme dagen (vereist Weer aan).",
        )


def _render_ml_day_preferences(settings: UserSettings, save_fn) -> None:
    """Per-day planning preferences with a tab bar for Ma–Zo + a lunch panel."""
    from pyplus.db.models import MEAT_TYPES, PREP_TIME_BUCKETS, STARCH_TYPES
    from pyplus.ui.format import meat_emoji, meat_label, starch_emoji, starch_label

    with (
        ui.expansion(t("settings.ml.day_prefs"), icon="sym_r_calendar_month")
        .style("border-top:1px solid var(--c-border)")
        .props("dense")
    ):
        _infobox(
            "Stel per dag in welke gerechten het model mag voorstellen. Blokkeer "
            "bepaalde eiwittypes (bijv. vleesvrije maandag) of koolhydraten, of stel een"
            "maximum bereidingstijd in voor doordeweekse dagen. Dagen op 'uit' worden "
            "overgeslagen bij het automatisch invullen.",
        )

        with ui.tabs().style("margin-bottom:.5rem").props("dense inline-label") as tabs:
            day_tabs = {}
            for day_key, day_label in _DAY_LABELS.items():
                day_tabs[day_key] = ui.tab(day_key, label=day_label)
            ui.tab("lunch", label="Extra")

        with ui.tab_panels(tabs, value="ma").style("min-height:auto"):
            for day_key in _DAY_LABELS:
                with ui.tab_panel(day_key):
                    _render_single_day_pref(
                        settings,
                        day_key,
                        save_fn,
                        MEAT_TYPES,
                        STARCH_TYPES,
                        PREP_TIME_BUCKETS,
                        meat_emoji,
                        meat_label,
                        starch_emoji,
                        starch_label,
                    )
            with ui.tab_panel("lunch"):
                _infobox(
                    "Deze voorkeuren gelden voor alle vijf extra-slots. "
                    "De extra-slots delen dezelfde regels — ze worden niet "
                    "individueel ingesteld.",
                    icon="sym_r_skillet",
                    color="var(--c-accent-tint)",
                    border="var(--c-accent-border)",
                    text_color="var(--c-accent)",
                )
                _render_single_day_pref(
                    settings,
                    "lunch",
                    save_fn,
                    MEAT_TYPES,
                    STARCH_TYPES,
                    PREP_TIME_BUCKETS,
                    meat_emoji,
                    meat_label,
                    starch_emoji,
                    starch_label,
                )


def _get_day_pref(settings: UserSettings, key: str) -> DayPreference:
    """Load or initialise a DayPreference, migrating old field names on first read."""
    raw = settings.day_preferences.get(key, {})
    if isinstance(raw, DayPreference):
        return raw
    if isinstance(raw, dict):
        raw = dict(raw)  # don't mutate the stored value
        mt: dict = {}
        for x in raw.pop("allowed_meat_types", []):
            mt[x] = "enforce"
        for x in raw.pop("blocked_meat_types", []):
            mt.setdefault(x, "disallow")
        if mt:
            raw["meat_types"] = mt
        st: dict = {}
        for x in raw.pop("preferred_starch_types", []):
            st[x] = "enforce"
        for x in raw.pop("blocked_starch_types", []):
            st.setdefault(x, "disallow")
        if st:
            raw["starch_types"] = st
        if raw.pop("no_unhealthy", False):
            raw["unhealthy"] = "disallow"
        elif raw.pop("only_unhealthy", False):
            raw["unhealthy"] = "enforce"
    return DayPreference.model_validate(raw)


def _save_day_pref(settings: UserSettings, key: str, pref: DayPreference) -> None:
    """Write a DayPreference back into the settings dict."""
    if key == "lunch":
        for i in range(1, 6):
            settings.day_preferences[f"lunch{i}"] = pref.model_dump()
    else:
        settings.day_preferences[key] = pref.model_dump()


def _render_single_day_pref(
    settings,
    day_key,
    save_fn,
    meat_types,
    starch_types,
    prep_buckets,
    meat_emoji_fn,
    meat_label_fn,
    starch_emoji_fn,
    starch_label_fn,
) -> None:
    pref = _get_day_pref(settings, day_key)

    # Enabled toggle
    with ui.row().style("align-items:center;gap:.625rem;margin-bottom:.5rem"):
        en_sw = ui.switch(value=pref.enabled).props("color=primary size=sm")
        ui.label(t("settings.ml.day_enabled")).style(
            "font-size:13px;font-weight:600;color:var(--c-text)"
        )

    async def _on_enabled(e, k=day_key) -> None:
        p = _get_day_pref(settings, k)
        p.enabled = en_sw.value
        _save_day_pref(settings, k, p)
        await save_fn()

    en_sw.on("update:model-value", lambda e: asyncio.ensure_future(_on_enabled(e)))

    # Max prep time
    prep_opts = {None: t("settings.ml.day_no_limit")}
    for m in prep_buckets:
        prep_opts[m] = f"≤{m} min"

    prep_sel = (
        ui.select(prep_opts, value=pref.max_prep_minutes, label=t("settings.ml.day_max_prep"))
        .props("outlined dense options-dense")
        .style("max-width:220px;margin-bottom:.5rem")
    )

    async def _on_prep(e, k=day_key) -> None:
        p = _get_day_pref(settings, k)
        p.max_prep_minutes = prep_sel.value
        _save_day_pref(settings, k, p)
        await save_fn()

    prep_sel.on("update:model-value", lambda e: asyncio.ensure_future(_on_prep(e)))

    # Meat types — tri-state chips
    ui.label(t("settings.ml.day_meat_blocked")).style(
        "font-size:12px;font-weight:600;color:var(--c-text-2);margin-bottom:.25rem"
    )
    _render_tristate_chips(
        items=list(meat_types),
        constraints=dict(pref.meat_types),
        label_fn=lambda m: f"{meat_emoji_fn(m)} {meat_label_fn(m)}".strip(),
        on_change=lambda new, k=day_key: asyncio.ensure_future(
            _update_day_constraint(settings, k, "meat_types", new, save_fn)
        ),
    )

    # Starch types — tri-state chips
    ui.label(t("settings.ml.day_starch_blocked")).style(
        "font-size:12px;font-weight:600;color:var(--c-text-2);margin-top:.5rem;margin-bottom:.25rem"
    )
    _render_tristate_chips(
        items=list(starch_types),
        constraints=dict(pref.starch_types),
        label_fn=lambda s: f"{starch_emoji_fn(s)} {starch_label_fn(s)}".strip(),
        on_change=lambda new, k=day_key: asyncio.ensure_future(
            _update_day_constraint(settings, k, "starch_types", new, save_fn)
        ),
    )

    # Unhealthy — single tri-state chip
    ui.label(t("settings.ml.day_unhealthy")).style(
        "font-size:12px;font-weight:600;color:var(--c-text-2);margin-top:.5rem;margin-bottom:.25rem"
    )
    _render_tristate_chips(
        items=["ongezond"],
        constraints={"ongezond": pref.unhealthy} if pref.unhealthy else {},
        label_fn=lambda _: "🍔 Ongezond",
        on_change=lambda new, k=day_key: asyncio.ensure_future(
            _update_day_constraint(settings, k, "unhealthy", new.get("ongezond"), save_fn)
        ),
    )


async def _update_day_constraint(
    settings: UserSettings, day_key: str, field: str, value, save_fn
) -> None:
    pref = _get_day_pref(settings, day_key)
    setattr(pref, field, value)
    _save_day_pref(settings, day_key, pref)
    await save_fn()


def _render_tristate_chips(
    items: list[str],
    constraints: dict,
    label_fn,
    on_change,
) -> None:
    """Tri-state chips: neutral (grey) → enforce (green ✓) → disallow (red ✗) → neutral.

    Uses a refreshable inner function so the chip fully re-renders on each click —
    NiceGUI's selectable chip only has two native states, so we control appearance
    ourselves via refresh rather than relying on update:selected.
    """

    @ui.refreshable
    def _draw() -> None:
        with ui.element("div").style(
            "display:flex;flex-wrap:wrap;gap:.375rem;margin-bottom:.25rem"
        ):
            for item in items:
                mode = constraints.get(item)
                if mode == "enforce":
                    color, suffix = "positive", " ✓"
                elif mode == "disallow":
                    color, suffix = "negative", " ✗"
                else:
                    color, suffix = "outline", ""
                chip = (
                    ui.chip(label_fn(item) + suffix)
                    .props(f"color={color} size=sm clickable")
                    .style("font-size:11px;cursor:pointer")
                )

                def _cycle(_e, it=item) -> None:
                    cur = constraints.get(it)
                    if cur is None:
                        constraints[it] = "enforce"
                    elif cur == "enforce":
                        constraints[it] = "disallow"
                    else:
                        del constraints[it]
                    on_change(dict(constraints))
                    _draw.refresh()

                chip.on("click", _cycle)

    _draw()


def _render_ml_week_constraints(settings: UserSettings, save_fn) -> None:
    """Cross-week diversity constraints."""
    with (
        ui.expansion(t("settings.ml.week_goals"), icon="sym_r_rule")
        .style("border-top:1px solid var(--c-border)")
        .props("dense")
    ):
        _infobox(
            "Deze regels gelden over de hele week. Het model probeert "
            "hieraan te voldoen bij het invullen van lege slots. Als alle regels tegelijk "
            "niet haalbaar zijn (bijv. min. 5 vega én min. 5 vis bij 7 avondeten), wordt "
            "terugevallen op de best mogelijke verdeling.",
        )

        wc = settings.week_constraints

        def _int_setting(label: str, attr: str, min_v: int, max_v: int, hint: str = "") -> None:
            with ui.element("div").style("padding:.375rem 0"):
                with ui.row().style("align-items:center;gap:.625rem"):
                    with ui.element("div").style("flex:1"):
                        ui.label(label).style("font-size:12px;color:var(--c-text-2)")
                        if hint:
                            ui.label(hint).style(
                                "font-size:10px;color:var(--c-text-4);line-height:1.4"
                            )
                    num = (
                        ui.number(value=getattr(wc, attr), min=min_v, max=max_v)
                        .props("outlined dense")
                        .style("max-width:80px")
                    )

                async def _on(a=attr, n=num) -> None:
                    setattr(wc, a, int(n.value or 0))
                    settings.week_constraints = wc
                    await save_fn()

                num.on("change", lambda e, f=_on: asyncio.ensure_future(f()))

        _int_setting(
            t("settings.ml.min_vega"),
            "min_vega_days",
            0,
            7,
            "Minimaal aantal vegetarische dagen per week.",
        )
        _int_setting(
            t("settings.ml.max_vega"),
            "max_vega_days",
            0,
            7,
            "Maximaal aantal vegetarische dagen per week.",
        )
        _int_setting(
            t("settings.ml.min_fish"),
            "min_fish_days",
            0,
            7,
            "Minimaal aantal visdagen per week.",
        )
        _int_setting(
            t("settings.ml.max_same_meat"),
            "max_same_meat_type",
            1,
            7,
            "Max. keren dat één eiwittype (bijv. kip) in de week mag voorkomen.",
        )
        _int_setting(
            t("settings.ml.min_unique_starch"),
            "min_unique_starch_types",
            0,
            7,
            "Minimaal aantal verschillende koolhydraten (aardappels, pasta, rijst…).",
        )
        _int_setting(
            t("settings.ml.max_consec_meat"),
            "max_consecutive_same_meat",
            1,
            7,
            "Max. opeenvolgende dagen met dezelfde eiwitsoort.",
        )
        _int_setting(
            t("settings.ml.max_consec_starch"),
            "max_consecutive_same_starch",
            1,
            7,
            "Max. opeenvolgende dagen met dezelfde koolhydraten.",
        )
        _int_setting(
            t("settings.ml.max_red_meat"),
            "max_red_meat_days",
            0,
            7,
            "Max. dagen per week met rund of varken (beperkt rood vlees).",
        )

        # Target avg veg count (slider 0–3, step 0.5)
        with ui.element("div").style("padding:.5rem 0"):
            with ui.row().style("align-items:center;justify-content:space-between;width:100%"):
                with ui.element("div").style("flex:1"):
                    ui.label(t("settings.ml.target_veg")).style(
                        "font-size:12px;color:var(--c-text-2)"
                    )
                    ui.label(
                        "Streefgemiddelde hoeveelheid groenten per maaltijd (0 = geen doel)."
                    ).style("font-size:10px;color:var(--c-text-4);line-height:1.4")
                veg_lbl = ui.label(f"{wc.target_avg_veg_count or 0:.1f}").style(
                    "font-size:11px;color:var(--c-text-3);font-weight:600"
                )
            veg_sl = ui.slider(min=0, max=3, step=0.5, value=wc.target_avg_veg_count or 0).props(
                "color=primary"
            )
            veg_sl.on(
                "update:model-value",
                lambda e: veg_lbl.set_text(f"{float(veg_sl.value):.1f}"),
            )

            async def _save_veg() -> None:
                v = float(veg_sl.value)
                wc.target_avg_veg_count = v if v > 0 else None
                settings.week_constraints = wc
                await save_fn()

            veg_sl.on("change", lambda e: asyncio.ensure_future(_save_veg()))


def _render_ml_advanced(settings: UserSettings, save_fn) -> None:
    """Advanced ML knobs for power users."""
    with (
        ui.expansion(t("settings.ml.advanced"), icon="sym_r_science")
        .style("border-top:1px solid var(--c-border)")
        .props("dense")
    ):
        _infobox(
            "Voor fijnregeling. De Variatie-instelling hierboven is de makkelijke weg — "
            "hier stel je de onderliggende parameters in. Handmatige aanpassing "
            "zet de Variatie-instelling op 'Aangepast'.",
            icon="sym_r_science",
            color="var(--c-accent-tint)",
            border="var(--c-accent-border)",
            text_color="var(--c-accent)",
        )

        # Repeat cooldown
        with ui.element("div").style("padding:.375rem 0"):
            with ui.row().style("align-items:center;gap:.625rem"):
                with ui.element("div").style("flex:1"):
                    ui.label(t("settings.ml.cooldown")).style(
                        "font-size:12px;color:var(--c-text-2)"
                    )
                    ui.label(t("settings.ml.cooldown_hint")).style(
                        "font-size:10px;color:var(--c-text-4);line-height:1.4"
                    )
                cd_num = (
                    ui.number(value=settings.ml_repeat_cooldown_weeks, min=0, max=12)
                    .props("outlined dense suffix=weken")
                    .style("max-width:120px")
                )

            async def _save_cd() -> None:
                settings.ml_repeat_cooldown_weeks = int(cd_num.value or 0)
                await save_fn()

            cd_num.on("change", lambda e: asyncio.ensure_future(_save_cd()))

        # Novelty ratio slider
        _adv_slider(
            t("settings.ml.novelty"),
            t("settings.ml.novelty_hint"),
            settings,
            "ml_novelty_ratio",
            0,
            1,
            0.05,
            pct=True,
            save_fn=save_fn,
        )

        # History window
        hist_opts = {4: "4 weken", 8: "8 weken", 13: "13 weken", 26: "26 weken", 52: "52 weken"}
        with ui.element("div").style("padding:.375rem 0"):
            ui.label(t("settings.ml.history_window")).style("font-size:12px;color:var(--c-text-2)")
            ui.label(t("settings.ml.history_hint")).style(
                "font-size:10px;color:var(--c-text-4);line-height:1.4;margin-bottom:.25rem"
            )
            hist_sel = (
                ui.select(hist_opts, value=settings.ml_history_window_weeks)
                .props("outlined dense options-dense")
                .style("max-width:160px")
            )

            async def _save_hist() -> None:
                settings.ml_history_window_weeks = int(hist_sel.value)
                await save_fn()

            hist_sel.on("update:model-value", lambda e: asyncio.ensure_future(_save_hist()))

        # Decay halflife slider
        _adv_slider(
            t("settings.ml.decay_halflife"),
            t("settings.ml.decay_hint"),
            settings,
            "ml_trend_decay_halflife",
            1,
            26,
            1,
            pct=False,
            unit=" wk",
            save_fn=save_fn,
        )

        # Selection method
        _infobox(
            "Selectiemethode: 'altijd de beste score' is deterministisch (Variatie 1), "
            "'op basis van kansen' voegt toeval toe — temperatuur bepaalt hoeveel "
            "(laag ≈ Variatie 2–3, hoog ≈ 4–5). De andere methoden zijn voor experimenteel gebruik.",
            icon="sym_r_casino",
            color="var(--c-accent-tint)",
            border="var(--c-accent-border)",
            text_color="var(--c-accent)",
        )

        method_opts = {
            "greedy": t("settings.ml.method_greedy"),
            "softmax": t("settings.ml.method_softmax"),
            "epsilon_greedy": t("settings.ml.method_epsilon"),
            "thompson": t("settings.ml.method_thompson"),
        }
        with ui.element("div").style("padding:.375rem 0"):
            ui.label(t("settings.ml.selection_method")).style(
                "font-size:12px;font-weight:600;color:var(--c-text-2)"
            )
            meth_sel = (
                ui.select(method_opts, value=settings.ml_selection_method)
                .props("outlined dense options-dense")
                .style("max-width:240px")
            )

            async def _save_method() -> None:
                settings.ml_selection_method = str(meth_sel.value)
                await save_fn()

            meth_sel.on("update:model-value", lambda e: asyncio.ensure_future(_save_method()))

        # Epsilon (only relevant for epsilon_greedy)
        with ui.element("div").bind_visibility_from(
            meth_sel, "value", backward=lambda v: v == "epsilon_greedy"
        ):
            _adv_slider(
                t("settings.ml.exploration"),
                t("settings.ml.exploration_hint"),
                settings,
                "ml_exploration_rate",
                0,
                0.5,
                0.01,
                pct=True,
                save_fn=save_fn,
            )

        # Temperature (only relevant for softmax)
        with ui.element("div").bind_visibility_from(
            meth_sel, "value", backward=lambda v: v == "softmax"
        ):
            _adv_slider(
                t("settings.ml.temperature"),
                t("settings.ml.temperature_hint"),
                settings,
                "ml_temperature",
                0.1,
                5.0,
                0.1,
                pct=False,
                unit="",
                save_fn=save_fn,
            )

        # Confidence threshold
        _adv_slider(
            t("settings.ml.confidence"),
            t("settings.ml.confidence_hint"),
            settings,
            "ml_confidence_threshold",
            0,
            1,
            0.05,
            pct=True,
            save_fn=save_fn,
        )


def _adv_slider(
    label: str,
    hint: str,
    settings: UserSettings,
    attr: str,
    min_v: float,
    max_v: float,
    step: float,
    *,
    pct: bool = False,
    unit: str = "",
    save_fn,
) -> None:
    """One labelled slider for an advanced numeric setting."""
    with ui.element("div").style("padding:.375rem 0"):
        with ui.row().style("align-items:center;justify-content:space-between;width:100%"):
            with ui.element("div").style("flex:1"):
                ui.label(label).style("font-size:12px;color:var(--c-text-2)")
                if hint:
                    ui.label(hint).style("font-size:10px;color:var(--c-text-4);line-height:1.4")
            cur = getattr(settings, attr)
            fmt = f"{cur:.0%}" if pct else f"{cur:.1f}{unit}"
            val_lbl = ui.label(fmt).style("font-size:11px;color:var(--c-text-3);font-weight:600")
        sl = ui.slider(min=min_v, max=max_v, step=step, value=cur).props("color=primary")

        def _update_lbl(e, lbl=val_lbl, s=sl) -> None:
            v = float(s.value)
            lbl.set_text(f"{v:.0%}" if pct else f"{v:.1f}{unit}")

        sl.on("update:model-value", _update_lbl)

        async def _save(a=attr, s=sl) -> None:
            setattr(settings, a, round(float(s.value), 2))
            await save_fn()

        sl.on("change", lambda e, f=_save: asyncio.ensure_future(f()))


def _render_ml_autopilot(settings: UserSettings, save_fn) -> None:
    """Autopilot settings — structured by feature area."""
    if not settings.ml_enabled:
        ui.label("Schakel eerst Slimme suggesties in.").style(
            "font-size:12px;color:var(--c-text-3)"
        )
        return

    _infobox(
        "Autopilot stelt automatisch een boodschappenplan samen dat je "
        "bekijkt en bevestigt op de Autopilot-pagina. Alle regels, dagvoorkeuren "
        "en weekdoelen uit Slimme suggesties worden gerespecteerd.",
        icon="sym_r_robot_2",
        color="var(--c-accent-tint)",
        border="var(--c-accent-border)",
        text_color="var(--c-accent)",
    )

    _ap_subhead = (
        "font-size:11px;font-weight:700;color:var(--c-accent);letter-spacing:.06em;"
        "text-transform:uppercase;margin-top:.75rem;display:block"
    )

    # ── Weekmenu ─────────────────────────────────────────────────────
    ui.label("Weekmenu").style(_ap_subhead)

    _ap_toggle(
        settings,
        "ml_autopilot_dinner",
        "Avondeten automatisch plannen",
        "Vult lege avondeten-slots in op basis van je voorkeuren.",
        save_fn,
        derived="ml_autopilot",
    )
    _ap_toggle(
        settings,
        "ml_autopilot_lunch",
        "Extra maaltijden automatisch plannen",
        "Vult lege extra-slots in.",
        save_fn,
        derived="ml_autopilot",
    )

    with ui.row().style("gap:.75rem;margin-top:.25rem;padding-left:.25rem"):
        with ui.element("div"):
            ui.label("Max. avondeten").style("font-size:11px;color:var(--c-text-3)")
            max_d = (
                ui.number(value=settings.ml_autopilot_max_dinner, min=0, max=7)
                .props("outlined dense")
                .style("max-width:72px")
            )

            async def _save_max_d() -> None:
                settings.ml_autopilot_max_dinner = int(max_d.value or 0)
                await save_fn()

            max_d.on("change", lambda e: asyncio.ensure_future(_save_max_d()))

        with ui.element("div"):
            ui.label("Max. extra").style("font-size:11px;color:var(--c-text-3)")
            max_l = (
                ui.number(value=settings.ml_autopilot_max_lunch, min=0, max=5)
                .props("outlined dense")
                .style("max-width:72px")
            )

            async def _save_max_l() -> None:
                settings.ml_autopilot_max_lunch = int(max_l.value or 0)
                await save_fn()

            max_l.on("change", lambda e: asyncio.ensure_future(_save_max_l()))

    # ── Aanbiedingen & bezorging ─────────────────────────────────────
    ui.label("Aanbiedingen & bezorging").style(_ap_subhead)

    _ap_toggle(
        settings,
        "ml_autopilot_promos",
        "Actie-alternatieven voorstellen",
        "Stelt goedkopere alternatieven voor als een vergelijkbaar product in de aanbieding is.",
        save_fn,
    )
    _ap_toggle(
        settings,
        "ml_autopilot_fillers",
        "Gratis-bezorgdrempel aanvullen",
        "Voegt vaste boodschappen toe om de gratis-bezorgdrempel te halen.",
        save_fn,
    )

    # ── Vaste boodschappen ───────────────────────────────────────────
    ui.label("Vaste boodschappen").style(_ap_subhead)

    _ap_toggle(
        settings,
        "ml_autopilot_staples",
        "Vaste boodschappen aanvullen",
        "Voegt alle vaste boodschappen met een standaard-aantal ≥ 1 toe aan het plan.",
        save_fn,
    )

    # ── Vervangproducten ─────────────────────────────────────────────
    ui.label("Vervangproducten").style(_ap_subhead)

    with ui.element("div").style("padding:.375rem 0 .25rem;border-top:1px solid var(--c-border)"):
        ui.label("Automatische vervanging tot score").style(
            "font-size:13px;font-weight:600;color:var(--c-text)"
        )
        ui.label(
            "Producten met een hogere score dan deze drempel worden automatisch "
            "vervangen. Lagere scores worden ter beoordeling aangeboden."
        ).style("font-size:11px;color:var(--c-text-3);line-height:1.5;margin-bottom:.25rem")
        with ui.row().style("align-items:center;gap:.5rem"):
            thr_label = ui.label(f"{settings.sub_confidence_auto:.1f}").style(
                "font-size:12px;font-weight:600;color:var(--c-text-2);min-width:24px"
            )
            thr = (
                ui.slider(value=settings.sub_confidence_auto, min=3.0, max=10.0, step=0.5)
                .props("color=deep-purple")
                .style("flex:1;max-width:220px")
            )
            thr.on(
                "update:model-value",
                lambda e: thr_label.set_text(f"{float(thr.value):.1f}"),
            )

            async def _save_thr() -> None:
                settings.sub_confidence_auto = thr.value
                await save_fn()

            thr.on("change", lambda e: asyncio.ensure_future(_save_thr()))
        with ui.element("div").style(
            "display:flex;gap:.5rem;margin-top:.25rem;font-size:10px;"
            "color:var(--c-text-4);line-height:1.4"
        ):
            ui.label(
                "3–5 = soepel (meer automatisch, maar soms minder passend) · "
                "6–7 = gebalanceerd · 8–10 = streng (bijna alles handmatig beoordelen)"
            )

    with ui.element("div").style("padding:.375rem 0 .25rem;border-top:1px solid var(--c-border)"):
        ui.label("Alternatieven tonen").style("font-size:13px;font-weight:600;color:var(--c-text)")
        ui.label("Hoeveel vervangopties per product worden getoond op de Autopilot-pagina.").style(
            "font-size:11px;color:var(--c-text-3);line-height:1.5;margin-bottom:.25rem"
        )
        sub_disp_label = ui.label(str(settings.autopilot_sub_display)).style(
            "font-size:12px;font-weight:600;color:var(--c-text-2)"
        )
        sub_disp = (
            ui.slider(value=settings.autopilot_sub_display, min=3, max=12, step=1)
            .props("color=deep-purple")
            .style("max-width:220px")
        )
        sub_disp.on(
            "update:model-value",
            lambda e: sub_disp_label.set_text(str(int(sub_disp.value))),
        )

        async def _save_sub_disp() -> None:
            settings.autopilot_sub_display = int(sub_disp.value)
            await save_fn()

        sub_disp.on("change", lambda e: asyncio.ensure_future(_save_sub_disp()))

    # ── Planning ─────────────────────────────────────────────────────
    ui.label("Planning").style(_ap_subhead)

    _DAY_OPTIONS = {
        "ma": "Maandag",
        "di": "Dinsdag",
        "wo": "Woensdag",
        "do": "Donderdag",
        "vr": "Vrijdag",
        "za": "Zaterdag",
        "zo": "Zondag",
    }
    with ui.row().style("gap:.75rem;padding:.375rem 0"):
        with ui.element("div"):
            ui.label("Dag").style("font-size:11px;color:var(--c-text-3)")
            day_sel = (
                ui.select(options=_DAY_OPTIONS, value=settings.autopilot_schedule_day)
                .props("outlined dense options-dense")
                .style("max-width:130px")
            )

            async def _save_day() -> None:
                settings.autopilot_schedule_day = day_sel.value
                await save_fn()

            day_sel.on("update:model-value", lambda e: asyncio.ensure_future(_save_day()))

        with ui.element("div"):
            ui.label("Tijdstip").style("font-size:11px;color:var(--c-text-3)")
            hour_in = (
                ui.number(value=settings.autopilot_schedule_hour, min=0, max=23)
                .props("outlined dense suffix=uur")
                .style("max-width:90px")
            )

            async def _save_hour() -> None:
                settings.autopilot_schedule_hour = int(hour_in.value or 9)
                await save_fn()

            hour_in.on("change", lambda e: asyncio.ensure_future(_save_hour()))

    _ap_toggle(
        settings,
        "autopilot_ntfy",
        "Pushmelding sturen als plan klaar is",
        "Stuurt een melding via ntfy zodra het boodschappenplan is samengesteld.",
        save_fn,
    )

    # ── Overig ───────────────────────────────────────────────────────
    ui.label("Overig").style(_ap_subhead)

    _ap_toggle(
        settings,
        "autopilot_clear_cart",
        "Winkelwagen legen voor autopilot",
        "Verwijdert alle producten uit je winkelwagen voordat autopilot begint.",
        save_fn,
        danger=True,
    )


def _ap_toggle(
    settings: UserSettings,
    attr: str,
    label: str,
    hint: str,
    save_fn,
    *,
    derived: str = "",
    danger: bool = False,
) -> None:
    """Autopilot toggle row with purple accent text."""
    with ui.row().style(
        "align-items:flex-start;gap:.625rem;padding:.375rem 0;border-top:1px solid var(--c-border)"
    ):
        color = "negative" if danger else "deep-purple"
        sw = ui.switch(value=getattr(settings, attr)).props(f"color={color} size=sm")
        with ui.element("div").style("flex:1"):
            ui.label(label).style("font-size:13px;font-weight:600;color:var(--c-text)")
            if hint:
                ui.label(hint).style("font-size:11px;color:var(--c-text-3);line-height:1.5")

    async def _on_change(a=attr, s=sw) -> None:
        setattr(settings, a, bool(s.value))
        if derived:
            setattr(
                settings,
                derived,
                settings.ml_autopilot_dinner or settings.ml_autopilot_lunch,
            )
        await save_fn()

    sw.on("update:model-value", lambda e: asyncio.ensure_future(_on_change()))


# ── Weather ──────────────────────────────────────────────────────────────────


def _render_weather(settings: UserSettings, save_fn) -> None:
    _infobox(
        "Het model kan het weer meenemen bij suggesties: op warme dagen gerechten "
        "met oven of airfryer vermijden en koude gerechten voorrang geven. "
        "De temperatuur wordt dagelijks opgehaald via Open-Meteo (gratis, geen API-sleutel nodig).",
    )

    _toggle_setting(
        settings,
        "weather_enabled",
        t("settings.weather.enabled"),
        t("settings.weather.enabled_hint"),
        save_fn,
    )

    # Location search
    ui.label(t("settings.weather.location")).style(
        "font-size:13px;font-weight:600;color:var(--c-text);margin-top:.5rem"
    )
    ui.label(t("settings.weather.location_hint")).style(
        "font-size:11px;color:var(--c-text-3);line-height:1.5;margin-bottom:.375rem;display:block"
    )

    loc_input = (
        ui.input(
            label="Plaatsnaam",
            value=settings.weather_location_name,
            placeholder="bijv. Amsterdam",
        )
        .props("outlined dense clearable")
        .style("max-width:280px;margin-bottom:.375rem")
    )

    coord_label = ui.label(
        f"({settings.weather_latitude:.2f}, {settings.weather_longitude:.2f})"
        if settings.weather_latitude is not None
        else ""
    ).style("font-size:11px;color:var(--c-text-4);margin-bottom:.5rem;display:block")

    async def _geocode() -> None:
        name = (loc_input.value or "").strip()
        if not name:
            return
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": name, "count": 1, "language": "nl"},
                    timeout=10,
                )
            data = r.json()
            results = data.get("results", [])
            if results:
                hit = results[0]
                settings.weather_latitude = round(hit["latitude"], 2)
                settings.weather_longitude = round(hit["longitude"], 2)
                settings.weather_location_name = hit.get("name", name)
                loc_input.set_value(settings.weather_location_name)
                coord_label.set_text(
                    f"({settings.weather_latitude:.2f}, {settings.weather_longitude:.2f})"
                )
                await save_fn()
                ui.notify(
                    f"Locatie: {settings.weather_location_name}", type="positive", timeout=1500
                )
            else:
                ui.notify("Plaats niet gevonden", type="warning", timeout=2000)
        except Exception:
            log.warning("Geocoding failed", exc_info=True)
            ui.notify(
                "Locatie opzoeken mislukt — probeer het later opnieuw",
                type="negative",
                timeout=3000,
            )

    loc_input.on("keydown.enter", lambda _: _geocode())
    ui.button("Zoeken", on_click=lambda: _geocode()).props(
        "flat rounded no-caps color=primary size=sm"
    ).style("font-size:12px;margin-bottom:.5rem")

    async def _download_weather() -> None:
        lat = settings.weather_latitude
        lon = settings.weather_longitude
        if lat is None or lon is None:
            ui.notify("Stel eerst een locatie in", type="warning", timeout=2000)
            return
        try:
            import datetime

            import httpx

            from pyplus.db import repo
            from pyplus.db.engine import AsyncSessionLocal

            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": round(lat, 2),
                        "longitude": round(lon, 2),
                        "daily": "temperature_2m_max",
                        "timezone": "Europe/Amsterdam",
                        "past_days": 30,
                        "forecast_days": 14,
                    },
                    timeout=20,
                )
            data = r.json()
            dates = data.get("daily", {}).get("time", [])
            temps = data.get("daily", {}).get("temperature_2m_max", [])
            async with AsyncSessionLocal() as db:
                for d_str, temp in zip(dates, temps):
                    if temp is None:
                        continue
                    await repo.upsert_weather(
                        db,
                        datetime.date.fromisoformat(d_str),
                        round(lat, 2),
                        round(lon, 2),
                        float(temp),
                    )
            ui.notify(f"{len(dates)} dagen weerdata opgehaald", type="positive", timeout=2000)
        except Exception:
            log.warning("Weather download failed", exc_info=True)
            ui.notify(
                "Weerdata ophalen mislukt — probeer het later opnieuw",
                type="negative",
                timeout=3000,
            )

    ui.button("Weerdata ophalen (44 dagen)", on_click=lambda: _download_weather()).props(
        "flat rounded no-caps color=secondary size=sm"
    ).style("font-size:12px;margin-bottom:.5rem")

    # Threshold slider
    with ui.element("div").style("padding:.375rem 0"):
        with ui.row().style("align-items:center;justify-content:space-between;width:100%"):
            with ui.element("div").style("flex:1"):
                ui.label(t("settings.weather.threshold")).style(
                    "font-size:12px;color:var(--c-text-2)"
                )
                ui.label(t("settings.weather.threshold_hint")).style(
                    "font-size:10px;color:var(--c-text-4);line-height:1.4"
                )
            thresh_lbl = ui.label(f"{settings.weather_hot_threshold:.0f}°C").style(
                "font-size:11px;color:var(--c-text-3);font-weight:600"
            )
        thresh_sl = ui.slider(min=20, max=40, step=1, value=settings.weather_hot_threshold).props(
            "color=primary"
        )
        thresh_sl.on(
            "update:model-value",
            lambda e: thresh_lbl.set_text(f"{float(thresh_sl.value):.0f}°C"),
        )

        async def _save_thresh() -> None:
            settings.weather_hot_threshold = float(thresh_sl.value)
            await save_fn()

        thresh_sl.on("change", lambda e: asyncio.ensure_future(_save_thresh()))

    _infobox(
        "Stel de gewichten in bij Weegfactoren → 'Weer: oven/airfryer vermijden' "
        "en 'Weer: voorkeur koud' om het effect op suggesties te bepalen.",
        icon="sym_r_tune",
        color="var(--c-accent-tint)",
        border="var(--c-accent-border)",
        text_color="var(--c-accent)",
    )


# ── ntfy ──────────────────────────────────────────────────────────────────────


def _render_ntfy(settings: UserSettings, save_fn) -> None:
    from pyplus.security import secrets

    url_input = (
        ui.input(
            label=t("settings.ntfy.url"),
            value=settings.ntfy_url,
            placeholder="https://ntfy.sh",
        )
        .props("outlined dense")
        .style("width:100%;margin-bottom:.5rem")
    )

    topic_input = (
        ui.input(
            label=t("settings.ntfy.topic"),
            value=settings.ntfy_topic,
        )
        .props("outlined dense")
        .style("width:100%;margin-bottom:.5rem")
    )

    username_input = (
        ui.input(
            label=t("settings.ntfy.username"),
            value=settings.ntfy_username,
        )
        .props("outlined dense")
        .style("width:100%;margin-bottom:.5rem")
    )

    _current_pw = secrets.decrypt(settings.ntfy_password_enc) if settings.ntfy_password_enc else ""
    password_input = (
        ui.input(
            label=t("settings.ntfy.password"),
            value=_current_pw or "",
            password=True,
            password_toggle_button=True,
        )
        .props("outlined dense")
        .style("width:100%;margin-bottom:.625rem")
    )

    async def _save_ntfy() -> None:
        settings.ntfy_url = url_input.value.strip()
        settings.ntfy_topic = topic_input.value.strip()
        settings.ntfy_username = username_input.value.strip()
        pw = password_input.value
        if pw:
            settings.ntfy_password_enc = secrets.encrypt(pw) or ""
        elif not pw and settings.ntfy_password_enc:
            settings.ntfy_password_enc = ""
        await save_fn()

    url_input.on("blur", lambda _: asyncio.ensure_future(_save_ntfy()))
    topic_input.on("blur", lambda _: asyncio.ensure_future(_save_ntfy()))
    username_input.on("blur", lambda _: asyncio.ensure_future(_save_ntfy()))
    password_input.on("blur", lambda _: asyncio.ensure_future(_save_ntfy()))

    with ui.row().style("align-items:center;gap:.625rem"):
        weekly_sw = ui.switch(t("settings.ntfy.weekly"), value=settings.ntfy_weekly_alert).props(
            "color=primary"
        )

        async def _on_weekly(e) -> None:
            settings.ntfy_weekly_alert = weekly_sw.value
            await save_fn()

        weekly_sw.on("update:model-value", lambda e: asyncio.ensure_future(_on_weekly(e)))

    ui.element("div").style("height:.5rem")
    ui.button(
        t("settings.ntfy.test"),
        icon="sym_r_send",
        on_click=lambda: asyncio.ensure_future(_test_ntfy(settings)),
    ).props("flat rounded no-caps color=primary size=sm").style("font-size:12px")


async def _test_ntfy(settings: UserSettings) -> None:
    if not settings.ntfy_url or not settings.ntfy_topic:
        ui.notify("Stel eerst de ntfy-URL en het topic in", type="warning", position="top")
        return
    from pyplus.security.net import UnsafeUrlError, assert_safe_url

    try:
        await assert_safe_url(settings.ntfy_url)
    except UnsafeUrlError as exc:
        ui.notify(str(exc), type="warning", position="top")
        return

    try:
        import httpx

        from pyplus.security import secrets

        auth = None
        if settings.ntfy_username:
            pw = secrets.decrypt(settings.ntfy_password_enc) if settings.ntfy_password_enc else ""
            auth = (settings.ntfy_username, pw)

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{settings.ntfy_url.rstrip('/')}/{settings.ntfy_topic}",
                content="PyPLUS test-melding",
                headers={"Title": "PyPLUS"},
                auth=auth,
                timeout=10,
            )
        if r.status_code < 300:
            ui.notify("Test-melding verstuurd", type="positive", position="top")
        else:
            ui.notify(f"ntfy antwoordde met {r.status_code}", type="warning", position="top")
    except Exception:
        log.warning("ntfy test failed", exc_info=True)
        ui.notify(
            "Versturen mislukt — controleer de ntfy-instellingen",
            type="negative",
            position="top",
        )


# ── iCal ──────────────────────────────────────────────────────────────────────


def _render_ical(settings: UserSettings, user_id: int, session, save_fn) -> None:
    from pyplus.ui.components.meals import render_ical_subscription_body

    render_ical_subscription_body(user_id)

    ui.separator().style("margin:.75rem 0 .5rem")
    _toggle_setting(
        settings,
        "ical_include_ingredients",
        "Ingrediënten meesturen",
        "Voeg de ingrediëntenlijst toe aan de omschrijving van elke agenda-afspraak.",
        save_fn,
    )


# ── Sync status ───────────────────────────────────────────────────────────────

# Resource → Dutch label, in display order. Keys match jobs/registry resource names.
_SYNC_LABELS: list[tuple[str, str]] = [
    ("catalogue", "Productcatalogus"),
    ("products", "Prijzen & beschikbaarheid"),
    ("promotions", "Aanbiedingen"),
    ("purchase_catalogue", "Eerder gekochte producten"),
    ("orders", "Bestelgeschiedenis"),
    ("ml", "Slimme suggesties"),
    ("weather", "Weer"),
]

_RESOURCE_TO_JOB: dict[str, str] = {
    "catalogue": "catalogue_weekly",
    "products": "full_preload_nightly",
    "promotions": "full_preload_nightly",
    "purchase_catalogue": "full_preload_nightly",
    "orders": "full_preload_nightly",
    "ml": "full_preload_nightly",
    "weather": "full_preload_nightly",
}


def _format_until(dt) -> str:
    """Human 'over Xd Yu' until a future (tz-aware) datetime."""
    import datetime as _dt

    now = _dt.datetime.now(dt.tzinfo)
    secs = int((dt - now).total_seconds())
    if secs <= 0:
        return "binnenkort"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days > 0:
        return f"over {days}d {hours}u"
    if hours > 0:
        return f"over {hours}u {mins}m"
    return f"over {mins}m"


def _format_duration(seconds: float | None) -> str:
    """Format a duration in seconds as 'Xm Ys' or 'Xs'."""
    if seconds is None:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60}s"


def _status_dot_colour(status: str | None) -> str:
    """Colour-code the status dot: green ok, amber in-progress, red error, grey never."""
    if status == "ok":
        return "var(--c-brand)"
    if status == "in_progress":
        return "var(--c-warning-dark)"
    if status == "error":
        return "var(--c-danger)"
    return "var(--c-border)"


async def _run_sync_job(resource: str, session) -> None:
    """Run the job behind a sync resource on the live (logged-in) session.

    Reuses the active browser session, so no second login is needed. Each job writes
    its own ``in_progress``/``ok``/``error`` sync_state and is per-resource locked.
    """
    from pyplus.jobs import registry

    uid = session.user_id
    client = getattr(session, "client", None)
    store = getattr(session, "store_number", 0) or 0

    if resource == "catalogue":
        await registry.refresh_product_catalogue(user_id=uid, client=client, store_number=store)
    elif resource == "products":
        await registry.refresh_products(user_id=uid, client=client, store_number=store)
    elif resource == "promotions":
        await registry.refresh_promotions(user_id=uid, client=client, store_number=store)
    elif resource == "purchase_catalogue":
        await registry.refresh_purchase_catalogue(user_id=uid, client=client)
    elif resource == "orders":
        await registry.refresh_orders(user_id=uid, client=client)
    elif resource == "ml":
        await registry.recompute_ml(user_id=uid)
    elif resource == "weather":
        await registry.refresh_weather(user_id=uid)


def _render_sync_status(
    session, user_id: int, sync_states: dict, next_runs: dict | None = None
) -> None:
    """Show when each background cache last refreshed and, if the in-app scheduler
    is active, when it runs again. Each row has a "run now" button that triggers the
    job on the live session and updates that row's timer + status in place."""
    from pyplus.ui.format import humanize_since

    next_runs = next_runs or {}
    scheduler_active = bool(next_runs)

    note = "Achtergrondtaken houden je gegevens vers zonder dat het openen vertraagt."
    if not scheduler_active:
        note += " De ingebouwde planner is uit; taken draaien via cron of handmatig."
    ui.label(note).style("font-size:12px;color:var(--c-text-3);margin-bottom:.75rem;display:block")

    for resource, label in _SYNC_LABELS:
        row = sync_states.get(resource)
        when0 = humanize_since(row.last_synced_at if row else None)
        status0 = row.last_status if row else None
        next_dt = next_runs.get(_RESOURCE_TO_JOB.get(resource, ""))

        with ui.element("div").style(
            "display:flex;align-items:center;gap:.625rem;padding:.45rem 0;"
            "border-bottom:1px solid var(--c-border)"
        ):
            dot = ui.element("div").style(
                f"width:8px;height:8px;border-radius:50%;flex-shrink:0;"
                f"background:{_status_dot_colour(status0)}"
            )
            ui.label(label).style("font-size:13px;color:var(--c-text-2);flex:1")
            with ui.element("div").style(
                "display:flex;flex-direction:column;align-items:flex-end;line-height:1.3"
            ):
                when_lbl = ui.label(when0).style("font-size:12px;color:var(--c-text-3)")
                dur0 = _format_duration(row.last_duration_seconds if row else None)
                dur_lbl = (
                    ui.label(dur0)
                    .style(
                        "font-size:11px;color:var(--c-text-4)"
                        + (";display:none" if not dur0 else "")
                    )
                    .tooltip("Duur van de laatste uitvoering")
                )
                if next_dt is not None:
                    ui.label(_format_until(next_dt)).style(
                        "font-size:11px;color:var(--c-text-4)"
                    ).tooltip(f"Volgende automatische run: {next_dt:%a %d %b %H:%M}")

            run_btn = (
                ui.button(icon="sym_r_refresh")
                .props("flat round dense size=sm color=grey-6")
                .tooltip("Nu uitvoeren")
            )

            async def _run(
                _=None,
                res=resource,
                btn=run_btn,
                dot_el=dot,
                lbl=when_lbl,
                dlbl=dur_lbl,
            ) -> None:
                btn.props("loading")
                dot_el.style(f"background:{_status_dot_colour('in_progress')}")
                try:
                    await _run_sync_job(res, session)
                    status = "ok"
                except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
                    status = "error"
                    ui.notify(
                        f"Uitvoeren mislukt: {exc}",
                        type="warning",
                        position="top-right",
                        timeout=4000,
                        close_button=True,
                    )
                finally:
                    btn.props(remove="loading")
                # Reflect the authoritative sync_state the job just wrote.
                from pyplus.db import repo
                from pyplus.db.engine import AsyncSessionLocal

                fresh = None
                try:
                    async with AsyncSessionLocal() as db:
                        fresh = await repo.get_sync_state(db, user_id, res)
                except Exception:
                    pass
                if fresh is not None:
                    status = fresh.last_status or status
                    lbl.set_text(humanize_since(fresh.last_synced_at))
                    dur_str = _format_duration(fresh.last_duration_seconds)
                    dlbl.set_text(dur_str)
                    dlbl.style(
                        "font-size:11px;color:var(--c-text-4)"
                        + (";display:none" if not dur_str else "")
                    )
                dot_el.style(f"background:{_status_dot_colour(status)}")

            run_btn.on_click(_run)

    if not sync_states:
        ui.label("Nog niets gesynchroniseerd.").style(
            "font-size:12px;color:var(--c-text-4);margin-top:.5rem;display:block"
        )
