"""Data-access helpers — all writes are user-scoped."""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyplus.db.models import (
    Credentials,
    Dish,
    DishIngredient,
    FixedProduct,
    IngredientSku,
    MlArtifact,
    OrderCache,
    OrderItemCache,
    PromotionsCache,
    PurchasedProductCache,
    SyncState,
    User,
    Weekmenu,
)

log = logging.getLogger(__name__)


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
    user_store_id: str = "",
) -> User:
    user = User(
        plus_email_enc=plus_email_enc,
        one_welcome_user_id=onewelcome_user_id,
        display_name=display_name,
        store_number=store_number,
        user_store_id=user_store_id,
        created_at=datetime.datetime.utcnow(),
        last_login_at=datetime.datetime.utcnow(),
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
    user_store_id: str = "",
    display_name: str = "",
) -> None:
    user = await get_user_by_id(db, user_id)
    if not user:
        return
    user.last_login_at = datetime.datetime.utcnow()
    if store_number is not None:
        user.store_number = store_number
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


async def get_dish(db: AsyncSession, user_id: int, dish_id: int) -> Dish | None:
    result = await db.execute(select(Dish).where(Dish.id == dish_id, Dish.user_id == user_id))
    return result.scalar_one_or_none()


async def create_dish(db: AsyncSession, user_id: int, *, name: str, prep_notes: str = "") -> Dish:
    dish = Dish(
        user_id=user_id,
        name=name,
        prep_notes=prep_notes,
        created_at=datetime.datetime.utcnow(),
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
    image_url: str = "",
    pack_size: float | None = None,
    pack_unit: str | None = None,
    last_price: float | None = None,
    last_seen_available: bool | None = None,
) -> IngredientSku:
    row = await get_ingredient_sku(db, user_id, sku)
    now = datetime.datetime.utcnow()
    if row:
        row.name = name
        row.subtitle = subtitle
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


async def upsert_sync_state(
    db: AsyncSession,
    user_id: int,
    resource: str,
    status: str,
    detail: str | None = None,
) -> None:
    row = await get_sync_state(db, user_id, resource)
    now = datetime.datetime.utcnow()
    if row:
        row.last_status = status
        row.last_synced_at = now
        if detail is not None:
            row.detail_json = detail
    else:
        db.add(
            SyncState(
                user_id=user_id,
                resource=resource,
                last_status=status,
                last_synced_at=now,
                detail_json=detail,
            )
        )
    await db.commit()


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
    now = datetime.datetime.utcnow()
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
    import json as _json

    now = datetime.datetime.utcnow()
    for p in products:
        result = await db.execute(
            select(PurchasedProductCache).where(
                PurchasedProductCache.user_id == user_id,
                PurchasedProductCache.sku == p.sku,
            )
        )
        row = result.scalar_one_or_none()
        cats = _json.dumps(p.categories if hasattr(p, "categories") else [])
        if row:
            row.name = p.name
            row.brand = getattr(p, "brand", "")
            row.subtitle = getattr(p, "subtitle", "")
            row.slug = getattr(p, "slug", "")
            row.image_url = getattr(p, "image_url", "")
            row.price = getattr(p, "price", 0.0)
            row.is_available = getattr(p, "is_available", False)
            row.categories_json = cats
            row.fetched_at = now
        else:
            db.add(
                PurchasedProductCache(
                    user_id=user_id,
                    sku=p.sku,
                    name=p.name,
                    brand=getattr(p, "brand", ""),
                    subtitle=getattr(p, "subtitle", ""),
                    slug=getattr(p, "slug", ""),
                    image_url=getattr(p, "image_url", ""),
                    price=getattr(p, "price", 0.0),
                    is_available=getattr(p, "is_available", False),
                    categories_json=cats,
                    fetched_at=now,
                )
            )
    await db.commit()


# ── Order history cache ────────────────────────────────────────────────────────


async def get_cached_order_ids(db: AsyncSession, user_id: int) -> set[str]:
    """Return order IDs that already have line items cached."""
    result = await db.execute(
        select(OrderItemCache.order_id).where(OrderItemCache.user_id == user_id).distinct()
    )
    return set(result.scalars().all())


async def upsert_order_summaries(db: AsyncSession, user_id: int, orders: list) -> None:
    """Store/update OrderSummary rows (no line items)."""
    now = datetime.datetime.utcnow()
    for o in orders:
        result = await db.execute(
            select(OrderCache).where(
                OrderCache.user_id == user_id,
                OrderCache.order_id == o.order_id,
            )
        )
        row = result.scalar_one_or_none()
        delivery = None
        if o.delivery_date and o.delivery_date != "1900-01-01":
            try:
                delivery = datetime.date.fromisoformat(o.delivery_date)
            except ValueError:
                pass
        if row:
            row.order_number = o.order_number
            row.delivery_date = delivery
            row.total_price = o.total_price
            row.status = o.status
            row.channel = o.channel
            row.is_active = o.is_active
            row.fetched_at = now
        else:
            db.add(
                OrderCache(
                    user_id=user_id,
                    order_id=o.order_id,
                    order_number=o.order_number,
                    delivery_date=delivery,
                    total_price=o.total_price,
                    status=o.status,
                    channel=o.channel,
                    is_active=o.is_active,
                    fetched_at=now,
                )
            )
    await db.commit()


async def upsert_order_items(db: AsyncSession, user_id: int, order_id: str, items: list) -> None:
    """Store line items for one order (idempotent — deletes existing items first)."""
    await db.execute(
        __import__("sqlalchemy")
        .delete(OrderItemCache)
        .where(
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
    now = datetime.datetime.utcnow()
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
    db: AsyncSession, user_id: int
) -> dict[int, list[DishIngredient]]:
    """Single query: all ingredients for all non-archived dishes. Returns dish_id → list."""
    result = await db.execute(
        select(DishIngredient)
        .join(Dish, Dish.id == DishIngredient.dish_id)
        .where(Dish.user_id == user_id, Dish.archived == False)  # noqa: E712
        .order_by(DishIngredient.dish_id, DishIngredient.sort_order)
    )
    by_dish: dict[int, list[DishIngredient]] = {}
    for ing in result.scalars().all():
        by_dish.setdefault(ing.dish_id, []).append(ing)
    return by_dish


async def get_dish_availability(
    db: AsyncSession, user_id: int, dish_id: int
) -> tuple[int, int, int]:
    """Return (available, unavailable, unknown) counts across all non-optional ingredients."""
    ingredients = await get_ingredients(db, dish_id)
    available = unavailable = unknown = 0
    for ing in ingredients:
        if ing.optional:
            continue
        cached = await get_ingredient_sku(db, user_id, ing.sku)
        if cached is None or cached.last_seen_available is None:
            unknown += 1
        elif cached.last_seen_available:
            available += 1
        else:
            unavailable += 1
    return available, unavailable, unknown
