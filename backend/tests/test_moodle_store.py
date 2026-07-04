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
from app.schemas import EventCreate, TaskCreate
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


def _seed_course(source_id="72", shortname="CSC116"):
    store.upsert_moodle_course(NormalizedCourse(
        source="moodle", source_id=source_id, shortname=shortname,
        fullname=f"{shortname} Intro to Computing",
    ))


def _seed_deadline(source_id="d1", course_id="72", due_at=None, name="Project 1 is due"):
    store.upsert_moodle_deadline(NormalizedDeadline(
        source="moodle", source_id=source_id, course_id=course_id,
        name=name, module_name="assign", event_type="due",
        due_at=due_at or datetime(2026, 7, 6, 23, 59, tzinfo=timezone.utc),
        url="https://moodle.example/event/1",
    ))


def _seed_assignment(source_id="a1", course_id="72", due_at=None,
                     name="Project 1", submission_status="new"):
    store.upsert_moodle_assignment(NormalizedAssignment(
        source="moodle", source_id=source_id, course_id=course_id, cmid="900",
        name=name,
        due_at=due_at or datetime(2026, 7, 6, 23, 59, tzinfo=timezone.utc),
        submission_status=submission_status,
    ))


def test_moodle_deadline_in_window_appears_in_events_between():
    _seed_course()
    _seed_deadline()
    window_start = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)
    occs = store.events_between(window_start, window_end)
    moodle = [o for o in occs if o["source"] == "moodle"]
    assert len(moodle) == 1
    occ = moodle[0]
    assert occ["id"] == "moodle:d1"
    assert occ["source"] == "moodle"
    assert occ["editable"] is False
    assert occ["tint"] == "grape"
    assert occ["title"] == "Project 1 is due · CSC116"
    assert occ["start"] == datetime(2026, 7, 6, 23, 59, tzinfo=timezone.utc)
    assert occ["end"] == datetime(2026, 7, 7, 0, 59, tzinfo=timezone.utc)  # +1h
    # _occurrence_dict-shaped: every calendar output key present.
    assert set(occ) >= {"id", "title", "start", "end", "tint", "location",
                        "description", "recurring", "recurrence_label", "at",
                        "source", "editable"}


def test_moodle_deadline_out_of_window_is_excluded_from_events_between():
    _seed_course()
    _seed_deadline(due_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc))
    window_start = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)
    occs = store.events_between(window_start, window_end)
    assert [o for o in occs if o["source"] == "moodle"] == []


def test_moodle_deadline_flows_into_up_next():
    _seed_course()
    # up_next scans [now-1d, now+14d]; anchor the deadline inside that window.
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    _seed_deadline(due_at=datetime(2026, 7, 6, 23, 59, tzinfo=timezone.utc))
    items = store.up_next(limit=5, now=now)
    moodle = [i for i in items if i["id"] == "moodle:d1"]
    assert len(moodle) == 1
    assert moodle[0]["tint"] == "grape"
    assert moodle[0]["title"] == "Project 1 is due · CSC116"


def test_moodle_assignment_appears_in_list_tasks_with_done_mirroring_submission():
    _seed_course()
    _seed_assignment(submission_status="new")
    tasks = store.list_tasks()
    moodle = [t for t in tasks if t["source"] == "moodle"]
    assert len(moodle) == 1
    task = moodle[0]
    assert task["id"] == "moodle:a1"
    assert task["source"] == "moodle"
    assert task["editable"] is False
    assert task["done"] is False           # "new" is not submitted
    assert task["group"] == "School"
    assert task["list"] == "School"
    assert task["prio"] == "med"
    assert task["label"] == "Project 1 · CSC116"
    # _task_dict-shaped: every task output key present.
    assert set(task) >= {"id", "label", "done", "group", "deadline", "prio",
                        "list", "description", "subtasks", "labels", "reminders",
                        "files", "recurrence", "recurrence_label", "due", "late",
                        "created_at", "updated_at", "completed_at",
                        "source", "editable"}


def test_moodle_assignment_done_true_when_submitted():
    _seed_course()
    _seed_assignment(source_id="a2", submission_status="submitted")
    tasks = store.list_tasks()
    task = next(t for t in tasks if t["id"] == "moodle:a2")
    assert task["done"] is True


def test_moodle_assignment_done_true_when_reopened():
    _seed_course()
    _seed_assignment(source_id="a3", submission_status="reopened")
    tasks = store.list_tasks()
    task = next(t for t in tasks if t["id"] == "moodle:a3")
    assert task["done"] is True


def test_assignment_without_due_date_is_skipped_from_tasks():
    _seed_course()
    store.upsert_moodle_assignment(NormalizedAssignment(
        source="moodle", source_id="a9", course_id="72", cmid="901",
        name="No-due assignment", due_at=None, submission_status="new",
    ))
    tasks = store.list_tasks()
    assert [t for t in tasks if t["id"] == "moodle:a9"] == []


def test_no_moodle_rows_leaves_events_between_and_up_next_unchanged():
    # A single real local event; NO moodle rows seeded. Store-level dicts for
    # local rows never carried "source"/"editable" (those keys are filled in
    # by the Pydantic response schema's defaults at the HTTP layer, per Task
    # 10) — so byte-identical here means: no moodle rows leak in, and the
    # local occurrence dict shape/values are untouched.
    store.create_event(EventCreate(
        title="Standup",
        start=datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
    ).model_dump())
    occs = store.events_between(
        datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc),
    )
    assert all("source" not in o for o in occs)
    assert [o["title"] for o in occs] == ["Standup"]


def test_no_moodle_rows_leaves_list_tasks_unchanged():
    store.create_task(TaskCreate(label="Buy milk").model_dump())
    tasks = store.list_tasks()
    assert all("source" not in t for t in tasks)
    assert [t["label"] for t in tasks] == ["Buy milk"]


def test_patch_to_moodle_task_id_returns_422(client):
    # The tasks PATCH route is typed /api/tasks/{task_id:int}; a "moodle:1"
    # path can never match, so the read-only projection is uneditable.
    res = client.patch("/api/tasks/moodle:1", json={"done": True})
    assert res.status_code == 422


def test_delete_to_moodle_calendar_event_id_returns_422(client):
    res = client.delete("/api/calendar/events/moodle:1")
    assert res.status_code == 422
