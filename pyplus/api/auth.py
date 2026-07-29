"""Bearer token authentication for the REST API."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Request
from fastapi.exceptions import HTTPException

from pyplus.db import repo
from pyplus.db.engine import AsyncSessionLocal
from pyplus.db.models import User

_PREFIX = "pyplus_"


def generate_api_key() -> str:
    return _PREFIX + secrets.token_hex(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def get_api_user(request: Request) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = auth[7:].strip()
    if not token.startswith(_PREFIX):
        raise HTTPException(401, "Invalid API key format")
    key_hash = hash_api_key(token)
    async with AsyncSessionLocal() as db:
        user = await repo.get_user_by_api_key_hash(db, key_hash)
    if user is None:
        raise HTTPException(401, "Invalid API key")
    return user
