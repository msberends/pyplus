"""Flexible dish ingredients.

Adds DishIngredient.flexible — a placeholder ingredient (label/instruction, no
fixed product) whose actual product is chosen when the dish is added to the cart.

Revision ID: c8d5e0a3b2f9
Revises: b7c4d9e2f1a8
Create Date: 2026-06-02

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d5e0a3b2f9"
down_revision: Union[str, None] = "b7c4d9e2f1a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dish_ingredients") as batch:
        batch.add_column(
            sa.Column("flexible", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # Backfill: ingredients with no SKU are flexible placeholders (free-text label,
    # product chosen at cart-add). The R import conflated these with "optional";
    # split them out so flexible and optional are independent again.
    op.execute(
        "UPDATE dish_ingredients SET flexible = 1, optional = 0 WHERE sku IS NULL OR sku = ''"
    )


def downgrade() -> None:
    with op.batch_alter_table("dish_ingredients") as batch:
        batch.drop_column("flexible")
