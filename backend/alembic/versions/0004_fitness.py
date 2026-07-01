"""Fitness domain (M4): provider OAuth accounts, daily snapshots, workouts.

- provider_accounts: one row per (owner, provider); server-side OAuth tokens
  + the incremental-sync cursor (last_sync_at).
- daily_snapshots: per-day physiological summary, keyed (owner, source, day);
  no source_id — a day folds together several provider records.
- workouts: synced + manual sessions; partial-unique on (source, source_id)
  WHERE source_id IS NOT NULL so synced rows upsert idempotently while manual
  rows (null source_id) never collide.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "provider_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner", "provider", name="uq_provider_accounts_owner_provider"),
    )
    op.create_index(op.f("ix_provider_accounts_owner"), "provider_accounts", ["owner"])
    op.create_index(op.f("ix_provider_accounts_provider"), "provider_accounts", ["provider"])

    op.create_table(
        "daily_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("recovery_pct", sa.Integer(), nullable=True),
        sa.Column("day_strain", sa.Float(), nullable=True),
        sa.Column("sleep_quality_pct", sa.Integer(), nullable=True),
        sa.Column("hrv_ms", sa.Float(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("respiratory_rate", sa.Float(), nullable=True),
        sa.Column("sleep_hours", sa.Float(), nullable=True),
        sa.Column("metrics_json", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "day", name="uq_daily_snapshots_owner_source_day"),
    )
    op.create_index(op.f("ix_daily_snapshots_owner"), "daily_snapshots", ["owner"])
    op.create_index(op.f("ix_daily_snapshots_source"), "daily_snapshots", ["source"])
    op.create_index(op.f("ix_daily_snapshots_day"), "daily_snapshots", ["day"])

    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sport", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("strain", sa.Float(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_workouts_owner"), "workouts", ["owner"])
    op.create_index(op.f("ix_workouts_source"), "workouts", ["source"])
    op.create_index(op.f("ix_workouts_started_at"), "workouts", ["started_at"])
    op.create_index(
        "uq_workouts_source_source_id",
        "workouts",
        ["source", "source_id"],
        unique=True,
        sqlite_where=sa.text("source_id IS NOT NULL"),
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("workouts")
    op.drop_table("daily_snapshots")
    op.drop_table("provider_accounts")
