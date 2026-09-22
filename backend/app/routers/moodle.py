"""Moodle API (M6 School): the five read endpoints + sync, plus the two ways
in — the pasted wstoken and the browser sign-in callback.

Reads serve the normalized moodle_* tables only — never a live Moodle call.
Disconnect/status live on the shared /api/oauth/* router.

Two routers are exported: `router` under /api/moodle, and `launch_router` with
NO prefix so Moodle's mobile-app sign-in handoff lands at exactly
/auth/moodle/launch (outside /api), alongside oauth.auth_router. main.py
includes both.
"""
import base64
import hashlib
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

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
    MoodleLaunch,
    NotificationOut,
    OAuthStatus,
)
from ..store import store
from .oauth import (
    _callback_error,
    _callback_success,
    _consume_state_where,
    _status_dict,
)

router = APIRouter(prefix="/api/moodle", tags=["moodle"])
launch_router = APIRouter(tags=["moodle"])

logger = logging.getLogger("scuffed_os.moodle")


def _wwwroot() -> str:
    """The site root exactly as Moodle signs with it. Moodle's $CFG->wwwroot
    never carries a trailing slash, so a configured base URL that does would
    otherwise make every md5(wwwroot + passport) miss and every sign-in look
    "expired or invalid" with no clue why."""
    return settings.moodle_base_url.rstrip("/")


def _persist_connected_account(wstoken: str, info: dict) -> None:
    """Store a validated wstoken as the `moodle` provider account. Shared by
    both entry points (pasted token and browser sign-in) so they persist
    identically. Server-side only — the wstoken never goes back to the client."""
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


@router.post("/connect", response_model=OAuthStatus)
def connect(payload: MoodleConnect) -> dict:
    """Connect Moodle via a pasted wstoken (the manual fallback to the browser
    sign-in at /auth/moodle/launch; WolfWare is Shibboleth SSO, so there is no
    OAuth code exchange either way). Parse the token (bare 32-hex or a
    launch-redirect URL), validate it with a live get_site_info call (a bad
    token -> 502, nothing persisted), persist it as the `moodle` provider
    account, kick one sync, and return the shared OAuth status."""
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
    _persist_connected_account(wstoken, info)
    moodle_sync.tick()
    return _status_dict()


def _decode_launch_blob(token: str | None) -> list[str] | None:
    """base64-decode a launch blob and split it on ':::', or None when there is
    nothing usable (absent/blank token, undecodable base64, or no signature +
    token pair). Never raises and never echoes the value."""
    value = (token or "").strip()
    if not value:
        return None
    try:
        decoded = base64.b64decode(value).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — any malformed payload is just invalid
        return None
    parts = decoded.split(":::")
    return parts if len(parts) >= 2 else None


@launch_router.post("/auth/moodle/launch")
def moodle_launch(payload: MoodleLaunch) -> HTMLResponse:
    """Moodle browser sign-in callback (outside /api).

    After the user signs in, Moodle redirects the browser to
    `<scheme>://token=<blob>`; the desktop shell catches that deep link and
    POSTs the blob here exactly once, as `{"token": "<blob>"}`. The blob
    carries the wstoken, so it travels in the BODY — in a query string it would
    land in uvicorn's access log and from there in the sidecar's stderr drain
    (and standard base64's '+' would be mangled into a space on the way).

    `blob = base64(md5(wwwroot + passport) ':::' wstoken [':::' privatetoken])`
    — there is no `state` parameter, so the md5 is the only tie back to a
    pending sign-in: find the issued state whose signature matches and burn it
    (success or failure alike, so a blob cannot be replayed). A blob matching
    NO pending state changes nothing.

    The blob, the wstoken and the privatetoken are secrets: they are never
    logged and never appear in the rendered page. Like the OAuth callback this
    renders inline HTML — there is no redirect back into the app; the
    Connectors panel's poll picks the flip up."""
    token = payload.token
    parts = _decode_launch_blob(token)
    if parts is None:
        logger.warning("moodle launch: malformed sign-in payload")
        return _callback_error("This sign-in link is not valid.")
    signature = parts[0]
    wwwroot = _wwwroot()
    state = _consume_state_where(
        "moodle",
        lambda s: hashlib.md5((wwwroot + s).encode()).hexdigest() == signature,
    )
    if state is None:
        logger.warning("moodle launch: no pending sign-in matched")
        return _callback_error("This sign-in link has expired or is invalid.")
    provider = providers.get("moodle")
    if provider is None:
        logger.warning("moodle launch: no moodle provider registered")
        return _callback_error("Moodle rejected the sign-in.")
    try:
        # Re-verifies the signature against the matched passport and returns
        # the 32-hex wstoken segment (the privatetoken is dropped here). The
        # blob may itself end in 'token=', so this relies on parse_pasted_token
        # splitting on the FIRST occurrence.
        wstoken = parse_pasted_token(
            f"token={token}", passport=state, wwwroot=wwwroot,
        )
        info = provider.get_site_info(wstoken)
    except (MoodleError, MoodleAuthError) as exc:
        # MoodleError/MoodleAuthError messages are the fixed parser strings or
        # Moodle's own errorcode/message — never the token itself.
        logger.warning("moodle launch: site-info validation failed: %s", exc)
        return _callback_error("Moodle rejected the sign-in.")
    _persist_connected_account(wstoken, info)
    # Connected as of here — a first-sync failure must NOT flip a successful
    # sign-in into an error page.
    try:
        moodle_sync.tick()
    except Exception as exc:  # noqa: BLE001 — first sync is best-effort
        logger.warning("moodle launch: first sync skipped (already connected): %s", exc)
    return _callback_success()


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
