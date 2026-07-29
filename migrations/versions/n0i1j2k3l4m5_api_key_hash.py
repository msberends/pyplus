"""Add api_key_hash to users for REST API authentication.

Revision ID: n0i1j2k3l4m5
Revises: m9h0i1j2k3l4
Create Date: 2026-07-30

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "n0i1j2k3l4m5"
down_revision: Union[str, None] = "m9h0i1j2k3l4"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("api_key_hash", sa.String(128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("api_key_hash")
