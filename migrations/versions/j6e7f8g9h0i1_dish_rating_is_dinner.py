"""Add rating and is_dinner to dishes.

Revision ID: j6e7f8g9h0i1
Revises: i5d6e7f8g9h0
Create Date: 2026-07-07

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "j6e7f8g9h0i1"
down_revision: Union[str, None] = "i5d6e7f8g9h0"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(sa.Column("is_dinner", sa.Boolean(), server_default="1", nullable=False))
        batch.add_column(sa.Column("rating", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("rating")
        batch.drop_column("is_dinner")
