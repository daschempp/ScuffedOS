"""Durable data store — SQLAlchemy over Postgres behind the same `Store` facade.

Routers keep calling plain methods that take and return API-shaped dicts; all
ORM/session detail stays in here. The engine is built lazily from settings on
first use so importing the app never requires a database; tests call
`store.configure(...)` to point the same singleton at a throwaway engine.

Patch semantics (review R7): updates receive only the keys the client sent
(`exclude_unset`). An explicit null clears nullable fields (deadline); nulls on
non-nullable fields are ignored rather than erroring.
"""
from __future__ import annotations

import functools
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from . import recurrence
from .db import make_engine, make_session_factory
from .display import (
    aware_utc,
    clock,
    email_when_display,
    event_when_display,
    meal_time_display,
    relative_when,
    reminder_label,
    task_due_display,
)
from .models import (
    Conversation,
    ConversationMessage,
    DailySnapshot,
    Email,
    Event,
    Habit,
    HabitCompletion,
    Meal,
    Memory,
    NutritionTargets,
    ProviderAccount,
    Task,
    TaskReminder,
    WaterDay,
    Workout,
    utcnow,
)
from .providers.base import NormalizedEmail, NormalizedSnapshot, NormalizedWorkout, Tokens

_TASK_FIELDS = {
    "label", "done", "group", "deadline", "prio", "list", "description",
    "subtasks", "labels", "files", "recurrence",
}
_TASK_NULLABLE = {"deadline", "recurrence"}
_MEMORY_FIELDS = {"text", "src", "tags", "color"}
_EVENT_FIELDS = {"title", "start", "end", "tint", "location", "description", "recurrence"}
_EVENT_NULLABLE = {"recurrence"}
_HABIT_FIELDS = {"name", "icon", "tint", "schedule", "link"}
_HABIT_NULLABLE = {"link"}
_MEAL_FIELDS = {"name", "slot", "kcal", "protein_g", "carbs_g", "fat_g"}
_TARGET_FIELDS = {"calories", "protein_g", "carbs_g", "fat_g", "water_cups"}
_SNAPSHOT_FIELDS = (
    "recovery_pct", "day_strain", "sleep_quality_pct", "hrv_ms",
    "resting_hr", "respiratory_rate", "sleep_hours",
)

# Meal chip icon/tint by slot — the prototype's mapping, derived on read.
_SLOT_CHIP = {
    "Breakfast": ("egg", "honey"),
    "Lunch": ("sandwich", "clay"),
    "Snack": ("apple", "green"),
    "Dinner": ("utensils", "plum"),
}

# Workout chip icon/tint by sport — derived on read (mirrors _SLOT_CHIP).
# Every icon name here MUST exist in frontend/src/lib/Icon.jsx's ICONS map or it
# renders blank. 'running' uses 'activity' (Lucide has no plain run glyph);
# 'swimming' uses 'waves', which Task 27 adds to the Icon registry.
_SPORT_CHIP = {
    "running": ("activity", "green"),
    "cycling": ("bike", "sky"),
    "strength": ("dumbbell", "clay"),
    "weightlifting": ("dumbbell", "clay"),
    "swimming": ("waves", "sky"),
    "yoga": ("flower-2", "plum"),
    "walking": ("footprints", "honey"),
}
_WORKOUT_CHIP_DEFAULT = ("activity", "clay")

_WORKOUT_FIELDS = {
    "name", "sport", "started_at", "duration_min", "strain",
    "calories", "avg_hr", "max_hr",
}

_EMAIL_FIELDS = (
    "thread_id", "from_name", "from_email", "subject", "snippet",
    "received_at", "unread",
)

# The four vitals shown under the rings — fixed layout; values + deltas
# derive on read from the day's snapshot (None when absent).
_VITALS_SPEC = (
    ("hrv", "hrv_ms", "HRV", "ms", "activity", "green"),
    ("resting_hr", "resting_hr", "Resting HR", "bpm", "heart", "clay"),
    ("respiratory_rate", "respiratory_rate", "Respiratory", "rpm", "wind", "sky"),
    ("sleep_hours", "sleep_hours", "Sleep", "h", "moon", "plum"),
)


def _local_today() -> date:
    return datetime.now().astimezone().date()


logger = logging.getLogger("scuffed_os.store")


def _to_utc(dt: datetime) -> datetime:
    """Normalize any incoming datetime to aware UTC before it's stored.

    SQLite silently drops tzinfo on write, so an aware *local* datetime
    (the assistant tools produce those) would be re-read as UTC wall clock
    — hours off. Converting at the store boundary keeps both dialects
    storing the same instant. Naive input is treated as already-UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _retry_integrity(fn):
    """Get-or-create / toggle upserts are select-then-insert; two concurrent
    writers (UI + assistant + the reminder tick) can race the unique
    constraint. One retry re-reads whatever the winner inserted."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except IntegrityError:
            return fn(*args, **kwargs)
    return wrapper


def _reminder_dict(r: TaskReminder) -> dict:
    remind_at = aware_utc(r.remind_at)
    return {
        "id": r.id,
        "task_id": r.task_id,
        "remind_at": remind_at,
        "label": r.label,
        "fired_at": aware_utc(r.fired_at),
        "display": reminder_label(remind_at, r.label),
    }


def _task_dict(t: Task, reminder_rows: list[TaskReminder] = ()) -> dict:
    due, late = task_due_display(t.deadline, t.done, t.completed_at)
    return {
        "id": t.id,
        "label": t.label,
        "done": t.done,
        "group": t.group,
        "deadline": t.deadline,
        "prio": t.prio,
        "list": t.list_name,
        "description": t.description,
        "subtasks": t.subtasks or [],
        "labels": t.labels or [],
        "reminders": [_reminder_dict(r) for r in reminder_rows],
        "files": t.files or [],
        "recurrence": t.recurrence,
        "recurrence_label": recurrence.describe(t.recurrence),
        "due": due,
        "late": late,
        "created_at": aware_utc(t.created_at),
        "updated_at": aware_utc(t.updated_at),
        "completed_at": aware_utc(t.completed_at),
    }


def _occurrence_dict(e: Event, start: datetime, end: datetime) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "start": start,
        "end": end,
        "tint": e.tint,
        "location": e.location,
        "description": e.description,
        "recurring": bool(e.recurrence),
        "recurrence_label": recurrence.describe(e.recurrence),
        "at": clock(start),
    }


def _event_occurrences(e: Event, window_start: datetime, window_end: datetime) -> list[dict]:
    """Concrete occurrences of one event row inside the window."""
    start_at, end_at = aware_utc(e.start_at), aware_utc(e.end_at)
    if not e.recurrence:
        if start_at < window_end and end_at > window_start:
            return [_occurrence_dict(e, start_at, end_at)]
        return []
    duration = end_at - start_at
    exdates = {_to_utc(datetime.fromisoformat(x)) for x in (e.exdates or [])}
    # Widen the left edge so an occurrence that *starts* before the window
    # but overlaps into it still shows up.
    try:
        starts = recurrence.expand_between(
            e.recurrence, start_at, window_start - duration, window_end, exdates=exdates
        )
    except Exception:
        # A bad stored rule (predating validation, or hand-edited) must not
        # poison every read of the whole calendar.
        logger.warning("could not expand recurrence for event %s: %r", e.id, e.recurrence)
        return []
    return [
        _occurrence_dict(e, occ, occ + duration)
        for occ in starts
        if occ < window_end and occ + duration > window_start
    ]


