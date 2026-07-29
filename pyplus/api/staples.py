"""Staples (fixed products) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pyplus.api.auth import get_api_user
from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User

router = APIRouter(prefix="/staples")


def _serialize_fp(fp) -> dict:
    return {
        "sku": fp.sku,
        "display_name": fp.display_name,
        "default_qty": fp.default_qty,
        "every_n_weeks": fp.every_n_weeks,
        "last_added_at": fp.last_added_at.isoformat() if fp.last_added_at else None,
        "sort_order": fp.sort_order,
    }


@router.get("")
async def list_staples(user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        products = await repo.get_fixed_products(db, user.id)
    return {"ok": True, "data": [_serialize_fp(fp) for fp in products]}


class StapleCreate(BaseModel):
    sku: str
    display_name: str
    default_qty: int = 1
    every_n_weeks: int = 1


@router.post("")
async def add_staple(body: StapleCreate, user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        fp = await repo.add_fixed_product(
            db, user.id, body.sku, body.display_name, body.default_qty, body.every_n_weeks
        )
    if fp is None:
        return {"ok": False, "error": "Invalid SKU"}
    return {"ok": True, "data": _serialize_fp(fp)}


@router.delete("/{sku}")
async def remove_staple(sku: str, user: User = Depends(get_api_user)) -> dict:
    async with AsyncSessionLocal() as db:
        await repo.remove_fixed_product(db, user.id, sku)
    return {"ok": True, "data": None}
