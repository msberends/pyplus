"""Add cooking_methods, is_cold to dishes; create weather_cache table.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-03

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch:
        batch.add_column(
            sa.Column("cooking_methods", sa.Text(), server_default="[]", nullable=False)
        )
        batch.add_column(
            sa.Column("is_cold", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    op.create_table(
        "weather_cache",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("temperature_max", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("date", "latitude", "longitude"),
    )


def downgrade() -> None:
    op.drop_table("weather_cache")
    with op.batch_alter_table("dishes") as batch:
        batch.drop_column("is_cold")
        batch.drop_column("cooking_methods")
