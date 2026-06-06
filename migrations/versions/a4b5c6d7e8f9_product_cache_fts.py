"""Add FTS5 trigram index over product_cache(name, brand) for fast search.

Replaces the unindexable ``LIKE '%tok%'`` full-table scan. The DDL lives in
``pyplus.db.fts`` so this migration and the create_all path stay identical.

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-06-05

"""

from __future__ import annotations

from typing import Union

from alembic import op

from pyplus.db import fts

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    for stmt in fts.ALL_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS product_cache_au")
    op.execute("DROP TRIGGER IF EXISTS product_cache_ad")
    op.execute("DROP TRIGGER IF EXISTS product_cache_ai")
    op.execute(f"DROP TABLE IF EXISTS {fts.FTS_TABLE}")
