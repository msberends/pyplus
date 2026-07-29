"""Status endpoint — sync states, session info."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User
from pyplus.session import manager

router = APIRouter()


@router.get("/status")
async def status(user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        sync_states = await repo.get_all_sync_states(db, user.id)
        creds = await repo.get_credentials(db, user.id)

    session = manager.get(user.id)
    return {
        "ok": True,
        "data": {
            "session_active": session is not None,
            "has_credentials": creds is not None,
            "store_number": user.store_number,
            "store_name": user.store_name,
            "display_name": user.display_name,
            "sync_states": {
                resource: {
                    "last_synced_at": row.last_synced_at.isoformat()
                    if row.last_synced_at
                    else None,
                    "last_status": row.last_status,
                    "last_duration_seconds": row.last_duration_seconds,
                }
                for resource, row in sync_states.items()
            },
        },
    }
