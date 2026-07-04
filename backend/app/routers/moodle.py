"""Moodle API (M6 School): the five read endpoints + sync.

Reads serve the normalized moodle_* tables only — never a live Moodle call.
Connect/disconnect/status live on the shared /api/oauth/* router (Task 14
appends connect/_status_dict endpoints to this same file).
"""
import logging

from fastapi import APIRouter, Query

from .. import moodle_sync, providers
from ..schemas import (
    AnnouncementOut,
    CourseOut,
    DeadlineOut,
    GradeOut,
    NotificationOut,
)
from ..store import store

router = APIRouter(prefix="/api/moodle", tags=["moodle"])

logger = logging.getLogger("scuffed_os.moodle")


@router.get("/courses", response_model=list[CourseOut])
def courses() -> list[dict]:
    """The student's synced Moodle courses. Served from the moodle_courses
    table (never a live Moodle call)."""
    return store.moodle_courses()


@router.get("/deadlines", response_model=list[DeadlineOut])
def deadlines(days: int | None = Query(default=None)) -> list[dict]:
    """Upcoming assignment/quiz due dates (the Moodle Timeline), due_at asc,
    optionally bounded to the next `days` days. Served from moodle_deadlines."""
    return store.moodle_deadlines(days)


@router.get("/grades", response_model=list[GradeOut])
def grades(course_id: str | None = Query(default=None)) -> list[dict]:
    """Current grades, optionally for one course_id. Served from moodle_grades."""
    return store.moodle_grades(course_id)


@router.get("/announcements", response_model=list[AnnouncementOut])
def announcements(course_id: str | None = Query(default=None)) -> list[dict]:
    """News-forum announcements, optionally for one course_id. Served from
    moodle_announcements."""
    return store.moodle_announcements(course_id)


@router.get("/notifications", response_model=list[NotificationOut])
def notifications() -> list[dict]:
    """Popup notifications (grades posted, etc.). Served from
    moodle_notifications."""
    return store.moodle_notifications()


@router.post("/sync")
def sync_now() -> dict:
    """Run one Moodle sync pass now (manual/test/assistant). Delegates to
    moodle_sync.tick(); reads never depend on it, so a failing tick returns 0.
    `providers` lists the Moodle providers that were polled (duck-typed by
    fetch_school_snapshot, mirroring email's fetch_messages check)."""
    count = moodle_sync.tick()
    try:
        names = [p.name for p in providers.all_providers()
                 if hasattr(p, "fetch_school_snapshot")]
    except RuntimeError:
        names = []
    return {"synced": count, "providers": names}
