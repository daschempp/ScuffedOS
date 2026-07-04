"""API-layer tests for /api/moodle/* (M6 School slice-1, contract §J). Reads
are served from the store (no live Moodle call); /sync delegates to a
FakeMoodleSync seam and lists providers by the fetch_school_snapshot
duck-type. This file defines its own slim FakeMoodleProvider + FakeMoodleSync
(only the router surface), matching test_email_api.py's local-fakes split."""
from datetime import datetime, timezone

from app import moodle_sync, providers
from app.providers.base import (
    NormalizedAnnouncement,
    NormalizedCourse,
    NormalizedDeadline,
    NormalizedGrade,
    NormalizedNotification,
)
from app.store import store

NOW = datetime(2026, 7, 3, 15, 0, tzinfo=timezone.utc)


class FakeMoodleProvider:
    """Only the surface the moodle router + /sync provider-list touches:
    name and the fetch_school_snapshot duck-type marker."""

    name = "moodle"

    def fetch_school_snapshot(self, since):  # marks this as a Moodle provider
        return None


class FakeMoodleSync:
    """Stand-in for moodle_sync installed via moodle_sync.configure(...).
    tick() returns a scripted count and records call count."""

    def __init__(self, count=0):
        self.count = count
        self.calls = 0

    def tick(self, now=None):
        self.calls += 1
        return self.count


def _course(source_id, *, shortname="CSC116", fullname="Intro to Computing"):
    return NormalizedCourse(
        source="moodle", source_id=source_id, shortname=shortname,
        fullname=fullname, progress=42.0,
    )


def _deadline(source_id, *, course_id="72", name="Project 1 is due", due_at=NOW):
    return NormalizedDeadline(
        source="moodle", source_id=source_id, course_id=course_id, name=name,
        module_name="assign", event_type="due", due_at=due_at,
        url="https://moodle/mod/assign/view.php?id=1",
    )


def _grade(source_id, *, course_id="72", item_name="Project 1"):
    return NormalizedGrade(
        source="moodle", source_id=source_id, course_id=course_id,
        item_name=item_name, item_type="mod", grade_formatted="92.0",
        grade_raw=92.0, grade_min=0.0, grade_max=100.0,
    )


def _announcement(source_id, *, course_id="72", subject="Welcome"):
    return NormalizedAnnouncement(
        source="moodle", source_id=source_id, course_id=course_id, forum_id="9",
        subject=subject, author="Prof. Ada", created_at=NOW,
        summary_html="See the syllabus.", url="https://moodle/mod/forum/discuss.php?d=1",
    )


def _notification(source_id, *, subject="Assignment graded"):
    return NormalizedNotification(
        source="moodle", source_id=source_id, subject=subject,
        full_message="Your Project 1 grade is posted.", created_at=NOW, read=False,
    )


def test_courses_read_returns_store_rows(client):
    providers.configure([FakeMoodleProvider()])
    store.upsert_moodle_course(_course("72", shortname="CSC116"))
    store.upsert_moodle_course(_course("69", shortname="MA242"))

    body = client.get("/api/moodle/courses").json()

    assert {c["shortname"] for c in body} == {"CSC116", "MA242"}
    # No token/scope leakage in a read shape.
    assert all("access_token" not in c and "scopes" not in c for c in body)


def test_deadlines_read_returns_store_rows_with_when_display(client):
    providers.configure([FakeMoodleProvider()])
    store.upsert_moodle_deadline(_deadline("d1", name="Project 1 is due"))

    body = client.get("/api/moodle/deadlines").json()

    assert [d["name"] for d in body] == ["Project 1 is due"]
    assert "when" in body[0]  # derived display present


def test_deadlines_read_passes_days_param_to_store(client):
    providers.configure([FakeMoodleProvider()])
    store.upsert_moodle_deadline(_deadline("d1"))

    res = client.get("/api/moodle/deadlines?days=30")

    assert res.status_code == 200


def test_grades_read_filters_by_course_id(client):
    providers.configure([FakeMoodleProvider()])
    store.upsert_moodle_grade(_grade("g1", course_id="72", item_name="Project 1"))
    store.upsert_moodle_grade(_grade("g2", course_id="69", item_name="Exam 1"))

    body = client.get("/api/moodle/grades?course_id=72").json()

    assert [g["item_name"] for g in body] == ["Project 1"]


def test_announcements_read_returns_store_rows(client):
    providers.configure([FakeMoodleProvider()])
    store.upsert_moodle_announcement(_announcement("a1", subject="Welcome"))

    body = client.get("/api/moodle/announcements").json()

    assert [a["subject"] for a in body] == ["Welcome"]


def test_notifications_read_returns_store_rows(client):
    providers.configure([FakeMoodleProvider()])
    store.upsert_moodle_notification(_notification("n1", subject="Assignment graded"))

    body = client.get("/api/moodle/notifications").json()

    assert [n["subject"] for n in body] == ["Assignment graded"]


def test_sync_triggers_moodle_sync_and_lists_moodle_providers(client):
    fake_sync = FakeMoodleSync(count=5)
    moodle_sync.configure(fake_sync)
    providers.configure([FakeMoodleProvider()])

    body = client.post("/api/moodle/sync").json()

    assert body == {"synced": 5, "providers": ["moodle"]}
    assert fake_sync.calls == 1
