"""Login page — full-screen card with real PlusClient login and remember-me."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from nicegui import app, background_tasks, ui

from pyplus import __version__
from pyplus.i18n import t

log = logging.getLogger(__name__)

# Each login spawns a headless Chromium (~20s). Cap concurrent logins so repeated
# submits can't exhaust memory; further attempts queue rather than pile up browsers.
_MAX_CONCURRENT_LOGINS = 2
_login_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_LOGINS)

# Hard cap on one login attempt. A hung PLUS/Playwright call must never hold the
# login semaphore or the auto-login slot forever.
_LOGIN_TIMEOUT_S = 120


@dataclass
class _AutoLoginJob:
    """A remember-me login running server-side, independent of any browser connection.

    The task's own lifetime is the single source of truth for "in progress": there is
    no separate marker to clean up, so a page load whose websocket never connects (link
    previews, prefetch, a phone suspending the tab) cannot leave the user locked out.
    """

    task: asyncio.Task
    progress: str = field(default_factory=lambda: t("login.progress_logging_in"))

    @property
    def running(self) -> bool:
        return not self.task.done()

    @property
    def succeeded(self) -> bool:
        if not self.task.done() or self.task.cancelled() or self.task.exception() is not None:
            return False
        return self.task.result() is not None


# user_id → the auto-login job for that user (running or just finished).
_auto_login_jobs: dict[int, _AutoLoginJob] = {}


def _render_version_badge() -> None:
    ui.label(f"v{__version__}").classes("sp-login-version")


def _mask_email(email: str) -> str:
    """Mask an email for logs: 'm***@umcg.nl'. Never log the full local part."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


# ── Public entry point ─────────────────────────────────────────────────────────


async def create_login_page() -> None:
    """
    Render the login page. Checks for a warm session or remember-me credentials
    and auto-logs in when possible; otherwise shows the login form.
    """
    # app.storage.browser is read-only once the response is built, so read it now,
    # never from a timer or callback.
    destination = app.storage.browser.pop("_login_next", "/weekmenu")
    app.storage.browser.pop("_auto_login_failed", None)  # legacy flag in old cookies

    user_id = app.storage.user.get("user_id")
    if user_id:
        from pyplus.session import manager

        # Reuse a still-warm server-side session (e.g. same user, second tab)
        if manager.get(user_id):
            ui.navigate.to(destination)
            return

        # Join a running auto-login (another tab, a reconnect, or a page load that
        # never connected) instead of spawning a second Playwright browser.
        job = _auto_login_jobs.get(user_id)
        if job is not None and job.running:
            _render_auto_login(job, user_id, None, destination)
            return

        # Try remember-me auto-login
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.security import secrets

        async with AsyncSessionLocal() as db:
            user = await repo.get_user_by_id(db, user_id)
            creds = await repo.get_credentials(db, user_id) if user else None

        if user and creds and secrets.is_available():
            email = secrets.decrypt(user.plus_email_enc)
            password = secrets.decrypt(creds.password_enc)
            if email and password:
                job = _start_auto_login(user_id, email, password)
                _render_auto_login(job, user_id, user.display_name or email, destination)
                return

    _render_login_form(destination)


# ── Auto-login variant (remember-me) ──────────────────────────────────────────


def _start_auto_login(user_id: int, email: str, password: str) -> _AutoLoginJob:
    """Start a server-side auto-login for this user, or return the one already running."""
    job = _auto_login_jobs.get(user_id)
    if job is not None and job.running:
        return job

    async def _run() -> int | None:
        return await _do_login_core(
            email=email,
            password=password,
            remember=True,
            on_progress=lambda msg: setattr(job, "progress", msg),
            on_error=lambda _: None,
        )

    job = _AutoLoginJob(task=background_tasks.create(_run(), name=f"auto_login_{user_id}"))
    _auto_login_jobs[user_id] = job
    return job


def _render_auto_login(
    job: _AutoLoginJob, user_id: int, name: str | None, destination: str
) -> None:
    """Show auto-login progress and follow the server-side job until it finishes."""
    with ui.element("div").classes("sp-login-bg"):
        _render_version_badge()
        with ui.element("div").classes("sp-login-card"):
            with ui.element("div").classes("sp-login-logo-wrap"):
                with (
                    ui.element("div")
                    .classes("sp-login-logo-mark")
                    .style("display:flex;align-items:center;justify-content:center")
                ):
                    ui.icon("sym_r_storefront", size="22px").style("color:white")
                ui.label("PyPLUS").classes("sp-login-logo-name")

            heading = f"Welkom terug, {name.split()[0]}!" if name else "Welkom terug!"
            ui.label(heading).classes("sp-login-heading")
            ui.label("Automatisch inloggen…").classes("sp-login-subheading")

            with ui.column().classes("sp-login-progress").style("gap:.45rem"):
                progress_label = ui.label(job.progress).classes("sp-login-progress-label")
                ui.linear_progress(value=None, size="3px", color="primary").props("indeterminate")

    async def _poll() -> None:
        progress_label.set_text(job.progress)
        if job.running:
            return
        poll_timer.deactivate()
        if job.succeeded:
            ui.navigate.to(destination)
            return
        # Failed or timed out: forget the remember-me session for this browser and
        # show the form. app.storage.user (server-side) is writable at any time.
        if _auto_login_jobs.get(user_id) is job:
            del _auto_login_jobs[user_id]
        app.storage.user.clear()
        ui.navigate.to("/login")

    poll_timer = ui.timer(0.5, _poll)


