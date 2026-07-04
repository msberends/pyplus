"""Unit tests for the promo index — single-product deals + group-deal children."""

import dataclasses

import pytest

from plus.models import Promotion, PromotionProduct
from pyplus.services import promos


def _promo(slug, *, sku="", single=False, free=False, label="1+1 GRATIS") -> Promotion:
    return Promotion(
        category_id="c1",
        category_label="Kant-en-klaar",
        slug=slug,
        brand="PLUS",
        name="Bapao" if not single else "Losse bapao",
        subtitle="",
        variant="",
        label=label,
        price_new=1.0,
        price_was=2.0,
        start_date="2026-06-01",
        end_date="2026-06-07",
        sku=sku,
        image_url="",
        is_free_delivery=free,
        is_single_product=single,
    )


def _child(sku, name) -> PromotionProduct:
    return PromotionProduct(
        sku=sku,
        brand="PLUS",
        name=name,
        subtitle="Per stuk",
        slug=f"{name.lower().replace(' ', '-')}-{sku}",
        image_url="",
        price_original=2.0,
        price_new=0.0,
        label="1+1 GRATIS",
        is_available=True,
        max_order_limit=0,
    )


def _payload(promos_list, children):
    """Build a cached payload exactly as refresh_promotions does (asdict round-trip)."""
    return {
        "period_from": "2026-06-01",
        "period_to": "2026-06-07",
        "is_next_week_published": False,
        "promotions": [dataclasses.asdict(p) for p in promos_list],
        "children": {
            slug: [dataclasses.asdict(c) for c in kids] for slug, kids in children.items()
        },
    }


@pytest.mark.asyncio
async def test_index_maps_group_children_to_parent(monkeypatch):
    group = _promo("4431-96", single=False)  # "Bapao" group deal
    payload = _payload(
        [group], {"4431-96": [_child("111", "Bapao kip"), _child("222", "Bapao groente")]}
    )

    async def _fake_load(store, week):
        return payload

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    index = await promos.get_promo_index(720)

    # Each child SKU resolves to its parent group deal (so the cart hint lights up).
    assert set(index) == {"111", "222"}
    assert index["111"] is index["222"]
    assert index["111"].slug == "4431-96"
    assert promos.promo_tag_label(index["111"]) == "1+1 GRATIS"


@pytest.mark.asyncio
async def test_single_product_deal_overrides_child(monkeypatch):
    # A SKU that is both a group child and its own single-product deal: the
    # single-product entry (more specific) must win.
    group = _promo("grp", single=False, label="2+1 GRATIS")
    single = _promo("single-slug", sku="111", single=True, label="50% KORTING")
    payload = _payload([group, single], {"grp": [_child("111", "Bapao kip")]})

    async def _fake_load(store, week):
        return payload

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    index = await promos.get_promo_index(720)

    assert index["111"].is_single_product
    assert promos.promo_tag_label(index["111"]) == "50% KORTING"


@pytest.mark.asyncio
async def test_free_delivery_children_included(monkeypatch):
    free = _promo("free", single=False, free=True)
    payload = _payload([free], {"free": [_child("111", "Iets")]})

    async def _fake_load(store, week):
        return payload

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    index = await promos.get_promo_index(720)
    assert set(index) == {"111"}
    assert index["111"].is_free_delivery
    assert promos.promo_tag_label(index["111"]) == "Gratis bezorging"


@pytest.mark.asyncio
async def test_regular_promo_overrides_free_delivery(monkeypatch):
    free = _promo("free-grp", single=False, free=True)
    regular = _promo("regular-grp", single=False, label="2+1 GRATIS")
    payload = _payload(
        [free, regular],
        {
            "free-grp": [_child("111", "Chips A")],
            "regular-grp": [_child("111", "Chips A")],
        },
    )

    async def _fake_load(store, week):
        return payload

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    index = await promos.get_promo_index(720)
    assert not index["111"].is_free_delivery
    assert promos.promo_tag_label(index["111"]) == "2+1 GRATIS"


@pytest.mark.asyncio
async def test_children_reader_round_trips(monkeypatch):
    group = _promo("grp", single=False)
    payload = _payload([group], {"grp": [_child("111", "Bapao kip")]})

    async def _fake_load(store, week):
        return payload

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    children = await promos.get_promo_children(720)
    assert [c.sku for c in children["grp"]] == ["111"]
    assert children["grp"][0].name == "Bapao kip"


@pytest.mark.asyncio
async def test_cold_cache_returns_empty(monkeypatch):
    async def _fake_load(store, week):
        return None

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    assert await promos.get_promo_index(720) == {}
    assert await promos.get_promo_children(720) == {}


@pytest.mark.asyncio
async def test_legacy_payload_without_children(monkeypatch):
    # Payloads cached before child support lack the "children" key entirely.
    single = _promo("s", sku="999", single=True)
    payload = {
        "period_from": "",
        "period_to": "",
        "is_next_week_published": False,
        "promotions": [dataclasses.asdict(single)],
    }

    async def _fake_load(store, week):
        return payload

    monkeypatch.setattr(promos, "_load_payload", _fake_load)
    index = await promos.get_promo_index(720)
    assert set(index) == {"999"}
