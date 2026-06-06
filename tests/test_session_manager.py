"""Unit tests for session lifecycle — the fixes against orphaned/leaked browsers:

- register() closes a previous session for the same user (no orphaned browser)
- get() bumps last_active (navigation = activity)
- reap_idle() closes idle sessions and keeps active ones
- UserSession.set_cart/touch mark activity
"""

from __future__ import annotations

import asyncio
import time

import pytest

from plus.models import Cart
from pyplus.session import manager
from pyplus.session.user_session import UserSession


class FakeClient:
    """Stand-in for PlusClient — records whether its browser was closed."""

    def __init__(self) -> None:
        self.closed = False

    async def __aexit__(self, *_exc) -> None:
        self.closed = True


def _make_session(uid: int = 1) -> UserSession:
    return UserSession(client=FakeClient(), user_id=uid, store_number=720, display_name="T")


@pytest.fixture(autouse=True)
def _clear_sessions():
    manager._sessions.clear()
    yield
    manager._sessions.clear()


async def test_register_attaches_cart_service():
    s = _make_session(1)
    manager.register(s)
    assert manager.get(1) is s
    assert getattr(s, "cart_service", None) is not None


async def test_register_closes_previous_session_for_same_user():
    old = _make_session(1)
    new = _make_session(1)
    manager.register(old)
    manager.register(new)
    await asyncio.sleep(0)  # let the fire-and-forget old.close() run
    assert old.client.closed is True  # previous browser released
    assert new.client.closed is False
    assert manager.get(1) is new


async def test_get_bumps_last_active():
    s = _make_session(1)
    manager.register(s)
    s.last_active = time.monotonic() - 100
    stale = s.last_active
    assert manager.get(1) is s
    assert s.last_active > stale


async def test_reap_idle_closes_idle_session():
    s = _make_session(1)
    manager.register(s)
    s.last_active = time.monotonic() - 10_000
    n = await manager.reap_idle(max_idle_seconds=3600)
    assert n == 1
    assert s.client.closed is True
    assert manager.get(1) is None


async def test_reap_idle_keeps_active_session():
    s = _make_session(2)
    manager.register(s)
    s.last_active = time.monotonic()  # fresh
    n = await manager.reap_idle(max_idle_seconds=3600)
    assert n == 0
    assert s.client.closed is False
    assert manager.get(2) is s


async def test_set_cart_and_touch_mark_active():
    s = _make_session(1)
    s.last_active = time.monotonic() - 100
    before = s.last_active
    s.set_cart(Cart(items=[], final_total=0.0))
    assert s.last_active > before

    s.last_active = time.monotonic() - 100
    before = s.last_active
    s.touch()
    assert s.last_active > before
