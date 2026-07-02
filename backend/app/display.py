"""Display strings derived from stored facts.

The DB stores real UTC timestamps and dates; the friendly strings the UI
shows ("2 days ago", "Overdue", "Done 8:02am") are computed here on read —
never stored (review R6).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; everything we write is UTC.

    Also used by the store so API timestamps serialize identically (with
    offset) no matter which dialect they were read from.
    """
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def _aware(dt: datetime) -> datetime:
    return aware_utc(dt)


def _local_clock(dt: datetime) -> str:
    local = _aware(dt).astimezone()
    return local.strftime("%I:%M%p").lstrip("0").lower()


def clock(dt: datetime) -> str:
    """'8:10am' / '4:00pm' — the clock format every panel uses."""
    return _local_clock(dt)


def relative_when(dt: datetime, now: datetime | None = None) -> str:
    """'just now' / 'N minutes ago' / 'yesterday' / '2 days ago' / 'Mar 14'."""
    now = now or datetime.now(timezone.utc)
    delta = now - _aware(dt)
    seconds = delta.total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 28:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    local = _aware(dt).astimezone()
    return local.strftime("%b %-d")


def task_due_display(
    deadline: date | None,
    done: bool,
    completed_at: datetime | None,
    today: date | None = None,
) -> tuple[str | None, bool]:
    """Return (due_label, late) the way the prototype rendered them."""
    today = today or datetime.now().astimezone().date()
    if done:
        if completed_at is not None:
            return f"Done {_local_clock(completed_at)}", False
        return "Done", False
    if deadline is None:
        return None, False
    if deadline < today:
        return "Overdue", True
    if deadline == today:
        return "Today", False
    if deadline == today + timedelta(days=1):
        return "Tomorrow", False
    if deadline < today + timedelta(days=7):
        return deadline.strftime("%a"), False
    return deadline.strftime("%b %-d"), False


def event_when_display(
    start: datetime,
    end: datetime,
    location: str = "",
    now: datetime | None = None,
) -> str:
    """The "Up next" line: 'Now · 9:00am–10:30am' / '11:30am · Google Meet'
    / 'Tomorrow 4:00pm · Oak Street' / 'Mon 9:00am'."""
    now = _aware(now) if now else datetime.now(timezone.utc)
    start, end = _aware(start), _aware(end)
    if start <= now < end:
        head = f"Now · {_local_clock(start)}–{_local_clock(end)}"
        return f"{head} · {location}" if location else head
    today = now.astimezone().date()
    day = start.astimezone().date()
    if day == today:
        head = _local_clock(start)
    elif day == today + timedelta(days=1):
        head = f"Tomorrow {_local_clock(start)}"
    elif day < today + timedelta(days=7):
        head = f"{day.strftime('%a')} {_local_clock(start)}"
    else:
        head = f"{day.strftime('%b %-d')} {_local_clock(start)}"
    return f"{head} · {location}" if location else head


def reminder_label(remind_at: datetime, label: str = "") -> str:
    """The chip text for a reminder: the user's phrasing if they gave one,
    else 'Jun 11, 9:00am'."""
    if label:
        return label
    local = _aware(remind_at).astimezone()
    return f"{local.strftime('%b %-d')}, {_local_clock(remind_at)}"


def meal_time_display(slot: str, logged_at: datetime) -> str:
    """'Breakfast · 8:10am' — the meal row's time line."""
    return f"{slot} · {_local_clock(logged_at)}"


def email_when_display(received_at: datetime, now: datetime | None = None) -> str:
    """The inbox row's compact relative timestamp: today shows the clock
    time ('8:24am'), yesterday shows 'Yesterday', older shows 'Jun 5'.
    Derived on read from the stored aware-UTC received_at (never stored)."""
    now = _aware(now) if now else datetime.now(timezone.utc)
    received = _aware(received_at)
    today = now.astimezone().date()
    day = received.astimezone().date()
    if day == today:
        return _local_clock(received)
    if day == today - timedelta(days=1):
        return "Yesterday"
    return received.astimezone().strftime("%b %-d")
