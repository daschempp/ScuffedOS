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

import base64
import functools
import hashlib
import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, case, delete, func, or_, select, text
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
    ContactsSyncState,
    Conversation,
    ConversationMessage,
    DailySnapshot,
    Email,
    Event,
    FinanceAccount,
    FinanceBudget,
    FinanceHolding,
    FinanceInvestmentTransaction,
    FinanceItem,
    FinanceLiability,
    FinanceRecurring,
    FinanceSecurity,
    FinanceTransaction,
    Habit,
    HabitCompletion,
    Insight,
    Meal,
    Memory,
    MoodleAnnouncement,
    MoodleAssignment,
    MoodleCourse,
    MoodleDeadline,
    MoodleGrade,
    MoodleNotification,
    NutritionTargets,
    Person,
    PersonHandle,
    ProviderAccount,
    Task,
    TaskReminder,
    WaterDay,
    Workout,
    utcnow,
)
from .providers.base import (
    NormalizedAccount,
    NormalizedAnnouncement,
    NormalizedAssignment,
    NormalizedCourse,
    NormalizedDeadline,
    NormalizedEmail,
    NormalizedGrade,
    NormalizedHolding,
    NormalizedItem,
    NormalizedNotification,
    NormalizedPerson,
    NormalizedSecurity,
    NormalizedSnapshot,
    NormalizedTransaction,
    NormalizedWorkout,
    Tokens,
    TransactionsDelta,
)
from .providers.macos_contacts import ContactsSnapshot, SnapshotStatus, SyncResult

# ---- finance budget categories (expanded fixed set, slice 2) ----
BUDGET_CATEGORIES = ["Groceries", "Dining out", "Rent & bills", "Transport",
                     "Shopping", "Entertainment", "Health", "Travel", "Savings", "Other"]
# kit.css defines only clay/honey/plum/sky/green (-600) + slate; colors repeat by design.
_BUDGET_COLORS = {
    "Groceries": "clay", "Dining out": "plum", "Rent & bills": "honey",
    "Transport": "sky", "Shopping": "plum", "Entertainment": "sky",
    "Health": "green", "Travel": "honey", "Savings": "green", "Other": "slate",
}


def budget_bucket(primary: str, detailed: str = "") -> str:
    """Map a Plaid personal_finance_category to one of the ten budget buckets.
    [confirm-against-live] — real PFC values verified at the live gate."""
    primary = (primary or "").upper()
    detailed = (detailed or "").upper()
    if "GROCERIES" in detailed:
        return "Groceries"
    if primary == "FOOD_AND_DRINK":
        return "Dining out"
    if primary in ("RENT_AND_UTILITIES", "LOAN_PAYMENTS", "HOME_IMPROVEMENT"):
        return "Rent & bills"
    if primary in ("TRANSPORTATION",):
        return "Transport"
    if primary == "TRAVEL":
        return "Travel"
    if primary in ("GENERAL_MERCHANDISE",):
        return "Shopping"
    if primary in ("ENTERTAINMENT",):
        return "Entertainment"
    if primary in ("MEDICAL", "PERSONAL_CARE"):
        return "Health"
    if primary == "TRANSFER_OUT" and ("SAVINGS" in detailed or "INVESTMENT" in detailed):
        return "Savings"
    return "Other"


def recurring_kind(primary: str, detailed: str = "") -> str:
    """Split a recurring OUTFLOW stream into 'subscription' vs 'bill' by Plaid PFC.
    [confirm-against-live] — real PFC values verified at the live gate."""
    primary = (primary or "").upper()
    if primary in ("RENT_AND_UTILITIES", "LOAN_PAYMENTS", "INSURANCE"):
        return "bill"
    if primary in ("ENTERTAINMENT", "GENERAL_SERVICES"):
        return "subscription"
    return "other"


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
    "received_at", "unread", "starred", "label_ids",
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


def _insight_dict(i: Insight) -> dict:
    return {
        "id": i.id,
        "day": i.day,
        "domain": i.domain,
        "code": i.code,
        "tone": i.tone,
        "headline": i.headline,
        "body": i.body,
        "signals": i.signals_json or {},
        "source": i.source,
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
        "starred": e.starred,
        "label_ids": e.label_ids or [],
        "category": e.category,
        "summary": e.summary_json or [],
        "triaged_at": aware_utc(e.triaged_at),
        "when": email_when_display(received),
        "created_at": aware_utc(e.created_at),
        "updated_at": aware_utc(e.updated_at),
    }


# ---- people (M10): locking + helpers ----
# Serializes every contacts mutation within this process; on PostgreSQL a
# transaction-scoped advisory lock (below) extends that guarantee across
# processes/hosts sharing the database. RLock so a retried @_retry_integrity
# call on the same thread can't self-deadlock.
_CONTACTS_LOCK = threading.RLock()

# Non-COMPLETE snapshot -> (SyncResult.status, contacts_sync_state.status, access).
# ACCESS_DENIED is handled inline (stale vs access_denied depends on existing rows).
_FAILED_MAP = {
    SnapshotStatus.UNSUPPORTED_SCHEMA: ("unsupported", "error", "unknown"),
    SnapshotStatus.MISSING_STORE:      ("error", "error", "unknown"),
    SnapshotStatus.PARTIAL_READ:       ("partial", "stale", "unknown"),
    SnapshotStatus.IO_ERROR:           ("error", "error", "unknown"),
}

# Sync-owned identity fields: written by the snapshot apply; server-enforced
# READ-ONLY on imported rows via the CRUD patch path. CRM-native fields
# (relationship*/notes/pinned/last_contacted_at) are ScuffedOS-owned and editable.
_PERSON_NAME_FIELDS = ("display_name", "first_name", "last_name",
                       "nickname", "organization", "job_title")
_PERSON_SYNC_FIELDS = _PERSON_NAME_FIELDS + ("phones", "emails", "photo_key", "has_photo")
_PERSON_IMMUTABLE = ("id", "owner", "source", "source_id",
                     "created_at", "updated_at", "meta", "removed_from_source_at")


def _advisory_key(owner: str) -> int:
    """Stable signed 64-bit key for pg_advisory_xact_lock, namespaced per owner."""
    digest = hashlib.sha1(f"scuffedos:contacts_sync:{owner}".encode()).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def _encode_cursor(display_name: str, person_id: int) -> str:
    """Opaque keyset cursor = base64(JSON [display_name, id]). SINGLE definition
    for the whole store — list_people (Task 3) and the router's paginated list
    (Task 7) both reuse it; do NOT redefine it elsewhere."""
    raw = json.dumps([display_name, person_id]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str | None, int | None]:
    """Inverse of _encode_cursor; returns (None, None) on any malformed token so a
    bad cursor yields an empty/whole page instead of a 500."""
    try:
        name, person_id = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return name, int(person_id)
    except Exception:
        return None, None


_HANDLE_MIN_DIGITS = 3
_LIKE_ESCAPE = "\\"


def _escape_like(ql: str) -> str:
    """Neutralize LIKE metacharacters in user text so a query means itself.

    Every pattern built from `q` MUST go through this and be matched with
    escape=_LIKE_ESCAPE. Unescaped, `%` and `_` are pattern syntax the user never
    asked for: "%com" expands to "%com%", which is exactly the substring search
    the email prefix rule removed, and "_da" matches any character before "da".
    Half-escaping is worse than none -- it just moves the hole to whichever
    clause was skipped.
    """
    return (ql.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)   # the escape char first, or we double our own
              .replace("%", _LIKE_ESCAPE + "%")
              .replace("_", _LIKE_ESCAPE + "_"))


def _handle_search_pattern(ql: str) -> tuple[str, str | None] | None:
    """(LIKE pattern, required handle kind) for the canonical person_handle keys,
    or None to skip handles entirely. A kind of None means any kind. The pattern
    is escaped and must be applied with escape=_LIKE_ESCAPE.

    A query carrying letters is an EMAIL search and matches the stored key as a
    PREFIX. An address is identifying on the left and shared on the right, so a
    substring match on "gmail" (or even "co") returned every person on that
    domain -- the whole address book, from a query that identifies nobody. The
    prefix covers what people actually type: a local part, or a pasted address,
    which is its own prefix. The cost is that the tail of an address is not a
    search key; a domain stays reachable through the organization field.
    The kind filter matters because short codes are stored as the literal
    "short:<n>" (app.identity), so an unscoped prefix made "sh" return every
    contact carrying one. (A prefix needs no substring/regex support beyond LIKE,
    so SQLite and Postgres behave identically -- but note it does NOT buy an
    index scan on Postgres: person_handle.value has a default-collation btree,
    which LIKE 'x%' can only use under varchar_pattern_ops. True on SQLite,
    not on the deployed Postgres.)

    A query of digits and punctuation only is a phone search, and the stored keys
    are E.164 -- "555-123" can only find "+15551234567" once the punctuation is
    stripped and the fragment is matched anywhere in the number, which happens
    HERE because neither backend gives us a portable regex. Digits are matched
    across every kind so a short code stays findable by its number. Below
    _HANDLE_MIN_DIGITS a fragment matches nearly every stored number, so such a
    query is not treated as a phone search at all.
    """
    if any(c.isalpha() for c in ql):
        return f"{_escape_like(ql)}%", "email"
    digits = "".join(c for c in ql if c in "0123456789")   # digits need no escaping
    return (f"%{digits}%", None) if len(digits) >= _HANDLE_MIN_DIGITS else None


def _clean_name(v, maxlen: int = 256) -> str:
    return str(v or "").strip()[:maxlen]


def _clean_label(v, maxlen: int = 64) -> str:
    return str(v or "").strip()[:maxlen]


def _clean_value(v, maxlen: int = 320) -> str:
    return str(v or "").strip()[:maxlen]


def _clean_strength(v) -> int | None:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return None


