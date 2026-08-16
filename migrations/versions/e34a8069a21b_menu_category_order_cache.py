"""menu category order cache

Revision ID: e34a8069a21b
Revises: 42f9e7706336
Create Date: 2026-08-16 08:19:43.348465

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e34a8069a21b"
down_revision: Union[str, None] = "42f9e7706336"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "menu_category_order_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("menu_category_order_cache")
