"""Add min_qty to fixed_products.

Revision ID: h4c5d6e7f8g9
Revises: g3b4c5d6e7f8
Create Date: 2026-07-06

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "h4c5d6e7f8g9"
down_revision: Union[str, None] = "g3b4c5d6e7f8"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("fixed_products") as batch:
        batch.add_column(sa.Column("min_qty", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("fixed_products") as batch:
        batch.drop_column("min_qty")