# ── Normal login form ──────────────────────────────────────────────────────────


def _render_login_form(destination: str) -> None:
    with ui.element("div").classes("sp-login-bg"):
        _render_version_badge()
        with ui.element("div").classes("sp-login-card"):
            # Logo
            with ui.element("div").classes("sp-login-logo-wrap"):
                with (
                    ui.element("div")
                    .classes("sp-login-logo-mark")
                    .style("display:flex;align-items:center;justify-content:center")
                ):
                    ui.icon("sym_r_storefront", size="22px").style("color:white")
                ui.label("PyPLUS").classes("sp-login-logo-name")

            ui.label(t("login.heading")).classes("sp-login-heading")
            ui.label(t("login.subheading")).classes("sp-login-subheading")

            # Fields
            with ui.element("div").classes("sp-login-fields"):
                email_input = (
                    ui.input(
                        label=t("login.email_label"),
                        placeholder=t("login.email_placeholder"),
                    )
                    .props("outlined type=email autocomplete=email")
                    .classes("sp-login-field")
                )
                password_input = (
                    ui.input(
                        label=t("login.password_label"),
                        password=True,
                        password_toggle_button=True,
                    )
                    .props("outlined autocomplete=current-password")
                    .classes("sp-login-field")
                )

            with ui.element("div").classes("sp-login-remember"):
                remember_check = ui.checkbox(t("login.remember_me"))
                from pyplus.security import secrets as _sec

                if not _sec.is_available():
                    ui.label(f"({t('error.no_secret_key')})").style(
                        "font-size:11px;color:var(--c-text-4);margin-left:.25rem"
                    )

            with ui.column().classes("sp-login-progress").style("gap:.45rem") as progress_col:
                progress_label = ui.label("").classes("sp-login-progress-label")
                ui.linear_progress(value=None, size="3px", color="primary").props("indeterminate")
            progress_col.set_visibility(False)

            async def _do_login() -> None:
                email = email_input.value.strip()
                password = password_input.value
                remember = remember_check.value

                if not email or not password:
                    ui.notify(t("login.error_empty"), type="negative", position="top")
                    return

                submit_btn.disable()
                progress_col.set_visibility(True)

                def _on_err(msg: str) -> None:
                    progress_col.set_visibility(False)
                    submit_btn.enable()
                    ui.notify(msg, type="negative", position="top", timeout=5000)

                user_id = await _do_login_core(
                    email=email,
                    password=password,
                    remember=remember,
                    on_progress=lambda msg: progress_label.set_text(msg),
                    on_error=_on_err,
                )
                if user_id is not None:
                    app.storage.user["user_id"] = user_id
                    ui.navigate.to(destination)

            submit_btn = (
                ui.button(t("login.submit"), on_click=_do_login)
                .props("unelevated rounded color=primary no-caps")
                .classes("sp-login-btn")
            )

            email_input.on("keydown.enter", lambda _: asyncio.ensure_future(_do_login()))
            password_input.on("keydown.enter", lambda _: asyncio.ensure_future(_do_login()))


# ── Core login orchestration ───────────────────────────────────────────────────


