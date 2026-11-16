"""Unit tests for CartService.clear_all — bulk clear, per-item fallback, reconcile."""

from __future__ import annotations

import pytest

from plus.models import Cart, CartItem
from pyplus.services.cart import CartService


def _item(sku: str, qty: int = 1) -> CartItem:
    return CartItem(
        product=sku,
        unit="",
        price=1.0,
        quantity=qty,
        sku=sku,
        image_url="",
        line_item_id="lid-" + sku,
    )


def _checkout(skus: list[str]) -> dict:
    return {
        "Id": "c1",
        "Version": 5,
        "LineItemList": {
            "List": [
                {"SKU": s, "Name": s, "Price": "1.0", "Quantity": 1, "LineItemId": "lid-" + s}
                for s in skus
            ]
        },
        "Receipt": {"Price": str(float(len(skus))), "Discount": "0"},
    }


class FakeClient:
    def __init__(self, *, bulk_ok: bool = True, stuck: set[str] | None = None) -> None:
        self.server = {"a", "b", "c"}
        self.bulk_ok = bulk_ok
        self.stuck = stuck or set()
        self.calls: list[str] = []

    async def clear_cart_api(self) -> dict:
        self.calls.append("clear")
        if not self.bulk_ok:
            raise RuntimeError("SoftDelete failed")
        self.server.clear()
        return _checkout([])

    async def get_cart_api(self) -> Cart:
        self.calls.append("get")
        return Cart(items=[_item(s) for s in sorted(self.server)], final_total=len(self.server))

    async def remove_from_cart_api(self, sku: str, qty: int) -> dict:
        self.calls.append(f"remove:{sku}")
        if sku in self.stuck:
            raise RuntimeError("boom")
        self.server.discard(sku)
        return _checkout(sorted(self.server))


class FakeSession:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.user_id = 1
        self.errors: list[str] = []
        self.syncing_skus: set = set()
        self._cart = Cart(items=[_item(s) for s in ("a", "b", "c")], final_total=3.0)

    @property
    def cart(self) -> Cart:
        return self._cart

    def set_cart(self, c: Cart) -> None:
        self._cart = c

    def touch(self) -> None:
        pass

    def notify_error(self, msg: str) -> None:
        self.errors.append(msg)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    from pyplus.db import repo

    monkeypatch.setattr(repo, "clear_all_cart_provenance", _noop)


@pytest.mark.asyncio
async def test_clear_uses_single_bulk_call():
    client = FakeClient()
    s = FakeSession(client)
    await CartService(s).clear_all()
    assert client.calls == ["clear"]
    assert s.cart.items == []
    assert s.errors == []


@pytest.mark.asyncio
async def test_clear_falls_back_to_per_item_removal():
    client = FakeClient(bulk_ok=False)
    s = FakeSession(client)
    await CartService(s).clear_all()
    assert client.calls[:2] == ["clear", "get"]
    assert {c for c in client.calls if c.startswith("remove:")} == {
        "remove:a",
        "remove:b",
        "remove:c",
    }
    assert s.cart.items == []
    assert s.errors == []


@pytest.mark.asyncio
async def test_clear_shows_what_plus_still_has_when_items_remain():
    client = FakeClient(bulk_ok=False, stuck={"b"})
    s = FakeSession(client)
    await CartService(s).clear_all()
    assert [i.sku for i in s.cart.items] == ["b"]
    assert len(s.errors) == 1
