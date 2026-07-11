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
from typing import Literal

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


class DayPreference(BaseModel):
    """Per-slot planning configuration (stored inside UserSettings.day_preferences)."""

    enabled: bool = True
    max_prep_minutes: int | None = None
    meat_types: dict[str, Literal["enforce", "disallow"]] = {}
    starch_types: dict[str, Literal["enforce", "disallow"]] = {}
    unhealthy: Literal["enforce", "disallow"] | None = None


class WeekConstraints(BaseModel):
    """Cross-week diversity constraints for the recommender."""

    min_vega_days: int = 0
    max_vega_days: int = 7
    min_fish_days: int = 0
    max_same_meat_type: int = 7
    min_unique_starch_types: int = 0
    max_consecutive_same_meat: int = 7
    max_consecutive_same_starch: int = 7
    max_red_meat_days: int = 7
    target_avg_veg_count: float | None = None


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
    ml_ingredient_overlap: float = 0.0  # shared ingredients across week (waste reduction)
    ml_budget: float = 0.0  # prefer cheaper dishes
    ml_rating_weight: float = 1.0  # multiplier strength for dish star ratings
    ml_weather_no_oven: float = 0.0  # penalise oven/airfryer on hot days
    ml_weather_cold: float = 0.0  # boost cold dishes on hot days

    # ── Per-day preferences ────────────────────────────────────────────────
    day_preferences: dict[str, DayPreference] = {}

    # ── Weekly diversity constraints ───────────────────────────────────────
    week_constraints: WeekConstraints = WeekConstraints()

    # ── Advanced ML knobs ──────────────────────────────────────────────────
    ml_repeat_cooldown_weeks: int = 0
    ml_novelty_ratio: float = 0.0
    ml_history_window_weeks: int = 26
    ml_trend_decay_halflife: float = 8.0
    ml_exploration_rate: float = 0.0
    ml_temperature: float = 0.5
    ml_selection_method: str = "softmax"
    ml_confidence_threshold: float = 0.0

    # ── Autopilot extensions ───────────────────────────────────────────────
    ml_autopilot_dinner: bool = False
    ml_autopilot_lunch: bool = False
    ml_autopilot_max_dinner: int = 7
    ml_autopilot_max_lunch: int = 5
    ml_autopilot_staples: bool = True
    ml_autopilot_promos: bool = True
    ml_autopilot_fillers: bool = True
    autopilot_schedule_day: str = "za"
    autopilot_schedule_hour: int = 9
    autopilot_ntfy: bool = True
    autopilot_clear_cart: bool = False
    autopilot_auto_confirm: bool = False
    sub_confidence_auto: float = 7.0
    autopilot_sub_display: int = 5

    # ── Weather-aware planning ────────────────────────────────────────────────
    weather_enabled: bool = False
    weather_latitude: float | None = None
    weather_longitude: float | None = None
    weather_location_name: str = ""
    weather_hot_threshold: float = 25.0
    # Kept for migration compat — superseded by ml_weather_* weights below
    weather_avoid_oven_airfryer: bool = True
    weather_prefer_cold: bool = True
    weather_cold_boost: float = 1.5

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

    # ── Substitutes ─────────────────────────────────────────────────────────────
    sub_prefer_same_brand: bool = False
    sub_prefer_bought: bool = True
    sub_price_range: str = "any"  # "cheaper" | "similar" | "any"
    sub_weight_category: float = 4.0
    sub_weight_name: float = 2.0
    sub_weight_brand: float = 1.0
    sub_weight_price: float = 1.0
    sub_weight_bought: float = 2.0
    sub_max_results: int = 12

    # ── Cart & staples organisation ────────────────────────────────────────────
    cart_group_by_category: bool = False  # group cart items under category headers
    cart_sort: str = "cart"  # cart | name | price
    staples_group_by_category: bool = False  # group staples under category headers
    staples_sort: str = "smart"  # smart | name | price
    deals_group_by_category: bool = False  # group promotions under category headers
