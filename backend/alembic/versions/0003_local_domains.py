"""Local domains (M3): events, habits, nutrition, firing reminders, recurrence.

- New tables: events, habits, habit_completions, meals, water_days,
  nutrition_targets, task_reminders.
- tasks gains `recurrence` (RRULE string); tasks.reminders (free-text JSON
  strings) is dropped — reminders that fire need concrete datetimes, so they
  graduated to task_reminders. The old demo strings are not migrated.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence", sa.Text(), nullable=True))
    op.drop_column("tasks", "reminders")

    op.create_table(
        "task_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_task_reminders_owner"), "task_reminders", ["owner"])
    op.create_index(op.f("ix_task_reminders_task_id"), "task_reminders", ["task_id"])
    op.create_index(op.f("ix_task_reminders_remind_at"), "task_reminders", ["remind_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tint", sa.String(length=16), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("exdates", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_events_owner"), "events", ["owner"])
    op.create_index(op.f("ix_events_start_at"), "events", ["start_at"])

    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(length=32), nullable=False),
        sa.Column("tint", sa.String(length=16), nullable=False),
        sa.Column("schedule", JSONField, nullable=False),
        sa.Column("link", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_habits_owner"), "habits", ["owner"])

    op.create_table(
        "habit_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "habit_id",
            sa.Integer(),
            sa.ForeignKey("habits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("habit_id", "date", name="uq_habit_completions_habit_date"),
    )
    op.create_index(op.f("ix_habit_completions_habit_id"), "habit_completions", ["habit_id"])
    op.create_index(op.f("ix_habit_completions_date"), "habit_completions", ["date"])

    op.create_table(
        "meals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kcal", sa.Integer(), nullable=False),
        # Matches Mapped[float] -> Float() in this SQLAlchemy version.
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_meals_owner"), "meals", ["owner"])
    op.create_index(op.f("ix_meals_date"), "meals", ["date"])

    op.create_table(
        "water_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("cups", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "date", name="uq_water_days_owner_date"),
    )
    op.create_index(op.f("ix_water_days_owner"), "water_days", ["owner"])
    op.create_index(op.f("ix_water_days_date"), "water_days", ["date"])

    op.create_table(
        "nutrition_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Integer(), nullable=False),
        sa.Column("carbs_g", sa.Integer(), nullable=False),
        sa.Column("fat_g", sa.Integer(), nullable=False),
        sa.Column("water_cups", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", name="uq_nutrition_targets_owner"),
    )
    op.create_index(op.f("ix_nutrition_targets_owner"), "nutrition_targets", ["owner"])


def downgrade() -> None:
    op.drop_table("nutrition_targets")
    op.drop_table("water_days")
    op.drop_table("meals")
    op.drop_table("habit_completions")
    op.drop_table("habits")
    op.drop_table("events")
    op.drop_table("task_reminders")
    op.add_column("tasks", sa.Column("reminders", JSONField, nullable=True))
    op.drop_column("tasks", "recurrence")
