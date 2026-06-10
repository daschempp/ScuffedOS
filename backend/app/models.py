"""SQLAlchemy models — the durable shape of every domain the app owns.

Conventions:
- Real UTC timestamps on every row; display strings derive on read (app/display.py).
- `owner` stamped everywhere (single-user today, schema-ready for more).
- Python-side defaults (not server defaults) so SQLite and Postgres behave
  identically under tests.
- Collection-ish fields the UI patches wholesale (subtasks, labels, reminders,
  file metadata) live in JSON (JSONB on Postgres). Reminders graduate to a
  queryable table in M3 when they start firing; files likewise when real
  uploads land.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
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
    reminders: Mapped[list] = mapped_column(JSONField, default=list)
    files: Mapped[list] = mapped_column(JSONField, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
