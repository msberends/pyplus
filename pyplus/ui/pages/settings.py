"""Settings page — account, ML preferences, ntfy, exports."""

from __future__ import annotations

import asyncio
import logging

from nicegui import app, ui

from pyplus.i18n import t
from pyplus.ml.interface import UserSettings
from pyplus.session import manager
from pyplus.ui.components.nav import create_nav_rail
from pyplus.ui.theme import apply_theme

log = logging.getLogger(__name__)


async def create_settings_page() -> None:
    user_id = app.storage.user.get("user_id")
    session = manager.get(user_id) if user_id else None
    if session is None:
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

        with ui.element("div").style(
            "flex:1;overflow-y:auto;padding:1.5rem;background:var(--c-bg);max-width:640px"
        ):
            ui.label(t("settings.title")).style(
                "font-size:22px;font-weight:700;color:var(--c-text);"
                "letter-spacing:-.3px;margin-bottom:1.5rem;display:block"
            )

            # ── Account & winkel ───────────────────────────────────────────
            _section_card(
                t("settings.account.title"), lambda: _render_account(session, user, user_id)
            )

            # ── Weergave & gedrag ──────────────────────────────────────────
            _section_card("Weergave & gedrag", lambda: _render_behaviour(settings, _save))

            # ── Indeling & sortering ───────────────────────────────────────
            _section_card("Indeling & sortering", lambda: _render_organisation(settings, _save))

            # ── Slimme suggesties (ML) ─────────────────────────────────────
            _section_card(t("settings.ml.title"), lambda: _render_ml(settings, user_id, _save))

            # ── Meldingen (ntfy) ───────────────────────────────────────────
            _section_card(t("settings.ntfy.title"), lambda: _render_ntfy(settings, _save))

            # ── Agenda-abonnement ─────────────────────────────────────────
            _section_card(
                "Agenda-abonnement", lambda: _render_ical(settings, user_id, session, _save)
            )

            # ── Gegevens & synchronisatie ─────────────────────────────────
            from pyplus.jobs.preload import scheduler_next_runs

            next_runs = scheduler_next_runs()
            _section_card(
                "Gegevens & synchronisatie",
                lambda: _render_sync_status(sync_states, next_runs),
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
            ui.label(f"PLUS winkel #{user.store_number}").style(
                "font-size:14px;color:var(--c-text-2)"
            )
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

    ui.button(t("settings.logout"), icon="logout", on_click=_logout).props(
        "flat rounded no-caps color=negative"
    ).style("font-size:13px")


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

        # ── Recommender weights ────────────────────────────────────────────
        with ui.element("div").style(
            "border-top:1px solid var(--c-border);margin-top:.625rem;padding-top:.625rem"
        ):
            ui.label("Weegfactoren weekmenu-suggesties").style(
                "font-size:13px;font-weight:600;color:var(--c-text)"
            )
            ui.label(
                "Bepaalt waar de suggesties op letten. Herbereken hieronder na het aanpassen."
            ).style("font-size:11px;color:var(--c-text-3);line-height:1.5;margin-bottom:.25rem")

            def _weight(label: str, attr: str) -> None:
                with ui.element("div").style("padding:.375rem 0"):
                    with ui.row().style(
                        "align-items:center;justify-content:space-between;width:100%"
                    ):
                        ui.label(label).style("font-size:12px;color:var(--c-text-2)")
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

            _weight("Afwisseling / variatie", "ml_afwisseling")
            _weight("Vaste dagen (gewoontes)", "ml_vaste_dagen")
            _weight("Voordeel (aanbiedingen)", "ml_voordeel")
            _weight("Voorraad (bijna op)", "ml_voorraad")
            _weight("Categorie-spreiding", "ml_variatie")

        with ui.element("div").style(
            "padding:.75rem;background:#fffbeb;border-radius:var(--r-md);"
            "border:1px solid #fde68a;margin-top:.625rem"
        ):
            with ui.row().style("align-items:flex-start;gap:.625rem"):
                autopilot_sw = ui.switch(value=settings.ml_autopilot).props("color=warning size=sm")
                with ui.element("div"):
                    ui.label(t("settings.ml.autopilot")).style(
                        "font-size:13px;font-weight:600;color:#92400e"
                    )
                    ui.label(t("settings.ml.autopilot_hint")).style(
                        "font-size:11px;color:#b45309;line-height:1.5"
                    )

            async def _on_autopilot(e) -> None:
                settings.ml_autopilot = autopilot_sw.value
                await save_fn()

            autopilot_sw.on("update:model-value", lambda e: asyncio.ensure_future(_on_autopilot(e)))

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
        except Exception as exc:
            recompute_label.set_text(f"Mislukt: {exc}")
            recompute_label.style("display:block;color:var(--c-danger)")
        finally:
            recompute_btn.props("loading=false")

    recompute_btn = (
        ui.button(
            "Herbereken suggesties",
            icon="refresh",
            on_click=lambda: asyncio.ensure_future(_recompute()),
        )
        .props("flat rounded no-caps color=primary size=sm")
        .style("font-size:12px")
    )


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
        icon="send",
        on_click=lambda: asyncio.ensure_future(_test_ntfy(settings)),
    ).props("flat rounded no-caps color=primary size=sm").style("font-size:12px")


