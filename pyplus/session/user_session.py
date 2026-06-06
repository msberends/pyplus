"""Per-logged-in-user state: PlusClient, cart, sync status, listener registry."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class UserSession:
    """One per active user. Holds the Playwright browser context and reactive cart state."""

    client: object  # plus.client.PlusClient (typed loosely to avoid circular import)
    user_id: int
    store_number: int
    display_name: str

    _cart: object = field(default=None)  # plus.models.Cart
    _settings: object = field(default=None)  # pyplus.ml.interface.UserSettings
    _cart_listeners: list[Callable] = field(default_factory=list)
    _error_listeners: list[Callable[[str], None]] = field(default_factory=list)

    # Set of SKUs whose qty is currently being sent to the API.
    # The cart component checks this to render a sync indicator per line.
    syncing_skus: set = field(default_factory=set)

    # Monotonic timestamp of last user activity — drives the idle-session reaper
    # so abandoned sessions (and their Playwright browsers) don't live forever.
    last_active: float = field(default_factory=time.monotonic)

    def mark_active(self) -> None:
        self.last_active = time.monotonic()

    # ── Cart access ────────────────────────────────────────────────────────────

    @property
    def cart(self):
        if self._cart is None:
            from plus.models import Cart

            return Cart(items=[], final_total=0.0)
        return self._cart

    def set_cart(self, cart) -> None:
        """Replace the cart and notify all listeners."""
        self._cart = cart
        self.mark_active()
        self._fire_cart_listeners()

    # ── User settings ──────────────────────────────────────────────────────────

    @property
    def settings(self):
        """The user's preferences. Falls back to defaults if not yet loaded."""
        if self._settings is None:
            from pyplus.ml.interface import UserSettings

            return UserSettings()
        return self._settings

    def set_settings(self, settings) -> None:
        self._settings = settings

    def touch(self) -> None:
        """Re-notify listeners without changing cart data (e.g. syncing status changed)."""
        self.mark_active()
        self._fire_cart_listeners()

    def _fire_cart_listeners(self) -> None:
        for cb in list(self._cart_listeners):
            try:
                cb()
            except Exception:
                log.debug("Cart listener error", exc_info=True)

    # ── Cart listener management ───────────────────────────────────────────────

    def add_cart_listener(self, cb: Callable) -> None:
        self._cart_listeners.append(cb)

    def remove_cart_listener(self, cb: Callable) -> None:
        try:
            self._cart_listeners.remove(cb)
        except ValueError:
            pass

    # ── Error listeners ────────────────────────────────────────────────────────

    def add_error_listener(self, cb: Callable[[str], None]) -> None:
        self._error_listeners.append(cb)

    def notify_error(self, message: str) -> None:
        for cb in list(self._error_listeners):
            try:
                cb(message)
            except Exception:
                log.debug("Error listener error", exc_info=True)

    # ── Cart refresh from PLUS API ─────────────────────────────────────────────

    async def refresh_cart(self):
        """Fetch latest cart from PLUS and notify all listeners."""
        cart = await self.client.get_cart_api()
        self.set_cart(cart)
        return cart

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Shut down the Playwright browser for this session."""
        try:
            await self.client.__aexit__(None, None, None)
        except Exception:
            log.debug("Session close error", exc_info=True)
