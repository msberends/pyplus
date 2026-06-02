"""Initial schema — all tables.

Revision ID: a3f2e1d4c5b6
Revises:
Create Date: 2026-06-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f2e1d4c5b6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plus_email_enc", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("store_number", sa.Integer(), nullable=True),
        sa.Column("user_store_id", sa.String(50), nullable=False, server_default=""),
        sa.Column("one_welcome_user_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── credentials ────────────────────────────────────────────────────────────
    op.create_table(
        "credentials",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=False),
        sa.Column("remember", sa.Boolean(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # ── dishes ─────────────────────────────────────────────────────────────────
    op.create_table(
        "dishes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("prep_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── dish_ingredients ───────────────────────────────────────────────────────
    op.create_table(
        "dish_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("amount_unit", sa.String(20), nullable=False),
        sa.Column("pack_size", sa.Float(), nullable=True),
        sa.Column("pack_unit", sa.String(20), nullable=True),
        sa.Column("optional", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── ingredient_skus (per-user-store cache) ─────────────────────────────────
    op.create_table(
        "ingredient_skus",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("subtitle", sa.String(200), nullable=False, server_default=""),
        sa.Column("image_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("pack_size", sa.Float(), nullable=True),
        sa.Column("pack_unit", sa.String(20), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("last_seen_available", sa.Boolean(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "sku"),
    )

    # ── fixed_products ─────────────────────────────────────────────────────────
    op.create_table(
        "fixed_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("default_qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── weekmenu ───────────────────────────────────────────────────────────────
    op.create_table(
        "weekmenu",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(20), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slot", "week_start", name="uq_weekmenu_user_slot_week"),
    )

    # ── product_cache (shared by store) ────────────────────────────────────────
    op.create_table(
        "product_cache",
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("store_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("subtitle", sa.String(200), nullable=False, server_default=""),
        sa.Column("image_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("sku", "store_number"),
    )

    # ── purchased_products_cache ───────────────────────────────────────────────
    op.create_table(
        "purchased_products_cache",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("brand", sa.String(200), nullable=False, server_default=""),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("subtitle", sa.String(200), nullable=False, server_default=""),
        sa.Column("slug", sa.String(200), nullable=False, server_default=""),
        sa.Column("image_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("categories_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "sku"),
    )

    # ── order_cache ────────────────────────────────────────────────────────────
    op.create_table(
        "order_cache",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column("order_number", sa.String(100), nullable=False, server_default=""),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("total_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(100), nullable=False, server_default=""),
        sa.Column("channel", sa.String(50), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "order_id"),
    )

    # ── order_item_cache ───────────────────────────────────────────────────────
    op.create_table(
        "order_item_cache",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("subtitle", sa.String(200), nullable=False, server_default=""),
        sa.Column("slug", sa.String(200), nullable=False, server_default=""),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(200), nullable=False, server_default=""),
        sa.Column("available", sa.Boolean(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["user_id", "order_id"],
            ["order_cache.user_id", "order_cache.order_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "order_id", "sku"),
    )

    # ── sync_state ─────────────────────────────────────────────────────────────
    op.create_table(
        "sync_state",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resource", sa.String(30), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(50), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "resource"),
    )

    # ── promotions_cache (store-level, shared) ─────────────────────────────────
    op.create_table(
        "promotions_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_number", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("is_next_week", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_number", "week_start", "is_next_week", name="uq_promos_store_week"
        ),
    )

    # ── ml_artifacts ───────────────────────────────────────────────────────────
    op.create_table(
        "ml_artifacts",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "kind"),
    )


def downgrade() -> None:
    op.drop_table("ml_artifacts")
    op.drop_table("promotions_cache")
    op.drop_table("sync_state")
    op.drop_table("order_item_cache")
    op.drop_table("order_cache")
    op.drop_table("purchased_products_cache")
    op.drop_table("product_cache")
    op.drop_table("weekmenu")
    op.drop_table("fixed_products")
    op.drop_table("ingredient_skus")
    op.drop_table("dish_ingredients")
    op.drop_table("dishes")
    op.drop_table("credentials")
    op.drop_table("users")