def _habit_dict(
    h: Habit, completed: set[date], week_start: date, today: date
) -> dict:
    """Habit + derived streaks and the requested week's Mon-first grid."""
    schedule = sorted(set(h.schedule or []))
    days = [week_start + timedelta(days=i) in completed for i in range(7)]

    def scheduled(d: date) -> bool:
        return d.weekday() in schedule if schedule else False

    # Current streak: walk back from today (an unfinished today doesn't
    # break it — start from yesterday if today is still open).
    streak = 0
    cursor = today
    if scheduled(cursor) and cursor not in completed:
        cursor -= timedelta(days=1)
    floor = min(completed) if completed else cursor
    while cursor >= floor:
        if scheduled(cursor):
            if cursor in completed:
                streak += 1
            else:
                break
        cursor -= timedelta(days=1)

    best = run = 0
    if completed:
        d = min(completed)
        while d <= today:
            if scheduled(d):
                run = run + 1 if d in completed else 0
                best = max(best, run)
            d += timedelta(days=1)
    best = max(best, streak)

    return {
        "id": h.id,
        "name": h.name,
        "icon": h.icon,
        "tint": h.tint,
        "schedule": schedule,
        "link": h.link,
        "streak": streak,
        "best_streak": best,
        "days": days,
    }


def _meal_dict(m: Meal) -> dict:
    icon, tint = _SLOT_CHIP.get(m.slot, ("utensils", "green"))
    logged_at = aware_utc(m.logged_at)
    return {
        "id": m.id,
        "date": m.date,
        "slot": m.slot,
        "name": m.name,
        "kcal": m.kcal,
        "protein_g": m.protein_g,
        "carbs_g": m.carbs_g,
        "fat_g": m.fat_g,
        "time": meal_time_display(m.slot, logged_at),
        "icon": icon,
        "tint": tint,
        "logged_at": logged_at,
    }


def _targets_dict(t: NutritionTargets) -> dict:
    return {
        "calories": t.calories,
        "protein_g": t.protein_g,
        "carbs_g": t.carbs_g,
        "fat_g": t.fat_g,
        "water_cups": t.water_cups,
    }


def _memory_dict(m: Memory) -> dict:
    return {
        "id": m.id,
        "text": m.text,
        "src": m.src,
        "tags": m.tags or [],
        "color": m.color,
        "when": relative_when(m.created_at),
        "created_at": aware_utc(m.created_at),
        "updated_at": aware_utc(m.updated_at),
        # Internal (filtered out of API responses by the response model).
        "mem0_id": m.mem0_id,
    }


def _message_dict(m: ConversationMessage) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "role": m.role,
        "content": m.content,
        "actions": m.actions,
        "created_at": aware_utc(m.created_at),
    }


_EMAIL_WRITE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
)


def _can_write_email(scopes: str) -> bool:
    """True iff the stored scope string grants BOTH gmail.modify and
    gmail.send (write capability for trash/flags/labels AND send/reply/
    forward). A readonly-only or partially-upgraded token is False."""
    return all(scope in scopes for scope in _EMAIL_WRITE_SCOPES)


def _provider_account_dict(p: ProviderAccount) -> dict:
    """Client-safe view of a provider account — NEVER includes tokens,
    scopes, or meta (those are server-side only; see /status). Exposes ONE
    derived boolean (can_write_email) computed from raw scopes so the
    frontend gate never sees the scope string itself."""
    return {
        "provider": p.provider,
        "status": p.status,
        "connected_at": aware_utc(p.connected_at),
        "last_sync_at": aware_utc(p.last_sync_at),
        "provider_user_id": p.provider_user_id,
        "can_write_email": _can_write_email(p.scopes or ""),
    }


def _snapshot_dict(d: DailySnapshot) -> dict:
    return {
        "source": d.source,
        "day": d.day,
        "recovery_pct": d.recovery_pct,
        "day_strain": d.day_strain,
        "sleep_quality_pct": d.sleep_quality_pct,
        "hrv_ms": d.hrv_ms,
        "resting_hr": d.resting_hr,
        "respiratory_rate": d.respiratory_rate,
        "sleep_hours": d.sleep_hours,
        "metrics_json": d.metrics_json or {},
        "created_at": aware_utc(d.created_at),
        "updated_at": aware_utc(d.updated_at),
    }


def _workout_chip(sport: str | None) -> tuple[str, str]:
    if not sport:
        return _WORKOUT_CHIP_DEFAULT
    return _SPORT_CHIP.get(sport.lower(), _WORKOUT_CHIP_DEFAULT)


def _workout_dict(w: Workout) -> dict:
    started = aware_utc(w.started_at)
    icon, tint = _workout_chip(w.sport)
    end = started + timedelta(minutes=w.duration_min or 0)
    return {
        "id": w.id,
        "source": w.source,
        "source_id": w.source_id,
        "name": w.name,
        "sport": w.sport,
        "started_at": started,
        "duration_min": w.duration_min,
        "strain": w.strain,
        "calories": w.calories,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "when": event_when_display(started, end),
        "icon": icon,
        "tint": tint,
    }


def _email_dict(e: Email) -> dict:
    received = aware_utc(e.received_at)
    return {
        "id": e.id,
        "source": e.source,
        "source_id": e.source_id,
        "thread_id": e.thread_id,
        "from_name": e.from_name,
        "from_email": e.from_email,
        "subject": e.subject,
        "snippet": e.snippet,
        "received_at": received,
        "unread": e.unread,
        "category": e.category,
        "summary": e.summary_json or [],
        "triaged_at": aware_utc(e.triaged_at),
        "when": email_when_display(received),
        "created_at": aware_utc(e.created_at),
        "updated_at": aware_utc(e.updated_at),
    }


def _apply_task_patch(task: Task, patch: dict) -> None:
    for key, value in patch.items():
        if key not in _TASK_FIELDS:
            continue
        if value is None and key not in _TASK_NULLABLE:
            continue
        if key == "list":
            task.list_name = value
        elif key == "done":
            if value and not task.done:
                task.completed_at = utcnow()
            elif not value:
                task.completed_at = None
            task.done = value
        else:
            setattr(task, key, value)


