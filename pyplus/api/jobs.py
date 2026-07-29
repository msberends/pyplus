"""Job trigger endpoint — no-client jobs only."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from pyplus.api.auth import get_api_user
from pyplus.db.models import User

router = APIRouter(prefix="/jobs")

_ALLOWED_JOBS = {"recompute_ml", "refresh_weather", "autopilot_prepare"}


@router.post("/{name}/run")
async def run_job(name: str, user: User = Depends(get_api_user)) -> dict:
    if name not in _ALLOWED_JOBS:
        return {
            "ok": False,
            "error": f"Job '{name}' is not available via API. Allowed: {', '.join(sorted(_ALLOWED_JOBS))}",
        }

    from pyplus.jobs import registry

    job_fn = getattr(registry, name, None)
    if job_fn is None:
        return {"ok": False, "error": f"Job '{name}' not found"}

    asyncio.create_task(job_fn(user_id=user.id))
    return {"ok": True, "data": {"message": f"Job '{name}' started"}}
