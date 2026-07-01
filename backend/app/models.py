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

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, JSON, String, Text,
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
    category: Mapped[str | None] = mapped_column(String(16))            # 'needs_reply' | 'fyi' | None
    summary_json: Mapped[list | None] = mapped_column(JSONField)        # list[str] bullets, or None
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