def _canon_entries(phones, emails, region: str):
    """Return (norm_phones, norm_emails, handles) as FRESH dicts/keys.

    Each stored entry is a brand-new ``{value,label,normalized}`` dict — reassigned
    wholesale to the JSON column by the caller so SQLAlchemy detects the change and
    ``normalized`` actually persists. ``handles`` maps a deduped ``(kind, value)``
    key to its ``possible`` flag for the PersonHandle rebuild. Never mutates the
    caller's input dicts.
    """
    from .identity import canon_handle

    norm_phones: list[dict] = []
    norm_emails: list[dict] = []
    handles: dict[tuple[str, str], bool] = {}
    for entries, out in ((phones, norm_phones), (emails, norm_emails)):
        for entry in entries or []:
            value = _clean_value((entry or {}).get("value", ""))
            if not value:
                continue
            label = _clean_label((entry or {}).get("label", ""))
            canon = canon_handle(value, region)
            out.append({"value": value, "label": label,
                        "normalized": canon["normalized"] if canon else None})
            if canon:
                handles.setdefault((canon["kind"], canon["normalized"]), canon["possible"])
    return norm_phones, norm_emails, handles


def _person_dict(p: Person) -> dict:
    return {
        "id": p.id,
        "source": p.source,
        "source_id": p.source_id,
        "display_name": p.display_name,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "nickname": p.nickname,
        "organization": p.organization,
        "job_title": p.job_title,
        "phones": p.phones or [],
        "emails": p.emails or [],
        "has_photo": bool(p.has_photo),
        "relationship": p.relationship,
        "relationship_strength": p.relationship_strength,
        "notes": p.notes,
        "pinned": bool(p.pinned),
        "last_contacted_at": aware_utc(p.last_contacted_at),
        "removed_from_source_at": aware_utc(p.removed_from_source_at),
        "created_at": aware_utc(p.created_at),
        "updated_at": aware_utc(p.updated_at),
    }


def _state_dict(st: ContactsSyncState) -> dict:
    return {
        "owner": st.owner,
        "enabled": bool(st.enabled),
        "status": st.status,
        "access": st.access,
        "normalization_region": st.normalization_region,
        "last_sync_at": aware_utc(st.last_sync_at),
        "last_error": st.last_error,
        "enabled_at": aware_utc(st.enabled_at),
        "created_at": aware_utc(st.created_at),
        "updated_at": aware_utc(st.updated_at),
    }


def _delete_photo_files(photos_root: str, keys: list[str]) -> None:
    """Best-effort unlink of relative photo_key files under the resolved photos
    root, with a containment check (never follow `..`/symlinks out of the root).
    A failure here never aborts the calling operation — including a malformed
    key (e.g. an embedded null byte) that would make os.path.realpath raise."""
    try:
        real_root = os.path.realpath(photos_root)
    except (OSError, ValueError):
        return
    for key in keys:
        if not key:
            continue
        try:
            target = os.path.realpath(os.path.join(real_root, key))
            if os.path.commonpath([real_root, target]) == real_root and os.path.isfile(target):
                os.remove(target)
        except (OSError, ValueError):
            continue


def _moodle_course_dict(c: MoodleCourse) -> dict:
    return {
        "id": c.id,
        "source_id": c.source_id,
        "shortname": c.shortname,
        "fullname": c.fullname,
        "progress": c.progress,
        "start_at": aware_utc(c.start_at),
        "end_at": aware_utc(c.end_at),
        "last_access_at": aware_utc(c.last_access_at),
        "hidden": c.hidden,
    }


def _moodle_deadline_dict(d: MoodleDeadline) -> dict:
    due = aware_utc(d.due_at)
    return {
        "id": d.id,
        "source_id": d.source_id,
        "course_id": d.course_id,
        "name": d.name,
        "module_name": d.module_name,
        "event_type": d.event_type,
        "due_at": due,
        "overdue": d.overdue,
        "url": d.url,
        # Derived display string (never stored) — reuse the calendar
        # "Up next" formatter; a deadline is a point in time, so start==end.
        "when": event_when_display(due, due, "", None),
    }


def _dec_to_float(x) -> float | None:
    return float(x) if x is not None else None


def _finance_account_dict(a: FinanceAccount) -> dict:
    return {
        "id": a.id,
        "source_id": a.source_id,
        "item_id": a.item_id,
        "name": a.name,
        "official_name": a.official_name,
        "mask": a.mask,
        "type": a.type,
        "subtype": a.subtype,
        "current_balance": _dec_to_float(a.current_balance),
        "available_balance": _dec_to_float(a.available_balance),
        "iso_currency": a.iso_currency,
    }


def _finance_transaction_dict(t: FinanceTransaction) -> dict:
    return {
        "id": t.id,
        "source_id": t.source_id,
        "account_id": t.account_id,
        "name": t.name,
        "merchant_name": t.merchant_name,
        "amount": _dec_to_float(t.amount),
        "positive": (t.amount is not None and t.amount < 0),   # inflow
        "iso_currency": t.iso_currency,
        "date": t.date.isoformat() if t.date else None,
        "pending": t.pending,
        "category": t.category_primary,
        "when": relative_when(_to_utc(datetime(t.date.year, t.date.month, t.date.day)))
                if t.date else "",
    }


def _finance_item_dict(row: FinanceItem) -> dict:
    """Client-safe Item view — NO access_token, NO cursor."""
    return {
        "item_id": row.source_id,
        "institution_name": row.institution_name,
        "status": row.status,
        "products": list(row.products or []),
        "connected_at": aware_utc(row.connected_at),
        "last_sync_at": aware_utc(row.last_sync_at),
    }


def _moodle_assignment_dict(a: MoodleAssignment) -> dict:
    return {
        "id": a.id,
        "source_id": a.source_id,
        "course_id": a.course_id,
        "cmid": a.cmid,
        "name": a.name,
        "due_at": aware_utc(a.due_at),
        "cutoff_at": aware_utc(a.cutoff_at),
        "grade_max": a.grade_max,
        "submission_status": a.submission_status,
        "grading_status": a.grading_status,
        "graded": a.graded,
    }


def _moodle_grade_dict(g: MoodleGrade) -> dict:
    return {
        "id": g.id,
        "source_id": g.source_id,
        "course_id": g.course_id,
        "item_name": g.item_name,
        "item_type": g.item_type,
        "grade_formatted": g.grade_formatted,
        "grade_raw": g.grade_raw,
        "grade_min": g.grade_min,
        "grade_max": g.grade_max,
        "graded_at": aware_utc(g.graded_at),
    }


def _moodle_announcement_dict(a: MoodleAnnouncement) -> dict:
    return {
        "id": a.id,
        "source_id": a.source_id,
        "course_id": a.course_id,
        "forum_id": a.forum_id,
        "subject": a.subject,
        "author": a.author,
        "created_at": aware_utc(a.created_at),
        "summary_html": a.summary_html,
        "url": a.url,
    }


