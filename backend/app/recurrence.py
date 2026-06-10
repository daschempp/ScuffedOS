"""Shared recurrence engine (M3) — calendar events and recurring tasks.

Rules are stored as RFC 5545 RRULE strings ("FREQ=WEEKLY;BYDAY=MO,WE,FR")
and expanded on read with python-dateutil. Nothing is materialized.

Correctness note: expansion happens in *local wall-clock time* (the event's
anchor converted to the local zone), so a 9:00am standup stays 9:00am across
a DST transition instead of drifting an hour. Occurrences come back UTC.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

from dateutil import tz as _dtz
from dateutil.rrule import rrulestr

# Hard cap per expansion so a pathological rule can't hang a request.
MAX_OCCURRENCES = 1000

# RFC 5545 clients write UNTIL in UTC ("...T000000Z"); dateutil refuses to mix
# that with the naive local dtstart we expand against, so rewrite it to the
# equivalent local wall-clock time before parsing.
_UNTIL_Z = re.compile(r"(?i)UNTIL=(\d{8}T\d{6})Z")

# Simple presets the UI offers; anything else is a custom RRULE.
PRESETS = {
    "FREQ=DAILY": "Repeats daily",
    "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR": "Repeats weekdays",
    "FREQ=WEEKLY": "Repeats weekly",
    "FREQ=MONTHLY": "Repeats monthly",
}


def _prep(rule: str, tz) -> str:
    """Normalize a stored rule for parsing against a naive local dtstart."""
    def to_local(m: re.Match) -> str:
        dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return "UNTIL=" + dt.astimezone(tz).strftime("%Y%m%dT%H%M%S")

    return _UNTIL_Z.sub(to_local, rule.strip())


def validate(rule: str) -> None:
    """Raise ValueError if `rule` is not a single parseable RRULE.

    Multi-line input and embedded DTSTART are rejected outright — the anchor
    always comes from the row, and a smuggled DTSTART would parse here but
    blow up every later expansion (poisoning reads forever).
    """
    if "\n" in rule or "\r" in rule:
        raise ValueError("Invalid recurrence rule: one RRULE line only")
    if "DTSTART" in rule.upper():
        raise ValueError("Invalid recurrence rule: DTSTART is not allowed (the anchor comes from the event/task)")
    try:
        rrulestr(_prep(rule, _zone(None)), dtstart=datetime(2020, 1, 6, 9, 0))
    except Exception as exc:  # dateutil raises bare ValueError/KeyError
        raise ValueError(f"Invalid recurrence rule: {exc}") from exc


def describe(rule: str | None) -> str | None:
    if not rule:
        return None
    return PRESETS.get(rule.upper().removeprefix("RRULE:"), "Repeats (custom)")


def _zone(tz):
    # A real (DST-aware) zone object, never a fixed offset — reattaching a
    # fixed offset to occurrences months out would apply the wrong offset.
    return tz if tz is not None else _dtz.tzlocal()


def _local(dt: datetime, tz) -> datetime:
    """UTC (or naive-UTC from SQLite) -> aware wall-clock in `tz`."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def expand_between(
    rule: str,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    exdates: set[datetime] | None = None,
    tz=None,
) -> list[datetime]:
    """Concrete occurrence starts of `rule` within [window_start, window_end].

    All inputs are UTC (or naive == UTC); output is aware UTC, ascending.
    `exdates` are occurrence starts to skip (deleted single occurrences).
    """
    zone = _zone(tz)
    start_local = _local(dtstart, zone)
    rr = rrulestr(_prep(rule, zone), dtstart=start_local.replace(tzinfo=None))
    lo = _local(window_start, zone).replace(tzinfo=None)
    hi = _local(window_end, zone).replace(tzinfo=None)
    skip = {_local(d, zone).replace(tzinfo=None) for d in (exdates or set())}
    out: list[datetime] = []
    # Lazy iteration, not rr.between(): between() materializes the whole
    # window before any cap could apply, so a FREQ=SECONDLY rule would hang
    # the request. xafter() yields one occurrence at a time.
    for occ in rr.xafter(lo, inc=True):
        if occ > hi or len(out) >= MAX_OCCURRENCES:
            break
        if occ in skip:
            continue
        out.append(occ.replace(tzinfo=zone).astimezone(timezone.utc))
    return out


def next_occurrence(
    rule: str, dtstart: datetime, after: datetime, tz=None
) -> datetime | None:
    """First occurrence strictly after `after` (UTC in, UTC out)."""
    zone = _zone(tz)
    start_local = _local(dtstart, zone)
    rr = rrulestr(_prep(rule, zone), dtstart=start_local.replace(tzinfo=None))
    occ = rr.after(_local(after, zone).replace(tzinfo=None))
    if occ is None:
        return None
    return occ.replace(tzinfo=zone).astimezone(timezone.utc)


def next_date(rule: str, anchor: date, after: date) -> date | None:
    """Date-level recurrence for tasks: next deadline strictly after `after`.

    Anchored at local noon so date math never straddles a day boundary
    under DST or timezone offset.
    """
    anchor_dt = datetime.combine(anchor, time(12, 0))
    after_dt = datetime.combine(after, time(12, 0))
    rr = rrulestr(_prep(rule, _zone(None)), dtstart=anchor_dt)
    occ = rr.after(after_dt)
    return occ.date() if occ else None


def decrement_count(rule: str) -> str | None:
    """The completed occurrence consumed one slot of a COUNT=N rule.

    Returns the rule the *next* occurrence should carry, or None when the
    budget is spent. Without this, re-anchoring the rule on every spawn
    would restart the count and a COUNT-limited task would recur forever.
    """
    m = re.search(r"(?i)COUNT=(\d+)", rule)
    if not m:
        return rule
    remaining = int(m.group(1)) - 1
    if remaining < 1:
        return None
    return re.sub(r"(?i)COUNT=\d+", f"COUNT={remaining}", rule)


def week_start(day: date) -> date:
    """Monday of `day`'s week (the prototype's week convention)."""
    return day - timedelta(days=day.weekday())
