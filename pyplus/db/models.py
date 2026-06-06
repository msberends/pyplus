"""SQLAlchemy 2.x ORM models — all tables defined up-front for correct migrations."""

from __future__ import annotations

import datetime
import enum
from typing import Optional

from sqlalchemy import (
    DDL,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Enum types ─────────────────────────────────────────────────────────────────


class WeekSlot(str, enum.Enum):
    ma = "ma"
    di = "di"
    wo = "wo"
    do = "do"
    vr = "vr"
    za = "za"
    zo = "zo"
    lunch1 = "lunch1"
    lunch2 = "lunch2"
    lunch3 = "lunch3"
    lunch4 = "lunch4"
    lunch5 = "lunch5"


class SyncResource(str, enum.Enum):
    orders = "orders"
    purchase_catalogue = "purchase_catalogue"
    promotions = "promotions"
    products = "products"
    ml = "ml"


class MlKind(str, enum.Enum):
    recommender = "recommender"
    replenishment = "replenishment"
    promo_match = "promo_match"


# Dish meat/diet categories (carried over from the R app). Stored as plain strings
# on Dish.meat_type; the UI maps them to icons via pyplus.i18n.
MEAT_TYPES = ("vega", "kip", "rund", "varken", "vis", "gecombineerd")
PREP_TIME_BUCKETS = (20, 40, 60, 120)  # minutes — upper bound of each bucket
STARCH_TYPES = ("aardappels", "pasta", "rijst", "noedels", "deeg", "geen_anders")
COOKING_METHODS = ("kookplaat", "oven", "magnetron", "airfryer")


# ── Core user tables ───────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plus_email_enc: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    store_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    store_name: Mapped[str] = mapped_column(String(200), default="")
    user_store_id: Mapped[str] = mapped_column(String(50), default="")
    one_welcome_user_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    last_login_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")

    credentials: Mapped[Optional["Credentials"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    dishes: Mapped[list["Dish"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    fixed_products: Mapped[list["FixedProduct"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    weekmenus: Mapped[list["Weekmenu"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ingredient_skus: Mapped[list["IngredientSku"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sync_states: Mapped[list["SyncState"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    purchased_products: Mapped[list["PurchasedProductCache"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list["OrderCache"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ml_artifacts: Mapped[list["MlArtifact"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Credentials(Base):
    __tablename__ = "credentials"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    remember: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="credentials")


# ── Dishes ─────────────────────────────────────────────────────────────────────


class Dish(Base):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    prep_notes: Mapped[str] = mapped_column(Text, default="")
    # Optional planning metadata (carried over from the R app's "Gerechten beheren").
    prep_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 20/40/60/120
    meat_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # see MEAT_TYPES
    starch_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # see STARCH_TYPES
    cooking_methods: Mapped[str] = mapped_column(
        Text, default="[]"
    )  # JSON list from COOKING_METHODS
    is_cold: Mapped[bool] = mapped_column(Boolean, default=False)
    veg_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0–3
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="dishes")
    ingredients: Mapped[list["DishIngredient"]] = relationship(
        back_populates="dish", cascade="all, delete-orphan", order_by="DishIngredient.sort_order"
    )
    weekmenu_slots: Mapped[list["Weekmenu"]] = relationship(back_populates="dish")


class DishIngredient(Base):
    __tablename__ = "dish_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id", ondelete="CASCADE"))
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    amount_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    pack_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pack_unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    # Flexible = no fixed product; display_name holds the instruction/label and the
    # actual product is chosen at add-to-cart time. Flexible rows have an empty sku.
    flexible: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    dish: Mapped["Dish"] = relationship(back_populates="ingredients")


# ── Per-user-store product facts cache ────────────────────────────────────────


class IngredientSku(Base):
    """Resolved SKU facts for a user's store — cached to avoid re-fetching."""

    __tablename__ = "ingredient_skus"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    slug: Mapped[str] = mapped_column(String(200), default="")  # for plus.nl product links
    image_url: Mapped[str] = mapped_column(Text, default="")
    pack_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pack_unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_seen_available: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_checked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="ingredient_skus")


# ── Fixed products (staples) ───────────────────────────────────────────────────


class FixedProduct(Base):
    __tablename__ = "fixed_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    default_qty: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="fixed_products")


# ── Weekmenu ───────────────────────────────────────────────────────────────────


class Weekmenu(Base):
    __tablename__ = "weekmenu"
    __table_args__ = (
        UniqueConstraint("user_id", "slot", "week_start", name="uq_weekmenu_user_slot_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slot: Mapped[str] = mapped_column(String(20), nullable=False)
    dish_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dishes.id", ondelete="SET NULL"), nullable=True
    )
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    user: Mapped["User"] = relationship(back_populates="weekmenus")
    dish: Mapped[Optional["Dish"]] = relationship(back_populates="weekmenu_slots")


# ── Shared product search cache (store-scoped) ─────────────────────────────────


class ProductCache(Base):
    """Search result cache, keyed by (sku, store_number). Shared across users at the same store."""

    __tablename__ = "product_cache"

    sku: Mapped[str] = mapped_column(String(100), primary_key=True)
    store_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    brand: Mapped[str] = mapped_column(String(200), default="")
    slug: Mapped[str] = mapped_column(String(200), default="")  # for plus.nl product links
    image_url: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON list of PLUS category names forming the product's breadcrumb path,
    # broad → specific, e.g. ["Verse kant-en-klaarmaaltijden", "Italiaanse
    # maaltijden", "Lasagne"]. May be 1+ layers. Captured during catalogue sync.
    categories_json: Mapped[str] = mapped_column(Text, default="[]")
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


# ── Purchase & order history caches ───────────────────────────────────────────


class PurchasedProductCache(Base):
    """Previously-bought catalogue — online + in-store (no dates). Breadth signal."""

    __tablename__ = "purchased_products_cache"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(String(100), primary_key=True)
    brand: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    slug: Mapped[str] = mapped_column(String(200), default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    categories_json: Mapped[str] = mapped_column(Text, default="[]")
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="purchased_products")


class OrderCache(Base):
    """Dated online orders — cadence/recency signal (no in-store dates)."""

    __tablename__ = "order_cache"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_number: Mapped[str] = mapped_column(String(100), default="")
    delivery_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(100), default="")
    channel: Mapped[str] = mapped_column(String(50), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItemCache"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItemCache(Base):
    """Line items for one order. Unavailable items have available=False, quantity=0."""

    __tablename__ = "order_item_cache"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("order_cache.order_id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    slug: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(200), default="")
    available: Mapped[bool] = mapped_column(Boolean, default=True)

    order: Mapped["OrderCache"] = relationship(back_populates="items")


# ── Cache freshness tracking ───────────────────────────────────────────────────


class SyncState(Base):
    """One row per (user, resource) — single source of truth for cache freshness."""

    __tablename__ = "sync_state"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    resource: Mapped[str] = mapped_column(String(30), primary_key=True)
    last_synced_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="sync_states")


class PromotionsCache(Base):
    """This week's (and optionally next week's) promotions, keyed by store."""

    __tablename__ = "promotions_cache"
    __table_args__ = (
        UniqueConstraint("store_number", "week_start", "is_next_week", name="uq_promos_store_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_number: Mapped[int] = mapped_column(Integer, nullable=False)
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    is_next_week: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class MlArtifact(Base):
    """Precomputed ML outputs — written by background jobs, read at open time."""

    __tablename__ = "ml_artifacts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(30), primary_key=True)
    blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    trained_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    input_hash: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped["User"] = relationship(back_populates="ml_artifacts")


# ── Weather cache ─────────────────────────────────────────────────────────────


class WeatherCache(Base):
    """Daily temperature cache — fetched from Open-Meteo, used by ML for weather-aware planning."""

    __tablename__ = "weather_cache"

    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, primary_key=True)
    longitude: Mapped[float] = mapped_column(Float, primary_key=True)
    temperature_max: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


# ── Product catalogue full-text index ──────────────────────────────────────────
# Created right after product_cache on any create_all() (e.g. the test suite).
# Production DBs get the identical DDL through an Alembic migration. See db/fts.py.
from pyplus.db import fts as _fts  # noqa: E402

for _stmt in _fts.ALL_STATEMENTS:
    event.listen(ProductCache.__table__, "after_create", DDL(_stmt))
