"""moodle_sync (M6 slice-1) — a near-clone of email_sync's tick loop. Mirrors
test_email_sync: tick fetches a MoodleSnapshot and upserts every record; tick
flips needs_reauth on MoodleAuthError; tick ignores providers lacking
fetch_school_snapshot; tick returns 0 with no DATABASE_URL configured."""
from datetime import datetime, timezone

from app import moodle_sync, providers
from app.providers.base import (
    MoodleSnapshot,
    NormalizedAnnouncement,
    NormalizedAssignment,
    NormalizedCourse,
    NormalizedDeadline,
    NormalizedGrade,
    NormalizedNotification,
    Tokens,
)
from app.store import store

from .fakes import FakeMoodleProvider, FakeProvider

NOW = datetime(2026, 7, 3, 18, tzinfo=timezone.utc)
DUE = datetime(2026, 7, 10, 23, 59, tzinfo=timezone.utc)


def _connect_moodle():
    store.upsert_provider_account("moodle", Tokens(
        access_token="wstoken-abc", refresh_token=None, expires_at=None,
        scopes="", provider_user_id="42"))


def _full_snapshot() -> MoodleSnapshot:
    return MoodleSnapshot(
        courses=[NormalizedCourse(
            source="moodle", source_id="72", shortname="CSC216",
            fullname="Software Development Fundamentals")],
        deadlines=[NormalizedDeadline(
            source="moodle", source_id="e1", course_id="72",
            name="Project 2 is due", module_name="assign",
            event_type="due", due_at=DUE)],
        assignments=[NormalizedAssignment(
            source="moodle", source_id="a1", course_id="72", cmid="900",
            name="Project 2", due_at=DUE)],
        grades=[NormalizedGrade(
            source="moodle", source_id="g1", course_id="72",
            item_name="Project 1", item_type="mod", grade_formatted="92.0")],
        announcements=[NormalizedAnnouncement(
            source="moodle", source_id="d1", course_id="72", forum_id="5",
            subject="Welcome", author="Prof X", created_at=NOW)],
        notifications=[NormalizedNotification(
            source="moodle", source_id="n1", subject="Graded: Project 1")],
    )


def test_tick_fetches_and_upserts_every_record():
    prov = FakeMoodleProvider(snapshot=_full_snapshot())
    providers.configure([prov])
    _connect_moodle()

    count = moodle_sync.tick(now=NOW)
    assert count == 6  # 1 each of course/deadline/assignment/grade/announcement/notification
    # Tokens were injected before the authed snapshot fetch.
    assert prov.injected and prov.injected[-1].access_token == "wstoken-abc"
    # Every record landed in its table.
    assert [c["source_id"] for c in store.moodle_courses()] == ["72"]
    assert [d["source_id"] for d in store.moodle_deadlines()] == ["e1"]
    assert [a["source_id"] for a in store.moodle_assignments()] == ["a1"]
    assert [g["source_id"] for g in store.moodle_grades()] == ["g1"]
    assert [a["source_id"] for a in store.moodle_announcements()] == ["d1"]
    assert [n["source_id"] for n in store.moodle_notifications()] == ["n1"]
    # Cursor advanced.
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "moodle")
    assert acct["last_sync_at"] is not None


def test_tick_is_idempotent_across_two_passes():
    prov = FakeMoodleProvider(snapshot=_full_snapshot())
    providers.configure([prov])
    _connect_moodle()

    moodle_sync.tick(now=NOW)
    moodle_sync.tick(now=NOW)  # second pass re-upserts the same source_ids
    # Upserts are keyed (owner, source, source_id) — no duplicate rows.
    assert len(store.moodle_courses()) == 1
    assert len(store.moodle_deadlines()) == 1


def test_tick_flips_account_to_needs_reauth_on_auth_error():
    providers.configure([FakeMoodleProvider(raise_auth=True)])
    _connect_moodle()
    moodle_sync.tick(now=NOW)
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "moodle")
    assert acct["status"] == "needs_reauth"


def test_tick_ignores_providers_without_fetch_school_snapshot():
    # A WHOOP FakeProvider has no fetch_school_snapshot -> moodle_sync skips it.
    providers.configure([FakeProvider()])
    store.upsert_provider_account("whoop", Tokens(
        access_token="w", refresh_token="r", expires_at=None,
        scopes="", provider_user_id=None))
    count = moodle_sync.tick(now=NOW)
    assert count == 0  # nothing moodle-shaped connected


def test_tick_skips_a_disconnected_or_needs_reauth_account():
    prov = FakeMoodleProvider(snapshot=_full_snapshot())
    providers.configure([prov])
    _connect_moodle()
    store.set_provider_status("moodle", "needs_reauth")

    count = moodle_sync.tick(now=NOW)
    assert count == 0
    assert prov.injected == []  # never fetched — account not connected


def test_tick_returns_zero_when_no_database_url(monkeypatch):
    # Detach the store from the test DB and clear DATABASE_URL so the registry
    # read raises the RuntimeError the tick swallows into a no-op.
    from app.config import settings

    providers.configure([FakeMoodleProvider(snapshot=_full_snapshot())])
    store.configure(None)  # lazy — will consult settings.database_url
    monkeypatch.setattr(settings, "database_url", "")
    assert moodle_sync.tick(now=NOW) == 0
