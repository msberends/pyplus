"""Health check endpoint — no auth required."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "data": {"status": "running"}}
