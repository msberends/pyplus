"""Main API router — assembles all sub-routers under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from pyplus.api import (
    autopilot,
    dishes,
    health,
    jobs,
    promotions,
    settings_api,
    staples,
    status,
    weekmenu,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(status.router)
api_router.include_router(weekmenu.router)
api_router.include_router(dishes.router)
api_router.include_router(staples.router)
api_router.include_router(promotions.router)
api_router.include_router(settings_api.router)
api_router.include_router(autopilot.router)
api_router.include_router(jobs.router)
