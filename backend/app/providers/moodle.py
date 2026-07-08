"""MoodleProvider — read-only NC State WolfWare Moodle web-services adapter
(M6 School slice-1, design §3/§4).

Hand-rolled authed REST over httpx (no vendor SDK; one instance doesn't justify
the dependency). Moodle-specific field/endpoint/wsfunction names are confined to
THIS module — everything past it speaks the normalized dataclasses in base.py.

The http layer is a test seam mirroring google.py / whoop.py: configure(fake_http=obj)
installs a fake exposing .post()/.get(); configure() (fake_http='unset') restores
the lazy real httpx.Client. A web-service exception whose errorcode is an auth
code (invalidtoken/accessexception/invalidlogin) raises MoodleAuthError (an
AuthError subclass), which moodle_sync translates into status='needs_reauth';
any other web-service exception raises MoodleError (a RuntimeError) and is
logged-and-skipped.

Moodle's REST convention (frozen, verified live 2026-07-03): POST
{moodle_base_url}/webservice/rest/server.php with form fields wstoken,
wsfunction, moodlewsrestformat='json', and PHP-array-flattened params
(courseids[0]=72); ERRORS COME BACK HTTP 200 with an "exception" key — always
check for it; timestamps are unix epoch seconds (0/absent = unset); HTML in
summaries/announcements is stripped for display.

[confirm-against-live] — MOODLE_REST_PATH / MOODLE_LAUNCH_PATH / MOODLE_SERVICE
and the wsfunction/param/field names are confirmed against the live WolfWare
instance during the live-gate task; their constant NAMES are frozen by the
interface contract.
"""
from __future__ import annotations

import base64
import hashlib
import html
import logging
import re
from datetime import datetime, timezone

from ..config import settings
from .base import (
    AuthError,
    NormalizedAnnouncement,
    NormalizedAssignment,
    NormalizedCourse,
    NormalizedDeadline,
    NormalizedGrade,
    NormalizedNotification,
    MoodleSnapshot,
    Tokens,
)

log = logging.getLogger("scuffed_os.moodle")

# [confirm-against-live] — verified against the live WolfWare Moodle during M6 impl.
MOODLE_REST_PATH = "/webservice/rest/server.php"
MOODLE_LAUNCH_PATH = "/admin/tool/mobile/launch.php"
MOODLE_SERVICE = "moodle_mobile_app"

# Moodle web-service errorcodes that mean "the wstoken is bad" -> needs_reauth.
_AUTH_ERRORCODES = frozenset({"invalidtoken", "accessexception", "invalidlogin"})


class MoodleError(RuntimeError):
    """Non-auth Moodle web-service exception (HTTP 200 with an 'exception' key
    whose errorcode is NOT an auth code). moodle_sync logs-and-skips it."""


class MoodleAuthError(AuthError):
    """A wstoken-is-bad web-service exception (errorcode in _AUTH_ERRORCODES).

    Subclasses providers.base.AuthError (NOT RuntimeError) so moodle_sync's
    `except AuthError` catches it and flips the provider to needs_reauth."""


