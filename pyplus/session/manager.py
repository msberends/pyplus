"""Server-side session registry. One UserSession per active user (user_id)."""

from __future__ import annotations

import logging

from pyplus.session.user_session import UserSession

log = logging.getLogger(__name__)

# user_id → UserSession
_sessions: dict[int, UserSession] = {}


def get(user_id: int) -> UserSession | None:
    return _sessions.get(user_id)


def register(session: UserSession) -> None:
    """Register a session and attach its CartService."""
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
