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
        source: str = "",
        check_stock: bool = True,
    ) -> bool:
        """Add qty units of sku. Returns False (and fires stock alert) if out of stock."""
        if check_stock:
            try:
                from pyplus.db import repo as _repo
                from pyplus.db.engine import AsyncSessionLocal as _ASL

                store = self.session.store_number
                if store:
                    async with _ASL() as _db:
                        cache = await _repo.get_product_cache_by_skus(_db, store, [sku])
                        pc = cache.get(sku)
                        if pc is not None and not pc.is_available:
                            self.session.notify_stock_alert(product_name or pc.name)
                            return False
                        if pc is None:
                            count = await _repo.count_product_cache(_db, store)
                            if count > 0:
                                self.session.notify_stock_alert(product_name or sku)
                                return False
            except Exception:
                pass  # never block the add due to check failure

        await self._queue(
            sku,
            +qty,
            name=product_name,
            unit=product_unit,
            price=product_price,
            image=product_image,
            source=source,
        )
        return True

    async def remove(self, sku: str, qty: int = 1) -> None:
        """Remove qty units of sku."""
        await self._queue(sku, -qty)

    async def set_quantity(self, sku: str, new_qty: int) -> None:
        """Jump directly to new_qty (used by inline numeric input in M3 polish)."""
        current = next((it.quantity for it in self.session.cart.items if it.sku == sku), 0)
        delta = new_qty - current
        if delta != 0:
            await self._queue(sku, delta)

    async def clear_all(self) -> None:
        """Remove every item from the cart (optimistic clear + API calls)."""
        items = list(self.session.cart.items)
        if not items:
            return
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()
        self._pending.clear()
        self._snapshots.clear()

        from plus.models import Cart

        snapshot = self.session.cart
        self.session.set_cart(Cart(items=[], final_total=0.0, savings=0.0))

        try:
            checkout = None
            for item in items:
                checkout = await self.session.client.remove_from_cart_api(item.sku, item.quantity)
            if checkout:
                from plus.client import _parse_cart_from_checkout

                new_cart = _parse_cart_from_checkout(checkout)
                self.session.set_cart(new_cart)
        except Exception as exc:
            log.warning("Clear cart error: %s", exc)
            self.session.set_cart(snapshot)
            from pyplus.i18n import t

            self.session.notify_error(t("cart.clear_failed"))

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
        source: str = "",
    ) -> None:
        # Take a pre-cycle snapshot on the very first tap of each debounce cycle.
        if sku not in self._pending:
            self._snapshots[sku] = self.session.cart

        self._apply_optimistic(
            sku, delta, name=name, unit=unit, price=price, image=image, source=source
        )
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

            new_cart = _parse_cart_from_checkout(checkout)
            # PLUS cart API doesn't return ImageURLs or source tags — preserve from optimistic cart.
            old_images = {it.sku: it.image_url for it in self.session.cart.items if it.image_url}
            old_sources = {it.sku: it.source for it in self.session.cart.items if it.source}
            if old_images or old_sources:
                patched = []
                for it in new_cart.items:
                    updates = {}
                    if not it.image_url and it.sku in old_images:
                        updates["image_url"] = old_images[it.sku]
                    if not it.source and it.sku in old_sources:
                        updates["source"] = old_sources[it.sku]
                    patched.append(it.model_copy(update=updates) if updates else it)
                new_cart = new_cart.model_copy(update={"items": patched})
            # Re-apply any taps that arrived while this call was in flight, so the
            # authoritative response doesn't clobber newer optimistic state (which
            # would make quantities/total briefly jump backwards).
            new_cart = self._overlay_pending(new_cart, self.session.cart)
            self.session.set_cart(new_cart)

        except Exception as exc:
            log.warning("Cart API error (sku=%s delta=%+d): %s", sku, delta, exc)
            self.session.set_cart(snapshot)  # rollback
            from pyplus.i18n import t

            msg = t("error.cart_add_failed") if delta > 0 else t("error.cart_remove_failed")
            self.session.notify_error(msg)

        finally:
            self.session.syncing_skus.discard(sku)
            self.session.touch()  # re-render to clear sync indicator

    def _overlay_pending(self, server_cart, optimistic_cart):
        """Overlay still-unflushed optimistic deltas onto the authoritative cart.

        When this flush started, its delta was popped from ``_pending``; anything
        left there (or re-added by taps during the network call, for this or other
        SKUs) must survive the reconcile. New items not yet known to the server are
        carried over from the optimistic cart. The total is adjusted from the
        server's *discounted* total by each pending line's value — never recomputed
        as the gross sum — so applied promotions are kept and the total doesn't flash.
        """
        if not self._pending:
            return server_cart

        opt_by_sku = {it.sku: it for it in optimistic_cart.items}
        items = []
        seen = set()
        delta_value = 0.0
        for it in server_cart.items:
            seen.add(it.sku)
            pend = self._pending.get(it.sku, 0)
            new_qty = it.quantity + pend
            if new_qty > 0:
                items.append(it.model_copy(update={"quantity": new_qty}) if pend else it)
                delta_value += it.price * pend
            else:
                delta_value -= it.price * it.quantity  # whole line removed in-flight
        # Pending adds for SKUs the server hasn't seen yet — keep the optimistic line.
        for sku, delta in self._pending.items():
            if delta > 0 and sku not in seen and sku in opt_by_sku:
                opt = opt_by_sku[sku]
                items.append(opt)
                delta_value += opt.price * opt.quantity

        new_total = max(0.0, round(server_cart.final_total + delta_value, 2))
        return server_cart.model_copy(update={"items": items, "final_total": new_total})

    def _apply_optimistic(
        self,
        sku: str,
        delta: int,
        *,
        name: str,
        unit: str,
        price: float,
        image: str,
        source: str = "",
    ) -> None:
        from plus.models import CartItem

        cart = self.session.cart
        new_items = list(cart.items)
        found = False
        unit_price = price  # for a brand-new line, the caller supplies the price

        for i, item in enumerate(new_items):
            if item.sku == sku:
                found = True
                unit_price = item.price  # known per-unit price of the existing line
                new_qty = item.quantity + delta
                if new_qty > 0:
                    # Merge source: append new origin if not already present.
                    if source and source not in (item.source or "").split(","):
                        merged = ",".join(filter(None, [item.source, source]))
                        new_items[i] = item.model_copy(
                            update={"quantity": new_qty, "source": merged}
                        )
                    else:
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
                    source=source,
                )
            )

        # Adjust the existing (already-discounted) total by just this line's value
        # rather than recomputing the gross sum of every line. Recomputing gross
        # discarded the cart's applied promotions, so the total flashed *up* to the
        # undiscounted amount and then dropped back when the server reconciled —
        # that's the unprofessional "bump". Keeping the discounted base avoids it;
        # any promo on the changed line itself is corrected on reconcile (small).
        new_total = max(0.0, round(cart.final_total + unit_price * delta, 2))
        self.session.set_cart(
            cart.model_copy(update={"items": new_items, "final_total": new_total})
        )
