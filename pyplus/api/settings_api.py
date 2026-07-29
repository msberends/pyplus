"""User settings endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User
from pyplus.ml.interface import UserSettings

router = APIRouter(prefix="/settings")


@router.get("")
async def get_settings(user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        settings_json = await repo.get_user_settings_json(db, user.id)
    try:
        settings = UserSettings.model_validate_json(settings_json)
    except Exception:
        settings = UserSettings()
    return {"ok": True, "data": settings.model_dump()}


@router.patch("")
async def patch_settings(request: Request, user: User = Depends(get_api_user)) -> dict:
    patch = await request.json()
    if not isinstance(patch, dict):
        return {"ok": False, "error": "Request body must be a JSON object"}

    async with AsyncSessionLocal() as db:
        settings_json = await repo.get_user_settings_json(db, user.id)
        try:
            current = json.loads(settings_json)
        except Exception:
            current = {}
        current.update(patch)
        merged = UserSettings.model_validate(current)
        await repo.save_user_settings_json(db, user.id, merged.model_dump_json())

    return {"ok": True, "data": merged.model_dump()}