def _moodle_notification_dict(n: MoodleNotification) -> dict:
    return {
        "id": n.id,
        "source_id": n.source_id,
        "subject": n.subject,
        "full_message": n.full_message,
        "context_url": n.context_url,
        "created_at": aware_utc(n.created_at),
        "read": n.read,
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
            local = [_task_dict(t, by_task.get(t.id, [])) for t in rows]
        # Read-time-merge Moodle assignments (contract §H) as read-only School
        # tasks — appended after local rows, NOT persisted to the tasks table.
        return local + self.moodle_tasks()

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
        """Concrete occurrences in the window, recurring series expanded.
        Read-time-merges in-window Moodle deadlines (contract §H) as read-only
        'grape' occurrences before the final sort, so Home/Calendar/up_next
        all show them without any events-table write."""
        with self._session() as s:
            rows = s.scalars(select(Event).order_by(Event.start_at)).all()
        out: list[dict] = []
        for e in rows:
            out.extend(_event_occurrences(e, window_start, window_end))
        out.extend(self.moodle_calendar_events(window_start, window_end))
        out.extend(self.finance_calendar_events(window_start, window_end))
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
        are preserved (their source is 'manual'); WHOOP-derived fitness
        insights are removed with their source data. Returns True iff an
        account existed. Deletion is the user-facing guarantee, so the router
        calls this even when the remote revoke fails."""
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
            if provider == "whoop":
                s.execute(
                    delete(Insight)
                    .where(Insight.owner == settings.owner)
                    .where(Insight.domain == "fitness")
                )
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

    # ---- people (M10) ----
    @contextmanager
    def _locked_write(self):
        """One serialized write transaction. Holds the module process lock and,
        on PostgreSQL, a transaction-scoped advisory lock so overlapping syncs /
        manual edits across processes or hosts can never interleave. SQLite (tests)
        -> the advisory lock is a no-op."""
        from .config import settings

        with _CONTACTS_LOCK:
            with self._session() as s, s.begin():
                if s.get_bind().dialect.name == "postgresql":
                    s.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                              {"k": _advisory_key(settings.owner)})
                yield s

    def _state_row(self, s: Session) -> ContactsSyncState:
        from .config import settings

        row = s.scalars(
            select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
        ).first()
        if row is None:
            row = ContactsSyncState(owner=settings.owner)
            s.add(row)
            s.flush()
        return row

    def _person_row(self, s: Session, source: str, source_id: str) -> Person | None:
        from .config import settings

        return s.scalars(
            select(Person)
            .where(Person.owner == settings.owner)
            .where(Person.source == source)
            .where(Person.source_id == source_id)
        ).first()

    def _write_handles(self, s: Session, person_id: int,
                       handles: dict[tuple[str, str], bool]) -> None:
        from .config import settings

        s.execute(delete(PersonHandle).where(PersonHandle.person_id == person_id))
        for (kind, value), possible in handles.items():
            s.add(PersonHandle(owner=settings.owner, person_id=person_id,
                               kind=kind, value=(value or "")[:320], possible=bool(possible)))

    def _apply_person(self, s: Session, person: NormalizedPerson,
                      region: str) -> tuple[Person, bool]:
        """Get-or-create by (owner, source, source_id); write ONLY the sync-owned
        identity fields + phones/emails/meta and rebuild the handle index. Clears
        removed_from_source_at so a returning contact resurrects. CRM-native fields
        are never touched here. Returns (row, created)."""
        from .config import settings

        row = self._person_row(s, person.source, person.source_id)
        created = row is None
        if created:
            row = Person(owner=settings.owner, source=person.source,
                         source_id=person.source_id)
            s.add(row)
        row.display_name = _clean_name(person.display_name)
        row.first_name = _clean_name(person.first_name)
        row.last_name = _clean_name(person.last_name)
        row.nickname = _clean_name(person.nickname)
        row.organization = _clean_name(person.organization)
        row.job_title = _clean_name(person.job_title)
        # Photos: the reader hands us a TRANSIENT absolute path; persist only the
        # opaque, RELATIVE photo_key (contract: Photo storage). When a person's
        # photo changes, unlink the superseded file. Imports are function-local so
        # Task 3 stays self-contained (contact_photos lands in Task 5) and a
        # photoless person (photo_path is None) never touches the photos module.
        old_key = row.photo_key
        new_key = None
        if person.photo_path:
            from .providers import contact_photos
            new_key = contact_photos.key_for_path(person.photo_path)
        row.photo_key = new_key
        row.has_photo = bool(person.has_photo)
        if old_key and old_key != new_key:
            from .providers import contact_photos
            contact_photos.delete_photo(old_key, settings.contacts_photos_root())
        norm_phones, norm_emails, handles = _canon_entries(person.phones, person.emails, region)
        row.phones = norm_phones            # fresh list of fresh dicts -> change detected
        row.emails = norm_emails
        row.meta = {**(row.meta or {}), **(person.meta or {})}
        row.removed_from_source_at = None
        s.flush()
        self._write_handles(s, row.id, handles)
        return row, created

    def _reconcile_people(self, s: Session, source: str,
                          seen_source_ids: list[str], now: datetime) -> int:
        """Soft-delete synced people no longer present in the snapshot (never a
        hard delete; handle rows survive so history still resolves). Caller runs
        this ONLY for a clean COMPLETE_* read."""
        from .config import settings

        seen = set(seen_source_ids)
        flipped = 0
        rows = s.scalars(
            select(Person)
            .where(Person.owner == settings.owner)
            .where(Person.source == source)
            .where(Person.removed_from_source_at.is_(None))
        ).all()
        for row in rows:
            if row.source_id not in seen:
                row.removed_from_source_at = _to_utc(now)
                flipped += 1
        return flipped

    @_retry_integrity
    def apply_contacts_snapshot(self, snapshot: ContactsSnapshot,
                                now: datetime) -> SyncResult:
        """The one transactional entry the sync engine (Task 5) calls. In a single
        locked transaction: on a COMPLETE_* read upsert every person + rebuild
        handles, then reconcile soft-deletions IFF no per-record error occurred
        (else commit the good upserts and record status='partial', skipping
        reconcile). A non-COMPLETE read writes NO rows — it only records state;
        ACCESS_DENIED with existing rows marks the state 'stale' (never
        soft-deletes)."""
        from .config import settings

        now = _to_utc(now)
        complete = snapshot.status in (SnapshotStatus.COMPLETE_NONEMPTY,
                                       SnapshotStatus.COMPLETE_EMPTY)
        with self._locked_write() as s:
            state = self._state_row(s)
            region = state.normalization_region or settings.contacts_default_region

            if not complete:
                if snapshot.status == SnapshotStatus.ACCESS_DENIED:
                    active = s.scalar(
                        select(func.count()).select_from(Person)
                        .where(Person.owner == settings.owner)
                        .where(Person.source == "macos_contacts")
                        .where(Person.removed_from_source_at.is_(None))
                    ) or 0
                    result_status = "access_denied"
                    state_status = "stale" if active else "access_denied"
                    access = "denied"
                else:
                    result_status, state_status, access = _FAILED_MAP[snapshot.status]
                state.status = state_status
                state.access = access
                state.last_error = snapshot.error
                return SyncResult(status=result_status, access=access,
                                  last_sync_at=aware_utc(state.last_sync_at),
                                  last_error=snapshot.error)

            imported = updated = 0
            per_record_error = False
            seen: list[str] = []
            for person in snapshot.people:
                try:
                    with s.begin_nested():          # savepoint: a bad record can't poison the batch
                        _row, created = self._apply_person(s, person, region)
                    seen.append(person.source_id)
                    imported += int(created)
                    updated += int(not created)
                except (ValueError, TypeError):
                    # DATA-TRANSFORM error only (bad record shape / handle): drop
                    # this record, commit the rest, and degrade to 'partial' with
                    # reconcile skipped. Infrastructure/DB errors (SQLAlchemyError /
                    # OperationalError) are deliberately NOT caught here -> they
                    # propagate and the whole transaction rolls back atomically.
                    per_record_error = True
                    logger.exception("apply_contacts_snapshot: record failed (%s)",
                                     getattr(person, "source_id", "?"))

            removed = 0
            if not per_record_error:
                removed = self._reconcile_people(s, "macos_contacts", seen, now)
                state.status = "ready"
                state.last_error = None
                result_status = ("empty" if snapshot.status == SnapshotStatus.COMPLETE_EMPTY
                                 else "ok")
            else:
                state.status = "error"
                state.last_error = "partial apply: one or more contacts failed to import"
                result_status = "partial"

            if state.normalization_region is None:
                state.normalization_region = region
            state.access = "granted"
            state.last_sync_at = now
            result = SyncResult(status=result_status, access="granted",
                                imported=imported, updated=updated, removed=removed,
                                last_sync_at=now, last_error=state.last_error)
            # Surviving photo keys, for the post-commit orphan sweep below.
            keep_photo_keys = set(s.scalars(
                select(Person.photo_key)
                .where(Person.owner == settings.owner)
                .where(Person.photo_key.is_not(None))
            ).all())

        # After the transaction COMMITS: sweep superseded / rolled-back / orphaned
        # photo files that no surviving row references (contract: Photo storage —
        # cleanup on re-sync). Skipped when no photos exist, which keeps Task 3
        # self-contained (contact_photos lands in Task 5).
        if keep_photo_keys:
            from .providers import contact_photos
            contact_photos.cleanup_orphans(keep_photo_keys, settings.contacts_photos_root())
        return result

    @_retry_integrity
    def upsert_person(self, person: NormalizedPerson) -> dict:
        """Single-person get-or-create + reindex (its own locked transaction).
        Convenience for granular callers/tests; the batch sync path uses
        apply_contacts_snapshot."""
        from .config import settings

        with self._locked_write() as s:
            region = self._state_row(s).normalization_region or settings.contacts_default_region
            row, _created = self._apply_person(s, person, region)
            return _person_dict(row)

    def list_people(self, *, include_removed: bool = False, q: str | None = None,
                    limit: int = 50, cursor: str | None = None) -> dict:
        """Deterministic (display_name, id) keyset page. Bounded search `q`
        (case-insensitive substring over name/nickname/organization/job title,
        plus email addresses by prefix and phone numbers by digit fragment via
        the person_handle index -- see _handle_search_pattern).
        Returns {"items": [...], "next_cursor": str | None}."""
        from .config import settings

        limit = max(1, min(int(limit or 50), 200))
        stmt = select(Person).where(Person.owner == settings.owner)
        if not include_removed:
            stmt = stmt.where(Person.removed_from_source_at.is_(None))
        ql = (q or "").strip()[:100].lower()
        if ql:
            # `q` is literal text everywhere: escape it ONCE, here, and pass
            # escape= on every clause below -- see _escape_like.
            like = f"%{_escape_like(ql)}%"
            clauses = [
                func.lower(Person.display_name).like(like, escape=_LIKE_ESCAPE),
                func.lower(Person.nickname).like(like, escape=_LIKE_ESCAPE),
                func.lower(Person.organization).like(like, escape=_LIKE_ESCAPE),
                func.lower(Person.job_title).like(like, escape=_LIKE_ESCAPE),
            ]
            # Emails/phones live in JSON columns neither backend can search
            # portably, so search the canonical person_handle index instead. Its
            # values are already lower-cased/E.164 by app.identity, hence no
            # lower() here (which would also throw away the index). EXISTS rather
            # than a join: a person carrying three matching handles must still
            # come back as ONE row, and a joined duplicate would also corrupt the
            # keyset page size.
            handle_match = _handle_search_pattern(ql)
            if handle_match is not None:
                handle_like, handle_kind = handle_match
                handle_q = (
                    select(PersonHandle.id)
                    .where(PersonHandle.person_id == Person.id)
                    .where(PersonHandle.owner == settings.owner)
                    .where(PersonHandle.value.like(handle_like, escape=_LIKE_ESCAPE))
                )
                if handle_kind is not None:
                    handle_q = handle_q.where(PersonHandle.kind == handle_kind)
                clauses.append(handle_q.exists())
            stmt = stmt.where(or_(*clauses))
        if cursor:
            cname, cid = _decode_cursor(cursor)
            if cname is not None:
                stmt = stmt.where(or_(
                    Person.display_name > cname,
                    and_(Person.display_name == cname, Person.id > cid),
                ))
        stmt = stmt.order_by(Person.display_name.asc(), Person.id.asc()).limit(limit + 1)
        with self._session() as s:
            rows = s.scalars(stmt).all()
        next_cursor = None
        if len(rows) > limit:
            edge = rows[limit - 1]
            next_cursor = _encode_cursor(edge.display_name, edge.id)
            rows = rows[:limit]
        return {"items": [_person_dict(r) for r in rows], "next_cursor": next_cursor}

    def count_people(self, source: str | None = None) -> int:
        """Owner-scoped count of people, excluding soft-deleted rows
        (removed_from_source_at IS NULL). `source=None` counts every source;
        the connectors card passes source="macos_contacts" for its imported
        count."""
        from .config import settings

        stmt = (
            select(func.count())
            .select_from(Person)
            .where(Person.owner == settings.owner)
            .where(Person.removed_from_source_at.is_(None))
        )
        if source is not None:
            stmt = stmt.where(Person.source == source)
        with self._session() as s:
            return int(s.scalar(stmt) or 0)

    def get_person(self, person_id: int) -> dict | None:
        """Fetch by id (owner-scoped). Returns soft-deleted rows too — callers
        decide; list_people hides them."""
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            return _person_dict(row) if row is not None else None

    def _apply_patch(self, s: Session, row: Person, patch: dict, region: str,
                     *, manual: bool) -> None:
        """Source-aware CRUD field application.
        - Imported rows: sync-owned identity fields are silently dropped (read-only).
        - Non-nullable fields: an explicit None is ignored (PATCH never 500s);
          nullable CRM-native fields: an explicit None clears them.
        Rebuilds handles by reassigning fresh normalized lists when phones/emails
        change (never post-flush nested mutation)."""
        new_phones = new_emails = None
        for key, value in (patch or {}).items():
            if key in _PERSON_IMMUTABLE:
                continue
            if not manual and key in _PERSON_SYNC_FIELDS:     # imported identity read-only
                continue
            if key == "phones":
                if value is not None:
                    new_phones = value
            elif key == "emails":
                if value is not None:
                    new_emails = value
            elif key in _PERSON_NAME_FIELDS:
                if value is not None:                          # non-nullable -> ignore None
                    setattr(row, key, _clean_name(value))
            elif key == "relationship":
                row.relationship = None if value is None else _clean_label(value, 32)
            elif key == "relationship_strength":
                row.relationship_strength = None if value is None else _clean_strength(value)
            elif key == "notes":
                row.notes = None if value is None else str(value)
            elif key == "pinned":
                if value is not None:
                    row.pinned = bool(value)
            elif key == "last_contacted_at":
                row.last_contacted_at = None if value is None else _to_utc(value)
            # unknown keys (and has_photo/photo_key/source) ignored -> PATCH cannot 500
        if new_phones is not None or new_emails is not None:
            phones_src = new_phones if new_phones is not None else (row.phones or [])
            emails_src = new_emails if new_emails is not None else (row.emails or [])
            s.flush()
            norm_phones, norm_emails, handles = _canon_entries(phones_src, emails_src, region)
            row.phones = norm_phones
            row.emails = norm_emails
            s.flush()
            self._write_handles(s, row.id, handles)

    @_retry_integrity
    def create_person(self, data: dict) -> dict:
        """Manual (source='manual') create; server-generates source_id. Rejects a
        whitespace-only display_name."""
        import uuid

        from .config import settings

        display = _clean_name((data or {}).get("display_name", ""))
        if not display:
            raise ValueError("display_name must not be blank")
        with self._locked_write() as s:
            region = self._state_row(s).normalization_region or settings.contacts_default_region
            row = Person(owner=settings.owner, source="manual",
                         source_id=uuid.uuid4().hex, display_name=display)
            s.add(row)
            s.flush()
            rest = {k: v for k, v in (data or {}).items() if k != "display_name"}
            self._apply_patch(s, row, rest, region, manual=True)
            return _person_dict(row)

    @_retry_integrity
    def update_person(self, person_id: int, patch: dict) -> dict | None:
        from .config import settings

        with self._locked_write() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            if row is None:
                return None
            region = self._state_row(s).normalization_region or settings.contacts_default_region
            clean = dict(patch or {})
            # Never blank an existing name with a whitespace-only value.
            if clean.get("display_name") is not None and not _clean_name(clean["display_name"]):
                clean.pop("display_name")
            self._apply_patch(s, row, clean, region, manual=(row.source == "manual"))
            return _person_dict(row)

    @_retry_integrity
    def delete_person(self, person_id: int) -> bool:
        """Hard-delete a manual row (its person_handle rows cascade). An imported
        row is never hard-deleted here — it is tombstoned (soft-deleted) so history
        still resolves; a later authoritative sync resurrects it if the source
        contact still exists. Permanent removal of imported data is the
        Disconnect/Forget lifecycle."""
        from .config import settings

        with self._locked_write() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            if row is None:
                return False
            if row.source == "manual":
                s.delete(row)
            else:
                row.removed_from_source_at = utcnow()
            return True

    def resolve_handle(self, handle: str) -> list[dict]:
        """Every person carrying this handle (shared handles -> multiple), most
        recently contacted first, INCLUDING soft-deleted people so historical
        messages still resolve. Canonicalizes with the PERSISTED
        normalization_region (falls back to settings), never the live locale."""
        from .config import settings
        from .identity import canon_handle

        with self._session() as s:
            state = s.scalars(
                select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
            ).first()
            region = (state.normalization_region if state else None) \
                or settings.contacts_default_region
            canon = canon_handle(handle, region)
            if canon is None:
                return []
            rows = s.scalars(
                select(Person)
                .join(PersonHandle, PersonHandle.person_id == Person.id)
                .where(Person.owner == settings.owner)
                .where(PersonHandle.value == canon["normalized"])
                .order_by(case((Person.last_contacted_at.is_(None), 1), else_=0),
                          Person.last_contacted_at.desc(),
                          Person.updated_at.desc(),
                          Person.id.desc())
            ).all()
            return [_person_dict(r) for r in rows]

    @_retry_integrity
    def get_contacts_state(self) -> dict:
        """Get-or-create the single contacts_sync_state row for the owner."""
        with self._session() as s, s.begin():
            return _state_dict(self._state_row(s))

    @_retry_integrity
    def set_contacts_state(self, patch: dict) -> dict:
        """Patch consent/lifecycle fields (enable/disconnect/status/region/errors).
        Datetimes are stored aware-UTC. The router (Task 6) drives enable/disconnect;
        the sync apply writes status/access/last_sync_at itself."""
        with self._locked_write() as s:
            st = self._state_row(s)
            for key in ("enabled", "status", "access", "normalization_region", "last_error"):
                if key in patch:
                    setattr(st, key, patch[key])
            for key in ("last_sync_at", "enabled_at"):
                if key in patch:
                    setattr(st, key, _to_utc(patch[key]) if patch[key] is not None else None)
            return _state_dict(st)

    def set_contacts_enabled(self, enabled: bool, *, region: str | None = None,
                             now: datetime | None = None) -> dict:
        """Thin consent toggle over set_contacts_state (used by the Task 10 tests
        and any caller that just flips the flag). Enabling stamps enabled_at +
        status 'ready' and, when given, persists normalization_region; disabling
        sets status 'disabled'. Delegates locking/serialization to
        set_contacts_state."""
        patch: dict = {"enabled": bool(enabled)}
        if enabled:
            patch["status"] = "ready"
            patch["enabled_at"] = now or utcnow()
            if region:
                patch["normalization_region"] = region
        else:
            patch["status"] = "disabled"
        return self.set_contacts_state(patch)

    # ---- people photo key (M10) ----
    # NOTE: the paginated/searchable people list is `store.list_people(...)` from
    # Task 3 (same `{items, next_cursor}` shape, and it searches
    # name/nickname/organization/job_title). The router calls it directly; do NOT
    # add a second `search_people` here.
    def get_person_photo_key(self, person_id: int) -> str | None:
        """The relative photo_key (opaque, stored in the configured database), or
        None. The router resolves it against the photos root with a containment
        check; the key itself is never a filesystem path we trust blindly."""
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            return row.photo_key if row is not None else None

    # ---- contacts consent lifecycle (M10) ----
    def enable_contacts(self, *, region: str) -> dict:
        """Connect: enabled=True, stamp enabled_at, and persist normalization_region
        ONCE (a later locale change must never retroactively re-resolve existing
        handles). Does not read contacts here — the caller kicks a sync."""
        with self._locked_write() as s:
            row = self._state_row(s)
            row.enabled = True
            row.enabled_at = utcnow()
            if not row.normalization_region:
                row.normalization_region = region
            if row.status in (None, "disabled"):
                row.status = "ready"
            s.flush()
            return _state_dict(row)

    def disconnect_contacts(self) -> dict:
        """Disconnect: stop future reads/syncs. Does NOT delete rows — existing CRM
        data is preserved; normalization_region is kept."""
        with self._locked_write() as s:
            row = self._state_row(s)
            row.enabled = False
            row.status = "disabled"
            s.flush()
            return _state_dict(row)

    @_retry_integrity
    def forget_contacts(self) -> dict:
        """Delete imported (source='macos_contacts') rows + their handle rows +
        extracted photos, then disable. CRM-native survival rule: a person carrying
        ANY CRM-native data (relationship/strength/notes/pinned/last_contacted_at)
        is converted to a source='manual' tombstone that keeps display_name + the
        CRM-native fields (identity fields, handle index and photo cleared);
        people with no CRM-native data are fully deleted."""
        import uuid

        from .config import settings

        photos_root = settings.contacts_photos_root()
        removed_keys: list[str] = []
        with self._locked_write() as s:
            rows = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.source == "macos_contacts")
            ).all()
            for row in rows:
                if row.photo_key:
                    removed_keys.append(row.photo_key)
                has_crm = any((row.relationship, row.relationship_strength, row.notes,
                               row.pinned, row.last_contacted_at))
                if has_crm:
                    s.execute(delete(PersonHandle).where(PersonHandle.person_id == row.id))
                    row.source = "manual"
                    row.source_id = uuid.uuid4().hex
                    row.first_name = ""
                    row.last_name = ""
                    row.nickname = ""
                    row.organization = ""
                    row.job_title = ""
                    row.phones = []
                    row.emails = []
                    row.photo_key = None
                    row.has_photo = False
                    row.removed_from_source_at = None
                else:
                    s.delete(row)  # person_handle rows cascade
            state = self._state_row(s)
            state.enabled = False
            state.status = "disabled"
            state.last_error = None
            s.flush()
            result = _state_dict(state)
        _delete_photo_files(photos_root, removed_keys)   # after commit; never fatal
        return result

    def _owned_email_row(self, s: Session, email_id: int) -> Email | None:
        from .config import settings

        return s.scalars(
            select(Email)
            .where(Email.id == email_id)
            .where(Email.owner == settings.owner)
        ).first()

    def set_email_flags(
        self, email_id: int, unread: bool | None = None, starred: bool | None = None
    ) -> dict | None:
        """Owner-scoped read-state/star patch. A None field is left unchanged;
        called by the router AFTER GoogleProvider.modify_labels has already
        succeeded (confirm-first — this method does no Gmail I/O itself)."""
        with self._session() as s, s.begin():
            row = self._owned_email_row(s, email_id)
            if row is None:
                return None
            if unread is not None:
                row.unread = unread
            if starred is not None:
                row.starred = starred
            s.flush()
            return _email_dict(row)

    def set_email_labels(self, email_id: int, label_ids: list[str]) -> dict | None:
        """Owner-scoped label replace. The router computes the full post-add/
        remove list from Gmail's response; unread/starred are re-derived here
        from UNREAD/STARRED membership in the new list so the two stay
        consistent with whatever labels now apply."""
        with self._session() as s, s.begin():
            row = self._owned_email_row(s, email_id)
            if row is None:
                return None
            row.label_ids = list(label_ids)
            row.unread = "UNREAD" in label_ids
            row.starred = "STARRED" in label_ids
            s.flush()
            return _email_dict(row)

    def delete_email(self, email_id: int) -> bool:
        """Owner-scoped single-row delete, called by the router AFTER
        GoogleProvider.trash_message has already succeeded (confirm-first)."""
        with self._session() as s, s.begin():
            row = self._owned_email_row(s, email_id)
            if row is None:
                return False
            s.delete(row)
            return True

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

    # ---- moodle ----
    def _moodle_row(self, s: Session, model, source: str, source_id: str):
        from .config import settings

        return s.scalars(
            select(model)
            .where(model.owner == settings.owner)
            .where(model.source == source)
            .where(model.source_id == source_id)
        ).first()

    @_retry_integrity
    def upsert_moodle_course(self, c: NormalizedCourse) -> dict:
        """Get-or-create by (owner, source, source_id); writes metadata every
        pass so re-sync keeps the enrolment summary fresh."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._moodle_row(s, MoodleCourse, c.source, c.source_id)
            if row is None:
                row = MoodleCourse(owner=settings.owner, source=c.source,
                                   source_id=c.source_id)
                s.add(row)
            row.shortname = c.shortname
            row.fullname = c.fullname
            row.progress = c.progress
            row.start_at = _to_utc(c.start_at) if c.start_at else None
            row.end_at = _to_utc(c.end_at) if c.end_at else None
            row.last_access_at = _to_utc(c.last_access_at) if c.last_access_at else None
            row.hidden = c.hidden
            s.flush()
            return _moodle_course_dict(row)

    @_retry_integrity
    def upsert_moodle_deadline(self, d: NormalizedDeadline) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            row = self._moodle_row(s, MoodleDeadline, d.source, d.source_id)
            if row is None:
                row = MoodleDeadline(owner=settings.owner, source=d.source,
                                     source_id=d.source_id)
                s.add(row)
            row.course_id = d.course_id
            row.name = d.name
            row.module_name = d.module_name
            row.event_type = d.event_type
            row.due_at = _to_utc(d.due_at)
            row.overdue = d.overdue
            row.url = d.url
            s.flush()
            return _moodle_deadline_dict(row)

    @_retry_integrity
    def upsert_moodle_assignment(self, a: NormalizedAssignment) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            row = self._moodle_row(s, MoodleAssignment, a.source, a.source_id)
            if row is None:
                row = MoodleAssignment(owner=settings.owner, source=a.source,
                                       source_id=a.source_id)
                s.add(row)
            row.course_id = a.course_id
            row.cmid = a.cmid
            row.name = a.name
            row.due_at = _to_utc(a.due_at) if a.due_at else None
            row.cutoff_at = _to_utc(a.cutoff_at) if a.cutoff_at else None
            row.grade_max = a.grade_max
            row.submission_status = a.submission_status
            row.grading_status = a.grading_status
            row.graded = a.graded
            s.flush()
            return _moodle_assignment_dict(row)

    @_retry_integrity
    def upsert_moodle_grade(self, g: NormalizedGrade) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            row = self._moodle_row(s, MoodleGrade, g.source, g.source_id)
            if row is None:
                row = MoodleGrade(owner=settings.owner, source=g.source,
                                  source_id=g.source_id)
                s.add(row)
            row.course_id = g.course_id
            row.item_name = g.item_name
            row.item_type = g.item_type
            row.grade_formatted = g.grade_formatted
            row.grade_raw = g.grade_raw
            row.grade_min = g.grade_min
            row.grade_max = g.grade_max
            row.graded_at = _to_utc(g.graded_at) if g.graded_at else None
            s.flush()
            return _moodle_grade_dict(row)

    @_retry_integrity
    def upsert_moodle_announcement(self, a: NormalizedAnnouncement) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            row = self._moodle_row(s, MoodleAnnouncement, a.source, a.source_id)
            if row is None:
                row = MoodleAnnouncement(owner=settings.owner, source=a.source,
                                         source_id=a.source_id)
                s.add(row)
            row.course_id = a.course_id
            row.forum_id = a.forum_id
            row.subject = a.subject
            row.author = a.author
            row.created_at = _to_utc(a.created_at) if a.created_at else None
            row.summary_html = a.summary_html
            row.url = a.url
            s.flush()
            return _moodle_announcement_dict(row)

    @_retry_integrity
    def upsert_moodle_notification(self, n: NormalizedNotification) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            row = self._moodle_row(s, MoodleNotification, n.source, n.source_id)
            if row is None:
                row = MoodleNotification(owner=settings.owner, source=n.source,
                                         source_id=n.source_id)
                s.add(row)
            row.subject = n.subject
            row.full_message = n.full_message
            row.context_url = n.context_url
            row.created_at = _to_utc(n.created_at) if n.created_at else None
            row.read = n.read
            s.flush()
            return _moodle_notification_dict(row)

    def moodle_courses(self) -> list[dict]:
        from .config import settings

        with self._session() as s:
            rows = s.scalars(
                select(MoodleCourse)
                .where(MoodleCourse.owner == settings.owner)
                .order_by(MoodleCourse.shortname)
            ).all()
            return [_moodle_course_dict(c) for c in rows]

    def moodle_deadlines(self, days_ahead: int | None = None) -> list[dict]:
        """Deadlines ordered by due_at asc. With days_ahead, only those due in
        [now, now + days_ahead)."""
        from .config import settings

        with self._session() as s:
            q = (
                select(MoodleDeadline)
                .where(MoodleDeadline.owner == settings.owner)
                .order_by(MoodleDeadline.due_at)
            )
            if days_ahead is not None:
                now = utcnow()
                horizon = now + timedelta(days=days_ahead)
                q = q.where(MoodleDeadline.due_at >= now).where(
                    MoodleDeadline.due_at < horizon
                )
            rows = s.scalars(q).all()
            return [_moodle_deadline_dict(d) for d in rows]

    def moodle_assignments(self, course_id: str | None = None) -> list[dict]:
        from .config import settings

        with self._session() as s:
            q = (
                select(MoodleAssignment)
                .where(MoodleAssignment.owner == settings.owner)
                .order_by(MoodleAssignment.due_at)
            )
            if course_id is not None:
                q = q.where(MoodleAssignment.course_id == course_id)
            rows = s.scalars(q).all()
            return [_moodle_assignment_dict(a) for a in rows]

    def moodle_calendar_events(
        self, window_start: datetime, window_end: datetime
    ) -> list[dict]:
        """Read-time projection (contract §H): Moodle deadlines whose due_at
        falls in [window_start, window_end) rendered as calendar occurrences
        (_occurrence_dict shape) tagged source='moodle'/editable=False. These
        are NOT rows in the events table — events_between appends them at read
        time so Home/Calendar show them read-only. tint='grape' and a
        synthetic 'moodle:<source_id>' id keep them visually + structurally
        distinct from local events (whose ids are ints)."""
        shortnames = {c["source_id"]: c["shortname"] for c in self.moodle_courses()}
        out: list[dict] = []
        for d in self.moodle_deadlines():
            start = d["due_at"]
            if start is None or not (window_start <= start < window_end):
                continue
            end = start + timedelta(hours=1)
            short = shortnames.get(d["course_id"], "")
            title = f"{d['name']} · {short}" if short else d["name"]
            out.append({
                "id": f"moodle:{d['source_id']}",
                "title": title,
                "start": start,
                "end": end,
                "tint": "grape",
                "location": "",
                "description": "",
                "recurring": False,
                "recurrence_label": None,
                "at": clock(start),
                "source": "moodle",
                "editable": False,
            })
        return out

    def moodle_tasks(self) -> list[dict]:
        """Read-time projection (contract §H): Moodle assignments that carry a
        due date rendered as tasks (_task_dict shape) tagged
        source='moodle'/editable=False. done mirrors submission_status
        (submitted/reopened => done). group/list='School', prio='med'.
        due/late come from task_due_display so the UI's overdue styling
        matches local tasks. Appended by list_tasks at read time — NOT rows in
        the tasks table. The 'moodle:<source_id>' id can never be edited or
        deleted through the int-typed /api/tasks/{id} routes."""
        shortnames = {c["source_id"]: c["shortname"] for c in self.moodle_courses()}
        now = utcnow()
        out: list[dict] = []
        for a in self.moodle_assignments():
            due_at = a["due_at"]
            if due_at is None:
                continue
            deadline = due_at.date()
            done = a["submission_status"] in {"submitted", "reopened"}
            due, late = task_due_display(deadline, done, None)
            short = shortnames.get(a["course_id"], "")
            label = f"{a['name']} · {short}" if short else a["name"]
            out.append({
                "id": f"moodle:{a['source_id']}",
                "label": label,
                "done": done,
                "group": "School",
                "deadline": deadline,
                "prio": "med",
                "list": "School",
                "description": "",
                "subtasks": [],
                "labels": [],
                "reminders": [],
                "files": [],
                "recurrence": None,
                "recurrence_label": None,
                "due": due,
                "late": late,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "source": "moodle",
                "editable": False,
            })
        return out

    def moodle_grades(self, course_id: str | None = None) -> list[dict]:
        from .config import settings

        with self._session() as s:
            q = (
                select(MoodleGrade)
                .where(MoodleGrade.owner == settings.owner)
                .order_by(MoodleGrade.id)
            )
            if course_id is not None:
                q = q.where(MoodleGrade.course_id == course_id)
            rows = s.scalars(q).all()
            return [_moodle_grade_dict(g) for g in rows]

    def moodle_announcements(self, course_id: str | None = None) -> list[dict]:
        from .config import settings

        with self._session() as s:
            q = (
                select(MoodleAnnouncement)
                .where(MoodleAnnouncement.owner == settings.owner)
                .order_by(MoodleAnnouncement.created_at.desc())
            )
            if course_id is not None:
                q = q.where(MoodleAnnouncement.course_id == course_id)
            rows = s.scalars(q).all()
            return [_moodle_announcement_dict(a) for a in rows]

    def moodle_notifications(self) -> list[dict]:
        from .config import settings

        with self._session() as s:
            rows = s.scalars(
                select(MoodleNotification)
                .where(MoodleNotification.owner == settings.owner)
                .order_by(MoodleNotification.created_at.desc())
            ).all()
            return [_moodle_notification_dict(n) for n in rows]

    def delete_moodle_data(self, source: str) -> bool:
        """Disconnect hook (MoodleProvider.on_disconnect): delete every moodle_*
        row where (owner, source). Returns True iff any row was deleted.
        Separate from delete_provider_data (which owns the provider_accounts
        row); the shared router deletes the account, this deletes the domain
        data. Mirrors delete_email_data."""
        from .config import settings

        deleted = False
        with self._session() as s, s.begin():
            for model in (
                MoodleCourse,
                MoodleDeadline,
                MoodleAssignment,
                MoodleGrade,
                MoodleAnnouncement,
                MoodleNotification,
            ):
                for row in s.scalars(
                    select(model)
                    .where(model.owner == settings.owner)
                    .where(model.source == source)
                ):
                    s.delete(row)
                    deleted = True
        return deleted

    # ---- finance ----
    def _finance_item_row(self, s: Session, item_id: str) -> FinanceItem | None:
        from .config import settings
        return s.scalars(
            select(FinanceItem)
            .where(FinanceItem.owner == settings.owner)
            .where(FinanceItem.source == "plaid")
            .where(FinanceItem.source_id == item_id)
        ).first()

    @_retry_integrity
    def upsert_finance_item(self, item: NormalizedItem, access_token: str) -> dict:
        from .config import settings
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item.item_id)
            if row is None:
                row = FinanceItem(owner=settings.owner, source="plaid",
                                  source_id=item.item_id)
                s.add(row)
            row.access_token = access_token
            row.institution_id = item.institution_id
            row.institution_name = item.institution_name
            row.products = list(item.products or [])
            row.status = "active"
            s.flush()
            return _finance_item_dict(row)

    def list_finance_items(self) -> list[dict]:
        from .config import settings
        with self._session() as s:
            rows = s.scalars(
                select(FinanceItem)
                .where(FinanceItem.owner == settings.owner)
                .order_by(FinanceItem.id)
            ).all()
            return [_finance_item_dict(r) for r in rows]

    def get_finance_item(self, item_id: str) -> dict | None:
        with self._session() as s:
            row = self._finance_item_row(s, item_id)
            return _finance_item_dict(row) if row else None

    def get_finance_item_token(self, item_id: str) -> str | None:
        """Server-side only — the access_token for one Item (used by the sync)."""
        with self._session() as s:
            row = self._finance_item_row(s, item_id)
            return row.access_token if row else None

    def set_finance_item_status(self, item_id: str, status: str) -> None:
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is not None:
                row.status = status

    def set_finance_item_cursor(self, item_id: str, cursor: str | None) -> None:
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is not None:
                row.cursor = cursor

    def set_finance_item_synced(self, item_id: str, when: datetime | None = None) -> None:
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is not None:
                row.last_sync_at = _to_utc(when) if when else utcnow()

    def get_finance_item_cursor(self, item_id: str) -> str | None:
        """Server-side only — the /transactions/sync cursor for one Item."""
        with self._session() as s:
            row = self._finance_item_row(s, item_id)
            return row.cursor if row else None

    def delete_finance_item(self, item_id: str) -> bool:
        """Disconnect one Item: delete it + its accounts/transactions/holdings,
        then prune securities no surviving holding references. Returns True iff
        the Item existed."""
        from .config import settings
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is None:
                return False
            s.delete(row)
            for model in (FinanceAccount, FinanceTransaction, FinanceHolding,
                          FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction):
                for r in s.scalars(
                    select(model)
                    .where(model.owner == settings.owner)
                    .where(model.item_id == item_id)
                ):
                    s.delete(r)
            # Prune orphan securities (nothing references them any more). A
            # security can be referenced by a surviving holding OR by a surviving
            # item's investment transaction — union both so we never prune a
            # security still in use by a DIFFERENT item.
            live_sec_ids = set(s.scalars(
                select(FinanceHolding.security_id)
                .where(FinanceHolding.owner == settings.owner)
            ).all())
            live_sec_ids |= set(s.scalars(
                select(FinanceInvestmentTransaction.security_id)
                .where(FinanceInvestmentTransaction.owner == settings.owner)
            ).all())
            for sec in s.scalars(
                select(FinanceSecurity).where(FinanceSecurity.owner == settings.owner)
            ):
                if sec.source_id not in live_sec_ids:
                    s.delete(sec)
            return True

    def finance_status(self) -> dict:
        items = self.list_finance_items()
        return {"connected": len(items) > 0, "items": items}

    def _finance_account_row(self, s: Session, source_id: str) -> FinanceAccount | None:
        from .config import settings
        return s.scalars(
            select(FinanceAccount)
            .where(FinanceAccount.owner == settings.owner)
            .where(FinanceAccount.source == "plaid")
            .where(FinanceAccount.source_id == source_id)
        ).first()

    @_retry_integrity
    def upsert_finance_account(self, a: NormalizedAccount) -> dict:
        from .config import settings
        with self._session() as s, s.begin():
            row = self._finance_account_row(s, a.source_id)
            if row is None:
                row = FinanceAccount(owner=settings.owner, source="plaid",
                                     source_id=a.source_id)
                s.add(row)
            row.item_id = a.item_id
            row.name = a.name
            row.official_name = a.official_name
            row.mask = a.mask
            row.type = a.type
            row.subtype = a.subtype
            row.current_balance = a.current_balance
            row.available_balance = a.available_balance
            row.iso_currency = a.iso_currency
            s.flush()
            return _finance_account_dict(row)

    def list_finance_accounts(self) -> list[dict]:
        from .config import settings
        with self._session() as s:
            rows = s.scalars(
                select(FinanceAccount)
                .where(FinanceAccount.owner == settings.owner)
                .order_by(FinanceAccount.id)
            ).all()
            return [_finance_account_dict(a) for a in rows]

    @_retry_integrity
    def upsert_finance_transaction(self, t: NormalizedTransaction) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceTransaction)
                .where(FinanceTransaction.owner == settings.owner)
                .where(FinanceTransaction.source == "plaid")
                .where(FinanceTransaction.source_id == t.source_id)
            ).first()
            if row is None:
                row = FinanceTransaction(owner=settings.owner, source="plaid",
                                         source_id=t.source_id)
                s.add(row)
            row.account_id = t.account_id
            row.item_id = t.item_id
            row.name = t.name
            row.merchant_name = t.merchant_name
            row.amount = t.amount
            row.iso_currency = t.iso_currency
            row.date = t.date
            row.authorized_date = t.authorized_date
            row.pending = t.pending
            row.category_primary = t.category_primary
            row.category_detailed = t.category_detailed
            row.payment_channel = t.payment_channel

    def apply_transaction_delta(self, delta: TransactionsDelta) -> int:
        """Apply one /transactions/sync page: upsert added+modified by
        transaction_id, delete removed. Returns rows added+modified."""
        from .config import settings
        for t in delta.added:
            self.upsert_finance_transaction(t)
        for t in delta.modified:
            self.upsert_finance_transaction(t)
        if delta.removed:
            with self._session() as s, s.begin():
                for tid in delta.removed:
                    row = s.scalars(
                        select(FinanceTransaction)
                        .where(FinanceTransaction.owner == settings.owner)
                        .where(FinanceTransaction.source == "plaid")
                        .where(FinanceTransaction.source_id == tid)
                    ).first()
                    if row is not None:
                        s.delete(row)
        return len(delta.added) + len(delta.modified)

    def finance_transactions(self, days: int | None = None, account_id: str | None = None,
                             category: str | None = None) -> list[dict]:
        from .config import settings
        with self._session() as s:
            q = (
                select(FinanceTransaction)
                .where(FinanceTransaction.owner == settings.owner)
                .order_by(FinanceTransaction.date.desc(), FinanceTransaction.id.desc())
            )
            if days is not None:
                cutoff = (utcnow() - timedelta(days=days)).date()
                q = q.where(FinanceTransaction.date >= cutoff)
            if account_id is not None:
                q = q.where(FinanceTransaction.account_id == account_id)
            if category is not None:
                q = q.where(FinanceTransaction.category_primary == category)
            return [_finance_transaction_dict(t) for t in s.scalars(q).all()]

    @_retry_integrity
    def upsert_finance_security(self, sec: NormalizedSecurity) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceSecurity)
                .where(FinanceSecurity.owner == settings.owner)
                .where(FinanceSecurity.source == "plaid")
                .where(FinanceSecurity.source_id == sec.source_id)
            ).first()
            if row is None:
                row = FinanceSecurity(owner=settings.owner, source="plaid",
                                      source_id=sec.source_id)
                s.add(row)
            row.name = sec.name
            row.ticker_symbol = sec.ticker_symbol
            row.type = sec.type
            row.close_price = sec.close_price
            row.iso_currency = sec.iso_currency
            row.is_cash_equivalent = sec.is_cash_equivalent

    @_retry_integrity
    def upsert_finance_holding(self, h: NormalizedHolding) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceHolding)
                .where(FinanceHolding.owner == settings.owner)
                .where(FinanceHolding.account_id == h.account_id)
                .where(FinanceHolding.security_id == h.security_id)
            ).first()
            if row is None:
                row = FinanceHolding(owner=settings.owner, account_id=h.account_id,
                                     security_id=h.security_id)
                s.add(row)
            row.item_id = h.item_id
            row.quantity = h.quantity
            row.cost_basis = h.cost_basis
            row.institution_value = h.institution_value
            row.institution_price = h.institution_price
            row.iso_currency = h.iso_currency

    @_retry_integrity
    def upsert_finance_recurring(self, r) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceRecurring)
                .where(FinanceRecurring.owner == settings.owner)
                .where(FinanceRecurring.source == "plaid")
                .where(FinanceRecurring.source_id == r.source_id)
            ).first()
            if row is None:
                row = FinanceRecurring(owner=settings.owner, source="plaid", source_id=r.source_id)
                s.add(row)
            row.item_id = r.item_id
            row.account_id = r.account_id
            row.stream_type = r.stream_type
            row.description = r.description
            row.merchant_name = r.merchant_name
            row.category_primary = r.category_primary
            row.category_detailed = r.category_detailed
            row.average_amount = r.average_amount
            row.last_amount = r.last_amount
            row.frequency = r.frequency
            row.first_date = r.first_date
            row.last_date = r.last_date
            row.predicted_next_date = r.predicted_next_date
            row.is_active = r.is_active
            row.status = r.status
            row.iso_currency = r.iso_currency

    @_retry_integrity
    def upsert_finance_liability(self, l) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceLiability)
                .where(FinanceLiability.owner == settings.owner)
                .where(FinanceLiability.source == "plaid")
                .where(FinanceLiability.source_id == l.source_id)
            ).first()
            if row is None:
                row = FinanceLiability(owner=settings.owner, source="plaid", source_id=l.source_id)
                s.add(row)
            row.item_id = l.item_id
            row.account_id = l.account_id
            row.liability_type = l.liability_type
            row.last_statement_balance = l.last_statement_balance
            row.minimum_payment = l.minimum_payment
            row.next_payment_due_date = l.next_payment_due_date
            row.last_payment_amount = l.last_payment_amount
            row.last_payment_date = l.last_payment_date
            row.apr_percentage = l.apr_percentage
            row.iso_currency = l.iso_currency

    @_retry_integrity
    def upsert_finance_investment_transaction(self, it) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceInvestmentTransaction)
                .where(FinanceInvestmentTransaction.owner == settings.owner)
                .where(FinanceInvestmentTransaction.source == "plaid")
                .where(FinanceInvestmentTransaction.source_id == it.source_id)
            ).first()
            if row is None:
                row = FinanceInvestmentTransaction(owner=settings.owner, source="plaid",
                                                   source_id=it.source_id)
                s.add(row)
            row.item_id = it.item_id
            row.account_id = it.account_id
            row.security_id = it.security_id
            row.type = it.type
            row.subtype = it.subtype
            row.name = it.name
            row.quantity = it.quantity
            row.amount = it.amount
            row.price = it.price
            row.fees = it.fees
            row.date = it.date
            row.iso_currency = it.iso_currency

    def finance_holdings(self) -> list[dict]:
        """Holdings joined to their securities, ordered by value desc."""
        from .config import settings
        with self._session() as s:
            secs = {
                x.source_id: x for x in s.scalars(
                    select(FinanceSecurity).where(FinanceSecurity.owner == settings.owner)
                ).all()
            }
            rows = s.scalars(
                select(FinanceHolding)
                .where(FinanceHolding.owner == settings.owner)
                .order_by(FinanceHolding.institution_value.desc())
            ).all()
            out = []
            for h in rows:
                sec = secs.get(h.security_id)
                out.append({
                    "id": h.id,
                    "account_id": h.account_id,
                    "security_id": h.security_id,
                    "name": sec.name if sec else h.security_id,
                    "ticker": (sec.ticker_symbol if sec else None),
                    "type": (sec.type if sec else ""),
                    "is_crypto": bool(sec and sec.type == "cryptocurrency"),
                    "quantity": _dec_to_float(h.quantity),
                    "value": _dec_to_float(h.institution_value),
                    "price": _dec_to_float(h.institution_price),
                    "currency": h.iso_currency,
                })
            return out

    def finance_investment_transactions(self, days: int | None = None) -> list[dict]:
        """Investment buys/sells/dividends joined to securities, newest first."""
        from .config import settings
        with self._session() as s:
            secs = {
                x.source_id: x for x in s.scalars(
                    select(FinanceSecurity).where(FinanceSecurity.owner == settings.owner)
                ).all()
            }
            q = (
                select(FinanceInvestmentTransaction)
                .where(FinanceInvestmentTransaction.owner == settings.owner)
                .order_by(FinanceInvestmentTransaction.date.desc(),
                          FinanceInvestmentTransaction.id.desc())
            )
            if days is not None:
                cutoff = (utcnow() - timedelta(days=days)).date()
                q = q.where(FinanceInvestmentTransaction.date >= cutoff)
            rows = s.scalars(q).all()
        out = []
        for t in rows:
            sec = secs.get(t.security_id)
            out.append({
                "type": t.type,
                "name": t.name or (sec.name if sec else t.security_id),
                "ticker": (sec.ticker_symbol if sec else None),
                "quantity": _dec_to_float(t.quantity),
                "amount": _dec_to_float(t.amount),
                "price": _dec_to_float(t.price),
                "date": t.date.isoformat() if t.date else None,
                "currency": t.iso_currency,
            })
        return out

    def finance_subscriptions(self) -> list[dict]:
        """Active recurring OUTFLOW streams classified 'subscription', by next date."""
        from .config import settings
        with self._session() as s:
            rows = s.scalars(
                select(FinanceRecurring)
                .where(FinanceRecurring.owner == settings.owner)
                .where(FinanceRecurring.stream_type == "outflow")
                .where(FinanceRecurring.is_active.is_(True))
            ).all()
        out = []
        for r in rows:
            if recurring_kind(r.category_primary, r.category_detailed) != "subscription":
                continue
            out.append({
                "name": r.merchant_name or r.description,
                "merchant_name": r.merchant_name,
                "amount": _dec_to_float(r.average_amount),
                "frequency": r.frequency,
                "next_date": r.predicted_next_date.isoformat() if r.predicted_next_date else None,
                "category": r.category_primary,
            })
        out.sort(key=lambda x: (x["next_date"] or "9999-12-31"))
        return out

    def finance_bills(self) -> list[dict]:
        """Recurring 'bill' streams merged with liabilities (statement/due), by due date."""
        from .config import settings
        with self._session() as s:
            streams = s.scalars(
                select(FinanceRecurring)
                .where(FinanceRecurring.owner == settings.owner)
                .where(FinanceRecurring.stream_type == "outflow")
                .where(FinanceRecurring.is_active.is_(True))
            ).all()
            liabs = s.scalars(
                select(FinanceLiability).where(FinanceLiability.owner == settings.owner)
            ).all()
            accts = {
                a.source_id: a for a in s.scalars(
                    select(FinanceAccount).where(FinanceAccount.owner == settings.owner)
                ).all()
            }
        out = []
        for r in streams:
            if recurring_kind(r.category_primary, r.category_detailed) != "bill":
                continue
            out.append({
                "name": r.merchant_name or r.description,
                "sub": r.description,
                "amount": _dec_to_float(r.average_amount),
                "due_date": r.predicted_next_date.isoformat() if r.predicted_next_date else None,
                "kind": "recurring",
                "auto": True,
            })
        for l in liabs:
            acct = accts.get(l.account_id)
            out.append({
                "name": (acct.name or acct.official_name or acct.mask if acct else None)
                        or l.account_id,
                "sub": l.liability_type,
                "amount": _dec_to_float(l.minimum_payment),
                "due_date": l.next_payment_due_date.isoformat() if l.next_payment_due_date else None,
                "kind": "liability",
                "auto": False,
            })
        out.sort(key=lambda x: (x["due_date"] or "9999-12-31"))
        return out

    def finance_calendar_events(self, window_start, window_end) -> list[dict]:
        """Read-time projection (mirrors moodle_calendar_events): bill due dates +
        subscription renewals in the window as read-only 'finance:<id>' occurrences.
        NOT rows in the events table — events_between appends these at read time."""
        out: list[dict] = []

        def _push(source_id: str, title: str, iso_date: str | None):
            if not iso_date:
                return
            d = date.fromisoformat(iso_date)
            start = datetime(d.year, d.month, d.day, 9, 0, tzinfo=timezone.utc)
            if not (window_start <= start < window_end):
                return
            out.append({
                "id": f"finance:{source_id}",
                "title": title,
                "start": start,
                "end": start + timedelta(hours=1),
                "tint": "honey",
                "location": "",
                "description": "",
                "recurring": False,
                "recurrence_label": None,
                "at": clock(start),
                "source": "finance",
                "editable": False,
            })

        for b in self.finance_bills():
            amt = f" · ${b['amount']:,.0f}" if b.get("amount") is not None else ""
            _push(f"bill:{b['name']}", f"{b['name']}{amt} due", b.get("due_date"))
        for sub in self.finance_subscriptions():
            amt = f" · ${sub['amount']:,.2f}" if sub.get("amount") is not None else ""
            _push(f"sub:{sub['name']}", f"{sub['name']}{amt} renews", sub.get("next_date"))
        return out

    def finance_budgets(self, month: str) -> list[dict]:
        """All six budget categories for `month` (YYYY-MM), each with its local
        limit and derived spend (Σ outflow amounts mapped to that bucket)."""
        from .config import settings
        with self._session() as s:
            limits = {
                b.category: b.limit_amount for b in s.scalars(
                    select(FinanceBudget)
                    .where(FinanceBudget.owner == settings.owner)
                    .where(FinanceBudget.month == month)
                ).all()
            }
            txns = s.scalars(
                select(FinanceTransaction)
                .where(FinanceTransaction.owner == settings.owner)
            ).all()
        spent = {c: Decimal("0") for c in BUDGET_CATEGORIES}
        for t in txns:
            if t.date is None or t.date.strftime("%Y-%m") != month:
                continue
            if t.amount is None or t.amount <= 0:        # only outflows are "spend"
                continue
            spent[budget_bucket(t.category_primary, t.category_detailed)] += t.amount
        return [
            {
                "category": c,
                "limit_amount": _dec_to_float(limits.get(c, Decimal("0"))),
                "spent": float(spent[c]),
                "color": _BUDGET_COLORS[c],
            }
            for c in BUDGET_CATEGORIES
        ]

    @_retry_integrity
    def _upsert_one_budget(self, month: str, category: str, limit_amount) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceBudget)
                .where(FinanceBudget.owner == settings.owner)
                .where(FinanceBudget.category == category)
                .where(FinanceBudget.month == month)
            ).first()
            if row is None:
                row = FinanceBudget(owner=settings.owner, category=category, month=month)
                s.add(row)
            row.limit_amount = Decimal(str(limit_amount))

    def upsert_budgets(self, month: str, budgets: list[dict]) -> list[dict]:
        for b in budgets:
            category = b["category"]
            if category not in BUDGET_CATEGORIES:        # ignore unknown buckets
                continue
            self._upsert_one_budget(month, category, b["limit_amount"])
        return self.finance_budgets(month)

    def reallocate_budget(self, month: str, from_category: str, to_category: str,
                          amount: float) -> list[dict]:
        """Logical move: subtract `amount` from from_category's limit, add it to
        to_category's. Local only — never touches a bank."""
        current = {b["category"]: b["limit_amount"] for b in self.finance_budgets(month)}
        amt = Decimal(str(amount))
        from_limit = max(Decimal("0"), Decimal(str(current.get(from_category, 0))))
        to_limit = Decimal(str(current.get(to_category, 0)))
        # Conserve: transfer at most what the source holds — never manufacture money.
        moved = min(max(Decimal("0"), amt), from_limit)
        new_from = from_limit - moved
        new_to = to_limit + moved
        self._upsert_one_budget(month, from_category, new_from)
        self._upsert_one_budget(month, to_category, new_to)
        return self.finance_budgets(month)

    _RETIREMENT_SUBTYPES = frozenset({
        "ira", "roth", "roth 401k", "401k", "401a", "403b", "457b", "pension",
        "retirement", "sep ira", "simple ira", "sarsep", "tsp",
    })

    def _month_sums(self, s: Session, month: str) -> tuple[Decimal, Decimal]:
        """(income, spent) for `month` (YYYY-MM), excluding internal transfers."""
        from .config import settings
        income = Decimal("0")
        spent = Decimal("0")
        for t in s.scalars(
            select(FinanceTransaction).where(FinanceTransaction.owner == settings.owner)
        ):
            if t.date is None or t.date.strftime("%Y-%m") != month or t.amount is None:
                continue
            primary = (t.category_primary or "").upper()
            if t.amount < 0:
                if primary != "TRANSFER_IN":
                    income += -t.amount
            elif t.amount > 0:
                if primary != "TRANSFER_OUT":
                    spent += t.amount
        return income, spent

    def finance_summary(self, month: str | None = None) -> dict:
        from .config import settings
        month = month or utcnow().strftime("%Y-%m")
        y, m = int(month[:4]), int(month[5:7])
        prev = f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"
        with self._session() as s:
            balance = Decimal("0")
            for a in s.scalars(
                select(FinanceAccount)
                .where(FinanceAccount.owner == settings.owner)
                .where(FinanceAccount.type == "depository")
            ):
                bal = a.available_balance if a.available_balance is not None else a.current_balance
                if bal is not None:
                    balance += bal
            income, spent = self._month_sums(s, month)
            prev_income, prev_spent = self._month_sums(s, prev)
        return {
            "month": month,
            "balance": float(balance),
            "income_month": float(income),
            "spent_month": float(spent),
            "income_delta": float(income - prev_income),
            "spent_delta": float(spent - prev_spent),
        }

    def finance_networth(self) -> dict:
        from .config import settings
        with self._session() as s:
            accounts = s.scalars(
                select(FinanceAccount).where(FinanceAccount.owner == settings.owner)
            ).all()
            crypto_ids = {
                x.source_id for x in s.scalars(
                    select(FinanceSecurity)
                    .where(FinanceSecurity.owner == settings.owner)
                    .where(FinanceSecurity.type == "cryptocurrency")
                ).all()
            }
            holdings = s.scalars(
                select(FinanceHolding).where(FinanceHolding.owner == settings.owner)
            ).all()
        cash = Decimal("0")
        credit_loans = Decimal("0")
        for a in accounts:
            bal = a.current_balance if a.current_balance is not None else Decimal("0")
            if a.type == "depository":
                cash += (a.available_balance if a.available_balance is not None else bal)
            elif a.type in ("credit", "loan"):
                credit_loans += bal
        crypto = Decimal("0")
        investments = Decimal("0")
        retirement = Decimal("0")
        acct_subtype = {a.source_id: (a.subtype or "").lower() for a in accounts}
        for h in holdings:
            value = h.institution_value or Decimal("0")
            if h.security_id in crypto_ids:
                crypto += value
            elif acct_subtype.get(h.account_id, "") in self._RETIREMENT_SUBTYPES:
                retirement += value
            else:
                investments += value
        # Un-itemized investment accounts (no holdings — e.g. some IRAs Plaid
        # can't itemize) contribute their account balance, classified by subtype.
        # Accounts WITH holdings are already counted via the holdings loop above,
        # so this never double-counts.
        accounts_with_holdings = {h.account_id for h in holdings}
        for a in accounts:
            if a.type == "investment" and a.source_id not in accounts_with_holdings:
                value = a.current_balance or Decimal("0")
                if (a.subtype or "").lower() in self._RETIREMENT_SUBTYPES:
                    retirement += value
                else:
                    investments += value
        buckets = [
            {"name": "Cash", "value": float(cash), "color": "honey"},
            {"name": "Investments", "value": float(investments), "color": "green"},
            {"name": "Retirement", "value": float(retirement), "color": "sky"},
            {"name": "Crypto", "value": float(crypto), "color": "plum"},
            {"name": "Credit/Loans", "value": float(-credit_loans), "color": "clay"},
        ]
        total = cash + investments + retirement + crypto - credit_loans
        return {"buckets": buckets, "total": float(total)}

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

    # ---- insights (derived; cached by the engine, read here) ----
    def list_snapshots(self, end_day: date, days_back: int = 7) -> list[dict]:
        """One snapshot dict per day in [end_day - days_back, end_day], oldest
        first, owner-scoped, 'whoop' source preferred (matches _snapshot_row).
        The rules' baseline window reads through this."""
        from .config import settings

        start = end_day - timedelta(days=days_back)
        precedence = case((DailySnapshot.source == "whoop", 0), else_=1)
        with self._session() as s:
            rows = s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.day >= start)
                .where(DailySnapshot.day <= end_day)
                .order_by(DailySnapshot.day.asc(), precedence.asc(), DailySnapshot.id.desc())
            ).all()
        by_day: dict[date, dict] = {}
        for r in rows:
            if r.day not in by_day:            # first per day == preferred source
                by_day[r.day] = _snapshot_dict(r)
        return [by_day[d] for d in sorted(by_day)]

    @_retry_integrity
    def upsert_insight(self, *, day: date, domain: str, code: str, tone: str,
                       headline: str, body: str, signals: dict, source: str) -> dict:
        """Get-or-create by (owner, domain, day, code); regeneration replaces."""
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(Insight)
                .where(Insight.owner == settings.owner)
                .where(Insight.domain == domain)
                .where(Insight.day == day)
                .where(Insight.code == code)
            ).first()
            if row is None:
                row = Insight(owner=settings.owner, domain=domain, day=day, code=code)
                s.add(row)
            row.tone = tone
            row.headline = headline
            row.body = body
            row.signals_json = signals or {}
            row.source = source
            s.flush()
            return _insight_dict(row)

    def list_insights(self, day: date | None = None, domain: str = "fitness") -> list[dict]:
        """Cached cards for a day (default today), insertion order (anchor first)."""
        from .config import settings

        day = day or _local_today()
        with self._session() as s:
            rows = s.scalars(
                select(Insight)
                .where(Insight.owner == settings.owner)
                .where(Insight.domain == domain)
                .where(Insight.day == day)
                .order_by(Insight.id.asc())
            ).all()
            return [_insight_dict(r) for r in rows]

    def has_insight(
        self,
        day: date,
        domain: str = "fitness",
        code: str | None = None,
    ) -> bool:
        from .config import settings

        with self._session() as s:
            query = (
                select(Insight.id)
                .where(Insight.owner == settings.owner)
                .where(Insight.domain == domain)
                .where(Insight.day == day)
            )
            if code is not None:
                query = query.where(Insight.code == code)
            return s.scalars(query).first() is not None

    @_retry_integrity
    def prune_insights(self, day: date, domain: str, keep_codes) -> int:
        """Delete the day's insight rows (owner+domain) whose code isn't in
        keep_codes. Used by regeneration to drop signals that stopped firing so
        a manual refresh never leaves a stale card behind."""
        from .config import settings

        with self._session() as s, s.begin():
            rows = s.scalars(
                select(Insight)
                .where(Insight.owner == settings.owner)
                .where(Insight.domain == domain)
                .where(Insight.day == day)
            ).all()
            removed = 0
            for r in rows:
                if r.code not in keep_codes:
                    s.delete(r)
                    removed += 1
            return removed

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
            day = self._workout_local_day(row.started_at)
            s.delete(row)
            s.flush()
            # Did that remove the last workout of the day? If so, retract the
            # workout->habit auto-completion (mirrors set_water lowering below
            # goal). Manual taps are untouched — auto_complete_linked only
            # retracts source='auto' rows.
            local_midnight = datetime.combine(day, time.min).astimezone()
            start_utc = local_midnight.astimezone(timezone.utc)
            another = s.scalars(
                select(Workout.id)
                .where(Workout.started_at >= start_utc)
                .where(Workout.started_at < start_utc + timedelta(days=1))
                .limit(1)
            ).first()
        self.auto_complete_linked("workout", day, another is not None)
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
