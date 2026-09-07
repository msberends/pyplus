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
    _stock_alert_listeners: list[Callable[[str], None]] = field(default_factory=list)

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

    # ── Stock alert listeners ─────────────────────────────────────────────

    def add_stock_alert_listener(self, cb: Callable[[str], None]) -> None:
        self._stock_alert_listeners.append(cb)

    def notify_stock_alert(self, product_name: str) -> None:
        for cb in list(self._stock_alert_listeners):
            try:
                cb(product_name)
            except Exception:
                log.debug("Stock alert listener error", exc_info=True)

    # ── Cart refresh from PLUS API ─────────────────────────────────────────────

    async def refresh_cart(self):
        """Fetch latest cart from PLUS and notify all listeners.

        A stale browser session (PLUS returns an HTML login page instead of
        JSON) is recovered transparently by re-logging in with the user's
        stored remember-me credentials and retrying once — the same recovery
        every background job already performs at the start of its run.
        """
        from plus.client import SessionExpiredError
        from pyplus.i18n import t

        try:
            cart = await self.client.get_cart_api()
        except SessionExpiredError:
            log.warning("PLUS-sessie verlopen voor user=%d — opnieuw inloggen…", self.user_id)
            if not await self._relogin():
                self.notify_error(t("cart.refresh_session_expired"))
                return self.cart
            try:
                cart = await self.client.get_cart_api()
            except Exception as exc:
                log.warning("Cart-refresh na relogin mislukt voor user=%d: %s", self.user_id, exc)
                self.notify_error(t("cart.refresh_failed"))
                return self.cart
        except Exception as exc:
            log.warning("Cart-refresh mislukt voor user=%d: %s", self.user_id, exc)
            self.notify_error(t("cart.refresh_failed"))
            return self.cart

        try:
            from pyplus.db.engine import AsyncSessionLocal
            from pyplus.services.cart import enrich_cart_with_provenance

            async with AsyncSessionLocal() as db:
                cart = await enrich_cart_with_provenance(db, self.user_id, cart)
        except Exception:
            log.debug("Cart provenance enrich failed", exc_info=True)
        self.set_cart(cart)
        return cart

    async def _relogin(self) -> bool:
        """Re-authenticate the existing PlusClient with stored remember-me
        credentials, mirroring pyplus/jobs/preload.py's job-startup login.
        Returns False (never raises) when credentials are absent, undecryptable,
        or login fails, so callers can show a clear inline error instead."""
        from pyplus.db import repo
        from pyplus.db.engine import AsyncSessionLocal
        from pyplus.security.secrets import decrypt

        async with AsyncSessionLocal() as db:
            creds = await repo.get_credentials(db, self.user_id)
            user = await repo.get_user_by_id(db, self.user_id)
        if not creds or not user:
            log.warning("relogin: user=%d heeft geen opgeslagen inloggegevens", self.user_id)
            return False

        email = decrypt(user.plus_email_enc)
        password = decrypt(creds.password_enc)
        if not email or not password:
            log.warning(
                "relogin: inloggegevens voor user=%d konden niet worden ontsleuteld",
                self.user_id,
            )
            return False

        try:
            ok = await self.client.login(email, password)
            if ok:
                await self.client.get_session_state()
            return ok
        except Exception:
            log.warning("relogin mislukt voor user=%d", self.user_id, exc_info=True)
            return False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Shut down the Playwright browser for this session."""
        try:
            await self.client.__aexit__(None, None, None)
        except Exception:
            log.debug("Session close error", exc_info=True)
