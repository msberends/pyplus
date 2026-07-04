"""Unit tests for the product catalogue cache (upsert + search) on an in-memory DB."""

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from plus.models import Product
from pyplus.db import repo
from pyplus.db.engine import register_sqlite_functions
from pyplus.db.models import Base


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", register_sqlite_functions)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _p(sku, name, brand="", available=True, categories=None):
    return Product(
        sku=sku,
        name=name,
        subtitle="Per stuk",
        brand=brand,
        slug=f"{name.lower().replace(' ', '-')}-{sku}",
        image_url=f"https://img/{sku}.png",
        price=1.99,
        is_available=available,
        categories=categories or [],
    )


@pytest.mark.asyncio
async def test_upsert_then_search(session_factory):
    products = [
        _p("1", "Halfvolle melk", "Campina"),
        _p("2", "Volle melk", "AH"),
        _p("3", "Sinaasappelsap", "Appelsientje"),
    ]
    async with session_factory() as db:
        written = await repo.upsert_product_cache(db, 720, products)
    assert written == 3

    async with session_factory() as db:
        hits = await repo.search_product_cache(db, 720, "melk")
        assert {h.sku for h in hits} == {"1", "2"}
        # slug + image survive the round-trip (needed for clickable links + thumbnails)
        assert hits[0].slug
        assert hits[0].image_url

        # Token-AND: both words must match
        brand_hits = await repo.search_product_cache(db, 720, "melk campina")
        assert {h.sku for h in brand_hits} == {"1"}

        # Store isolation
        assert await repo.search_product_cache(db, 999, "melk") == []


@pytest.mark.asyncio
async def test_upsert_is_idempotent(session_factory):
    async with session_factory() as db:
        await repo.upsert_product_cache(db, 720, [_p("1", "Melk")])
        await repo.upsert_product_cache(db, 720, [_p("1", "Melk halfvol", available=False)])
        assert await repo.count_product_cache(db, 720) == 1
        hits = await repo.search_product_cache(db, 720, "melk")
        assert hits[0].name == "Melk halfvol"
        assert hits[0].is_available is False


@pytest.mark.asyncio
async def test_get_by_skus_flags_missing(session_factory):
    async with session_factory() as db:
        await repo.upsert_product_cache(db, 720, [_p("1", "Melk"), _p("2", "Brood")])
        found = await repo.get_product_cache_by_skus(db, 720, ["1", "2", "999"])
        assert set(found) == {"1", "2"}  # 999 is not carried → absent
        assert await repo.get_product_cache_by_skus(db, 720, []) == {}


@pytest.mark.asyncio
async def test_categories_breadcrumb_round_trip(session_factory):
    from pyplus.services.search import _row_to_product

    path = ["Verse kant-en-klaarmaaltijden", "Italiaanse maaltijden", "Lasagne"]
    async with session_factory() as db:
        await repo.upsert_product_cache(db, 720, [_p("1", "Verse lasagne", categories=path)])
        hits = await repo.search_product_cache(db, 720, "lasagne")
    # The full multi-layer path is preserved in order, broad → specific.
    assert _row_to_product(hits[0], 720).categories == path


@pytest.mark.asyncio
async def test_available_sorts_first(session_factory):
    async with session_factory() as db:
        await repo.upsert_product_cache(
            db,
            720,
            [_p("1", "Appel rood", available=False), _p("2", "Appel groen", available=True)],
        )
        hits = await repo.search_product_cache(db, 720, "appel")
    assert hits[0].sku == "2"  # available first


@pytest.mark.asyncio
async def test_search_matches_substring_in_compound_word(session_factory):
    # Dutch compound words: "kaas" must match inside "Pindakaas".
    async with session_factory() as db:
        await repo.upsert_product_cache(db, 720, [_p("1", "Pindakaas naturel")])
        hits = await repo.search_product_cache(db, 720, "kaas")
    assert {h.sku for h in hits} == {"1"}


@pytest.mark.asyncio
async def test_search_short_token(session_factory):
    # Short tokens (< 3 chars) work the same as longer ones — no length gate.
    async with session_factory() as db:
        await repo.upsert_product_cache(db, 720, [_p("1", "Eieren")])
        hits = await repo.search_product_cache(db, 720, "ei")
    assert {h.sku for h in hits} == {"1"}


@pytest.mark.asyncio
async def test_search_reflects_name_update(session_factory):
    # Upsert updates product_cache; search immediately reflects the new name.
    async with session_factory() as db:
        await repo.upsert_product_cache(db, 720, [_p("1", "Halfvolle melk")])
        await repo.upsert_product_cache(db, 720, [_p("1", "Volle yoghurt")])
        assert {h.sku for h in await repo.search_product_cache(db, 720, "yoghurt")} == {"1"}
        assert await repo.search_product_cache(db, 720, "halfvolle") == []
