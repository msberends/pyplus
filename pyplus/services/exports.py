"""
Export service — iCal and plain-text shopping list.

build_ical(user_id, week_start)              → bytes  one-week .ics (download)
build_ical_multi_week(user_id, week_start)   → bytes  multi-week .ics (subscription)
build_text_list(cart)                        → str    plain shopping list
build_html_list(cart, user_id, store_number) → str    printable HTML shopping list

All functions are pure (no UI) and testable without a running app.
"""

from __future__ import annotations

import datetime
import uuid
import zoneinfo

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
    from pyplus.ml.interface import UserSettings

    async with AsyncSessionLocal() as db:
        rows = await repo.get_weekmenu(db, user_id, week_start)

        # Settings + ingredients are best-effort: the calendar must still build
        # (with just prep notes) if either lookup fails.
        settings = UserSettings()
        ingredients_by_dish: dict[int, list] = {}
        try:
            settings = UserSettings.model_validate_json(
                await repo.get_user_settings_json(db, user_id)
            )
        except Exception:
            settings = UserSettings()
        sku_cache: dict[str, object] = {}
        if settings.ical_include_ingredients:
            try:
                for row in rows:
                    if row.dish is not None and row.dish.id not in ingredients_by_dish:
                        ingredients_by_dish[row.dish.id] = await repo.get_ingredients(
                            db, row.dish.id
                        )
            except Exception:
                ingredients_by_dish = {}
            # Pack-size enrichment is a nice-to-have on top of the ingredient lines
            # above — a failure here shouldn't discard ingredients we already have.
            try:
                skus = {ing.sku for ings in ingredients_by_dish.values() for ing in ings if ing.sku}
                sku_cache = await repo.get_ingredient_skus_by_skus(db, user_id, list(skus))
            except Exception:
                sku_cache = {}

    events: list[Event] = []
    for row in rows:
        dish = row.dish
        if dish is None:
            continue
        event_date = _slot_to_date(row.slot, week_start)
        if event_date is None:
            continue

        is_extra = row.slot.startswith("lunch")
        ams = zoneinfo.ZoneInfo("Europe/Amsterdam")

        event = Event()
        event.add("uid", str(uuid.uuid4()) + "@pyplus")
        if is_extra:
            event.add("dtstart", event_date)
            event.add("dtend", event_date + datetime.timedelta(days=1))
        else:
            dtstart = datetime.datetime(
                event_date.year, event_date.month, event_date.day, 17, 30, tzinfo=ams
            )
            event.add("dtstart", dtstart)
            event.add("dtend", dtstart + datetime.timedelta(hours=1))
        event.add(
            "summary",
            f"Extra: {dish.name}" if is_extra else dish.name,
        )
        event.add("status", "CONFIRMED")
        event.add("transp", "TRANSPARENT")
        event.add("class", "PRIVATE")

        desc_parts: list[str] = []
        if dish.prep_notes and dish.prep_notes.strip():
            desc_parts.append(dish.prep_notes.strip())
        if settings.ical_include_ingredients:
            ings = ingredients_by_dish.get(dish.id, [])
            lines = [_format_ingredient_line(ing, sku_cache) for ing in ings]
            lines = [ln for ln in lines if ln]
            if lines:
                desc_parts.append("Ingrediënten:\n" + "\n".join(lines))
        if desc_parts:
            event.add("description", "\n\n".join(desc_parts))
        events.append(event)

    return events


def _format_ingredient_line(ing, sku_cache: dict[str, object] | None = None) -> str:
    """One concise ingredient line, e.g. '• 2x Naam (500 g)', '• Naam', '• 500 g Naam'."""
    name = (ing.display_name or "").strip()
    if not name:
        return ""
    amount = ing.amount or 0
    unit = (ing.amount_unit or "").strip()

    # DishIngredient.pack_size is only set at add-time and often stale/missing;
    # the ingredient_skus cache is kept warm by a background job and covers far
    # more products, so prefer it and fall back to the DishIngredient value.
    pack_size = ing.pack_size
    pack_unit = (ing.pack_unit or "").strip()
    cached = (sku_cache or {}).get(ing.sku) if ing.sku else None
    if cached is not None and cached.pack_size and cached.pack_unit:
        pack_size, pack_unit = cached.pack_size, cached.pack_unit.strip()
    pack_suffix = f" ({pack_size:g} {pack_unit})" if pack_size and pack_unit else ""

    if unit in ("", "stuks"):
        # Countable: drop the count for a single item, else "Nx".
        base = f"• {amount:g}x {name}" if amount and amount != 1 else f"• {name}"
        return f"{base}{pack_suffix}"
    # Measured (g, ml, teen, …): keep the amount + unit.
    qty = f"{amount:g}" if amount else ""
    prefix = " ".join(p for p in (qty, unit) if p)
    base = f"• {prefix} {name}" if prefix else f"• {name}"
    return f"{base}{pack_suffix}"


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
        savings = f"€ {cart.savings:.2f}".replace(".", ",")
        lines.append(f"  {'Korting':<{name_w + 6}}  {savings:>8}")

    lines += [
        "",
        f"  {len(cart.items)} producten · PyPLUS",
    ]

    return "\n".join(lines)


