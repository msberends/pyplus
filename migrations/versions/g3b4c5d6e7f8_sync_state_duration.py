"""Add last_duration_seconds to sync_state.

Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-29

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "g3b4c5d6e7f8"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("sync_state") as batch:
        batch.add_column(sa.Column("last_duration_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sync_state") as batch:
        batch.drop_column("last_duration_seconds")
