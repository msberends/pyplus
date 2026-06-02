"""
Cart mutation service — optimistic updates, 300 ms debounce per SKU, API reconcile.

One instance per UserSession. Attach as session.cart_service after creation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyplus.session.user_session import UserSession

log = logging.getLogger(__name__)

_DEBOUNCE = 0.30  # seconds


class CartService:
    def __init__(self, session: "UserSession") -> None:
        self.session = session
        self._pending: dict[str, int] = {}  # sku → accumulated unsent delta
        self._tasks: dict[str, asyncio.Task] = {}  # sku → active debounce task
        self._snapshots: dict[str, object] = {}  # sku → pre-cycle Cart (for rollback)

    # ── Public ─────────────────────────────────────────────────────────────────

    async def add(
        self,
        sku: str,
        qty: int = 1,
        *,
        product_name: str = "",
        product_unit: str = "",
        product_price: float = 0.0,
        product_image: str = "",
    ) -> None:
        """Add qty units of sku. Warns (non-blocking) if the item is cached as unavailable."""
        # Best-effort availability check — reads cached DB value, never blocks the add
        try:
            import datetime as _dt

            from pyplus.db import repo as _repo
            from pyplus.db.engine import AsyncSessionLocal as _ASL

            async with _ASL() as _db:
                _cached = await _repo.get_ingredient_sku(_db, self.session.user_id, sku)
            if _cached and _cached.last_seen_available is False and _cached.last_checked_at:
                _age_days = (_dt.datetime.utcnow() - _cached.last_checked_at).days
                if _age_days < 7:
                    from pyplus.i18n import t

                    self.session.notify_error(t("error.product_unavailable_cached"))
        except Exception:
            pass  # never block the add due to availability check failure

        await self._queue(
            sku,
            +qty,
            name=product_name,
            unit=product_unit,
            price=product_price,
            image=product_image,
        )

    async def remove(self, sku: str, qty: int = 1) -> None:
        """Remove qty units of sku."""
        await self._queue(sku, -qty)

    async def set_quantity(self, sku: str, new_qty: int) -> None:
        """Jump directly to new_qty (used by inline numeric input in M3 polish)."""
        current = next((it.quantity for it in self.session.cart.items if it.sku == sku), 0)
        delta = new_qty - current
        if delta != 0:
            await self._queue(sku, delta)

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _queue(
        self,
        sku: str,
        delta: int,
        *,
        name: str = "",
        unit: str = "",
        price: float = 0.0,
        image: str = "",
    ) -> None:
        # Take a pre-cycle snapshot on the very first tap of each debounce cycle.
        if sku not in self._pending:
            self._snapshots[sku] = self.session.cart

        self._apply_optimistic(sku, delta, name=name, unit=unit, price=price, image=image)
        self._pending[sku] = self._pending.get(sku, 0) + delta

        # Cancel previous debounce task and start a fresh one.
        if sku in self._tasks and not self._tasks[sku].done():
            self._tasks[sku].cancel()
        self._tasks[sku] = asyncio.create_task(self._debounce_and_flush(sku))

    async def _debounce_and_flush(self, sku: str) -> None:
        try:
            await asyncio.sleep(_DEBOUNCE)
        except asyncio.CancelledError:
            return  # A newer tap arrived — its task will flush.

        delta = self._pending.pop(sku, 0)
        self._tasks.pop(sku, None)
        if delta == 0:
            self._snapshots.pop(sku, None)
            return

        await self._api_flush(sku, delta)

    async def _api_flush(self, sku: str, delta: int) -> None:
        snapshot = self._snapshots.pop(sku, None) or self.session.cart
        self.session.syncing_skus.add(sku)
        self.session.touch()  # re-render to show sync indicator

        try:
            if delta > 0:
                checkout = await self.session.client.add_to_cart_api(sku, delta)
            else:
                checkout = await self.session.client.remove_from_cart_api(sku, abs(delta))

            # Reconcile with authoritative server response.
            from plus.client import _parse_cart_from_checkout

            self.session.set_cart(_parse_cart_from_checkout(checkout))

        except Exception as exc:
            log.warning("Cart API error (sku=%s delta=%+d): %s", sku, delta, exc)
            self.session.set_cart(snapshot)  # rollback
            from pyplus.i18n import t

            msg = t("error.cart_add_failed") if delta > 0 else t("error.cart_remove_failed")
            self.session.notify_error(msg)

        finally:
            self.session.syncing_skus.discard(sku)
            self.session.touch()  # re-render to clear sync indicator

    def _apply_optimistic(
        self,
        sku: str,
        delta: int,
        *,
        name: str,
        unit: str,
        price: float,
        image: str,
    ) -> None:
        from plus.models import CartItem

        cart = self.session.cart
        new_items = list(cart.items)
        found = False

        for i, item in enumerate(new_items):
            if item.sku == sku:
                found = True
                new_qty = item.quantity + delta
                if new_qty > 0:
                    new_items[i] = item.model_copy(update={"quantity": new_qty})
                else:
                    new_items.pop(i)
                break

        if not found and delta > 0 and name:
            # New item from a lane (M4+).
            new_items.append(
                CartItem(
                    product=name,
                    unit=unit,
                    price=price,
                    quantity=delta,
                    sku=sku,
                    image_url=image,
                )
            )

        new_total = sum(it.price_total for it in new_items)
        self.session.set_cart(
            cart.model_copy(update={"items": new_items, "final_total": new_total})
        )
