"""Add starch_type column to dishes for meal variety tracking.

Revision ID: e1f2a3b4c5d6
Revises: d9e6f1a4c7b2
Create Date: 2026-06-03

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e6f1a4c7b2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(sa.Column("starch_type", sa.String(30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("starch_type")
