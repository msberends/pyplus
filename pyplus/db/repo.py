"""Data-access helpers — all writes are user-scoped."""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyplus.db.models import (
    AutopilotPlan,
    Credentials,
    Dish,
    DishIngredient,
    FixedProduct,
    IngredientSku,
    MlArtifact,
    OrderCache,
    OrderItemCache,
    ProductCache,
    PromotionsCache,
    PurchasedProductCache,
    SyncState,
    User,
    WeatherCache,
    Weekmenu,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


# ── Users ──────────────────────────────────────────────────────────────────────


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_onewelcome_id(db: AsyncSession, onewelcome_id: str) -> User | None:
    result = await db.execute(select(User).where(User.one_welcome_user_id == onewelcome_id))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    plus_email_enc: str,
    onewelcome_user_id: str,
    display_name: str = "",
    store_number: int | None = None,
    store_name: str = "",
    user_store_id: str = "",
) -> User:
    user = User(
        plus_email_enc=plus_email_enc,
        one_welcome_user_id=onewelcome_user_id,
        display_name=display_name,
        store_number=store_number,
        store_name=store_name,
        user_store_id=user_store_id,
        created_at=_utcnow(),
        last_login_at=_utcnow(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("Created user id=%d", user.id)
    return user


async def update_user_login(
    db: AsyncSession,
    user_id: int,
    *,
    store_number: int | None = None,
    store_name: str = "",
    user_store_id: str = "",
    display_name: str = "",
) -> None:
    user = await get_user_by_id(db, user_id)
    if not user:
        return
    user.last_login_at = _utcnow()
    if store_number is not None:
        user.store_number = store_number
    if store_name:
        user.store_name = store_name
    if user_store_id:
        user.user_store_id = user_store_id
    if display_name:
        user.display_name = display_name
    await db.commit()


async def update_user_store(db: AsyncSession, user_id: int, store_number: int) -> None:
    user = await get_user_by_id(db, user_id)
    if user:
        user.store_number = store_number
        await db.commit()


async def set_user_display_name(db: AsyncSession, user_id: int, display_name: str) -> None:
    """Set the user-chosen display name used for the greeting."""
    user = await get_user_by_id(db, user_id)
    if user:
        user.display_name = display_name.strip()
        await db.commit()


# ── Credentials ────────────────────────────────────────────────────────────────


async def get_credentials(db: AsyncSession, user_id: int) -> Credentials | None:
    result = await db.execute(select(Credentials).where(Credentials.user_id == user_id))
    return result.scalar_one_or_none()


async def upsert_credentials(db: AsyncSession, user_id: int, password_enc: str) -> None:
    creds = await get_credentials(db, user_id)
    if creds:
        creds.password_enc = password_enc
    else:
        db.add(Credentials(user_id=user_id, password_enc=password_enc, remember=True))
    await db.commit()


async def delete_credentials(db: AsyncSession, user_id: int) -> None:
    creds = await get_credentials(db, user_id)
    if creds:
        await db.delete(creds)
        await db.commit()


# ── Dishes ─────────────────────────────────────────────────────────────────────


async def get_dishes(db: AsyncSession, user_id: int, include_archived: bool = False) -> list[Dish]:
    q = select(Dish).where(Dish.user_id == user_id)
    if not include_archived:
        q = q.where(Dish.archived == False)  # noqa: E712
    q = q.order_by(Dish.name)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_dish_group_names(db: AsyncSession, user_id: int) -> list[str]:
    result = await db.execute(
        select(Dish.group_name)
        .where(Dish.user_id == user_id, Dish.group_name.isnot(None), Dish.archived == False)  # noqa: E712
        .distinct()
        .order_by(Dish.group_name)
    )
    return [row[0] for row in result.all()]


async def get_dish(db: AsyncSession, user_id: int, dish_id: int) -> Dish | None:
    result = await db.execute(select(Dish).where(Dish.id == dish_id, Dish.user_id == user_id))
    return result.scalar_one_or_none()


async def create_dish(
    db: AsyncSession,
    user_id: int,
    *,
    name: str,
    prep_notes: str = "",
    prep_minutes: int | None = None,
    meat_type: str | None = None,
    starch_type: str | None = None,
    cooking_methods: str = "[]",
    is_cold: bool = False,
    is_unhealthy: bool = False,
    is_dinner: bool = True,
    rating: float | None = None,
    veg_count: int | None = None,
    group_name: str | None = None,
    cooldown_weeks: int | None = None,
) -> Dish:
    dish = Dish(
        user_id=user_id,
        name=name,
        prep_notes=prep_notes,
        prep_minutes=prep_minutes,
        meat_type=meat_type,
        starch_type=starch_type,
        cooking_methods=cooking_methods,
        is_cold=is_cold,
        is_unhealthy=is_unhealthy,
        is_dinner=is_dinner,
        rating=rating,
        veg_count=veg_count,
        group_name=group_name or name,
        cooldown_weeks=cooldown_weeks,
        created_at=_utcnow(),
    )
    db.add(dish)
    await db.commit()
    await db.refresh(dish)
    return dish


async def update_dish(db: AsyncSession, user_id: int, dish_id: int, **kwargs) -> Dish | None:
    dish = await get_dish(db, user_id, dish_id)
    if not dish:
        return None
    for k, v in kwargs.items():
        if hasattr(dish, k):
            setattr(dish, k, v)
    await db.commit()
    await db.refresh(dish)
    return dish


async def archive_dish(db: AsyncSession, user_id: int, dish_id: int, archived: bool = True) -> None:
    await update_dish(db, user_id, dish_id, archived=archived)


async def duplicate_dish(db: AsyncSession, user_id: int, dish_id: int) -> Dish | None:
    src = await get_dish(db, user_id, dish_id)
    if not src:
        return None
    ingredients = await get_ingredients(db, dish_id)
    new_dish = await create_dish(
        db,
        user_id,
        name=src.name + " (kopie)",
        prep_notes=src.prep_notes,
        prep_minutes=src.prep_minutes,
        meat_type=src.meat_type,
        starch_type=src.starch_type,
        cooking_methods=src.cooking_methods,
        is_cold=src.is_cold,
        is_unhealthy=src.is_unhealthy,
        veg_count=src.veg_count,
        group_name=src.group_name,
        cooldown_weeks=src.cooldown_weeks,
    )
    for ing in ingredients:
        db.add(
            DishIngredient(
                dish_id=new_dish.id,
                sku=ing.sku,
                display_name=ing.display_name,
                amount=ing.amount,
                amount_unit=ing.amount_unit,
                pack_size=ing.pack_size,
                pack_unit=ing.pack_unit,
                optional=ing.optional,
                flexible=ing.flexible,
                sort_order=ing.sort_order,
            )
        )
    await db.commit()
    return new_dish


# ── Dish ingredients ───────────────────────────────────────────────────────────


async def get_ingredients(db: AsyncSession, dish_id: int) -> list[DishIngredient]:
    result = await db.execute(
        select(DishIngredient)
        .where(DishIngredient.dish_id == dish_id)
        .order_by(DishIngredient.sort_order, DishIngredient.id)
    )
    return list(result.scalars().all())


async def add_ingredient(
    db: AsyncSession,
    dish_id: int,
    *,
    sku: str,
    display_name: str,
    amount: float = 1.0,
    amount_unit: str = "stuks",
    pack_size: float | None = None,
    pack_unit: str | None = None,
    optional: bool = False,
    flexible: bool = False,
    sort_order: int = 0,
) -> DishIngredient:
    ing = DishIngredient(
        dish_id=dish_id,
        sku=sku,
        display_name=display_name,
        amount=amount,
        amount_unit=amount_unit,
        pack_size=pack_size,
        pack_unit=pack_unit,
        optional=optional,
        flexible=flexible,
        sort_order=sort_order,
    )
    db.add(ing)
    await db.commit()
    await db.refresh(ing)
    return ing


async def update_ingredient(
    db: AsyncSession, ingredient_id: int, **kwargs
) -> DishIngredient | None:
    result = await db.execute(select(DishIngredient).where(DishIngredient.id == ingredient_id))
    ing = result.scalar_one_or_none()
    if not ing:
        return None
    for k, v in kwargs.items():
        if hasattr(ing, k):
            setattr(ing, k, v)
    await db.commit()
    await db.refresh(ing)
    return ing


async def delete_ingredient(db: AsyncSession, ingredient_id: int) -> None:
    result = await db.execute(select(DishIngredient).where(DishIngredient.id == ingredient_id))
    ing = result.scalar_one_or_none()
    if ing:
        await db.delete(ing)
        await db.commit()


async def reorder_ingredients(db: AsyncSession, dish_id: int, ordered_ids: list[int]) -> None:
    """Update sort_order for each ingredient id in the given order."""
    for i, ing_id in enumerate(ordered_ids):
        result = await db.execute(
            select(DishIngredient).where(
                DishIngredient.id == ing_id, DishIngredient.dish_id == dish_id
            )
        )
        ing = result.scalar_one_or_none()
        if ing:
            ing.sort_order = i
    await db.commit()


async def relink_ingredient_sku(db: AsyncSession, user_id: int, old_sku: str, new_sku: str) -> int:
    """Replace old_sku with new_sku in all of a user's DishIngredient rows.

    Returns the number of ingredients updated.
    """
    dishes = await db.execute(select(Dish.id).where(Dish.user_id == user_id))
    dish_ids = [r[0] for r in dishes.all()]
    if not dish_ids:
        return 0
    result = await db.execute(
        select(DishIngredient).where(
            DishIngredient.dish_id.in_(dish_ids),
            DishIngredient.sku == old_sku,
        )
    )
    count = 0
    for ing in result.scalars().all():
        ing.sku = new_sku
        count += 1
    if count:
        await db.commit()
    return count


# ── IngredientSku cache ────────────────────────────────────────────────────────


async def get_ingredient_sku(db: AsyncSession, user_id: int, sku: str) -> IngredientSku | None:
    result = await db.execute(
        select(IngredientSku).where(IngredientSku.user_id == user_id, IngredientSku.sku == sku)
    )
    return result.scalar_one_or_none()


async def upsert_ingredient_sku(
    db: AsyncSession,
    user_id: int,
    sku: str,
    *,
    name: str,
    subtitle: str = "",
    slug: str = "",
    image_url: str = "",
    pack_size: float | None = None,
    pack_unit: str | None = None,
    last_price: float | None = None,
    last_seen_available: bool | None = None,
) -> IngredientSku:
    row = await get_ingredient_sku(db, user_id, sku)
    now = _utcnow()
    if row:
        row.name = name
        row.subtitle = subtitle
        if slug:
            row.slug = slug
        row.image_url = image_url
        if pack_size is not None:
            row.pack_size = pack_size
        if pack_unit is not None:
            row.pack_unit = pack_unit
        if last_price is not None:
            row.last_price = last_price
        if last_seen_available is not None:
            row.last_seen_available = last_seen_available
        row.last_checked_at = now
    else:
        row = IngredientSku(
            user_id=user_id,
            sku=sku,
            name=name,
            subtitle=subtitle,
            slug=slug,
            image_url=image_url,
            pack_size=pack_size,
            pack_unit=pack_unit,
            last_price=last_price,
            last_seen_available=last_seen_available,
            last_checked_at=now,
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ── Weekmenu ───────────────────────────────────────────────────────────────────

# ── Fixed products (staples) ───────────────────────────────────────────────────


async def get_fixed_products(db: AsyncSession, user_id: int) -> list[FixedProduct]:
    result = await db.execute(
        select(FixedProduct)
        .where(FixedProduct.user_id == user_id)
        .order_by(FixedProduct.sort_order, FixedProduct.display_name)
    )
    return list(result.scalars().all())


async def add_fixed_product(
    db: AsyncSession,
    user_id: int,
    sku: str,
    display_name: str,
    default_qty: int = 1,
    every_n_weeks: int = 1,
) -> FixedProduct | None:
    """Add a staple product. No-op (returns existing) if the sku is already a staple."""
    if not sku:
        return None
    existing = await db.execute(
        select(FixedProduct).where(FixedProduct.user_id == user_id, FixedProduct.sku == sku)
    )
    row = existing.scalar_one_or_none()
    if row:
        return row
    # Append at the end.
    current = await get_fixed_products(db, user_id)
    fp = FixedProduct(
        user_id=user_id,
        sku=sku,
        display_name=display_name,
        default_qty=default_qty,
        every_n_weeks=every_n_weeks,
        sort_order=len(current),
    )
    db.add(fp)
    await db.commit()
    await db.refresh(fp)
    return fp


async def update_fixed_product(db: AsyncSession, user_id: int, sku: str, **kwargs: object) -> None:
    result = await db.execute(
        select(FixedProduct).where(FixedProduct.user_id == user_id, FixedProduct.sku == sku)
    )
    row = result.scalar_one_or_none()
    if row:
        for k, v in kwargs.items():
            setattr(row, k, v)
        await db.commit()


async def stamp_fixed_products_added(
    db: AsyncSession,
    user_id: int,
    skus: list[str],
    date: datetime.date | None = None,
) -> None:
    if not skus:
        return
    stamp = date or datetime.date.today()
    result = await db.execute(
        select(FixedProduct).where(FixedProduct.user_id == user_id, FixedProduct.sku.in_(skus))
    )
    for fp in result.scalars().all():
        fp.last_added_at = stamp
    await db.commit()


async def replace_fixed_product_sku(
    db: AsyncSession, user_id: int, old_sku: str, new_sku: str, new_name: str
) -> None:
    result = await db.execute(
        select(FixedProduct).where(FixedProduct.user_id == user_id, FixedProduct.sku == old_sku)
    )
    row = result.scalar_one_or_none()
    if row:
        row.sku = new_sku
        row.display_name = new_name
        await db.commit()


async def remove_fixed_product(db: AsyncSession, user_id: int, sku: str) -> None:
    result = await db.execute(
        select(FixedProduct).where(FixedProduct.user_id == user_id, FixedProduct.sku == sku)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()


async def get_ingredient_skus_by_skus(
    db: AsyncSession, user_id: int, skus: list[str]
) -> dict[str, IngredientSku]:
    """Batch-load IngredientSku cache rows for the given SKUs. Returns sku → row dict."""
    if not skus:
        return {}
    result = await db.execute(
        select(IngredientSku).where(
            IngredientSku.user_id == user_id,
            IngredientSku.sku.in_(skus),
        )
    )
    return {row.sku: row for row in result.scalars().all()}


async def get_all_ingredient_prices(db: AsyncSession, user_id: int) -> dict[str, float]:
    """Return {sku: last_price} for all cached ingredient SKUs with a known price."""
    result = await db.execute(
        select(IngredientSku.sku, IngredientSku.last_price).where(
            IngredientSku.user_id == user_id,
            IngredientSku.last_price.is_not(None),
        )
    )
    return {row.sku: row.last_price for row in result.all()}


async def get_weekmenu(db: AsyncSession, user_id: int, week_start: datetime.date) -> list[Weekmenu]:
    """All slot rows for a user + week, with dish eagerly loaded."""
    result = await db.execute(
        select(Weekmenu)
        .where(Weekmenu.user_id == user_id, Weekmenu.week_start == week_start)
        .options(selectinload(Weekmenu.dish))
    )
    return list(result.scalars().all())


async def set_weekmenu_slot(
    db: AsyncSession,
    user_id: int,
    slot: str,
    week_start: datetime.date,
    dish_id: int | None,
) -> None:
    """Upsert a weekmenu slot. Passing dish_id=None deletes the row (empty slot)."""
    result = await db.execute(
        select(Weekmenu).where(
            Weekmenu.user_id == user_id,
            Weekmenu.slot == slot,
            Weekmenu.week_start == week_start,
        )
    )
    row = result.scalar_one_or_none()
    if dish_id is None:
        if row:
            await db.delete(row)
    elif row:
        row.dish_id = dish_id
    else:
        db.add(
            Weekmenu(
                user_id=user_id,
                slot=slot,
                week_start=week_start,
                dish_id=dish_id,
            )
        )
    await db.commit()


# ── SyncState ──────────────────────────────────────────────────────────────────


async def get_sync_state(db: AsyncSession, user_id: int, resource: str) -> SyncState | None:
    result = await db.execute(
        select(SyncState).where(SyncState.user_id == user_id, SyncState.resource == resource)
    )
    return result.scalar_one_or_none()


async def get_all_sync_states(db: AsyncSession, user_id: int) -> dict[str, SyncState]:
    """Return every sync_state row for a user, keyed by resource name."""
    result = await db.execute(select(SyncState).where(SyncState.user_id == user_id))
    return {row.resource: row for row in result.scalars().all()}


async def upsert_sync_state(
    db: AsyncSession,
    user_id: int,
    resource: str,
    status: str,
    detail: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    row = await get_sync_state(db, user_id, resource)
    now = _utcnow()
    if row:
        row.last_status = status
        row.last_synced_at = now
        if detail is not None:
            row.detail_json = detail
        if duration_seconds is not None:
            row.last_duration_seconds = duration_seconds
    else:
        db.add(
            SyncState(
                user_id=user_id,
                resource=resource,
                last_status=status,
                last_synced_at=now,
                detail_json=detail,
                last_duration_seconds=duration_seconds,
            )
        )
    await db.commit()


# ── ProductCache (store-scoped catalogue) ──────────────────────────────────────


async def count_product_cache(db: AsyncSession, store_number: int) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ProductCache)
        .where(ProductCache.store_number == store_number)
    )
    return int(result.scalar_one())


async def get_product_cache_by_skus(
    db: AsyncSession, store_number: int, skus: list[str]
) -> dict[str, ProductCache]:
    """Look up catalogue rows for specific SKUs at a store, keyed by SKU.

    A SKU absent from the result is not carried by that store's catalogue
    (discontinued / not stocked) — used to flag staples and dish ingredients.
    """
    skus = [s for s in skus if s]
    if not skus:
        return {}
    result = await db.execute(
        select(ProductCache).where(
            ProductCache.store_number == store_number, ProductCache.sku.in_(skus)
        )
    )
    return {row.sku: row for row in result.scalars().all()}


async def get_pack_alternatives(
    db: AsyncSession, store_number: int, skus: list[str]
) -> dict[str, list[ProductCache]]:
    """For each cart SKU, return the catalogue products sharing its (brand, name).

    These are the same product in different pack sizes — the candidate set for a
    cheaper-per-unit swap. Maps sku → [ProductCache, …] (includes the sku itself).
    """
    base = await get_product_cache_by_skus(db, store_number, skus)
    if not base:
        return {}
    names = {row.name for row in base.values()}
    result = await db.execute(
        select(ProductCache).where(
            ProductCache.store_number == store_number,
            ProductCache.name.in_(names),
            ProductCache.is_available == True,  # noqa: E712
        )
    )
    groups: dict[tuple[str, str], list[ProductCache]] = {}
    for row in result.scalars().all():
        groups.setdefault((row.brand, row.name), []).append(row)
    return {sku: groups.get((r.brand, r.name), [r]) for sku, r in base.items()}


async def search_product_cache(
    db: AsyncSession, store_number: int, query: str, limit: int = 24
) -> list[ProductCache]:
    """Per-word substring search over the cached catalogue for one store.

    Each whitespace-separated token must appear as a substring anywhere in the
    combined name+brand string (case-insensitive, any order). Available products
    sort first, then by name.
    """
    import re as _re

    tokens = [tok for tok in query.split() if tok]
    if not tokens:
        return []
    pattern = "(?i)" + "".join(f"(?=.*{_re.escape(tok)})" for tok in tokens)
    stmt = select(ProductCache).from_statement(
        text(
            "SELECT pc.* FROM product_cache pc "
            "WHERE pc.store_number = :store "
            "AND (pc.name || ' ' || COALESCE(pc.brand, '')) REGEXP :pat "
            "ORDER BY pc.is_available DESC, pc.name "
            "LIMIT :limit"
        )
    )
    result = await db.execute(stmt, {"store": store_number, "pat": pattern, "limit": limit})
    return list(result.scalars().all())


async def upsert_product_cache(db: AsyncSession, store_number: int, products: list) -> int:
    """Bulk upsert catalogue products (plus.models.Product) for a store.

    Uses SQLite's ON CONFLICT to update existing (sku, store_number) rows in one
    statement per chunk. Returns the number of products written.
    """
    import json as _json

    now = _utcnow()
    rows = [
        {
            "sku": p.sku,
            "store_number": store_number,
            "name": p.name,
            "subtitle": getattr(p, "subtitle", "") or "",
            "brand": getattr(p, "brand", "") or "",
            "slug": getattr(p, "slug", "") or "",
            "image_url": getattr(p, "image_url", "") or "",
            "price": getattr(p, "price", 0.0) or 0.0,
            "is_available": getattr(p, "is_available", False),
            "categories_json": _json.dumps(getattr(p, "categories", None) or []),
            "fetched_at": now,
        }
        for p in products
        if p.sku
    ]
    if not rows:
        return 0
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start + 500]
        stmt = sqlite_insert(ProductCache).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sku", "store_number"],
            set_={
                "name": stmt.excluded.name,
                "subtitle": stmt.excluded.subtitle,
                "brand": stmt.excluded.brand,
                "slug": stmt.excluded.slug,
                "image_url": stmt.excluded.image_url,
                "price": stmt.excluded.price,
                "is_available": stmt.excluded.is_available,
                "categories_json": stmt.excluded.categories_json,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await db.execute(stmt)
    await db.commit()
    return len(rows)


# ── PromotionsCache ────────────────────────────────────────────────────────────


async def get_promotions_cache(
    db: AsyncSession,
    store_number: int,
    week_start: datetime.date,
    is_next_week: bool = False,
) -> PromotionsCache | None:
    result = await db.execute(
        select(PromotionsCache).where(
            PromotionsCache.store_number == store_number,
            PromotionsCache.week_start == week_start,
            PromotionsCache.is_next_week == is_next_week,
        )
    )
    return result.scalar_one_or_none()


async def upsert_promotions_cache(
    db: AsyncSession,
    store_number: int,
    week_start: datetime.date,
    is_next_week: bool,
    payload_json: str,
) -> None:
    row = await get_promotions_cache(db, store_number, week_start, is_next_week)
    now = _utcnow()
    if row:
        row.payload_json = payload_json
        row.fetched_at = now
    else:
        db.add(
            PromotionsCache(
                store_number=store_number,
                week_start=week_start,
                is_next_week=is_next_week,
                payload_json=payload_json,
                fetched_at=now,
            )
        )
    await db.commit()


# ── Users with credentials ─────────────────────────────────────────────────────


async def get_users_with_credentials(db: AsyncSession) -> list[User]:
    """Return users that have stored (remember-me) credentials — eligible for background jobs."""
    result = await db.execute(select(User).join(Credentials, Credentials.user_id == User.id))
    return list(result.scalars().all())


# ── Purchase history cache ─────────────────────────────────────────────────────


async def upsert_purchased_products(
    db: AsyncSession,
    user_id: int,
    products: list,  # list[plus.models.PurchasedProduct]
) -> None:
    """Bulk upsert purchase-history rows via ON CONFLICT (one statement per chunk)."""
    import json as _json

    now = _utcnow()
    rows = [
        {
            "user_id": user_id,
            "sku": p.sku,
            "name": p.name,
            "brand": getattr(p, "brand", "") or "",
            "subtitle": getattr(p, "subtitle", "") or "",
            "slug": getattr(p, "slug", "") or "",
            "image_url": getattr(p, "image_url", "") or "",
            "price": getattr(p, "price", 0.0) or 0.0,
            "is_available": getattr(p, "is_available", False),
            "categories_json": _json.dumps(getattr(p, "categories", None) or []),
            "fetched_at": now,
        }
        for p in products
        if p.sku
    ]
    if not rows:
        return
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start + 500]
        stmt = sqlite_insert(PurchasedProductCache).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "sku"],
            set_={
                "name": stmt.excluded.name,
                "brand": stmt.excluded.brand,
                "subtitle": stmt.excluded.subtitle,
                "slug": stmt.excluded.slug,
                "image_url": stmt.excluded.image_url,
                "price": stmt.excluded.price,
                "is_available": stmt.excluded.is_available,
                "categories_json": stmt.excluded.categories_json,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await db.execute(stmt)
    await db.commit()


async def get_purchased_products_by_skus(
    db: AsyncSession, user_id: int, skus: list[str]
) -> dict[str, PurchasedProductCache]:
    """Return {sku: PurchasedProductCache} for the given SKUs (purchase history)."""
    if not skus:
        return {}
    result = await db.execute(
        select(PurchasedProductCache).where(
            PurchasedProductCache.user_id == user_id,
            PurchasedProductCache.sku.in_(skus),
        )
    )
    return {row.sku: row for row in result.scalars().all()}


# ── Order history cache ────────────────────────────────────────────────────────


async def get_cached_order_ids(db: AsyncSession, user_id: int) -> set[str]:
    """Return order IDs that already have line items cached."""
    result = await db.execute(
        select(OrderItemCache.order_id).where(OrderItemCache.user_id == user_id).distinct()
    )
    return set(result.scalars().all())


async def upsert_order_summaries(db: AsyncSession, user_id: int, orders: list) -> None:
    """Store/update OrderSummary rows (no line items) — bulk ON CONFLICT upsert."""
    now = _utcnow()

    def _delivery(o) -> datetime.date | None:
        if o.delivery_date and o.delivery_date != "1900-01-01":
            try:
                return datetime.date.fromisoformat(o.delivery_date)
            except ValueError:
                return None
        return None

    rows = [
        {
            "user_id": user_id,
            "order_id": o.order_id,
            "order_number": o.order_number,
            "delivery_date": _delivery(o),
            "total_price": o.total_price,
            "status": o.status,
            "channel": o.channel,
            "is_active": o.is_active,
            "fetched_at": now,
        }
        for o in orders
        if o.order_id
    ]
    if not rows:
        return
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start + 500]
        stmt = sqlite_insert(OrderCache).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "order_id"],
            set_={
                "order_number": stmt.excluded.order_number,
                "delivery_date": stmt.excluded.delivery_date,
                "total_price": stmt.excluded.total_price,
                "status": stmt.excluded.status,
                "channel": stmt.excluded.channel,
                "is_active": stmt.excluded.is_active,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await db.execute(stmt)
    await db.commit()


async def upsert_order_items(db: AsyncSession, user_id: int, order_id: str, items: list) -> None:
    """Store line items for one order (idempotent — deletes existing items first)."""
    await db.execute(
        delete(OrderItemCache).where(
            OrderItemCache.user_id == user_id,
            OrderItemCache.order_id == order_id,
        )
    )
    for item in items:
        db.add(
            OrderItemCache(
                user_id=user_id,
                order_id=order_id,
                sku=item.sku,
                name=item.name,
                subtitle=item.subtitle,
                slug=item.slug,
                quantity=item.quantity,
                price=item.price,
                category=item.category,
                available=item.available,
            )
        )
    await db.commit()


# ── ML artifacts ──────────────────────────────────────────────────────────────


async def get_ml_artifact(db: AsyncSession, user_id: int, kind: str) -> MlArtifact | None:
    result = await db.execute(
        select(MlArtifact).where(MlArtifact.user_id == user_id, MlArtifact.kind == kind)
    )
    return result.scalar_one_or_none()


async def upsert_ml_artifact(
    db: AsyncSession, user_id: int, kind: str, blob: bytes, input_hash: str = ""
) -> None:
    row = await get_ml_artifact(db, user_id, kind)
    now = _utcnow()
    if row:
        row.blob = blob
        row.input_hash = input_hash
        row.trained_at = now
    else:
        db.add(
            MlArtifact(
                user_id=user_id,
                kind=kind,
                blob=blob,
                input_hash=input_hash,
                trained_at=now,
            )
        )
    await db.commit()


# ── User settings ──────────────────────────────────────────────────────────────


async def get_user_settings_json(db: AsyncSession, user_id: int) -> str:
    user = await get_user_by_id(db, user_id)
    return user.settings_json if user else "{}"


async def save_user_settings_json(db: AsyncSession, user_id: int, settings_json: str) -> None:
    user = await get_user_by_id(db, user_id)
    if user:
        user.settings_json = settings_json
        await db.commit()


# ── Weekmenu history (for recommender) ────────────────────────────────────────


async def get_weekmenu_history(
    db: AsyncSession, user_id: int, limit_weeks: int = 26
) -> list[Weekmenu]:
    """Past weekmenu entries (up to limit_weeks ago) with dish loaded."""
    cutoff = datetime.date.today() - datetime.timedelta(weeks=limit_weeks)
    result = await db.execute(
        select(Weekmenu)
        .where(Weekmenu.user_id == user_id, Weekmenu.week_start >= cutoff)
        .options(selectinload(Weekmenu.dish))
        .order_by(Weekmenu.week_start.desc())
    )
    return list(result.scalars().all())


async def get_all_dish_ingredients_for_user(
    db: AsyncSession, user_id: int, *, include_archived: bool = False
) -> dict[int, list[DishIngredient]]:
    """Single query: all ingredients for a user's dishes. Returns dish_id → list."""
    stmt = (
        select(DishIngredient)
        .join(Dish, Dish.id == DishIngredient.dish_id)
        .where(Dish.user_id == user_id)
        .order_by(DishIngredient.dish_id, DishIngredient.sort_order)
    )
    if not include_archived:
        stmt = stmt.where(Dish.archived == False)  # noqa: E712
    result = await db.execute(stmt)
    by_dish: dict[int, list[DishIngredient]] = {}
    for ing in result.scalars().all():
        by_dish.setdefault(ing.dish_id, []).append(ing)
    return by_dish


async def get_dish_discontinued_skus(
    db: AsyncSession, store_number: int, dish_id: int
) -> list[str]:
    """Non-optional ingredient SKUs missing or unavailable in the store catalogue.

    Returns [] when the catalogue hasn't been synced yet for this store (so we
    never flag dishes as broken just because the cache is cold).
    """
    if not store_number:
        return []
    if await count_product_cache(db, store_number) == 0:
        return []
    ingredients = await get_ingredients(db, dish_id)
    skus = [ing.sku for ing in ingredients if ing.sku and not ing.optional]
    present = await get_product_cache_by_skus(db, store_number, skus)
    return [s for s in skus if s not in present or not present[s].is_available]


async def get_dish_availability(
    db: AsyncSession, user_id: int, dish_id: int
) -> tuple[int, int, int]:
    """Return (available, unavailable, unknown) counts across all non-optional ingredients."""
    ingredients = [ing for ing in await get_ingredients(db, dish_id) if not ing.optional]
    # Single batched lookup instead of one query per ingredient.
    cached = await get_ingredient_skus_by_skus(
        db, user_id, [ing.sku for ing in ingredients if ing.sku]
    )
    available = unavailable = unknown = 0
    for ing in ingredients:
        row = cached.get(ing.sku)
        if row is None or row.last_seen_available is None:
            unknown += 1
        elif row.last_seen_available:
            available += 1
        else:
            unavailable += 1
    return available, unavailable, unknown


# ── Substitute product search ─────────────────────────────────────────────────


async def find_category_matches(
    db: AsyncSession,
    store_number: int,
    categories: list[str],
    exclude_skus: set[str] | None = None,
    limit: int = 40,
) -> list[ProductCache]:
    """Find available products sharing a category with the target product.

    Tries the deepest (most specific) category first, broadening to parent
    categories until at least ``limit`` candidates are collected or categories
    are exhausted.
    """
    if not store_number or not categories:
        return []
    exclude_skus = exclude_skus or set()
    seen: set[str] = set()
    results: list[ProductCache] = []
    for cat in reversed(categories):
        pat = f'%"{cat}"%'
        stmt = (
            select(ProductCache)
            .where(
                ProductCache.store_number == store_number,
                ProductCache.is_available == True,  # noqa: E712
                ProductCache.categories_json.like(pat),
            )
            .order_by(ProductCache.name)
            .limit(limit * 2)
        )
        rows = (await db.execute(stmt)).scalars().all()
        for row in rows:
            if row.sku not in seen and row.sku not in exclude_skus:
                seen.add(row.sku)
                results.append(row)
        if len(results) >= limit:
            break
    return results[:limit]


# ── Weather cache ─────────────────────────────────────────────────────────────


async def upsert_weather(
    db: AsyncSession,
    date: datetime.date,
    latitude: float,
    longitude: float,
    temperature_max: float,
) -> None:
    stmt = sqlite_insert(WeatherCache).values(
        date=date,
        latitude=round(latitude, 2),
        longitude=round(longitude, 2),
        temperature_max=temperature_max,
        fetched_at=_utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[WeatherCache.date, WeatherCache.latitude, WeatherCache.longitude],
        set_={"temperature_max": temperature_max, "fetched_at": _utcnow()},
    )
    await db.execute(stmt)
    await db.commit()


async def get_weather(
    db: AsyncSession, latitude: float, longitude: float, date: datetime.date
) -> WeatherCache | None:
    lat = round(latitude, 2)
    lon = round(longitude, 2)
    result = await db.execute(
        select(WeatherCache).where(
            WeatherCache.date == date,
            WeatherCache.latitude == lat,
            WeatherCache.longitude == lon,
        )
    )
    return result.scalar_one_or_none()


async def get_weather_range(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    start: datetime.date,
    end: datetime.date,
) -> dict[datetime.date, float]:
    lat = round(latitude, 2)
    lon = round(longitude, 2)
    result = await db.execute(
        select(WeatherCache).where(
            WeatherCache.latitude == lat,
            WeatherCache.longitude == lon,
            WeatherCache.date >= start,
            WeatherCache.date <= end,
        )
    )
    return {row.date: row.temperature_max for row in result.scalars().all()}


# ── Autopilot plans ──────────────────────────────────────────────────────────


async def get_autopilot_plan(
    db: AsyncSession,
    user_id: int,
    week_start: datetime.date,
) -> AutopilotPlan | None:
    result = await db.execute(
        select(AutopilotPlan).where(
            AutopilotPlan.user_id == user_id,
            AutopilotPlan.week_start == week_start,
        )
    )
    return result.scalar_one_or_none()


async def get_latest_autopilot_plan(
    db: AsyncSession,
    user_id: int,
) -> AutopilotPlan | None:
    result = await db.execute(
        select(AutopilotPlan)
        .where(AutopilotPlan.user_id == user_id)
        .order_by(AutopilotPlan.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def upsert_autopilot_plan(
    db: AsyncSession,
    user_id: int,
    week_start: datetime.date,
    plan_json: str,
    status: str = "draft",
) -> AutopilotPlan:
    existing = await get_autopilot_plan(db, user_id, week_start)
    if existing:
        existing.plan_json = plan_json
        existing.status = status
        existing.created_at = _utcnow()
        existing.confirmed_at = None
        existing.cart_snapshot_json = None
    else:
        existing = AutopilotPlan(
            user_id=user_id,
            week_start=week_start,
            plan_json=plan_json,
            status=status,
            created_at=_utcnow(),
        )
        db.add(existing)
    await db.commit()
    await db.refresh(existing)
    return existing


async def update_autopilot_plan_status(
    db: AsyncSession,
    plan_id: int,
    status: str,
    *,
    cart_snapshot_json: str | None = None,
) -> None:
    result = await db.execute(select(AutopilotPlan).where(AutopilotPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        return
    plan.status = status
    if status == "confirmed":
        plan.confirmed_at = _utcnow()
    if cart_snapshot_json is not None:
        plan.cart_snapshot_json = cart_snapshot_json
    await db.commit()


async def expire_old_autopilot_plans(
    db: AsyncSession,
    user_id: int,
    before: datetime.date,
) -> int:
    result = await db.execute(
        select(AutopilotPlan).where(
            AutopilotPlan.user_id == user_id,
            AutopilotPlan.status == "draft",
            AutopilotPlan.week_start < before,
        )
    )
    plans = result.scalars().all()
    for p in plans:
        p.status = "expired"
    await db.commit()
    return len(plans)
