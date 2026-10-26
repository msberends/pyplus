"""Add is_organic to product_cache.

Revision ID: p2k3l4m5n6o7
Revises: e34a8069a21b
Create Date: 2026-10-26

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "p2k3l4m5n6o7"
down_revision: Union[str, None] = "e34a8069a21b"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Plain ADD COLUMN (no batch table copy) — product_cache is large and shared.
    op.add_column(
        "product_cache",
        sa.Column("is_organic", sa.Boolean(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    with op.batch_alter_table("product_cache") as batch:
        batch.drop_column("is_organic")
