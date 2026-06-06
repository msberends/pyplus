"""Unit tests for the bulk-upsert repo helpers (the N+1 → ON CONFLICT rewrites)
and the batched dish-availability query."""

from __future__ import annotations

import datetime
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from plus.models import OrderLineItem, OrderSummary, PurchasedProduct
from pyplus.db import repo
from pyplus.db.models import (
    Base,
    Dish,
    DishIngredient,
    IngredientSku,
    OrderCache,
    OrderItemCache,
)

USER = 5


@pytest_asyncio.fixture
async def sf():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _pp(sku, name, brand="B", available=True, cats=None):
    return PurchasedProduct(
        sku=sku,
        brand=brand,
        name=name,
        subtitle="Per stuk",
        slug=f"{name}-{sku}",
        image_url=f"i/{sku}",
        price=1.0,
        is_available=available,
        categories=cats or [],
    )


def _order(order_id, delivery="2026-03-16", total=42.0, active=False):
    return OrderSummary(
        order_id=order_id,
        order_number="N" + order_id,
        delivery_date=delivery,
        delivery_start="10:00",
        delivery_end="12:00",
        total_price=total,
        status="Bezorgd",
        channel="Web",
        is_active=active,
    )


# ── upsert_purchased_products ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purchased_products_insert_update_and_isolation(sf):
    async with sf() as db:
        await repo.upsert_purchased_products(db, USER, [_pp("1", "Melk", cats=["Zuivel"])])
    async with sf() as db:
        got = await repo.get_purchased_products_by_skus(db, USER, ["1"])
        assert got["1"].name == "Melk"
        assert json.loads(got["1"].categories_json) == ["Zuivel"]
        # other user can't see it
        assert await repo.get_purchased_products_by_skus(db, 999, ["1"]) == {}

    # Re-upsert same SKU → updates in place (no duplicate row)
    async with sf() as db:
        await repo.upsert_purchased_products(db, USER, [_pp("1", "Melk halfvol", available=False)])
    async with sf() as db:
        got = await repo.get_purchased_products_by_skus(db, USER, ["1"])
        assert got["1"].name == "Melk halfvol"
        assert got["1"].is_available is False


@pytest.mark.asyncio
async def test_purchased_products_empty_is_noop(sf):
    async with sf() as db:
        await repo.upsert_purchased_products(db, USER, [])
        assert await repo.get_purchased_products_by_skus(db, USER, ["1"]) == {}


# ── upsert_order_summaries ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_summaries_parse_dates_and_update(sf):
    async with sf() as db:
        await repo.upsert_order_summaries(
            db,
            USER,
            [
                _order("u1", delivery="2026-03-16", total=42.0),
                _order("u2", delivery="1900-01-01"),  # sentinel → None
                _order("u3", delivery="not-a-date"),  # unparseable → None
            ],
        )
    async with sf() as db:
        rows = {
            r.order_id: r
            for r in (await db.execute(select(OrderCache).where(OrderCache.user_id == USER)))
            .scalars()
            .all()
        }
        assert rows["u1"].delivery_date == datetime.date(2026, 3, 16)
        assert rows["u2"].delivery_date is None
        assert rows["u3"].delivery_date is None

    # Idempotent update: same order_id, new total → updated, still one row
    async with sf() as db:
        await repo.upsert_order_summaries(db, USER, [_order("u1", total=99.0)])
    async with sf() as db:
        rows = (
            (await db.execute(select(OrderCache).where(OrderCache.order_id == "u1")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].total_price == 99.0


# ── upsert_order_items + get_cached_order_ids ─────────────────────────────────


def _line(sku):
    return OrderLineItem(
        sku=sku,
        name="Product " + sku,
        subtitle="",
        slug="",
        quantity=2,
        price=1.0,
        category="Zuivel",
        image_url="",
        available=True,
    )


async def _count_items(db, order_id):
    rows = (
        (await db.execute(select(OrderItemCache).where(OrderItemCache.order_id == order_id)))
        .scalars()
        .all()
    )
    return len(rows)


@pytest.mark.asyncio
async def test_order_items_idempotent_and_cached_ids(sf):
    async with sf() as db:
        await repo.upsert_order_summaries(db, USER, [_order("o1")])
        await repo.upsert_order_items(db, USER, "o1", [_line("1"), _line("2")])
        assert await _count_items(db, "o1") == 2
        # Re-running replaces (delete-then-insert) rather than appending.
        await repo.upsert_order_items(db, USER, "o1", [_line("1")])
        assert await _count_items(db, "o1") == 1
        assert await repo.get_cached_order_ids(db, USER) == {"o1"}


# ── get_dish_availability (batched) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_dish_availability_counts(sf):
    now = datetime.datetime.utcnow()
    async with sf() as db:
        dish = Dish(user_id=USER, name="Test", created_at=now)
        db.add(dish)
        await db.commit()
        await db.refresh(dish)
        db.add_all(
            [
                DishIngredient(
                    dish_id=dish.id, sku="A", display_name="a", amount=1, amount_unit="stuks"
                ),
                DishIngredient(
                    dish_id=dish.id, sku="B", display_name="b", amount=1, amount_unit="stuks"
                ),
                DishIngredient(
                    dish_id=dish.id, sku="C", display_name="c", amount=1, amount_unit="stuks"
                ),
                DishIngredient(
                    dish_id=dish.id,
                    sku="D",
                    display_name="d",
                    amount=1,
                    amount_unit="stuks",
                    optional=True,  # excluded from the count
                ),
            ]
        )
        db.add_all(
            [
                IngredientSku(
                    user_id=USER, sku="A", name="a", last_seen_available=True, last_checked_at=now
                ),
                IngredientSku(
                    user_id=USER, sku="B", name="b", last_seen_available=False, last_checked_at=now
                ),
                # C has no cache row → unknown
            ]
        )
        await db.commit()

        avail, unavail, unknown = await repo.get_dish_availability(db, USER, dish.id)
    assert (avail, unavail, unknown) == (1, 1, 1)
