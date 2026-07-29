"""Promotions endpoint — cached, read-only."""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User

router = APIRouter(prefix="/promotions")


@router.get("")
async def get_promotions(user: User = Depends(get_api_user)) -> dict:
    if not user.store_number:
        return {"ok": False, "error": "No store configured for this user"}

    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    async with AsyncSessionLocal() as db:
        cache = await repo.get_promotions_cache(db, user.store_number, week_start)

    if cache is None:
        return {"ok": False, "error": "Promotions cache is empty — run a sync first"}

    return {
        "ok": True,
        "data": {
            "week_start": week_start.isoformat(),
            "fetched_at": cache.fetched_at.isoformat() if cache.fetched_at else None,
            "promotions": json.loads(cache.payload_json),
        },
    }
