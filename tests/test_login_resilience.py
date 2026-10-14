"""Regression tests for the "stuck on Automatisch inloggen" class of failures:

- auto-login runs as a server-side job: deduplicated per user, and "in progress"
  ends when the job ends, whether or not a browser ever connected
- every login attempt is bounded by a timeout and releases its browser
- a failed in-place re-login falls back to a fresh browser and swaps it in
"""

from __future__ import annotations

import asyncio

import pytest
from nicegui import core

import plus.client
from pyplus.session.user_session import UserSession
from pyplus.ui.pages import login


class FakeClient:
    """Stand-in for PlusClient. `login_result` None means: hang forever."""

    instances: list[FakeClient] = []

    def __init__(self, headless: bool = True, login_result: bool | None = True) -> None:
        self.login_result = login_result
        self.closed = False
        FakeClient.instances.append(self)

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        self.closed = True

    async def login(self, _email: str, _password: str) -> bool:
        if self.login_result is None:
            await asyncio.Event().wait()
        return bool(self.login_result)

    async def get_session_state(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    FakeClient.instances = []
    login._auto_login_jobs.clear()
    yield
    login._auto_login_jobs.clear()


async def test_auto_login_job_is_deduplicated_and_ends_without_a_browser(monkeypatch):
    monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
    release = asyncio.Event()
    calls = 0

    async def fake_core(**_kwargs):
        nonlocal calls
        calls += 1
        await release.wait()
        return 2

    monkeypatch.setattr(login, "_do_login_core", fake_core)

    job = login._start_auto_login(2, "e", "p")
    assert login._start_auto_login(2, "e", "p") is job  # second tab joins
    await asyncio.sleep(0)
    assert job.running

    release.set()
    await job.task
    assert not job.running and job.succeeded
    assert calls == 1

    # A finished job never blocks a new attempt.
    assert login._start_auto_login(2, "e", "p") is not job


async def test_failed_auto_login_is_not_success(monkeypatch):
    monkeypatch.setattr(core, "loop", asyncio.get_running_loop())

    async def fake_core(**_kwargs):
        return None

    monkeypatch.setattr(login, "_do_login_core", fake_core)
    job = login._start_auto_login(3, "e", "p")
    await job.task
    assert not job.running and not job.succeeded


async def test_hung_login_times_out_and_closes_browser(monkeypatch):
    monkeypatch.setattr(login, "_LOGIN_TIMEOUT_S", 0.05)
    monkeypatch.setattr(plus.client, "PlusClient", lambda headless: FakeClient(login_result=None))
    errors: list[str] = []

    result = await login._do_login_core(
        email="e@example.org",
        password="p",
        remember=True,
        on_progress=lambda _msg: None,
        on_error=errors.append,
    )

    assert result is None
    assert len(errors) == 1
    assert FakeClient.instances[0].closed


def _session(client) -> UserSession:
    return UserSession(client=client, user_id=1, store_number=1, display_name="x")


async def test_fresh_browser_relogin_swaps_client_and_closes_old(monkeypatch):
    monkeypatch.setattr(plus.client, "PlusClient", lambda headless: FakeClient(login_result=True))
    stale = FakeClient(login_result=False)
    session = _session(stale)

    assert await session._relogin_fresh_browser("e", "p")
    assert session.client is not stale
    assert stale.closed
    assert not session.client.closed


async def test_fresh_browser_relogin_failure_keeps_old_and_closes_new(monkeypatch):
    monkeypatch.setattr(plus.client, "PlusClient", lambda headless: FakeClient(login_result=False))
    stale = FakeClient(login_result=False)
    session = _session(stale)

    assert not await session._relogin_fresh_browser("e", "p")
    assert session.client is stale
    assert not stale.closed
    assert FakeClient.instances[-1].closed
