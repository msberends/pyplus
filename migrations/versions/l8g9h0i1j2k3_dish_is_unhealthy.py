"""Add is_unhealthy to dishes.

Revision ID: l8g9h0i1j2k3
Revises: k7f8g9h0i1j2
Create Date: 2026-07-11

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "l8g9h0i1j2k3"
down_revision: Union[str, None] = "k7f8g9h0i1j2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(
            sa.Column("is_unhealthy", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("is_unhealthy")
