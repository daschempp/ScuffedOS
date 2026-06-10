from datetime import date, datetime, timedelta, timezone

from app.display import relative_when, task_due_display

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