async def _do_login_core(
    *,
    email: str,
    password: str,
    remember: bool,
    on_progress,
    on_error,
) -> int | None:
    """
    Authenticate against PLUS.nl, set up the UserSession, and persist remember-me.
    Returns the user ID on success; otherwise calls on_error(msg) and returns None.
    on_progress(msg) reports progress. Never touches browser storage, so it is safe
    to run outside a page's request (e.g. as a server-side auto-login job).
    """
    from plus.client import PlusClient
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.security import secrets
    from pyplus.session import manager
    from pyplus.session.user_session import UserSession

    log.info("Login S0 — browser starten")
    client = PlusClient(headless=True)
    try:
        # Throttle concurrent logins — each holds a headless browser for ~20s.
        # The timeout (incl. queueing) guarantees a hung attempt always ends.
        async with asyncio.timeout(_LOGIN_TIMEOUT_S), _login_semaphore:
            await client.__aenter__()
            log.info("Login S1 — OAuth login starten (%s)", _mask_email(email))
            on_progress(t("login.progress_logging_in"))
            success = await client.login(email, password)
            if not success:
                await client.__aexit__(None, None, None)
                on_error(t("login.error_failed"))
                return None

            log.info("Login S2 — session state ophalen (cart-navigatie)")
            on_progress(t("login.progress_cart"))
            session_state = await client.get_session_state()
            log.info(
                "Login S2 done — checkout_id=%s store=%s",
                session_state.checkout_id[:8] if session_state.checkout_id else "?",
                session_state.store_number,
            )

            log.info("Login S3 — live cart ophalen")
            cart = await client.get_cart_api()
            log.info("Login S3 done — %d item(s) in cart", len(cart.items) if cart else 0)

        log.info("Login S4 — gebruiker opzoeken/aanmaken in DB")
        onewelcome_id = session_state.onewelcome_user_id
        async with AsyncSessionLocal() as db:
            user = await repo.get_user_by_onewelcome_id(db, onewelcome_id)
            is_first_login = user is None

            if user is None:
                email_enc = secrets.encrypt(email) or ""
                user = await repo.create_user(
                    db,
                    plus_email_enc=email_enc,
                    onewelcome_user_id=onewelcome_id,
                    store_number=session_state.store_number or None,
                    store_name=session_state.store_name,
                    user_store_id=session_state.user_store_id,
                )
            else:
                await repo.update_user_login(
                    db,
                    user.id,
                    store_number=session_state.store_number or None,
                    store_name=session_state.store_name,
                    user_store_id=session_state.user_store_id,
                )
                await db.refresh(user)

            log.info("Login S5 — remember-me opslaan (remember=%s)", remember)
            if remember and secrets.is_available():
                password_enc = secrets.encrypt(password)
                if password_enc:
                    await repo.upsert_credentials(db, user.id, password_enc)
            elif not remember:
                await repo.delete_credentials(db, user.id)

            user_id = user.id
            store_number = user.store_number or 0
            display_name = user.display_name or email.split("@")[0]

            from pyplus.services.cart import enrich_cart_with_provenance

            cart = await enrich_cart_with_provenance(db, user_id, cart)

            # Load the user's saved preferences so all lanes can read them.
            from pyplus.ml.interface import UserSettings

            settings_json = await repo.get_user_settings_json(db, user_id)
            try:
                user_settings = UserSettings.model_validate_json(settings_json)
            except Exception:
                user_settings = UserSettings()

    except BaseException as exc:
        # BaseException so a cancelled attempt (shutdown) still releases its browser.
        if isinstance(exc, TimeoutError):
            log.error("Login timed out after %ds", _LOGIN_TIMEOUT_S)
        else:
            log.exception("Login error: %s", exc)
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
        if not isinstance(exc, Exception):
            raise
        on_error(t("login.error_failed"))
        return None

    log.info("Login S6 — sessie registreren (user_id=%d)", user_id)
    session = UserSession(
        client=client,
        user_id=user_id,
        store_number=store_number,
        display_name=display_name,
        _cart=cart,
        _settings=user_settings,
    )
    manager.register(session)
    log.info("Login S6 done — sessie geregistreerd")

    log.info("Login S7 — winkelbevestiging + navigeren (first_login=%s)", is_first_login)
    if is_first_login and store_number:
        try:
            _show_store_confirmation(store_number)
        except Exception:
            log.warning("Login S7 — store-bevestiging overgeslagen (NiceGUI context weg)")

    log.info("Login S8 — klaar")
    return user_id


# ── Store confirmation dialog (first login only) ───────────────────────────────


def _show_store_confirmation(store_number: int) -> None:
    with ui.dialog(value=True) as dlg, ui.card().style("max-width:360px;padding:1.5rem"):
        with ui.element("div").style("display:flex;flex-direction:column;gap:.75rem"):
            ui.label(t("login.store_confirm_heading")).style(
                "font-size:17px;font-weight:700;color:var(--c-text)"
            )
            ui.label(f"PLUS winkel #{store_number}").style(
                "font-size:15px;font-weight:600;color:var(--c-brand-dark);"
                "background:var(--c-brand-tint);padding:.5rem .75rem;"
                "border-radius:var(--r-md)"
            )
            ui.label(t("login.store_confirm_prompt")).style("font-size:14px;color:var(--c-text-3)")
            ui.label("Je kunt je winkel later wijzigen via Instellingen.").style(
                "font-size:12px;color:var(--c-text-4)"
            )
            with ui.row().style("gap:.5rem;justify-content:flex-end;margin-top:.25rem"):
                ui.button(t("login.store_confirm"), on_click=dlg.close).props(
                    "unelevated rounded color=primary no-caps autofocus"
                )