class Store:
    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory

    def configure(self, session_factory: sessionmaker | None) -> None:
        """Point the store at a different database (tests) or back to lazy (None)."""
        self._session_factory = session_factory

    def _session(self) -> Session:
        if self._session_factory is None:
            from .config import settings

            if not settings.database_url:
                raise RuntimeError(
                    "DATABASE_URL is not set. Put your Postgres connection string "
                    "(Supabase: the session-pooler URL) in backend/.env."
                )
            self._session_factory = make_session_factory(make_engine(settings.database_url))
        return self._session_factory()

    # ---- tasks ----
    @staticmethod
    def _task_reminders(s: Session, task_id: int) -> list[TaskReminder]:
        return list(s.scalars(
            select(TaskReminder)
            .where(TaskReminder.task_id == task_id)
            .order_by(TaskReminder.remind_at)
        ))

    def list_tasks(self) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(Task).order_by(Task.id.desc())).all()
            by_task: dict[int, list[TaskReminder]] = {}
            for r in s.scalars(select(TaskReminder).order_by(TaskReminder.remind_at)):
                by_task.setdefault(r.task_id, []).append(r)
            return [_task_dict(t, by_task.get(t.id, [])) for t in rows]

    def get_task(self, task_id: int) -> dict | None:
        with self._session() as s:
            task = s.get(Task, task_id)
            if task is None:
                return None
            return _task_dict(task, self._task_reminders(s, task_id))

    def create_task(self, data: dict) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            fields = {k: v for k, v in data.items() if k in _TASK_FIELDS and k != "list"}
            task = Task(owner=settings.owner, **fields)
            if "list" in data:
                task.list_name = data["list"]
            if task.done:
                task.completed_at = utcnow()
            s.add(task)
            s.flush()
            return _task_dict(task)

    def _spawn_next_occurrence(self, s: Session, task: Task) -> None:
        """Completing a recurring task rolls the series forward: a fresh row
        for the next occurrence, and the rule comes *off* the done row so the
        history stays plain and re-completing can't double-spawn."""
        rule = task.recurrence
        today = _local_today()
        anchor = task.deadline or today
        next_deadline = recurrence.next_date(rule, anchor, max(anchor, today))
        task.recurrence = None
        if next_deadline is None:  # rule ran out (UNTIL passed / COUNT spent)
            return
        # This completion consumed one slot of a COUNT=N budget — the clone
        # carries N-1, else re-anchoring would restart the count forever.
        clone_rule = recurrence.decrement_count(rule)
        if clone_rule is None:
            return
        clone = Task(
            owner=task.owner,
            label=task.label,
            group="Today" if next_deadline == today else "Upcoming",
            deadline=next_deadline,
            prio=task.prio,
            list_name=task.list_name,
            description=task.description,
            subtasks=[{**st, "done": False} for st in (task.subtasks or [])],
            labels=list(task.labels or []),
            recurrence=clone_rule,
        )
        s.add(clone)
        s.flush()
        if task.deadline is not None:
            shift = next_deadline - task.deadline
            for r in self._task_reminders(s, task.id):
                s.add(TaskReminder(
                    owner=r.owner,
                    task_id=clone.id,
                    remind_at=aware_utc(r.remind_at) + shift,
                    label=r.label,
                ))

    def update_task(self, task_id: int, patch: dict) -> dict | None:
        with self._session() as s, s.begin():
            task = s.get(Task, task_id)
            if task is None:
                return None
            completing = bool(patch.get("done")) and not task.done
            _apply_task_patch(task, patch)
            if completing and task.recurrence:
                self._spawn_next_occurrence(s, task)
            s.flush()
            return _task_dict(task, self._task_reminders(s, task_id))

    def delete_task(self, task_id: int) -> bool:
        with self._session() as s, s.begin():
            task = s.get(Task, task_id)
            if task is None:
                return False
            s.delete(task)  # reminders go with it (FK ON DELETE CASCADE)
            return True

    # ---- task reminders (M3 — these fire; see app/reminders.py) ----
    def list_task_reminders(self, task_id: int) -> list[dict] | None:
        with self._session() as s:
            if s.get(Task, task_id) is None:
                return None
            return [_reminder_dict(r) for r in self._task_reminders(s, task_id)]

    def add_task_reminder(self, task_id: int, remind_at: datetime, label: str = "") -> dict | None:
        from .config import settings

        with self._session() as s, s.begin():
            if s.get(Task, task_id) is None:
                return None
            row = TaskReminder(
                owner=settings.owner, task_id=task_id,
                remind_at=_to_utc(remind_at), label=label,
            )
            s.add(row)
            s.flush()
            return _reminder_dict(row)

    def delete_task_reminder(self, task_id: int, reminder_id: int) -> bool:
        with self._session() as s, s.begin():
            row = s.get(TaskReminder, reminder_id)
            if row is None or row.task_id != task_id:
                return False
            s.delete(row)
            return True

    def due_reminders(self, now: datetime | None = None) -> list[dict]:
        """Unfired reminders past due on still-open tasks — the scheduler's query."""
        now = now or utcnow()
        with self._session() as s:
            rows = s.execute(
                select(TaskReminder, Task)
                .join(Task, TaskReminder.task_id == Task.id)
                .where(TaskReminder.fired_at.is_(None))
                .where(TaskReminder.remind_at <= now)
                .where(Task.done.is_(False))
                .order_by(TaskReminder.remind_at)
            ).all()
            return [
                {**_reminder_dict(r), "task_label": t.label}
                for r, t in rows
            ]

    def mark_reminder_fired(self, reminder_id: int, when: datetime | None = None) -> None:
        with self._session() as s, s.begin():
            row = s.get(TaskReminder, reminder_id)
            if row is not None and row.fired_at is None:
                row.fired_at = when or utcnow()

    # ---- task files (M3 — metadata here, bytes under settings.attachments_dir) ----
    def append_task_file(self, task_id: int, meta: dict) -> dict | None:
        with self._session() as s, s.begin():
            task = s.get(Task, task_id)
            if task is None:
                return None
            task.files = [*(task.files or []), meta]
            return meta

    def remove_task_file(self, task_id: int, file_id: str) -> dict | None:
        """Drop one file's metadata; returns it so the router can unlink bytes."""
        with self._session() as s, s.begin():
            task = s.get(Task, task_id)
            if task is None:
                return None
            keep, removed = [], None
            for f in task.files or []:
                if str(f.get("id")) == str(file_id):
                    removed = f
                else:
                    keep.append(f)
            if removed is not None:
                task.files = keep
            return removed

    # ---- memory ----
    def list_memories(self) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(Memory).order_by(Memory.id.desc())).all()
            return [_memory_dict(m) for m in rows]

    def create_memory(self, data: dict, mem0_id: str | None = None) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            memory = Memory(
                owner=settings.owner,
                mem0_id=mem0_id,
                **{k: v for k, v in data.items() if k in _MEMORY_FIELDS and v is not None},
            )
            s.add(memory)
            s.flush()
            return _memory_dict(memory)

    def set_memory_mem0_id(self, memory_id: int, mem0_id: str) -> None:
        with self._session() as s, s.begin():
            memory = s.get(Memory, memory_id)
            if memory is not None:
                memory.mem0_id = mem0_id

    def update_memory_by_mem0_id(self, mem0_id: str, text: str) -> bool:
        with self._session() as s, s.begin():
            memory = s.scalars(select(Memory).where(Memory.mem0_id == mem0_id)).first()
            if memory is None:
                return False
            memory.text = text
            return True

    def delete_memory_by_mem0_id(self, mem0_id: str) -> bool:
        with self._session() as s, s.begin():
            memory = s.scalars(select(Memory).where(Memory.mem0_id == mem0_id)).first()
            if memory is None:
                return False
            s.delete(memory)
            return True

    def update_memory(self, memory_id: int, patch: dict) -> dict | None:
        with self._session() as s, s.begin():
            memory = s.get(Memory, memory_id)
            if memory is None:
                return None
            for key, value in patch.items():
                if key in _MEMORY_FIELDS and value is not None:
                    setattr(memory, key, value)
            s.flush()
            return _memory_dict(memory)

    def delete_memory(self, memory_id: int) -> dict | None:
        """Delete and return the row (callers propagate its mem0_id to Mem0)."""
        with self._session() as s, s.begin():
            memory = s.get(Memory, memory_id)
            if memory is None:
                return None
            snapshot = _memory_dict(memory)
            s.delete(memory)
            return snapshot

    # ---- conversations (used by the real assistant from M2 on) ----
    def create_conversation(self, title: str | None = None) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            conv = Conversation(owner=settings.owner, title=title)
            s.add(conv)
            s.flush()
            return {"id": conv.id, "title": conv.title,
                    "created_at": aware_utc(conv.created_at),
                    "updated_at": aware_utc(conv.updated_at)}

    def get_conversation(self, conversation_id: int) -> dict | None:
        with self._session() as s:
            conv = s.get(Conversation, conversation_id)
            if conv is None:
                return None
            return {"id": conv.id, "title": conv.title,
                    "created_at": aware_utc(conv.created_at),
                    "updated_at": aware_utc(conv.updated_at)}

    def latest_conversation(self) -> dict | None:
        with self._session() as s:
            conv = s.scalars(
                select(Conversation).order_by(Conversation.updated_at.desc()).limit(1)
            ).first()
            if conv is None:
                return None
            return {"id": conv.id, "title": conv.title,
                    "created_at": aware_utc(conv.created_at),
                    "updated_at": aware_utc(conv.updated_at)}

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        actions: list | None = None,
    ) -> dict | None:
        with self._session() as s, s.begin():
            conv = s.get(Conversation, conversation_id)
            if conv is None:
                return None
            msg = ConversationMessage(
                conversation_id=conversation_id, role=role, content=content, actions=actions
            )
            conv.updated_at = utcnow()
            if conv.title is None and role == "user":
                conv.title = content[:80]
            s.add(msg)
            s.flush()
            return _message_dict(msg)

    def list_messages(self, conversation_id: int) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.id)
            ).all()
            return [_message_dict(m) for m in rows]

    # ---- calendar (M3) ----
    def create_event(self, data: dict) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            start = _to_utc(data["start"])
            end = _to_utc(data["end"]) if data.get("end") else start + timedelta(hours=1)
            event = Event(
                owner=settings.owner,
                title=data["title"],
                start_at=start,
                end_at=end,
                tint=data.get("tint") or "sky",
                location=data.get("location") or "",
                description=data.get("description") or "",
                recurrence=data.get("recurrence"),
            )
            s.add(event)
            s.flush()
            return _occurrence_dict(event, aware_utc(event.start_at), aware_utc(event.end_at))

    def update_event(self, event_id: int, patch: dict) -> dict | None:
        """Edit a series. Raises ValueError when the patch would leave
        end <= start (the router turns that into a 422, like POST)."""
        with self._session() as s, s.begin():
            event = s.get(Event, event_id)
            if event is None:
                return None
            old_start = aware_utc(event.start_at)
            for key, value in patch.items():
                if key not in _EVENT_FIELDS:
                    continue
                if value is None and key not in _EVENT_NULLABLE:
                    continue
                if key == "start":
                    event.start_at = _to_utc(value)
                elif key == "end":
                    event.end_at = _to_utc(value)
                else:
                    setattr(event, key, value)
            if aware_utc(event.end_at) <= aware_utc(event.start_at):
                raise ValueError("'end' must be after 'start'")
            # Exdates are absolute occurrence starts; rescheduling the series
            # moves every occurrence, so the deletions move with them —
            # otherwise deleted occurrences silently resurrect.
            new_start = aware_utc(event.start_at)
            if event.exdates and new_start != old_start:
                shift = new_start - old_start
                event.exdates = [
                    (_to_utc(datetime.fromisoformat(x)) + shift).isoformat()
                    for x in event.exdates
                ]
            s.flush()
            return _occurrence_dict(event, aware_utc(event.start_at), aware_utc(event.end_at))

    def delete_event(self, event_id: int, occurrence_start: datetime | None = None) -> bool:
        """Delete a series — or one occurrence of it (recorded as an exdate)."""
        with self._session() as s, s.begin():
            event = s.get(Event, event_id)
            if event is None:
                return False
            if occurrence_start is not None and event.recurrence:
                iso = _to_utc(occurrence_start).isoformat()
                if iso not in (event.exdates or []):
                    event.exdates = [*(event.exdates or []), iso]
                return True
            s.delete(event)
            return True

    def events_between(self, window_start: datetime, window_end: datetime) -> list[dict]:
        """Concrete occurrences in the window, recurring series expanded."""
        with self._session() as s:
            rows = s.scalars(select(Event).order_by(Event.start_at)).all()
        out: list[dict] = []
        for e in rows:
            out.extend(_event_occurrences(e, window_start, window_end))
        out.sort(key=lambda o: o["start"])
        return out

    def up_next(self, limit: int = 3, now: datetime | None = None) -> list[dict]:
        """The agenda projection: ongoing first, then the next starts."""
        now = now or utcnow()
        occs = self.events_between(now - timedelta(days=1), now + timedelta(days=14))
        upcoming = [o for o in occs if o["end"] > now]
        upcoming.sort(key=lambda o: (o["start"] > now, o["start"]))
        return [
            {
                "id": o["id"],
                "title": o["title"],
                "when": event_when_display(o["start"], o["end"], o["location"], now),
                "tint": o["tint"],
                "start": o["start"],
            }
            for o in upcoming[:limit]
        ]

    # ---- habits (M3) ----
    def _habits_week_inner(self, s: Session, week_start: date, today: date) -> dict:
        habits = s.scalars(select(Habit).order_by(Habit.id)).all()
        week_end = week_start + timedelta(days=6)
        prev_start = week_start - timedelta(days=7)
        completions = s.scalars(select(HabitCompletion)).all()
        by_habit: dict[int, set[date]] = {}
        for c in completions:
            by_habit.setdefault(c.habit_id, set()).add(c.date)

        items = [
            _habit_dict(h, by_habit.get(h.id, set()), week_start, today) for h in habits
        ]

        def pct(habits_rows, start: date, until: date) -> int:
            slots = done = 0
            for h in habits_rows:
                sched = set(h.schedule or [])
                comp = by_habit.get(h.id, set())
                d = start
                while d <= until:
                    if d.weekday() in sched:
                        slots += 1
                        if d in comp:
                            done += 1
                    d += timedelta(days=1)
            return round(100 * done / slots) if slots else 0

        done_today = sum(
            1 for h, item in zip(habits, items)
            if today in by_habit.get(h.id, set())
        )
        today_index = (today - week_start).days
        return {
            "week_start": week_start,
            "today_index": today_index if 0 <= today_index <= 6 else None,
            "habits": items,
            "done_today": done_today,
            "week_pct": pct(habits, week_start, min(week_end, today)),
            "prev_week_pct": pct(habits, prev_start, prev_start + timedelta(days=6)),
        }

    def habits_week(self, week_start: date | None = None) -> dict:
        today = _local_today()
        week_start = week_start or recurrence.week_start(today)
        with self._session() as s:
            return self._habits_week_inner(s, week_start, today)

    def create_habit(self, data: dict) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            habit = Habit(
                owner=settings.owner,
                **{k: v for k, v in data.items() if k in _HABIT_FIELDS and v is not None},
            )
            s.add(habit)
            s.flush()
            today = _local_today()
            return _habit_dict(habit, set(), recurrence.week_start(today), today)

    def update_habit(self, habit_id: int, patch: dict) -> dict | None:
        with self._session() as s, s.begin():
            habit = s.get(Habit, habit_id)
            if habit is None:
                return None
            for key, value in patch.items():
                if key not in _HABIT_FIELDS:
                    continue
                if value is None and key not in _HABIT_NULLABLE:
                    continue
                setattr(habit, key, value)
            s.flush()
            completed = {
                c.date for c in s.scalars(
                    select(HabitCompletion).where(HabitCompletion.habit_id == habit_id)
                )
            }
            today = _local_today()
            return _habit_dict(habit, completed, recurrence.week_start(today), today)

    def delete_habit(self, habit_id: int) -> bool:
        with self._session() as s, s.begin():
            habit = s.get(Habit, habit_id)
            if habit is None:
                return False
            s.delete(habit)  # completions cascade
            return True

    @_retry_integrity
    def toggle_habit(self, habit_id: int, day: date | None = None) -> dict | None:
        """Flip a day's completion. A manual toggle always wins — toggling
        off an auto-completed day removes the auto row too."""
        day = day or _local_today()
        with self._session() as s, s.begin():
            habit = s.get(Habit, habit_id)
            if habit is None:
                return None
            existing = s.scalars(
                select(HabitCompletion)
                .where(HabitCompletion.habit_id == habit_id)
                .where(HabitCompletion.date == day)
            ).first()
            if existing is not None:
                s.delete(existing)
            else:
                s.add(HabitCompletion(habit_id=habit_id, date=day, source="manual"))
            s.flush()
            completed = {
                c.date for c in s.scalars(
                    select(HabitCompletion).where(HabitCompletion.habit_id == habit_id)
                )
            }
            today = _local_today()
            return _habit_dict(habit, completed, recurrence.week_start(today), today)

    @_retry_integrity
    def auto_complete_linked(self, link: str, day: date, achieved: bool) -> list[int]:
        """The cross-domain hook: nutrition (water) today, fitness (workout)
        in M4. Achieving the goal files an "auto" completion; falling back
        under it retracts auto rows only — never a user's manual tap."""
        changed: list[int] = []
        with self._session() as s, s.begin():
            habits = s.scalars(select(Habit).where(Habit.link == link)).all()
            for h in habits:
                existing = s.scalars(
                    select(HabitCompletion)
                    .where(HabitCompletion.habit_id == h.id)
                    .where(HabitCompletion.date == day)
                ).first()
                if achieved and existing is None:
                    s.add(HabitCompletion(habit_id=h.id, date=day, source="auto"))
                    changed.append(h.id)
                elif not achieved and existing is not None and existing.source == "auto":
                    s.delete(existing)
                    changed.append(h.id)
        return changed

    # ---- nutrition (M3) ----
    def _targets_inner(self, s: Session) -> NutritionTargets:
        from .config import settings

        row = s.scalars(
            select(NutritionTargets).where(NutritionTargets.owner == settings.owner)
        ).first()
        if row is None:
            row = NutritionTargets(owner=settings.owner)
            s.add(row)
            s.flush()
        return row

    @_retry_integrity
    def get_targets(self) -> dict:
        with self._session() as s, s.begin():
            return _targets_dict(self._targets_inner(s))

    @_retry_integrity
    def update_targets(self, patch: dict) -> dict:
        with self._session() as s, s.begin():
            row = self._targets_inner(s)
            for key, value in patch.items():
                if key in _TARGET_FIELDS and value is not None:
                    setattr(row, key, value)
            s.flush()
            result = _targets_dict(row)
        # A new water goal can flip today's auto-completion either way.
        today = _local_today()
        water = self.get_water(today)
        self.auto_complete_linked("water", today, water["cups"] >= result["water_cups"])
        return result

    def get_water(self, day: date | None = None) -> dict:
        day = day or _local_today()
        with self._session() as s, s.begin():
            targets = self._targets_inner(s)
            row = s.scalars(select(WaterDay).where(WaterDay.date == day)).first()
            return {"date": day, "cups": row.cups if row else 0, "goal": targets.water_cups}

    @_retry_integrity
    def set_water(self, day: date | None = None, cups: int | None = None,
                  delta: int | None = None) -> dict:
        from .config import settings

        day = day or _local_today()
        with self._session() as s, s.begin():
            targets = self._targets_inner(s)
            row = s.scalars(select(WaterDay).where(WaterDay.date == day)).first()
            if row is None:
                row = WaterDay(owner=settings.owner, date=day, cups=0)
                s.add(row)
            if cups is not None:
                row.cups = max(0, cups)
            else:
                row.cups = max(0, row.cups + (delta if delta is not None else 1))
            s.flush()
            result = {"date": day, "cups": row.cups, "goal": targets.water_cups}
        self.auto_complete_linked("water", day, result["cups"] >= result["goal"])
        return result

    def nutrition_day(self, day: date | None = None) -> dict:
        day = day or _local_today()
        with self._session() as s, s.begin():
            targets = _targets_dict(self._targets_inner(s))
            meals = s.scalars(
                select(Meal).where(Meal.date == day).order_by(Meal.logged_at)
            ).all()
            water = s.scalars(select(WaterDay).where(WaterDay.date == day)).first()
            meal_dicts = [_meal_dict(m) for m in meals]
            return {
                "date": day,
                "meals": meal_dicts,
                "totals": {
                    "kcal": sum(m["kcal"] for m in meal_dicts),
                    "protein_g": round(sum(m["protein_g"] for m in meal_dicts), 1),
                    "carbs_g": round(sum(m["carbs_g"] for m in meal_dicts), 1),
                    "fat_g": round(sum(m["fat_g"] for m in meal_dicts), 1),
                },
                "targets": targets,
                "water": {"date": day, "cups": water.cups if water else 0,
                          "goal": targets["water_cups"]},
            }

    def create_meal(self, data: dict) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            day = data.get("date") or _local_today()
            meal = Meal(
                owner=settings.owner,
                date=day,
                logged_at=data.get("logged_at") or utcnow(),
                **{k: v for k, v in data.items() if k in _MEAL_FIELDS and v is not None},
            )
            s.add(meal)
            s.flush()
            return _meal_dict(meal)

    def update_meal(self, meal_id: int, patch: dict) -> dict | None:
        with self._session() as s, s.begin():
            meal = s.get(Meal, meal_id)
            if meal is None:
                return None
            for key, value in patch.items():
                if key in _MEAL_FIELDS and value is not None:
                    setattr(meal, key, value)
            s.flush()
            return _meal_dict(meal)

    def delete_meal(self, meal_id: int) -> bool:
        with self._session() as s, s.begin():
            meal = s.get(Meal, meal_id)
            if meal is None:
                return False
            s.delete(meal)
            return True

    def nutrition_week(self, end_day: date | None = None) -> dict:
        """Mon-first week containing `end_day` (default today) for the trend chart."""
        end_day = end_day or _local_today()
        start = recurrence.week_start(end_day)
        with self._session() as s, s.begin():
            goal = self._targets_inner(s).calories
            meals = s.scalars(
                select(Meal)
                .where(Meal.date >= start)
                .where(Meal.date <= start + timedelta(days=6))
            ).all()
        by_day: dict[date, int] = {}
        for m in meals:
            by_day[m.date] = by_day.get(m.date, 0) + m.kcal
        dows = ["M", "T", "W", "T", "F", "S", "S"]
        days = [
            {
                "date": start + timedelta(days=i),
                "dow": dows[i],
                "kcal": by_day.get(start + timedelta(days=i), 0),
                "frac": min(1.0, round(by_day.get(start + timedelta(days=i), 0) / goal, 2))
                if goal else 0.0,
            }
            for i in range(7)
        ]
        logged = [d["kcal"] for d in days if d["kcal"] > 0]
        return {
            "days": days,
            "avg_kcal": round(sum(logged) / len(logged)) if logged else 0,
            "days_met": sum(1 for k in logged if k <= goal),
            "goal": goal,
        }

    # ---- provider accounts (OAuth, server-side only) ----
    def _provider_row(self, s: Session, provider: str) -> ProviderAccount | None:
        from .config import settings

        return s.scalars(
            select(ProviderAccount)
            .where(ProviderAccount.owner == settings.owner)
            .where(ProviderAccount.provider == provider)
        ).first()

    def get_provider_account(self, provider: str) -> dict | None:
        with self._session() as s:
            row = self._provider_row(s, provider)
            return _provider_account_dict(row) if row else None

    def get_provider_tokens(self, provider: str) -> Tokens | None:
        with self._session() as s:
            row = self._provider_row(s, provider)
            if row is None:
                return None
            return Tokens(
                access_token=row.access_token,
                refresh_token=row.refresh_token,
                expires_at=aware_utc(row.expires_at),
                scopes=row.scopes or "",
                provider_user_id=row.provider_user_id,
                meta=dict(row.meta or {}),
            )

    def list_provider_accounts(self) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(ProviderAccount).order_by(ProviderAccount.id)).all()
            return [_provider_account_dict(p) for p in rows]

    @_retry_integrity
    def upsert_provider_account(self, provider: str, tokens: Tokens) -> dict:
        """Get-or-create by (owner, provider); writes the tokens, scopes,
        provider_user_id and meta, sets status='connected' (a reconnect
        clears a prior needs_reauth). connected_at is stamped only on create."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            if row is None:
                row = ProviderAccount(owner=settings.owner, provider=provider)
                s.add(row)
            row.access_token = tokens.access_token
            row.refresh_token = tokens.refresh_token
            row.expires_at = _to_utc(tokens.expires_at) if tokens.expires_at else None
            row.scopes = tokens.scopes or ""
            if tokens.provider_user_id is not None:
                row.provider_user_id = tokens.provider_user_id
            if tokens.meta:
                row.meta = dict(tokens.meta)
            row.status = "connected"
            s.flush()
            return _provider_account_dict(row)

    def set_provider_status(self, provider: str, status: str) -> None:
        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            if row is not None:
                row.status = status

    def set_provider_synced(self, provider: str, when: datetime | None = None) -> None:
        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            if row is not None:
                row.last_sync_at = _to_utc(when) if when else utcnow()

    def delete_provider_data(self, provider: str) -> bool:
        """Disconnect: delete the provider_accounts row + that provider's
        daily_snapshots and workouts (source == provider). Manual workouts
        are preserved (their source is 'manual'). Returns True iff an account
        existed. Deletion is the user-facing guarantee, so the router calls
        this even when the remote revoke fails."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            existed = row is not None
            if row is not None:
                s.delete(row)
            for snap in s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.source == provider)
            ):
                s.delete(snap)
            for w in s.scalars(
                select(Workout)
                .where(Workout.owner == settings.owner)
                .where(Workout.source == provider)
            ):
                s.delete(w)
            return existed

    # ---- emails (M5) ----
    def _email_row(self, s: Session, source: str, source_id: str) -> Email | None:
        from .config import settings

        return s.scalars(
            select(Email)
            .where(Email.owner == settings.owner)
            .where(Email.source == source)
            .where(Email.source_id == source_id)
        ).first()

    def email_exists(self, source: str, source_id: str) -> bool:
        """Sync skips messages.get + triage for ids already stored (idempotency)."""
        with self._session() as s:
            return self._email_row(s, source, source_id) is not None

    def email_triaged(self, source: str, source_id: str) -> bool:
        """True iff a row exists for (owner, source, source_id) AND it has been
        triaged (category is not None). The sync skips fully-triaged rows but
        RE-triages rows that are stored-but-untriaged (category IS NULL)."""
        with self._session() as s:
            row = self._email_row(s, source, source_id)
            return row is not None and row.category is not None

    @_retry_integrity
    def upsert_email(
        self,
        email: NormalizedEmail,
        category: str | None,
        summary: list[str] | None,
    ) -> dict:
        """Get-or-create by (owner, source, source_id); writes metadata every
        pass. Triage fields (category/summary_json/triaged_at) are written
        ONLY when category is not None — a triage failure passes category=None,
        leaving the row untriaged for retry (and never clobbering prior good
        triage). Body is never persisted."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._email_row(s, email.source, email.source_id)
            if row is None:
                row = Email(
                    owner=settings.owner,
                    source=email.source,
                    source_id=email.source_id,
                )
                s.add(row)
            for field in _EMAIL_FIELDS:
                value = getattr(email, field)
                if field == "received_at":
                    value = _to_utc(value)
                setattr(row, field, value)
            if category is not None:
                row.category = category
                row.summary_json = summary
                row.triaged_at = utcnow()
            s.flush()
            return _email_dict(row)

    def inbox(self) -> dict:
        """The two-pane inbox: needs_reply / fyi / untriaged lists (each sorted
        received_at desc) + the needs_reply count and the unread count.
        Always served from the emails table — never a live Gmail call."""
        from .config import settings

        with self._session() as s:
            rows = s.scalars(
                select(Email)
                .where(Email.owner == settings.owner)
                .order_by(Email.received_at.desc())
            ).all()
        needs_reply, fyi, untriaged = [], [], []
        unread_count = 0
        for r in rows:
            if r.unread:
                unread_count += 1
            d = _email_dict(r)
            if r.category == "needs_reply":
                needs_reply.append(d)
            elif r.category == "fyi":
                fyi.append(d)
            else:
                untriaged.append(d)
        return {
            "needs_reply": needs_reply,
            "fyi": fyi,
            "untriaged": untriaged,
            "needs_reply_count": len(needs_reply),
            "unread_count": unread_count,
        }

    def get_email(self, email_id: int) -> dict | None:
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Email)
                .where(Email.id == email_id)
                .where(Email.owner == settings.owner)
            ).first()
            return _email_dict(row) if row is not None else None

    def delete_email_data(self, source: str) -> bool:
        """Disconnect hook (GoogleProvider.on_disconnect): delete emails where
        (owner, source). Returns True iff any row was deleted. Separate from
        delete_provider_data (which owns the provider_accounts row + fitness
        tables); the shared router deletes the account, this deletes the domain
        data."""
        from .config import settings

        deleted = False
        with self._session() as s, s.begin():
            for row in s.scalars(
                select(Email)
                .where(Email.owner == settings.owner)
                .where(Email.source == source)
            ):
                s.delete(row)
                deleted = True
        return deleted

    # ---- snapshots (derive-on-read) ----
    @_retry_integrity
    def upsert_snapshot(self, snap: NormalizedSnapshot) -> dict:
        """Get-or-create by (owner, source, day); merges non-None fields onto
        the existing row so a day's recovery and sleep records fold together
        (non-None wins, None never clobbers). metrics_json shallow-merges."""
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.source == snap.source)
                .where(DailySnapshot.day == snap.day)
            ).first()
            if row is None:
                row = DailySnapshot(owner=settings.owner, source=snap.source, day=snap.day)
                s.add(row)
            for field in _SNAPSHOT_FIELDS:
                value = getattr(snap, field)
                if value is not None:
                    setattr(row, field, value)
            if snap.metrics_json:
                row.metrics_json = {**(row.metrics_json or {}), **snap.metrics_json}
            s.flush()
            return _snapshot_dict(row)

    def _snapshot_row(self, s: Session, day: date) -> DailySnapshot | None:
        """The owner's snapshot for `day`. When multiple sources wrote the same
        day (e.g. a future 'oura' alongside 'whoop'), prefer 'whoop' so reads
        don't flip between providers; ties fall back to newest id."""
        from .config import settings

        # Source precedence: prefer 'whoop' (0) over any other source (1).
        precedence = case((DailySnapshot.source == "whoop", 0), else_=1)
        return s.scalars(
            select(DailySnapshot)
            .where(DailySnapshot.owner == settings.owner)
            .where(DailySnapshot.day == day)
            .order_by(precedence, DailySnapshot.id.desc())
        ).first()

    @staticmethod
    def _vital_delta(field: str, today_val, prior_val):
        if today_val is None or prior_val is None:
            return None
        if field == "resting_hr":
            return today_val - prior_val
        return round(today_val - prior_val, 1)

    def fitness_today(self, day: date | None = None) -> dict:
        """Rings + vitals for `day` (default today). Vital deltas are this-day
        minus the prior-day snapshot (None if there's no prior)."""
        day = day or _local_today()
        with self._session() as s:
            today_row = self._snapshot_row(s, day)
            prior_row = self._snapshot_row(s, day - timedelta(days=1))
        vitals = []
        for key, field, label, unit, icon, tint in _VITALS_SPEC:
            value = getattr(today_row, field) if today_row else None
            prior = getattr(prior_row, field) if prior_row else None
            vitals.append({
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "delta": self._vital_delta(field, value, prior),
                "icon": icon,
                "tint": tint,
            })
        return {
            "date": day,
            "source": today_row.source if today_row else None,
            "recovery_pct": today_row.recovery_pct if today_row else None,
            "day_strain": today_row.day_strain if today_row else None,
            "sleep_quality_pct": today_row.sleep_quality_pct if today_row else None,
            "vitals": vitals,
            "has_data": today_row is not None,
        }

    def fitness_week(self, end_day: date | None = None) -> dict:
        """Mon-first 7-day day_strain trend for the week containing `end_day`
        (default today). frac = day_strain / 21, capped at 1.0. Scoped to the
        owner; when several sources wrote the same day, 'whoop' wins (matching
        _snapshot_row's precedence) so the trend doesn't flip between providers."""
        from .config import settings

        end_day = end_day or _local_today()
        start = recurrence.week_start(end_day)
        # 'whoop' (0) sorts before other sources (1); within a day the last
        # write seen for that ordering wins.
        precedence = case((DailySnapshot.source == "whoop", 0), else_=1)
        with self._session() as s:
            rows = s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.day >= start)
                .where(DailySnapshot.day <= start + timedelta(days=6))
                .order_by(precedence.desc(), DailySnapshot.id.desc())
            ).all()
        # Iterating worst-precedence-first means the preferred ('whoop') row is
        # written LAST and wins the dict slot for its day.
        strain_by_day: dict[date, float] = {}
        for r in rows:
            if r.day_strain is not None:
                strain_by_day[r.day] = r.day_strain
        dows = ["M", "T", "W", "T", "F", "S", "S"]
        days = []
        for i in range(7):
            d = start + timedelta(days=i)
            strain = strain_by_day.get(d)
            days.append({
                "date": d,
                "dow": dows[i],
                "strain": strain,
                "frac": min(1.0, round(strain / 21, 2)) if strain is not None else 0.0,
            })
        logged = [d["strain"] for d in days if d["strain"] is not None]
        peak = max(days, key=lambda d: d["strain"] if d["strain"] is not None else -1.0)
        return {
            "days": days,
            "avg_strain": round(sum(logged) / len(logged), 1) if logged else 0,
            "peak_day": peak["date"] if logged else None,
        }

    # ---- workouts ----
    def _workout_local_day(self, started_at: datetime) -> date:
        """The calendar day a workout belongs to = its start in local tz."""
        return aware_utc(started_at).astimezone().date()

    def list_workouts(self, limit: int = 50) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(
                select(Workout).order_by(Workout.started_at.desc()).limit(limit)
            ).all()
            return [_workout_dict(w) for w in rows]

    @_retry_integrity
    def upsert_workout(self, w: NormalizedWorkout) -> dict:
        """Upsert a synced workout by (source, source_id); manual rows (null
        source_id) go through create_workout. Runs the workout->habit
        auto-complete for the workout's local day after the row lands."""
        from .config import settings

        with self._session() as s, s.begin():
            row = None
            if w.source_id is not None:
                row = s.scalars(
                    select(Workout)
                    .where(Workout.source == w.source)
                    .where(Workout.source_id == w.source_id)
                ).first()
            if row is None:
                row = Workout(owner=settings.owner, source=w.source, source_id=w.source_id)
                s.add(row)
            row.name = w.name
            row.sport = w.sport
            row.started_at = _to_utc(w.started_at)
            row.duration_min = w.duration_min
            row.strain = w.strain
            row.calories = w.calories
            row.avg_hr = w.avg_hr
            row.max_hr = w.max_hr
            s.flush()
            result = _workout_dict(row)
            day = self._workout_local_day(row.started_at)
        self.auto_complete_linked("workout", day, True)
        return result

    def create_workout(self, data: dict) -> dict:
        """Manual workout: source='manual', source_id=None. Triggers the
        workout->habit auto-complete for the started_at local day."""
        from .config import settings

        with self._session() as s, s.begin():
            fields = {k: v for k, v in data.items() if k in _WORKOUT_FIELDS and v is not None}
            started = fields.pop("started_at")
            row = Workout(
                owner=settings.owner, source="manual", source_id=None,
                started_at=_to_utc(started), **fields,
            )
            s.add(row)
            s.flush()
            result = _workout_dict(row)
            day = self._workout_local_day(row.started_at)
        self.auto_complete_linked("workout", day, True)
        return result

    def delete_workout(self, workout_id: int) -> bool:
        with self._session() as s, s.begin():
            row = s.get(Workout, workout_id)
            if row is None:
                return False
            s.delete(row)
            return True

    # ---- demo data ----
    def seed_demo(self) -> bool:
        """Insert the design-prototype sample rows.

        Idempotent **per domain**: each table seeds only if empty, so running
        it after a milestone adds the new domains without touching existing
        data. Dates are relative to today so every panel looks the way the
        prototype intended no matter when it runs.
        """
        today = _local_today()
        with self._session() as s, s.begin():
            seeded = self._seed_tasks_and_memories(s, today)
            seeded = self._seed_events(s, today) or seeded
            seeded = self._seed_habits(s, today) or seeded
            seeded = self._seed_nutrition(s, today) or seeded
            return seeded

    def _seed_tasks_and_memories(self, s: Session, today: date) -> bool:
        from .config import settings

        if s.scalars(select(Task).limit(1)).first() is not None:
            return False

        def day(offset: int) -> date:
            return today + timedelta(days=offset)

        def at(d: date, hour: int, minute: int = 0) -> datetime:
            local = datetime.combine(d, time(hour, minute)).astimezone()
            return local.astimezone(timezone.utc)

        tasks = [
            Task(label="Reply to Priya about Lighthouse", group="Today", deadline=day(0),
                 prio="high", list_name="Work",
                 description="She asked about the moved deadline — confirm the 30th works and loop in the design review.",
                 subtasks=[{"id": 11, "label": "Check calendar for the 30th", "done": True},
                           {"id": 12, "label": "Draft reply", "done": False}],
                 files=[{"id": 101, "name": "lighthouse-brief.pdf", "size": 248000}]),
            Task(label="Log lunch", group="Today", deadline=day(0), prio="low",
                 list_name="Health", labels=["nutrition"]),
            Task(label="Book dentist follow-up", group="Today", deadline=day(-2), prio="med",
                 list_name="Health",
                 description="Call Oak Street Dental — ask for an early-morning slot."),
            Task(label="Move $120 to savings", group="Today", deadline=day(0), prio="med",
                 list_name="Finance", description="Roll over the dining-budget surplus.",
                 labels=["savings"]),
            Task(label="Pay rent", group="Today", deadline=day(0), prio="high",
                 list_name="Finance", done=True, completed_at=utcnow()),
            Task(label="Draft Q3 planning doc", group="Upcoming", deadline=day(1),
                 prio="high", list_name="Work",
                 description="Outline goals, headcount, and the roadmap themes.",
                 subtasks=[{"id": 61, "label": "Goals", "done": False},
                           {"id": 62, "label": "Roadmap themes", "done": False}],
                 labels=["planning"]),
            Task(label="Order mom's birthday gift", group="Upcoming", deadline=day(4),
                 prio="med", list_name="Personal",
                 description="The ceramics class she mentioned in a voice note.",
                 files=[{"id": 701, "name": "ceramics-studio.png", "size": 1340000},
                        {"id": 702, "name": "gift-ideas.txt", "size": 1200}]),
            Task(label="Meal prep for the week", group="Upcoming", deadline=day(6),
                 prio="low", list_name="Health",
                 recurrence="FREQ=WEEKLY"),
            Task(label="Renew gym membership", group="Someday", prio="low", list_name="Health"),
            Task(label="Read 'Deep Work'", group="Someday", prio="low", list_name="Personal",
                 labels=["reading"]),
        ]
        for t in reversed(tasks):  # insert so list order (id desc) matches the prototype
            t.owner = settings.owner
            s.add(t)
        s.flush()

        # The prototype's reminder strings, now as rows that actually fire.
        by_label = {t.label: t for t in tasks}
        reminders = [
            (by_label["Reply to Priya about Lighthouse"], at(day(0), 16), "1 hour before"),
            (by_label["Log lunch"], at(day(0), 13), "1:00pm"),
            (by_label["Order mom's birthday gift"], at(day(1), 9), ""),
        ]
        for task, when, label in reminders:
            s.add(TaskReminder(owner=settings.owner, task_id=task.id,
                               remind_at=when, label=label))

        now = utcnow()
        memories = [
            Memory(text="Mom's birthday is March 14 — she mentioned wanting that ceramics class.",
                   src="voice note", tags=["family", "gifts"], color="plum",
                   created_at=now - timedelta(days=2)),
            Memory(text="Prefer morning workouts; energy dips after 8pm. Schedule deep work before noon.",
                   src="learned", tags=["health", "routine"], color="green",
                   created_at=now - timedelta(days=4)),
            Memory(text="Project Lighthouse deadline moved to June 30. Loop in Priya before the 20th.",
                   src="telegram", tags=["work"], color="sky",
                   created_at=now - timedelta(days=7)),
            Memory(text="Trying to cut dining out to twice a week. Cook salmon more often.",
                   src="voice note", tags=["finance", "nutrition"], color="clay",
                   created_at=now - timedelta(days=8)),
        ]
        for m in reversed(memories):
            m.owner = settings.owner
            s.add(m)
        return True

    def _seed_events(self, s: Session, today: date) -> bool:
        from .config import settings

        if s.scalars(select(Event).limit(1)).first() is not None:
            return False

        monday = recurrence.week_start(today)

        def at(offset_days: int, hour: int, minute: int = 0) -> datetime:
            local = datetime.combine(
                monday + timedelta(days=offset_days), time(hour, minute)
            ).astimezone()
            return local.astimezone(timezone.utc)

        events = [
            # Recurring: weekday standup + a weekly deep-work block prove the
            # expansion path the moment the screen loads.
            Event(title="Team standup", start_at=at(0, 9, 30), end_at=at(0, 9, 45),
                  tint="sky", location="Google Meet",
                  recurrence="FREQ=WEEKLY;BYDAY=MO,WE,FR"),
            Event(title="Deep work — Q3 plan", start_at=at(1, 9), end_at=at(1, 10, 30),
                  tint="green", recurrence="FREQ=WEEKLY"),
            Event(title="Dentist", start_at=at(1, 16), end_at=at(1, 17),
                  tint="clay", location="Oak Street"),
            Event(title="Design review", start_at=at(2, 11, 30), end_at=at(2, 12, 15),
                  tint="sky", location="Google Meet"),
            Event(title="Lunch with Sam", start_at=at(3, 12, 30), end_at=at(3, 13, 30),
                  tint="honey"),
            Event(title="Gym — push day", start_at=at(4, 8), end_at=at(4, 9),
                  tint="clay"),
            Event(title="Groceries", start_at=at(5, 10), end_at=at(5, 11),
                  tint="plum"),
        ]
        for e in events:
            e.owner = settings.owner
            s.add(e)
        return True

    def _seed_habits(self, s: Session, today: date) -> bool:
        from .config import settings

        if s.scalars(select(Habit).limit(1)).first() is not None:
            return False

        # (name, icon, tint, link, streak, done_today) — streaks land on the
        # prototype's numbers; only Meditate and Read are done today (2 of 5).
        habits = [
            ("Meditate", "flower-2", "green", None, 12, True),
            ("Read 20 min", "book-open", "sky", None, 5, True),
            ("Workout", "dumbbell", "clay", "workout", 3, False),
            ("Sleep by 11", "moon", "plum", None, 8, False),
            ("Drink 8 cups water", "droplet", "honey", "water", 2, False),
        ]
        for name, icon, tint, link, streak, done_today in habits:
            h = Habit(owner=settings.owner, name=name, icon=icon, tint=tint, link=link)
            s.add(h)
            s.flush()
            start = 0 if done_today else 1
            for back in range(start, start + streak):
                s.add(HabitCompletion(habit_id=h.id, date=today - timedelta(days=back)))
        return True

    def _seed_nutrition(self, s: Session, today: date) -> bool:
        from .config import settings

        has_meals = s.scalars(select(Meal).limit(1)).first() is not None
        has_targets = s.scalars(select(NutritionTargets).limit(1)).first() is not None
        if has_meals or has_targets:
            return False

        s.add(NutritionTargets(owner=settings.owner))  # the prototype's defaults

        def meal(d: date, slot: str, name: str, hour: int, minute: int,
                 kcal: int, protein: float, carbs: float, fat: float) -> Meal:
            logged = datetime.combine(d, time(hour, minute)).astimezone()
            return Meal(owner=settings.owner, date=d, slot=slot, name=name,
                        kcal=kcal, protein_g=protein, carbs_g=carbs, fat_g=fat,
                        logged_at=logged.astimezone(timezone.utc))

        # Today: the prototype's four meals (1,690 kcal of 2,100).
        for m in [
            meal(today, "Breakfast", "Eggs & toast", 8, 10, 320, 24, 30, 12),
            meal(today, "Lunch", "Chicken wrap", 12, 40, 540, 38, 52, 18),
            meal(today, "Snack", "Apple & almonds", 15, 30, 210, 7, 24, 10),
            meal(today, "Dinner", "Salmon & rice", 19, 10, 620, 45, 58, 22),
        ]:
            s.add(m)

        # Earlier this week: one compact set per elapsed day so the trend
        # chart lands on the prototype's fractions.
        fracs = [0.82, 0.94, 0.71, 0.88, 1.0, 0.64, 0.87]
        monday = recurrence.week_start(today)
        d = monday
        while d < today:
            total = round(fracs[(d - monday).days] * 2100)
            s.add(meal(d, "Breakfast", "Yogurt & granola", 8, 0, 380, 22, 44, 12))
            s.add(meal(d, "Lunch", "Grain bowl", 12, 30, 560, 32, 60, 20))
            s.add(meal(d, "Dinner", "Dinner", 19, 0, max(0, total - 940),
                       round(0.075 * total), round(0.1 * total), round(0.03 * total)))
            d += timedelta(days=1)

        s.add(WaterDay(owner=settings.owner, date=today, cups=5))
        return True


store = Store()
