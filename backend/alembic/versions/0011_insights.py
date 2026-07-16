"""Insights (fitness slice 1): derived coaching cards, one row per
(owner, domain, day, code).

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("tone", sa.String(length=12), nullable=False),
        sa.Column("headline", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("signals_json", JSONField, nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "domain", "day", "code", name="uq_insights_owner_domain_day_code"),
    )
    op.create_index(op.f("ix_insights_owner"), "insights", ["owner"])
    op.create_index(op.f("ix_insights_day"), "insights", ["day"])
    op.create_index(op.f("ix_insights_domain"), "insights", ["domain"])


def downgrade() -> None:
    op.drop_table("insights")
