"""Finance domain (M7): Plaid items / accounts / transactions / securities /
holdings + local budgets.

Six tables. The five synced tables are keyed (owner, source, source_id) =
('plaid', <id>) for idempotent upsert; finance_holdings is keyed
(owner, account_id, security_id) and finance_budgets (owner, category, month).
Read-only against Plaid — access_tokens live in finance_items server-side.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "finance_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("institution_id", sa.String(length=64), nullable=False),
        sa.Column("institution_name", sa.String(length=255), nullable=False),
        sa.Column("products", JSONField, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_items_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_items_owner"), "finance_items", ["owner"])
    op.create_index(op.f("ix_finance_items_source"), "finance_items", ["source"])
    op.create_index(op.f("ix_finance_items_source_id"), "finance_items", ["source_id"])

    op.create_table(
        "finance_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("official_name", sa.String(length=255), nullable=True),
        sa.Column("mask", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("subtype", sa.String(length=48), nullable=True),
        sa.Column("current_balance", sa.Numeric(16, 2), nullable=True),
        sa.Column("available_balance", sa.Numeric(16, 2), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_accounts_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_accounts_owner"), "finance_accounts", ["owner"])
    op.create_index(op.f("ix_finance_accounts_source"), "finance_accounts", ["source"])
    op.create_index(op.f("ix_finance_accounts_source_id"), "finance_accounts", ["source_id"])
    op.create_index(op.f("ix_finance_accounts_item_id"), "finance_accounts", ["item_id"])

    op.create_table(
        "finance_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("authorized_date", sa.Date(), nullable=True),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("category_primary", sa.String(length=64), nullable=False),
        sa.Column("category_detailed", sa.String(length=128), nullable=False),
        sa.Column("payment_channel", sa.String(length=32), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_transactions_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_transactions_owner"), "finance_transactions", ["owner"])
    op.create_index(op.f("ix_finance_transactions_source"), "finance_transactions", ["source"])
    op.create_index(op.f("ix_finance_transactions_source_id"), "finance_transactions", ["source_id"])
    op.create_index(op.f("ix_finance_transactions_account_id"), "finance_transactions", ["account_id"])
    op.create_index(op.f("ix_finance_transactions_item_id"), "finance_transactions", ["item_id"])
    op.create_index(op.f("ix_finance_transactions_date"), "finance_transactions", ["date"])

    op.create_table(
        "finance_securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ticker_symbol", sa.String(length=32), nullable=True),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("close_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("is_cash_equivalent", sa.Boolean(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_securities_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_securities_owner"), "finance_securities", ["owner"])
    op.create_index(op.f("ix_finance_securities_source"), "finance_securities", ["source"])
    op.create_index(op.f("ix_finance_securities_source_id"), "finance_securities", ["source_id"])

    op.create_table(
        "finance_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("security_id", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(20, 8), nullable=True),
        sa.Column("institution_value", sa.Numeric(16, 2), nullable=False),
        sa.Column("institution_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "account_id", "security_id",
                            name="uq_finance_holdings_owner_account_security"),
    )
    op.create_index(op.f("ix_finance_holdings_owner"), "finance_holdings", ["owner"])
    op.create_index(op.f("ix_finance_holdings_source"), "finance_holdings", ["source"])
    op.create_index(op.f("ix_finance_holdings_item_id"), "finance_holdings", ["item_id"])
    op.create_index(op.f("ix_finance_holdings_account_id"), "finance_holdings", ["account_id"])
    op.create_index(op.f("ix_finance_holdings_security_id"), "finance_holdings", ["security_id"])

    op.create_table(
        "finance_budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("limit_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "category", "month",
                            name="uq_finance_budgets_owner_category_month"),
    )
    op.create_index(op.f("ix_finance_budgets_owner"), "finance_budgets", ["owner"])
    op.create_index(op.f("ix_finance_budgets_category"), "finance_budgets", ["category"])
    op.create_index(op.f("ix_finance_budgets_month"), "finance_budgets", ["month"])


def downgrade() -> None:
    op.drop_table("finance_budgets")
    op.drop_table("finance_holdings")
    op.drop_table("finance_securities")
    op.drop_table("finance_transactions")
    op.drop_table("finance_accounts")
    op.drop_table("finance_items")
