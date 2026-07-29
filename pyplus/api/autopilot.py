"""Autopilot endpoints — read plan status, trigger preparation."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User

router = APIRouter(prefix="/autopilot")


@router.get("/plan")
async def get_plan(user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        plan = await repo.get_latest_autopilot_plan(db, user.id)

    if plan is None:
        return {"ok": True, "data": None}

    return {
        "ok": True,
        "data": {
            "id": plan.id,
            "week_start": plan.week_start.isoformat(),
            "status": plan.status,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
            "plan": json.loads(plan.plan_json),
        },
    }


@router.post("/prepare")
async def prepare(user: User = Depends(get_api_user)) -> dict:
    from pyplus.jobs.registry import autopilot_prepare

    asyncio.create_task(autopilot_prepare(user_id=user.id))
    return {"ok": True, "data": {"message": "Autopilot preparation started"}}
