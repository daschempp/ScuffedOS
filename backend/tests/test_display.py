import os
import time

import pytest
from datetime import date, datetime, timedelta, timezone

from app.display import relative_when, task_due_display, email_when_display

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 6, 10)


def test_relative_when_buckets():
    assert relative_when(NOW, NOW) == "just now"
    assert relative_when(NOW - timedelta(minutes=5), NOW) == "5 minutes ago"
    assert relative_when(NOW - timedelta(hours=3), NOW) == "3 hours ago"
    assert relative_when(NOW - timedelta(days=1), NOW) == "yesterday"
    assert relative_when(NOW - timedelta(days=2), NOW) == "2 days ago"
    assert relative_when(NOW - timedelta(days=8), NOW) == "1 week ago"
    assert relative_when(NOW - timedelta(days=15), NOW) == "2 weeks ago"


def test_relative_when_accepts_naive_utc():
    # SQLite returns naive datetimes; they're treated as UTC.
    assert relative_when(NOW.replace(tzinfo=None), NOW) == "just now"


def test_due_display_matrix():
    assert task_due_display(None, False, None, TODAY) == (None, False)
    assert task_due_display(TODAY, False, None, TODAY) == ("Today", False)
    assert task_due_display(TODAY - timedelta(days=1), False, None, TODAY) == ("Overdue", True)
    assert task_due_display(TODAY + timedelta(days=1), False, None, TODAY) == ("Tomorrow", False)
    due, late = task_due_display(TODAY + timedelta(days=4), False, None, TODAY)
    assert due == (TODAY + timedelta(days=4)).strftime("%a") and late is False
    assert task_due_display(TODAY + timedelta(days=30), False, None, TODAY) == \
        ((TODAY + timedelta(days=30)).strftime("%b %-d"), False)


def test_due_display_done_beats_overdue():
    completed = datetime(2026, 6, 10, 15, 2, tzinfo=timezone.utc)
    due, late = task_due_display(TODAY - timedelta(days=3), True, completed, TODAY)
    assert due.startswith("Done ")
    assert late is False
    assert task_due_display(None, True, None, TODAY) == ("Done", False)


def test_email_when_today_shows_clock():
    now = datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)
    # Same local calendar day -> clock time (e.g. '8:24am' in local tz).
    out = email_when_display(received, now)
    assert out == _local_clock_expected(received)


def test_email_when_yesterday():
    now = datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    assert email_when_display(received, now) == "Yesterday"


def test_email_when_older_shows_month_day():
    now = datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)
    # Older than yesterday -> 'Mon D' in local tz.
    expected = received.astimezone().strftime("%b %-d")
    assert email_when_display(received, now) == expected


def _local_clock_expected(dt):
    from app.display import clock
    return clock(dt)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset unavailable (non-Unix)")
def test_email_when_uses_local_calendar_day_not_utc():
    """Locks the §F rule: comparison is on the LOCAL calendar day, not UTC.
    received and now share a UTC calendar day (Jun 30) but received falls on
    the previous LOCAL day in America/New_York (UTC-4 in June), so the correct
    result is 'Yesterday'. A naive UTC-date comparison would wrongly return the
    clock time — this test fails against that bug and passes for the local-day
    implementation."""
    prev_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        now = datetime(2026, 6, 30, 5, 0, tzinfo=timezone.utc)       # 01:00 EDT Jun 30
        received = datetime(2026, 6, 30, 1, 0, tzinfo=timezone.utc)  # 21:00 EDT Jun 29
        assert email_when_display(received, now) == "Yesterday"
    finally:
        if prev_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = prev_tz
        time.tzset()
