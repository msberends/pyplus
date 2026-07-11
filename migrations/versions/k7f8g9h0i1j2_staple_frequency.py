"""Add every_n_weeks and last_added_at to fixed_products.

Revision ID: k7f8g9h0i1j2
Revises: j6e7f8g9h0i1
Create Date: 2026-07-08

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "k7f8g9h0i1j2"
down_revision: Union[str, None] = "j6e7f8g9h0i1"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("fixed_products") as batch:
        batch.add_column(
            sa.Column("every_n_weeks", sa.Integer(), server_default="1", nullable=False)
        )
        batch.add_column(sa.Column("last_added_at", sa.Date(), nullable=True))

    # Seed last_added_at from order history — most recent delivery_date per staple SKU
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE fixed_products
            SET last_added_at = (
                SELECT MAX(oc.delivery_date)
                FROM order_item_cache oic
                JOIN order_cache oc ON oc.order_id = oic.order_id
                    AND oc.user_id = oic.user_id
                WHERE oic.sku = fixed_products.sku
                    AND oic.user_id = fixed_products.user_id
                    AND oc.delivery_date IS NOT NULL
            )
        """)
    )


def downgrade() -> None:
    with op.batch_alter_table("fixed_products") as batch:
        batch.drop_column("last_added_at")
        batch.drop_column("every_n_weeks")
