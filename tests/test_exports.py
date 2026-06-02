"""
Unit tests for services/exports.py and security/tokens.py.

Tests cover:
  - build_text_list: formatting, totals, savings row, empty cart
  - build_ical / build_ical_multi_week: valid iCal output, slot→date mapping,
    prep notes in description, multi-week coverage
  - make_ical_token / verify_ical_token: HMAC stability and rejection
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from icalendar import Calendar

from pyplus.services.exports import _slot_to_date, build_ical, build_text_list

# ── Helpers ───────────────────────────────────────────────────────────────────


def _cart(items: list[tuple[str, float, int]], total: float = 0.0, savings: float = 0.0):
    cart = MagicMock()
    cart.items = []
    cart.savings = savings
    running = 0.0
    for name, price, qty in items:
        it = MagicMock()
        it.product = name
        it.price = price
        it.quantity = qty
        it.price_total = price * qty
        running += price * qty
        cart.items.append(it)
    cart.final_total = total if total else running
    return cart


def _weekmenu_row(slot: str, dish_name: str, prep_notes: str = ""):
    row = MagicMock()
    row.slot = slot
    dish = MagicMock()
    dish.name = dish_name
    dish.prep_notes = prep_notes
    row.dish = dish
    return row


# ── _slot_to_date ─────────────────────────────────────────────────────────────


def test_slot_to_date_dinner():
    monday = datetime.date(2026, 6, 1)
    assert _slot_to_date("ma", monday) == datetime.date(2026, 6, 1)
    assert _slot_to_date("di", monday) == datetime.date(2026, 6, 2)
    assert _slot_to_date("zo", monday) == datetime.date(2026, 6, 7)


def test_slot_to_date_lunch():
    monday = datetime.date(2026, 6, 1)
    assert _slot_to_date("lunch1", monday) == datetime.date(2026, 6, 1)
    assert _slot_to_date("lunch5", monday) == datetime.date(2026, 6, 5)


def test_slot_to_date_unknown():
    assert _slot_to_date("unknown", datetime.date(2026, 6, 1)) is None


# ── build_text_list ───────────────────────────────────────────────────────────


def test_text_list_basic():
    cart = _cart([("Melk", 1.29, 2), ("Brood", 2.49, 1)])
    text = build_text_list(cart)
    assert "Melk" in text
    assert "Brood" in text
    assert "2×" in text
    assert "Totaal" in text


def test_text_list_total_formatted():
    cart = _cart([("Kip", 3.99, 2)], total=7.98)
    text = build_text_list(cart)
    assert "7,98" in text


def test_text_list_savings_shown():
    cart = _cart([("Yoghurt", 1.49, 2)], total=1.49, savings=1.49)
    text = build_text_list(cart)
    assert "Bespaard" in text
    assert "1,49" in text


def test_text_list_no_savings_when_zero():
    cart = _cart([("Yoghurt", 1.49, 2)], total=2.98, savings=0.0)
    text = build_text_list(cart)
    assert "Bespaard" not in text


def test_text_list_empty_cart():
    cart = _cart([], total=0.0)
    text = build_text_list(cart)
    assert "0 producten" in text
    assert "Totaal" in text


def test_text_list_week_label():
    cart = _cart([("Melk", 1.29, 1)])
    text = build_text_list(cart, week_label="week 24")
    assert "week 24" in text


def test_text_list_sorted_alphabetically():
    cart = _cart([("Zuivel", 1.0, 1), ("Appel", 1.0, 1)])
    text = build_text_list(cart)
    assert text.index("Appel") < text.index("Zuivel")


# ── build_ical ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ical_basic_structure():
    monday = datetime.date(2026, 6, 1)
    rows = [_weekmenu_row("ma", "Pasta Bolognese", "Verhit de saus 10 min")]

    with patch("pyplus.services.exports.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("pyplus.services.exports.repo.get_weekmenu", new_callable=AsyncMock) as mock_wm:
            mock_wm.return_value = rows
            ical_bytes = await build_ical(user_id=1, week_start=monday)

    assert isinstance(ical_bytes, bytes)
    cal = Calendar.from_ical(ical_bytes)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 1
    ev = events[0]
    assert str(ev["summary"]) == "Pasta Bolognese"
    assert ev["dtstart"].dt == datetime.date(2026, 6, 1)
    assert "Verhit de saus" in str(ev.get("description", ""))


@pytest.mark.asyncio
async def test_ical_lunch_prefix():
    monday = datetime.date(2026, 6, 1)
    rows = [_weekmenu_row("lunch2", "Soep", "")]

    with patch("pyplus.services.exports.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("pyplus.services.exports.repo.get_weekmenu", new_callable=AsyncMock) as mock_wm:
            mock_wm.return_value = rows
            ical_bytes = await build_ical(user_id=1, week_start=monday)

    cal = Calendar.from_ical(ical_bytes)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 1
    assert str(events[0]["summary"]) == "Lunch: Soep"
    # lunch2 → Tuesday
    assert events[0]["dtstart"].dt == datetime.date(2026, 6, 2)


@pytest.mark.asyncio
async def test_ical_skips_empty_slots():
    monday = datetime.date(2026, 6, 1)
    row_filled = _weekmenu_row("wo", "Kip kerrie")
    row_empty = MagicMock()
    row_empty.slot = "do"
    row_empty.dish = None  # slot exists but dish was deleted

    with patch("pyplus.services.exports.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("pyplus.services.exports.repo.get_weekmenu", new_callable=AsyncMock) as mock_wm:
            mock_wm.return_value = [row_filled, row_empty]
            ical_bytes = await build_ical(user_id=1, week_start=monday)

    cal = Calendar.from_ical(ical_bytes)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 1
    assert str(events[0]["summary"]) == "Kip kerrie"


@pytest.mark.asyncio
async def test_ical_empty_week():
    monday = datetime.date(2026, 6, 1)

    with patch("pyplus.services.exports.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("pyplus.services.exports.repo.get_weekmenu", new_callable=AsyncMock) as mock_wm:
            mock_wm.return_value = []
            ical_bytes = await build_ical(user_id=1, week_start=monday)

    assert isinstance(ical_bytes, bytes)
    cal = Calendar.from_ical(ical_bytes)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 0


# ── build_ical_multi_week ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ical_multi_week_aggregates_events():
    from pyplus.services.exports import build_ical_multi_week

    monday = datetime.date(2026, 6, 1)
    week2 = monday + datetime.timedelta(weeks=1)

    wk1_rows = [_weekmenu_row("ma", "Pasta")]
    wk2_rows = [_weekmenu_row("di", "Kip")]

    call_count = [0]

    async def _mock_get_weekmenu(db, user_id, ws):
        call_count[0] += 1
        return wk1_rows if ws == monday else (wk2_rows if ws == week2 else [])

    with patch("pyplus.services.exports.AsyncSessionLocal") as mock_ctx:
        mock_db = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("pyplus.services.exports.repo.get_weekmenu", side_effect=_mock_get_weekmenu):
            ical_bytes = await build_ical_multi_week(user_id=1, week_start=monday, n_weeks=2)

    cal = Calendar.from_ical(ical_bytes)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    summaries = {str(e["summary"]) for e in events}
    assert "Pasta" in summaries
    assert "Kip" in summaries
    assert len(events) == 2
    assert call_count[0] == 2  # one DB call per week


# ── HMAC tokens ───────────────────────────────────────────────────────────────

_KEY = "testkey123"


def test_token_stable():
    from pyplus.security.tokens import make_ical_token

    assert make_ical_token(42, _KEY) == make_ical_token(42, _KEY)
    assert make_ical_token(42, _KEY) is not None


def test_token_differs_per_user():
    from pyplus.security.tokens import make_ical_token

    assert make_ical_token(1, _KEY) != make_ical_token(2, _KEY)


def test_token_verify_ok():
    from pyplus.security.tokens import make_ical_token, verify_ical_token

    token = make_ical_token(7, _KEY)
    assert verify_ical_token(token, 7, _KEY) is True


def test_token_verify_wrong_user():
    from pyplus.security.tokens import make_ical_token, verify_ical_token

    token = make_ical_token(7, _KEY)
    assert verify_ical_token(token, 8, _KEY) is False


def test_token_no_key_returns_none():
    from pyplus.security.tokens import make_ical_token

    assert make_ical_token(1, None) is None


def test_token_verify_no_key_returns_false():
    from pyplus.security.tokens import verify_ical_token

    assert verify_ical_token("anytoken", 1, None) is False
