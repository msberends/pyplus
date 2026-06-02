"""Store product categories in the catalogue cache.

Adds product_cache.categories_json — a JSON list of PLUS category names per
product (the category breadcrumb), captured during the catalogue sync. Enables
grouping/sorting/organising the full ~11k-product catalogue, not just the
purchase history.

Revision ID: d9e6f1a4c7b2
Revises: c8d5e0a3b2f9
Create Date: 2026-06-03

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e6f1a4c7b2"
down_revision: Union[str, None] = "c8d5e0a3b2f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("product_cache") as batch:
        batch.add_column(
            sa.Column("categories_json", sa.Text(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("product_cache") as batch:
        batch.drop_column("categories_json")
