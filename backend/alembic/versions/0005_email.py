"""Email domain (M5): the synced Gmail inbox.

- emails: one row per (owner, source, source_id) = ('google', gmail message id);
  re-sync upserts idempotently. Triage output (category + summary_json) is
  written on sync. NO body column — message bodies are privacy-sensitive and
  fetched on demand, never stored.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("from_name", sa.Text(), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=True),
        sa.Column("summary_json", JSONField, nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_emails_owner_source_source_id"),
    )
    op.create_index(op.f("ix_emails_owner"), "emails", ["owner"])
    op.create_index(op.f("ix_emails_source"), "emails", ["source"])
    op.create_index(op.f("ix_emails_source_id"), "emails", ["source_id"])
    op.create_index(op.f("ix_emails_received_at"), "emails", ["received_at"])


def downgrade() -> None:
    op.drop_table("emails")
