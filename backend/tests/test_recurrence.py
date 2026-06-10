"""Unit tests for the shared recurrence engine (app/recurrence.py)."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import recurrence

UTC = timezone.utc
# Monday 2026-01-05, 9:00am America/New_York (EST, UTC-5) == 14:00 UTC.
ANCHOR = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
JAN = datetime(2026, 1, 1, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)


def test_expand_between_weekly_yields_expected_utc_starts():
    got = recurrence.expand_between("FREQ=WEEKLY", ANCHOR, JAN, FEB, tz=UTC)
    assert got == [datetime(2026, 1, d, 14, 0, tzinfo=UTC) for d in (5, 12, 19, 26)]
    assert all(o.tzinfo == timezone.utc for o in got)


def test_expand_between_treats_naive_datetimes_as_utc():
    got = recurrence.expand_between(
        "FREQ=WEEKLY",
        ANCHOR.replace(tzinfo=None),
        JAN.replace(tzinfo=None),
        FEB.replace(tzinfo=None),
        tz=UTC,
    )
    assert got == recurrence.expand_between("FREQ=WEEKLY", ANCHOR, JAN, FEB, tz=UTC)


def test_weekly_rule_keeps_local_wall_clock_across_spring_forward():
    """A 9am New York standup stays 9am local across 2026-03-08 (UTC shifts)."""
    ny = ZoneInfo("America/New_York")
    got = recurrence.expand_between(
        "FREQ=WEEKLY",
        ANCHOR,
        datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 3, 15, tzinfo=UTC),
        tz=ny,
    )
    assert got == [
        datetime(2026, 3, 2, 14, 0, tzinfo=UTC),  # EST, UTC-5
        datetime(2026, 3, 9, 13, 0, tzinfo=UTC),  # EDT after spring-forward, UTC-4
    ]
    assert [(o.astimezone(ny).hour, o.astimezone(ny).minute) for o in got] == [(9, 0), (9, 0)]


def test_exdates_drop_single_occurrences():
    skipped = datetime(2026, 1, 12, 14, 0, tzinfo=UTC)
    got = recurrence.expand_between(
        "FREQ=WEEKLY", ANCHOR, JAN, FEB, exdates={skipped}, tz=UTC
    )
    assert skipped not in got
    assert got == [datetime(2026, 1, d, 14, 0, tzinfo=UTC) for d in (5, 19, 26)]


def test_next_occurrence_is_strictly_after():
    nxt = recurrence.next_occurrence("FREQ=WEEKLY", ANCHOR, after=ANCHOR, tz=UTC)
    assert nxt == ANCHOR + timedelta(days=7)
    on_the_dot = recurrence.next_occurrence(
        "FREQ=WEEKLY", ANCHOR, after=ANCHOR - timedelta(seconds=1), tz=UTC
    )
    assert on_the_dot == ANCHOR


def test_next_occurrence_none_when_rule_is_exhausted():
    assert (
        recurrence.next_occurrence("FREQ=DAILY;COUNT=1", ANCHOR, after=ANCHOR, tz=UTC)
        is None
    )


def test_next_date_for_date_level_task_rules():
    today = date.today()
    assert recurrence.next_date("FREQ=DAILY", today, after=today) == today + timedelta(days=1)
    assert recurrence.next_date("FREQ=WEEKLY", today, after=today) == today + timedelta(days=7)
    # an anchor still in the future is itself the next occurrence
    ahead = today + timedelta(days=3)
    assert recurrence.next_date("FREQ=WEEKLY", ahead, after=today) == ahead


def test_validate_accepts_presets_and_rejects_garbage():
    for preset in recurrence.PRESETS:
        recurrence.validate(preset)  # must not raise
    with pytest.raises(ValueError):
        recurrence.validate("complete garbage")
    with pytest.raises(ValueError):
        recurrence.validate("FREQ=NEVER")


def test_describe_maps_presets_and_custom():
    assert recurrence.describe("FREQ=WEEKLY") == "Repeats weekly"
    assert recurrence.describe("RRULE:freq=daily") == "Repeats daily"
    assert recurrence.describe("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR") == "Repeats weekdays"
    assert recurrence.describe("FREQ=WEEKLY;INTERVAL=2") == "Repeats (custom)"
    assert recurrence.describe(None) is None


def test_max_occurrences_caps_runaway_expansion():
    got = recurrence.expand_between(
        "FREQ=MINUTELY", ANCHOR, ANCHOR, ANCHOR + timedelta(days=30), tz=UTC
    )
    assert len(got) == recurrence.MAX_OCCURRENCES
    assert got[0] == ANCHOR
    assert got[-1] == ANCHOR + timedelta(minutes=recurrence.MAX_OCCURRENCES - 1)


def test_until_in_utc_z_form_is_accepted():
    """RFC 5545 clients (and Claude) write UNTIL in UTC; dateutil alone
    refuses to mix that with a naive dtstart — _prep rewrites it."""
    recurrence.validate("FREQ=DAILY;UNTIL=20260701T000000Z")
    anchor = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    occs = recurrence.expand_between(
        "FREQ=WEEKLY;UNTIL=20270101T000000Z",
        anchor,
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    assert len(occs) > 0


def test_decrement_count():
    assert recurrence.decrement_count("FREQ=DAILY") == "FREQ=DAILY"
    assert recurrence.decrement_count("FREQ=DAILY;COUNT=3") == "FREQ=DAILY;COUNT=2"
    assert recurrence.decrement_count("freq=daily;count=2") == "freq=daily;COUNT=1"
    assert recurrence.decrement_count("FREQ=DAILY;COUNT=1") is None


def test_pathological_rule_expands_lazily_and_fast():
    """FREQ=SECONDLY over a year-long window must hit the cap quickly, not
    materialize tens of millions of occurrences first."""
    import time as _time

    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t0 = _time.monotonic()
    occs = recurrence.expand_between(
        "FREQ=SECONDLY",
        anchor,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    assert len(occs) == recurrence.MAX_OCCURRENCES
    assert _time.monotonic() - t0 < 2.0
