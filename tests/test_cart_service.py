"""Unit tests for CartService — debounce, optimistic updates, rollback."""

import asyncio
from dataclasses import dataclass, field

import pytest

from plus.models import Cart, CartItem
from pyplus.services.cart import CartService


def _item(sku="abc", qty=2, price=1.50) -> CartItem:
    return CartItem(
        product="Test",
        unit="Per stuk",
        price=price,
        quantity=qty,
        sku=sku,
        image_url="",
        line_item_id="lid-" + sku,
    )


@dataclass
class FakeSession:
    _cart: Cart = field(default_factory=lambda: Cart(items=[_item()], final_total=3.00))
    syncing_skus: set = field(default_factory=set)
    _cart_listeners: list = field(default_factory=list)
    _error_listeners: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    _client_calls: list = field(default_factory=list)

    user_id: int = 1
    store_number: int = 720
    display_name: str = "Test"

    @property
    def cart(self):
        return self._cart

    def set_cart(self, c):
        self._cart = c
        self._fire()

    def touch(self):
        self._fire()

    def _fire(self):
        for cb in self._cart_listeners:
            cb()

    def notify_error(self, msg):
        self.errors.append(msg)

    def add_cart_listener(self, cb):
        self._cart_listeners.append(cb)

    def add_error_listener(self, cb):
        self._error_listeners.append(cb)

    class client:
        _session = type("S", (), {"line_item_ids": {"abc": "lid-abc"}})()

        @staticmethod
        async def add_to_cart_api(sku, qty):
            return {
                "Version": 99,
                "LineItemList": {
                    "List": [
                        {
                            "SKU": sku,
                            "Name": "Test",
                            "Subtitle": "Per stuk",
                            "Price": "1.50",
                            "Quantity": qty,
                            "LineItemId": "lid-" + sku,
                            "ImageURL": "",
                        },
                    ]
                },
                "Receipt": {"Price": str(qty * 1.50), "Discount": "0"},
            }

        @staticmethod
        async def remove_from_cart_api(sku, qty):
            remaining = max(0, 2 - qty)
            items = []
            if remaining > 0:
                items.append(
                    {
                        "SKU": sku,
                        "Name": "Test",
                        "Subtitle": "",
                        "Price": "1.50",
                        "Quantity": remaining,
                        "LineItemId": "lid-" + sku,
                        "ImageURL": "",
                    }
                )
            return {
                "Version": 100,
                "LineItemList": {"List": items},
                "Receipt": {"Price": str(remaining * 1.50), "Discount": "0"},
            }


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_optimistic_then_reconcile():
    """Adding 1 unit optimistically updates qty, then reconciles from API."""
    s = FakeSession()
    svc = CartService(s)

    await svc.add("abc")
    # Optimistic: qty should now be 3
    item = next(i for i in s.cart.items if i.sku == "abc")
    assert item.quantity == 3

    # Let debounce fire
    await asyncio.sleep(0.4)
    # After API reconcile: API returned qty=1 (FakeSession.client.add_to_cart_api adds qty delta=1)
    item_after = next((i for i in s.cart.items if i.sku == "abc"), None)
    assert item_after is not None
    assert item_after.quantity == 1  # API returned qty=delta which is 1


@pytest.mark.asyncio
async def test_rapid_taps_coalesced():
    """Three rapid taps produce ONE API call with delta=3."""
    calls = []
    original_add = FakeSession.client.add_to_cart_api

    async def patched_add(sku, qty):
        calls.append(qty)
        return await original_add(sku, qty)

    FakeSession.client.add_to_cart_api = staticmethod(patched_add)
    try:
        s = FakeSession()
        svc = CartService(s)

        # Three rapid taps within debounce window
        await svc.add("abc")
        await asyncio.sleep(0.05)
        await svc.add("abc")
        await asyncio.sleep(0.05)
        await svc.add("abc")

        # Wait for debounce to fire
        await asyncio.sleep(0.4)

        assert len(calls) == 1, f"Expected 1 API call, got {len(calls)}: {calls}"
        assert calls[0] == 3
    finally:
        FakeSession.client.add_to_cart_api = staticmethod(original_add)


@pytest.mark.asyncio
async def test_remove_to_zero_removes_item():
    """Removing all units drops the item from the cart."""
    s = FakeSession()
    svc = CartService(s)

    await svc.remove("abc", qty=2)
    # Optimistic: item gone
    assert not any(i.sku == "abc" for i in s.cart.items)

    await asyncio.sleep(0.4)
    # After reconcile: still gone
    assert not any(i.sku == "abc" for i in s.cart.items)


@pytest.mark.asyncio
async def test_api_failure_rolls_back():
    """When the API call fails, the cart is rolled back to its pre-tap state."""

    async def failing_add(sku, qty):
        raise RuntimeError("PLUS server error")

    s = FakeSession()
    FakeSession.client.add_to_cart_api = staticmethod(failing_add)

    try:
        svc = CartService(s)
        await svc.add("abc")
        # After debounce + failed API call
        await asyncio.sleep(0.4)

        # Cart should be back to original
        item = next((i for i in s.cart.items if i.sku == "abc"), None)
        assert item is not None
        assert item.quantity == 2  # original qty

        # Error was notified
        assert len(s.errors) == 1
    finally:
        from tests.test_cart_service import FakeSession as FS

        FS.client.add_to_cart_api = staticmethod(
            lambda sku, qty: asyncio.coroutine(
                lambda: {
                    "Version": 99,
                    "LineItemList": {
                        "List": [
                            {
                                "SKU": sku,
                                "Name": "Test",
                                "Subtitle": "",
                                "Price": "1.50",
                                "Quantity": qty,
                                "LineItemId": "lid-" + sku,
                                "ImageURL": "",
                            }
                        ]
                    },
                    "Receipt": {"Price": str(qty * 1.50), "Discount": "0"},
                }
            )()
        )


