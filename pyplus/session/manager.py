"""Server-side session registry. One UserSession per active user (user_id)."""

from __future__ import annotations

import asyncio
import logging
import time

from pyplus.session.user_session import UserSession

log = logging.getLogger(__name__)

# user_id → UserSession
_sessions: dict[int, UserSession] = {}


def get(user_id: int) -> UserSession | None:
    session = _sessions.get(user_id)
    if session is not None:
        session.mark_active()  # navigation counts as activity for the idle reaper
    return session


def register(session: UserSession) -> None:
    """Register a session and attach its CartService.

    Closes any session already registered for this user so its Playwright browser
    is released rather than orphaned (re-login / second device would otherwise leak
    a headless Chromium per login).
    """
    old = _sessions.get(session.user_id)
    if old is not None and old is not session:
        log.info("Replacing existing session for user_id=%d — closing old one", session.user_id)
        asyncio.ensure_future(old.close())

    _sessions[session.user_id] = session

    # Attach the cart mutation service
    from pyplus.services.cart import CartService

    session.cart_service = CartService(session)  # type: ignore[attr-defined]

    log.info("Session registered for user_id=%d store=%d", session.user_id, session.store_number)


async def close(user_id: int) -> None:
    """Destroy session and close the Playwright browser."""
    session = _sessions.pop(user_id, None)
    if session:
        log.info("Closing session for user_id=%d", user_id)
        await session.close()


def all_sessions() -> list[UserSession]:
    return list(_sessions.values())


async def reap_idle(max_idle_seconds: float) -> int:
    """Close and drop sessions idle longer than max_idle_seconds.

    Frees the Playwright browser held by abandoned sessions. Returns how many
    were reaped. Safe to call from the scheduler.
    """
    now = time.monotonic()
    stale = [s.user_id for s in all_sessions() if (now - s.last_active) > max_idle_seconds]
    for uid in stale:
        log.info("Reaping idle session for user_id=%d", uid)
        await close(uid)
    return len(stale)
