"""Add autopilot_plans table.

Revision ID: i5d6e7f8g9h0
Revises: h4c5d6e7f8g9
Create Date: 2026-07-06

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "i5d6e7f8g9h0"
down_revision: Union[str, None] = "h4c5d6e7f8g9"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "autopilot_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("cart_snapshot_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "week_start", name="uq_autopilot_user_week_active"),
    )


def downgrade() -> None:
    op.drop_table("autopilot_plans")