class MoodleProvider:
    name = "moodle"   # NO `kind` attr — excluded from pull_providers (like Google)

    def __init__(self) -> None:
        self._http: object | str = "unset"   # 'unset' -> lazy real httpx.Client
        self._client = None
        self._tokens: Tokens | None = None    # injected by moodle_sync before fetch
        self._userid: int | None = None       # cached during fetch_school_snapshot

    # ---- http seam (mirrors GoogleProvider) ----
    def configure(self, fake_http: object | str = "unset") -> None:
        """Tests install a fake exposing .post()/.get(); configure() restores real."""
        self._http = fake_http
        self._client = None

    def set_tokens(self, tokens: Tokens | None) -> None:
        """moodle_sync injects the stored wstoken (Tokens.access_token) here
        before calling fetch_school_snapshot so authed web-service calls carry it."""
        self._tokens = tokens

    def _transport(self):
        if self._http != "unset":
            return self._http
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=20.0)
        return self._client

    # ---- web-service call ----
    def _call(self, wsfunction: str, *, token: str | None = None, **params) -> dict | list:
        """POST one Moodle web-service function. wstoken is `token` (a connect-time
        override, e.g. the pasted token before it is stored) or the injected
        self._tokens.access_token. Params are PHP-array-flattened. A transport
        failure (status >= 400) or an auth-code web-service exception raises
        MoodleAuthError; any other web-service exception raises MoodleError.
        Otherwise the parsed JSON (dict or list) is returned."""
        wstoken = token
        if wstoken is None and self._tokens is not None:
            wstoken = self._tokens.access_token
        data = {
            "wstoken": wstoken or "",
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
            **_flatten(params),
        }
        res = self._transport().post(
            f"{settings.moodle_base_url}{MOODLE_REST_PATH}", data=data
        )
        if getattr(res, "status_code", 200) >= 400:
            raise MoodleAuthError(
                f"Moodle {wsfunction} returned {getattr(res, 'status_code', '?')}"
            )
        payload = res.json()
        if isinstance(payload, dict) and "exception" in payload:
            errorcode = payload.get("errorcode", "")
            message = payload.get("message") or payload.get("exception") or errorcode
            if errorcode in _AUTH_ERRORCODES:
                raise MoodleAuthError(f"{errorcode}: {message}")
            raise MoodleError(f"{errorcode}: {message}")
        return payload

    # ---- connect-time validation / snapshot bootstrap ----
    def get_site_info(self, token: str) -> dict:
        """core_webservice_get_site_info — validates a token at connect time and
        bootstraps a snapshot (userid + the list of enabled function NAMES for
        feature-detection). `token` is passed as the wstoken override so this
        works before the token is stored. Raises MoodleAuthError on a bad token."""
        info = self._call("core_webservice_get_site_info", token=token)
        functions = [
            f.get("name", "")
            for f in (info.get("functions") or [])
            if isinstance(f, dict) and f.get("name")
        ]
        return {
            "userid": int(info.get("userid") or 0),
            "sitename": info.get("sitename") or "",
            "release": info.get("release") or "",
            "functions": functions,
        }

    # ---- domain fetch methods (map raw WS JSON -> base.py dataclasses) ----
    # [confirm-against-live] wsfunction / param / field names verified against
    # the live WolfWare Moodle in Task 21; the method signatures are frozen.

    def fetch_courses(self, userid: int) -> list[NormalizedCourse]:
        """Enrolled courses for `userid` via core_enrol_get_users_courses.
        Epoch timestamps (startdate/enddate/lastaccess) map to aware UTC via
        _epoch (0/absent -> None); `hidden` is a 0/1 int -> bool; progress is
        a 0..100 float or None."""
        rows = self._call("core_enrol_get_users_courses", userid=userid)
        out: list[NormalizedCourse] = []
        for row in rows or []:
            out.append(NormalizedCourse(
                source="moodle",
                source_id=str(row.get("id") or ""),
                shortname=row.get("shortname") or "",
                fullname=row.get("fullname") or "",
                progress=row.get("progress"),
                start_at=_epoch(row.get("startdate")),
                end_at=_epoch(row.get("enddate")),
                last_access_at=_epoch(row.get("lastaccess")),
                hidden=bool(row.get("hidden")),
            ))
        return out

    def fetch_deadlines(self, now: datetime) -> list[NormalizedDeadline]:
        """The deadline timeline via core_calendar_get_action_events_by_timesort.
        Window = [now, now + settings.moodle_backfill_days_ahead days] as epoch
        seconds; pages of limitnum=50, paginated on aftereventid (the last
        event id of the previous page) while a page comes back full (==50).
        due_at comes from `timesort` (epoch -> aware UTC)."""
        timesortfrom = int(now.timestamp())
        timesortto = timesortfrom + settings.moodle_backfill_days_ahead * 86400
        out: list[NormalizedDeadline] = []
        after: int | None = None
        while True:
            params: dict = {
                "timesortfrom": timesortfrom,
                "timesortto": timesortto,
                "limitnum": 50,
            }
            if after is not None:
                params["aftereventid"] = after
            result = self._call(
                "core_calendar_get_action_events_by_timesort", **params
            )
            events = (result or {}).get("events") or []
            for ev in events:
                course = ev.get("course") or {}
                out.append(NormalizedDeadline(
                    source="moodle",
                    source_id=str(ev.get("id") or ""),
                    course_id=str(course.get("id") or ""),
                    name=ev.get("name") or "",
                    module_name=ev.get("modulename") or "",
                    event_type=ev.get("eventtype") or "",
                    due_at=_epoch(ev.get("timesort")),
                    overdue=bool(ev.get("overdue")),
                    url=ev.get("viewurl") or "",
                ))
            if len(events) < 50:
                break
            after = int(events[-1].get("id") or 0)
        return out

    def fetch_assignments(self, userid: int) -> list[NormalizedAssignment]:
        """Assignments via mod_assign_get_assignments (grouped under courses[]),
        then per-assignment mod_assign_get_submission_status(assignid,userid)
        for the student's submission_status / grading_status / graded flags.
        duedate/cutoffdate 0 -> None via _epoch; submission status falls back
        to 'none' when the student has no lastattempt.submission yet."""
        result = self._call("mod_assign_get_assignments")
        out: list[NormalizedAssignment] = []
        for course in (result or {}).get("courses") or []:
            course_id = str(course.get("id") or "")
            for asn in course.get("assignments") or []:
                assign_id = str(asn.get("id") or "")
                status = self._call(
                    "mod_assign_get_submission_status",
                    assignid=assign_id, userid=userid,
                ) or {}
                submission = (status.get("lastattempt") or {}).get("submission") or {}
                out.append(NormalizedAssignment(
                    source="moodle",
                    source_id=assign_id,
                    course_id=course_id,
                    cmid=str(asn.get("cmid") or ""),
                    name=asn.get("name") or "",
                    due_at=_epoch(asn.get("duedate")),
                    cutoff_at=_epoch(asn.get("cutoffdate")),
                    grade_max=asn.get("grade"),
                    submission_status=submission.get("status") or "none",
                    grading_status=status.get("gradingstatus") or "",
                    graded=bool(status.get("graded")),
                ))
        return out

    def fetch_grades(self, userid: int, course_ids: list[str]) -> list[NormalizedGrade]:
        """Grade items per course via gradereport_user_get_grade_items
        (courseid,userid). The report groups items under usergrades[]; each
        gradeitem's `graderaw` is a float or None ("-" display => graderaw
        None). course_id is taken from the loop arg (authoritative), not the
        row. gradedategraded 0 -> None via _epoch."""
        out: list[NormalizedGrade] = []
        for course_id in course_ids:
            result = self._call(
                "gradereport_user_get_grade_items",
                courseid=course_id, userid=userid,
            ) or {}
            for usergrade in result.get("usergrades") or []:
                for item in usergrade.get("gradeitems") or []:
                    out.append(NormalizedGrade(
                        source="moodle",
                        source_id=str(item.get("id") or ""),
                        course_id=course_id,
                        item_name=item.get("itemname") or "",
                        item_type=item.get("itemtype") or "",
                        grade_formatted=item.get("gradeformatted") or "-",
                        grade_raw=item.get("graderaw"),
                        grade_min=item.get("grademin"),
                        grade_max=item.get("grademax"),
                        graded_at=_epoch(item.get("gradedategraded")),
                    ))
        return out

    def fetch_announcements(
        self, userid: int, course_ids: list[str]
    ) -> list[NormalizedAnnouncement]:
        """Course announcements: list forums for the given courses via
        mod_forum_get_forums_by_courses, keep only type=='news' (the
        announcement forum), then pull each news forum's discussions via
        mod_forum_get_forum_discussions. The discussion `message` HTML is
        stripped via _strip_html at this provider boundary before it lands in
        summary_html, so the stored value is already display-ready (contract
        — no bodies persisted beyond this short summary)."""
        if not course_ids:
            return []
        forums = self._call(
            "mod_forum_get_forums_by_courses", courseids=course_ids
        ) or []
        out: list[NormalizedAnnouncement] = []
        for forum in forums:
            if (forum.get("type") or "") != "news":
                continue
            forum_id = str(forum.get("id") or "")
            course_id = str(forum.get("course") or "")
            result = self._call(
                "mod_forum_get_forum_discussions", forumid=forum_id
            ) or {}
            for disc in result.get("discussions") or []:
                out.append(NormalizedAnnouncement(
                    source="moodle",
                    source_id=str(disc.get("discussion") or ""),
                    course_id=course_id,
                    forum_id=forum_id,
                    subject=disc.get("subject") or "",
                    author=disc.get("userfullname") or "",
                    created_at=_epoch(disc.get("created")),
                    summary_html=_strip_html(disc.get("message") or ""),
                    url="",
                ))
        return out

    def fetch_notifications(self, userid: int) -> list[NormalizedNotification]:
        """Popup notifications via message_popup_get_popup_notifications
        (useridto=userid, newestfirst=1, limit=0 => all, offset=0). NB this WS
        uses limit/offset, NOT limitnum. fullmessage is stripped via
        _strip_html at this provider boundary before it lands in
        full_message; timecreated 0 -> None."""
        result = self._call(
            "message_popup_get_popup_notifications",
            useridto=userid, newestfirst=1, limit=0, offset=0,
        ) or {}
        out: list[NormalizedNotification] = []
        for note in result.get("notifications") or []:
            out.append(NormalizedNotification(
                source="moodle",
                source_id=str(note.get("id") or ""),
                subject=note.get("subject") or "",
                full_message=_strip_html(note.get("fullmessage") or ""),
                context_url=note.get("contexturl") or "",
                created_at=_epoch(note.get("timecreated")),
                read=bool(note.get("read")),
            ))
        return out

    def fetch_school_snapshot(self, since: datetime | None) -> MoodleSnapshot:
        """The bundle the sync tick consumes. Calls get_site_info once for the
        userid (cached on self._userid) and the site's advertised wsfunction
        list, feature-detects each OPTIONAL call against that list (a Moodle
        instance may not expose every WS — a missing function yields an empty
        list, never an error), then assembles a MoodleSnapshot from the six
        fetch_* methods. `since` is accepted for signature parity with the
        pull providers; the deadline window is driven off `now` internally."""
        info = self.get_site_info(self._tokens.access_token if self._tokens else "")
        userid = int(info.get("userid") or 0)
        self._userid = userid
        available = set(info.get("functions") or [])

        def _has(*names: str) -> bool:
            return all(n in available for n in names)

        now = datetime.now(timezone.utc)
        courses = (
            self.fetch_courses(userid)
            if _has("core_enrol_get_users_courses") else []
        )
        course_ids = [c.source_id for c in courses]
        deadlines = (
            self.fetch_deadlines(now)
            if _has("core_calendar_get_action_events_by_timesort") else []
        )
        assignments = (
            self.fetch_assignments(userid)
            if _has("mod_assign_get_assignments",
                    "mod_assign_get_submission_status") else []
        )
        grades = (
            self.fetch_grades(userid, course_ids)
            if _has("gradereport_user_get_grade_items") else []
        )
        announcements = (
            self.fetch_announcements(userid, course_ids)
            if _has("mod_forum_get_forums_by_courses",
                    "mod_forum_get_forum_discussions") else []
        )
        notifications = (
            self.fetch_notifications(userid)
            if _has("message_popup_get_popup_notifications") else []
        )
        return MoodleSnapshot(
            courses=courses,
            deadlines=deadlines,
            assignments=assignments,
            grades=grades,
            announcements=announcements,
            notifications=notifications,
        )

    # ---- OAuth-ish plumbing (Moodle has no code exchange; connect is token-paste) ----
    def authorize_url(self, state: str) -> str:
        """The Moodle mobile launch URL. Not used by the token-paste connect flow;
        present for OAuthProvider/registry symmetry."""
        from urllib.parse import urlencode

        q = urlencode({"service": MOODLE_SERVICE, "passport": state})
        return f"{settings.moodle_base_url}{MOODLE_LAUNCH_PATH}?{q}"

    def exchange_code(self, code: str) -> Tokens:
        raise MoodleError("moodle uses token paste, not code exchange")

    def refresh(self, tokens: Tokens) -> Tokens:
        """No refresh endpoint — a Moodle wstoken is static. Pass through so
        moodle_sync's token-rotation path is a no-op."""
        return tokens

    def revoke(self, tokens: Tokens) -> None:
        """No web-service revoke — disconnect just deletes the local token/data."""
        return None

    # ---- OAuthProvider connect/disconnect hooks ----
    def on_connected(self) -> None:
        """Post-connect hook: kick an immediate first sync. Imported lazily so
        this module does not hard-depend on the sync phase; a not-yet-authored
        moodle_sync is swallowed (the connect still succeeds)."""
        try:
            from .. import moodle_sync

            moodle_sync.tick()
        except Exception as exc:  # noqa: BLE001 — first-sync is best-effort
            log.warning("Moodle on_connected sync skipped: %s", exc)

    def on_disconnect(self) -> None:
        """Disconnect hook: delete this provider's synced Moodle rows. Imported
        lazily; a store without delete_moodle_data yet (mid-plan) is swallowed."""
        try:
            from ..store import store

            store.delete_moodle_data(self.name)
        except Exception as exc:  # noqa: BLE001 — data deletion is best-effort here
            log.warning("Moodle on_disconnect delete skipped: %s", exc)


