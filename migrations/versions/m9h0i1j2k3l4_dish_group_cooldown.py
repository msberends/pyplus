"""Add group_name and cooldown_weeks to dishes.

Revision ID: m9h0i1j2k3l4
Revises: l8g9h0i1j2k3
Create Date: 2026-07-11

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "m9h0i1j2k3l4"
down_revision: Union[str, None] = "l8g9h0i1j2k3"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(sa.Column("group_name", sa.String(300), nullable=True))
        batch.add_column(sa.Column("cooldown_weeks", sa.Integer(), nullable=True))
    op.execute("UPDATE dishes SET group_name = name WHERE group_name IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("cooldown_weeks")
        batch.drop_column("group_name")
