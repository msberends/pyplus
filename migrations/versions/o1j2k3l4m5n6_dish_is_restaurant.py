"""Add is_restaurant to dishes.

Revision ID: o1j2k3l4m5n6
Revises: n0i1j2k3l4m5
Create Date: 2026-08-02

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "o1j2k3l4m5n6"
down_revision: Union[str, None] = "n0i1j2k3l4m5"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(
            sa.Column("is_restaurant", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("is_restaurant")
