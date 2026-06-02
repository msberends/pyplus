"""
Core data types for the ML layer.

PurchaseRecord fuses two PLUS data sources:
  - purchased_products_cache  (breadth, incl. in-store — no dates)
  - order_cache + order_item_cache (dated cadence, online orders only)

The dating-gap is first-class: a product bought solely in-store has
ever_bought=True but last_bought=None / frequency=None / dates_complete=False.
Never treat absence-of-order as absence-of-purchase.

UserSettings is stored as JSON in users.settings_json.  All ML features are
off by default; the cart is never auto-modified unless Autopilot is enabled.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class PurchaseRecord:
    sku: str
    name: str
    category: str | None
    ever_bought: bool  # from purchase-history catalogue (online + in-store)
    last_bought: datetime.date | None  # from dated order history — None if in-store only
    order_count: int  # number of dated online orders containing this sku
    frequency: float | None  # buys/week derived from online orders; None if undatable
    dates_complete: bool  # True when ≥2 dated online orders exist (enough for cadence)


class UserSettings(BaseModel):
    """Per-user ML and notification preferences.  All ML off by default."""

    # ── ML ──────────────────────────────────────────────────────────────────
    ml_enabled: bool = False  # master switch for all smart features

    # Active only when ml_enabled=True:
    ml_recommender: bool = True  # week-menu dish suggestions
    ml_replenish: bool = True  # staple due-prediction highlights
    ml_promo_match: bool = True  # sort deals lane by relevance

    # Autopilot: the ONLY setting that allows ML to auto-fill the cart.
    # Off by default — even when ML is on, suggestions are suggest-only.
    ml_autopilot: bool = False

    # Recommender signal weights (0.0–1.0); presented as sliders in Settings.
    ml_afwisseling: float = 0.8  # recency / variety
    ml_vaste_dagen: float = 0.5  # day-of-week habits
    ml_voordeel: float = 0.6  # dishes whose ingredients are on promotion
    ml_voorraad: float = 0.4  # dishes that use staples predicted as due
    ml_variatie: float = 0.5  # category spread across the week

    # ── Notifications (ntfy) ─────────────────────────────────────────────────
    ntfy_url: str = ""
    ntfy_topic: str = ""
    ntfy_username: str = ""
    ntfy_password_enc: str = ""  # Fernet-encrypted; set via Settings screen
    ntfy_weekly_alert: bool = False

    # ── Exports ───────────────────────────────────────────────────────────────
    ical_include_ingredients: bool = False

    # ── Display & behaviour ───────────────────────────────────────────────────
    show_dish_metadata: bool = True  # meat/prep/veg chips on dishes + week menu
    show_promo_tags: bool = True  # "in de aanbieding" tags in cart + staples
    show_cart_savings: bool = True  # cheaper-pack hints + optimise button
    show_replenish_hints: bool = True  # "binnenkort op" highlights in staples
    confirm_clear_slot: bool = False  # ask before clearing a week-menu dish
    hide_unavailable_search: bool = False  # drop unavailable products from search
    search_result_limit: int = 24  # max products shown per search

    # ── Cart & staples organisation ────────────────────────────────────────────
    cart_group_by_category: bool = False  # group cart items under category headers
    cart_sort: str = "cart"  # cart | name | price
    staples_group_by_category: bool = False  # group staples under category headers
    staples_sort: str = "smart"  # smart | name | price
    deals_group_by_category: bool = False  # group promotions under category headers