# ── HTML shopping list ──────────────────────────────────────────────────────────


def _eur(value: float) -> str:
    return f"€ {value:.2f}".replace(".", ",")


async def build_html_list(
    cart,
    user_id: int,
    store_number: int,
    category_order: str = "alpha",
    week_label: str = "",
) -> str:
    """
    Build a self-contained, printable HTML shopping list from the current PLUS
    cart: grouped by top-level product category (cache-only lookup, no PLUS
    call), sorted alphabetically within each group, with unit/weight shown
    per line. Inline CSS so it can be opened directly in a browser tab and
    printed with Ctrl+P.
    """
    import html as _html

    from pyplus.services.categories import (
        get_category_index,
        get_category_order_map,
        group_order,
        top_category,
    )

    skus = [i.sku for i in cart.items if i.sku]
    cat_by_sku = await get_category_index(store_number, user_id, skus) if skus else {}
    order_map = await get_category_order_map() if category_order == "plus" else {}

    buckets: dict[str, list] = {}
    for item in cart.items:
        buckets.setdefault(top_category(cat_by_sku.get(item.sku, [])), []).append(item)
    for group_items in buckets.values():
        group_items.sort(key=lambda i: i.product.lower())

    title = f"Boodschappenlijst — {week_label}" if week_label else "Boodschappenlijst"
    today = datetime.date.today().strftime("%d-%m-%Y")

    sections: list[str] = []
    for cat in group_order(list(buckets), order_map or None):
        rows = "\n".join(
            f"""        <tr>
          <td class="qty">{item.quantity}×</td>
          <td class="name">{_html.escape(item.product)}</td>
          <td class="unit">{_html.escape(item.unit)}</td>
          <td class="price">{_eur(item.price_total)}</td>
        </tr>"""
            for item in buckets[cat]
        )
        sections.append(
            f'      <h2 class="group">{_html.escape(cat)}</h2>\n'
            f"      <table>\n        <tbody>\n{rows}\n        </tbody>\n      </table>"
        )

    savings_row = (
        f'      <div class="row savings"><span>Korting</span><span>{_eur(cart.savings)}</span></div>'
        if cart.savings > 0.01
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>{_html.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 2rem 1rem;
    background: #f2f4f0;
    color: #1c1f1c;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .sheet {{
    max-width: 640px;
    margin: 0 auto;
    background: #fff;
    border-radius: 12px;
    padding: 2rem 2.25rem;
    box-shadow: 0 1px 3px rgba(0, 0, 0, .08);
  }}
  h1 {{
    margin: 0 0 .125rem;
    font-size: 1.5rem;
    font-weight: 700;
    color: #007a3d;
  }}
  .meta {{
    margin: 0 0 1.5rem;
    font-size: .85rem;
    color: #6b706b;
  }}
  h2.group {{
    font-size: .8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .04em;
    color: #4c534c;
    border-bottom: 1px solid #e2e5e0;
    margin: 1.5rem 0 .5rem;
    padding-bottom: .25rem;
  }}
  h2.group:first-of-type {{ margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: .35rem 0; font-size: .95rem; vertical-align: baseline; }}
  tbody tr + tr td {{ border-top: 1px solid #f0f1ee; }}
  td.qty {{ width: 2.75rem; color: #6b706b; font-variant-numeric: tabular-nums; }}
  td.unit {{ color: #8a8f8a; font-size: .8rem; padding-left: .5rem; white-space: nowrap; }}
  td.price {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; padding-left: .5rem; }}
  .totals {{ margin-top: 1.5rem; border-top: 2px solid #1c1f1c; padding-top: .5rem; }}
  .totals .row {{ display: flex; justify-content: space-between; font-size: .95rem; padding: .15rem 0; }}
  .totals .row.total {{ font-weight: 700; font-size: 1.05rem; }}
  .totals .row.savings {{ color: #007a3d; }}
  .footer-note {{ margin-top: 1.5rem; font-size: .75rem; color: #9a9e9a; text-align: center; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .sheet {{ box-shadow: none; border-radius: 0; max-width: none; padding: 0; }}
  }}
</style>
</head>
<body>
  <div class="sheet">
    <h1>{_html.escape(title)}</h1>
    <p class="meta">{len(cart.items)} producten · gegenereerd via PyPLUS op {today}</p>
{chr(10).join(sections)}
    <div class="totals">
      <div class="row total"><span>Totaal</span><span>{_eur(cart.final_total)}</span></div>
{savings_row}
    </div>
    <p class="footer-note">PyPLUS</p>
  </div>
</body>
</html>
"""
