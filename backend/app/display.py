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
