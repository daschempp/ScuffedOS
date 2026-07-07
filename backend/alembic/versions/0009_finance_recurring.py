"""Finance slice 2 (M7): recurring streams, liabilities, investment transactions.

Three tables keyed (owner, source, source_id) = ('plaid', <id>) for idempotent
upsert. Read-only against Plaid.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "finance_recurring",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("stream_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("category_primary", sa.String(length=64), nullable=False),
        sa.Column("category_detailed", sa.String(length=128), nullable=False),
        sa.Column("average_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("last_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("frequency", sa.String(length=24), nullable=False),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("predicted_next_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_recurring_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_recurring_owner"), "finance_recurring", ["owner"])
    op.create_index(op.f("ix_finance_recurring_source"), "finance_recurring", ["source"])
    op.create_index(op.f("ix_finance_recurring_source_id"), "finance_recurring", ["source_id"])
    op.create_index(op.f("ix_finance_recurring_item_id"), "finance_recurring", ["item_id"])
    op.create_index(op.f("ix_finance_recurring_account_id"), "finance_recurring", ["account_id"])

    op.create_table(
        "finance_liabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("liability_type", sa.String(length=16), nullable=False),
        sa.Column("last_statement_balance", sa.Numeric(16, 2), nullable=True),
        sa.Column("minimum_payment", sa.Numeric(16, 2), nullable=True),
        sa.Column("next_payment_due_date", sa.Date(), nullable=True),
        sa.Column("last_payment_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("last_payment_date", sa.Date(), nullable=True),
        sa.Column("apr_percentage", sa.Numeric(8, 4), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_liabilities_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_liabilities_owner"), "finance_liabilities", ["owner"])
    op.create_index(op.f("ix_finance_liabilities_source"), "finance_liabilities", ["source"])
    op.create_index(op.f("ix_finance_liabilities_source_id"), "finance_liabilities", ["source_id"])
    op.create_index(op.f("ix_finance_liabilities_item_id"), "finance_liabilities", ["item_id"])
    op.create_index(op.f("ix_finance_liabilities_account_id"), "finance_liabilities", ["account_id"])

    op.create_table(
        "finance_investment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("security_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("subtype", sa.String(length=48), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("fees", sa.Numeric(16, 2), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_investment_transactions_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_investment_transactions_owner"),
                    "finance_investment_transactions", ["owner"])
    op.create_index(op.f("ix_finance_investment_transactions_source"),
                    "finance_investment_transactions", ["source"])
    op.create_index(op.f("ix_finance_investment_transactions_source_id"),
                    "finance_investment_transactions", ["source_id"])
    op.create_index(op.f("ix_finance_investment_transactions_item_id"),
                    "finance_investment_transactions", ["item_id"])
    op.create_index(op.f("ix_finance_investment_transactions_account_id"),
                    "finance_investment_transactions", ["account_id"])
    op.create_index(op.f("ix_finance_investment_transactions_security_id"),
                    "finance_investment_transactions", ["security_id"])
    op.create_index(op.f("ix_finance_investment_transactions_date"),
                    "finance_investment_transactions", ["date"])


def downgrade() -> None:
    op.drop_table("finance_investment_transactions")
    op.drop_table("finance_liabilities")
    op.drop_table("finance_recurring")
