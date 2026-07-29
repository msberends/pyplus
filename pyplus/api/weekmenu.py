"""Weekmenu endpoints — read current/history, set slots."""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User, WeekSlot

router = APIRouter(prefix="/weekmenu")


def _serialize_slot(entry) -> dict:
    d = entry.dish
    return {
        "slot": entry.slot,
        "week_start": entry.week_start.isoformat(),
        "dish": {
            "id": d.id,
            "name": d.name,
            "meat_type": d.meat_type,
            "starch_type": d.starch_type,
            "prep_minutes": d.prep_minutes,
            "is_cold": d.is_cold,
            "is_dinner": d.is_dinner,
            "rating": d.rating,
            "group_name": d.group_name,
            "cooking_methods": json.loads(d.cooking_methods) if d.cooking_methods else [],
        }
        if d
        else None,
    }


@router.get("")
async def get_weekmenu(
    week: str | None = None,
    user: User = Depends(get_api_user),
) -> dict:
    if week:
        week_start = datetime.date.fromisoformat(week)
    else:
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())

    async with AsyncSessionLocal() as db:
        entries = await repo.get_weekmenu(db, user.id, week_start)

    return {
        "ok": True,
        "data": {
            "week_start": week_start.isoformat(),
            "slots": [_serialize_slot(e) for e in entries],
        },
    }


@router.get("/history")
async def get_weekmenu_history(
    weeks: int = 8,
    user: User = Depends(get_api_user),
) -> dict:
    async with AsyncSessionLocal() as db:
        entries = await repo.get_weekmenu_history(db, user.id, limit_weeks=min(weeks, 52))

    grouped: dict[str, list] = {}
    for e in entries:
        key = e.week_start.isoformat()
        grouped.setdefault(key, []).append(_serialize_slot(e))

    return {"ok": True, "data": {"weeks": grouped}}


class SlotUpdate(BaseModel):
    slot: str
    week_start: str
    dish_id: int | None = None


@router.put("/slot")
async def set_slot(body: SlotUpdate, user: User = Depends(get_api_user)) -> dict:
    try:
        WeekSlot(body.slot)
    except ValueError:
        return {"ok": False, "error": f"Invalid slot: {body.slot}"}

    week_start = datetime.date.fromisoformat(body.week_start)

    async with AsyncSessionLocal() as db:
        await repo.set_weekmenu_slot(db, user.id, body.slot, week_start, body.dish_id)

    return {
        "ok": True,
        "data": {"slot": body.slot, "week_start": week_start.isoformat(), "dish_id": body.dish_id},
    }
