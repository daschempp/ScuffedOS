"""SQLAlchemy models — the durable shape of every domain the app owns.

Conventions:
- Real UTC timestamps on every row; display strings derive on read (app/display.py).
- `owner` stamped everywhere (single-user today, schema-ready for more).
- Python-side defaults (not server defaults) so SQLite and Postgres behave
  identically under tests.
- Collection-ish fields the UI patches wholesale (subtasks, labels, file
  metadata) live in JSON (JSONB on Postgres). Reminders graduated to the
  queryable `task_reminders` table in M3 (the scheduler queries them);
  `files` stays JSON metadata mirroring real bytes on disk.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, JSON, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

JSONField = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task(Base):
    """THE task model (review D1) — the rich TasksScreen shape, server-side."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    label: Mapped[str] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(default=False)
    # "group" is too overloaded a word in SQL; the API field is still `group`.
    group: Mapped[str] = mapped_column("bucket", String(16), default="Today")
    deadline: Mapped[date | None]
    prio: Mapped[str] = mapped_column(String(8), default="med")
    list_name: Mapped[str] = mapped_column("list", String(64), default="Personal")
    description: Mapped[str] = mapped_column(Text, default="")
    subtasks: Mapped[list] = mapped_column(JSONField, default=list)
    labels: Mapped[list] = mapped_column(JSONField, default=list)
    # File *metadata*; the bytes live under settings.attachments_dir (M3).
    files: Mapped[list] = mapped_column(JSONField, default=list)
    # RFC 5545 RRULE (e.g. "FREQ=WEEKLY;BYDAY=MO"); completing a recurring
    # task spawns the next occurrence and strips the rule from the done row.
    recurrence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskReminder(Base):
    """A reminder that fires (M3) — concrete datetime, queried by the scheduler.

    Replaces the old free-text strings in tasks.reminders JSON; a string
    can't fire. `label` keeps the human phrasing for the chip in the UI.
    """

    __tablename__ = "task_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    label: Mapped[str] = mapped_column(Text, default="")
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    """A calendar event. Recurring events store the series here; occurrences
    are expanded on read (app/recurrence.py), never materialized."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    title: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tint: Mapped[str] = mapped_column(String(16), default="sky")
    location: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    recurrence: Mapped[str | None] = mapped_column(Text)
    # ISO datetimes (UTC) of occurrence starts deleted from a recurring series.
    exdates: Mapped[list] = mapped_column(JSONField, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Habit(Base):
    """A recurring habit definition; completion truth lives in HabitCompletion."""

    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    name: Mapped[str] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(32), default="check")
    tint: Mapped[str] = mapped_column(String(16), default="green")
    # Weekday ints the habit is expected (Mon=0 … Sun=6); misses/streaks are
    # judged against this, so "weekdays only" habits don't break on Saturday.
    schedule: Mapped[list] = mapped_column(JSONField, default=lambda: [0, 1, 2, 3, 4, 5, 6])
    # Auto-complete source: "water" (nutrition water goal, M3) or "workout"
    # (fitness sync, fires in M4). Null = manual only.
    link: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HabitCompletion(Base):
    """One row per habit per completed day — the source of truth for streaks."""

    __tablename__ = "habit_completions"
    __table_args__ = (UniqueConstraint("habit_id", "date", name="uq_habit_completions_habit_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(
        ForeignKey("habits.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    # "manual" toggles always win; "auto" rows (water goal, workouts) can be
    # retracted by the linking domain without clobbering a user's tap.
    source: Mapped[str] = mapped_column(String(8), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Meal(Base):
    """A logged meal. Macros are stored as filed (from food DB, LLM estimate,
    or manual entry); day totals are computed on read, never stored."""

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    slot: Mapped[str] = mapped_column(String(16), default="Snack")
    name: Mapped[str] = mapped_column(Text)
    kcal: Mapped[int] = mapped_column(default=0)
    protein_g: Mapped[float] = mapped_column(default=0.0)
    carbs_g: Mapped[float] = mapped_column(default=0.0)
    fat_g: Mapped[float] = mapped_column(default=0.0)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WaterDay(Base):
    """Per-day water counter ("Add a cup")."""

    __tablename__ = "water_days"
    __table_args__ = (UniqueConstraint("owner", "date", name="uq_water_days_owner_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    cups: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class NutritionTargets(Base):
    """Per-owner macro + water goals (one row, get-or-create)."""

    __tablename__ = "nutrition_targets"
    __table_args__ = (UniqueConstraint("owner", name="uq_nutrition_targets_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    calories: Mapped[int] = mapped_column(default=2100)
    protein_g: Mapped[int] = mapped_column(default=160)
    carbs_g: Mapped[int] = mapped_column(default=210)
    fat_g: Mapped[int] = mapped_column(default=70)
    water_cups: Mapped[int] = mapped_column(default=8)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Memory(Base):
    """A second-brain note. The canonical, user-visible memory record."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    text: Mapped[str] = mapped_column(Text)
    src: Mapped[str] = mapped_column(String(32), default="note")
    tags: Mapped[list] = mapped_column(JSONField, default=list)
    color: Mapped[str] = mapped_column(String(16), default="green")
    # Link to the Mem0 vector record this row mirrors (M2) — null for rows
    # that only exist in the canonical table.
    mem0_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Conversation(Base):
    """An assistant chat session — persists across backend restarts (M2 reads these)."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    # Action cards the assistant attached to this message, if any.
    actions: Mapped[list | None] = mapped_column(JSONField)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderAccount(Base):
    """OAuth credentials + incremental-sync cursor. One row per (owner, provider).
    Tokens live server-side only, never serialized to the client (M4)."""

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint("owner", "provider", name="uq_provider_accounts_owner_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)        # 'whoop'
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str] = mapped_column(Text, default="")                # space-delimited
    provider_user_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="connected")  # 'connected' | 'needs_reauth'
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailySnapshot(Base):
    """Per-day physiological summary; one row per (owner, source, day) — the upsert key.
    No source_id: a day folds together several provider records. Deltas + weekly
    trend derive on read."""

    __tablename__ = "daily_snapshots"
    __table_args__ = (
        UniqueConstraint("owner", "source", "day", name="uq_daily_snapshots_owner_source_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)          # 'whoop'|'oura'|'apple_health'|'manual'
    day: Mapped[date] = mapped_column(Date, index=True)
    recovery_pct: Mapped[int | None]
    day_strain: Mapped[float | None]
    sleep_quality_pct: Mapped[int | None]
    hrv_ms: Mapped[float | None]
    resting_hr: Mapped[int | None]
    respiratory_rate: Mapped[float | None]
    sleep_hours: Mapped[float | None]
    metrics_json: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Workout(Base):
    """Synced + manual sessions. Unique on (source, source_id) WHERE source_id IS NOT NULL —
    synced rows upsert idempotently; manual rows (null source_id) never collide."""

    __tablename__ = "workouts"
    __table_args__ = (
        Index("uq_workouts_source_source_id", "source", "source_id",
              unique=True, sqlite_where=text("source_id IS NOT NULL"),
              postgresql_where=text("source_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)          # 'whoop' | 'manual'
    source_id: Mapped[str | None] = mapped_column(String(64))            # provider id; null for manual
    name: Mapped[str] = mapped_column(Text)
    sport: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_min: Mapped[int] = mapped_column(default=0)
    strain: Mapped[float | None]
    calories: Mapped[int | None]                                        # kJ->kcal converted on map
    avg_hr: Mapped[int | None]
    max_hr: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Email(Base):
    """A synced email (M5). Keyed (owner, source, source_id) = ('google', gmail id)
    so re-sync upserts idempotently. Triage output (category + summary_json) is
    written on sync; NO body column — bodies are privacy-sensitive and fetched
    on demand via EmailProvider.get_message, never stored."""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_emails_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'google'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # gmail message id
    thread_id: Mapped[str] = mapped_column(String(128), default="")
    from_name: Mapped[str] = mapped_column(Text, default="")
    from_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    unread: Mapped[bool] = mapped_column(default=False)
    starred: Mapped[bool] = mapped_column(default=False)
    label_ids: Mapped[list] = mapped_column(JSONField, default=list)     # Gmail label ids, sync-authoritative
    category: Mapped[str | None] = mapped_column(String(16))            # 'needs_reply' | 'fyi' | None
    summary_json: Mapped[list | None] = mapped_column(JSONField)        # list[str] bullets, or None
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MoodleCourse(Base):
    """A synced Moodle course (M6). Keyed (owner, source, source_id) =
    ('moodle', course id) so re-sync upserts idempotently. Read-only this
    slice — no course content or files stored, only the enrolment summary."""

    __tablename__ = "moodle_courses"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_moodle_courses_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # course id
    shortname: Mapped[str] = mapped_column(String(255), default="")
    fullname: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float | None] = mapped_column(Float)              # 0..100 or None
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MoodleDeadline(Base):
    """A synced Moodle deadline / calendar action event (M6). Keyed
    (owner, source, source_id) = ('moodle', calendar event id). Projected
    read-only into the Calendar/Tasks surfaces at read time (never copied
    into the tasks/events tables)."""

    __tablename__ = "moodle_deadlines"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_moodle_deadlines_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # calendar event id
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    module_name: Mapped[str] = mapped_column(String(32), default="")   # 'assign'|'quiz'|...
    event_type: Mapped[str] = mapped_column(String(32), default="")    # 'due'|'close'|...
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MoodleAssignment(Base):
    """A synced Moodle assignment + submission status (M6). Keyed
    (owner, source, source_id) = ('moodle', assign id). Projected read-only
    into the Tasks surface at read time via its due date."""

    __tablename__ = "moodle_assignments"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_moodle_assignments_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # assign id
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    cmid: Mapped[str] = mapped_column(String(32), default="")
    name: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grade_max: Mapped[float | None] = mapped_column(Float)
    submission_status: Mapped[str] = mapped_column(String(16), default="none")
    grading_status: Mapped[str] = mapped_column(String(32), default="")
    graded: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MoodleGrade(Base):
    """A synced Moodle grade item (M6). Keyed (owner, source, source_id) =
    ('moodle', grade item id). Display string kept alongside raw values."""

    __tablename__ = "moodle_grades"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_moodle_grades_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # grade item id
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    item_name: Mapped[str] = mapped_column(Text, default="")
    item_type: Mapped[str] = mapped_column(String(16), default="")     # 'mod'|'course'|'category'
    grade_formatted: Mapped[str] = mapped_column(String(64), default="-")
    grade_raw: Mapped[float | None] = mapped_column(Float)
    grade_min: Mapped[float | None] = mapped_column(Float)
    grade_max: Mapped[float | None] = mapped_column(Float)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MoodleAnnouncement(Base):
    """A synced Moodle news-forum announcement (M6). Keyed
    (owner, source, source_id) = ('moodle', discussion id). Only a short
    HTML summary is stored (stripped for display); no full post bodies.

    `created_at` is nullable: the provider's `_epoch(disc.get("created"))`
    can yield None if a discussion lacks a `created` field, and a NOT NULL
    column would reject that row at sync time."""

    __tablename__ = "moodle_announcements"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_moodle_announcements_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # discussion id
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    forum_id: Mapped[str] = mapped_column(String(32), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_html: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MoodleNotification(Base):
    """A synced Moodle popup notification (M6). Keyed
    (owner, source, source_id) = ('moodle', notification id). Message text
    is stripped of HTML for display."""

    __tablename__ = "moodle_notifications"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_moodle_notifications_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # notification id
    subject: Mapped[str] = mapped_column(Text, default="")
    full_message: Mapped[str] = mapped_column(Text, default="")
    context_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---- Finance / Plaid (M7) -------------------------------------------------
class FinanceItem(Base):
    """One linked Plaid Item (a bank/Coinbase connection). access_token is
    server-side only, never serialized. cursor is the /transactions/sync
    cursor; products drives the per-Item sync branch (transactions/investments)."""

    __tablename__ = "finance_items"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_items_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid item_id
    access_token: Mapped[str | None] = mapped_column(Text)             # server-side only
    institution_id: Mapped[str] = mapped_column(String(64), default="")
    institution_name: Mapped[str] = mapped_column(String(255), default="")
    products: Mapped[list] = mapped_column(JSONField, default=list)    # ['transactions']/['investments']
    status: Mapped[str] = mapped_column(String(16), default="active")  # 'active' | 'needs_reauth'
    cursor: Mapped[str | None] = mapped_column(Text)                   # /transactions/sync cursor
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceAccount(Base):
    """A Plaid account within an Item. type/subtype drive net-worth bucketing."""

    __tablename__ = "finance_accounts"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_accounts_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid account_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    official_name: Mapped[str | None] = mapped_column(String(255))
    mask: Mapped[str | None] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(32), default="")          # depository|investment|credit|loan
    subtype: Mapped[str | None] = mapped_column(String(48))
    current_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    available_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceTransaction(Base):
    """A Plaid transaction. amount sign is Plaid's: + = outflow / money leaving."""

    __tablename__ = "finance_transactions"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_transactions_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid transaction_id
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    date: Mapped[date] = mapped_column(Date, index=True)
    authorized_date: Mapped[date | None] = mapped_column(Date)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    category_primary: Mapped[str] = mapped_column(String(64), default="")
    category_detailed: Mapped[str] = mapped_column(String(128), default="")
    payment_channel: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceSecurity(Base):
    """A security referenced by holdings. type='cryptocurrency' for Coinbase coins."""

    __tablename__ = "finance_securities"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_securities_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid security_id
    name: Mapped[str] = mapped_column(String(255), default="")
    ticker_symbol: Mapped[str | None] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(48), default="")          # equity|etf|cryptocurrency|...
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_cash_equivalent: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceHolding(Base):
    """An investment position (account x security). Keyed (owner, account_id,
    security_id) — Plaid gives holdings no id of their own."""

    __tablename__ = "finance_holdings"
    __table_args__ = (
        UniqueConstraint("owner", "account_id", "security_id",
                         name="uq_finance_holdings_owner_account_security"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), default="plaid", index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(128), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    institution_value: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    institution_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceBudget(Base):
    """A local, user-editable monthly budget limit per category. NOT from Plaid
    — spend is derived from finance_transactions at read time."""

    __tablename__ = "finance_budgets"
    __table_args__ = (
        UniqueConstraint("owner", "category", "month",
                         name="uq_finance_budgets_owner_category_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    category: Mapped[str] = mapped_column(String(48), index=True)      # a fixed bucket name
    month: Mapped[str] = mapped_column(String(7), index=True)          # 'YYYY-MM'
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceRecurring(Base):
    """A Plaid recurring stream (/transactions/recurring/get). stream_type splits
    inflow (income) vs outflow (subscriptions/bills). NOT a bank write source."""

    __tablename__ = "finance_recurring"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_recurring_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid stream_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    stream_type: Mapped[str] = mapped_column(String(16), default="outflow")  # inflow|outflow
    description: Mapped[str] = mapped_column(String(255), default="")
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    category_primary: Mapped[str] = mapped_column(String(64), default="")
    category_detailed: Mapped[str] = mapped_column(String(128), default="")
    average_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    last_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    frequency: Mapped[str] = mapped_column(String(24), default="")
    first_date: Mapped[date | None] = mapped_column(Date)
    last_date: Mapped[date | None] = mapped_column(Date)
    predicted_next_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="")
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceLiability(Base):
    """Loan/credit-card terms (/liabilities/get). Keyed by the account it describes."""

    __tablename__ = "finance_liabilities"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_liabilities_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # = account_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    liability_type: Mapped[str] = mapped_column(String(16), default="credit")  # credit|mortgage|student
    last_statement_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    minimum_payment: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    next_payment_due_date: Mapped[date | None] = mapped_column(Date)
    last_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    last_payment_date: Mapped[date | None] = mapped_column(Date)
    apr_percentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceInvestmentTransaction(Base):
    """An investment buy/sell/dividend/fee (/investments/transactions/get)."""

    __tablename__ = "finance_investment_transactions"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_investment_transactions_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # investment_transaction_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    type: Mapped[str] = mapped_column(String(32), default="")
    subtype: Mapped[str] = mapped_column(String(48), default="")
    name: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    fees: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    date: Mapped[date] = mapped_column(Date, index=True)
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---- People / CRM (M10 s1) -------------------------------------------------
class Person(Base):
    """A contact (M10 s1). `source='macos_contacts'` rows are synced one-way from
    the local AddressBook and keyed (owner, source, source_id) for idempotent
    upsert; `source='manual'` rows are user-created. source_id is the already-
    hashed, namespaced id from the reader (contract: Source ID namespacing) — the
    model just stores it.

    Ownership split (contract: Sync-owned vs CRM-native): sync writes ONLY the
    sync-owned identity fields (names, org, phones/emails, photo_key/has_photo,
    meta); the CRM-native block (relationship .. last_contacted_at) is
    ScuffedOS-owned and never touched by sync. `removed_from_source_at`
    soft-deletes a contact that vanished from AddressBook (preserving its CRM
    data) and is cleared on any re-upsert (resurrection).

    Photos: `photo_key` is the opaque, RELATIVE key persisted here (contract:
    Photo storage); the extracted bytes live on the backend host's App Support
    filesystem, never in this table."""

    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_people_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'macos_contacts' | 'manual'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # hashed, namespaced (reader)
    display_name: Mapped[str] = mapped_column(Text, default="")
    first_name: Mapped[str] = mapped_column(Text, default="")
    last_name: Mapped[str] = mapped_column(Text, default="")
    nickname: Mapped[str] = mapped_column(Text, default="")
    organization: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str] = mapped_column(Text, default="")
    phones: Mapped[list] = mapped_column(JSONField, default=list)      # [{value, label, normalized}]
    emails: Mapped[list] = mapped_column(JSONField, default=list)      # [{value, label, normalized}]
    photo_key: Mapped[str | None] = mapped_column(Text)               # opaque, RELATIVE (contract)
    has_photo: Mapped[bool] = mapped_column(default=False)
    # ---- CRM-native (ScuffedOS-owned; sync NEVER writes these) ----
    relationship: Mapped[str | None] = mapped_column(String(32))
    relationship_strength: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(default=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_from_source_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PersonHandle(Base):
    """Normalized handle -> person index for resolve_handle (M10 s1). One row per
    (person_id, kind, value); `value` is the canonical key from app.identity and
    `kind` is 'phone' | 'email' | 'short'. Kept across soft-delete so historical
    messages still resolve to a removed contact. A single handle may map to many
    people (shared family/household numbers) -> resolve_handle returns a list."""

    __tablename__ = "person_handle"
    __table_args__ = (
        UniqueConstraint("person_id", "kind", "value",
                         name="uq_person_handle_person_kind_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))               # 'phone' | 'email' | 'short'
    value: Mapped[str] = mapped_column(String(320), index=True)  # normalized key
    possible: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContactsSyncState(Base):
    """One row per owner: the Contacts connector's consent + lifecycle record
    (contract: Consent & lifecycle). `enabled` is APP CONSENT and defaults OFF —
    no probing, no background sync, and no reads happen until the user explicitly
    connects. `access` (FDA state) is tracked SEPARATELY from consent.
    `normalization_region` is the region persisted at enable/first-sync used to
    canonicalize handles; a later system-locale change does NOT retroactively
    alter it (contract: Region persistence)."""

    __tablename__ = "contacts_sync_state"
    __table_args__ = (
        UniqueConstraint("owner", name="uq_contacts_sync_state_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))              # unique via constraint above
    # app consent (default OFF); status/access are independent
    enabled: Mapped[bool] = mapped_column(default=False)
    # 'disabled' | 'access_denied' | 'ready' | 'syncing' | 'stale' | 'error'
    status: Mapped[str] = mapped_column(String(16), default="disabled")
    # 'granted' | 'denied' | 'unknown'
    access: Mapped[str] = mapped_column(String(16), default="unknown")
    normalization_region: Mapped[str | None] = mapped_column(String(8))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
