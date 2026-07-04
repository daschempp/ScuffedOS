"""School domain (M6): synced Moodle courses / deadlines / assignments /
grades / announcements / notifications.

Six tables, each keyed (owner, source, source_id) = ('moodle', <id>) so
re-sync upserts idempotently. Read-only this slice — no course content, no
file bytes, no full post bodies stored. Deadlines/assignments are projected
read-only into the Calendar/Tasks surfaces at read time, never copied into
the tasks/events tables.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "moodle_courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("shortname", sa.String(length=255), nullable=False),
        sa.Column("fullname", sa.Text(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_moodle_courses_owner_source_source_id"),
    )
    op.create_index(op.f("ix_moodle_courses_owner"), "moodle_courses", ["owner"])
    op.create_index(op.f("ix_moodle_courses_source"), "moodle_courses", ["source"])
    op.create_index(op.f("ix_moodle_courses_source_id"), "moodle_courses", ["source_id"])

    op.create_table(
        "moodle_deadlines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("course_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("module_name", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overdue", sa.Boolean(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_moodle_deadlines_owner_source_source_id"),
    )
    op.create_index(op.f("ix_moodle_deadlines_owner"), "moodle_deadlines", ["owner"])
    op.create_index(op.f("ix_moodle_deadlines_source"), "moodle_deadlines", ["source"])
    op.create_index(op.f("ix_moodle_deadlines_source_id"), "moodle_deadlines", ["source_id"])
    op.create_index(op.f("ix_moodle_deadlines_course_id"), "moodle_deadlines", ["course_id"])
    op.create_index(op.f("ix_moodle_deadlines_due_at"), "moodle_deadlines", ["due_at"])

    op.create_table(
        "moodle_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("course_id", sa.String(length=32), nullable=False),
        sa.Column("cmid", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grade_max", sa.Float(), nullable=True),
        sa.Column("submission_status", sa.String(length=16), nullable=False),
        sa.Column("grading_status", sa.String(length=32), nullable=False),
        sa.Column("graded", sa.Boolean(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_moodle_assignments_owner_source_source_id"),
    )
    op.create_index(op.f("ix_moodle_assignments_owner"), "moodle_assignments", ["owner"])
    op.create_index(op.f("ix_moodle_assignments_source"), "moodle_assignments", ["source"])
    op.create_index(op.f("ix_moodle_assignments_source_id"), "moodle_assignments", ["source_id"])
    op.create_index(op.f("ix_moodle_assignments_course_id"), "moodle_assignments", ["course_id"])

    op.create_table(
        "moodle_grades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("course_id", sa.String(length=32), nullable=False),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("grade_formatted", sa.String(length=64), nullable=False),
        sa.Column("grade_raw", sa.Float(), nullable=True),
        sa.Column("grade_min", sa.Float(), nullable=True),
        sa.Column("grade_max", sa.Float(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_moodle_grades_owner_source_source_id"),
    )
    op.create_index(op.f("ix_moodle_grades_owner"), "moodle_grades", ["owner"])
    op.create_index(op.f("ix_moodle_grades_source"), "moodle_grades", ["source"])
    op.create_index(op.f("ix_moodle_grades_source_id"), "moodle_grades", ["source_id"])
    op.create_index(op.f("ix_moodle_grades_course_id"), "moodle_grades", ["course_id"])

    op.create_table(
        "moodle_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("course_id", sa.String(length=32), nullable=False),
        sa.Column("forum_id", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        # Nullable: the provider's _epoch(disc.get("created")) can yield None
        # if a discussion lacks a `created` field (Task 7 review fix).
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_html", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_moodle_announcements_owner_source_source_id"),
    )
    op.create_index(op.f("ix_moodle_announcements_owner"), "moodle_announcements", ["owner"])
    op.create_index(op.f("ix_moodle_announcements_source"), "moodle_announcements", ["source"])
    op.create_index(op.f("ix_moodle_announcements_source_id"), "moodle_announcements", ["source_id"])
    op.create_index(op.f("ix_moodle_announcements_course_id"), "moodle_announcements", ["course_id"])

    op.create_table(
        "moodle_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("full_message", sa.Text(), nullable=False),
        sa.Column("context_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_moodle_notifications_owner_source_source_id"),
    )
    op.create_index(op.f("ix_moodle_notifications_owner"), "moodle_notifications", ["owner"])
    op.create_index(op.f("ix_moodle_notifications_source"), "moodle_notifications", ["source"])
    op.create_index(op.f("ix_moodle_notifications_source_id"), "moodle_notifications", ["source_id"])


def downgrade() -> None:
    op.drop_table("moodle_notifications")
    op.drop_table("moodle_announcements")
    op.drop_table("moodle_grades")
    op.drop_table("moodle_assignments")
    op.drop_table("moodle_deadlines")
    op.drop_table("moodle_courses")
