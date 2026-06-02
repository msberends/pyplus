"""Save/load precomputed ML results from the ml_artifacts DB table via pickle."""

from __future__ import annotations

import hashlib
import logging
import pickle
from typing import Any

log = logging.getLogger(__name__)


async def save_artifact(user_id: int, kind: str, obj: Any, input_data: bytes = b"") -> None:
    input_hash = hashlib.sha256(input_data).hexdigest() if input_data else ""
    blob = pickle.dumps(obj, protocol=5)

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await repo.upsert_ml_artifact(db, user_id, kind, blob, input_hash)
    log.debug("Saved ML artifact '%s' for user=%d (%d bytes)", kind, user_id, len(blob))


async def load_artifact(user_id: int, kind: str) -> Any | None:
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await repo.get_ml_artifact(db, user_id, kind)
    if row is None:
        return None
    try:
        return pickle.loads(row.blob)
    except Exception as exc:
        log.warning("Failed to load ML artifact '%s' for user=%d: %s", kind, user_id, exc)
        return None
