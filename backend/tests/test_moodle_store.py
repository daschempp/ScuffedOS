"""Moodle store section (M6 contract §G) — upsert idempotency, owner-scoping,
delete-all-six, and the moodle_deadlines(days_ahead) horizon filter. No
network; the store is bound to a throwaway SQLite engine by conftest."""
from datetime import datetime, timedelta, timezone

from app.providers.base import (
    NormalizedAnnouncement,
    NormalizedAssignment,
    NormalizedCourse,
    NormalizedDeadline,
    NormalizedGrade,
    NormalizedNotification,
)
from app.store import store

UTC = timezone.utc


def _course(sid="72", shortname="CSC510"):
    return NormalizedCourse(
        source="moodle", source_id=sid, shortname=shortname,
        fullname="Software Engineering", progress=42.0,
    )


def _deadline(sid, due_at, name="Assignment 1 is due"):
    return NormalizedDeadline(
        source="moodle", source_id=sid, course_id="72", name=name,
        module_name="assign", event_type="due", due_at=due_at,
    )


def _assignment(sid="9", course_id="72", status="submitted"):
    return NormalizedAssignment(
        source="moodle", source_id=sid, course_id=course_id, cmid="140",
        name="Design doc", submission_status=status,
    )


def _grade(sid="500", course_id="72"):
    return NormalizedGrade(
        source="moodle", source_id=sid, course_id=course_id,
        item_name="Quiz 1", item_type="mod", grade_formatted="88.00",
    )


_UNSET = object()


def _announcement(sid="30", course_id="72", created_at=_UNSET):
    if created_at is _UNSET:
        created_at = datetime(2026, 6, 30, 12, tzinfo=UTC)
    return NormalizedAnnouncement(
        source="moodle", source_id=sid, course_id=course_id, forum_id="11",
        subject="Welcome", author="Prof X",
        created_at=created_at,
    )


def _notification(sid="900"):
    return NormalizedNotification(
        source="moodle", source_id=sid, subject="Grade posted",
        full_message="Your quiz was graded.",
    )


def test_upsert_moodle_course_is_idempotent_by_source_id():
    first = store.upsert_moodle_course(_course())
    # Re-upsert same source_id with changed metadata -> same row, updated fields.
    second = store.upsert_moodle_course(_course(shortname="CSC-510"))
    assert first["id"] == second["id"]
    assert second["shortname"] == "CSC-510"
    assert len(store.moodle_courses()) == 1


def test_upsert_moodle_deadline_is_idempotent_and_serializes_when():
    due = datetime(2026, 7, 10, 23, 59, tzinfo=UTC)
    row = store.upsert_moodle_deadline(_deadline("100", due))
    again = store.upsert_moodle_deadline(_deadline("100", due, name="Renamed"))
    assert row["id"] == again["id"]
    assert again["name"] == "Renamed"
    assert isinstance(again["when"], str) and again["when"]   # derived display
    assert len(store.moodle_deadlines()) == 1


def test_upsert_moodle_announcement_allows_null_created_at():
    # Regression: NormalizedAnnouncement.created_at is nullable (the provider's
    # _epoch(disc.get("created")) returns None when a discussion lacks a
    # "created" field). The upsert must not crash on that, matching the guard
    # already used by the sibling upsert_moodle_notification.
    row = store.upsert_moodle_announcement(_announcement(sid="31", created_at=None))
    assert row["created_at"] is None


def test_upsert_moodle_assignment_grade_announcement_notification_idempotent():
    a1 = store.upsert_moodle_assignment(_assignment())
    a2 = store.upsert_moodle_assignment(_assignment(status="draft"))
    assert a1["id"] == a2["id"] and a2["submission_status"] == "draft"
    assert len(store.moodle_assignments()) == 1

    g1 = store.upsert_moodle_grade(_grade())
    g2 = store.upsert_moodle_grade(_grade())
    assert g1["id"] == g2["id"]
    assert len(store.moodle_grades()) == 1

    n1 = store.upsert_moodle_announcement(_announcement())
    n2 = store.upsert_moodle_announcement(_announcement())
    assert n1["id"] == n2["id"]
    assert len(store.moodle_announcements()) == 1

    f1 = store.upsert_moodle_notification(_notification())
    f2 = store.upsert_moodle_notification(_notification())
    assert f1["id"] == f2["id"]
    assert len(store.moodle_notifications()) == 1


def test_moodle_reads_are_owner_scoped():
    # Seed one of each under the default owner.
    store.upsert_moodle_course(_course())
    store.upsert_moodle_deadline(_deadline("100", datetime(2026, 7, 10, tzinfo=UTC)))
    store.upsert_moodle_assignment(_assignment())
    store.upsert_moodle_grade(_grade())
    store.upsert_moodle_announcement(_announcement())
    store.upsert_moodle_notification(_notification())
    # Flip the owner: the same store now sees no rows (owner-scoped selects).
    from app.config import settings

    original = settings.owner
    settings.owner = "someone-else"
    try:
        assert store.moodle_courses() == []
        assert store.moodle_deadlines() == []
        assert store.moodle_assignments() == []
        assert store.moodle_grades() == []
        assert store.moodle_announcements() == []
        assert store.moodle_notifications() == []
    finally:
        settings.owner = original
    # Restored owner sees them again.
    assert len(store.moodle_courses()) == 1


def test_delete_moodle_data_removes_all_six_tables():
    store.upsert_moodle_course(_course())
    store.upsert_moodle_deadline(_deadline("100", datetime(2026, 7, 10, tzinfo=UTC)))
    store.upsert_moodle_assignment(_assignment())
    store.upsert_moodle_grade(_grade())
    store.upsert_moodle_announcement(_announcement())
    store.upsert_moodle_notification(_notification())

    assert store.delete_moodle_data("moodle") is True
    assert store.moodle_courses() == []
    assert store.moodle_deadlines() == []
    assert store.moodle_assignments() == []
    assert store.moodle_grades() == []
    assert store.moodle_announcements() == []
    assert store.moodle_notifications() == []
    # Idempotent: a second delete with nothing left returns False.
    assert store.delete_moodle_data("moodle") is False


def test_moodle_deadlines_days_ahead_horizon_filter():
    now = datetime(2026, 7, 3, 12, tzinfo=UTC)
    soon = now + timedelta(days=5)
    far = now + timedelta(days=45)
    store.upsert_moodle_deadline(_deadline("soon", soon, name="Soon due"))
    store.upsert_moodle_deadline(_deadline("far", far, name="Far due"))

    # No horizon -> both, ordered by due_at asc.
    alld = store.moodle_deadlines()
    assert [d["source_id"] for d in alld] == ["soon", "far"]

    # 10-day horizon from now -> only the soon one.
    within = store.moodle_deadlines(days_ahead=10)
    assert [d["source_id"] for d in within] == ["soon"]