# ── _overlay_pending: in-flight taps survive the authoritative reconcile ──────


def _ci(sku, qty, price=1.50):
    return CartItem(product=sku, unit="", price=price, quantity=qty, sku=sku)


def test_overlay_pending_reapplies_in_flight_delta():
    """A tap that arrived during the flush must not be clobbered by the response."""
    svc = CartService(FakeSession())
    server = Cart(items=[_ci("abc", 2)], final_total=3.0)  # what the flush returned
    optimistic = Cart(items=[_ci("abc", 3)], final_total=4.5)  # newer tap already applied
    svc._pending = {"abc": 1}

    merged = svc._overlay_pending(server, optimistic)
    item = next(i for i in merged.items if i.sku == "abc")
    assert item.quantity == 3  # 2 (server) + 1 (still-pending)
    assert merged.final_total == 4.5  # recomputed from line totals


def test_overlay_pending_keeps_new_optimistic_item():
    """An item added during the flush (not yet known to the server) is preserved."""
    svc = CartService(FakeSession())
    server = Cart(items=[_ci("abc", 2)], final_total=3.0)
    optimistic = Cart(items=[_ci("abc", 2), _ci("zzz", 1, price=2.0)], final_total=5.0)
    svc._pending = {"zzz": 1}

    merged = svc._overlay_pending(server, optimistic)
    assert {i.sku for i in merged.items} == {"abc", "zzz"}
    assert merged.final_total == 5.0


def test_overlay_pending_noop_without_pending():
    svc = CartService(FakeSession())
    server = Cart(items=[_ci("abc", 2)], final_total=3.0)
    svc._pending = {}
    assert svc._overlay_pending(server, server) is server


def test_overlay_pending_drops_item_when_pending_removal():
    """A pending removal to zero during the flush leaves the item out."""
    svc = CartService(FakeSession())
    server = Cart(items=[_ci("abc", 1)], final_total=1.5)
    optimistic = Cart(items=[], final_total=0.0)
    svc._pending = {"abc": -1}

    merged = svc._overlay_pending(server, optimistic)
    assert not any(i.sku == "abc" for i in merged.items)
    assert merged.final_total == 0.0


# ── Savings parsing in _parse_cart_from_checkout ─────────────────────────────────


def _checkout(lines, price, discount=None):
    receipt = {"Price": str(price)}
    if discount is not None:
        receipt["Discount"] = str(discount)
    return {
        "Version": 1,
        "LineItemList": {
            "List": [
                {"SKU": s, "Name": "X", "Subtitle": "", "Price": str(p), "Quantity": q}
                for (s, p, q) in lines
            ]
        },
        "Receipt": receipt,
    }


def test_savings_uses_explicit_discount_when_present():
    from plus.client import _parse_cart_from_checkout

    cart = _parse_cart_from_checkout(_checkout([("a", 1.50, 2)], price=3.0, discount=1.25))
    assert cart.savings == 1.25


def test_savings_derived_from_gross_minus_net_when_discount_absent():
    """Gross line total 10.00, net total 8.00 → 2.00 savings, even with no Discount key."""
    from plus.client import _parse_cart_from_checkout

    cart = _parse_cart_from_checkout(_checkout([("a", 5.00, 2)], price=8.00))
    assert cart.final_total == 8.00
    assert cart.savings == 2.00


def test_savings_zero_when_gross_equals_net():
    from plus.client import _parse_cart_from_checkout

    cart = _parse_cart_from_checkout(_checkout([("a", 1.50, 2)], price=3.0, discount=0))
    assert cart.savings == 0.0


# ── Optimistic total preserves applied discounts (no "bump" to gross) ────────────


def test_optimistic_add_preserves_existing_discount():
    """Adding a unit adjusts the discounted total by one line's value — it does NOT
    flash up to the undiscounted gross sum before the server reconciles."""
    s = FakeSession()
    # Two lines: gross 2*1.50 + 1*4.00 = 7.00, but the cart total is discounted to 5.50.
    s._cart = Cart(
        items=[_ci("abc", 2, price=1.50), _ci("xyz", 1, price=4.00)],
        final_total=5.50,
        savings=1.50,
    )
    svc = CartService(s)
    svc._apply_optimistic("abc", 1, name="", unit="", price=0.0, image="")
    assert s.cart.final_total == 7.00  # 5.50 + 1.50, NOT gross 8.50
    assert s.cart.savings == 1.50  # discount carried through


def test_optimistic_new_item_adds_its_price_to_discounted_base():
    s = FakeSession()
    s._cart = Cart(items=[_ci("abc", 2, price=1.50)], final_total=2.50, savings=0.50)
    svc = CartService(s)
    svc._apply_optimistic("new", 1, name="New", unit="", price=3.00, image="")
    assert s.cart.final_total == 5.50  # 2.50 discounted base + 3.00
    assert any(i.sku == "new" for i in s.cart.items)
