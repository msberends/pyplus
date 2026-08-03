"""Dishes endpoints — read-only."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User

router = APIRouter(prefix="/dishes")


def _serialize_dish(d, *, ingredients: list | None = None) -> dict:
    out = {
        "id": d.id,
        "name": d.name,
        "prep_notes": d.prep_notes,
        "prep_minutes": d.prep_minutes,
        "meat_type": d.meat_type,
        "starch_type": d.starch_type,
        "cooking_methods": json.loads(d.cooking_methods) if d.cooking_methods else [],
        "is_cold": d.is_cold,
        "is_unhealthy": d.is_unhealthy,
        "is_restaurant": d.is_restaurant,
        "is_dinner": d.is_dinner,
        "rating": d.rating,
        "veg_count": d.veg_count,
        "archived": d.archived,
        "group_name": d.group_name,
        "cooldown_weeks": d.cooldown_weeks,
    }
    if ingredients is not None:
        out["ingredients"] = [
            {
                "id": ing.id,
                "sku": ing.sku,
                "display_name": ing.display_name,
                "amount": ing.amount,
                "amount_unit": ing.amount_unit,
                "pack_size": ing.pack_size,
                "pack_unit": ing.pack_unit,
                "optional": ing.optional,
                "flexible": ing.flexible,
            }
            for ing in ingredients
        ]
    return out


@router.get("")
async def list_dishes(
    include_archived: bool = False,
    user: User = Depends(get_api_user),
) -> dict:
    async with AsyncSessionLocal() as db:
        dishes = await repo.get_dishes(db, user.id, include_archived=include_archived)
    return {"ok": True, "data": [_serialize_dish(d) for d in dishes]}


@router.get("/{dish_id}")
async def get_dish(dish_id: int, user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        dish = await repo.get_dish(db, user.id, dish_id)
        if dish is None:
            return {"ok": False, "error": "Dish not found"}
        ingredients = await repo.get_ingredients(db, dish_id)
    return {"ok": True, "data": _serialize_dish(dish, ingredients=ingredients)}
