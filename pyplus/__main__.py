"""PyPLUS — run with: uv run python -m pyplus"""

from __future__ import annotations

import datetime
import logging
import secrets

from fastapi import Request
from fastapi.responses import Response
from nicegui import app, ui

from pyplus.config import settings

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


# ── Page routes ───────────────────────────────────────────────────────────────


@ui.page("/")
@ui.page("/login")
async def login_page() -> None:
    from pyplus.ui.pages.login import create_login_page
    from pyplus.ui.theme import apply_theme

    apply_theme()
    await create_login_page()


@ui.page("/weekmenu")
async def weekmenu_page() -> None:
    from pyplus.ui.pages.weekmenu import create_weekmenu_page

    await create_weekmenu_page()


@ui.page("/promos")
async def promos_page() -> None:
    from pyplus.ui.pages.promos import create_promos_page

    await create_promos_page()


@ui.page("/staples")
async def staples_page() -> None:
    from pyplus.ui.pages.staples import create_staples_page

    await create_staples_page()


@ui.page("/cart")
async def cart_page() -> None:
    from pyplus.ui.pages.cart import create_cart_page

    await create_cart_page()


@ui.page("/dishes")
async def dishes_page() -> None:
    from pyplus.ui.pages.dishes import create_dishes_page

    await create_dishes_page()


@ui.page("/settings")
async def settings_page() -> None:
    from pyplus.ui.pages.settings import create_settings_page

    await create_settings_page()


# ── iCal subscription endpoint ───────────────────────────────────────────────


@app.get("/menu.ics")
async def serve_ical(request: Request, uid: int = 0, token: str = "") -> Response:
    """
    Stable per-user iCal subscription endpoint.

    Calendar apps call this with no cookies — authentication is the HMAC token:
      webcal://<host>/menu.ics?uid=<user_id>&token=<token>

    Returns 4 weeks of meal data starting from the Monday of the current week.
    """
    from pyplus.security.tokens import verify_ical_token

    if not settings.secret_key:
        return Response(
            "iCal-abonnement niet beschikbaar: PYPLUS_SECRET_KEY is niet ingesteld.",
            status_code=503,
            media_type="text/plain",
        )

    if not uid or not verify_ical_token(token, uid):
        return Response("Ongeldig token.", status_code=401, media_type="text/plain")

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        user = await repo.get_user_by_id(db, uid)
    if not user:
        return Response("Gebruiker niet gevonden.", status_code=404, media_type="text/plain")

    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    from pyplus.services.exports import build_ical_multi_week

    ical_bytes = await build_ical_multi_week(uid, week_start, n_weeks=4)

    return Response(
        content=ical_bytes,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="pyplus-menu.ics"',
            "Cache-Control": "no-cache, no-store",
        },
    )


# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def _on_startup() -> None:
    from pyplus.db.engine import init_db

    await init_db()

    if not settings.secret_key:
        log.warning(
            "PYPLUS_SECRET_KEY is not set — remember-me and background jobs "
            "are disabled. Generate a key:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            "and set PYPLUS_SECRET_KEY in your .env file."
        )

    from pyplus.jobs.preload import start_scheduler

    start_scheduler()


async def _on_shutdown() -> None:
    from pyplus.jobs.preload import stop_scheduler

    stop_scheduler()


app.on_startup(_on_startup)
app.on_shutdown(_on_shutdown)


# ── HTTP security headers ───────────────────────────────────────────────────
# Set conservatively: clickjacking + MIME-sniff + referrer protection, and CSP
# directives that don't touch resource loading (a full script-src CSP would break
# NiceGUI's inline Vue/Quasar). Tighten further at the reverse proxy if desired.


@app.middleware("http")
async def _security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    )
    return response


# ── Entry point ───────────────────────────────────────────────────────────────

# Cookie-signing secret is derived from the master key (not the raw key, which
# also encrypts credentials). Falls back to an ephemeral key when unset, so
# sessions simply don't survive a restart rather than being signed with nothing.
_storage_secret = secrets.token_hex(32)
if settings.secret_key:
    from pyplus.security.secrets import derive_key

    _derived = derive_key(b"pyplus/cookie/v1")
    if _derived:
        _storage_secret = _derived.hex()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host=settings.host,
        port=settings.port,
        title="PyPLUS",
        favicon="🧺",
        dark=False,
        storage_secret=_storage_secret,
        show=False,
        reload=False,
    )
