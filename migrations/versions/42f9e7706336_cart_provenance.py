"""cart provenance

Revision ID: 42f9e7706336
Revises: o1j2k3l4m5n6
Create Date: 2026-08-15 20:23:46.408259

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "42f9e7706336"
down_revision: Union[str, None] = "o1j2k3l4m5n6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cart_provenance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.Column("via_autopilot", sa.Boolean(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "sku", "kind", "detail", name="uq_cart_provenance"),
    )
    op.create_index(op.f("ix_cart_provenance_sku"), "cart_provenance", ["sku"], unique=False)
    op.create_index(
        op.f("ix_cart_provenance_user_id"), "cart_provenance", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cart_provenance_user_id"), table_name="cart_provenance")
    op.drop_index(op.f("ix_cart_provenance_sku"), table_name="cart_provenance")
    op.drop_table("cart_provenance")
