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
