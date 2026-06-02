"""Dish planning metadata + product slug/brand columns.

Adds the dish fields carried over from the R "Gerechten beheren" screen
(prep time, meat/diet type, vegetable count) and slug columns used to build
clickable plus.nl product links.

Revision ID: b7c4d9e2f1a8
Revises: a3f2e1d4c5b6
Create Date: 2026-06-02

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c4d9e2f1a8"
down_revision: Union[str, None] = "a3f2e1d4c5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(sa.Column("prep_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("meat_type", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("veg_count", sa.Integer(), nullable=True))

    with op.batch_alter_table("ingredient_skus") as batch:
        batch.add_column(
            sa.Column("slug", sa.String(length=200), nullable=False, server_default="")
        )

    with op.batch_alter_table("product_cache") as batch:
        batch.add_column(
            sa.Column("brand", sa.String(length=200), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("slug", sa.String(length=200), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("product_cache") as batch:
        batch.drop_column("slug")
        batch.drop_column("brand")

    with op.batch_alter_table("ingredient_skus") as batch:
        batch.drop_column("slug")

    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("veg_count")
        batch.drop_column("meat_type")
        batch.drop_column("prep_minutes")
