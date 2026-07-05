"""Moodle API (M6 School): the five read endpoints + sync.

Reads serve the normalized moodle_* tables only — never a live Moodle call.
Connect/disconnect/status live on the shared /api/oauth/* router (Task 14
appends connect/_status_dict endpoints to this same file).
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from .. import moodle_sync, providers
from ..config import settings
from ..providers.base import Tokens
from ..providers.moodle import MoodleAuthError, MoodleError, parse_pasted_token
from ..schemas import (
    AnnouncementOut,
    CourseOut,
    DeadlineOut,
    GradeOut,
    MoodleConnect,
    NotificationOut,
    OAuthStatus,
)
from ..store import store
from .oauth import _status_dict

router = APIRouter(prefix="/api/moodle", tags=["moodle"])

logger = logging.getLogger("scuffed_os.moodle")


@router.post("/connect", response_model=OAuthStatus)
def connect(payload: MoodleConnect) -> dict:
    """Connect Moodle via a pasted wstoken (WolfWare is Shibboleth SSO, so
    there is no OAuth code exchange — the token is pasted, not redirected).
    Parse the token (bare 32-hex or a launch-redirect URL), validate it with a
    live get_site_info call (a bad token -> 502, nothing persisted), persist it
    as the `moodle` provider account (server-side only — the wstoken never goes
    back to the client), kick one sync, and return the shared OAuth status."""
    provider = providers.get("moodle")
    if provider is None:
        raise HTTPException(status_code=502, detail="Moodle rejected the token")
    try:
        wstoken = parse_pasted_token(
            payload.token, passport=payload.passport, wwwroot=settings.moodle_base_url,
        )
        info = provider.get_site_info(wstoken)
    except (MoodleError, MoodleAuthError) as exc:
        logger.warning("moodle connect validation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Moodle rejected the token") from exc
    store.upsert_provider_account(
        "moodle",
        Tokens(
            access_token=wstoken,
            refresh_token=None,
            expires_at=None,
            scopes="",
            provider_user_id=str(info["userid"]),
            meta={
                "sitename": info.get("sitename", ""),
                "release": info.get("release", ""),
                "functions": info.get("functions", []),
            },
        ),
    )
    moodle_sync.tick()
    return _status_dict()


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
