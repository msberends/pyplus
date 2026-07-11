"""
Unit tests for M12 ntfy weekly alert.

Covers:
  - _build_ntfy_message: Dutch message formatting, singular/plural, truncation, deep link
  - _push_ntfy: HTTP POST to correct URL, auth header, error handling
  - weekly_ntfy: spam prevention, settings gate, no-match skip
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyplus.jobs.registry import (
    _NTFY_MAX_PROMOS,
    _build_ntfy_message,
    _push_ntfy,
)
from pyplus.ml.interface import UserSettings

# ── Helpers ───────────────────────────────────────────────────────────────────


def _promo(name: str, sku: str, score: float = 2.0):
    p = MagicMock()
    p.name = name
    p.sku = sku
    p.is_single_product = True
    p.is_free_delivery = False
    return p, score


def _make_db_ctx():
    """Return a callable that works as AsyncSessionLocal: call → async context manager."""
    mock_db = MagicMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    return mock_db


# ── _build_ntfy_message ───────────────────────────────────────────────────────


def test_message_singular():
    msg, _ = _build_ntfy_message([_promo("Melk Houdbaar", "melk")])
    assert "1 product" in msg
    assert "Melk Houdbaar" in msg
    assert "volgende week" in msg
    assert "in de aanbieding" in msg


def test_message_plural():
    promos = [_promo(f"Product {i}", f"sku{i}") for i in range(3)]
    msg, _ = _build_ntfy_message(promos)
    assert "3 producten" in msg
    assert "Product 0" in msg
    assert "Product 2" in msg


def test_message_truncates_beyond_max():
    promos = [_promo(f"P{i}", f"s{i}") for i in range(_NTFY_MAX_PROMOS + 3)]
    msg, _ = _build_ntfy_message(promos)
    assert "… en 3 meer" in msg
    # Names beyond _NTFY_MAX_PROMOS should not appear explicitly
    assert f"P{_NTFY_MAX_PROMOS}" not in msg


def test_message_no_truncation_at_exact_max():
    promos = [_promo(f"P{i}", f"s{i}") for i in range(_NTFY_MAX_PROMOS)]
    msg, _ = _build_ntfy_message(promos)
    assert "meer" not in msg


def test_message_deep_link_included():
    _, click_url = _build_ntfy_message([_promo("Kaas", "kaas")], base_url="http://localhost:8080")
    assert click_url == "http://localhost:8080/weekmenu"


def test_message_no_deep_link_when_base_url_empty():
    msg, click_url = _build_ntfy_message([_promo("Kaas", "kaas")], base_url="")
    assert click_url == ""
    assert "weekmenu" not in msg
    assert "→" not in msg


def test_message_falls_back_to_sku_when_name_empty():
    p, s = _promo("", "melk_sku")
    p.name = ""
    msg, _ = _build_ntfy_message([(p, s)])
    assert "melk_sku" in msg


# ── _push_ntfy ────────────────────────────────────────────────────────────────


def _http_mock(status: int = 200):
    """Build a patched httpx.AsyncClient with a controllable response status."""
    mock_response = MagicMock()
    mock_response.status_code = status

    mock_instance = MagicMock()
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)
    mock_instance.post = AsyncMock(return_value=mock_response)
    return mock_instance


@pytest.mark.asyncio
async def test_push_ntfy_posts_to_correct_url():
    settings = UserSettings(ntfy_url="https://ntfy.sh", ntfy_topic="myshop")
    http = _http_mock(200)
    with patch("httpx.AsyncClient", return_value=http):
        await _push_ntfy(settings, "test body")
    http.post.assert_called_once()
    assert http.post.call_args[0][0] == "https://ntfy.sh/myshop"


@pytest.mark.asyncio
async def test_push_ntfy_strips_trailing_slash():
    settings = UserSettings(ntfy_url="https://ntfy.sh/", ntfy_topic="test")
    http = _http_mock(200)
    with patch("httpx.AsyncClient", return_value=http):
        await _push_ntfy(settings, "body")
    url_called = http.post.call_args[0][0]
    assert url_called == "https://ntfy.sh/test"


@pytest.mark.asyncio
async def test_push_ntfy_raises_on_http_error():
    settings = UserSettings(ntfy_url="https://ntfy.sh", ntfy_topic="test")
    http = _http_mock(401)
    with patch("httpx.AsyncClient", return_value=http):
        with pytest.raises(RuntimeError, match="HTTP 401"):
            await _push_ntfy(settings, "body")


@pytest.mark.asyncio
async def test_push_ntfy_no_auth_header_by_default():
    settings = UserSettings(ntfy_url="https://ntfy.sh", ntfy_topic="test", ntfy_username="")
    http = _http_mock(200)
    with patch("httpx.AsyncClient", return_value=http):
        await _push_ntfy(settings, "body")
    headers_sent = http.post.call_args[1]["headers"]
    assert "Authorization" not in headers_sent


@pytest.mark.asyncio
async def test_push_ntfy_adds_basic_auth():
    settings = UserSettings(
        ntfy_url="https://ntfy.sh",
        ntfy_topic="secure",
        ntfy_username="alice",
        ntfy_password_enc="enc_secret",
    )
    http = _http_mock(200)
    with (
        patch("httpx.AsyncClient", return_value=http),
        patch("pyplus.security.secrets.decrypt", return_value="s3cr3t"),
    ):
        await _push_ntfy(settings, "body")
    headers_sent = http.post.call_args[1]["headers"]
    assert headers_sent.get("Authorization", "").startswith("Basic ")


# ── weekly_ntfy (integration-level) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_ntfy_skips_spam_prevention():
    """Job skips when a push was sent within the last 6 days."""
    from pyplus.jobs.registry import weekly_ntfy

    recent_state = MagicMock()
    recent_state.last_status = "ok"
    recent_state.last_synced_at = datetime.datetime.now(datetime.UTC).replace(
        tzinfo=None
    ) - datetime.timedelta(days=2)

    mock_db = _make_db_ctx()

    with (
        patch("pyplus.jobs.registry._is_locked", AsyncMock(return_value=False)),
        patch("pyplus.db.engine.AsyncSessionLocal", return_value=mock_db),
        patch("pyplus.db.repo.get_sync_state", AsyncMock(return_value=recent_state)),
        patch("pyplus.jobs.registry._push_ntfy") as mock_push,
    ):
        await weekly_ntfy(user_id=1)

    mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_weekly_ntfy_skips_when_ntfy_disabled():
    """No HTTP call when ntfy_weekly_alert=False."""
    from pyplus.jobs.registry import weekly_ntfy

    # State is old enough that spam check passes
    old_state = MagicMock()
    old_state.last_status = "ok"
    old_state.last_synced_at = datetime.datetime.now(datetime.UTC).replace(
        tzinfo=None
    ) - datetime.timedelta(days=8)

    disabled_settings = UserSettings(ntfy_weekly_alert=False)
    mock_db = _make_db_ctx()
    mock_user = MagicMock()
    mock_user.store_number = 1

    with (
        patch("pyplus.jobs.registry._is_locked", AsyncMock(return_value=False)),
        patch("pyplus.jobs.registry._set_status", AsyncMock()),
        patch("pyplus.db.engine.AsyncSessionLocal", return_value=mock_db),
        patch("pyplus.db.repo.get_sync_state", AsyncMock(return_value=old_state)),
        patch(
            "pyplus.db.repo.get_user_settings_json",
            AsyncMock(return_value=disabled_settings.model_dump_json()),
        ),
        patch("pyplus.db.repo.get_user_by_id", AsyncMock(return_value=mock_user)),
        patch("pyplus.jobs.registry._push_ntfy") as mock_push,
    ):
        await weekly_ntfy(user_id=1)

    mock_push.assert_not_called()