async def _test_ntfy(settings: UserSettings) -> None:
    if not settings.ntfy_url or not settings.ntfy_topic:
        ui.notify("Stel eerst de ntfy-URL en het topic in", type="warning", position="top")
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
    except Exception as exc:
        ui.notify(f"Fout: {exc}", type="negative", position="top")


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


# Resource → Dutch label, in display order. Keys match jobs/registry resource names.
_SYNC_LABELS: list[tuple[str, str]] = [
    ("catalogue", "Productcatalogus"),
    ("products", "Prijzen & beschikbaarheid"),
    ("promotions", "Aanbiedingen"),
    ("purchase_catalogue", "Eerder gekochte producten"),
    ("orders", "Bestelgeschiedenis"),
    ("ml", "Slimme suggesties"),
]

# Resource → the scheduler job that next refreshes it. The catalogue has its own
# weekly job; everything else is refreshed by the nightly full preload.
_RESOURCE_TO_JOB: dict[str, str] = {
    "catalogue": "catalogue_weekly",
    "products": "full_preload_nightly",
    "promotions": "full_preload_nightly",
    "purchase_catalogue": "full_preload_nightly",
    "orders": "full_preload_nightly",
    "ml": "full_preload_nightly",
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


def _render_sync_status(sync_states: dict, next_runs: dict | None = None) -> None:
    """Show when each background cache last refreshed and, if the in-app scheduler
    is active, when it runs again."""
    from pyplus.ui.format import humanize_since

    next_runs = next_runs or {}
    scheduler_active = bool(next_runs)

    note = "Achtergrondtaken houden je gegevens vers zonder dat het openen vertraagt."
    if not scheduler_active:
        note += " De ingebouwde planner is uit; taken draaien via cron of handmatig."
    ui.label(note).style("font-size:12px;color:var(--c-text-3);margin-bottom:.75rem;display:block")

    for resource, label in _SYNC_LABELS:
        row = sync_states.get(resource)
        when = humanize_since(row.last_synced_at if row else None)
        status = row.last_status if row else None

        # Colour-code the status dot: green ok, amber in-progress, red error, grey never.
        if status == "ok":
            dot = "var(--c-brand)"
        elif status == "in_progress":
            dot = "var(--c-warning, #d97706)"
        elif status == "error":
            dot = "var(--c-danger)"
        else:
            dot = "var(--c-border)"

        next_dt = next_runs.get(_RESOURCE_TO_JOB.get(resource, ""))

        with ui.element("div").style(
            "display:flex;align-items:center;gap:.625rem;padding:.45rem 0;"
            "border-bottom:1px solid var(--c-border)"
        ):
            ui.element("div").style(
                f"width:8px;height:8px;border-radius:50%;background:{dot};flex-shrink:0"
            )
            ui.label(label).style("font-size:13px;color:var(--c-text-2);flex:1")
            with ui.element("div").style(
                "display:flex;flex-direction:column;align-items:flex-end;line-height:1.3"
            ):
                ui.label(when).style("font-size:12px;color:var(--c-text-3)")
                if next_dt is not None:
                    ui.label(_format_until(next_dt)).style(
                        "font-size:11px;color:var(--c-text-4)"
                    ).tooltip(f"Volgende automatische run: {next_dt:%a %d %b %H:%M}")

    if not sync_states:
        ui.label("Nog niets gesynchroniseerd.").style(
            "font-size:12px;color:var(--c-text-4);margin-top:.5rem;display:block"
        )