# ---- module-level pure helpers ----
def _flatten(params: dict, prefix: str = "") -> dict:
    """PHP-array-flatten a params dict for Moodle's form-encoded body:
    {'courseids': [72, 69]} -> {'courseids[0]': '72', 'courseids[1]': '69'};
    nested dicts/lists recurse ({'options': {'ids': [1]}} ->
    {'options[ids][0]': '1'}). Scalars are stringified. None values are dropped."""
    out: dict = {}
    for key, value in params.items():
        full = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, full))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                child = f"{full}[{i}]"
                if isinstance(item, (dict, list, tuple)):
                    out.update(_flatten({str(i): item}, full))
                else:
                    out[child] = str(item)
        elif value is None:
            continue
        else:
            out[full] = str(value)
    return out


def _epoch(value) -> datetime | None:
    """Moodle unix epoch seconds -> aware UTC datetime. 0 / None / '' (Moodle's
    'unset' encodings) -> None."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(markup: str) -> str:
    """Best-effort HTML -> readable plain text for announcement/notification
    summaries: drop script/style, strip tags, unescape entities, collapse
    whitespace (mirrors google._html_to_text)."""
    if not markup:
        return ""
    text = _SCRIPT_STYLE_RE.sub(" ", markup)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def parse_pasted_token(pasted: str, *, passport: str | None = None,
                       wwwroot: str | None = None) -> str:
    """Accept either a bare 32-hex wstoken OR a '<scheme>://token=<base64>' launch
    redirect (base64 = md5(wwwroot+passport) + ':::' + token
    [+ ':::' + privatetoken]). For the URL form: base64-decode, split on ':::',
    and — when passport+wwwroot are given — verify the md5 prefix ==
    md5(wwwroot+passport); return the token segment. A bare 32-hex string is
    returned as-is. Raises MoodleError('unrecognized token') on neither, and
    MoodleError('passport mismatch') when the launch signature fails to verify."""
    value = (pasted or "").strip()
    if _HEX32_RE.match(value):
        return value
    # Launch-redirect form: everything after the last 'token=' is the base64 blob.
    if "token=" in value:
        blob = value.split("token=", 1)[1].strip()
        try:
            decoded = base64.b64decode(blob).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 — malformed paste
            raise MoodleError("unrecognized token") from exc
        parts = decoded.split(":::")
        if len(parts) >= 2:
            signature, token = parts[0], parts[1]
            if passport is not None and wwwroot is not None:
                expected = hashlib.md5((wwwroot + passport).encode()).hexdigest()
                if signature != expected:
                    raise MoodleError("passport mismatch")
            if _HEX32_RE.match(token):
                return token
    raise MoodleError("unrecognized token")
