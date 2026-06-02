"""
Export service — iCal and plain-text shopping list.

build_ical(user_id, week_start)              → bytes  one-week .ics (download)
build_ical_multi_week(user_id, week_start)   → bytes  multi-week .ics (subscription)
build_text_list(cart)                        → str    plain shopping list

All functions are pure (no UI) and testable without a running app.
"""

from __future__ import annotations

import datetime
import uuid

from icalendar import Calendar, Event

from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal

# ── Slot → calendar date mapping ──────────────────────────────────────────────

_DINNER_OFFSET = {"ma": 0, "di": 1, "wo": 2, "do": 3, "vr": 4, "za": 5, "zo": 6}
_LUNCH_OFFSET = {"lunch1": 0, "lunch2": 1, "lunch3": 2, "lunch4": 3, "lunch5": 4}


def _slot_to_date(slot: str, week_start: datetime.date) -> datetime.date | None:
    if slot in _DINNER_OFFSET:
        return week_start + datetime.timedelta(days=_DINNER_OFFSET[slot])
    if slot in _LUNCH_OFFSET:
        return week_start + datetime.timedelta(days=_LUNCH_OFFSET[slot])
    return None


def _make_calendar() -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//PyPLUS//NL")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "PyPLUS weekmenu")
    cal.add("x-wr-timezone", "Europe/Amsterdam")
    return cal


async def _build_events(user_id: int, week_start: datetime.date) -> list[Event]:
    """Load weekmenu from DB and return iCal Event objects for filled slots."""
    async with AsyncSessionLocal() as db:
        rows = await repo.get_weekmenu(db, user_id, week_start)

    events: list[Event] = []
    for row in rows:
        dish = row.dish
        if dish is None:
            continue
        event_date = _slot_to_date(row.slot, week_start)
        if event_date is None:
            continue

        event = Event()
        event.add("uid", str(uuid.uuid4()) + "@pyplus")
        event.add("dtstart", event_date)
        event.add("dtend", event_date + datetime.timedelta(days=1))
        event.add(
            "summary",
            f"Lunch: {dish.name}" if row.slot.startswith("lunch") else dish.name,
        )
        event.add("status", "CONFIRMED")
        event.add("transp", "TRANSPARENT")
        event.add("class", "PRIVATE")
        if dish.prep_notes and dish.prep_notes.strip():
            event.add("description", dish.prep_notes.strip())
        events.append(event)

    return events


# ── iCal export ────────────────────────────────────────────────────────────────


async def build_ical(user_id: int, week_start: datetime.date) -> bytes:
    """Single-week iCal — for the one-off .ics download button."""
    cal = _make_calendar()
    for ev in await _build_events(user_id, week_start):
        cal.add_component(ev)
    return cal.to_ical()


async def build_ical_multi_week(user_id: int, week_start: datetime.date, n_weeks: int = 4) -> bytes:
    """
    Multi-week iCal — for the /menu.ics subscription endpoint.

    Builds events for `n_weeks` consecutive weeks starting from `week_start`,
    covering past + current + future weeks so clients always have context.
    """
    cal = _make_calendar()
    for i in range(n_weeks):
        ws = week_start + datetime.timedelta(weeks=i)
        for ev in await _build_events(user_id, ws):
            cal.add_component(ev)
    return cal.to_ical()


# ── Plain-text shopping list ───────────────────────────────────────────────────


def build_text_list(cart, week_label: str = "") -> str:
    """
    Build a plain UTF-8 shopping list from the current PLUS cart.

    Lines are sorted alphabetically by product name and padded for readability.
    Designed for copy-paste or printing — no Markdown, no ANSI.
    """
    title = f"Boodschappenlijst — {week_label}" if week_label else "Boodschappenlijst"
    rule = "─" * 50

    lines: list[str] = [
        title,
        rule,
        "",
    ]

    items = sorted(cart.items, key=lambda i: i.product.lower())
    name_w = min(40, max((len(i.product) for i in items), default=20))

    for item in items:
        qty = f"{item.quantity}×"
        name = item.product
        price = f"€ {item.price_total:.2f}".replace(".", ",")
        lines.append(f"  {qty:>3}  {name:<{name_w}}  {price:>8}")

    lines += [
        "",
        rule,
    ]

    total = f"€ {cart.final_total:.2f}".replace(".", ",")
    lines.append(f"  {'Totaal':<{name_w + 6}}  {total:>8}")

    if cart.savings > 0.01:
        savings = f"−€ {cart.savings:.2f}".replace(".", ",")
        lines.append(f"  {'Bespaard':<{name_w + 6}}  {savings:>8}")

    lines += [
        "",
        f"  {len(cart.items)} producten · PyPLUS",
    ]

    return "\n".join(lines)
