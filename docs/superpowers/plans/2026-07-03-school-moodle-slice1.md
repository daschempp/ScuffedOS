# M6 School Slice-1 ("Glance at school") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only **School** section that connects to NC State's WolfWare Moodle (SSO token paste-back), syncs courses / deadline-timeline / assignments (+submission status) / grades / announcements / notifications into Postgres, renders them in a `SchoolScreen`, and merges assignment deadlines into the existing Calendar + Tasks (and Home agenda) at read time — per the approved spec `docs/superpowers/specs/2026-07-03-school-moodle-slice1-design.md`.

**Architecture:** Clones the M5 Gmail groove exactly — `MoodleProvider` (hand-rolled httpx over the Moodle web-services REST endpoint, `configure(fake_http=)` seam, `MoodleAuthError(AuthError)`) → registry → the shared `/api/oauth/*` disconnect/status plumbing (connect is a thin token-paste endpoint since Moodle uses a static `wstoken`, not an OAuth code exchange) → `moodle_sync.py` tick loop (clone of `email_sync.py`) → `store` moodle section (idempotent `(owner, source, source_id)` upserts) → `routers/moodle.py` (reads from DB only) → `SchoolScreen.jsx`. Moodle deadlines are **not copied into** the `tasks`/`events` tables; they are projected into the Calendar/Tasks *output shapes* at read time inside `store.events_between()` / `store.list_tasks()`, tagged `source="moodle"` + `editable=False`, so Home/Calendar/Tasks show them read-only with zero schema change to those tables and no new write-guards.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic (0006 chains onto 0005), httpx (hand-rolled Moodle REST — NO vendor SDK), pytest + TestClient (SQLite), React + Vite frontend (no test harness — `npm run build` is the frontend gate).

## Global Constraints

- **The full test suite must stay green.** Baseline on this branch (`m6-school-moodle-slice1`, from `main`@866c538): run `cd backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q` FIRST and record the printed `N passed, 1 skipped` — that is the baseline every task must hold or grow (the 1 skip = the Postgres-only migration drift test). Report "X tests passing" after each task (user CLAUDE.md rule).
- **MIGRATION NUMBERING (coordination hazard — user-decided 2026-07-03):** this branch is based on `main` whose Alembic head is **0005**. The Moodle migration is **`0006_moodle`, `down_revision="0005"`** — executable immediately on this branch. The unmerged `m5-email-slice2` branch ALSO introduces a `0006_email_actions`. **If email slice-2 merges to `main` before this branch does, renumber this migration to `0007_moodle` with `down_revision="0006"` (the email revision id) during the rebase** — two revisions sharing id `0006` is an Alembic multi-head that breaks `upgrade head`. School's PR is otherwise independent of email.
- **READ-ONLY THIS SLICE.** No Moodle write of any kind (no submit, forum post, message send, mark-complete). The only state the backend mutates is its own DB (synced rows + the `provider_accounts` token row). Submitting assignments is slice 3.
- **Tokens/scopes are NEVER serialized to the client.** The Moodle `wstoken` lives only in `provider_accounts.access_token` (server-side). `_provider_account_dict` continues to emit only its 5 safe keys. The client learns connection state via `/api/oauth/status` (derived booleans only).
- **No message/content BODIES or file bytes are persisted.** Stored: course names, due dates, assignment/grade metadata, short announcement/notification HTML summaries. NOT stored (live-fetched from slice 2 on): course content trees, files, assignment intro/detail bodies.
- **Reads never depend on a live Moodle call.** Every `/api/moodle/*` GET is served from the DB. Only `POST /api/moodle/connect` (validate the pasted token) and `POST /api/moodle/sync` (the tick) reach Moodle. The sync tick NEVER crashes (per-provider try/except; `except AuthError` → `needs_reauth`; `DATABASE_URL` RuntimeError → no-op) — copied verbatim-in-shape from `email_sync.tick`.
- **`MoodleAuthError(AuthError)`** (subclass base `AuthError`, NOT `RuntimeError`) is raised for Moodle errorcodes `invalidtoken` / `accessexception` / `invalidlogin`; the sync's `except AuthError` flips the account to `needs_reauth`. Non-auth Moodle exceptions raise `MoodleError(RuntimeError)` and are logged-and-skipped.
- **Moodle's REST convention (frozen, verified live 2026-07-03):** POST `{moodle_base_url}/webservice/rest/server.php` with form fields `wstoken`, `wsfunction`, `moodlewsrestformat=json`, and PHP-array-flattened params (`courseids[0]=72`); **errors come back HTTP 200 with an `"exception"` key** — always check for it; timestamps are unix epoch seconds (`0`/absent = unset); HTML appears in summaries/announcements and must be stripped for display; file URLs need `?token=` appended (slice 2 concern).
- **Calendar/Tasks feed = READ-TIME MERGE (frozen spec §8), NOT physical rows.** `tasks`/`events` tables are UNCHANGED. The merge happens inside `store.events_between()` and `store.list_tasks()`, which append projected dicts from the `moodle_*` tables. The `EventOccurrence` and `Task` response models are widened additively (`id: int | str`; new `source: str = "local"` + `editable: bool = True`) so real rows validate unchanged and projected rows carry `id="moodle:<n>"`, `source="moodle"`, `editable=False`. Existing calendar/tasks mutation endpoints take `int` path ids, so a `"moodle:<n>"` id can never be edited/deleted through them (FastAPI 422) — no new guards needed.
- **`configure(...)` seam on every external-reaching module, wired into conftest.** `moodle_sync.configure(None)` on setup + `moodle_sync.configure("unset")` on teardown MUST be added to `backend/tests/conftest.py`'s autouse `no_external_services` fixture (both blocks). `providers.configure([...])` swaps the registry for tests.
- **`[confirm-against-live]` names are FROZEN:** the Moodle endpoint path, wsfunction names, param names, and JSON field paths in `moodle.py` are confirmed against the live WolfWare instance in Task 21, but the constant NAMES and method signatures in this contract never change. Downstream tasks code against the frozen names.
- **No new runtime dependencies.** Moodle REST over the existing `httpx` dependency; token parsing via stdlib `base64`/`hashlib`; HTML-strip via a small module-level regex (mirror `google._html_to_text`).
- **Python/test conventions (user CLAUDE.md):** venv interpreter `/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python`; pytest runs from `backend/`; avoid `&&` chains for steps that may return non-zero; run the full suite after changes and report the count.
- **Branch:** all slice-1 work lands on `m6-school-moodle-slice1` (from `main`).
- **Deferred — DO NOT build:** any Moodle write, course-content/file browsing, assignment detail view, submit (slice 2/3), quizzes, messaging/replies, multi-instance, calendar/tasks→Moodle write-back, autonomous assistant writes, rich HTML rendering of Moodle content (spec §2/§14).

---

## Interface Contract (single source of truth — signatures frozen)

Every task codes against these exact names/types. `MOODLE_*` constant VALUES carry `[confirm-against-live]`; their NAMES are frozen.

### §A. Settings — `app/config.py` (+ `backend/.env.example`)

```python
# app/config.py — new block after the Google/email block, before `settings = Settings()`:
    # ---- M6 School (Moodle) ----
    # Moodle web-services live at {moodle_base_url}/webservice/rest/server.php.
    # Auth is a static per-user wstoken (NOT OAuth) stored in provider_accounts,
    # never here. WolfWare is Shibboleth SSO (typeoflogin=3); the token is
    # obtained via the mobile launch flow / Security-keys page and pasted in.
    moodle_base_url: str = "https://moodle-courses2527.wolfware.ncsu.edu"   # no trailing slash
    moodle_sync_enabled: bool = True
    moodle_sync_seconds: int = 900              # 15 min; gentle (mobile-app cadence)
    moodle_backfill_days_ahead: int = 60        # deadline-timeline horizon
```

### §B. Normalized dataclasses + `MoodleProvider` protocol — `app/providers/base.py`

Aware-UTC datetimes; every record carries `source` (="moodle") + `source_id` (str). Added after `NormalizedEmail`.

```python
@dataclass
class NormalizedCourse:
    source: str                          # 'moodle'
    source_id: str                       # course id
    shortname: str
    fullname: str
    progress: float | None = None        # 0..100 or None
    start_at: datetime | None = None
    end_at: datetime | None = None
    last_access_at: datetime | None = None
    hidden: bool = False

@dataclass
class NormalizedDeadline:                # the Timeline (core_calendar_get_action_events_by_timesort)
    source: str
    source_id: str                       # calendar event id
    course_id: str
    name: str                            # e.g. "Summative assignment is due"
    module_name: str                     # 'assign' | 'quiz' | 'lesson' | ...
    event_type: str                      # 'due' | 'close' | ...
    due_at: datetime                     # from timesort (epoch → aware UTC)
    overdue: bool = False
    url: str = ""                        # viewurl

@dataclass
class NormalizedAssignment:
    source: str
    source_id: str                       # assign id
    course_id: str
    cmid: str
    name: str
    due_at: datetime | None = None
    cutoff_at: datetime | None = None
    grade_max: float | None = None
    submission_status: str = "none"      # 'new'|'draft'|'submitted'|'reopened'|'none'
    grading_status: str = ""             # 'graded'|'notgraded'|...
    graded: bool = False

@dataclass
class NormalizedGrade:
    source: str
    source_id: str                       # grade item id
    course_id: str
    item_name: str
    item_type: str                       # 'mod'|'course'|'category'
    grade_formatted: str = "-"           # display string (may contain HTML entities)
    grade_raw: float | None = None
    grade_min: float | None = None
    grade_max: float | None = None
    graded_at: datetime | None = None

@dataclass
class NormalizedAnnouncement:
    source: str
    source_id: str                       # discussion id
    course_id: str
    forum_id: str
    subject: str
    author: str
    created_at: datetime
    summary_html: str = ""               # short; stripped for display
    url: str = ""

@dataclass
class NormalizedNotification:
    source: str
    source_id: str                       # notification id
    subject: str
    full_message: str = ""               # stripped for display
    context_url: str = ""
    created_at: datetime | None = None
    read: bool = False

@dataclass
class MoodleSnapshot:                    # the bundle fetch_school_snapshot returns
    courses: list[NormalizedCourse] = field(default_factory=list)
    deadlines: list[NormalizedDeadline] = field(default_factory=list)
    assignments: list[NormalizedAssignment] = field(default_factory=list)
    grades: list[NormalizedGrade] = field(default_factory=list)
    announcements: list[NormalizedAnnouncement] = field(default_factory=list)
    notifications: list[NormalizedNotification] = field(default_factory=list)

@runtime_checkable
class MoodleProvider(OAuthProvider, Protocol):
    """Read-only Moodle web-services adapter. Distinguishing method
    fetch_school_snapshot — moodle_sync selects providers by hasattr on it
    (mirrors email_sync's hasattr(p,'fetch_messages'))."""
    def get_site_info(self, token: str) -> dict: ...                 # connect-time validation
    def fetch_school_snapshot(self, since: datetime | None) -> MoodleSnapshot: ...
```

### §C. `MoodleProvider` core — `app/providers/moodle.py`

```python
MOODLE_REST_PATH = "/webservice/rest/server.php"                     # [confirm-against-live]
MOODLE_LAUNCH_PATH = "/admin/tool/mobile/launch.php"                 # [confirm-against-live]
MOODLE_SERVICE = "moodle_mobile_app"                                 # [confirm-against-live]
_AUTH_ERRORCODES = frozenset({"invalidtoken", "accessexception", "invalidlogin"})

class MoodleError(RuntimeError): ...      # non-auth Moodle web-service exception
class MoodleAuthError(AuthError): ...     # invalidtoken/accessexception → sync flips needs_reauth

class MoodleProvider:
    name = "moodle"                       # NO `kind` attr (excluded from pull_providers, like Google)
    def __init__(self) -> None:
        self._http: object | str = "unset"
        self._client = None
        self._tokens: Tokens | None = None
    def configure(self, fake_http: object | str = "unset") -> None: ...   # + self._client=None
    def set_tokens(self, tokens: Tokens | None) -> None: ...
    def _transport(self): ...             # lazy httpx.Client(timeout=20.0); fake when self._http!="unset"
    def _call(self, wsfunction: str, *, token: str | None = None, **params) -> dict | list: ...
        # POST {base}{REST_PATH} data={wstoken: token or self._tokens.access_token,
        #   wsfunction, moodlewsrestformat:'json', **_flatten(params)}.
        # HTTP status>=400 → MoodleAuthError. Parse JSON; if dict and 'exception' in it:
        #   errorcode in _AUTH_ERRORCODES → MoodleAuthError(message) else MoodleError(message).
        # Else return parsed JSON.
    # OAuth-ish plumbing (Moodle has no code exchange; connect is token-paste — see §J):
    def authorize_url(self, state: str) -> str: ...   # returns the launch.php URL (not used by connect flow; present for protocol/registry symmetry)
    def exchange_code(self, code: str) -> Tokens: ... # raises MoodleError("moodle uses token paste, not code exchange")
    def refresh(self, tokens: Tokens) -> Tokens: ...  # returns tokens unchanged (no refresh endpoint)
    def revoke(self, tokens: Tokens) -> None: ...     # no-op (Moodle has no WS revoke; disconnect just deletes locally)
    def success_redirect(self) -> str: return "/?screen=school&connected=moodle"
    def on_connected(self) -> None: ...   # lazy import moodle_sync; moodle_sync.tick(); swallow
    def on_disconnect(self) -> None: ...  # lazy import store; store.delete_moodle_data(self.name); swallow

# module-level pure helpers:
def _flatten(params: dict, prefix: str = "") -> dict: ...   # PHP-array flatten: {'courseids':[72,69]} -> {'courseids[0]':'72','courseids[1]':'69'}; nested dicts/lists recurse
def _epoch(value) -> datetime | None: ...   # int epoch secs → aware UTC; 0/None/"" → None
def _strip_html(markup: str) -> str: ...    # drop script/style, strip tags, unescape, collapse ws (mirror google._html_to_text)
```

### §D. Token paste-back parsing — `app/providers/moodle.py` (pure, module-level)

```python
def parse_pasted_token(pasted: str, *, passport: str | None = None, wwwroot: str | None = None) -> str:
    """Accept either a bare 32-hex wstoken, OR a '<scheme>://token=<base64>' launch
    redirect (base64 = md5(wwwroot+passport)+':::'+token[+':::'+privatetoken]). For the
    URL form, base64-decode, split on ':::', and — when passport+wwwroot are given —
    verify the md5 prefix == md5(wwwroot+passport); return the token segment. A bare
    32-hex string is returned as-is. Raises MoodleError('unrecognized token') on neither."""
```

### §E. Provider fetch methods — `app/providers/moodle.py` (map raw WS JSON → §B dataclasses)

All `[confirm-against-live]` on wsfunction/param/field names (verified against the Moodle 5.2 demo 2026-07-03).

```python
def get_site_info(self, token: str) -> dict:
    # core_webservice_get_site_info -> {"userid","fullname","sitename","release","functions":[{"name":...}]}
    # returns {"userid": int, "sitename": str, "release": str, "functions": [str,...]}
def fetch_courses(self, userid: int) -> list[NormalizedCourse]:
    # core_enrol_get_users_courses(userid=userid)
def fetch_deadlines(self, now: datetime) -> list[NormalizedDeadline]:
    # core_calendar_get_action_events_by_timesort(timesortfrom=now_epoch,
    #   timesortto=(now+backfill_days_ahead)_epoch, limitnum=50) -> {"events":[...]}
    #   paginate via aftereventid on lastid while len(page)==50
def fetch_assignments(self, userid: int) -> list[NormalizedAssignment]:
    # mod_assign_get_assignments() -> {"courses":[{"assignments":[...]}]}; then for each
    #   assignment mod_assign_get_submission_status(assignid=..., userid=userid) for status/graded
def fetch_grades(self, userid: int, course_ids: list[str]) -> list[NormalizedGrade]:
    # per course: gradereport_user_get_grade_items(courseid=cid, userid=userid) -> usergrades[].gradeitems[]
def fetch_announcements(self, userid: int, course_ids: list[str]) -> list[NormalizedAnnouncement]:
    # mod_forum_get_forums_by_courses(courseids=[...]) keep type=='news'; per news forum
    #   mod_forum_get_forum_discussions(forumid=fid) -> {"discussions":[...]}
def fetch_notifications(self, userid: int) -> list[NormalizedNotification]:
    # message_popup_get_popup_notifications(useridto=userid, newestfirst=1, limit=0, offset=0)
    #   -> {"notifications":[...]}   (NB: 'limit'/'offset', NOT 'limitnum')
def fetch_school_snapshot(self, since: datetime | None) -> MoodleSnapshot:
    # site_info for userid+functions; feature-detect each optional call against functions[];
    #   assemble MoodleSnapshot from the six fetch_* methods (missing feature → empty list, never crash).
```

The injected token (`set_tokens`) supplies `wstoken` for every `_call` here; `userid` comes from `get_site_info` cached on the provider during the snapshot (store it on `self._userid` within `fetch_school_snapshot`).

### §F. Data model + migration — `app/models.py` + `alembic/versions/0006_moodle.py`

Six tables, each: `id` PK, `owner` (String(64), default "me", indexed), `source` (String(16), indexed), `source_id` (String(128), indexed), domain columns, `created_at`/`updated_at` (aware-UTC, Python-side `default=utcnow`/`onupdate=utcnow`), `UniqueConstraint("owner","source","source_id", name="uq_<table>_owner_source_source_id")`. `JSONField` for the `meta` column. Column sets (frozen):

- `moodle_courses`: shortname `String(255)`, fullname `Text`, progress `Float|None`, start_at/end_at/last_access_at `DateTime(tz)|None`, hidden `Boolean` default False, meta `JSONField` default dict.
- `moodle_deadlines`: course_id `String(32)` idx, name `Text`, module_name `String(32)`, event_type `String(32)`, due_at `DateTime(tz)` idx, overdue `Boolean` default False, url `Text` default "", meta `JSONField`.
- `moodle_assignments`: course_id `String(32)` idx, cmid `String(32)`, name `Text`, due_at/cutoff_at `DateTime(tz)|None`, grade_max `Float|None`, submission_status `String(16)` default "none", grading_status `String(32)` default "", graded `Boolean` default False, meta `JSONField`.
- `moodle_grades`: course_id `String(32)` idx, item_name `Text`, item_type `String(16)`, grade_formatted `String(64)` default "-", grade_raw/grade_min/grade_max `Float|None`, graded_at `DateTime(tz)|None`, meta `JSONField`.
- `moodle_announcements`: course_id `String(32)` idx, forum_id `String(32)`, subject `Text`, author `String(255)` default "", created_at `DateTime(tz)`, summary_html `Text` default "", url `Text` default "", meta `JSONField`.
- `moodle_notifications`: subject `Text`, full_message `Text` default "", context_url `Text` default "", created_at `DateTime(tz)|None`, read `Boolean` default False, meta `JSONField`.

Migration: `revision="0006"`, `down_revision="0005"` (see Global Constraints hazard note); `upgrade()` creates all six + their indexes; `downgrade()` drops all six. `test_migrations.py` `ALL_TABLES` gains the six names.

### §G. Store — `app/store.py` (`# ---- moodle ----` section)

```python
# module-level, near _email_dict:
def _moodle_course_dict(c) -> dict: ...        # id, source_id, shortname, fullname, progress, start_at, end_at, last_access_at, hidden
def _moodle_deadline_dict(d) -> dict: ...      # id, source_id, course_id, name, module_name, event_type, due_at, overdue, url, when (derived display)
def _moodle_grade_dict(g) -> dict: ...
def _moodle_announcement_dict(a) -> dict: ...
def _moodle_notification_dict(n) -> dict: ...
def _moodle_assignment_dict(a) -> dict: ...

# Store methods (owner-scoped; @_retry_integrity on upserts):
def upsert_moodle_course(self, c: NormalizedCourse) -> dict: ...        # get-or-create (owner, source, source_id); metadata every pass
def upsert_moodle_deadline(self, d: NormalizedDeadline) -> dict: ...
def upsert_moodle_assignment(self, a: NormalizedAssignment) -> dict: ...
def upsert_moodle_grade(self, g: NormalizedGrade) -> dict: ...
def upsert_moodle_announcement(self, a: NormalizedAnnouncement) -> dict: ...
def upsert_moodle_notification(self, n: NormalizedNotification) -> dict: ...
def moodle_courses(self) -> list[dict]: ...
def moodle_deadlines(self, days_ahead: int | None = None) -> list[dict]: ...   # due_at asc
def moodle_grades(self, course_id: str | None = None) -> list[dict]: ...
def moodle_announcements(self, course_id: str | None = None) -> list[dict]: ...
def moodle_notifications(self) -> list[dict]: ...
def moodle_assignments(self, course_id: str | None = None) -> list[dict]: ...
def delete_moodle_data(self, source: str) -> bool: ...   # delete all six tables where (owner, source); on_disconnect hook
# read-time projectors for §H (return dicts in the EventOccurrence / Task output shapes):
def moodle_calendar_events(self, window_start: datetime, window_end: datetime) -> list[dict]: ...
def moodle_tasks(self) -> list[dict]: ...
```

### §H. Calendar/Tasks read-time merge — `app/schemas.py` + `app/store.py`

Additive schema widening (existing rows validate unchanged):
```python
# EventOccurrence: change `id: int` -> `id: int | str`; append:
    source: str = "local"
    editable: bool = True
# Task: change `id: int` -> `id: int | str`; append:
    source: str = "local"
    editable: bool = True
```
Merge points (append projected rows, then re-sort):
```python
# store.events_between(...) — after building `out` from Event rows, before the final sort:
    out.extend(self.moodle_calendar_events(window_start, window_end))
    out.sort(key=lambda o: o["start"])
# store.list_tasks() — after building the Task list:
    return [ ...existing... ] + self.moodle_tasks()
```
`moodle_calendar_events` emits `_occurrence_dict`-shaped dicts: `id="moodle:<deadline source_id>"`, `title="<name> · <course shortname>"`, `start=due_at`, `end=due_at` (+1h), `tint="grape"` (a valid `Tint`), `location=""`, `description=""`, `recurring=False`, `recurrence_label=None`, `at=clock(start)`, `source="moodle"`, `editable=False`. Only deadlines whose `due_at` ∈ [window_start, window_end).
`moodle_tasks` emits `_task_dict`-shaped dicts from `moodle_assignments` with a `due_at`/`duedate`: `id="moodle:<assign source_id>"`, `label="<name> · <course shortname>"`, `done=(submission_status in {"submitted","reopened"})`, `group="School"`, `deadline=<date>`, `prio="med"`, `list="School"`, `description=""`, `subtasks=[]`, `labels=[]`, `reminders=[]`, `files=[]`, `recurrence=None`, `recurrence_label=None`, `due`/`late` via `task_due_display(deadline, done, None)`, timestamps = now, `source="moodle"`, `editable=False`. NB `TaskGroup`/`TaskPriority`/`Tint` are Literals — if `"School"`/`"grape"` are not already allowed values, ADD them to those Literals in `schemas.py` (a valid, tested extension) in the same task.

### §I. Sync engine — `app/moodle_sync.py` (clone of `email_sync.py`)

```python
_override: object | None | str = "unset"
def configure(override="unset") -> None: ...                       # test seam (identical to email_sync)
def _moodle_providers() -> list: ...                               # [p for p in providers.all_providers() if hasattr(p,"fetch_school_snapshot")]
def _load_and_inject_tokens(provider, now) -> bool: ...            # identical logic to email_sync (Moodle refresh is a no-op passthrough, so no rotation persist actually happens)
def _sync_provider(provider, now) -> int: ...                      # if acct connected: inject tokens; snap = provider.fetch_school_snapshot(since); upsert every record; set_provider_synced; return count
def tick(now=None) -> int: ...                                     # override seam + DATABASE_URL guard + per-provider try/except (AuthError→needs_reauth); NEVER crashes
async def trigger() -> int: ...                                    # asyncio.to_thread(tick)
async def run_loop() -> None: ...                                  # while True: tick; sleep(settings.moodle_sync_seconds)
```
`main.py` lifespan starts `moodle_sync.run_loop()` behind `settings.moodle_sync_enabled`; conftest wires `moodle_sync.configure(None)`/`("unset")`.

### §J. Schemas + Router — `app/schemas.py` + `app/routers/moodle.py`

```python
# schemas.py — Moodle read models:
class CourseOut(BaseModel): id: int; source_id: str; shortname: str; fullname: str; progress: float | None; start_at: datetime | None; end_at: datetime | None; last_access_at: datetime | None; hidden: bool
class DeadlineOut(BaseModel): id: int; source_id: str; course_id: str; name: str; module_name: str; event_type: str; due_at: datetime; overdue: bool; url: str; when: str
class GradeOut(BaseModel): id: int; source_id: str; course_id: str; item_name: str; item_type: str; grade_formatted: str; grade_raw: float | None; grade_min: float | None; grade_max: float | None; graded_at: datetime | None
class AnnouncementOut(BaseModel): id: int; source_id: str; course_id: str; forum_id: str; subject: str; author: str; created_at: datetime; summary_html: str; url: str
class NotificationOut(BaseModel): id: int; source_id: str; subject: str; full_message: str; context_url: str; created_at: datetime | None; read: bool
class MoodleConnect(BaseModel): token: str; passport: str | None = None

# routers/moodle.py:
router = APIRouter(prefix="/api/moodle", tags=["moodle"])
POST /api/moodle/connect        MoodleConnect  -> OAuthStatus   # parse_pasted_token → provider.get_site_info (502 on MoodleError) → store.upsert_provider_account("moodle", Tokens(access_token=wstoken, refresh_token=None, expires_at=None, scopes="", provider_user_id=str(userid), meta={"sitename","release","functions"})) → moodle_sync.tick() → _status_dict()
GET  /api/moodle/courses                       -> list[CourseOut]
GET  /api/moodle/deadlines      ?days=60       -> list[DeadlineOut]
GET  /api/moodle/grades         ?course_id=    -> list[GradeOut]
GET  /api/moodle/announcements  ?course_id=    -> list[AnnouncementOut]
GET  /api/moodle/notifications                 -> list[NotificationOut]
POST /api/moodle/sync                          -> {"synced": int, "providers": [str]}
```
Register `moodle.router` in `main.py`. Connect validation failure (`MoodleError`/`MoodleAuthError`) → `HTTPException(502, "Moodle rejected the token")`. `_status_dict` is imported from `routers.oauth` (or re-derived from `store.list_provider_accounts()`).

### §K. Assistant tools — `app/tools.py`

```python
def _moodle_action(title: str, meta: str) -> dict:
    return {"icon": "graduation-cap", "title": title, "meta": meta, "cta": "Open school", "screen": "school"}
# three READ tools (registration test asserts NO write tools exist):
{"name": "get_courses", "description": "List the student's Moodle courses.", "input_schema": {"type":"object","properties":{},"additionalProperties":False}, "run": _get_courses}
{"name": "get_deadlines", "description": "Upcoming Moodle assignment/quiz due dates (optionally within N days).", "input_schema": {"type":"object","properties":{"days":{"type":"integer"}},"additionalProperties":False}, "run": _get_deadlines}
{"name": "get_grades", "description": "Current Moodle grades, optionally for one course_id.", "input_schema": {"type":"object","properties":{"course_id":{"type":"string"}},"additionalProperties":False}, "run": _get_grades}
# each returns (data_from_store, _moodle_action(...))  — reads, so the action card is optional context, not a mutation.
```

### §L. Frontend — `frontend/src/lib/api.js` + `SchoolScreen.jsx` + registration

```js
// api.js — school block (GET=bare path, POST={method, body}):
moodleCourses:       () => request('/api/moodle/courses'),
moodleDeadlines:     (days) => request(`/api/moodle/deadlines${days ? `?days=${days}` : ''}`),
moodleGrades:        (courseId) => request(`/api/moodle/grades${courseId ? `?course_id=${courseId}` : ''}`),
moodleAnnouncements: (courseId) => request(`/api/moodle/announcements${courseId ? `?course_id=${courseId}` : ''}`),
moodleNotifications: () => request('/api/moodle/notifications'),
moodleSync:          () => request('/api/moodle/sync', { method: 'POST' }),
moodleConnect:       (payload) => request('/api/moodle/connect', { method: 'POST', body: JSON.stringify(payload) }),
```
`SchoolScreen.jsx` clones `EmailScreen.jsx`'s self-owned/OAuth-gated render ladder (§ frontend extract): not-connected → **Connect Moodle card with a paste field + Security-keys instructions** (calls `api.moodleConnect({token})` then `refresh()`); needs-reauth banner; syncing card; main `kit-grid` = course list (left) + deadlines timeline / grades / announcements / notifications (right). `graduation-cap` icon added to `Icon.jsx`; `{id:'school', label:'School', icon:'graduation-cap'}` in `Sidebar.jsx`; `school:{title:'School', sub:'Courses, deadlines & grades'}` in `App.jsx` SCREENS; `else if (screen==='school') body=<SchoolScreen/>` render branch; import added.

### §M. Calendar/Tasks UI markers — `CalendarScreen.jsx` / `TasksScreen.jsx` / `DashboardScreen.jsx`

Rows with `source==='moodle'` render a small "Moodle" chip and hide edit/delete/toggle affordances (they are read-only; the id is a `"moodle:<n>"` string so any accidental mutation call 422s server-side anyway). No hook changes — deadlines arrive via `useCalendar`/`useTasks` from the merged read endpoints.

### §N. Privacy + docs

Privacy wave 1 across canonical `docs/privacy-policy.md` (§1/§3/§4/§6) + corp `scuffed-corporation/privacy/index.html` (commit on `redesign/mono-bold`) + the gist (gist push = a **user-approval step**, flagged in the task, NOT done by the agent). New `docs/school.md` (7-part skeleton) + a `docs/README.md` status-table row.

### §O. Task → phase map

| Phase | Tasks | Theme |
|---|---|---|
| P1 provider foundation | 1–7 | settings; base dataclasses+protocol; provider `_call` seam + FakeMoodleHTTP + registry; token parse + get_site_info; fetch courses/deadlines; fetch assignments/grades; fetch announcements/notifications + snapshot |
| P2 data layer | 8–11 | models + migration 0006; store moodle section; schema widening (id+source+editable); store projectors + calendar/tasks merge |
| P3 sync | 12 | moodle_sync.py + conftest wiring + main lifespan |
| P4 API | 13–14 | schemas + router reads/sync; connect endpoint (token validate → store → kick sync) |
| P5 assistant | 15 | get_courses/get_deadlines/get_grades tools + no-write registration test |
| P6 frontend | 16–18 | icon/sidebar/App/api wiring; SchoolScreen; Calendar/Tasks/Home read-only Moodle markers |
| P7 privacy+docs+smoke | 19–20 | privacy wave 1 (+docs/school.md, README row); smoke_moodle.py |
| P8 live gate | 21 | connect real WolfWare, verify screen + Calendar/Tasks feed, resolve [confirm-against-live], full suite + build green |

---

<!-- TASK BODIES 1-21 ASSEMBLED BELOW -->

### Task 1: Moodle settings block + `.env.example` M6 section

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_config.py`

**Interfaces:**
- Consumes: `app.config.Settings` (existing pydantic-settings model; the Google/email block ends at the `email_backfill_count` field with `settings = Settings()` immediately after — config.py lines 90-96).
- Produces: `Settings.moodle_base_url: str = "https://moodle-courses2527.wolfware.ncsu.edu"`; `Settings.moodle_sync_enabled: bool = True`; `Settings.moodle_sync_seconds: int = 900`; `Settings.moodle_backfill_days_ahead: int = 60` — consumed by Task 5 (`fetch_deadlines` horizon), Task 12 (`moodle_sync.run_loop` sleep + lifespan gate), and Task 13 (router `days` default).

- [ ] **Step 1: Write the failing config test.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_config.py` (mirrors `test_email_config.py` / `test_fitness_config.py` exactly — asserts declared code defaults on the model fields, independent of any local `backend/.env`):
  ```python
  """M6 config: Moodle base URL + moodle-sync knobs land on Settings with spec defaults."""
  from app.config import Settings


  def test_moodle_defaults():
      # Assert declared code defaults on the model fields, independent of any local
      # backend/.env or env vars — a real WolfWare setup never fills these in .env,
      # but this defaults check must hold regardless (matches test_email_config.py).
      d = Settings.model_fields
      assert d["moodle_base_url"].default.endswith("wolfware.ncsu.edu")
      assert d["moodle_base_url"].default == "https://moodle-courses2527.wolfware.ncsu.edu"
      assert d["moodle_sync_enabled"].default is True
      assert d["moodle_sync_seconds"].default == 900
      assert d["moodle_backfill_days_ahead"].default == 60


  def test_moodle_settings_have_the_annotated_types():
      fields = Settings.model_fields
      assert fields["moodle_base_url"].annotation is str
      assert fields["moodle_sync_enabled"].annotation is bool
      assert fields["moodle_sync_seconds"].annotation is int
      assert fields["moodle_backfill_days_ahead"].annotation is int
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_config.py -q
  ```
  Expected failure: `KeyError: 'moodle_base_url'` — `Settings.model_fields` has no `moodle_*` keys yet, so the first `d["moodle_base_url"]` access raises.

- [ ] **Step 3: Add the Moodle settings block to `config.py`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py`, replace the tail of the file (the email-sync block through the module singleton — currently lines 90-96):
  ```python
      # Background email-sync (mirrors fitness_sync_enabled / fitness_sync_seconds).
      email_sync_enabled: bool = True
      email_sync_seconds: int = 900               # 15 min
      email_backfill_count: int = 50              # first-connect messages.list maxResults


  settings = Settings()
  ```
  with (add the new `# ---- M6 School (Moodle) ----` block after the email block, before `settings = Settings()`):
  ```python
      # Background email-sync (mirrors fitness_sync_enabled / fitness_sync_seconds).
      email_sync_enabled: bool = True
      email_sync_seconds: int = 900               # 15 min
      email_backfill_count: int = 50              # first-connect messages.list maxResults

      # ---- M6 School (Moodle) ----
      # Moodle web-services live at {moodle_base_url}/webservice/rest/server.php.
      # Auth is a static per-user wstoken (NOT OAuth) stored in provider_accounts,
      # never here. WolfWare is Shibboleth SSO (typeoflogin=3); the token is
      # obtained via the mobile launch flow / Security-keys page and pasted in.
      moodle_base_url: str = "https://moodle-courses2527.wolfware.ncsu.edu"   # no trailing slash
      moodle_sync_enabled: bool = True
      moodle_sync_seconds: int = 900              # 15 min; gentle (mobile-app cadence)
      moodle_backfill_days_ahead: int = 60        # deadline-timeline horizon


  settings = Settings()
  ```

- [ ] **Step 4: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_config.py -q
  ```
  Expected: `2 passed`.

- [ ] **Step 5: Document the settings in `.env.example` under a new M6 section.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example`, append after the last line (the email section ends with `# EMAIL_BACKFILL_COUNT=50` — currently line 53):
  ```
  # --- School / Moodle (M6) ---
  # NC State WolfWare Moodle web services. Auth is a static per-user wstoken
  # (NOT OAuth) obtained via the Moodle mobile launch flow / the Preferences ->
  # Security keys page, then pasted into the Connect card — the token lives in
  # provider_accounts, never here. moodle_base_url has NO trailing slash; web
  # services POST to {MOODLE_BASE_URL}/webservice/rest/server.php.
  # MOODLE_BASE_URL=https://moodle-courses2527.wolfware.ncsu.edu
  # Background Moodle sync (mirrors EMAIL_SYNC_ENABLED / _SECONDS):
  # MOODLE_SYNC_ENABLED=true
  # MOODLE_SYNC_SECONDS=900
  # MOODLE_BACKFILL_DAYS_AHEAD=60
  ```

- [ ] **Step 6: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: baseline + 2 new tests, `0 failed`, still `1 skipped` (Postgres drift). Report "X tests passing" per the user's global convention (record the exact printed count as the gate for later tasks).

- [ ] **Step 7: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/config.py .env.example tests/test_moodle_config.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add Moodle settings block + .env.example M6 section

  Adds moodle_base_url (WolfWare host, no trailing slash), moodle_sync_enabled,
  moodle_sync_seconds (900), and moodle_backfill_days_ahead (60) to Settings per
  contract §A, plus a documented M6 block in .env.example. Auth is a static
  per-user wstoken stored in provider_accounts, never in config.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2: Normalized* dataclasses + `MoodleSnapshot` + `MoodleProvider` protocol

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_provider.py`

**Interfaces:**
- Consumes: `app.providers.base.OAuthProvider` (existing Protocol, base.py lines 76-89); the module imports already present at base.py lines 13-15 (`from dataclasses import dataclass, field`; `from datetime import date, datetime`; `from typing import Literal, Protocol, runtime_checkable`).
- Produces: `NormalizedCourse`, `NormalizedDeadline`, `NormalizedAssignment`, `NormalizedGrade`, `NormalizedAnnouncement`, `NormalizedNotification`, `MoodleSnapshot` dataclasses + the `@runtime_checkable MoodleProvider(OAuthProvider, Protocol)` — consumed by Task 3 (provider imports these), Task 5-7 (fetch methods return them), Task 9 (store upserts them), and the whole data layer. `MoodleSnapshot` is what `fetch_school_snapshot` returns; the sync (Task 12) selects providers via `hasattr(p, "fetch_school_snapshot")`.

- [ ] **Step 1: Write the failing provider-contract test.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_provider.py`:
  ```python
  """M6 base contract (§B): the six Normalized* Moodle dataclasses instantiate
  with their frozen fields, MoodleSnapshot bundles them with empty-list defaults,
  and MoodleProvider is a runtime_checkable Protocol extending OAuthProvider."""
  from datetime import datetime, timezone

  from app.providers.base import (
      MoodleProvider,
      MoodleSnapshot,
      NormalizedAnnouncement,
      NormalizedAssignment,
      NormalizedCourse,
      NormalizedDeadline,
      NormalizedGrade,
      NormalizedNotification,
      OAuthProvider,
  )

  UTC = timezone.utc


  def test_normalized_course_fields():
      c = NormalizedCourse(source="moodle", source_id="72", shortname="CSC216",
                           fullname="Programming Concepts — Java")
      assert c.source == "moodle" and c.source_id == "72"
      assert c.shortname == "CSC216"
      # defaults
      assert c.progress is None and c.start_at is None and c.end_at is None
      assert c.last_access_at is None and c.hidden is False


  def test_normalized_deadline_requires_due_at():
      due = datetime(2026, 7, 10, 23, 59, tzinfo=UTC)
      d = NormalizedDeadline(source="moodle", source_id="e1", course_id="72",
                             name="Summative assignment is due", module_name="assign",
                             event_type="due", due_at=due)
      assert d.due_at == due and d.overdue is False and d.url == ""


  def test_normalized_assignment_defaults():
      a = NormalizedAssignment(source="moodle", source_id="a1", course_id="72",
                               cmid="900", name="Project 1")
      assert a.due_at is None and a.cutoff_at is None and a.grade_max is None
      assert a.submission_status == "none" and a.grading_status == "" and a.graded is False


  def test_normalized_grade_defaults():
      g = NormalizedGrade(source="moodle", source_id="gi1", course_id="72",
                          item_name="Project 1", item_type="mod")
      assert g.grade_formatted == "-" and g.grade_raw is None
      assert g.grade_min is None and g.grade_max is None and g.graded_at is None


  def test_normalized_announcement_requires_created_at():
      created = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
      an = NormalizedAnnouncement(source="moodle", source_id="d1", course_id="72",
                                  forum_id="f1", subject="Welcome", author="Prof X",
                                  created_at=created)
      assert an.created_at == created and an.summary_html == "" and an.url == ""


  def test_normalized_notification_defaults():
      n = NormalizedNotification(source="moodle", source_id="n1", subject="Graded")
      assert n.full_message == "" and n.context_url == ""
      assert n.created_at is None and n.read is False


  def test_moodle_snapshot_defaults_to_empty_lists():
      snap = MoodleSnapshot()
      assert snap.courses == [] and snap.deadlines == [] and snap.assignments == []
      assert snap.grades == [] and snap.announcements == [] and snap.notifications == []
      # distinct list instances (field(default_factory=list), not a shared mutable)
      snap.courses.append(1)
      assert MoodleSnapshot().courses == []


  def test_moodle_provider_is_runtime_checkable_and_extends_oauth():
      assert issubclass(MoodleProvider, OAuthProvider)

      class _Impl:
          name = "moodle"
          def authorize_url(self, state): return ""
          def exchange_code(self, code): ...
          def refresh(self, tokens): ...
          def revoke(self, tokens): ...
          def set_tokens(self, tokens): ...
          def success_redirect(self): return ""
          def on_connected(self): ...
          def on_disconnect(self): ...
          def get_site_info(self, token): return {}
          def fetch_school_snapshot(self, since): return MoodleSnapshot()

      assert isinstance(_Impl(), MoodleProvider)
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_provider.py -q
  ```
  Expected failure: `ImportError: cannot import name 'MoodleProvider' from 'app.providers.base'` (none of the new names exist yet).

- [ ] **Step 3: Add the dataclasses + protocol to `base.py`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`, add the new block after the `NormalizedEmail` dataclass (currently ends at line 73) and before the `@runtime_checkable class OAuthProvider` (line 76). Insert exactly:
  ```python
  @dataclass
  class NormalizedCourse:
      source: str                          # 'moodle'
      source_id: str                       # course id
      shortname: str
      fullname: str
      progress: float | None = None        # 0..100 or None
      start_at: datetime | None = None
      end_at: datetime | None = None
      last_access_at: datetime | None = None
      hidden: bool = False


  @dataclass
  class NormalizedDeadline:                # the Timeline (core_calendar_get_action_events_by_timesort)
      source: str
      source_id: str                       # calendar event id
      course_id: str
      name: str                            # e.g. "Summative assignment is due"
      module_name: str                     # 'assign' | 'quiz' | 'lesson' | ...
      event_type: str                      # 'due' | 'close' | ...
      due_at: datetime                     # from timesort (epoch -> aware UTC)
      overdue: bool = False
      url: str = ""                        # viewurl


  @dataclass
  class NormalizedAssignment:
      source: str
      source_id: str                       # assign id
      course_id: str
      cmid: str
      name: str
      due_at: datetime | None = None
      cutoff_at: datetime | None = None
      grade_max: float | None = None
      submission_status: str = "none"      # 'new'|'draft'|'submitted'|'reopened'|'none'
      grading_status: str = ""             # 'graded'|'notgraded'|...
      graded: bool = False


  @dataclass
  class NormalizedGrade:
      source: str
      source_id: str                       # grade item id
      course_id: str
      item_name: str
      item_type: str                       # 'mod'|'course'|'category'
      grade_formatted: str = "-"           # display string (may contain HTML entities)
      grade_raw: float | None = None
      grade_min: float | None = None
      grade_max: float | None = None
      graded_at: datetime | None = None


  @dataclass
  class NormalizedAnnouncement:
      source: str
      source_id: str                       # discussion id
      course_id: str
      forum_id: str
      subject: str
      author: str
      created_at: datetime
      summary_html: str = ""               # short; stripped for display
      url: str = ""


  @dataclass
  class NormalizedNotification:
      source: str
      source_id: str                       # notification id
      subject: str
      full_message: str = ""               # stripped for display
      context_url: str = ""
      created_at: datetime | None = None
      read: bool = False


  @dataclass
  class MoodleSnapshot:                    # the bundle fetch_school_snapshot returns
      courses: list[NormalizedCourse] = field(default_factory=list)
      deadlines: list[NormalizedDeadline] = field(default_factory=list)
      assignments: list[NormalizedAssignment] = field(default_factory=list)
      grades: list[NormalizedGrade] = field(default_factory=list)
      announcements: list[NormalizedAnnouncement] = field(default_factory=list)
      notifications: list[NormalizedNotification] = field(default_factory=list)


  ```
  Then add the `MoodleProvider` Protocol at the END of the file, after the existing `EmailProvider` Protocol (currently ends at line 104):
  ```python
  @runtime_checkable
  class MoodleProvider(OAuthProvider, Protocol):
      """Read-only Moodle web-services adapter. Distinguishing method
      fetch_school_snapshot — moodle_sync selects providers by hasattr on it
      (mirrors email_sync's hasattr(p,'fetch_messages'))."""
      def get_site_info(self, token: str) -> dict: ...                 # connect-time validation
      def fetch_school_snapshot(self, since: datetime | None) -> MoodleSnapshot: ...
  ```

- [ ] **Step 4: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_provider.py -q
  ```
  Expected: `8 passed`.

- [ ] **Step 5: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior count + 8 new tests, `0 failed`, `1 skipped`. Report "X tests passing".

- [ ] **Step 6: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/base.py tests/test_moodle_provider.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add Moodle normalized dataclasses + MoodleProvider protocol

  Adds NormalizedCourse/Deadline/Assignment/Grade/Announcement/Notification and
  the MoodleSnapshot bundle to providers.base, plus a runtime_checkable
  MoodleProvider(OAuthProvider) whose distinguishing method is
  fetch_school_snapshot (the sync selects providers by hasattr on it) — all per
  contract §B. Every record carries source='moodle' + a str source_id.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 3: `MoodleProvider` core — `_call` seam + `_flatten`/`_epoch`/`_strip_html` + FakeMoodleHTTP + registry

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/__init__.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_call.py`

**Interfaces:**
- Consumes: `app.config.settings` (Task 1 `moodle_base_url`); `app.providers.base.AuthError`, `Tokens` (existing); the `_FakeResponse` httpx stand-in in `tests/fakes.py` (lines 172-180); the provider registry `_build_real()` try/except pattern (`__init__.py` lines 27-42).
- Produces: `app.providers.moodle.MoodleError(RuntimeError)`, `MoodleAuthError(AuthError)`; the constants `MOODLE_REST_PATH`, `MOODLE_LAUNCH_PATH`, `MOODLE_SERVICE`, `_AUTH_ERRORCODES`; `MoodleProvider` (name="moodle", NO `kind`) with the `configure`/`set_tokens`/`_transport`/`_call` seam, the OAuth-symmetry stubs, the hooks, and the module-level pure helpers `_flatten`/`_epoch`/`_strip_html`; `tests.fakes.FakeMoodleHTTP`. Consumed by Task 4 (`parse_pasted_token` + `get_site_info` build on `_call`), Tasks 5-7 (fetch methods call `_call`), Task 12 (sync selects it via `hasattr(fetch_school_snapshot)`).

- [ ] **Step 1: Add `FakeMoodleHTTP` to `tests/fakes.py` (test infra needed by the failing tests below).** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`, append after the `gmail_message(...)` builder (currently ends at line 246, before `class FakeEmailProvider:` at line 249):
  ```python
  # ---- moodle provider seam (M6) --------------------------------------------
  class _Seq:
      """Wrap successive per-call responses for ONE wsfunction. Needed because a
      plain list is a LITERAL array payload (some Moodle WS functions —
      core_enrol_get_users_courses, mod_forum_get_forums_by_courses — return a
      top-level JSON array), so a list cannot also mean 'call sequence'. Use
      seq(...) ONLY for a wsfunction the provider calls more than once in one
      fetch (calendar pagination, per-course grades, per-assignment status,
      per-forum discussions). Exhausting a sequence keeps returning its last item."""

      def __init__(self, items):
          self.items = list(items)
          self.i = 0

      def next(self):
          item = self.items[min(self.i, len(self.items) - 1)]
          self.i += 1
          return item


  def seq(*items):
      """seq(resp1, resp2, ...) — successive responses for a repeatedly-called wsfunction."""
      return _Seq(items)


  class FakeMoodleHTTP:
      """Scriptable transport for MoodleProvider.configure(fake_http=...).

      Constructed with responses= (alias: payloads=), a dict wsfunction -> value:
        - a dict OR list value is returned LITERALLY every call (a list is a real
          top-level array payload, e.g. core_enrol_get_users_courses returns a
          JSON array of courses);
        - a seq(...) value pops the next scripted response per successive call.
      exceptions= maps wsfunction -> an exception dict {"exception","errorcode",
      "message"} (Moodle returns errors as HTTP 200 with an "exception" key — see
      contract §C). .post(url, data=...) routes on data["wsfunction"] and records
      every post as (url, flattened-form-dict) so tests can assert the params
      reached server.php.
      """

      def __init__(self, responses: dict | None = None, exceptions: dict | None = None,
                   payloads: dict | None = None):
          # payloads= is a back-compat alias for responses=.
          self.responses = dict(responses if responses is not None else (payloads or {}))
          self.exceptions = exceptions or {}
          self.posts: list[tuple[str, dict]] = []  # (url, form-data dict)

      def post(self, url, data=None, headers=None):
          data = dict(data or {})
          self.posts.append((url, data))
          fn = data.get("wsfunction", "")
          if fn in self.exceptions:
              # Moodle web-service error: HTTP 200 with an exception body.
              return _FakeResponse(dict(self.exceptions[fn]))
          value = self.responses.get(fn, {})
          if isinstance(value, _Seq):
              return _FakeResponse(value.next())
          return _FakeResponse(value)     # literal dict OR top-level array

      def get(self, url, headers=None, params=None):  # unused by MoodleProvider
          return _FakeResponse({})
  ```

- [ ] **Step 2: Write the failing tests for `_flatten` + `_call` + registry.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_call.py`:
  ```python
  """M6 provider core (§C): _flatten PHP-array encoding, the _call web-service
  seam (token override + HTTP-200-exception check mapping to MoodleAuthError vs
  MoodleError), the pure helpers, and registry membership."""
  from datetime import datetime, timezone

  import pytest

  from app import providers
  from app.providers.base import Tokens
  from app.providers.moodle import (
      MoodleAuthError,
      MoodleError,
      MoodleProvider,
      _epoch,
      _flatten,
      _strip_html,
  )

  from .fakes import FakeMoodleHTTP


  def _provider(http, *, token: str = "tok123") -> MoodleProvider:
      p = MoodleProvider()
      p.configure(http)
      p.set_tokens(Tokens(access_token=token, refresh_token=None, expires_at=None,
                          scopes="", provider_user_id="56"))
      return p


  # ---- _flatten (PHP-array param encoding) ----
  def test_flatten_list_produces_indexed_keys():
      out = _flatten({"courseids": [72, 69]})
      assert out == {"courseids[0]": "72", "courseids[1]": "69"}


  def test_flatten_scalars_stringified():
      out = _flatten({"userid": 56, "newestfirst": 1})
      assert out == {"userid": "56", "newestfirst": "1"}


  def test_flatten_nested_dict_recurses():
      out = _flatten({"options": {"ids": [1, 2]}})
      assert out == {"options[ids][0]": "1", "options[ids][1]": "2"}


  # ---- _call ----
  def test_call_posts_token_wsfunction_and_flattened_params():
      http = FakeMoodleHTTP(payloads={"core_enrol_get_users_courses": [{"id": 72}]})
      p = _provider(http)
      out = p._call("core_enrol_get_users_courses", userid=56)
      assert out == [{"id": 72}]
      url, data = http.posts[-1]
      assert url.endswith("/webservice/rest/server.php")
      assert data["wstoken"] == "tok123"
      assert data["wsfunction"] == "core_enrol_get_users_courses"
      assert data["moodlewsrestformat"] == "json"
      assert data["userid"] == "56"


  def test_call_token_override_wins_over_injected_tokens():
      http = FakeMoodleHTTP(payloads={"core_webservice_get_site_info": {"userid": 56}})
      p = _provider(http, token="injected")
      p._call("core_webservice_get_site_info", token="pasted-token")
      _, data = http.posts[-1]
      assert data["wstoken"] == "pasted-token"


  def test_call_raises_moodle_auth_error_on_invalidtoken():
      http = FakeMoodleHTTP(exceptions={"core_webservice_get_site_info": {
          "exception": "moodle_exception", "errorcode": "invalidtoken",
          "message": "Invalid token - token not found",
      }})
      with pytest.raises(MoodleAuthError):
          _provider(http)._call("core_webservice_get_site_info")


  def test_call_raises_moodle_error_on_non_auth_exception():
      http = FakeMoodleHTTP(exceptions={"mod_assign_get_assignments": {
          "exception": "webservice_access_exception", "errorcode": "nofunction",
          "message": "Function not found",
      }})
      with pytest.raises(MoodleError) as ei:
          _provider(http)._call("mod_assign_get_assignments")
      assert not isinstance(ei.value, MoodleAuthError)


  # ---- pure helpers ----
  def test_epoch_maps_seconds_to_aware_utc_and_zero_to_none():
      dt = _epoch(1_782_777_540)
      assert dt is not None and dt.tzinfo is timezone.utc
      assert dt == datetime(2026, 6, 30, 4, 39, tzinfo=timezone.utc)
      assert _epoch(0) is None and _epoch(None) is None and _epoch("") is None


  def test_strip_html_drops_tags_and_collapses_whitespace():
      assert _strip_html("<p>Hello &amp; <b>welcome</b></p>") == "Hello & welcome"
      assert _strip_html("<script>x=1</script>Body") == "Body"
      assert _strip_html("") == ""


  # ---- registry membership ----
  def test_moodle_provider_registered_in_all_providers():
      providers.configure("unset")  # real registry (conftest installs [] for tests)
      try:
          names = {p.name for p in providers.all_providers()}
      finally:
          providers.configure([])   # restore the test-time empty registry
      assert "moodle" in names
  ```

- [ ] **Step 3: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_call.py -q
  ```
  Expected failure: `ModuleNotFoundError: No module named 'app.providers.moodle'` (the module does not exist yet).

- [ ] **Step 4: Create `app/providers/moodle.py` with the core seam + helpers + stubs.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`:
  ```python
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
  from .base import AuthError, Tokens

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
      def success_redirect(self) -> str:
          return "/?screen=school&connected=moodle"

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
  ```

- [ ] **Step 5: Register `MoodleProvider` in the registry.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/__init__.py`, add a third try/except block inside `_build_real()` after the GoogleProvider block (currently lines 36-40, ending with `pass  # GoogleProvider not present yet...`). Replace:
  ```python
          try:
              from .google import GoogleProvider
              built.append(GoogleProvider())
          except ImportError:
              pass  # GoogleProvider not present yet (mid-plan) — skip it.
          _real = built
      return _real
  ```
  with:
  ```python
          try:
              from .google import GoogleProvider
              built.append(GoogleProvider())
          except ImportError:
              pass  # GoogleProvider not present yet (mid-plan) — skip it.
          try:
              from .moodle import MoodleProvider
              built.append(MoodleProvider())
          except ImportError:
              pass  # MoodleProvider not present yet (mid-plan) — skip it.
          _real = built
      return _real
  ```

- [ ] **Step 6: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_call.py -q
  ```
  Expected: `10 passed` (3 `_flatten` + 4 `_call` + 2 helper + 1 registry).

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior count + 10, `0 failed`, `1 skipped`. Report "X tests passing". (The registry now builds a MoodleProvider; because its httpx client is lazy and conftest's `no_external_services` fixture installs `providers.configure([])` for every test, no test reaches the network.)

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/moodle.py app/providers/__init__.py tests/fakes.py tests/test_moodle_call.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add MoodleProvider core _call seam + pure helpers + registry

  New app/providers/moodle.py: MoodleError/MoodleAuthError, the configure/
  set_tokens/_transport http seam, the _call web-service wrapper (token override,
  PHP-array _flatten, HTTP-200 exception check mapping auth errorcodes to
  MoodleAuthError and the rest to MoodleError), OAuth-symmetry stubs (launch-url
  authorize_url, code-exchange-refused exchange_code, passthrough refresh, no-op
  revoke), the on_connected/on_disconnect lazy hooks, and the pure helpers
  _flatten/_epoch/_strip_html — all per contract §C. FakeMoodleHTTP routes on
  wsfunction; MoodleProvider is registered in the provider registry.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4: `parse_pasted_token` + `get_site_info`

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_call.py`

**Interfaces:**
- Consumes: `MoodleProvider._call` (Task 3); `MoodleError` (Task 3); `settings.moodle_base_url` (Task 1); stdlib `base64` / `hashlib` (already imported in moodle.py by Task 3); `FakeMoodleHTTP` (Task 3).
- Produces: `app.providers.moodle.parse_pasted_token(pasted, *, passport=None, wwwroot=None) -> str` (module-level, pure); `MoodleProvider.get_site_info(self, token: str) -> dict` returning `{"userid": int, "sitename": str, "release": str, "functions": [str, ...]}` — consumed by Task 13 (`POST /api/moodle/connect` validates the pasted token then calls `get_site_info`) and Task 7's `fetch_school_snapshot` (calls `get_site_info` for `userid` + `functions` feature-detection).

- [ ] **Step 1: Write the failing tests.** Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_call.py`, first adding `base64` + `hashlib` imports at the top of the file (alongside the existing imports) and importing the new symbols from `app.providers.moodle`:
  ```python
  import base64
  import hashlib
  ```
  and extend the existing `from app.providers.moodle import (...)` block to also import `get_site_info` is a method (no import change) and `parse_pasted_token`:
  ```python
  from app.providers.moodle import (
      MoodleAuthError,
      MoodleError,
      MoodleProvider,
      _epoch,
      _flatten,
      _strip_html,
      parse_pasted_token,
  )
  ```
  then append the tests:
  ```python
  # ---- parse_pasted_token ----
  def test_parse_bare_32_hex_token_passthrough():
      tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"   # 32 hex chars, live-verified format
      assert parse_pasted_token(tok) == tok
      # surrounding whitespace is tolerated
      assert parse_pasted_token("  " + tok + "\n") == tok


  def test_parse_launch_url_decodes_and_verifies_passport():
      wwwroot = "https://moodle-courses2527.wolfware.ncsu.edu"
      passport = "0.123456789"
      tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"
      signature = hashlib.md5((wwwroot + passport).encode()).hexdigest()
      raw = signature + ":::" + tok
      b64 = base64.b64encode(raw.encode()).decode()
      launch = "moodlemobile://token=" + b64

      parsed = parse_pasted_token(launch, passport=passport, wwwroot=wwwroot)
      assert parsed == tok


  def test_parse_launch_url_with_private_token_segment():
      wwwroot = "https://moodle-courses2527.wolfware.ncsu.edu"
      passport = "0.5"
      tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"
      priv = "CKjkasuZ8GQOveWdWzBa3p7MDlh4Y1MYAN2jkDJQddHHjPZZvKTYPm5TQpTuFCmX"
      signature = hashlib.md5((wwwroot + passport).encode()).hexdigest()
      raw = signature + ":::" + tok + ":::" + priv
      launch = "moodlemobile://token=" + base64.b64encode(raw.encode()).decode()

      # token segment is the SECOND field, private token is ignored
      assert parse_pasted_token(launch, passport=passport, wwwroot=wwwroot) == tok


  def test_parse_launch_url_bad_passport_raises():
      wwwroot = "https://moodle-courses2527.wolfware.ncsu.edu"
      tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"
      # signature computed with the WRONG passport -> md5 prefix won't match
      wrong_sig = hashlib.md5((wwwroot + "9.9").encode()).hexdigest()
      raw = wrong_sig + ":::" + tok
      launch = "app://token=" + base64.b64encode(raw.encode()).decode()
      with pytest.raises(MoodleError):
          parse_pasted_token(launch, passport="0.1", wwwroot=wwwroot)


  def test_parse_unrecognized_raises_moodle_error():
      with pytest.raises(MoodleError):
          parse_pasted_token("not a token")


  # ---- get_site_info ----
  def test_get_site_info_maps_functions_to_name_list():
      http = FakeMoodleHTTP(payloads={"core_webservice_get_site_info": {
          "userid": 56,
          "fullname": "Wolf Pack",
          "sitename": "WolfWare",
          "release": "4.5.1 (Build: 20250113)",
          "functions": [
              {"name": "core_enrol_get_users_courses", "version": "4.5"},
              {"name": "mod_assign_get_assignments", "version": "4.5"},
          ],
      }})
      info = _provider(http).get_site_info("pasted-token")
      assert info == {
          "userid": 56,
          "sitename": "WolfWare",
          "release": "4.5.1 (Build: 20250113)",
          "functions": ["core_enrol_get_users_courses", "mod_assign_get_assignments"],
      }
      # the pasted token was used as the wstoken (override), not the injected one
      _, data = http.posts[-1]
      assert data["wstoken"] == "pasted-token"
      assert data["wsfunction"] == "core_webservice_get_site_info"


  def test_get_site_info_auth_failure_raises_moodle_auth_error():
      http = FakeMoodleHTTP(exceptions={"core_webservice_get_site_info": {
          "exception": "moodle_exception", "errorcode": "invalidtoken",
          "message": "Invalid token",
      }})
      with pytest.raises(MoodleAuthError):
          _provider(http).get_site_info("bad-token")
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_call.py -q
  ```
  Expected failure: `ImportError: cannot import name 'parse_pasted_token' from 'app.providers.moodle'` (the function and `get_site_info` method do not exist yet).

- [ ] **Step 3: Implement `get_site_info` on the provider.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`, add `get_site_info` as a method on `MoodleProvider`, immediately after `_call` (added in Task 3) and before the `authorize_url` OAuth-plumbing block:
  ```python
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
  ```

- [ ] **Step 4: Implement `parse_pasted_token` as a module-level pure helper.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`, add after `_strip_html` (the last function in the module, added in Task 3):
  ```python
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
  ```

- [ ] **Step 5: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_call.py -q
  ```
  Expected: `17 passed` (10 from Task 3 + 5 parse + 2 get_site_info).

- [ ] **Step 6: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior count + 7, `0 failed`, `1 skipped`. Report "X tests passing".

- [ ] **Step 7: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/moodle.py tests/test_moodle_call.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add parse_pasted_token + get_site_info to MoodleProvider

  parse_pasted_token accepts a bare 32-hex wstoken (passthrough) or a
  '<scheme>://token=<base64>' mobile-launch redirect (base64-decode, split on
  ':::', md5(wwwroot+passport) verify, return the token segment) per contract §D.
  get_site_info calls core_webservice_get_site_info with the pasted token as a
  wstoken override and returns {userid, sitename, release, functions:[names]} —
  connect-time validation + snapshot feature-detection bootstrap (§C/§E).

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 5: `fetch_courses` + `fetch_deadlines` — the timeline

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py`

**Interfaces:**
- Consumes: `MoodleProvider.configure(fake_http)`, `MoodleProvider.set_tokens(tokens)`, `MoodleProvider._call(wsfunction, *, token=None, **params) -> dict | list`, `MoodleProvider._transport()`, and the module-level `_epoch(value) -> datetime | None` helper (all from Task 3/4, `moodle.py`); `MOODLE_REST_PATH` (contract §C, Task 3); `NormalizedCourse`, `NormalizedDeadline` dataclasses (contract §B, Task 2, `app.providers.base`); `Tokens` (`app.providers.base`); `settings.moodle_backfill_days_ahead` (contract §A, Task 1, `app.config`); the `FakeMoodleHTTP` test double built in Task 3 (`backend/tests/fakes.py`) whose constructor takes `responses: dict[str, object]` (a wsfunction-name → decoded-JSON map) and records every POST as `self.posts: list[tuple[str, dict]]` where the dict is the flattened form body (so tests can read `posts[i][1]["wsfunction"]`, `["timesortfrom"]`, `["aftereventid[...]"]`, etc.); the `_provider(http)` helper added to `test_moodle_fetch.py` in Task 4.
- Produces: `MoodleProvider.fetch_courses(self, userid: int) -> list[NormalizedCourse]` (consumed by Task 7 `fetch_school_snapshot` and Task 6 `fetch_grades` for the `course_ids` list); `MoodleProvider.fetch_deadlines(self, now: datetime) -> list[NormalizedDeadline]` (consumed by Task 7 `fetch_school_snapshot`).

- [ ] **Step 1: Create `test_moodle_fetch.py` with the shared `_provider` helper + `FakeMoodleHTTP`/`seq` imports.** Tasks 1-4 built the fetch layer's *core* tests in `test_moodle_call.py`; the `fetch_*` tests get their OWN file. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py` (if a prior task already created it, just ensure this exact import block + helper are present — relative `.fakes` import, `seq` included):
  ```python
  """MoodleProvider fetch_* methods (M6 contract §E) — every test drives the
  REAL MoodleProvider through FakeMoodleHTTP scripted with realistic Moodle
  web-service JSON. No network. [confirm-against-live] on every wsfunction /
  param / field name touched here — verified against the live WolfWare Moodle
  in Task 21; the constant names and method signatures are frozen."""
  from datetime import datetime, timezone

  import pytest

  from app.providers.base import Tokens
  from app.providers.moodle import MoodleProvider

  from .fakes import FakeMoodleHTTP, seq


  def _provider(http) -> MoodleProvider:
      p = MoodleProvider()
      p.configure(http)
      p.set_tokens(
          Tokens(
              access_token="wstoken-abc", refresh_token=None, expires_at=None,
              scopes="", provider_user_id="7",
          )
      )
      return p
  ```
  (`seq` is the call-sequence marker from `fakes.py` — used by the deadline-pagination, per-course-grades and per-assignment-status tests below; a plain list stays a literal array payload. Tasks 5-7 all append to this same file and reuse this helper.)

- [ ] **Step 2: Write the failing `fetch_courses` tests.** Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py`:
  ```python
  # ---- fetch_courses [confirm-against-live: core_enrol_get_users_courses;
  #      fields id/shortname/fullname/progress/startdate/enddate/lastaccess/hidden] ----

  def test_fetch_courses_maps_ws_json_to_normalized_courses():
      http = FakeMoodleHTTP(responses={
          "core_enrol_get_users_courses": [
              {
                  "id": 72, "shortname": "CSC510", "fullname": "Software Engineering",
                  "progress": 42.5, "startdate": 1725148800, "enddate": 1733011200,
                  "lastaccess": 1725580800, "hidden": 0,
              },
              {
                  "id": 69, "shortname": "MA305", "fullname": "Linear Algebra",
                  "progress": None, "startdate": 0, "enddate": 0,
                  "lastaccess": 0, "hidden": 1,
              },
          ],
      })
      courses = _provider(http).fetch_courses(userid=7)

      assert len(courses) == 2
      c0 = courses[0]
      assert c0.source == "moodle"
      assert c0.source_id == "72"                 # id coerced to str
      assert c0.shortname == "CSC510"
      assert c0.fullname == "Software Engineering"
      assert c0.progress == 42.5
      assert c0.start_at == datetime(2024, 9, 1, tzinfo=timezone.utc)   # 1725148800
      assert c0.end_at == datetime(2024, 12, 1, tzinfo=timezone.utc)    # 1733011200
      assert c0.last_access_at == datetime(2024, 9, 6, tzinfo=timezone.utc)  # 1725580800
      assert c0.hidden is False

      c1 = courses[1]
      assert c1.source_id == "69"
      assert c1.progress is None
      assert c1.start_at is None                   # epoch 0 -> None
      assert c1.end_at is None
      assert c1.last_access_at is None             # epoch 0 -> None
      assert c1.hidden is True                     # 1 -> True


  def test_fetch_courses_sends_userid_param():
      http = FakeMoodleHTTP(responses={"core_enrol_get_users_courses": []})
      _provider(http).fetch_courses(userid=7)

      url, body = http.posts[0]
      assert url.endswith("/webservice/rest/server.php")
      assert body["wsfunction"] == "core_enrol_get_users_courses"
      assert body["userid"] == "7"                 # PHP form field, flattened to str
      assert body["moodlewsrestformat"] == "json"


  def test_fetch_courses_empty_list_when_no_courses():
      http = FakeMoodleHTTP(responses={"core_enrol_get_users_courses": []})
      assert _provider(http).fetch_courses(userid=7) == []
  ```

- [ ] **Step 3: Write the failing `fetch_deadlines` tests** (mapping + that `timesortfrom`/`timesortto` were sent + the 50-per-page `aftereventid` pagination). Append to `test_moodle_fetch.py`:
  ```python
  # ---- fetch_deadlines [confirm-against-live: core_calendar_get_action_events_by_timesort;
  #      params timesortfrom/timesortto/limitnum/aftereventid; response
  #      {"events":[{id,name,modulename,eventtype,timesort,overdue,viewurl,course:{id}}]}] ----

  def _event(eid, timesort, *, name="Assignment is due", modulename="assign",
             eventtype="due", overdue=False, courseid=72):
      return {
          "id": eid, "name": name, "modulename": modulename, "eventtype": eventtype,
          "timesort": timesort, "overdue": overdue,
          "viewurl": f"https://moodle.example/mod/assign/view.php?id={eid}",
          "course": {"id": courseid},
      }


  def test_fetch_deadlines_maps_events_to_normalized_deadlines():
      http = FakeMoodleHTTP(responses={
          "core_calendar_get_action_events_by_timesort": {"events": [
              _event(9001, 1725580800, name="Summative assignment is due",
                     modulename="assign", eventtype="due", overdue=True, courseid=72),
          ]},
      })
      deadlines = _provider(http).fetch_deadlines(
          now=datetime(2024, 9, 1, tzinfo=timezone.utc)
      )

      assert len(deadlines) == 1
      d = deadlines[0]
      assert d.source == "moodle"
      assert d.source_id == "9001"
      assert d.course_id == "72"
      assert d.name == "Summative assignment is due"
      assert d.module_name == "assign"
      assert d.event_type == "due"
      assert d.due_at == datetime(2024, 9, 6, tzinfo=timezone.utc)   # 1725580800
      assert d.overdue is True
      assert d.url == "https://moodle.example/mod/assign/view.php?id=9001"


  def test_fetch_deadlines_sends_timesort_window_and_limit():
      http = FakeMoodleHTTP(responses={
          "core_calendar_get_action_events_by_timesort": {"events": []},
      })
      now = datetime(2024, 9, 1, tzinfo=timezone.utc)       # epoch 1725148800
      _provider(http).fetch_deadlines(now=now)

      url, body = http.posts[0]
      assert body["wsfunction"] == "core_calendar_get_action_events_by_timesort"
      assert body["timesortfrom"] == "1725148800"           # now epoch
      # now + settings.moodle_backfill_days_ahead (default 60) days:
      assert body["timesortto"] == str(1725148800 + 60 * 86400)
      assert body["limitnum"] == "50"


  def test_fetch_deadlines_paginates_via_aftereventid_while_page_is_full():
      # A full first page (exactly 50) triggers a second call keyed on the last
      # event id; the second, short page (< 50) stops pagination.
      page1 = [_event(3000 + i, 1725148800 + i) for i in range(50)]
      page2 = [_event(4000 + i, 1725238800 + i) for i in range(7)]
      http = FakeMoodleHTTP(responses={
          # seq(...) scripts successive per-call responses (this wsfunction is
          # called once per page); a bare list would be a literal array payload.
          "core_calendar_get_action_events_by_timesort": seq(
              {"events": page1},          # first call
              {"events": page2},          # second call (after aftereventid)
          ),
      })
      deadlines = _provider(http).fetch_deadlines(
          now=datetime(2024, 9, 1, tzinfo=timezone.utc)
      )

      assert len(deadlines) == 57                       # 50 + 7, both pages merged
      assert len(http.posts) == 2                       # exactly two WS calls
      # second call carried aftereventid = last id of page 1 (3049).
      _, body2 = http.posts[1]
      assert body2["aftereventid"] == "3049"


  def test_fetch_deadlines_single_short_page_makes_one_call():
      http = FakeMoodleHTTP(responses={
          "core_calendar_get_action_events_by_timesort": {"events": [
              _event(9001, 1725580800),
          ]},
      })
      _provider(http).fetch_deadlines(now=datetime(2024, 9, 1, tzinfo=timezone.utc))
      assert len(http.posts) == 1
  ```
  Note the `FakeMoodleHTTP` convention (frozen in Task 3): when a wsfunction's `responses[...]` value is a **list of dicts**, each successive POST for that wsfunction pops the next element (call-sequence scripting); a single dict is returned for every call. The pagination test relies on that sequencing.

- [ ] **Step 4: Run the tests and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_fetch.py -q
  ```
  Expected failure: `AttributeError: 'MoodleProvider' object has no attribute 'fetch_courses'` (and `fetch_deadlines`) — neither method exists yet.

- [ ] **Step 5: Implement `fetch_courses`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`, add the two normalized-dataclass names to the existing base import (the file already imports `AuthError`, `Tokens` per Task 3 — extend that import line to also pull the dataclasses):
  ```python
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
  ```
  (Import all six normalized dataclasses + `MoodleSnapshot` now so Tasks 6-7 need no further import edits.) Then add `fetch_courses` after `get_message`-equivalent — i.e. after the last method Task 4 left in the class (`get_site_info`); it is the first `fetch_*`:
  ```python
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
  ```

- [ ] **Step 6: Implement `fetch_deadlines`** (with `aftereventid` pagination). Add directly after `fetch_courses`:
  ```python
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
  ```
  Note: `due_at` on `NormalizedDeadline` is non-optional (contract §B), and every timeline event carries a `timesort`, so `_epoch` never returns `None` here in practice; the frozen dataclass field stays typed `datetime`.

- [ ] **Step 7: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_fetch.py -q
  ```
  Expected: all `fetch_courses`/`fetch_deadlines` tests pass (8 new tests).

- [ ] **Step 8: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior task's count + 8, `0 failed`. Report "X tests passing" (user CLAUDE.md rule).

- [ ] **Step 9: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/moodle.py tests/test_moodle_fetch.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): fetch_courses + fetch_deadlines (Moodle timeline)

  fetch_courses maps core_enrol_get_users_courses rows to NormalizedCourse
  (epoch->UTC via _epoch, hidden 0/1 -> bool). fetch_deadlines pulls the
  action-event timeline via core_calendar_get_action_events_by_timesort over a
  [now, now+backfill_days_ahead] epoch window, paginating on aftereventid while
  a page returns the full limitnum=50 (contract §E). All wsfunction/param/field
  names carry [confirm-against-live], resolved against WolfWare in Task 21.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 6: `fetch_assignments` (+ submission status merge) + `fetch_grades`

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py`

**Interfaces:**
- Consumes: `MoodleProvider._call`, module-level `_epoch` (Task 3, `moodle.py`); `NormalizedAssignment`, `NormalizedGrade` dataclasses (contract §B, Task 2, `app.providers.base`); the `FakeMoodleHTTP` response-map + `posts` recording convention and the `_provider(http)` helper (Task 3 / Task 4, established in Task 5).
- Produces: `MoodleProvider.fetch_assignments(self, userid: int) -> list[NormalizedAssignment]` (consumed by Task 7 `fetch_school_snapshot` and later by Task 11's `moodle_tasks` projector via the stored rows); `MoodleProvider.fetch_grades(self, userid: int, course_ids: list[str]) -> list[NormalizedGrade]` (consumed by Task 7 `fetch_school_snapshot`).

- [ ] **Step 1: Write the failing `fetch_assignments` tests** (mapping + that the per-assignment submission status is merged onto the RIGHT assignment). Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py`:
  ```python
  # ---- fetch_assignments [confirm-against-live: mod_assign_get_assignments ->
  #      {"courses":[{id, assignments:[{id,cmid,name,duedate,cutoffdate,grade}]}]};
  #      then mod_assign_get_submission_status(assignid,userid) ->
  #      lastattempt.submission.status / gradingstatus / graded] ----

  def _sub_status(status="submitted", gradingstatus="graded", graded=True):
      return {
          "lastattempt": {"submission": {"status": status}},
          "gradingstatus": gradingstatus,
          "graded": graded,
      }


  def test_fetch_assignments_maps_and_merges_submission_status_per_assignment():
      http = FakeMoodleHTTP(responses={
          "mod_assign_get_assignments": {"courses": [
              {"id": 72, "assignments": [
                  {"id": 501, "cmid": 8801, "name": "Design doc",
                   "duedate": 1725580800, "cutoffdate": 1725667200, "grade": 100},
                  {"id": 502, "cmid": 8802, "name": "Reflection",
                   "duedate": 0, "cutoffdate": 0, "grade": 20},
              ]},
          ]},
          # scripted per-call sequence: first call -> assign 501, second -> 502
          "mod_assign_get_submission_status": seq(
              _sub_status(status="submitted", gradingstatus="graded", graded=True),
              _sub_status(status="draft", gradingstatus="notgraded", graded=False),
          ),
      })
      assignments = _provider(http).fetch_assignments(userid=7)

      assert len(assignments) == 2
      a0, a1 = assignments
      assert a0.source == "moodle"
      assert a0.source_id == "501"
      assert a0.course_id == "72"
      assert a0.cmid == "8801"
      assert a0.name == "Design doc"
      assert a0.due_at == datetime(2024, 9, 6, tzinfo=timezone.utc)      # 1725580800
      assert a0.cutoff_at == datetime(2024, 9, 7, tzinfo=timezone.utc)   # 1725667200
      assert a0.grade_max == 100
      assert a0.submission_status == "submitted"     # merged onto 501
      assert a0.grading_status == "graded"
      assert a0.graded is True

      assert a1.source_id == "502"
      assert a1.due_at is None                        # duedate 0 -> None
      assert a1.cutoff_at is None
      assert a1.submission_status == "draft"          # merged onto 502, not 501
      assert a1.grading_status == "notgraded"
      assert a1.graded is False


  def test_fetch_assignments_passes_assignid_and_userid_to_status_call():
      http = FakeMoodleHTTP(responses={
          "mod_assign_get_assignments": {"courses": [
              {"id": 72, "assignments": [
                  {"id": 501, "cmid": 8801, "name": "Design doc",
                   "duedate": 1725580800, "cutoffdate": 0, "grade": 100},
              ]},
          ]},
          "mod_assign_get_submission_status": _sub_status(),
      })
      _provider(http).fetch_assignments(userid=7)

      # posts[0] = mod_assign_get_assignments; posts[1] = the status call.
      _, status_body = http.posts[1]
      assert status_body["wsfunction"] == "mod_assign_get_submission_status"
      assert status_body["assignid"] == "501"
      assert status_body["userid"] == "7"


  def test_fetch_assignments_status_defaults_when_lastattempt_missing():
      http = FakeMoodleHTTP(responses={
          "mod_assign_get_assignments": {"courses": [
              {"id": 72, "assignments": [
                  {"id": 501, "cmid": 8801, "name": "Design doc",
                   "duedate": 0, "cutoffdate": 0, "grade": 100},
              ]},
          ]},
          "mod_assign_get_submission_status": {"gradingstatus": "", "graded": False},
      })
      a = _provider(http).fetch_assignments(userid=7)[0]
      assert a.submission_status == "none"     # no lastattempt.submission -> "none"
      assert a.grading_status == ""
      assert a.graded is False


  def test_fetch_assignments_empty_when_no_courses():
      http = FakeMoodleHTTP(responses={"mod_assign_get_assignments": {"courses": []}})
      assert _provider(http).fetch_assignments(userid=7) == []
  ```

- [ ] **Step 2: Write the failing `fetch_grades` tests** (per-course mapping + `grade_raw` None when the raw is `"-"`/absent). Append to `test_moodle_fetch.py`:
  ```python
  # ---- fetch_grades [confirm-against-live: gradereport_user_get_grade_items
  #      (courseid,userid) -> usergrades[].gradeitems[]: id,itemname,itemtype,
  #      graderaw,gradeformatted,grademin,grademax,gradedategraded] ----

  def test_fetch_grades_maps_rows_per_course():
      http = FakeMoodleHTTP(responses={
          "gradereport_user_get_grade_items": {"usergrades": [
              {"gradeitems": [
                  {"id": 9001, "itemname": "Design doc", "itemtype": "mod",
                   "graderaw": 88.0, "gradeformatted": "88.00",
                   "grademin": 0.0, "grademax": 100.0,
                   "gradedategraded": 1725580800},
                  {"id": 9002, "itemname": "Course total", "itemtype": "course",
                   "graderaw": None, "gradeformatted": "-",
                   "grademin": 0.0, "grademax": 100.0,
                   "gradedategraded": 0},
              ]},
          ]},
      })
      grades = _provider(http).fetch_grades(userid=7, course_ids=["72"])

      assert len(grades) == 2
      g0, g1 = grades
      assert g0.source == "moodle"
      assert g0.source_id == "9001"
      assert g0.course_id == "72"                  # from the course_ids arg, not the row
      assert g0.item_name == "Design doc"
      assert g0.item_type == "mod"
      assert g0.grade_formatted == "88.00"
      assert g0.grade_raw == 88.0
      assert g0.grade_min == 0.0
      assert g0.grade_max == 100.0
      assert g0.graded_at == datetime(2024, 9, 6, tzinfo=timezone.utc)  # 1725580800

      # "-" / None raw -> grade_raw None; formatted string preserved as-is.
      assert g1.item_name == "Course total"
      assert g1.grade_formatted == "-"
      assert g1.grade_raw is None
      assert g1.graded_at is None                  # gradedategraded 0 -> None


  def test_fetch_grades_iterates_every_course_id():
      http = FakeMoodleHTTP(responses={
          # one call per course_id -> seq() scripts the two successive responses.
          "gradereport_user_get_grade_items": seq(
              {"usergrades": [{"gradeitems": [
                  {"id": 1, "itemname": "A", "itemtype": "mod",
                   "graderaw": 1.0, "gradeformatted": "1", "grademin": 0.0,
                   "grademax": 1.0, "gradedategraded": 0}]}]},
              {"usergrades": [{"gradeitems": [
                  {"id": 2, "itemname": "B", "itemtype": "mod",
                   "graderaw": 2.0, "gradeformatted": "2", "grademin": 0.0,
                   "grademax": 2.0, "gradedategraded": 0}]}]},
          ),
      })
      grades = _provider(http).fetch_grades(userid=7, course_ids=["72", "69"])

      assert [g.course_id for g in grades] == ["72", "69"]   # tagged per course
      assert len(http.posts) == 2                            # one call per course
      _, body0 = http.posts[0]
      _, body1 = http.posts[1]
      assert body0["courseid"] == "72"
      assert body0["userid"] == "7"
      assert body1["courseid"] == "69"


  def test_fetch_grades_empty_when_no_course_ids():
      http = FakeMoodleHTTP(responses={"gradereport_user_get_grade_items": {}})
      assert _provider(http).fetch_grades(userid=7, course_ids=[]) == []
      assert http.posts == []          # no course ids -> no WS calls at all
  ```

- [ ] **Step 3: Run the tests and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_fetch.py -q
  ```
  Expected failure: `AttributeError: 'MoodleProvider' object has no attribute 'fetch_assignments'` (and `fetch_grades`) — neither exists yet.

- [ ] **Step 4: Implement `fetch_assignments`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`, add after `fetch_deadlines`:
  ```python
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
  ```

- [ ] **Step 5: Implement `fetch_grades`.** Add after `fetch_assignments`:
  ```python
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
  ```

- [ ] **Step 6: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_fetch.py -q
  ```
  Expected: all `fetch_assignments`/`fetch_grades` tests pass (7 new tests), plus Task 5's still-green tests.

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior task's count + 7, `0 failed`. Report "X tests passing".

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/moodle.py tests/test_moodle_fetch.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): fetch_assignments (+submission status) + fetch_grades

  fetch_assignments maps mod_assign_get_assignments rows to NormalizedAssignment
  then merges each student's mod_assign_get_submission_status
  (lastattempt.submission.status / gradingstatus / graded) onto the matching
  assignment; duedate 0 -> None. fetch_grades pulls
  gradereport_user_get_grade_items per course, tagging each row with its course
  id and mapping graderaw "-"/absent to None (contract §E). wsfunction/param/
  field names carry [confirm-against-live], resolved in Task 21.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 7: `fetch_announcements` + `fetch_notifications` + `fetch_school_snapshot`

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py`

**Interfaces:**
- Consumes: `MoodleProvider._call`, `MoodleProvider.get_site_info(token) -> {"userid","sitename","release","functions":[str,...]}` (Task 4, `moodle.py`, returns `functions` as a flat list of wsfunction-name strings), module-level `_epoch` (Task 3); `MoodleProvider.set_tokens`/`self._tokens` (Task 3 — `self._tokens.access_token` supplies the wstoken for `get_site_info`); `fetch_courses`/`fetch_deadlines` (Task 5), `fetch_assignments`/`fetch_grades` (Task 6); `NormalizedAnnouncement`, `NormalizedNotification`, `MoodleSnapshot` dataclasses (contract §B, Task 2, `app.providers.base`); the `FakeMoodleHTTP` response-map + `posts` convention and `_provider(http)` helper (Task 5).
- Produces: `MoodleProvider.fetch_announcements(self, userid: int, course_ids: list[str]) -> list[NormalizedAnnouncement]`; `MoodleProvider.fetch_notifications(self, userid: int) -> list[NormalizedNotification]`; `MoodleProvider.fetch_school_snapshot(self, since: datetime | None) -> MoodleSnapshot` (the distinguishing method `moodle_sync` selects providers by `hasattr` on — Task 12); `self._userid: int | None` cached during the snapshot. Together these close out Phase P1 (contract §O) — the whole provider fetch surface is now driven end-to-end by `fetch_school_snapshot`.

- [ ] **Step 1: Write the failing `fetch_announcements` tests** (news-forum filter + discussion mapping, raw HTML kept in `summary_html`). Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_fetch.py`:
  ```python
  # ---- fetch_announcements [confirm-against-live: mod_forum_get_forums_by_courses
  #      (courseids[]) -> [{id,type,course,...}] keep type=='news'; then
  #      mod_forum_get_forum_discussions(forumid) ->
  #      {"discussions":[{discussion,subject,message,userfullname,created}]}] ----

  def test_fetch_announcements_keeps_only_news_forums_and_maps_discussions():
      http = FakeMoodleHTTP(responses={
          "mod_forum_get_forums_by_courses": [
              {"id": 11, "type": "news", "course": 72},
              {"id": 12, "type": "general", "course": 72},   # not an announcement forum
          ],
          "mod_forum_get_forum_discussions": {"discussions": [
              {"discussion": 3001, "subject": "Welcome to CSC510",
               "message": "<p>Read the <b>syllabus</b>.</p>",
               "userfullname": "Prof. Ada", "created": 1725580800},
          ]},
      })
      anns = _provider(http).fetch_announcements(userid=7, course_ids=["72"])

      assert len(anns) == 1                          # only the news forum's discussion
      a = anns[0]
      assert a.source == "moodle"
      assert a.source_id == "3001"                   # discussion id
      assert a.course_id == "72"
      assert a.forum_id == "11"
      assert a.subject == "Welcome to CSC510"
      assert a.author == "Prof. Ada"
      assert a.created_at == datetime(2024, 9, 6, tzinfo=timezone.utc)  # 1725580800
      # raw HTML is kept in summary_html (stripped only at display, per contract).
      assert a.summary_html == "<p>Read the <b>syllabus</b>.</p>"


  def test_fetch_announcements_sends_courseids_and_forumid_params():
      http = FakeMoodleHTTP(responses={
          "mod_forum_get_forums_by_courses": [{"id": 11, "type": "news", "course": 72}],
          "mod_forum_get_forum_discussions": {"discussions": []},
      })
      _provider(http).fetch_announcements(userid=7, course_ids=["72", "69"])

      _, forums_body = http.posts[0]
      assert forums_body["wsfunction"] == "mod_forum_get_forums_by_courses"
      assert forums_body["courseids[0]"] == "72"       # PHP-array flattened
      assert forums_body["courseids[1]"] == "69"
      _, disc_body = http.posts[1]
      assert disc_body["wsfunction"] == "mod_forum_get_forum_discussions"
      assert disc_body["forumid"] == "11"


  def test_fetch_announcements_empty_when_no_news_forums():
      http = FakeMoodleHTTP(responses={
          "mod_forum_get_forums_by_courses": [{"id": 12, "type": "general", "course": 72}],
      })
      anns = _provider(http).fetch_announcements(userid=7, course_ids=["72"])
      assert anns == []
      assert len(http.posts) == 1     # forums listed, but no discussion call made
  ```

- [ ] **Step 2: Write the failing `fetch_notifications` tests.** Append to `test_moodle_fetch.py`:
  ```python
  # ---- fetch_notifications [confirm-against-live: message_popup_get_popup_notifications
  #      (useridto,newestfirst,limit,offset) -> {"notifications":[{id,subject,
  #      fullmessage,contexturl,timecreated,read}]}  (NB limit/offset, NOT limitnum)] ----

  def test_fetch_notifications_maps_popup_notifications():
      http = FakeMoodleHTTP(responses={
          "message_popup_get_popup_notifications": {"notifications": [
              {"id": 7001, "subject": "Assignment graded",
               "fullmessage": "Your Design doc was graded.",
               "contexturl": "https://moodle.example/mod/assign/view.php?id=1",
               "timecreated": 1725580800, "read": False},
              {"id": 7002, "subject": "Reminder",
               "fullmessage": "Quiz closes tomorrow.", "contexturl": "",
               "timecreated": 0, "read": True},
          ]},
      })
      notes = _provider(http).fetch_notifications(userid=7)

      assert len(notes) == 2
      n0, n1 = notes
      assert n0.source == "moodle"
      assert n0.source_id == "7001"
      assert n0.subject == "Assignment graded"
      assert n0.full_message == "Your Design doc was graded."
      assert n0.context_url == "https://moodle.example/mod/assign/view.php?id=1"
      assert n0.created_at == datetime(2024, 9, 6, tzinfo=timezone.utc)  # 1725580800
      assert n0.read is False
      assert n1.source_id == "7002"
      assert n1.created_at is None            # timecreated 0 -> None
      assert n1.read is True


  def test_fetch_notifications_sends_limit_offset_not_limitnum():
      http = FakeMoodleHTTP(responses={
          "message_popup_get_popup_notifications": {"notifications": []},
      })
      _provider(http).fetch_notifications(userid=7)

      _, body = http.posts[0]
      assert body["wsfunction"] == "message_popup_get_popup_notifications"
      assert body["useridto"] == "7"
      assert body["newestfirst"] == "1"
      assert body["limit"] == "0"
      assert body["offset"] == "0"
      assert "limitnum" not in body           # this WS uses limit/offset
  ```

- [ ] **Step 3: Write the failing `fetch_school_snapshot` tests** (bundles all six lists; a missing optional wsfunction in `functions[]` yields an empty list without error). Append to `test_moodle_fetch.py`:
  ```python
  # ---- fetch_school_snapshot: get_site_info for userid+functions, feature-detect
  #      each optional wsfunction, assemble MoodleSnapshot from the six fetch_* ----

  _ALL_FUNCTIONS = [
      "core_enrol_get_users_courses",
      "core_calendar_get_action_events_by_timesort",
      "mod_assign_get_assignments",
      "mod_assign_get_submission_status",
      "gradereport_user_get_grade_items",
      "mod_forum_get_forums_by_courses",
      "mod_forum_get_forum_discussions",
      "message_popup_get_popup_notifications",
  ]


  def _snapshot_responses(functions):
      return {
          "core_webservice_get_site_info": {
              "userid": 7, "fullname": "Sam Student", "sitename": "WolfWare",
              "release": "5.2", "functions": [{"name": n} for n in functions],
          },
          "core_enrol_get_users_courses": [
              {"id": 72, "shortname": "CSC510", "fullname": "Software Engineering",
               "progress": 42.5, "startdate": 0, "enddate": 0,
               "lastaccess": 0, "hidden": 0},
          ],
          "core_calendar_get_action_events_by_timesort": {"events": [
              {"id": 9001, "name": "Assignment is due", "modulename": "assign",
               "eventtype": "due", "timesort": 1725580800, "overdue": False,
               "viewurl": "https://moodle.example/a", "course": {"id": 72}},
          ]},
          "mod_assign_get_assignments": {"courses": [
              {"id": 72, "assignments": [
                  {"id": 501, "cmid": 8801, "name": "Design doc",
                   "duedate": 1725580800, "cutoffdate": 0, "grade": 100},
              ]},
          ]},
          "mod_assign_get_submission_status": {
              "lastattempt": {"submission": {"status": "submitted"}},
              "gradingstatus": "graded", "graded": True,
          },
          "gradereport_user_get_grade_items": {"usergrades": [
              {"gradeitems": [
                  {"id": 9001, "itemname": "Design doc", "itemtype": "mod",
                   "graderaw": 88.0, "gradeformatted": "88.00",
                   "grademin": 0.0, "grademax": 100.0, "gradedategraded": 0},
              ]},
          ]},
          "mod_forum_get_forums_by_courses": [{"id": 11, "type": "news", "course": 72}],
          "mod_forum_get_forum_discussions": {"discussions": [
              {"discussion": 3001, "subject": "Welcome", "message": "<p>Hi</p>",
               "userfullname": "Prof. Ada", "created": 1725580800},
          ]},
          "message_popup_get_popup_notifications": {"notifications": [
              {"id": 7001, "subject": "Graded", "fullmessage": "Nice work.",
               "contexturl": "", "timecreated": 1725580800, "read": False},
          ]},
      }


  def test_fetch_school_snapshot_bundles_all_six_lists():
      http = FakeMoodleHTTP(responses=_snapshot_responses(_ALL_FUNCTIONS))
      snap = _provider(http).fetch_school_snapshot(since=None)

      assert len(snap.courses) == 1
      assert len(snap.deadlines) == 1
      assert len(snap.assignments) == 1
      assert len(snap.grades) == 1
      assert len(snap.announcements) == 1
      assert len(snap.notifications) == 1
      # spot-check bundling wired the right normalized objects through:
      assert snap.courses[0].shortname == "CSC510"
      assert snap.deadlines[0].source_id == "9001"
      assert snap.assignments[0].submission_status == "submitted"
      assert snap.grades[0].grade_formatted == "88.00"
      assert snap.announcements[0].subject == "Welcome"
      assert snap.notifications[0].subject == "Graded"


  def test_fetch_school_snapshot_caches_userid_from_site_info():
      http = FakeMoodleHTTP(responses=_snapshot_responses(_ALL_FUNCTIONS))
      p = _provider(http)
      p.fetch_school_snapshot(since=None)
      assert p._userid == 7


  def test_fetch_school_snapshot_skips_missing_notification_function():
      # functions[] lacks message_popup_get_popup_notifications -> notifications
      # == [] and NO error (feature-detect, never raise).
      funcs = [f for f in _ALL_FUNCTIONS
               if f != "message_popup_get_popup_notifications"]
      http = FakeMoodleHTTP(responses=_snapshot_responses(funcs))
      snap = _provider(http).fetch_school_snapshot(since=None)

      assert snap.notifications == []
      # the missing function was never called...
      called = [body["wsfunction"] for _, body in http.posts]
      assert "message_popup_get_popup_notifications" not in called
      # ...but the rest of the snapshot still populated normally.
      assert len(snap.courses) == 1
      assert len(snap.deadlines) == 1


  def test_fetch_school_snapshot_skips_missing_grades_function():
      funcs = [f for f in _ALL_FUNCTIONS
               if f != "gradereport_user_get_grade_items"]
      http = FakeMoodleHTTP(responses=_snapshot_responses(funcs))
      snap = _provider(http).fetch_school_snapshot(since=None)

      assert snap.grades == []
      assert len(snap.courses) == 1     # unaffected
  ```

- [ ] **Step 4: Run the tests and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_fetch.py -q
  ```
  Expected failure: `AttributeError: 'MoodleProvider' object has no attribute 'fetch_announcements'` (and `fetch_notifications`, `fetch_school_snapshot`) — none exist yet.

- [ ] **Step 5: Implement `fetch_announcements`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py`, add after `fetch_grades`:
  ```python
      def fetch_announcements(
          self, userid: int, course_ids: list[str]
      ) -> list[NormalizedAnnouncement]:
          """Course announcements: list forums for the given courses via
          mod_forum_get_forums_by_courses, keep only type=='news' (the
          announcement forum), then pull each news forum's discussions via
          mod_forum_get_forum_discussions. The raw discussion `message` HTML is
          kept verbatim in summary_html (stripped only at display, per contract
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
                      summary_html=disc.get("message") or "",
                      url="",
                  ))
          return out
  ```
  Note: `created_at` on `NormalizedAnnouncement` is non-optional (contract §B); every discussion carries a `created` epoch so `_epoch` yields a datetime here in practice.

- [ ] **Step 6: Implement `fetch_notifications`.** Add after `fetch_announcements`:
  ```python
      def fetch_notifications(self, userid: int) -> list[NormalizedNotification]:
          """Popup notifications via message_popup_get_popup_notifications
          (useridto=userid, newestfirst=1, limit=0 => all, offset=0). NB this WS
          uses limit/offset, NOT limitnum. fullmessage is kept raw in
          full_message (stripped at display); timecreated 0 -> None."""
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
                  full_message=note.get("fullmessage") or "",
                  context_url=note.get("contexturl") or "",
                  created_at=_epoch(note.get("timecreated")),
                  read=bool(note.get("read")),
              ))
          return out
  ```

- [ ] **Step 7: Implement `fetch_school_snapshot`** (site-info for userid + feature-detect + assemble). Add after `fetch_notifications`:
  ```python
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
  ```
  And add `self._userid: int | None = None` to `MoodleProvider.__init__` (Task 3 leaves `__init__` setting `self._http`/`self._client`/`self._tokens`; append this fourth line so `_userid` is always defined before the snapshot caches it):
  ```python
      def __init__(self) -> None:
          self._http: object | str = "unset"
          self._client = None
          self._tokens: Tokens | None = None
          self._userid: int | None = None
  ```
  Note: `get_site_info` (Task 4) returns `functions` as a **flat list of wsfunction-name strings** (it maps the raw `[{"name": ...}]` down to `[str, ...]` per contract §E), so the `available` set-membership check compares plain names — matching what the `_snapshot_responses` fixture's site-info feeds after Task 4's mapping.

- [ ] **Step 8: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_fetch.py -q
  ```
  Expected: all `fetch_announcements`/`fetch_notifications`/`fetch_school_snapshot` tests pass (11 new tests), plus Tasks 5-6's still-green tests — the entire `test_moodle_fetch.py` file is green.

- [ ] **Step 9: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior task's count + 11, `0 failed`. Report "X tests passing". This closes Phase P1 (provider foundation, Tasks 1-7) — confirm the full suite (M4 fitness + all M5 email + the new Moodle provider tests) is green before Phase P2 (data layer) begins.

- [ ] **Step 10: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/moodle.py tests/test_moodle_fetch.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): fetch_announcements + fetch_notifications + fetch_school_snapshot

  fetch_announcements lists course forums via mod_forum_get_forums_by_courses,
  keeps type=='news', and maps each news-forum discussion (raw message HTML
  kept in summary_html, stripped at display). fetch_notifications pulls
  message_popup_get_popup_notifications (limit/offset, not limitnum).
  fetch_school_snapshot calls get_site_info once for the userid (cached on
  self._userid) and the advertised functions[], feature-detects each optional
  wsfunction (missing -> empty list, never raises), and assembles a
  MoodleSnapshot from the six fetch_* methods — closing Phase P1 (contract §E).
  wsfunction/param/field names carry [confirm-against-live], resolved in Task 21.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 8: Six Moodle models + migration 0006 + migration tests

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/alembic/versions/0006_moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `app.models.Base`, `app.models.JSONField`, `app.models.utcnow` (existing, `models.py` lines 24-30); the sqlalchemy `mapped_column`/`Mapped` machinery and the `String`/`Text`/`DateTime`/`Boolean`/`UniqueConstraint` symbols; the 0005 migration chain (`revision = "0005"` in `backend/alembic/versions/0005_email.py`) as `down_revision`.
- Produces: six SQLAlchemy models `MoodleCourse`, `MoodleDeadline`, `MoodleAssignment`, `MoodleGrade`, `MoodleAnnouncement`, `MoodleNotification` (tables `moodle_courses` / `moodle_deadlines` / `moodle_assignments` / `moodle_grades` / `moodle_announcements` / `moodle_notifications`) — read/written by Task 9's store section; migration `0006` (`revision = "0006"`, `down_revision = "0005"`) that builds the same six tables + indexes so `compare_metadata` stays clean on Postgres; six new names in `test_migrations.ALL_TABLES` + a `moodle_cols` assertion block.

> **MIGRATION-NUMBER HAZARD (restate — Global Constraints):** this branch is based on `main`@head `0005`, so `revision="0006"` / `down_revision="0005"` is correct AS WRITTEN and executable now. IF the unmerged `m5-email-slice2` branch (which also introduces a `0006_email_actions`) merges to `main` before this branch does, RENUMBER this migration to `revision="0007"` / `down_revision="0006"` (the email revision id) during the rebase — two revisions sharing id `0006` is an Alembic multi-head that breaks `upgrade head`. The model code and table names do not change; only the two revision strings in `0006_moodle.py` do.

- [ ] **Step 1: Add `Boolean` and `Float` to the models.py sqlalchemy import.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py`, the current import (lines 17-20) is:
  ```python
  from sqlalchemy import (
      Date, DateTime, ForeignKey, Index, JSON, String, Text,
      UniqueConstraint, text,
  )
  ```
  Replace it with (adds `Boolean` and `Float`, which the six Moodle models need and which are not currently imported):
  ```python
  from sqlalchemy import (
      Boolean, Date, DateTime, Float, ForeignKey, Index, JSON, String, Text,
      UniqueConstraint, text,
  )
  ```

- [ ] **Step 2: Add the failing migration test edits first (ALL_TABLES + moodle_cols block).** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`, the current `ALL_TABLES` set is:
  ```python
  ALL_TABLES = {
      "tasks", "memories", "conversations", "conversation_messages",
      "task_reminders", "events", "habits", "habit_completions",
      "meals", "water_days", "nutrition_targets",
      "provider_accounts", "daily_snapshots", "workouts", "emails",
  }
  ```
  Replace it with (adds the six moodle table names):
  ```python
  ALL_TABLES = {
      "tasks", "memories", "conversations", "conversation_messages",
      "task_reminders", "events", "habits", "habit_completions",
      "meals", "water_days", "nutrition_targets",
      "provider_accounts", "daily_snapshots", "workouts", "emails",
      "moodle_courses", "moodle_deadlines", "moodle_assignments",
      "moodle_grades", "moodle_announcements", "moodle_notifications",
  }
  ```
  Then, in `test_upgrade_head_builds_full_schema`, the current tail (after the `email_cols` block) is:
  ```python
      email_cols = {c["name"] for c in inspect(engine).get_columns("emails")}
      assert {"owner", "source", "source_id", "thread_id", "from_name",
              "from_email", "subject", "snippet", "received_at", "unread",
              "category", "summary_json", "triaged_at"} <= email_cols
      assert "body" not in email_cols  # privacy: bodies never persisted
      engine.dispose()
  ```
  Replace it with (inserts a `moodle_cols`-style assertion block before `engine.dispose()`):
  ```python
      email_cols = {c["name"] for c in inspect(engine).get_columns("emails")}
      assert {"owner", "source", "source_id", "thread_id", "from_name",
              "from_email", "subject", "snippet", "received_at", "unread",
              "category", "summary_json", "triaged_at"} <= email_cols
      assert "body" not in email_cols  # privacy: bodies never persisted

      deadline_cols = {c["name"] for c in inspect(engine).get_columns("moodle_deadlines")}
      assert {"owner", "source", "source_id", "course_id", "name",
              "module_name", "event_type", "due_at", "overdue", "url",
              "meta", "created_at", "updated_at"} <= deadline_cols
      assignment_cols = {c["name"] for c in inspect(engine).get_columns("moodle_assignments")}
      assert {"owner", "source", "source_id", "course_id", "cmid", "name",
              "due_at", "cutoff_at", "grade_max", "submission_status",
              "grading_status", "graded", "meta"} <= assignment_cols
      grade_cols = {c["name"] for c in inspect(engine).get_columns("moodle_grades")}
      assert {"owner", "source", "source_id", "course_id", "item_name",
              "item_type", "grade_formatted", "grade_raw", "grade_min",
              "grade_max", "graded_at", "meta"} <= grade_cols
      course_cols = {c["name"] for c in inspect(engine).get_columns("moodle_courses")}
      assert {"owner", "source", "source_id", "shortname", "fullname",
              "progress", "start_at", "end_at", "last_access_at", "hidden",
              "meta"} <= course_cols
      announcement_cols = {c["name"] for c in inspect(engine).get_columns("moodle_announcements")}
      assert {"owner", "source", "source_id", "course_id", "forum_id",
              "subject", "author", "created_at", "summary_html", "url",
              "meta"} <= announcement_cols
      notification_cols = {c["name"] for c in inspect(engine).get_columns("moodle_notifications")}
      assert {"owner", "source", "source_id", "subject", "full_message",
              "context_url", "created_at", "read", "meta"} <= notification_cols
      engine.dispose()
  ```

- [ ] **Step 3: Run the migration tests and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_migrations.py -q
  ```
  Expected failure: `test_upgrade_head_builds_full_schema` fails at `ALL_TABLES <= tables` (the six `moodle_*` tables do not exist yet — neither the migration nor the models are written), and `test_downgrade_base_removes_everything` still passes vacuously. This confirms the tests are gating the new schema.

- [ ] **Step 4: Add the six Moodle models to models.py.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py`, append the following at the END of the file (after the existing `Email` class, which is the current tail). Each model follows the frozen §F column sets, the `(owner, source, source_id)` `UniqueConstraint`, `owner`/`source`/`source_id` indexes, and Python-side `default=utcnow`/`onupdate=utcnow` timestamps:
  ```python
  class MoodleCourse(Base):
      """A synced Moodle course (M6). Keyed (owner, source, source_id) =
      ('moodle', course id) so re-sync upserts idempotently. Read-only this
      slice — no course content or files stored, only the enrolment summary."""

      __tablename__ = "moodle_courses"
      __table_args__ = (
          UniqueConstraint("owner", "source", "source_id",
                           name="uq_moodle_courses_owner_source_source_id"),
      )

      id: Mapped[int] = mapped_column(primary_key=True)
      owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
      source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
      source_id: Mapped[str] = mapped_column(String(128), index=True)    # course id
      shortname: Mapped[str] = mapped_column(String(255), default="")
      fullname: Mapped[str] = mapped_column(Text, default="")
      progress: Mapped[float | None] = mapped_column(Float)              # 0..100 or None
      start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      hidden: Mapped[bool] = mapped_column(Boolean, default=False)
      meta: Mapped[dict] = mapped_column(JSONField, default=dict)
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), default=utcnow, onupdate=utcnow
      )


  class MoodleDeadline(Base):
      """A synced Moodle deadline / calendar action event (M6). Keyed
      (owner, source, source_id) = ('moodle', calendar event id). Projected
      read-only into the Calendar/Tasks surfaces at read time (never copied
      into the tasks/events tables)."""

      __tablename__ = "moodle_deadlines"
      __table_args__ = (
          UniqueConstraint("owner", "source", "source_id",
                           name="uq_moodle_deadlines_owner_source_source_id"),
      )

      id: Mapped[int] = mapped_column(primary_key=True)
      owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
      source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
      source_id: Mapped[str] = mapped_column(String(128), index=True)    # calendar event id
      course_id: Mapped[str] = mapped_column(String(32), index=True)
      name: Mapped[str] = mapped_column(Text, default="")
      module_name: Mapped[str] = mapped_column(String(32), default="")   # 'assign'|'quiz'|...
      event_type: Mapped[str] = mapped_column(String(32), default="")    # 'due'|'close'|...
      due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
      overdue: Mapped[bool] = mapped_column(Boolean, default=False)
      url: Mapped[str] = mapped_column(Text, default="")
      meta: Mapped[dict] = mapped_column(JSONField, default=dict)
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), default=utcnow, onupdate=utcnow
      )


  class MoodleAssignment(Base):
      """A synced Moodle assignment + submission status (M6). Keyed
      (owner, source, source_id) = ('moodle', assign id). Projected read-only
      into the Tasks surface at read time via its due date."""

      __tablename__ = "moodle_assignments"
      __table_args__ = (
          UniqueConstraint("owner", "source", "source_id",
                           name="uq_moodle_assignments_owner_source_source_id"),
      )

      id: Mapped[int] = mapped_column(primary_key=True)
      owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
      source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
      source_id: Mapped[str] = mapped_column(String(128), index=True)    # assign id
      course_id: Mapped[str] = mapped_column(String(32), index=True)
      cmid: Mapped[str] = mapped_column(String(32), default="")
      name: Mapped[str] = mapped_column(Text, default="")
      due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      grade_max: Mapped[float | None] = mapped_column(Float)
      submission_status: Mapped[str] = mapped_column(String(16), default="none")
      grading_status: Mapped[str] = mapped_column(String(32), default="")
      graded: Mapped[bool] = mapped_column(Boolean, default=False)
      meta: Mapped[dict] = mapped_column(JSONField, default=dict)
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), default=utcnow, onupdate=utcnow
      )


  class MoodleGrade(Base):
      """A synced Moodle grade item (M6). Keyed (owner, source, source_id) =
      ('moodle', grade item id). Display string kept alongside raw values."""

      __tablename__ = "moodle_grades"
      __table_args__ = (
          UniqueConstraint("owner", "source", "source_id",
                           name="uq_moodle_grades_owner_source_source_id"),
      )

      id: Mapped[int] = mapped_column(primary_key=True)
      owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
      source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
      source_id: Mapped[str] = mapped_column(String(128), index=True)    # grade item id
      course_id: Mapped[str] = mapped_column(String(32), index=True)
      item_name: Mapped[str] = mapped_column(Text, default="")
      item_type: Mapped[str] = mapped_column(String(16), default="")     # 'mod'|'course'|'category'
      grade_formatted: Mapped[str] = mapped_column(String(64), default="-")
      grade_raw: Mapped[float | None] = mapped_column(Float)
      grade_min: Mapped[float | None] = mapped_column(Float)
      grade_max: Mapped[float | None] = mapped_column(Float)
      graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      meta: Mapped[dict] = mapped_column(JSONField, default=dict)
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), default=utcnow, onupdate=utcnow
      )


  class MoodleAnnouncement(Base):
      """A synced Moodle news-forum announcement (M6). Keyed
      (owner, source, source_id) = ('moodle', discussion id). Only a short
      HTML summary is stored (stripped for display); no full post bodies."""

      __tablename__ = "moodle_announcements"
      __table_args__ = (
          UniqueConstraint("owner", "source", "source_id",
                           name="uq_moodle_announcements_owner_source_source_id"),
      )

      id: Mapped[int] = mapped_column(primary_key=True)
      owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
      source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
      source_id: Mapped[str] = mapped_column(String(128), index=True)    # discussion id
      course_id: Mapped[str] = mapped_column(String(32), index=True)
      forum_id: Mapped[str] = mapped_column(String(32), default="")
      subject: Mapped[str] = mapped_column(Text, default="")
      author: Mapped[str] = mapped_column(String(255), default="")
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
      summary_html: Mapped[str] = mapped_column(Text, default="")
      url: Mapped[str] = mapped_column(Text, default="")
      meta: Mapped[dict] = mapped_column(JSONField, default=dict)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), default=utcnow, onupdate=utcnow
      )


  class MoodleNotification(Base):
      """A synced Moodle popup notification (M6). Keyed
      (owner, source, source_id) = ('moodle', notification id). Message text
      is stripped of HTML for display."""

      __tablename__ = "moodle_notifications"
      __table_args__ = (
          UniqueConstraint("owner", "source", "source_id",
                           name="uq_moodle_notifications_owner_source_source_id"),
      )

      id: Mapped[int] = mapped_column(primary_key=True)
      owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
      source: Mapped[str] = mapped_column(String(16), index=True)        # 'moodle'
      source_id: Mapped[str] = mapped_column(String(128), index=True)    # notification id
      subject: Mapped[str] = mapped_column(Text, default="")
      full_message: Mapped[str] = mapped_column(Text, default="")
      context_url: Mapped[str] = mapped_column(Text, default="")
      created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
      read: Mapped[bool] = mapped_column(Boolean, default=False)
      meta: Mapped[dict] = mapped_column(JSONField, default=dict)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), default=utcnow, onupdate=utcnow
      )
  ```
  NB: `MoodleAnnouncement` and `MoodleNotification` have their own `created_at` domain column (the record's real creation time on Moodle, `nullable` on notifications) so they carry only an `updated_at` audit timestamp — matching §F which lists `created_at` as a domain field for those two tables but does not add a second audit `created_at`. The other four tables carry both audit timestamps (`created_at`/`updated_at`).

- [ ] **Step 5: Author the 0006 migration (mirror 0005_email.py — self-contained JSONField, no server_default).** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/alembic/versions/0006_moodle.py`:
  ```python
  """School domain (M6): synced Moodle courses / deadlines / assignments /
  grades / announcements / notifications.

  Six tables, each keyed (owner, source, source_id) = ('moodle', <id>) so
  re-sync upserts idempotently. Read-only this slice — no course content, no
  file bytes, no full post bodies stored. Deadlines/assignments are projected
  read-only into the Calendar/Tasks surfaces at read time, never copied into
  the tasks/events tables.

  Revision ID: 0006
  Revises: 0005
  Create Date: 2026-07-03
  """
  from __future__ import annotations

  import sqlalchemy as sa
  from alembic import op
  from sqlalchemy.dialects import postgresql

  revision = "0006"
  down_revision = "0005"
  branch_labels = None
  depends_on = None

  JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


  def upgrade() -> None:
      op.create_table(
          "moodle_courses",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("owner", sa.String(length=64), nullable=False),
          sa.Column("source", sa.String(length=16), nullable=False),
          sa.Column("source_id", sa.String(length=128), nullable=False),
          sa.Column("shortname", sa.String(length=255), nullable=False),
          sa.Column("fullname", sa.Text(), nullable=False),
          sa.Column("progress", sa.Float(), nullable=True),
          sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("hidden", sa.Boolean(), nullable=False),
          sa.Column("meta", JSONField, nullable=False),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
          sa.UniqueConstraint("owner", "source", "source_id",
                              name="uq_moodle_courses_owner_source_source_id"),
      )
      op.create_index(op.f("ix_moodle_courses_owner"), "moodle_courses", ["owner"])
      op.create_index(op.f("ix_moodle_courses_source"), "moodle_courses", ["source"])
      op.create_index(op.f("ix_moodle_courses_source_id"), "moodle_courses", ["source_id"])

      op.create_table(
          "moodle_deadlines",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("owner", sa.String(length=64), nullable=False),
          sa.Column("source", sa.String(length=16), nullable=False),
          sa.Column("source_id", sa.String(length=128), nullable=False),
          sa.Column("course_id", sa.String(length=32), nullable=False),
          sa.Column("name", sa.Text(), nullable=False),
          sa.Column("module_name", sa.String(length=32), nullable=False),
          sa.Column("event_type", sa.String(length=32), nullable=False),
          sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("overdue", sa.Boolean(), nullable=False),
          sa.Column("url", sa.Text(), nullable=False),
          sa.Column("meta", JSONField, nullable=False),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
          sa.UniqueConstraint("owner", "source", "source_id",
                              name="uq_moodle_deadlines_owner_source_source_id"),
      )
      op.create_index(op.f("ix_moodle_deadlines_owner"), "moodle_deadlines", ["owner"])
      op.create_index(op.f("ix_moodle_deadlines_source"), "moodle_deadlines", ["source"])
      op.create_index(op.f("ix_moodle_deadlines_source_id"), "moodle_deadlines", ["source_id"])
      op.create_index(op.f("ix_moodle_deadlines_course_id"), "moodle_deadlines", ["course_id"])
      op.create_index(op.f("ix_moodle_deadlines_due_at"), "moodle_deadlines", ["due_at"])

      op.create_table(
          "moodle_assignments",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("owner", sa.String(length=64), nullable=False),
          sa.Column("source", sa.String(length=16), nullable=False),
          sa.Column("source_id", sa.String(length=128), nullable=False),
          sa.Column("course_id", sa.String(length=32), nullable=False),
          sa.Column("cmid", sa.String(length=32), nullable=False),
          sa.Column("name", sa.Text(), nullable=False),
          sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("grade_max", sa.Float(), nullable=True),
          sa.Column("submission_status", sa.String(length=16), nullable=False),
          sa.Column("grading_status", sa.String(length=32), nullable=False),
          sa.Column("graded", sa.Boolean(), nullable=False),
          sa.Column("meta", JSONField, nullable=False),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
          sa.UniqueConstraint("owner", "source", "source_id",
                              name="uq_moodle_assignments_owner_source_source_id"),
      )
      op.create_index(op.f("ix_moodle_assignments_owner"), "moodle_assignments", ["owner"])
      op.create_index(op.f("ix_moodle_assignments_source"), "moodle_assignments", ["source"])
      op.create_index(op.f("ix_moodle_assignments_source_id"), "moodle_assignments", ["source_id"])
      op.create_index(op.f("ix_moodle_assignments_course_id"), "moodle_assignments", ["course_id"])

      op.create_table(
          "moodle_grades",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("owner", sa.String(length=64), nullable=False),
          sa.Column("source", sa.String(length=16), nullable=False),
          sa.Column("source_id", sa.String(length=128), nullable=False),
          sa.Column("course_id", sa.String(length=32), nullable=False),
          sa.Column("item_name", sa.Text(), nullable=False),
          sa.Column("item_type", sa.String(length=16), nullable=False),
          sa.Column("grade_formatted", sa.String(length=64), nullable=False),
          sa.Column("grade_raw", sa.Float(), nullable=True),
          sa.Column("grade_min", sa.Float(), nullable=True),
          sa.Column("grade_max", sa.Float(), nullable=True),
          sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("meta", JSONField, nullable=False),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
          sa.UniqueConstraint("owner", "source", "source_id",
                              name="uq_moodle_grades_owner_source_source_id"),
      )
      op.create_index(op.f("ix_moodle_grades_owner"), "moodle_grades", ["owner"])
      op.create_index(op.f("ix_moodle_grades_source"), "moodle_grades", ["source"])
      op.create_index(op.f("ix_moodle_grades_source_id"), "moodle_grades", ["source_id"])
      op.create_index(op.f("ix_moodle_grades_course_id"), "moodle_grades", ["course_id"])

      op.create_table(
          "moodle_announcements",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("owner", sa.String(length=64), nullable=False),
          sa.Column("source", sa.String(length=16), nullable=False),
          sa.Column("source_id", sa.String(length=128), nullable=False),
          sa.Column("course_id", sa.String(length=32), nullable=False),
          sa.Column("forum_id", sa.String(length=32), nullable=False),
          sa.Column("subject", sa.Text(), nullable=False),
          sa.Column("author", sa.String(length=255), nullable=False),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
          sa.Column("summary_html", sa.Text(), nullable=False),
          sa.Column("url", sa.Text(), nullable=False),
          sa.Column("meta", JSONField, nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
          sa.UniqueConstraint("owner", "source", "source_id",
                              name="uq_moodle_announcements_owner_source_source_id"),
      )
      op.create_index(op.f("ix_moodle_announcements_owner"), "moodle_announcements", ["owner"])
      op.create_index(op.f("ix_moodle_announcements_source"), "moodle_announcements", ["source"])
      op.create_index(op.f("ix_moodle_announcements_source_id"), "moodle_announcements", ["source_id"])
      op.create_index(op.f("ix_moodle_announcements_course_id"), "moodle_announcements", ["course_id"])

      op.create_table(
          "moodle_notifications",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("owner", sa.String(length=64), nullable=False),
          sa.Column("source", sa.String(length=16), nullable=False),
          sa.Column("source_id", sa.String(length=128), nullable=False),
          sa.Column("subject", sa.Text(), nullable=False),
          sa.Column("full_message", sa.Text(), nullable=False),
          sa.Column("context_url", sa.Text(), nullable=False),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
          sa.Column("read", sa.Boolean(), nullable=False),
          sa.Column("meta", JSONField, nullable=False),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
          sa.UniqueConstraint("owner", "source", "source_id",
                              name="uq_moodle_notifications_owner_source_source_id"),
      )
      op.create_index(op.f("ix_moodle_notifications_owner"), "moodle_notifications", ["owner"])
      op.create_index(op.f("ix_moodle_notifications_source"), "moodle_notifications", ["source"])
      op.create_index(op.f("ix_moodle_notifications_source_id"), "moodle_notifications", ["source_id"])


  def downgrade() -> None:
      op.drop_table("moodle_notifications")
      op.drop_table("moodle_announcements")
      op.drop_table("moodle_grades")
      op.drop_table("moodle_assignments")
      op.drop_table("moodle_deadlines")
      op.drop_table("moodle_courses")
  ```
  Notes (mirroring 0005_email.py): the migration defines its own local `JSONField` (self-contained, not imported from models.py); every non-nullable column is `nullable=False` with **no `server_default`** (Python-side `default=` on the models supplies values through the ORM); nullable columns (`progress`, `start_at`/`end_at`/`last_access_at`, `due_at`/`cutoff_at`/`grade_max` on assignments, `grade_raw`/`grade_min`/`grade_max`/`graded_at` on grades, notification `created_at`) are `nullable=True`, matching the `| None` model fields. `downgrade()` drops the six tables in reverse creation order.

- [ ] **Step 6: Run the migration tests and confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_migrations.py -q
  ```
  Expected: all non-skipped tests in the file pass (`test_upgrade_head_builds_full_schema` now finds all six `moodle_*` tables + the asserted column sets; `test_downgrade_base_removes_everything` confirms `downgrade()` drops them; the Postgres drift test stays skipped on SQLite). Typical: `2 passed, 1 skipped`.

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: baseline count unchanged except for the migration-test edits (the six models + migration add schema, not test cases; the `moodle_cols` assertions live inside the existing `test_upgrade_head_builds_full_schema`, so no new test IDs). `0 failed`. Report "X tests passing".

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/models.py alembic/versions/0006_moodle.py tests/test_migrations.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add six Moodle models + migration 0006

  Adds moodle_courses/deadlines/assignments/grades/announcements/
  notifications — each keyed (owner, source, source_id) with matching
  indexes and a JSONField meta column (contract §F). Migration 0006
  (down_revision 0005) mirrors 0005_email.py: self-contained JSONField,
  Python-side defaults (no server_default), reverse-order downgrade.
  test_migrations ALL_TABLES + a moodle column-set assertion block guard
  the new schema and the Postgres model/migration drift check.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 9: Store `# ---- moodle ----` section (serializers, upserts, reads, delete)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_store.py`

**Interfaces:**
- Consumes: the six models from Task 8 (`MoodleCourse`, `MoodleDeadline`, `MoodleAssignment`, `MoodleGrade`, `MoodleAnnouncement`, `MoodleNotification`); the §B normalized dataclasses `NormalizedCourse`/`NormalizedDeadline`/`NormalizedAssignment`/`NormalizedGrade`/`NormalizedAnnouncement`/`NormalizedNotification` (added to `app/providers/base.py` in Task 2); existing store internals `_retry_integrity` (`store.py` line 134), `_to_utc`/`aware_utc` (`store.py`/`display.py`), the `event_when_display` display helper (already imported from `.display`, `store.py` line 23), the `Store._session()` seam, and `settings.owner`.
- Produces: six `_moodle_*_dict` serializers; six `upsert_moodle_*` methods (`@_retry_integrity`, get-or-create by `(owner, source, source_id)`, metadata every pass); six read methods (`moodle_courses`, `moodle_deadlines(days_ahead)`, `moodle_grades(course_id)`, `moodle_announcements(course_id)`, `moodle_notifications`, `moodle_assignments(course_id)`); `delete_moodle_data(source) -> bool` — consumed by Task 10 (read-time projectors `moodle_calendar_events`/`moodle_tasks`), Task 12 (`moodle_sync._sync_provider` calls the upserts + `MoodleProvider.on_disconnect` calls `delete_moodle_data`), Task 13/14 (the `/api/moodle/*` router reads). **Do NOT write the read-time projectors (`moodle_calendar_events`/`moodle_tasks`) here — those are Task 10.**

- [ ] **Step 1: Add the six model names to the store.py models import.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, the `from .models import (` block currently lists `Conversation, ConversationMessage, DailySnapshot, Email, Event, Habit, ...`. Add the six Moodle model names to that import block (alphabetical placement near the other M-names, e.g. after `Meal`/before `NutritionTarget` — exact ordering is cosmetic, just ensure all six are imported):
  ```python
      MoodleAnnouncement,
      MoodleAssignment,
      MoodleCourse,
      MoodleDeadline,
      MoodleGrade,
      MoodleNotification,
  ```
  Also confirm the §B dataclasses are importable: `store.py` line 52 already reads `from .providers.base import NormalizedEmail, NormalizedSnapshot, NormalizedWorkout, Tokens`. Extend it to include the six Moodle normalized dataclasses (added to `base.py` in Task 2):
  ```python
  from .providers.base import (
      NormalizedAnnouncement,
      NormalizedAssignment,
      NormalizedCourse,
      NormalizedDeadline,
      NormalizedEmail,
      NormalizedGrade,
      NormalizedNotification,
      NormalizedSnapshot,
      NormalizedWorkout,
      Tokens,
  )
  ```

- [ ] **Step 2: Write the failing store test file.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_store.py`:
  ```python
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


  def _announcement(sid="30", course_id="72"):
      return NormalizedAnnouncement(
          source="moodle", source_id=sid, course_id=course_id, forum_id="11",
          subject="Welcome", author="Prof X",
          created_at=datetime(2026, 6, 30, 12, tzinfo=UTC),
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
  ```

- [ ] **Step 3: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_store.py -q
  ```
  Expected failure: `AttributeError: 'Store' object has no attribute 'upsert_moodle_course'` (the store section does not exist yet). If Task 2's dataclasses are not yet on `base.py` the import line fails first with `ImportError` — that is also expected until Task 2 lands (this task assumes Tasks 1-8 are complete per the phase map).

- [ ] **Step 4: Add the six `_moodle_*_dict` serializers near `_email_dict`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, directly after the `_email_dict` function (module-level, currently ending near line 405), add:
  ```python
  def _moodle_course_dict(c: MoodleCourse) -> dict:
      return {
          "id": c.id,
          "source_id": c.source_id,
          "shortname": c.shortname,
          "fullname": c.fullname,
          "progress": c.progress,
          "start_at": aware_utc(c.start_at),
          "end_at": aware_utc(c.end_at),
          "last_access_at": aware_utc(c.last_access_at),
          "hidden": c.hidden,
      }


  def _moodle_deadline_dict(d: MoodleDeadline) -> dict:
      due = aware_utc(d.due_at)
      return {
          "id": d.id,
          "source_id": d.source_id,
          "course_id": d.course_id,
          "name": d.name,
          "module_name": d.module_name,
          "event_type": d.event_type,
          "due_at": due,
          "overdue": d.overdue,
          "url": d.url,
          # Derived display string (never stored) — reuse the calendar
          # "Up next" formatter; a deadline is a point in time, so start==end.
          "when": event_when_display(due, due, "", None),
      }


  def _moodle_assignment_dict(a: MoodleAssignment) -> dict:
      return {
          "id": a.id,
          "source_id": a.source_id,
          "course_id": a.course_id,
          "cmid": a.cmid,
          "name": a.name,
          "due_at": aware_utc(a.due_at),
          "cutoff_at": aware_utc(a.cutoff_at),
          "grade_max": a.grade_max,
          "submission_status": a.submission_status,
          "grading_status": a.grading_status,
          "graded": a.graded,
      }


  def _moodle_grade_dict(g: MoodleGrade) -> dict:
      return {
          "id": g.id,
          "source_id": g.source_id,
          "course_id": g.course_id,
          "item_name": g.item_name,
          "item_type": g.item_type,
          "grade_formatted": g.grade_formatted,
          "grade_raw": g.grade_raw,
          "grade_min": g.grade_min,
          "grade_max": g.grade_max,
          "graded_at": aware_utc(g.graded_at),
      }


  def _moodle_announcement_dict(a: MoodleAnnouncement) -> dict:
      return {
          "id": a.id,
          "source_id": a.source_id,
          "course_id": a.course_id,
          "forum_id": a.forum_id,
          "subject": a.subject,
          "author": a.author,
          "created_at": aware_utc(a.created_at),
          "summary_html": a.summary_html,
          "url": a.url,
      }


  def _moodle_notification_dict(n: MoodleNotification) -> dict:
      return {
          "id": n.id,
          "source_id": n.source_id,
          "subject": n.subject,
          "full_message": n.full_message,
          "context_url": n.context_url,
          "created_at": aware_utc(n.created_at),
          "read": n.read,
      }
  ```
  Note: `_moodle_deadline_dict` includes the derived `"when"` display (the §G requirement) via the existing `event_when_display` helper — the file imports `event_when_display` (not an `email_when_display`-only import), and a deadline is a single instant so `start == end == due`. No new import is needed.

- [ ] **Step 5: Add the `# ---- moodle ----` store section (row finders + six upserts).** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, inside the `Store` class, add the following section directly after the email store methods (after `delete_email_data`, currently near line 1346). First the shared row-finder helper + the six upserts (each `@_retry_integrity`, get-or-create by `(owner, source, source_id)`, writing metadata on every pass — cloning `upsert_email`'s shape):
  ```python
      # ---- moodle ----
      def _moodle_row(self, s: Session, model, source: str, source_id: str):
          from .config import settings

          return s.scalars(
              select(model)
              .where(model.owner == settings.owner)
              .where(model.source == source)
              .where(model.source_id == source_id)
          ).first()

      @_retry_integrity
      def upsert_moodle_course(self, c: NormalizedCourse) -> dict:
          """Get-or-create by (owner, source, source_id); writes metadata every
          pass so re-sync keeps the enrolment summary fresh."""
          from .config import settings

          with self._session() as s, s.begin():
              row = self._moodle_row(s, MoodleCourse, c.source, c.source_id)
              if row is None:
                  row = MoodleCourse(owner=settings.owner, source=c.source,
                                     source_id=c.source_id)
                  s.add(row)
              row.shortname = c.shortname
              row.fullname = c.fullname
              row.progress = c.progress
              row.start_at = _to_utc(c.start_at) if c.start_at else None
              row.end_at = _to_utc(c.end_at) if c.end_at else None
              row.last_access_at = _to_utc(c.last_access_at) if c.last_access_at else None
              row.hidden = c.hidden
              s.flush()
              return _moodle_course_dict(row)

      @_retry_integrity
      def upsert_moodle_deadline(self, d: NormalizedDeadline) -> dict:
          from .config import settings

          with self._session() as s, s.begin():
              row = self._moodle_row(s, MoodleDeadline, d.source, d.source_id)
              if row is None:
                  row = MoodleDeadline(owner=settings.owner, source=d.source,
                                       source_id=d.source_id)
                  s.add(row)
              row.course_id = d.course_id
              row.name = d.name
              row.module_name = d.module_name
              row.event_type = d.event_type
              row.due_at = _to_utc(d.due_at)
              row.overdue = d.overdue
              row.url = d.url
              s.flush()
              return _moodle_deadline_dict(row)

      @_retry_integrity
      def upsert_moodle_assignment(self, a: NormalizedAssignment) -> dict:
          from .config import settings

          with self._session() as s, s.begin():
              row = self._moodle_row(s, MoodleAssignment, a.source, a.source_id)
              if row is None:
                  row = MoodleAssignment(owner=settings.owner, source=a.source,
                                         source_id=a.source_id)
                  s.add(row)
              row.course_id = a.course_id
              row.cmid = a.cmid
              row.name = a.name
              row.due_at = _to_utc(a.due_at) if a.due_at else None
              row.cutoff_at = _to_utc(a.cutoff_at) if a.cutoff_at else None
              row.grade_max = a.grade_max
              row.submission_status = a.submission_status
              row.grading_status = a.grading_status
              row.graded = a.graded
              s.flush()
              return _moodle_assignment_dict(row)

      @_retry_integrity
      def upsert_moodle_grade(self, g: NormalizedGrade) -> dict:
          from .config import settings

          with self._session() as s, s.begin():
              row = self._moodle_row(s, MoodleGrade, g.source, g.source_id)
              if row is None:
                  row = MoodleGrade(owner=settings.owner, source=g.source,
                                    source_id=g.source_id)
                  s.add(row)
              row.course_id = g.course_id
              row.item_name = g.item_name
              row.item_type = g.item_type
              row.grade_formatted = g.grade_formatted
              row.grade_raw = g.grade_raw
              row.grade_min = g.grade_min
              row.grade_max = g.grade_max
              row.graded_at = _to_utc(g.graded_at) if g.graded_at else None
              s.flush()
              return _moodle_grade_dict(row)

      @_retry_integrity
      def upsert_moodle_announcement(self, a: NormalizedAnnouncement) -> dict:
          from .config import settings

          with self._session() as s, s.begin():
              row = self._moodle_row(s, MoodleAnnouncement, a.source, a.source_id)
              if row is None:
                  row = MoodleAnnouncement(owner=settings.owner, source=a.source,
                                           source_id=a.source_id)
                  s.add(row)
              row.course_id = a.course_id
              row.forum_id = a.forum_id
              row.subject = a.subject
              row.author = a.author
              row.created_at = _to_utc(a.created_at)
              row.summary_html = a.summary_html
              row.url = a.url
              s.flush()
              return _moodle_announcement_dict(row)

      @_retry_integrity
      def upsert_moodle_notification(self, n: NormalizedNotification) -> dict:
          from .config import settings

          with self._session() as s, s.begin():
              row = self._moodle_row(s, MoodleNotification, n.source, n.source_id)
              if row is None:
                  row = MoodleNotification(owner=settings.owner, source=n.source,
                                           source_id=n.source_id)
                  s.add(row)
              row.subject = n.subject
              row.full_message = n.full_message
              row.context_url = n.context_url
              row.created_at = _to_utc(n.created_at) if n.created_at else None
              row.read = n.read
              s.flush()
              return _moodle_notification_dict(row)
  ```

- [ ] **Step 6: Add the six read methods + `delete_moodle_data` (still inside the `# ---- moodle ----` section).** Immediately after the six upserts, add the read methods and the disconnect delete hook. `moodle_deadlines(days_ahead)` orders by `due_at` asc and, when `days_ahead` is given, keeps only deadlines with `due_at` in `[now, now + days_ahead)`; `delete_moodle_data` deletes all six tables where `(owner, source)` and returns whether anything was deleted (cloning `delete_email_data`):
  ```python
      def moodle_courses(self) -> list[dict]:
          from .config import settings

          with self._session() as s:
              rows = s.scalars(
                  select(MoodleCourse)
                  .where(MoodleCourse.owner == settings.owner)
                  .order_by(MoodleCourse.shortname)
              ).all()
              return [_moodle_course_dict(c) for c in rows]

      def moodle_deadlines(self, days_ahead: int | None = None) -> list[dict]:
          """Deadlines ordered by due_at asc. With days_ahead, only those due in
          [now, now + days_ahead)."""
          from .config import settings

          with self._session() as s:
              q = (
                  select(MoodleDeadline)
                  .where(MoodleDeadline.owner == settings.owner)
                  .order_by(MoodleDeadline.due_at)
              )
              if days_ahead is not None:
                  now = utcnow()
                  horizon = now + timedelta(days=days_ahead)
                  q = q.where(MoodleDeadline.due_at >= now).where(
                      MoodleDeadline.due_at < horizon
                  )
              rows = s.scalars(q).all()
              return [_moodle_deadline_dict(d) for d in rows]

      def moodle_assignments(self, course_id: str | None = None) -> list[dict]:
          from .config import settings

          with self._session() as s:
              q = (
                  select(MoodleAssignment)
                  .where(MoodleAssignment.owner == settings.owner)
                  .order_by(MoodleAssignment.due_at)
              )
              if course_id is not None:
                  q = q.where(MoodleAssignment.course_id == course_id)
              rows = s.scalars(q).all()
              return [_moodle_assignment_dict(a) for a in rows]

      def moodle_grades(self, course_id: str | None = None) -> list[dict]:
          from .config import settings

          with self._session() as s:
              q = (
                  select(MoodleGrade)
                  .where(MoodleGrade.owner == settings.owner)
                  .order_by(MoodleGrade.id)
              )
              if course_id is not None:
                  q = q.where(MoodleGrade.course_id == course_id)
              rows = s.scalars(q).all()
              return [_moodle_grade_dict(g) for g in rows]

      def moodle_announcements(self, course_id: str | None = None) -> list[dict]:
          from .config import settings

          with self._session() as s:
              q = (
                  select(MoodleAnnouncement)
                  .where(MoodleAnnouncement.owner == settings.owner)
                  .order_by(MoodleAnnouncement.created_at.desc())
              )
              if course_id is not None:
                  q = q.where(MoodleAnnouncement.course_id == course_id)
              rows = s.scalars(q).all()
              return [_moodle_announcement_dict(a) for a in rows]

      def moodle_notifications(self) -> list[dict]:
          from .config import settings

          with self._session() as s:
              rows = s.scalars(
                  select(MoodleNotification)
                  .where(MoodleNotification.owner == settings.owner)
                  .order_by(MoodleNotification.created_at.desc())
              ).all()
              return [_moodle_notification_dict(n) for n in rows]

      def delete_moodle_data(self, source: str) -> bool:
          """Disconnect hook (MoodleProvider.on_disconnect): delete every moodle_*
          row where (owner, source). Returns True iff any row was deleted.
          Separate from delete_provider_data (which owns the provider_accounts
          row); the shared router deletes the account, this deletes the domain
          data. Mirrors delete_email_data."""
          from .config import settings

          deleted = False
          with self._session() as s, s.begin():
              for model in (
                  MoodleCourse,
                  MoodleDeadline,
                  MoodleAssignment,
                  MoodleGrade,
                  MoodleAnnouncement,
                  MoodleNotification,
              ):
                  for row in s.scalars(
                      select(model)
                      .where(model.owner == settings.owner)
                      .where(model.source == source)
                  ):
                      s.delete(row)
                      deleted = True
          return deleted
  ```

- [ ] **Step 7: Run the store test and confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_store.py -q
  ```
  Expected: `6 passed` (idempotency for course/deadline, idempotency for assignment+grade+announcement+notification, owner-scoping, delete-all-six, days_ahead horizon).

- [ ] **Step 8: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior count + 6 new tests, `0 failed`. Report "X tests passing".

- [ ] **Step 9: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/store.py tests/test_moodle_store.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add store moodle section (upserts, reads, delete)

  Six _moodle_*_dict serializers (deadline carries a derived "when" via
  event_when_display), six @_retry_integrity upserts keyed
  (owner, source, source_id) writing metadata every pass, owner-scoped
  reads (courses / deadlines(days_ahead horizon) / assignments(course_id)
  / grades(course_id) / announcements(course_id) / notifications), and
  delete_moodle_data clearing all six tables for on_disconnect — cloning
  the email store shape (contract §G). Read-time projectors are Task 10.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 10: Schema widening — `id: int | str`, `source`, `editable` on EventOccurrence + Task (+ Tint/TaskGroup Literals)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_schema_widening.py`

**Interfaces:**
- Consumes: `app.schemas.EventOccurrence` (existing model, `schemas.py` lines 187-201, `id: int`, `tint: Tint`); `app.schemas.Task` (existing model, `schemas.py` lines 105-125, `id: int`, `group: TaskGroup`, `prio: TaskPriority`, serialized `list` key); the `Tint` Literal (`schemas.py` line 25, currently `Literal["green", "sky", "plum", "honey", "clay"]`); the `TaskGroup` Literal (`schemas.py` line 22, currently `Literal["Today", "Upcoming", "Someday"]`); the `TaskPriority` Literal (`schemas.py` line 23, currently `Literal["low", "med", "high"]` — already contains `"med"`, unchanged).
- Produces: `EventOccurrence.id: int | str`, `EventOccurrence.source: str = "local"`, `EventOccurrence.editable: bool = True`; `Task.id: int | str`, `Task.source: str = "local"`, `Task.editable: bool = True`; `Tint` widened with `"grape"`; `TaskGroup` widened with `"School"` — all consumed by Task 11 (the `moodle_calendar_events` / `moodle_tasks` projectors emit `id="moodle:<n>"`, `source="moodle"`, `editable=False`, `tint="grape"`, `group="School"`, `list="School"` dicts that must validate through these two response models).

- [ ] **Step 1: Write the failing schema-widening test file.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_schema_widening.py`:
  ```python
  """M6 School slice-1 contract §H — additive widening of the Calendar/Tasks
  response models so read-time Moodle projections (id='moodle:<n>',
  source='moodle', editable=False) validate alongside real local rows, which
  must keep validating unchanged and defaulting to source='local'/editable=True.
  Pure pydantic validation — no DB, no network."""
  from datetime import datetime, timezone

  from app.schemas import EventOccurrence, Task, TaskGroup, Tint


  def _local_event_dict() -> dict:
      # The exact shape store._occurrence_dict emits for a real Event row —
      # note it carries NO source/editable keys (those are additive here).
      return {
          "id": 7,
          "title": "Standup",
          "start": datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
          "end": datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
          "tint": "sky",
          "location": "",
          "description": "",
          "recurring": False,
          "recurrence_label": None,
          "at": "9:00am",
      }


  def _local_task_dict() -> dict:
      # The exact shape store._task_dict emits for a real Task row — no
      # source/editable keys.
      return {
          "id": 3,
          "label": "Buy milk",
          "done": False,
          "group": "Today",
          "deadline": None,
          "prio": "med",
          "list": "Personal",
          "description": "",
          "subtasks": [],
          "labels": [],
          "reminders": [],
          "files": [],
          "recurrence": None,
          "recurrence_label": None,
          "due": None,
          "late": False,
          "created_at": datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
          "updated_at": datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
          "completed_at": None,
      }


  def test_existing_event_dict_without_source_editable_still_validates_and_defaults():
      occ = EventOccurrence.model_validate(_local_event_dict())
      assert occ.id == 7
      assert occ.source == "local"
      assert occ.editable is True


  def test_existing_task_dict_without_source_editable_still_validates_and_defaults():
      task = Task.model_validate(_local_task_dict())
      assert task.id == 3
      assert task.source == "local"
      assert task.editable is True


  def test_moodle_projected_event_with_string_id_validates():
      d = _local_event_dict()
      d.update(id="moodle:1", source="moodle", editable=False, tint="grape")
      occ = EventOccurrence.model_validate(d)
      assert occ.id == "moodle:1"
      assert occ.source == "moodle"
      assert occ.editable is False
      assert occ.tint == "grape"


  def test_moodle_projected_task_with_string_id_validates():
      d = _local_task_dict()
      d.update(id="moodle:1", source="moodle", editable=False,
               group="School", list="School")
      task = Task.model_validate(d)
      assert task.id == "moodle:1"
      assert task.source == "moodle"
      assert task.editable is False
      assert task.group == "School"
      assert task.list == "School"


  def test_grape_is_a_valid_tint_and_school_a_valid_taskgroup():
      # The two new Literal members the projection relies on.
      assert "grape" in Tint.__args__
      assert "School" in TaskGroup.__args__
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_schema_widening.py -q
  ```
  Expected failure: `test_moodle_projected_event_with_string_id_validates` and `test_moodle_projected_task_with_string_id_validates` fail with a pydantic `ValidationError` — `EventOccurrence.id`/`Task.id` are `int`, so `"moodle:1"` is rejected, and `tint="grape"`/`group="School"` are not in their Literals. `test_existing_*_defaults` fail on `AttributeError`/`ValidationError` because `source`/`editable` do not exist yet. `test_grape_is_a_valid_tint_and_school_a_valid_taskgroup` fails because `"grape"`/`"School"` are not yet Literal members.

- [ ] **Step 3: Widen the `Tint` and `TaskGroup` Literals.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, replace line 22:
  ```python
  TaskGroup = Literal["Today", "Upcoming", "Someday"]
  ```
  with:
  ```python
  TaskGroup = Literal["Today", "Upcoming", "Someday", "School"]  # "School" = read-time Moodle-assignment projection (M6)
  ```
  and replace line 25:
  ```python
  Tint = Literal["green", "sky", "plum", "honey", "clay"]
  ```
  with:
  ```python
  Tint = Literal["green", "sky", "plum", "honey", "clay", "grape"]  # "grape" = read-time Moodle-deadline projection (M6)
  ```
  Leave `TaskPriority` (line 23) unchanged — it already contains `"med"`, the priority the Moodle-task projection uses.

- [ ] **Step 4: Widen `Task` — `id: int | str`, append `source`/`editable`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, replace the `Task` model body (lines 105-125):
  ```python
  class Task(BaseModel):
      id: int
      label: str
      done: bool
      group: TaskGroup
      deadline: date | None
      prio: TaskPriority
      list: str
      description: str
      subtasks: List[Subtask]
      labels: List[str]
      reminders: List[TaskReminderOut]
      files: List[TaskFile]
      recurrence: str | None
      recurrence_label: str | None  # derived: "Repeats weekly" / None
      # Derived display facts (review R6) — computed from deadline/done on read.
      due: str | None
      late: bool
      created_at: datetime
      updated_at: datetime
      completed_at: datetime | None
  ```
  with:
  ```python
  class Task(BaseModel):
      id: int | str  # int for local rows; "moodle:<source_id>" for read-time Moodle projections (M6)
      label: str
      done: bool
      group: TaskGroup
      deadline: date | None
      prio: TaskPriority
      list: str
      description: str
      subtasks: List[Subtask]
      labels: List[str]
      reminders: List[TaskReminderOut]
      files: List[TaskFile]
      recurrence: str | None
      recurrence_label: str | None  # derived: "Repeats weekly" / None
      # Derived display facts (review R6) — computed from deadline/done on read.
      due: str | None
      late: bool
      created_at: datetime
      updated_at: datetime
      completed_at: datetime | None
      # Read-time origin markers (M6). Real rows default to local/editable so
      # existing serializers that omit these keys validate unchanged; Moodle
      # projections set source="moodle"/editable=False (read-only in the UI).
      source: str = "local"
      editable: bool = True
  ```

- [ ] **Step 5: Widen `EventOccurrence` — `id: int | str`, append `source`/`editable`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, replace the `EventOccurrence` model body (lines 187-201):
  ```python
  class EventOccurrence(BaseModel):
      """One concrete occurrence — what GET /events returns. For a recurring
      series, `id` is the series row and `start`/`end` are this instance's
      times; single-occurrence deletes key on `start`."""

      id: int
      title: str
      start: datetime
      end: datetime
      tint: Tint
      location: str
      description: str
      recurring: bool
      recurrence_label: str | None
      at: str  # derived display clock, e.g. "9:00am"
  ```
  with:
  ```python
  class EventOccurrence(BaseModel):
      """One concrete occurrence — what GET /events returns. For a recurring
      series, `id` is the series row and `start`/`end` are this instance's
      times; single-occurrence deletes key on `start`."""

      id: int | str  # int for local rows; "moodle:<source_id>" for read-time Moodle projections (M6)
      title: str
      start: datetime
      end: datetime
      tint: Tint
      location: str
      description: str
      recurring: bool
      recurrence_label: str | None
      at: str  # derived display clock, e.g. "9:00am"
      # Read-time origin markers (M6). Real rows default to local/editable so
      # existing serializers that omit these keys validate unchanged; Moodle
      # projections set source="moodle"/editable=False (read-only in the UI).
      source: str = "local"
      editable: bool = True
  ```

- [ ] **Step 6: Run the targeted test and confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_schema_widening.py -q
  ```
  Expected: `5 passed`.

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: the prior baseline count + 5 new tests, `0 failed, 1 skipped`. This widening is purely additive — the `int | str` id union accepts every existing int id, `source`/`editable` default so existing calendar/tasks tests that build `EventOccurrence`/`Task` from `_occurrence_dict`/`_task_dict` (which do not yet emit those keys) validate unchanged, and the two new Literal members are unused by any existing row. Report "X tests passing" per the user's global convention.

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/schemas.py tests/test_moodle_schema_widening.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): widen EventOccurrence/Task for read-time Moodle projections

  Additive contract §H widening: id becomes int | str so projected rows can
  carry "moodle:<source_id>" ids, and source="local"/editable=True defaults are
  appended so existing _occurrence_dict/_task_dict output (which omits these
  keys) validates unchanged while Moodle projections mark themselves
  source="moodle"/editable=False. Tint gains "grape" and TaskGroup gains
  "School" for the deadline/assignment projections (Task 11). No table or
  migration change — the tasks/events tables are untouched.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 11: Read-time merge — `moodle_calendar_events` / `moodle_tasks` projectors + `events_between`/`list_tasks` merge

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_store.py`

**Interfaces:**
- Consumes: `store.moodle_deadlines(days_ahead=None) -> list[dict]` (Task 9; each dict carries `id, source_id, course_id, name, module_name, event_type, due_at, overdue, url, when` per contract §G — `due_at` is an aware-UTC `datetime`); `store.moodle_assignments(course_id=None) -> list[dict]` (Task 9; each dict carries `id, source_id, course_id, cmid, name, due_at, cutoff_at, grade_max, submission_status, grading_status, graded` — `due_at` is an aware-UTC `datetime` or `None`); `store.moodle_courses() -> list[dict]` (Task 9; each dict carries `id, source_id, shortname, fullname, ...` — used to resolve a deadline/assignment `course_id` to a course `shortname` for the display title); `store.upsert_moodle_deadline` / `store.upsert_moodle_assignment` / `store.upsert_moodle_course` (Task 9, used by the tests to seed rows); the `NormalizedDeadline` / `NormalizedAssignment` / `NormalizedCourse` dataclasses (`app.providers.base`, contract §B); the `clock` display helper (`app.display.clock`, already imported in `store.py` line 26); `task_due_display` (already imported, `store.py` line 32); `utcnow` (already imported, `store.py` line 50); `store.events_between(window_start, window_end) -> list[dict]` (existing, `store.py` lines 814-822, sorts `out` by `o["start"]` then returns); `store.list_tasks() -> list[dict]` (existing, `store.py` lines 455-461, returns a list comprehension over Task rows); `store.up_next(...)` (existing, `store.py` lines 824-839, built ON TOP of `events_between` — inherits the merge automatically).
- Produces: `store.moodle_calendar_events(self, window_start: datetime, window_end: datetime) -> list[dict]` (emits `_occurrence_dict`-shaped dicts for in-window Moodle deadlines); `store.moodle_tasks(self) -> list[dict]` (emits `_task_dict`-shaped dicts for Moodle assignments with a due date); the two-line merge in `events_between` and the one-line merge in `list_tasks` — consumed by the Calendar `GET /events` endpoint (`routers/calendar.py`), the Tasks `GET /` endpoint (`routers/tasks.py`), and the Home agenda via `up_next`. The int-path-id guard for edit/delete is a NEGATIVE contract (a `"moodle:<n>"` id can never be edited/deleted through the existing `int`-typed calendar/tasks mutation routes → FastAPI 422) verified by the router tests below.

- [ ] **Step 1: Write the failing store/merge tests.** These tests seed Moodle rows via the Task 9 upserts and assert the projections surface in `events_between` / `up_next` / `list_tasks`, that a no-Moodle-rows run leaves the existing outputs untouched, and that the string id 422s through the int-typed mutation routes. Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_store.py` (this file already exists from Task 9; add the imports it does not yet have at the top alongside the existing ones, then append the tests). The needed top-of-file imports:
  ```python
  from datetime import datetime, timedelta, timezone

  from app.providers.base import (
      NormalizedAssignment,
      NormalizedCourse,
      NormalizedDeadline,
  )
  from app.store import store
  ```
  (If any of these are already imported by the Task 9 tests in this file, do NOT duplicate — merge into the existing import lines.) Then append:
  ```python
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
      # A single real local event; NO moodle rows seeded.
      store.add_event(EventCreate(
          title="Standup",
          start=datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
      ))
      occs = store.events_between(
          datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
          datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc),
      )
      assert all(o["source"] == "local" for o in occs)
      assert all(o["editable"] is True for o in occs)
      assert [o["title"] for o in occs] == ["Standup"]


  def test_no_moodle_rows_leaves_list_tasks_unchanged():
      store.add_task(TaskCreate(label="Buy milk"))
      tasks = store.list_tasks()
      assert all(t["source"] == "local" for t in tasks)
      assert [t["label"] for t in tasks] == ["Buy milk"]


  def test_patch_to_moodle_task_id_returns_422(client):
      # The tasks PATCH route is typed /api/tasks/{task_id:int}; a "moodle:1"
      # path can never match, so the read-only projection is uneditable.
      res = client.patch("/api/tasks/moodle:1", json={"done": True})
      assert res.status_code == 422


  def test_delete_to_moodle_calendar_event_id_returns_422(client):
      res = client.delete("/api/calendar/events/moodle:1")
      assert res.status_code == 422
  ```
  Note the two new-in-this-step imports the appended tests reference — add them to the top of the file alongside the others (merge, do not duplicate):
  ```python
  from app.schemas import EventCreate, TaskCreate
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_store.py -q
  ```
  Expected failure: the new `test_moodle_deadline_*` / `test_moodle_assignment_*` tests fail with `KeyError: 'source'` (the merged output dicts have no `source` key because `events_between`/`list_tasks` do not yet append Moodle projections) or `AttributeError: 'Store' object has no attribute 'moodle_calendar_events'`. The two 422 router tests fail with `assert 404 == 422` or similar until confirmed — actually they should ALREADY pass (the routes are int-typed, so `moodle:1` 422s today); if a route instead 404s, note it, but the frozen contract §H states existing calendar/tasks mutation endpoints take `int` path ids and a string id yields FastAPI 422. Run them last; the store/merge tests are the ones driving the red.

- [ ] **Step 3: Implement the two read-time projectors.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, add both methods inside the `Store` class in the `# ---- moodle ----` section (created in Task 9), directly after the existing `moodle_assignments` read method. `moodle_calendar_events` projects in-window deadlines into the `_occurrence_dict` output shape; `moodle_tasks` projects due-dated assignments into the `_task_dict` output shape. Both resolve a `course_id` → course `shortname` via a one-pass dict built from `self.moodle_courses()`:
  ```python
      def moodle_calendar_events(
          self, window_start: datetime, window_end: datetime
      ) -> list[dict]:
          """Read-time projection (contract §H): Moodle deadlines whose due_at
          falls in [window_start, window_end) rendered as calendar occurrences
          (_occurrence_dict shape) tagged source='moodle'/editable=False. These
          are NOT rows in the events table — events_between appends them at read
          time so Home/Calendar show them read-only. tint='grape' and a
          synthetic 'moodle:<source_id>' id keep them visually + structurally
          distinct from local events (whose ids are ints)."""
          shortnames = {c["source_id"]: c["shortname"] for c in self.moodle_courses()}
          out: list[dict] = []
          for d in self.moodle_deadlines():
              start = d["due_at"]
              if start is None or not (window_start <= start < window_end):
                  continue
              end = start + timedelta(hours=1)
              short = shortnames.get(d["course_id"], "")
              title = f"{d['name']} · {short}" if short else d["name"]
              out.append({
                  "id": f"moodle:{d['source_id']}",
                  "title": title,
                  "start": start,
                  "end": end,
                  "tint": "grape",
                  "location": "",
                  "description": "",
                  "recurring": False,
                  "recurrence_label": None,
                  "at": clock(start),
                  "source": "moodle",
                  "editable": False,
              })
          return out

      def moodle_tasks(self) -> list[dict]:
          """Read-time projection (contract §H): Moodle assignments that carry a
          due date rendered as tasks (_task_dict shape) tagged
          source='moodle'/editable=False. done mirrors submission_status
          (submitted/reopened => done). group/list='School', prio='med'.
          due/late come from task_due_display so the UI's overdue styling
          matches local tasks. Appended by list_tasks at read time — NOT rows in
          the tasks table. The 'moodle:<source_id>' id can never be edited or
          deleted through the int-typed /api/tasks/{id} routes."""
          shortnames = {c["source_id"]: c["shortname"] for c in self.moodle_courses()}
          now = utcnow()
          out: list[dict] = []
          for a in self.moodle_assignments():
              due_at = a["due_at"]
              if due_at is None:
                  continue
              deadline = due_at.date()
              done = a["submission_status"] in {"submitted", "reopened"}
              due, late = task_due_display(deadline, done, None)
              short = shortnames.get(a["course_id"], "")
              label = f"{a['name']} · {short}" if short else a["name"]
              out.append({
                  "id": f"moodle:{a['source_id']}",
                  "label": label,
                  "done": done,
                  "group": "School",
                  "deadline": deadline,
                  "prio": "med",
                  "list": "School",
                  "description": "",
                  "subtasks": [],
                  "labels": [],
                  "reminders": [],
                  "files": [],
                  "recurrence": None,
                  "recurrence_label": None,
                  "due": due,
                  "late": late,
                  "created_at": now,
                  "updated_at": now,
                  "completed_at": None,
                  "source": "moodle",
                  "editable": False,
              })
          return out
  ```
  (`moodle_deadlines()` returns due_at-ascending dicts and `moodle_assignments()` returns all assignment dicts per Task 9's contract §G; both include the `source_id`/`course_id`/`due_at`/`submission_status` keys these projectors read.)

- [ ] **Step 4: Wire the merge into `events_between`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, replace the existing `events_between` body (lines 814-822):
  ```python
      def events_between(self, window_start: datetime, window_end: datetime) -> list[dict]:
          """Concrete occurrences in the window, recurring series expanded."""
          with self._session() as s:
              rows = s.scalars(select(Event).order_by(Event.start_at)).all()
          out: list[dict] = []
          for e in rows:
              out.extend(_event_occurrences(e, window_start, window_end))
          out.sort(key=lambda o: o["start"])
          return out
  ```
  with:
  ```python
      def events_between(self, window_start: datetime, window_end: datetime) -> list[dict]:
          """Concrete occurrences in the window, recurring series expanded.
          Read-time-merges in-window Moodle deadlines (contract §H) as read-only
          'grape' occurrences before the final sort, so Home/Calendar/up_next
          all show them without any events-table write."""
          with self._session() as s:
              rows = s.scalars(select(Event).order_by(Event.start_at)).all()
          out: list[dict] = []
          for e in rows:
              out.extend(_event_occurrences(e, window_start, window_end))
          out.extend(self.moodle_calendar_events(window_start, window_end))
          out.sort(key=lambda o: o["start"])
          return out
  ```

- [ ] **Step 5: Wire the merge into `list_tasks`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, replace the existing `list_tasks` body (lines 455-461):
  ```python
      def list_tasks(self) -> list[dict]:
          with self._session() as s:
              rows = s.scalars(select(Task).order_by(Task.id.desc())).all()
              by_task: dict[int, list[TaskReminder]] = {}
              for r in s.scalars(select(TaskReminder).order_by(TaskReminder.remind_at)):
                  by_task.setdefault(r.task_id, []).append(r)
              return [_task_dict(t, by_task.get(t.id, [])) for t in rows]
  ```
  with:
  ```python
      def list_tasks(self) -> list[dict]:
          with self._session() as s:
              rows = s.scalars(select(Task).order_by(Task.id.desc())).all()
              by_task: dict[int, list[TaskReminder]] = {}
              for r in s.scalars(select(TaskReminder).order_by(TaskReminder.remind_at)):
                  by_task.setdefault(r.task_id, []).append(r)
              local = [_task_dict(t, by_task.get(t.id, [])) for t in rows]
          # Read-time-merge Moodle assignments (contract §H) as read-only School
          # tasks — appended after local rows, NOT persisted to the tasks table.
          return local + self.moodle_tasks()
  ```
  (Note the projector call is OUTSIDE the `with self._session()` block — `moodle_tasks` opens its own sessions via `moodle_assignments`/`moodle_courses`, so it must not nest inside the open task session.)

- [ ] **Step 6: Run the targeted test and confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_store.py -q
  ```
  Expected: all tests in the file pass (the Task 9 store tests plus the 11 new merge/projection/guard tests added in Step 1).

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior baseline count + 11, `0 failed, 1 skipped`. The existing calendar tests (`test_calendar_*`) and tasks tests (`test_tasks_*`) stay green because with no Moodle rows seeded, `moodle_calendar_events`/`moodle_tasks` return `[]` and the merged outputs are byte-for-byte the pre-merge outputs (the `source`/`editable` keys default through the widened models from Task 10). Report "X tests passing" per the user's global convention.

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/store.py tests/test_moodle_store.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): read-time-merge Moodle deadlines into Calendar and assignments into Tasks

  Adds store.moodle_calendar_events (in-window deadlines → _occurrence_dict
  shape, tint="grape") and store.moodle_tasks (due-dated assignments →
  _task_dict shape, done mirrors submission_status, group/list="School"), both
  tagged id="moodle:<source_id>"/source="moodle"/editable=False per contract
  §H. events_between and list_tasks append these projections at read time (and
  up_next inherits the deadline merge for free); the tasks/events tables are
  never written. The synthetic string id can't reach the int-typed
  /api/tasks/{id} and /api/calendar/events/{id} mutation routes (FastAPI 422),
  so the projections are read-only with no new write guard.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 12: `moodle_sync.py` sync engine + `FakeMoodleProvider` + conftest seam + main lifespan

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/moodle_sync.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_sync.py`

**Interfaces:**
- Consumes: `app.providers.all_providers()` (existing registry accessor); `app.providers.base.AuthError` (existing base, `MoodleAuthError` subclasses it — contract §C); `app.store.store` with the Task-9 moodle methods `upsert_moodle_course`, `upsert_moodle_deadline`, `upsert_moodle_assignment`, `upsert_moodle_grade`, `upsert_moodle_announcement`, `upsert_moodle_notification`, plus `list_provider_accounts`, `get_provider_tokens`, `upsert_provider_account`, `set_provider_status`, `set_provider_synced` (all existing — contract §G); `settings.moodle_sync_enabled` / `settings.moodle_sync_seconds` (Task-1 settings, contract §A); the `MoodleSnapshot` bundle + `fetch_school_snapshot(since)` provider method (Task-2 contract §B); the `MoodleProvider` OAuth surface `set_tokens` / `refresh` (contract §C).
- Produces: `app.moodle_sync.configure(override="unset") -> None`; `app.moodle_sync._moodle_providers() -> list`; `app.moodle_sync._load_and_inject_tokens(provider, now) -> bool`; `app.moodle_sync._sync_provider(provider, now) -> int`; `app.moodle_sync.tick(now=None) -> int`; `app.moodle_sync.trigger() -> int` (async); `app.moodle_sync.run_loop() -> None` (async) — consumed by Task 13 (`POST /api/moodle/sync` calls `moodle_sync.tick()`) and Task 14 (`POST /api/moodle/connect` calls `moodle_sync.tick()` after storing the token). `tests.fakes.FakeMoodleProvider` — consumed by this task's `test_moodle_sync.py` and by Task 13/14 router tests.

This task's conftest edit, the new module, and the new fake MUST land in the SAME commit — per the slice-1 conftest hazard note: `no_external_services` in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py` configures every external-reaching module's fake-seam atomically. A module added without its conftest line lets that module's `run_loop`/`tick` silently reach the real registry/network in the full-suite run, because the autouse fixture doesn't know to neutralize it yet.

- [ ] **Step 1: Add `FakeMoodleProvider` to `tests/fakes.py`.**

  This is test infra the failing sync tests below import. In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`, the provider fakes at the top of the file import from `app.providers.base`. The existing `FakeEmailProvider` import line (around `fakes.py:169`) reads:

  ```python
  from app.providers.base import NormalizedEmail
  ```

  Extend it to also import the Moodle snapshot type (added in Task 2, contract §B):

  ```python
  from app.providers.base import MoodleSnapshot, NormalizedEmail
  ```

  Then append `FakeMoodleProvider` to the end of `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py` (after `FakeEmailProvider`, which ends around `fakes.py:329`):

  ```python
  class FakeMoodleProvider:
      """Scriptable MoodleProvider stand-in (name='moodle') — no network.

      Installed via ``providers.configure([FakeMoodleProvider(...)])``. Satisfies the
      MoodleProvider protocol (contract §B/§C) so the shared oauth router and
      moodle_sync accept it. Its distinguishing method is fetch_school_snapshot —
      moodle_sync selects providers by hasattr on it, exactly as email_sync selects
      by hasattr(p, 'fetch_messages'). Records every OAuth call so router tests can
      assert exchange/refresh/revoke ran; raise_auth drives the needs_reauth path.
      """

      name = "moodle"

      def __init__(
          self,
          *,
          tokens: Tokens | None = None,
          snapshot: MoodleSnapshot | None = None,
          site_info: dict | None = None,
          raise_auth: bool = False,
      ) -> None:
          self.tokens = tokens or Tokens(
              access_token="m-wstoken", refresh_token=None, expires_at=None,
              scopes="", provider_user_id="42",
          )
          self.snapshot = snapshot or MoodleSnapshot()
          self.site_info = site_info or {
              "userid": 42, "sitename": "WolfWare", "release": "5.2",
              "functions": [],
          }
          self.raise_auth = raise_auth
          self.exchanged: list[str] = []
          self.refreshed: list[Tokens] = []
          self.revoked: list[Tokens] = []
          self.injected: list[Tokens | None] = []
          self.fetched_since: list = []
          self.site_info_calls: list[str] = []

      # ---- OAuthProvider ----
      def set_tokens(self, tokens):
          self.injected.append(tokens)

      def authorize_url(self, state: str) -> str:
          return (
              "https://moodle-courses2527.wolfware.ncsu.edu/admin/tool/mobile/launch.php"
              f"?service=moodle_mobile_app&state={state}"
          )

      def exchange_code(self, code: str) -> Tokens:
          self.exchanged.append(code)
          return self.tokens

      def refresh(self, tokens: Tokens) -> Tokens:
          # Moodle has no refresh endpoint — passthrough (contract §C).
          self.refreshed.append(tokens)
          return tokens

      def revoke(self, tokens: Tokens) -> None:
          self.revoked.append(tokens)

      def success_redirect(self) -> str:
          return "/?screen=school&connected=moodle"

      def on_connected(self) -> None:
          from app import moodle_sync

          moodle_sync.tick()

      def on_disconnect(self) -> None:
          from app.store import store

          store.delete_moodle_data(self.name)

      # ---- MoodleProvider ----
      def get_site_info(self, token: str) -> dict:
          self.site_info_calls.append(token)
          return self.site_info

      def fetch_school_snapshot(self, since):
          from app.providers.moodle import MoodleAuthError

          if self.raise_auth:
              raise MoodleAuthError("moodle invalidtoken")
          self.fetched_since.append(since)
          return self.snapshot
  ```

  Note: `Tokens`, `NormalizedSnapshot`, `NormalizedWorkout` are already imported at the top of the provider-fakes section (`fakes.py:89`); `Tokens` is what `FakeMoodleProvider` uses. `refresh` returns its argument unchanged (Moodle is a passthrough — there is no rotation to persist, matching the `_load_and_inject_tokens` note below). `on_connected` kicks `moodle_sync.tick()`; `on_disconnect` calls `store.delete_moodle_data` (the Task-9 §G disconnect hook). `fetch_school_snapshot` raises `MoodleAuthError` (a subclass of `AuthError`, contract §C) when `raise_auth` is set — this drives the `needs_reauth` flip test.

- [ ] **Step 2: Write the failing sync tests.**

  Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_sync.py`:

  ```python
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
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_sync.py -q`
  Expected: `ModuleNotFoundError: No module named 'app.moodle_sync'` (collection error — the module doesn't exist yet).

- [ ] **Step 3: Implement `app/moodle_sync.py` as a near-verbatim clone of `email_sync.py`.**

  Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/moodle_sync.py`:

  ```python
  """Moodle sync engine (M6) — a background tick + on-demand trigger.

  A near-clone of app/email_sync.py: a plain asyncio loop (started from the app
  lifespan, guarded by settings.moodle_sync_enabled) wakes every
  settings.moodle_sync_seconds, and for each connected Moodle provider fetches a
  MoodleSnapshot since its cursor and upserts every course / deadline /
  assignment / grade / announcement / notification into the moodle_* tables,
  then advances the cursor.

  Moodle providers are the registry entries that implement fetch_school_snapshot
  (i.e. MoodleProvider). The email_sync hasattr(p, 'fetch_messages') filter is
  the model — a fitness pull provider and GoogleProvider both lack
  fetch_school_snapshot, so they are skipped here, exactly as MoodleProvider (no
  fetch_messages) is skipped by email_sync.

  Reads never depend on a live Moodle call — every /api/moodle/* GET is served
  from the DB; only connect (token validate) and this sync reach Moodle. A
  failed sync just logs and retries next tick; the tick NEVER crashes. Auth
  failures (MoodleAuthError, a subclass of AuthError) flip the account to
  needs_reauth. Test seam: configure(fake) installs an object with a .tick()
  that tick() delegates to; configure(None)/"unset" run the real pass (matching
  email_sync). Providers are swapped via providers.configure(...).
  """
  from __future__ import annotations

  import asyncio
  import logging
  from datetime import datetime, timedelta, timezone

  from . import providers
  from .config import settings
  from .providers.base import AuthError
  from .store import store

  logger = logging.getLogger("scuffed_os.moodle_sync")

  _override: object | None | str = "unset"


  def configure(override: object | None | str = "unset") -> None:
      """Test seam for mocking tick(); install a fake with .tick() to delegate to
      it. None or "unset" run the real tick. Does NOT gate run_loop (the lifespan,
      gated by settings.moodle_sync_enabled, controls that). The provider registry
      is swapped separately via providers.configure(...)."""
      global _override
      _override = override


  def _utcnow() -> datetime:
      return datetime.now(timezone.utc)


  def _moodle_providers() -> list:
      """Registry entries that implement fetch_school_snapshot (Moodle domain)."""
      return [p for p in providers.all_providers() if hasattr(p, "fetch_school_snapshot")]


  def _load_and_inject_tokens(provider, now: datetime) -> bool:
      """Load stored tokens, refresh if within the skew of expiry (persist the
      rotation), and inject them so the authed Moodle calls carry the wstoken.
      Returns False if no tokens are stored. Raises AuthError on a refresh failure
      so the caller flips needs_reauth. Byte-identical to
      email_sync._load_and_inject_tokens — for Moodle the refresh is a passthrough
      (no refresh endpoint; tokens.expires_at is always None), so the refresh
      branch never fires and no rotation is actually persisted."""
      tokens = store.get_provider_tokens(provider.name)
      if tokens is None:
          return False
      refresh = getattr(provider, "refresh", None)
      if (
          tokens.expires_at is not None
          and refresh is not None
          and now >= tokens.expires_at - timedelta(seconds=60)
      ):
          tokens = refresh(tokens)                              # may raise AuthError
          store.upsert_provider_account(provider.name, tokens)  # persist rotation
      set_tokens = getattr(provider, "set_tokens", None)
      if set_tokens is not None:
          set_tokens(tokens)
      return True


  def _sync_provider(provider, now: datetime) -> int:
      """One Moodle provider's pass. Returns records upserted. Raises AuthError on
      an auth/refresh failure so the caller flips needs_reauth; other errors
      propagate so the caller can log-and-continue."""
      acct = next(
          (a for a in store.list_provider_accounts() if a["provider"] == provider.name),
          None,
      )
      if acct is None or acct["status"] != "connected":
          return 0
      if not _load_and_inject_tokens(provider, now):
          return 0

      since = acct["last_sync_at"]  # None on a fresh account -> full backfill
      snap = provider.fetch_school_snapshot(since)
      count = 0
      for course in snap.courses:
          store.upsert_moodle_course(course)
          count += 1
      for deadline in snap.deadlines:
          store.upsert_moodle_deadline(deadline)
          count += 1
      for assignment in snap.assignments:
          store.upsert_moodle_assignment(assignment)
          count += 1
      for grade in snap.grades:
          store.upsert_moodle_grade(grade)
          count += 1
      for announcement in snap.announcements:
          store.upsert_moodle_announcement(announcement)
          count += 1
      for notification in snap.notifications:
          store.upsert_moodle_notification(notification)
          count += 1
      store.set_provider_synced(provider.name, now)
      return count


  def tick(now: datetime | None = None) -> int:
      """One sync pass over every connected Moodle provider. Returns records
      upserted. Safe to call any time — per-account errors are caught and logged
      so the tick never crashes; auth failures flip the account to needs_reauth.
      Returns 0 when no database is configured (RuntimeError caught).

      Test seam: if configure() installed an object with a .tick(), that is called
      instead of the real pass.
      """
      if _override not in ("unset", None) and hasattr(_override, "tick"):
          return _override.tick(now)  # type: ignore[union-attr]
      now = now or _utcnow()
      try:
          provider_list = _moodle_providers()
      except RuntimeError:  # no DATABASE_URL behind the registry — nothing to do
          return 0
      total = 0
      for provider in provider_list:
          try:
              total += _sync_provider(provider, now)
          except AuthError:
              logger.warning("%s needs re-auth; flipping status", provider.name)
              try:
                  store.set_provider_status(provider.name, "needs_reauth")
              except Exception:
                  logger.exception("could not flip %s to needs_reauth", provider.name)
          except RuntimeError as exc:
              if "DATABASE_URL" in str(exc):
                  return total
              logger.exception("moodle sync failed for %s", provider.name)
          except Exception:
              logger.exception("moodle sync failed for %s", provider.name)
      return total


  async def trigger() -> int:
      """Run one sync pass off the event loop and return its count. Awaited by the
      OAuth/connect flow (via on_connected) and by POST /api/moodle/sync. Errors are
      already swallowed inside tick, so this never raises for provider problems."""
      return await asyncio.to_thread(tick)


  async def run_loop() -> None:
      """The lifespan background task; ticks forever until cancelled."""
      logger.info("moodle sync loop started (every %ss)", settings.moodle_sync_seconds)
      while True:
          try:
              synced = await asyncio.to_thread(tick)
              if synced:
                  logger.info("synced %d moodle record(s)", synced)
          except Exception:
              logger.exception("moodle sync tick failed")
          await asyncio.sleep(settings.moodle_sync_seconds)
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_sync.py -q`
  Expected: `6 passed`.

- [ ] **Step 4: Wire the conftest seam (same commit as the module).**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`, the current `no_external_services` import line reads (after Task 12 of the email plan added `email_draft`; if that branch has not merged, the line will still contain `email_sync, email_triage, ...` — insert `moodle_sync` in alphabetical position after `memory_engine` regardless):

  ```python
  from app import email_sync, email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
  ```

  Edit it to add `moodle_sync`:

  ```python
  from app import email_sync, email_triage, fitness_sync, food_db, llm, memory_engine, moodle_sync, providers, reminders
  ```

  The current fixture body reads:

  ```python
  @pytest.fixture(autouse=True)
  def no_external_services():
      """Tests never reach the Claude API, OpenAI, Mem0, USDA, osascript, or
      WHOOP — install a fake explicitly (each module's configure seam) when needed."""
      llm.configure(None)
      memory_engine.configure(None)
      food_db.configure(None)
      reminders.configure(None)
      providers.configure([])
      fitness_sync.configure(None)
      email_triage.configure(None)
      email_sync.configure(None)
      yield
      llm.configure()
      memory_engine.configure("unset")
      food_db.configure("unset")
      reminders.configure("unset")
      providers.configure("unset")
      fitness_sync.configure("unset")
      email_triage.configure("unset")
      email_sync.configure("unset")
  ```

  Add `moodle_sync.configure(None)` immediately after the `email_sync.configure(None)` line, and `moodle_sync.configure("unset")` immediately after the `email_sync.configure("unset")` line, so the fixture body becomes:

  ```python
  @pytest.fixture(autouse=True)
  def no_external_services():
      """Tests never reach the Claude API, OpenAI, Mem0, USDA, osascript, or
      WHOOP — install a fake explicitly (each module's configure seam) when needed."""
      llm.configure(None)
      memory_engine.configure(None)
      food_db.configure(None)
      reminders.configure(None)
      providers.configure([])
      fitness_sync.configure(None)
      email_triage.configure(None)
      email_sync.configure(None)
      moodle_sync.configure(None)
      yield
      llm.configure()
      memory_engine.configure("unset")
      food_db.configure("unset")
      reminders.configure("unset")
      providers.configure("unset")
      fitness_sync.configure("unset")
      email_triage.configure("unset")
      email_sync.configure("unset")
      moodle_sync.configure("unset")
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_sync.py -q`
  Expected: still `6 passed` (the fixture brackets each test with `configure(None)`/`configure("unset")`; each test's own explicit `providers.configure([...])` overrides the empty registry for its body — matching how `test_email_sync.py` behaves against the same fixture).

- [ ] **Step 5: Wire the `main.py` lifespan to start `moodle_sync.run_loop()`.**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`, add `moodle_sync` to the app imports. The existing sync-module import (near the top, the same line that imports `email_sync`, `fitness_sync`, `reminders`) reads approximately:

  ```python
  from . import email_sync, fitness_sync, reminders
  ```

  Add `moodle_sync` to it (keep whatever other names are on that line; insert alphabetically):

  ```python
  from . import email_sync, fitness_sync, moodle_sync, reminders
  ```

  The current `lifespan()` reads:

  ```python
  @contextlib.asynccontextmanager
  async def lifespan(_: FastAPI):
      """Start the reminder tick and the fitness-sync loop alongside the server;
      stop them on shutdown."""
      reminder_task: asyncio.Task | None = None
      fitness_task: asyncio.Task | None = None
      email_task: asyncio.Task | None = None
      if settings.reminders_enabled:
          reminder_task = asyncio.create_task(reminders.run_loop())
      if settings.fitness_sync_enabled:
          fitness_task = asyncio.create_task(fitness_sync.run_loop())
      if settings.email_sync_enabled:
          email_task = asyncio.create_task(email_sync.run_loop())
      yield
      for task in (reminder_task, fitness_task, email_task):
          if task is not None:
              task.cancel()
              with contextlib.suppress(asyncio.CancelledError):
                  await task
  ```

  Replace it with (adds `moodle_task` alongside `email_task`, gated by `settings.moodle_sync_enabled`, cancelled on shutdown):

  ```python
  @contextlib.asynccontextmanager
  async def lifespan(_: FastAPI):
      """Start the reminder tick and the fitness/email/moodle-sync loops alongside
      the server; stop them on shutdown."""
      reminder_task: asyncio.Task | None = None
      fitness_task: asyncio.Task | None = None
      email_task: asyncio.Task | None = None
      moodle_task: asyncio.Task | None = None
      if settings.reminders_enabled:
          reminder_task = asyncio.create_task(reminders.run_loop())
      if settings.fitness_sync_enabled:
          fitness_task = asyncio.create_task(fitness_sync.run_loop())
      if settings.email_sync_enabled:
          email_task = asyncio.create_task(email_sync.run_loop())
      if settings.moodle_sync_enabled:
          moodle_task = asyncio.create_task(moodle_sync.run_loop())
      yield
      for task in (reminder_task, fitness_task, email_task, moodle_task):
          if task is not None:
              task.cancel()
              with contextlib.suppress(asyncio.CancelledError):
                  await task
  ```

  This is a lifespan-only change (no router registration — the `/api/moodle/*` router is mounted in Task 13). It carries no direct unit test; the guarantee is the full suite still importing/constructing `app` cleanly, which the next step exercises.

- [ ] **Step 6: Run the full suite and commit.**

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q`
  Expected: the running baseline carried in from Task 11 + 6 new `test_moodle_sync.py` tests, `0 failed`, `1 skipped` (the Postgres-only migration drift test). This is a relative estimate — report the exact printed count as the actual gate, e.g. "X tests passing" per the user's global convention.

  ```bash
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/moodle_sync.py app/main.py tests/conftest.py tests/fakes.py tests/test_moodle_sync.py
  ```
  ```bash
  git commit -m "$(cat <<'EOF'
  feat(school): add moodle_sync tick loop + FakeMoodleProvider + lifespan wiring

  Near-verbatim clone of email_sync (contract §I): _moodle_providers selects
  registry entries by hasattr(fetch_school_snapshot); tick fetches a
  MoodleSnapshot and upserts every course/deadline/assignment/grade/
  announcement/notification via the store's moodle upserts, advances the
  cursor, and NEVER crashes — per-provider try/except flips MoodleAuthError
  accounts to needs_reauth and short-circuits to a no-op when DATABASE_URL is
  unset. main.py lifespan starts run_loop() behind settings.moodle_sync_enabled
  alongside the email task; conftest wires the fake seam atomically with the
  module (slice-1 conftest hazard note); FakeMoodleProvider lands in fakes.py.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 13: Moodle read schemas + `routers/moodle.py` (five GET reads + POST /sync) + registration

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_api.py`

**Interfaces:**
- Consumes: `store.moodle_courses() -> list[dict]`, `store.moodle_deadlines(days_ahead: int | None = None) -> list[dict]`, `store.moodle_grades(course_id: str | None = None) -> list[dict]`, `store.moodle_announcements(course_id: str | None = None) -> list[dict]`, `store.moodle_notifications() -> list[dict]` (Task 9, contract §G — every read served from the DB, never a live Moodle call); `moodle_sync.tick() -> int` and `moodle_sync.configure(override)` (Task 12, contract §I); `providers.all_providers()` (existing, `app/providers/__init__.py`) — the `/sync` provider list is derived by `hasattr(p, "fetch_school_snapshot")` (contract §I `_moodle_providers` duck-type, mirroring email's `hasattr(p, "fetch_messages")`).
- Produces: `app.schemas.CourseOut`, `DeadlineOut`, `GradeOut`, `AnnouncementOut`, `NotificationOut`, `MoodleConnect` (contract §J — `MoodleConnect` is consumed by Task 14's connect endpoint); `app.routers.moodle.router` (`APIRouter(prefix="/api/moodle")`) with the five GET reads + `POST /sync`, registered in `main.py` — consumed by Task 14 (connect/disconnect endpoints appended to the same router) and Task 16 (frontend `api.js` helpers).

- [ ] **Step 1: Add the six Moodle schemas to `schemas.py`.** These sit in a new `# ---- Moodle schemas (M6 School) ----` block at the very end of `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py` (after the Email schemas block, which currently ends the file). `datetime` and `BaseModel` are already imported at the top of the file (used by `EmailOut`/`ProviderStatus`); do NOT re-import. Append:
  ```python
  # ---- Moodle schemas (M6 School) ---------------------------------------------
  # Read models for the /api/moodle/* GET endpoints. Every field is served from
  # the moodle_* tables (never a live Moodle call). Tokens/scopes are NEVER in
  # any of these shapes — connection state travels via /api/oauth/status only.
  class CourseOut(BaseModel):
      id: int
      source_id: str
      shortname: str
      fullname: str
      progress: float | None
      start_at: datetime | None
      end_at: datetime | None
      last_access_at: datetime | None
      hidden: bool


  class DeadlineOut(BaseModel):
      id: int
      source_id: str
      course_id: str
      name: str
      module_name: str
      event_type: str
      due_at: datetime
      overdue: bool
      url: str
      when: str  # derived display, e.g. "Fri 3:00pm" / "Tomorrow"


  class GradeOut(BaseModel):
      id: int
      source_id: str
      course_id: str
      item_name: str
      item_type: str
      grade_formatted: str
      grade_raw: float | None
      grade_min: float | None
      grade_max: float | None
      graded_at: datetime | None


  class AnnouncementOut(BaseModel):
      id: int
      source_id: str
      course_id: str
      forum_id: str
      subject: str
      author: str
      created_at: datetime
      summary_html: str
      url: str


  class NotificationOut(BaseModel):
      id: int
      source_id: str
      subject: str
      full_message: str
      context_url: str
      created_at: datetime | None
      read: bool


  # POST /api/moodle/connect body — the pasted wstoken (bare 32-hex or a
  # launch-redirect URL) plus the optional passport used to verify the launch
  # redirect's md5 prefix (see parse_pasted_token, contract §D).
  class MoodleConnect(BaseModel):
      token: str
      passport: str | None = None
  ```

- [ ] **Step 2: Write the failing API tests.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_api.py`. This file defines its OWN lightweight `FakeMoodleProvider` (only the surface the router touches: `name`, the `fetch_school_snapshot` duck-type marker) and a `FakeMoodleSync` seam, mirroring the split in `test_email_api.py` (which has its own slim `FakeEmailProvider` + `FakeEmailSync` distinct from `fakes.py`). The `_course`/`_deadline`/etc. builders return the §B `Normalized*` dataclasses so the store upserts real rows.
  ```python
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
  ```

- [ ] **Step 3: Run the tests — expect failure (no router module yet).**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_api.py -q
  ```
  Expected failure: collection error `ModuleNotFoundError: No module named 'app.routers.moodle'` — `test_moodle_api.py` does not import the router directly, but the `/api/moodle/*` routes are unregistered, so once the file collects, every request returns `404 Not Found` and the assertions fail (e.g. `test_courses_read_returns_store_rows` fails calling `.json()` on a 404 body / getting `{"detail":"Not Found"}`). The router module + its `main.py` registration land in Steps 4–5.

- [ ] **Step 4: Create `routers/moodle.py` with the five reads + `/sync`.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/moodle.py`. This mirrors `routers/email.py`'s shape exactly: an `APIRouter` with a domain prefix, reads served straight from the store with `response_model`, and a `POST /sync` that delegates to the sync-module `tick()` and lists providers by the domain duck-type. (Task 14 appends the `connect`/`_status_dict` code to this same file — leave room but write only the reads + sync now.)
  ```python
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
  ```

- [ ] **Step 5: Register `moodle.router` in `main.py`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`, add `moodle` to the routers import and register the router at the end of the `include_router` block (after `email.router`, currently the last line of that block). First extend the router import line — the current block imports the routers as a group; add `moodle` alongside `email`:
  ```python
  from .routers import (
      assistant,
      calendar,
      email,
      fitness,
      habits,
      memory,
      moodle,
      nutrition,
      oauth,
      tasks,
  )
  ```
  (Match the existing import style in `main.py` — if the routers are imported on a single `from .routers import assistant, tasks, ...` line rather than the parenthesized multi-line form above, add `moodle` to that line in alphabetical position instead; the goal is `moodle` importable, not a specific line shape.) Then add the registration after the `app.include_router(email.router)` line:
  ```python
  app.include_router(email.router)
  app.include_router(moodle.router)
  ```

- [ ] **Step 6: Run the targeted tests — expect pass.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_api.py -q
  ```
  Expected: all 7 tests pass. The reads return store rows; `test_sync_triggers_moodle_sync_and_lists_moodle_providers` asserts `{"synced": 5, "providers": ["moodle"]}` and `fake_sync.calls == 1` (the `FakeMoodleSync` seam is installed via `moodle_sync.configure`, and `FakeMoodleProvider` is duck-typed as Moodle-shaped by its `fetch_school_snapshot`).

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: baseline-from-Task-12 count + 7 new tests, `0 failed`. Report the exact "X passed, Y skipped" count as "X tests passing" (user CLAUDE.md rule).

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/schemas.py app/routers/moodle.py app/main.py tests/test_moodle_api.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): Moodle read schemas + /api/moodle router (reads + sync)

  Six read schemas (CourseOut/DeadlineOut/GradeOut/AnnouncementOut/
  NotificationOut/MoodleConnect, contract §J) and a new /api/moodle router
  (contract §J): five GET reads served straight from the moodle_* tables (never
  a live Moodle call) plus POST /sync delegating to moodle_sync.tick() and
  listing providers by the fetch_school_snapshot duck-type — the exact shape of
  the email router. Registered in main.py.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 14: `POST /api/moodle/connect` (token paste → validate → store → kick sync) + disconnect data delete

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/moodle.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_api.py`

**Interfaces:**
- Consumes: `parse_pasted_token(pasted: str, *, passport: str | None = None, wwwroot: str | None = None) -> str` raising `MoodleError` on an unrecognized token (Task 4, contract §D); `MoodleProvider.get_site_info(token: str) -> dict` returning `{"userid": int, "sitename": str, "release": str, "functions": [str, ...]}` and raising `MoodleError`/`MoodleAuthError` on a bad token (Task 4, contract §E); `MoodleError`/`MoodleAuthError` (`app/providers/moodle.py`, contract §C); `providers.get(name) -> OAuthProvider | None` (existing); `settings.moodle_base_url` (Task 1, contract §A); `store.upsert_provider_account(provider: str, tokens: Tokens) -> dict` (existing); `Tokens` (`app/providers/base.py`, fields `access_token, refresh_token, expires_at, scopes="", provider_user_id=None, meta={}`); `moodle_sync.tick() -> int` (Task 12); `store.list_provider_accounts()` (existing, backs `_status_dict`); `store.delete_moodle_data(source: str) -> bool` (Task 9, contract §G — invoked via the shared oauth-disconnect `on_disconnect` hook); `routers.oauth._status_dict` (existing, `oauth.py`, returns `{"connected": bool, "providers": [...]}`); `OAuthStatus` schema (existing).
- Produces: route `POST /api/moodle/connect` (`MoodleConnect -> OAuthStatus`) that validates the pasted token, persists it as the `moodle` provider account, kicks a sync, and returns the shared OAuth status — consumed by Task 16's frontend `api.moodleConnect(...)` and the SchoolScreen connect card. Disconnect + data-delete flow through the EXISTING shared `POST /api/oauth/disconnect/moodle` (no new route) via the provider's `on_disconnect -> store.delete_moodle_data` hook.

- [ ] **Step 1: Write the failing connect/disconnect tests.** Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_api.py`. First extend the top-of-file imports — add `Tokens` and the Moodle provider errors alongside the existing imports:
  ```python
  from app.providers.base import Tokens
  from app.providers.moodle import MoodleAuthError
  ```
  (Add these two lines to the existing import block at the top of the file; `Tokens` comes from `app.providers.base`, `MoodleAuthError` from `app.providers.moodle`.) Next, upgrade the slim `FakeMoodleProvider` so it can drive connect: give it a scripted `get_site_info` (return value or a raised error), an `on_disconnect` that deletes Moodle data (so the shared disconnect test exercises the real hook), and the OAuth-plumbing no-ops the shared router calls. Replace the `FakeMoodleProvider` class from Task 13 Step 2 with:
  ```python
  class FakeMoodleProvider:
      """Slim MoodleProvider stand-in for the router tests. Scripts
      get_site_info (the connect-time validation) and mirrors the real
      on_disconnect -> store.delete_moodle_data hook so the shared
      /api/oauth/disconnect/moodle path deletes Moodle rows for real."""

      name = "moodle"

      def __init__(self, *, site_info=None, raise_auth=False):
          self._site_info = site_info or {
              "userid": 501, "sitename": "WolfWare", "release": "5.2",
              "functions": ["core_enrol_get_users_courses"],
          }
          self._raise_auth = raise_auth
          self.injected = []

      def fetch_school_snapshot(self, since):  # marks this as a Moodle provider
          return None

      def get_site_info(self, token: str) -> dict:
          if self._raise_auth:
              raise MoodleAuthError("invalidtoken")
          return dict(self._site_info)

      # ---- OAuth plumbing the shared oauth router calls on disconnect ----
      def set_tokens(self, tokens):
          self.injected.append(tokens)

      def revoke(self, tokens) -> None:
          pass

      def on_disconnect(self) -> None:
          store.delete_moodle_data(self.name)
  ```
  Then append the connect/disconnect tests:
  ```python
  def test_connect_validates_token_persists_account_and_kicks_sync(client):
      fake_sync = FakeMoodleSync(count=3)
      moodle_sync.configure(fake_sync)
      providers.configure([FakeMoodleProvider(site_info={
          "userid": 501, "sitename": "WolfWare", "release": "5.2",
          "functions": ["core_enrol_get_users_courses", "gradereport_user_get_grade_items"],
      })])

      res = client.post("/api/moodle/connect",
                        json={"token": "a" * 32})

      assert res.status_code == 200
      body = res.json()
      # Shared OAuth status shape: connected=True with a moodle provider row.
      assert body["connected"] is True
      moodle = next(p for p in body["providers"] if p["provider"] == "moodle")
      assert moodle["status"] == "connected"
      assert moodle["provider_user_id"] == "501"
      # Connect kicked exactly one sync.
      assert fake_sync.calls == 1


  def test_connect_status_never_serializes_tokens_or_scopes(client):
      moodle_sync.configure(FakeMoodleSync())
      providers.configure([FakeMoodleProvider()])

      body = client.post("/api/moodle/connect", json={"token": "a" * 32}).json()
      moodle = next(p for p in body["providers"] if p["provider"] == "moodle")

      # The wstoken lives only in provider_accounts.access_token, server-side.
      assert "access_token" not in moodle
      assert "wstoken" not in moodle
      assert "scopes" not in moodle
      assert "meta" not in moodle
      # And it is genuinely connected per the shared status endpoint too.
      status = client.get("/api/oauth/status").json()
      assert any(p["provider"] == "moodle" and p["status"] == "connected"
                 for p in status["providers"])


  def test_connect_invalid_token_returns_502_and_persists_nothing(client):
      moodle_sync.configure(FakeMoodleSync())
      providers.configure([FakeMoodleProvider(raise_auth=True)])

      res = client.post("/api/moodle/connect", json={"token": "bad-token"})

      assert res.status_code == 502
      assert res.json()["detail"] == "Moodle rejected the token"
      # No account row was written.
      assert all(p["provider"] != "moodle"
                 for p in store.list_provider_accounts())


  def test_disconnect_moodle_deletes_synced_data_via_shared_router(client):
      moodle_sync.configure(FakeMoodleSync())
      providers.configure([FakeMoodleProvider()])
      # Connect, then seed a synced row.
      client.post("/api/moodle/connect", json={"token": "a" * 32})
      store.upsert_moodle_course(_course("72", shortname="CSC116"))
      assert store.moodle_courses()  # non-empty before disconnect

      res = client.post("/api/oauth/disconnect/moodle")

      assert res.status_code == 200
      # on_disconnect -> delete_moodle_data cleared the synced rows.
      assert store.moodle_courses() == []
      # And the moodle account is gone from status.
      assert all(p["provider"] != "moodle"
                 for p in res.json()["providers"])
  ```

- [ ] **Step 2: Run the tests — expect failure (no `/connect` route yet).**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_api.py -q
  ```
  Expected failure: the four new tests fail — `POST /api/moodle/connect` is undeclared so FastAPI returns `404 Not Found`, e.g. `test_connect_validates_token_persists_account_and_kicks_sync` fails asserting `res.status_code == 200` (got 404) and `fake_sync.calls == 1` (got 0). `test_disconnect_moodle_deletes_synced_data_via_shared_router` fails because the connect precondition 404s (no rows are ever seeded/deleted). The Task 13 tests still pass. The connect route lands in Step 3.

- [ ] **Step 3: Implement `POST /api/moodle/connect` in `routers/moodle.py`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/moodle.py`, extend the imports and add the connect endpoint. First widen the existing imports (add `HTTPException` to the fastapi line, `settings`, `MoodleConnect` + `OAuthStatus` to schemas, `Tokens`, the Moodle errors + `parse_pasted_token`, and reuse `routers.oauth._status_dict`):
  ```python
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
  ```
  Then add the connect endpoint immediately after the `router = APIRouter(...)` / `logger = ...` lines (before the `courses` read, so the connect POST is grouped with the router construction — route order does not matter here since `/connect` is a distinct literal path and a POST):
  ```python
  @router.post("/connect", response_model=OAuthStatus)
  def connect(payload: MoodleConnect) -> dict:
      """Connect Moodle via a pasted wstoken (WolfWare is Shibboleth SSO, so
      there is no OAuth code exchange — the token is pasted, not redirected).
      Parse the token (bare 32-hex or a launch-redirect URL), validate it with a
      live get_site_info call (a bad token -> 502, nothing persisted), persist it
      as the `moodle` provider account (server-side only — the wstoken never goes
      back to the client), kick one sync, and return the shared OAuth status."""
      wstoken = parse_pasted_token(
          payload.token, passport=payload.passport, wwwroot=settings.moodle_base_url,
      )
      provider = providers.get("moodle")
      if provider is None:
          raise HTTPException(status_code=502, detail="Moodle rejected the token")
      try:
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
  ```
  Note: `MoodleAuthError` subclasses `AuthError` (not `MoodleError`), so both must be named in the `except` tuple — either a hard-invalid token (`MoodleError("unrecognized token")` from `parse_pasted_token` for a genuinely malformed paste that still parses to a call) or an auth-rejected token (`MoodleAuthError` from `get_site_info`'s `invalidtoken`/`accessexception`) maps to the same 502 "Moodle rejected the token". `parse_pasted_token` raising `MoodleError` for an unrecognized paste propagates as a 502 as well since it is not caught — acceptable for slice-1 (the frozen contract §J maps connect validation failure to 502); the FakeMoodleProvider tests drive the `get_site_info` path, which is the common case.

- [ ] **Step 4: Run the targeted tests — expect pass.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_api.py -q
  ```
  Expected: all tests in the file pass (the 7 from Task 13 + 4 new). The valid-token test connects and kicks a sync; the status shape carries no tokens/scopes; the invalid-token test 502s and persists nothing; the shared `POST /api/oauth/disconnect/moodle` deletes the synced Moodle rows via the provider's `on_disconnect -> delete_moodle_data` hook and drops the account from status.

- [ ] **Step 5: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: baseline-from-Task-13 count + 4 new tests, `0 failed`. Report the exact "X passed, Y skipped" count as "X tests passing".

- [ ] **Step 6: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/routers/moodle.py tests/test_moodle_api.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): POST /api/moodle/connect — token paste-back → validate → sync

  Moodle uses a static wstoken (Shibboleth SSO, no OAuth code exchange), so
  connect is a thin token-paste endpoint (contract §J): parse the pasted token,
  validate it with a live get_site_info (bad token -> 502, nothing persisted),
  store it server-side as the moodle provider account (never serialized back to
  the client), kick one sync, and return the shared OAuth status. Disconnect +
  data delete flow through the existing shared /api/oauth/disconnect/moodle via
  the provider's on_disconnect -> store.delete_moodle_data hook.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 15: assistant Moodle read tools (`get_courses` / `get_deadlines` / `get_grades`) + no-write registration test

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_tools.py`

**Interfaces:**
- Consumes: `store.moodle_courses() -> list[dict]`, `store.moodle_deadlines(days_ahead: int | None = None) -> list[dict]`, `store.moodle_grades(course_id: str | None = None) -> list[dict]` (Task 9 store methods, contract §G, `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`); `store.upsert_moodle_deadline(d: NormalizedDeadline) -> dict` (Task 9, used only by the test to seed); `NormalizedDeadline` (contract §B, `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`); `tools.execute(name, args) -> tuple[str, dict | None]`, `tools.TOOLS`, `tools.DEFINITIONS` (existing bottom-of-file assembly, `tools.py:716-729` in the extract) — all unchanged. The read tools mirror the existing `get_email` tool dict + `_get_email` executor shape (extract-apiConfig.md §6) and the `_email_action` card helper (`tools.py:95-97`).
- Produces: `app.tools._moodle_action(title: str, meta: str) -> dict`; executors `app.tools._get_courses(args: dict) -> tuple[list[dict], dict]`, `app.tools._get_deadlines(args: dict) -> tuple[list[dict], dict]`, `app.tools._get_grades(args: dict) -> tuple[list[dict], dict]`; three new entries in `tools.TOOLS` (`get_courses`, `get_deadlines`, `get_grades`, contract §K) — consumed by the assistant loop's tool dispatch (`tools.execute`, unchanged) and the frontend's action-card renderer (existing card shape, no frontend change this task). No Moodle WRITE tool is added or ever will be this slice (read-only guarantee, Global Constraints).

- [ ] **Step 1: Write the failing test file.**

  Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_moodle_tools.py`:
  ```python
  """M6 assistant Moodle tools (READ-ONLY): get_courses / get_deadlines /
  get_grades return store data plus an "Open school" action card, and the
  registration test asserts NO Moodle write tool is ever exposed to the
  assistant (read-only guarantee, Global Constraints)."""
  import json
  from datetime import datetime, timezone

  from app import tools
  from app.providers.base import NormalizedDeadline
  from app.store import store


  def test_get_deadlines_returns_store_deadlines_and_school_action_card(client):
      # Seed one deadline through the real store upsert (Task 9) so the tool
      # reads exactly what the DB holds — no provider/network involved.
      store.upsert_moodle_deadline(
          NormalizedDeadline(
              source="moodle",
              source_id="evt-501",
              course_id="72",
              name="Summative assignment is due",
              module_name="assign",
              event_type="due",
              due_at=datetime(2026, 7, 10, 23, 59, tzinfo=timezone.utc),
              overdue=False,
              url="https://moodle-courses2527.wolfware.ncsu.edu/mod/assign/view.php?id=1",
          )
      )

      result_json, action = tools.execute("get_deadlines", {})
      result = json.loads(result_json)

      # The tool returns the store's deadline list verbatim (JSON round-tripped).
      assert isinstance(result, list)
      assert result == store.moodle_deadlines(None)
      assert result[0]["source_id"] == "evt-501"
      assert result[0]["name"] == "Summative assignment is due"

      # The action card is the frozen school card (contract §K).
      assert action == {
          "icon": "graduation-cap",
          "title": "Deadlines",
          "meta": "Upcoming Moodle due dates",
          "cta": "Open school",
          "screen": "school",
      }
      assert action["screen"] == "school"


  def test_get_deadlines_passes_days_window_through_to_store(client):
      # args["days"] must reach store.moodle_deadlines(days_ahead=...) — a bare
      # call with no days seeds the same row, and asking for a 0-day window (no
      # deadlines within it) proves the arg is actually forwarded, not dropped.
      store.upsert_moodle_deadline(
          NormalizedDeadline(
              source="moodle",
              source_id="evt-777",
              course_id="72",
              name="Quiz closes",
              module_name="quiz",
              event_type="close",
              due_at=datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc),
              overdue=False,
          )
      )

      result_json, _ = tools.execute("get_deadlines", {"days": 5})
      result = json.loads(result_json)
      assert result == store.moodle_deadlines(5)


  def test_moodle_read_tools_are_registered_and_no_write_tool_exists():
      names = {d["name"] for d in tools.DEFINITIONS}
      # The three read tools this slice adds.
      assert {"get_courses", "get_deadlines", "get_grades"} <= names
      # READ-ONLY guarantee: no Moodle write tool is ever exposed to the
      # assistant this slice (submitting/posting is slice 3, Global Constraints).
      assert not any(
          n in names for n in ("submit_assignment", "moodle_submit", "post_forum")
      )
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_tools.py -q
  ```
  Expected failure: `test_get_deadlines_*` fail because `tools.execute("get_deadlines", {...})` hits the "Unknown tool" path (executor not registered) — `json.loads(result_json)` yields `{"error": "Unknown tool get_deadlines."}` (a dict), so `result == store.moodle_deadlines(...)` and the `result[0]` indexing raise `AssertionError`/`KeyError`; `test_moodle_read_tools_are_registered_and_no_write_tool_exists` fails on the first assert because `{"get_courses", "get_deadlines", "get_grades"}` are absent from `tools.DEFINITIONS`.

- [ ] **Step 3: Implement `_moodle_action` + the three executors.**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`, add the school action-card helper alongside the other per-domain card builders (right after `_email_action`, which is at `tools.py:95-97`):
  ```python
  def _email_action(title: str, meta: str) -> dict:
      return {"icon": "mail", "title": title, "meta": meta,
              "cta": "Open email", "screen": "email"}


  def _moodle_action(title: str, meta: str) -> dict:
      return {"icon": "graduation-cap", "title": title, "meta": meta,
              "cta": "Open school", "screen": "school"}
  ```
  (Keep the existing `_email_action` body verbatim; the block above shows it only as the insertion anchor — add `_moodle_action` immediately below it.)

  Then add the three read executors. They belong with the other read tools; append them immediately after `_get_email` (the last email executor, `tools.py:452-466` in the extract), before the `# ---- task reminders (real from M3) ----` section. Each returns the store list verbatim plus the frozen school action card (reads, so the card is optional context, not a mutation — contract §K):
  ```python
  def _get_courses(args: dict):
      """List the student's synced Moodle courses (read-only, from the DB —
      never a live Moodle call)."""
      return store.moodle_courses(), _moodle_action(
          "Courses", "Your Moodle courses"
      )


  def _get_deadlines(args: dict):
      """Upcoming Moodle assignment/quiz due dates, optionally within N days
      (args['days']). Reads store.moodle_deadlines only — no provider call."""
      return store.moodle_deadlines(args.get("days")), _moodle_action(
          "Deadlines", "Upcoming Moodle due dates"
      )


  def _get_grades(args: dict):
      """Current Moodle grades, optionally scoped to one course_id
      (args['course_id']). Reads store.moodle_grades only — no provider call."""
      return store.moodle_grades(args.get("course_id")), _moodle_action(
          "Grades", "Your Moodle grades"
      )
  ```

- [ ] **Step 4: Register the three tools in `TOOLS`.**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`, the `TOOLS` list currently ends with the `get_email` entry followed by the closing `]` (extract-apiConfig.md §6, `tools.py:708-713`):
  ```python
      {"name": "get_email",
       "description": "Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
       "input_schema": {"type": "object", "properties": {
           "email_id": {"type": "integer"}},
           "required": ["email_id"], "additionalProperties": False},
       "run": _get_email},
  ]
  ```
  Insert the three Moodle read tools right after the `get_email` entry, before the closing `]`:
  ```python
      {"name": "get_email",
       "description": "Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
       "input_schema": {"type": "object", "properties": {
           "email_id": {"type": "integer"}},
           "required": ["email_id"], "additionalProperties": False},
       "run": _get_email},
      {"name": "get_courses",
       "description": "List the student's Moodle courses.",
       "input_schema": {"type": "object", "properties": {},
           "additionalProperties": False},
       "run": _get_courses},
      {"name": "get_deadlines",
       "description": "Upcoming Moodle assignment/quiz due dates (optionally within N days).",
       "input_schema": {"type": "object", "properties": {
           "days": {"type": "integer"}},
           "additionalProperties": False},
       "run": _get_deadlines},
      {"name": "get_grades",
       "description": "Current Moodle grades, optionally for one course_id.",
       "input_schema": {"type": "object", "properties": {
           "course_id": {"type": "string"}},
           "additionalProperties": False},
       "run": _get_grades},
  ]
  ```
  (`DEFINITIONS`, `_BY_NAME`, and `execute()` at the bottom of the file — `tools.py:716-729` in the extract — pick these up automatically: `DEFINITIONS` strips each dict to the Claude-facing triple and `_BY_NAME` maps name→executor. No change to that assembly.)

- [ ] **Step 5: Run the targeted test file and confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_moodle_tools.py -q
  ```
  Expected: `3 passed`.

- [ ] **Step 6: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior task's count + 3 new tests, `0 failed` (`... passed, 1 skipped`). This is a relative estimate — report the exact printed count as the actual gate. Report "X tests passing" per the user's global convention.

- [ ] **Step 7: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/tools.py tests/test_moodle_tools.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): add read-only assistant Moodle tools (courses/deadlines/grades)

  Three read tools — get_courses, get_deadlines, get_grades — each served
  straight from the store (never a live Moodle call) and returning the
  frozen "Open school" action card via _moodle_action (contract §K). The
  registration test asserts the three reads are exposed AND that no Moodle
  write tool (submit_assignment/moodle_submit/post_forum) exists, enforcing
  the slice-1 read-only guarantee for the assistant surface.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 16: Frontend wiring — icon, api.js Moodle block, App/Sidebar registration, SchoolScreen stub

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/App.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/shell/Sidebar.jsx`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SchoolScreen.jsx`

**Interfaces:**
- Consumes: the Moodle read/connect/sync endpoints (`GET /api/moodle/courses|deadlines|grades|announcements|notifications`, `POST /api/moodle/connect`, `POST /api/moodle/sync`) built in Tasks 13–14 (contract §J); the existing `request()` wrapper in `api.js` (GET = bare path; POST = `{ method, body: JSON.stringify(...) }` — the file's frozen convention, see the fitness/email helpers); the `ICONS` name→component map in `Icon.jsx` (§L / frontend extract §5); the `SCREENS` map, render if/else chain, and screen imports in `App.jsx` (§L / frontend extract §3); the `sections` nav array in `Sidebar.jsx` (§L / frontend extract §4).
- Produces: `graduation-cap` registered in `Icon.jsx`; the 7 `api.moodle*` helpers in `api.js` (`moodleCourses`, `moodleDeadlines`, `moodleGrades`, `moodleAnnouncements`, `moodleNotifications`, `moodleSync`, `moodleConnect`) — consumed by Task 17's `SchoolScreen`; a `school` entry in `SCREENS`, the `<SchoolScreen />` render branch, and a `{ id: 'school', label: 'School', icon: 'graduation-cap' }` sidebar item — together making `school` a reachable screen; a minimal `SchoolScreen.jsx` stub (fleshed out in Task 17). This is the P6 wiring seam — no backend or test change.

There is no test harness for the frontend (slice-1 and the email slice shipped none — `ls frontend/src/**/*.test.*` returns nothing). The gate for every step in this task is `npm run build` exiting 0, plus `grep` verification that the new names exist. Full browser verification happens in the live-gate task.

- [ ] **Step 1: Register the `graduation-cap` icon in both halves of `Icon.jsx`.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`, the import list is PascalCase-alphabetical and the `ICONS` map is kebab-alphabetical; add `GraduationCap` to each in its alphabetical slot (between `Folder`/`Footprints` in the imports — `GraduationCap` sorts after `Footprints`; and between `'folder'`/`'footprints'` … `'graduation-cap'` sorts after `'footprints'` and before `'heart'` in the map).

  First add the named import. Replace this run of imports:
  ```jsx
  Folder,
  Footprints,
  Heart,
  ```
  with:
  ```jsx
  Folder,
  Footprints,
  GraduationCap,
  Heart,
  ```

  Then add the `ICONS` map entry. Replace:
  ```js
  folder: Folder,
  footprints: Footprints,
  heart: Heart,
  ```
  with:
  ```js
  folder: Folder,
  footprints: Footprints,
  'graduation-cap': GraduationCap,
  heart: Heart,
  ```

- [ ] **Step 2: Verify the icon build compiles and the name resolves.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0 (a bad lucide import name would fail the Vite build here). Then:
  ```
  grep -n "GraduationCap\|'graduation-cap'" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx
  ```
  Expected: two matches — the import and the map entry.

- [ ] **Step 3: Add the Moodle (School) block to `api.js`, matching the file's GET/POST convention exactly.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`, locate the Email (M5) block (the anchor is the `emailSync` line at the end of that block):
  ```js
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),
  ```
  Replace it with (the three email helpers unchanged, then the new School block appended after them):
  ```js
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),

  // School / Moodle (M6) — every read comes straight from the moodle_* tables
  // server-side (a list call never triggers a live Moodle request), so the
  // screen works while a sync is mid-flight or Moodle is down. Only
  // moodleConnect (validate the pasted wstoken) and moodleSync (kick a
  // foreground tick) reach Moodle. The wstoken is pasted once and lives
  // server-side only — it never crosses this boundary again.
  moodleCourses: () => request('/api/moodle/courses'),
  moodleDeadlines: (days) => request(`/api/moodle/deadlines${days ? `?days=${days}` : ''}`),
  moodleGrades: (courseId) => request(`/api/moodle/grades${courseId ? `?course_id=${courseId}` : ''}`),
  moodleAnnouncements: (courseId) => request(`/api/moodle/announcements${courseId ? `?course_id=${courseId}` : ''}`),
  moodleNotifications: () => request('/api/moodle/notifications'),
  moodleSync: () => request('/api/moodle/sync', { method: 'POST' }),
  moodleConnect: (payload) => request('/api/moodle/connect', { method: 'POST', body: JSON.stringify(payload) }),
  ```

- [ ] **Step 4: Verify the api helpers compile and are all present.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0. Then:
  ```
  grep -c "moodleCourses:\|moodleDeadlines:\|moodleGrades:\|moodleAnnouncements:\|moodleNotifications:\|moodleSync:\|moodleConnect:" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js
  ```
  Expected: `7`.

- [ ] **Step 5: Create the minimal `SchoolScreen.jsx` stub.**
  This is a placeholder so `App.jsx` can import and render it in this task — Task 17 replaces its body wholesale with the full render ladder. Write `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SchoolScreen.jsx`:
  ```jsx
  /* Scuffed OS — School (live, synced with NC State WolfWare Moodle).
     Owns its own state (App.jsx renders <SchoolScreen /> with no props),
     mirroring EmailScreen's in-component fetch convention. /api/oauth/status
     drives which connection state renders; the /api/moodle/* reads feed the
     course list, deadline timeline, grades, announcements and notifications.
     Every read comes straight from the moodle_* tables server-side (never a
     live Moodle call), so it works while a sync is mid-flight or Moodle is
     down — it shows what's landed. Read-only this slice: no submit, post, or
     message send. The wstoken is pasted once and stays server-side; it never
     reaches the client again. NOTE: this is the Task-16 wiring stub — Task 17
     replaces the body with the full connect/timeline/grades ladder. */
  import React from 'react'
  import { Card, Button } from '../components/ui.jsx'
  import { Icon } from '../lib/Icon.jsx'
  import { api } from '../lib/api.js'

  export function SchoolScreen() {
    const connect = () => {
      // Placeholder — the real paste-field connect flow lands in Task 17.
      // Referencing api here keeps the import used so the stub builds cleanly.
      if (api.moodleConnect) return
    }
    return (
      <Card variant="flat" style={{ textAlign: 'center', padding: '56px 24px' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="graduation-cap" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect Moodle</h3>
        <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Sync your WolfWare courses, deadlines and grades into Scuffed OS. Read-only — your token stays server-side and message bodies are never stored.</p>
        <Button variant="primary" iconLeft={<Icon name="graduation-cap" />} onClick={connect}>Connect Moodle</Button>
      </Card>
    )
  }
  ```

- [ ] **Step 6: Wire `SchoolScreen` into `App.jsx` — import, `SCREENS` entry, render branch.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/App.jsx`, first add the screen import. Replace:
  ```jsx
  import { EmailScreen } from './screens/EmailScreen.jsx'
  import { MemoryScreen } from './screens/MemoryScreen.jsx'
  ```
  with:
  ```jsx
  import { EmailScreen } from './screens/EmailScreen.jsx'
  import { SchoolScreen } from './screens/SchoolScreen.jsx'
  import { MemoryScreen } from './screens/MemoryScreen.jsx'
  ```

  Then add the `SCREENS` entry. Replace:
  ```jsx
    email: { title: 'Email', sub: '12 new · 4 need a reply' },
    settings: { title: 'Settings', sub: 'Preferences & connections' },
  ```
  with:
  ```jsx
    email: { title: 'Email', sub: '12 new · 4 need a reply' },
    school: { title: 'School', sub: 'Courses, deadlines & grades' },
    settings: { title: 'Settings', sub: 'Preferences & connections' },
  ```

  Then add the render branch. Replace:
  ```jsx
    else if (screen === 'email') body = <EmailScreen />
    else body = <Placeholder icon={{ settings: 'settings' }[screen] || 'sparkles'} name={meta.title} />
  ```
  with:
  ```jsx
    else if (screen === 'email') body = <EmailScreen />
    else if (screen === 'school') body = <SchoolScreen />
    else body = <Placeholder icon={{ settings: 'settings' }[screen] || 'sparkles'} name={meta.title} />
  ```

- [ ] **Step 7: Add the School nav item to `Sidebar.jsx` as its own group.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/shell/Sidebar.jsx`, the `sections` array holds `{ label?, items }` groups. Add a new `School` group after the `Intelligence` group (Second Brain). Replace:
  ```jsx
      { label: 'Intelligence', items: [
        { id: 'memory', label: 'Second Brain', icon: 'brain' },
      ] },
    ]
  ```
  with:
  ```jsx
      { label: 'Intelligence', items: [
        { id: 'memory', label: 'Second Brain', icon: 'brain' },
      ] },
      { label: 'School', items: [
        { id: 'school', label: 'School', icon: 'graduation-cap' },
      ] },
    ]
  ```
  (The `item.id` `'school'` matches the `App.jsx` render key + `SCREENS` key added in Step 6; the `icon` `'graduation-cap'` matches the `ICONS` entry added in Step 1.)

- [ ] **Step 8: Verify the full wiring builds and every new name resolves.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0 (a missing `SchoolScreen` export, an unregistered icon, or a syntax slip in any of the four edited files would fail here). Then confirm the wiring landed:
  ```
  grep -n "SchoolScreen" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/App.jsx
  grep -n "id: 'school'" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/shell/Sidebar.jsx
  ```
  Expected: two matches in `App.jsx` (import + render branch) and one in `Sidebar.jsx`.

- [ ] **Step 9: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/lib/Icon.jsx frontend/src/lib/api.js frontend/src/App.jsx frontend/src/shell/Sidebar.jsx frontend/src/screens/SchoolScreen.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): wire School screen — icon, api helpers, sidebar, App branch

  Registers the graduation-cap lucide icon, adds the 7 api.moodle* read/
  connect/sync helpers (GET=bare path, POST=JSON.stringify per the file's
  convention, contract §L), and makes `school` a reachable screen via a
  SCREENS entry, an <SchoolScreen /> render branch, and a School sidebar
  group. SchoolScreen is a minimal Connect-Moodle stub here — Task 17
  fleshes out the full connect/timeline/grades ladder.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 17: SchoolScreen — connect card, deadline timeline, grades, announcements, notifications

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SchoolScreen.jsx`

**Interfaces:**
- Consumes: `api.oauthStatus()` returning `{ providers: [{ provider, status, connected_at, last_sync_at, ... }] }` (find the `provider === 'moodle'` entry — contract §J connect returns this status shape; frontend extract §1e shows the email equivalent); `api.moodleCourses()` → `CourseOut[]` (`{ id, source_id, shortname, fullname, progress, start_at, end_at, last_access_at, hidden }`); `api.moodleDeadlines(days)` → `DeadlineOut[]` (`{ id, source_id, course_id, name, module_name, event_type, due_at, overdue, url, when }`); `api.moodleGrades(courseId)` → `GradeOut[]` (`{ id, source_id, course_id, item_name, item_type, grade_formatted, grade_raw, grade_min, grade_max, graded_at }`); `api.moodleAnnouncements(courseId)` → `AnnouncementOut[]` (`{ id, source_id, course_id, forum_id, subject, author, created_at, summary_html, url }`); `api.moodleNotifications()` → `NotificationOut[]` (`{ id, source_id, subject, full_message, context_url, created_at, read }`); `api.moodleConnect({ token })` → status dict; `api.moodleSync()` → `{ synced, providers }` — all from Task 16's api.js block (contract §L). The `Card`/`Badge`/`Button` components (`../components/ui.jsx`) and `Icon` (`../lib/Icon.jsx`).
- Produces: the full self-owned, OAuth-gated `SchoolScreen` render ladder — terminal within P6 except for Task 18 (which touches the *other* screens, not this one). No later task imports new names from here.

No test harness exists for the frontend. The gate for every step is `npm run build` exiting 0 plus `grep` verification; full interactive verification happens in the live-gate task. This task replaces the entire body of the Task-16 `SchoolScreen.jsx` stub in one Write — the structure clones `EmailScreen.jsx`'s state / refresh / derived-connection / render-ladder shape (frontend extract §1), swapping Gmail reads for the five Moodle reads and the Google OAuth CTA for a wstoken paste field.

- [ ] **Step 1: Replace the whole `SchoolScreen.jsx` file with the full implementation.**
  Overwrite `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SchoolScreen.jsx` with:
  ```jsx
  /* Scuffed OS — School (live, synced with NC State WolfWare Moodle).
     Owns its own state (App.jsx renders <SchoolScreen /> with no props),
     mirroring EmailScreen's in-component fetch convention. /api/oauth/status
     drives which connection state renders; the five /api/moodle/* reads feed a
     course list + deadline timeline + grades + announcements + notifications.
     Every read comes straight from the moodle_* tables server-side (never a
     live Moodle call), so it works while a sync is mid-flight or Moodle is
     down — it shows what's landed. Read-only this slice: no submit, forum
     post, or message send. Moodle uses a static per-user wstoken (not an OAuth
     code exchange), so connecting is a one-time token paste; the token lives
     server-side only and never reaches the client again. Announcement/
     notification text is rendered as plain text (no dangerouslySetInnerHTML) —
     the backend already strips HTML. */
  import React from 'react'
  import { Card, Badge, Button } from '../components/ui.jsx'
  import { Icon } from '../lib/Icon.jsx'
  import { api } from '../lib/api.js'

  export function SchoolScreen() {
    const [status, setStatus] = React.useState(null)          // null = /status not answered yet
    const [courses, setCourses] = React.useState(null)        // null = not loaded
    const [deadlines, setDeadlines] = React.useState(null)
    const [grades, setGrades] = React.useState(null)
    const [announcements, setAnnouncements] = React.useState(null)
    const [notifications, setNotifications] = React.useState(null)
    const [selCourse, setSelCourse] = React.useState(null)    // selected course_id (string) for the grades pane
    const [token, setToken] = React.useState('')              // wstoken paste field (connect form)
    const [connectError, setConnectError] = React.useState('')

    const refresh = React.useCallback(() => {
      api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
      api.moodleCourses().then((c) => { if (c) setCourses(c) }).catch(() => {})
      api.moodleDeadlines().then((d) => { if (d) setDeadlines(d) }).catch(() => {})
      api.moodleGrades().then((g) => { if (g) setGrades(g) }).catch(() => {})
      api.moodleAnnouncements().then((a) => { if (a) setAnnouncements(a) }).catch(() => {})
      api.moodleNotifications().then((n) => { if (n) setNotifications(n) }).catch(() => {})
    }, [])

    React.useEffect(() => { refresh() }, [refresh])

    const moodle = (status?.providers || []).find((p) => p.provider === 'moodle') || null
    const connected = !!moodle
    const needsReauth = moodle?.status === 'needs_reauth'
    // Connected, no reauth, nothing has landed yet, and Moodle has never synced
    // → the first backfill is still running (mirrors EmailScreen's pre-first-
    // tick state: moodle_sync always stamps last_sync_at, so once the first
    // tick completes a genuinely-empty account shows the normal panes).
    const noData = (courses?.length || 0) === 0 && (deadlines?.length || 0) === 0
    const syncing = connected && !needsReauth && courses != null && noData && !moodle?.last_sync_at

    // Keep the grades pane pointed at a valid course once courses land.
    React.useEffect(() => {
      const list = courses || []
      if (list.length === 0) { setSelCourse(null); return }
      if (selCourse == null || !list.some((c) => c.source_id === selCourse)) setSelCourse(list[0].source_id)
    }, [courses, selCourse])

    const connect = () => {
      if (!token.trim()) { setConnectError('Paste your Moodle security key first.'); return }
      setConnectError('')
      api.moodleConnect({ token: token.trim() })
        .then(() => { setToken(''); refresh() })
        .catch(() => setConnectError("Moodle rejected that key — double-check you copied the whole value."))
    }
    const sync = () => { api.moodleSync().then(() => refresh()).catch(() => {}) }

    const courseName = (courseId) => {
      const c = (courses || []).find((x) => x.source_id === courseId)
      return c ? (c.shortname || c.fullname) : courseId
    }

    // —— not connected: paste-field connect card ——
    if (status && !connected && !needsReauth) {
      return (
        <Card variant="flat" style={{ maxWidth: 560, margin: '0 auto', padding: '40px 28px' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
              <Icon name="graduation-cap" />
            </div>
            <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect Moodle</h3>
            <p className="kit-muted" style={{ maxWidth: 420, margin: '0 auto 18px' }}>Sync your WolfWare courses, deadlines and grades into Scuffed OS. Read-only — your security key stays server-side and message bodies are never stored.</p>
          </div>
          <div className="kit-stack" style={{ gap: 10 }}>
            <input
              className="kit-input"
              placeholder="Paste your Moodle security key…"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && connect()}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono, monospace)', fontSize: 'var(--text-sm)' }}
            />
            {connectError && <p className="kit-muted" style={{ color: 'var(--clay-600)' }}>{connectError}</p>}
            <Button variant="primary" fullWidth iconLeft={<Icon name="graduation-cap" />} onClick={connect}>Connect Moodle</Button>
          </div>
          <div className="kit-divider" style={{ margin: '18px 0 12px' }} />
          <p className="sa-card__eyebrow" style={{ margin: '0 0 6px' }}>Where do I find my security key?</p>
          <ol className="kit-muted" style={{ margin: 0, paddingLeft: 18, fontSize: 'var(--text-sm)', lineHeight: 1.7 }}>
            <li>Sign in to WolfWare Moodle in your browser.</li>
            <li>Open <strong>Preferences → Security keys</strong> (under your profile menu).</li>
            <li>Copy the key for the <strong>Moodle mobile web service</strong>.</li>
            <li>Paste it above and press Connect.</li>
          </ol>
        </Card>
      )
    }

    const eyebrow = moodle?.last_sync_at
      ? `Synced with Moodle · ${new Date(moodle.last_sync_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
      : 'Connected with Moodle'
    const overdueCount = (deadlines || []).filter((d) => d.overdue).length
    const selGrades = (grades || []).filter((g) => g.course_id === selCourse)

    return (
      <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
        {needsReauth && (
          <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
            <div style={{ flex: 1 }}>
              <p className="kit-row__title">Moodle needs to be reconnected</p>
              <p className="kit-muted">Your security key expired or was revoked. Paste a fresh key to resume syncing your courses.</p>
            </div>
          </Card>
        )}

        {needsReauth && (
          <Card variant="flat" style={{ maxWidth: 560, padding: '20px 24px' }}>
            <p className="sa-card__eyebrow" style={{ margin: '0 0 8px' }}>Reconnect Moodle</p>
            <div className="kit-stack" style={{ gap: 10 }}>
              <input
                className="kit-input"
                placeholder="Paste your Moodle security key…"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && connect()}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono, monospace)', fontSize: 'var(--text-sm)' }}
              />
              {connectError && <p className="kit-muted" style={{ color: 'var(--clay-600)' }}>{connectError}</p>}
              <Button variant="primary" size="sm" onClick={connect}>Reconnect</Button>
            </div>
          </Card>
        )}

        {syncing && (
          <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
            <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
              <Icon name="refresh-cw" />
            </div>
            <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Syncing…</h3>
            <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Pulling your courses, deadlines and grades from Moodle. This usually takes a moment — hang tight.</p>
            <Button variant="secondary" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Check again</Button>
          </Card>
        )}

        {!syncing && !needsReauth && (
          <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1.4fr' }}>
            <Card title="Courses" eyebrow={eyebrow}
              action={<Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>}>
              {(courses || []).length === 0 && <p className="kit-muted" style={{ marginTop: 6 }}>No courses yet — sync to pull your enrollment.</p>}
              {(courses || []).map((c) => (
                <div key={c.id} className={'kit-mail' + (c.source_id === selCourse ? ' is-active' : '')} onClick={() => setSelCourse(c.source_id)}>
                  <div className="kit-mail__main">
                    <div className="kit-mail__top">
                      <span className="kit-mail__from">{c.shortname || c.fullname}</span>
                      {c.progress != null && <span className="kit-mail__time">{Math.round(c.progress)}%</span>}
                    </div>
                    <p className="kit-mail__snip">{c.fullname}</p>
                  </div>
                </div>
              ))}
            </Card>

            <div className="kit-col">
              <Card title="Deadlines"
                action={overdueCount > 0 ? <Badge color="clay" dot>{overdueCount} overdue</Badge> : null}>
                {(deadlines || []).length === 0 && <p className="kit-muted" style={{ marginTop: 6 }}>Nothing due in the next 60 days.</p>}
                <div className="kit-stack" style={{ gap: 0 }}>
                  {(deadlines || []).map((d) => (
                    <div className="kit-listrow" key={d.id} style={d.overdue ? { background: 'var(--clay-100)', borderRadius: 'var(--radius-md)' } : undefined}>
                      <span className="kit-listrow__dot" style={{ background: d.overdue ? 'var(--clay-600)' : 'var(--plum-600)' }} />
                      <div className="kit-row__main">
                        <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{d.name}</p>
                        <p className="kit-row__sub" style={{ fontSize: 12 }}>{courseName(d.course_id)} · {d.when}</p>
                      </div>
                      {d.overdue && <Badge color="clay">Overdue</Badge>}
                    </div>
                  ))}
                </div>
              </Card>

              <Card title="Grades" eyebrow={selCourse ? courseName(selCourse) : undefined}>
                {selGrades.length === 0 && <p className="kit-muted" style={{ marginTop: 6 }}>No grades posted for this course yet.</p>}
                <div className="kit-stack" style={{ gap: 0 }}>
                  {selGrades.map((g) => (
                    <div className="kit-listrow" key={g.id}>
                      <div className="kit-row__main">
                        <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{g.item_name}</p>
                        {g.item_type && <p className="kit-row__sub" style={{ fontSize: 12 }}>{g.item_type}</p>}
                      </div>
                      <span className="kit-row__amt">{g.grade_formatted}</span>
                    </div>
                  ))}
                </div>
              </Card>

              <Card title="Announcements" variant="sunken">
                {(announcements || []).length === 0 && <p className="kit-muted" style={{ marginTop: 6 }}>No announcements.</p>}
                <div className="kit-stack" style={{ gap: 10 }}>
                  {(announcements || []).map((a) => (
                    <div key={a.id}>
                      <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{a.subject}</p>
                      <p className="kit-row__sub" style={{ fontSize: 12 }}>{courseName(a.course_id)}{a.author ? ` · ${a.author}` : ''}</p>
                      {a.summary_html && <p className="kit-muted" style={{ fontSize: 12, marginTop: 2 }}>{a.summary_html}</p>}
                    </div>
                  ))}
                </div>
              </Card>

              {(notifications || []).length > 0 && (
                <Card title="Notifications" variant="sunken">
                  <div className="kit-stack" style={{ gap: 6 }}>
                    {(notifications || []).map((n) => (
                      <div className="kit-listrow" key={n.id}>
                        <span className={'kit-mail__dot' + (n.read ? ' read' : '')} />
                        <div className="kit-row__main">
                          <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{n.subject}</p>
                          {n.full_message && <p className="kit-row__sub" style={{ fontSize: 12 }}>{n.full_message}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </div>
          </div>
        )}
      </div>
    )
  }
  ```

  Notes on frozen-shape fidelity:
  - Connection state is read exactly as EmailScreen reads Google (`status.providers` array, `find(p.provider === 'moodle')`, `status`/`last_sync_at`), per frontend extract §1e.
  - Announcement `summary_html` and notification `full_message` are rendered as plain-text children (JSX text nodes), **never** `dangerouslySetInnerHTML` — the backend already strips HTML (contract §C `_strip_html`), so this both matches the Global Constraint ("no rich HTML rendering of Moodle content") and avoids an XSS surface.
  - Overdue deadlines are tinted with `--clay-100`/`--clay-600` (the same error-tint tokens EmailScreen uses for the reauth banner), so no new CSS is introduced.
  - `d.when`, `g.grade_formatted`, `c.progress` are consumed as the backend emits them (display strings/numbers from the store dicts, contract §G/§J) — the screen does no reformatting.

- [ ] **Step 2: Verify the full screen builds.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0 (a JSX slip, an undefined component, or a bad `api.*` reference would fail here). Then confirm the key structural pieces are present and that no raw-HTML injection sneaked in:
  ```
  grep -n "moodleConnect\|moodleSync\|provider === 'moodle'\|selCourse\|Security keys\|security key" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SchoolScreen.jsx
  ```
  Expected: matches for the connect/sync calls, the moodle provider lookup, the selected-course state, and the security-key instructions.
  ```
  grep -c "dangerouslySetInnerHTML" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SchoolScreen.jsx
  ```
  Expected: `0` (announcements/notifications render as plain text, per the Global Constraint).

- [ ] **Step 3: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/screens/SchoolScreen.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): flesh out SchoolScreen — connect, timeline, grades, feeds

  Replaces the Task-16 stub with the full self-owned, OAuth-gated ladder
  cloned from EmailScreen (contract §L): a wstoken paste-field connect card
  with Security-keys instructions, a needs-reauth banner + re-paste field, a
  syncing card, and the main two-pane grid — course list (left) plus deadline
  timeline (overdue tinted), a grades pane for the selected course, an
  announcements feed, and a notifications strip. All reads come straight from
  the moodle_* tables; announcement/notification text renders as plain text
  (no dangerouslySetInnerHTML). Read-only this slice.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 18: Read-only Moodle markers in Calendar, Tasks, and the Home agenda

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/CalendarScreen.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/TasksScreen.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/DashboardScreen.jsx`

**Interfaces:**
- Consumes: the read-time-merged Moodle rows that already arrive through `useCalendar`/`useTasks` with **no hook change** (contract §H/§M): calendar occurrences and tasks carry `source: 'moodle'` + `editable: false` and a string id `"moodle:<n>"` (the widened `EventOccurrence`/`Task` models, Tasks 10–11); `upNext` occurrences (Home agenda) carry the same `source`. The `Badge`/`Icon` components already imported in each screen (`../components/ui.jsx`, `../lib/Icon.jsx`).
- Produces: a small "Moodle" chip on `source === 'moodle'` rows in all three surfaces, with their edit/delete/toggle affordances suppressed (defensive UI only — the `"moodle:<n>"` string id already 422s any accidental mutation call server-side, since those endpoints take `int` path ids). Terminal within P6 — no later task depends on this.

No test harness exists for the frontend. The gate for every step is `npm run build` exiting 0 plus `grep` verification. The changes are minimal and localized — a chip + a guard on each surface, nothing else.

- [ ] **Step 1: Mark Moodle occurrences in the Calendar week grid.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/CalendarScreen.jsx`, `Badge` is not yet imported — the current import is `import { Card, IconButton, Button } from '../components/ui.jsx'`. Replace it:
  ```jsx
  import { Card, IconButton, Button } from '../components/ui.jsx'
  ```
  with:
  ```jsx
  import { Card, IconButton, Button, Badge } from '../components/ui.jsx'
  ```
  Then find the week-grid event block (the `.kit-event` render inside `eventsByCol[i].map`):
  ```jsx
                {eventsByCol[i].map((ev) => (
                  <div key={ev.id + '-' + ev.start} className={'kit-event kit-ev--' + (ev.tint || 'green')}
                    style={{ top: (ev.s - START) * ROW + 1, height: (ev.e - ev.s) * ROW - 3 }}>
                    <b>{ev.title}</b><span>{ev.at}</span>
                  </div>
                ))}
  ```
  Replace it with (adding a compact "Moodle" tag on merged read-only occurrences; Calendar events have no inline edit/delete controls in this view, so the chip is the only change needed):
  ```jsx
                {eventsByCol[i].map((ev) => (
                  <div key={ev.id + '-' + ev.start} className={'kit-event kit-ev--' + (ev.tint || 'green')}
                    style={{ top: (ev.s - START) * ROW + 1, height: (ev.e - ev.s) * ROW - 3 }}>
                    <b>{ev.title}</b>
                    <span>{ev.at}{ev.source === 'moodle' ? ' · Moodle' : ''}</span>
                  </div>
                ))}
  ```
  Then find the "Up next" side list (occurrences share the merged `source`):
  ```jsx
              {upNext.map((u, i) => (
                <div className="kit-listrow" key={i}>
                  <span className="kit-listrow__dot" style={{ background: `var(--${u.tint || 'green'}-600)` }} />
                  <div className="kit-row__main">
                    <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{u.title}</p>
                    <p className="kit-row__sub" style={{ fontSize: 12 }}>{u.when}</p>
                  </div>
                </div>
              ))}
  ```
  Replace it with:
  ```jsx
              {upNext.map((u, i) => (
                <div className="kit-listrow" key={i}>
                  <span className="kit-listrow__dot" style={{ background: `var(--${u.tint || 'green'}-600)` }} />
                  <div className="kit-row__main">
                    <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{u.title}</p>
                    <p className="kit-row__sub" style={{ fontSize: 12 }}>{u.when}</p>
                  </div>
                  {u.source === 'moodle' && <Badge color="plum">Moodle</Badge>}
                </div>
              ))}
  ```

- [ ] **Step 2: Verify the Calendar build.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0. Then:
  ```
  grep -n "source === 'moodle'\|Badge" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/CalendarScreen.jsx
  ```
  Expected: the `Badge` import plus two `source === 'moodle'` guards (week event tag + Up-next chip).

- [ ] **Step 3: Mark Moodle rows in the Tasks list and suppress their controls.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/TasksScreen.jsx`, the `TaskRow` render currently makes every row a clickable detail-opener with an editable checkbox and a chevron. A Moodle-sourced task is read-only (`editable === false`, string id `"moodle:<n>"`), so it must not open the editor, must not toggle, and must show a "Moodle" chip instead of the chevron. Replace the whole `TaskRow` function:
  ```jsx
    const TaskRow = (raw) => {
      const t = withColor(raw)
      const subs = t.subtasks || []
      const subsDone = subs.filter((s) => s.done).length
      return (
        <div className={'kit-task' + (t.done ? ' kit-task--done' : '')} key={t.id} onClick={() => setOpenId(t.id)}>
          <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex' }}>
            <Checkbox checked={t.done} onChange={() => onToggle(t.id)} />
          </span>
          <div className="kit-task__main">
            <p className="kit-task__title">{t.label}</p>
            <div className="kit-task__meta">
              <span className="kit-prio" style={{ background: t.prio === 'high' ? 'var(--clay-600)' : t.prio === 'med' ? 'var(--honey-600)' : 'var(--green-500)' }} />
              {t.due && <span className={'kit-task__due' + (t.late ? ' is-late' : '')}><Icon name={t.late ? 'alarm-clock' : 'clock'} />{t.due}</span>}
              <Badge color={t.listColor}>{t.list}</Badge>
              {subs.length > 0 && <span className="kit-task__due"><Icon name="list-checks" />{subsDone}/{subs.length}</span>}
              {(t.files || []).length > 0 && <span className="kit-task__due"><Icon name="paperclip" />{t.files.length}</span>}
            </div>
          </div>
          <span className="kit-task__chev"><Icon name="chevron-right" /></span>
        </div>
      )
    }
  ```
  with (a Moodle row is read-only: no `onClick` opener, a disabled checkbox that never toggles, and a "Moodle" chip in place of the chevron):
  ```jsx
    const TaskRow = (raw) => {
      const t = withColor(raw)
      const subs = t.subtasks || []
      const subsDone = subs.filter((s) => s.done).length
      // Moodle deadlines are merged in read-only (contract §M): editable===false
      // and a string id "moodle:<n>" that already 422s any mutation endpoint
      // server-side. Suppress the detail-opener, toggle and chevron; show a
      // "Moodle" chip instead.
      const readOnly = t.editable === false || t.source === 'moodle'
      return (
        <div className={'kit-task' + (t.done ? ' kit-task--done' : '')} key={t.id} onClick={readOnly ? undefined : () => setOpenId(t.id)}>
          <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex' }}>
            <Checkbox checked={t.done} onChange={readOnly ? undefined : () => onToggle(t.id)} />
          </span>
          <div className="kit-task__main">
            <p className="kit-task__title">{t.label}</p>
            <div className="kit-task__meta">
              <span className="kit-prio" style={{ background: t.prio === 'high' ? 'var(--clay-600)' : t.prio === 'med' ? 'var(--honey-600)' : 'var(--green-500)' }} />
              {t.due && <span className={'kit-task__due' + (t.late ? ' is-late' : '')}><Icon name={t.late ? 'alarm-clock' : 'clock'} />{t.due}</span>}
              <Badge color={t.listColor}>{t.list}</Badge>
              {subs.length > 0 && <span className="kit-task__due"><Icon name="list-checks" />{subsDone}/{subs.length}</span>}
              {(t.files || []).length > 0 && <span className="kit-task__due"><Icon name="paperclip" />{t.files.length}</span>}
            </div>
          </div>
          {readOnly
            ? <Badge color="plum">Moodle</Badge>
            : <span className="kit-task__chev"><Icon name="chevron-right" /></span>}
        </div>
      )
    }
  ```
  This is the only change in the file — `TaskDetail` at the bottom already only mounts for `openTask` (found by `openId`), and a read-only Moodle row can never set `openId` now, so the editor never opens on a `"moodle:<n>"` id.

- [ ] **Step 4: Verify the Tasks build.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0. Then:
  ```
  grep -n "readOnly\|editable === false\|source === 'moodle'\|Moodle" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/TasksScreen.jsx
  ```
  Expected: the `readOnly` derivation (guarding on `t.editable === false || t.source === 'moodle'`), the guarded `onClick`/`onChange`, and the "Moodle" chip.

- [ ] **Step 5: Mark Moodle rows in the Home agenda and Home tasks list.**
  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/DashboardScreen.jsx`, the agenda is built from `calendar.upNext`; carry the merged `source` through so the agenda rows can flag Moodle items, and guard the Home tasks-list checkbox (which currently toggles unconditionally). First, carry `source` into the agenda mapping. Replace:
  ```jsx
    const agenda = ((calendar && calendar.upNext) || []).map((u, i) => ({
      time: (u.when || '').split(' · ')[0],
      title: u.title,
      meta: (u.when || '').split(' · ').slice(1).join(' · '),
      icon: u.tint === 'sky' ? 'video' : undefined,
      active: i === 0,
    }))
  ```
  with:
  ```jsx
    const agenda = ((calendar && calendar.upNext) || []).map((u, i) => ({
      time: (u.when || '').split(' · ')[0],
      title: u.title,
      meta: (u.when || '').split(' · ').slice(1).join(' · '),
      icon: u.tint === 'sky' ? 'video' : undefined,
      moodle: u.source === 'moodle',
      active: i === 0,
    }))
  ```
  Then flag the agenda row. Replace:
  ```jsx
              <div key={i} className={`kit-agenda__item ${a.active ? '' : 'kit-agenda__item--muted'}`}>
                <div className="kit-agenda__time">{a.time}</div>
                <div className="kit-agenda__body">
                  <p className="kit-agenda__title">{a.title}</p>
                  <p className="kit-agenda__meta">{a.icon && <Icon name={a.icon} />}{a.meta}</p>
                </div>
              </div>
  ```
  with:
  ```jsx
              <div key={i} className={`kit-agenda__item ${a.active ? '' : 'kit-agenda__item--muted'}`}>
                <div className="kit-agenda__time">{a.time}</div>
                <div className="kit-agenda__body">
                  <p className="kit-agenda__title">{a.title}{a.moodle && <Badge color="plum" style={{ marginLeft: 8 }}>Moodle</Badge>}</p>
                  <p className="kit-agenda__meta">{a.icon && <Icon name={a.icon} />}{a.meta}</p>
                </div>
              </div>
  ```
  Then guard the Home tasks-list checkbox so a merged read-only Moodle task can't be toggled from Home either. Replace:
  ```jsx
            {tasks.map((t) => (
              <div key={t.id} style={{ padding: '7px 0' }}>
                <Checkbox checked={t.done} strikeWhenChecked label={t.label} onChange={() => onToggleTask(t.id)} />
              </div>
            ))}
  ```
  with:
  ```jsx
            {tasks.map((t) => {
              const readOnly = t.editable === false || t.source === 'moodle'
              return (
                <div key={t.id} style={{ padding: '7px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Checkbox checked={t.done} strikeWhenChecked label={t.label} onChange={readOnly ? undefined : () => onToggleTask(t.id)} />
                  {readOnly && <Badge color="plum">Moodle</Badge>}
                </div>
              )
            })}
  ```
  (`Badge` is already imported in `DashboardScreen.jsx`'s first import line — no import change needed here.)

- [ ] **Step 6: Verify the Home build.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0. Then:
  ```
  grep -n "moodle\|readOnly\|Moodle" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/DashboardScreen.jsx
  ```
  Expected: the `moodle:` agenda flag, the agenda-row chip, the tasks-list `readOnly` guard, and its chip.

- [ ] **Step 7: Final build across all three screens together, then commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/screens/CalendarScreen.jsx frontend/src/screens/TasksScreen.jsx frontend/src/screens/DashboardScreen.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(school): mark merged Moodle rows read-only in Calendar, Tasks & Home

  Moodle deadlines/assignments merge into the calendar and tasks feeds
  read-time with source="moodle", editable=false and a "moodle:<n>" string id
  (contract §H/§M). The UI now shows a small "Moodle" chip on those rows and
  suppresses their edit/delete/toggle affordances (Tasks row no longer opens
  the editor or toggles; Home checkbox is inert; Calendar tags the event and
  Up-next chip). Defensive only — the string id already 422s any mutation
  endpoint, which takes int path ids. No hook or backend change.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 19: Privacy wave 1 (Moodle read) + docs (canonical + corp-site + docs/school.md + README row)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`
- Modify: `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/school.md`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/README.md`

**Interfaces:**
- Consumes: the current canonical markdown and corp-site HTML (both already describe WHOOP + Gmail from the M4/M5 waves; neither mentions Moodle); the frozen Moodle read-only behavior built by Phases P1–P6 (static `wstoken` stored in `provider_accounts`, never serialized; read-only sync of courses/deadlines/assignments/grades/announcements/notifications; deadlines projected read-time into Calendar/Tasks per contract §H; disconnect deletes all Moodle data via `store.delete_moodle_data`).
- Produces: the canonical markdown (`docs/privacy-policy.md`) and corp-site HTML (`scuffed-corporation/privacy/index.html`, committed on `redesign/mono-bold`) both updated so Moodle appears in Section 1 (collect paragraph), Section 3 (provider table row), Section 4 (a dedicated "If you choose to connect Moodle" block, added as `4b`/`Section 4b` after the Gmail `4a` block), and Section 6 (retention cross-ref), with the effective date bumped; a new `docs/school.md` 7-part function doc; a `docs/README.md` status-table row for it. The gist re-sync is a documented-but-not-executed step requiring explicit user approval.

This is a docs-only slice with no automated test — the guardrail is that the two privacy copies stay in sync and read correctly (verified with `grep -c` after each edit) and that the full suite's pass count is unchanged (no code touched). Do the canonical markdown first (it is the source of truth), then mirror to the corp-site HTML, then document (but do not execute) the gist sync.

- [ ] **Step 1: Edit the canonical markdown — Section 1 collect-paragraph, Section 3 provider row, effective date**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`.

**(a)** Bump the effective date. Replace the exact current line 3:

```
**Effective date:** June 10, 2026
```

with:

```
**Effective date:** July 4, 2026
```

**(b)** The intro paragraph names only WHOOP and Gmail as connected services. Replace the exact current line:

```
This policy describes what data ScuffedOS stores, how it is used, and which service providers process it. It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP and Gmail.
```

with:

```
This policy describes what data ScuffedOS stores, how it is used, and which service providers process it. It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP, Gmail, and Moodle.
```

**(c)** Section 1's "Connected service data" paragraph currently ends after the Gmail sentences. Append a Moodle sentence to it. Replace the exact current line (the whole "Connected service data" paragraph):

```
**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, ScuffedOS reads your inbox messages via the Gmail API after you authorize access through Google's OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, ScuffedOS acts on your mailbox only when you take an explicit action — sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. See Section 4 for how WHOOP and Gmail data are handled.
```

with:

```
**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, ScuffedOS reads your inbox messages via the Gmail API after you authorize access through Google's OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, ScuffedOS acts on your mailbox only when you take an explicit action — sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. If you connect a Moodle (school learning-management) account, ScuffedOS reads your course information via the Moodle web-services API after you paste in an access token you obtain from your school's Moodle site; access is read-only, and it stores course names, assignment due dates, assignment and grade metadata, and short announcement and notification summaries — never assignment files or the full text of course content. See Section 4 for how WHOOP, Gmail, and Moodle data are handled.
```

**(d)** Section 3's provider table currently ends with the Google (Gmail) and USDA rows. Add a Moodle row immediately after the Google (Gmail) row and before the USDA row. Replace the exact current two-line block:

```
| **Google (Gmail)** | Email source — read and user-initiated actions (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage or, when you ask for an AI draft, to generate one — see Section 4. Actions you take (send, reply, forward, trash, star, read/unread, labels) are carried out via the Gmail API using your own account; sent mail is delivered through Gmail and appears in your Sent folder |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |
```

with:

```
| **Google (Gmail)** | Email source — read and user-initiated actions (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage or, when you ask for an AI draft, to generate one — see Section 4. Actions you take (send, reply, forward, trash, star, read/unread, labels) are carried out via the Gmail API using your own account; sent mail is delivered through Gmail and appears in your Sent folder |
| **Moodle** (school LMS, e.g. NC State WolfWare) | School source, read-only (only if you connect it) | A `wstoken` you provide; ScuffedOS reads your courses, deadlines, grades, and announcements via the Moodle web-services API to display them. Course data may be included in assistant context sent to Anthropic only when you ask the assistant about school — see Section 4 |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |
```

**Run:**

```bash
grep -c "July 4, 2026" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "connect a Moodle (school learning-management) account" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "School source, read-only" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "June 10, 2026" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
```

**Expected:** the first three print `1`; `June 10, 2026` prints `0` (the only effective-date line was replaced — the corp-site copy is a separate repo edited in Step 3). Do NOT commit yet — the Section 4 block and Section 6 cross-ref (next step) land in the same commit.

- [ ] **Step 2: Edit the canonical markdown — Section 4 Moodle block (`4b`) + Section 6 retention cross-ref**

Continue editing `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`.

**(a)** Section 4 currently ends with the Gmail block, whose last two lines are the disconnect bullet and the "not affiliated … Google" line, immediately followed by the `## 5. Data storage and security` heading. Insert a dedicated Moodle block between the Gmail "not affiliated … Google" line and the `## 5.` heading. Replace the exact current block:

```
ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.

## 5. Data storage and security
```

with:

```
ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.

If you choose to connect Moodle:

- Access is **read-only** and is granted only after you explicitly provide an access token (a `wstoken`) that you obtain from your school's Moodle site (for NC State WolfWare, from the Security-keys page after signing in). ScuffedOS never sees your school username or password; only the token you paste is stored, server-side, and it is never exposed to the client.
- ScuffedOS reads your course data to display it in the School section. It **stores** your course names, assignment due dates, assignment and grade metadata (title, status, points), and short announcement and notification summaries.
- ScuffedOS does **not** store the contents of course files or the full body text of assignments or course pages. Those are **fetched live** from Moodle only when you open them, and are never written to disk.
- Assignment deadlines from Moodle are **projected into your Calendar and Tasks locally** so they appear alongside your own events and to-dos. These projected entries are read-only markers derived from Moodle data — they are not copied into your calendar or task tables and cannot be edited or deleted through ScuffedOS; changing them happens in Moodle.
- Moodle data is **never sent to Anthropic except when you ask the assistant about your school** (for example, "what's due this week?"); it is never sent to any other provider, never sold, never shared with third parties for their own purposes, and never used for advertising.
- You can disconnect Moodle within ScuffedOS at any time. On disconnect, all stored Moodle data and your access token are deleted. As with all deletions, this is honored within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Moodle, Moodle Pty Ltd, or North Carolina State University.

## 5. Data storage and security
```

**(b)** Section 6 currently cross-references WHOOP and Gmail disconnect-deletion. Append a Moodle clause. Replace the exact current line:

```
Data is retained until you delete it. ScuffedOS provides in-app deletion for every domain (tasks, events, habits, logs, memories, conversations), and the operator can delete any record — or all data — directly from the database at any time. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens. For any deletion request, contact us at the address below and it will be honored within 30 days.
```

with:

```
Data is retained until you delete it. ScuffedOS provides in-app deletion for every domain (tasks, events, habits, logs, memories, conversations), and the operator can delete any record — or all data — directly from the database at any time. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens; disconnecting Moodle likewise deletes all stored Moodle data (courses, deadlines, assignments, grades, announcements, notifications) and your Moodle access token. For any deletion request, contact us at the address below and it will be honored within 30 days.
```

**Run:**

```bash
grep -c "If you choose to connect Moodle" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "projected into your Calendar and Tasks locally" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "except when you ask the assistant about your school" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "not affiliated with, endorsed by, or sponsored by Moodle" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "disconnecting Moodle likewise deletes" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
```

**Expected:** every line prints `1`.

- [ ] **Step 3: Create `docs/school.md` (7-part function-doc skeleton) + add the `docs/README.md` status row**

**(a)** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/school.md` — the 7-part skeleton every function doc follows (Responsibility · Surface/current state · Data model · Dependencies & interactions · How it _should_ function · External integrations · Open questions), matching the shape of `docs/email.md`:

```markdown
# School (Moodle) — Architecture

> Status: **building** (M6 slice-1) · Last updated: 2026-07-04 · Owner: _Dylan_
>
> Part of the [backend overview](backend-overview.md). A read-only view of the student's
> Moodle learning-management data — courses, deadlines, grades, and announcements — that
> also feeds assignment due dates into the existing Calendar and Tasks.

## Responsibility

Connect to a Moodle instance (NC State's WolfWare, `moodle-courses2527.wolfware.ncsu.edu`)
via a pasted access token, **sync** the student's courses, deadline timeline, assignments
(+ submission status), grades, announcements, and notifications into Postgres, and serve
them to a `SchoolScreen`. Project assignment deadlines into the Calendar/Tasks output at
read time so they appear on Home/Calendar/Tasks as **read-only** markers.

## Surface / current state

Building in M6 slice-1 (this plan). The screen is served from the DB — every `/api/moodle/*`
GET reads stored rows; only `POST /api/moodle/connect` (validate the pasted token) and
`POST /api/moodle/sync` (the tick) reach Moodle.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/moodle/connect` | Validate a pasted `wstoken`, store it, kick a first sync. |
| `GET` | `/api/moodle/courses` | Enrolled courses. |
| `GET` | `/api/moodle/deadlines?days=` | Upcoming deadline timeline. |
| `GET` | `/api/moodle/grades?course_id=` | Grade items (optionally one course). |
| `GET` | `/api/moodle/announcements?course_id=` | News-forum announcements. |
| `GET` | `/api/moodle/notifications` | Popup notifications. |
| `POST` | `/api/moodle/sync` | Pull from Moodle (the tick). |

## Data model

Six owner-scoped tables (`moodle_courses`, `moodle_deadlines`, `moodle_assignments`,
`moodle_grades`, `moodle_announcements`, `moodle_notifications`), each keyed
`(owner, source, source_id)` for idempotent upserts (mirrors the `emails` table). No file
bytes or full content bodies are stored — only names, due dates, status/points metadata,
and short HTML summaries (stripped for display). See [data-store.md](data-store.md).

## Dependencies & interactions

- **OAuth plumbing (shared).** Reuses the `/api/oauth/status` + disconnect surface; connect
  is a thin token-paste endpoint because Moodle uses a static `wstoken`, not a code exchange.
- **School → Calendar / Tasks.** Assignment deadlines are projected read-time into
  `store.events_between()` / `store.list_tasks()` output (tagged `source="moodle"`,
  `editable=False`) — no rows are copied into the `events`/`tasks` tables. See
  [calendar.md](calendar.md) and [tasks.md](tasks.md).
- **Assistant / LLM.** Read tools (`get_courses`, `get_deadlines`, `get_grades`) let the
  assistant answer school questions; course data reaches Anthropic only on such a request.
  See [assistant.md](assistant.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [ ] **Sync pipeline** (`moodle_sync.py`, a clone of `email_sync.py`) that upserts the six
      record types idempotently and flips the account to `needs_reauth` on an auth error.
- [ ] **Read-time Calendar/Tasks merge** — deadlines/assignments projected into the existing
      output shapes, never physical rows, so those tables need no schema change or write-guards.
- [ ] **Privacy** — token stored server-side only; content bodies/files fetched live, never
      stored; disconnect deletes all Moodle data within 30 days.

## External integrations

- **Moodle web services** (`{base}/webservice/rest/server.php`) — hand-rolled `httpx` over the
  REST endpoint (no vendor SDK), static per-user `wstoken`, JSON format. Errors come back
  HTTP 200 with an `"exception"` key. Read-only this slice — no submit/post/message writes.

## Open questions / future work

- Assignment **submission** (upload a file, mark done) — deferred to a later slice.
- Course-content/file browsing and rich HTML rendering of Moodle pages.
- Multi-instance support (more than one Moodle) and calendar/tasks → Moodle write-back.
```

**(b)** Add a status-table row to `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/README.md`. The "Function docs" table currently ends with the `people.md` row. Replace the exact current line:

```
| [people.md](people.md) | Personal CRM — contacts, cadence, nudges, dates | ⬜ Planned |
```

with:

```
| [people.md](people.md) | Personal CRM — contacts, cadence, nudges, dates | ⬜ Planned |
| [school.md](school.md) | Moodle courses, deadlines, grades, announcements (read-only) — `/api/moodle` | 🔨 Building |
```

**Run:**

```bash
grep -c "# School (Moodle) — Architecture" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/school.md
grep -c "school.md" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/README.md
```

**Expected:** the first prints `1`; the second prints `2` (the new README row links `school.md` twice — once as the doc link text `[school.md]` and once in the `(school.md)` target).

**Commit (canonical markdown + docs, in the ScuffedOS repo — the corp-site copy follows in Step 4):**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git checkout m6-school-moodle-slice1
git add docs/privacy-policy.md docs/school.md docs/README.md
git commit -m "$(cat <<'EOF'
docs(privacy): wave 1 — Moodle read-only (+ docs/school.md, README row)

Section 1, Section 3's provider table, a new Section 4b block, and Section 6
now describe the read-only Moodle integration: a wstoken the user provides;
STORED = course names, due dates, assignment/grade metadata, announcement/
notification summaries; live-fetched-not-stored = course files and assignment
bodies; deadlines projected read-time into Calendar/Tasks; nothing sent to
Anthropic except when the user asks the assistant about school; disconnect
deletes all Moodle data within 30 days; not affiliated with Moodle or NC
State. Effective date bumped to 2026-07-04. Adds docs/school.md (7-part
function doc) and a docs/README.md status row.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Expected:** commit succeeds on branch `m6-school-moodle-slice1`.

- [ ] **Step 4: Mirror to the corp-site HTML copy (`scuffed-corporation/privacy/index.html`)**

The corp site is a **separate git repo** at `/Users/dylanschempp/PycharmProjects/scuffed-corporation`, on branch `redesign/mono-bold`. Apply the same content in HTML, using the site's existing entity style (`&rsquo;`, `&ldquo;`/`&rdquo;`, `&mdash;`, `&middot;`, `&nbsp;`). The Gmail section there is `<section ... aria-labelledby="gmail-data">` (heading "4a. Gmail data"); the new Moodle section is added as a `4b` section right after it.

First confirm you are on the right branch:

```bash
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation
git checkout redesign/mono-bold
```

Edit `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`.

**(a)** Bump both effective-date spots. Replace the exact current sec-label line (line 46):

```html
      <p class="sec-label"><span>00 &mdash; privacy policy</span><span>effective june 10, 2026</span></p>
```

with:

```html
      <p class="sec-label"><span>00 &mdash; privacy policy</span><span>effective july 4, 2026</span></p>
```

and replace the exact current body line (line 49):

```html
        <p><strong>Effective date:</strong> June 10, 2026</p>
```

with:

```html
        <p><strong>Effective date:</strong> July 4, 2026</p>
```

**(b)** The intro paragraph (line 51) names WHOOP and Gmail. Replace the exact current line:

```html
        <p>This policy describes what data Scuffed OS stores, how it is used, and which service providers process it. It applies to the Scuffed OS application and any data obtained through connected services such as WHOOP and Gmail.</p>
```

with:

```html
        <p>This policy describes what data Scuffed OS stores, how it is used, and which service providers process it. It applies to the Scuffed OS application and any data obtained through connected services such as WHOOP, Gmail, and Moodle.</p>
```

**(c)** Section 1 "Connected service data" paragraph (line 62) — append the Moodle sentence. Replace the exact current line:

```html
        <p><strong>Connected service data (with your consent).</strong> If you connect a WHOOP account, Scuffed OS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP&rsquo;s OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, Scuffed OS reads your inbox messages via the Gmail API after you authorize access through Google&rsquo;s OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, Scuffed OS acts on your mailbox only when you take an explicit action &mdash; sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. See <a href="#whoop-data">Section 4</a> and <a href="#gmail-data">Section 4a</a> for how WHOOP and Gmail data are handled.</p>
```

with:

```html
        <p><strong>Connected service data (with your consent).</strong> If you connect a WHOOP account, Scuffed OS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP&rsquo;s OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, Scuffed OS reads your inbox messages via the Gmail API after you authorize access through Google&rsquo;s OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, Scuffed OS acts on your mailbox only when you take an explicit action &mdash; sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. If you connect a Moodle (school learning-management) account, Scuffed OS reads your course information via the Moodle web-services API after you paste in an access token you obtain from your school&rsquo;s Moodle site; access is read-only, and it stores course names, assignment due dates, assignment and grade metadata, and short announcement and notification summaries &mdash; never assignment files or the full text of course content. See <a href="#whoop-data">Section 4</a>, <a href="#gmail-data">Section 4a</a>, and <a href="#moodle-data">Section 4b</a> for how WHOOP, Gmail, and Moodle data are handled.</p>
```

**(d)** Section 3 provider table — add a Moodle row after the Google (Gmail) row and before the USDA row. Replace the exact current block (the USDA `<tr>`, lines 120–124):

```html
              <tr>
                <th scope="row"><strong>USDA FoodData Central</strong></th>
                <td>Food nutrition lookup</td>
                <td>Only the food search text you enter (e.g., &ldquo;chicken wrap&rdquo;)</td>
              </tr>
```

with:

```html
              <tr>
                <th scope="row"><strong>Moodle</strong> (school LMS, e.g. NC&nbsp;State WolfWare)</th>
                <td>School source, read-only (only if you connect it)</td>
                <td>A <code>wstoken</code> you provide; Scuffed OS reads your courses, deadlines, grades, and announcements via the Moodle web-services API to display them. Course data may be included in assistant context sent to Anthropic only when you ask the assistant about school &mdash; see <a href="#moodle-data">Section 4b</a></td>
              </tr>
              <tr>
                <th scope="row"><strong>USDA FoodData Central</strong></th>
                <td>Food nutrition lookup</td>
                <td>Only the food search text you enter (e.g., &ldquo;chicken wrap&rdquo;)</td>
              </tr>
```

**(e)** Add the Moodle `4b` section immediately after the closing `</section>` of the Gmail `4a` block (the Gmail section ends at line 168 with `</section>`, right before the `<!-- 05 / data storage and security -->` comment). Replace the exact current block:

```html
    </section>

    <!-- 05 / data storage and security -->
```

with:

```html
    </section>

    <!-- 04c / moodle data -->
    <section class="sec" aria-labelledby="moodle-data">
      <p class="sec-label"><span>04 &mdash; moodle data</span><span>read-only &middot; bodies &amp; files not stored</span></p>
      <div class="sec-main">
        <h2 id="moodle-data">4b. Moodle data</h2>
        <p>If you choose to connect Moodle:</p>
        <ul>
          <li>Access is <strong>read-only</strong> and is granted only after you explicitly provide an access token (a <code>wstoken</code>) that you obtain from your school&rsquo;s Moodle site (for NC&nbsp;State WolfWare, from the Security-keys page after signing in). Scuffed OS never sees your school username or password; only the token you paste is stored, server-side, and it is never exposed to the client.</li>
          <li>Scuffed OS reads your course data to display it in the School section. It <strong>stores</strong> your course names, assignment due dates, assignment and grade metadata (title, status, points), and short announcement and notification summaries.</li>
          <li>Scuffed OS does <strong>not</strong> store the contents of course files or the full body text of assignments or course pages. Those are <strong>fetched live</strong> from Moodle only when you open them, and are never written to disk.</li>
          <li>Assignment deadlines from Moodle are <strong>projected into your Calendar and Tasks locally</strong> so they appear alongside your own events and to-dos. These projected entries are read-only markers derived from Moodle data &mdash; they are not copied into your calendar or task tables and cannot be edited or deleted through Scuffed OS; changing them happens in Moodle.</li>
          <li>Moodle data is <strong>never sent to Anthropic except when you ask the assistant about your school</strong> (for example, &ldquo;what&rsquo;s due this week?&rdquo;); it is never sent to any other provider, never sold, never shared with third parties for their own purposes, and never used for advertising.</li>
          <li>You can disconnect Moodle within Scuffed OS at any time. On disconnect, all stored Moodle data and your access token are deleted. As with all deletions, this is honored within 30 days.</li>
        </ul>
        <p>Scuffed OS is an independent application and is not affiliated with, endorsed by, or sponsored by Moodle, Moodle Pty Ltd, or North Carolina State University.</p>
      </div>
    </section>

    <!-- 05 / data storage and security -->
```

**(f)** Section 6 retention (line 190) — append a Moodle clause. Replace the exact current line:

```html
        <p>Data is retained until you delete it. Scuffed OS provides in-app deletion for every domain (tasks, events, habits, logs, memories, conversations), and the operator can delete any record &mdash; or all data &mdash; directly from the database at any time. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in <a href="#whoop-data">Section 4</a>; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens. For any deletion request, contact us at <a href="#contact">the address below</a> and it will be honored within 30 days.</p>
```

with:

```html
        <p>Data is retained until you delete it. Scuffed OS provides in-app deletion for every domain (tasks, events, habits, logs, memories, conversations), and the operator can delete any record &mdash; or all data &mdash; directly from the database at any time. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in <a href="#whoop-data">Section 4</a>; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens; disconnecting Moodle likewise deletes all stored Moodle data (courses, deadlines, assignments, grades, announcements, notifications) and your Moodle access token. For any deletion request, contact us at <a href="#contact">the address below</a> and it will be honored within 30 days.</p>
```

**Run** (verify the HTML edits and that the file is still well-formed):

```bash
grep -c "effective july 4, 2026" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c 'id="moodle-data"' /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "School source, read-only" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "projected into your Calendar and Tasks locally" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "not affiliated with, endorsed by, or sponsored by Moodle" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "june 10, 2026" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
python3 -c "import html.parser; p=html.parser.HTMLParser(); p.feed(open('/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html').read()); print('html-parses-ok')"
```

**Expected:** the first five `grep -c` print `1` (`effective july 4, 2026` once — the body `<p>` uses capitalized "July 4, 2026", so it does not also match this lowercased pattern); `june 10, 2026` prints `0` (both the lowercased sec-label spot is replaced; the capitalized body spot was `June 10, 2026`, also replaced, and does not match this lowercased grep anyway); the python line prints `html-parses-ok` with no exception.

**Commit in the corp-site repo:**

```bash
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation
git add privacy/index.html
git commit -m "$(cat <<'EOF'
privacy: wave 1 — Moodle read (sync with app policy)

Mirrors docs/privacy-policy.md in the ScuffedOS repo (M6 school slice-1):
Section 1, the Section 3 provider table, a new Section 4b block, and Section 6
now describe the read-only Moodle integration — a user-provided wstoken;
stored course/deadline/grade metadata and short summaries; files and content
bodies fetched live, never stored; deadlines projected read-time into
Calendar/Tasks; sent to Anthropic only on a school question; disconnect deletes
all Moodle data within 30 days; not affiliated with Moodle or NC State.
Effective date bumped to 2026-07-04.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Expected:** commit succeeds on branch `redesign/mono-bold`. (Deploying the static site is out of scope for this slice — the commit is the deliverable, matching the M4/M5 convention.)

- [ ] **Step 5: Document (do NOT execute) the gist sync — REQUIRES EXPLICIT USER APPROVAL**

The gist `439cee7cba3ac9077da6a5b81f83527c` (file `privacy-policy.md`, viewable at `https://gist.github.com/daschempp/439cee7cba3ac9077da6a5b81f83527c`) is the third copy and must eventually match the updated canonical markdown verbatim. **Learned in M5: the auto-mode permission classifier blocks this PATCH as a public publish.** Do NOT attempt to run it as part of this task. Instead, hand the exact command to the user for them to run or explicitly approve:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
python3 - <<'PY'
import json, subprocess
body = json.dumps({
    "description": "ScuffedOS Privacy Policy",
    "files": {"privacy-policy.md": {"content": open("docs/privacy-policy.md").read()}},
})
subprocess.run(
    ["gh", "api", "-X", "PATCH", "gists/439cee7cba3ac9077da6a5b81f83527c", "--input", "-"],
    input=body, text=True, check=True,
)
print("gist-patched")
PY
```

**Verification command for the user to run afterward** (also do not auto-run):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
gh gist view 439cee7cba3ac9077da6a5b81f83527c --raw > /tmp/gist_privacy.md
diff docs/privacy-policy.md /tmp/gist_privacy.md && echo "GIST-IN-SYNC"
```

**Expected once the user runs it:** `gist-patched` prints with no error, then `diff` prints nothing and `GIST-IN-SYNC` appears. Until the user runs this, note the gist as the one remaining out-of-sync copy. No git commit for this step (the gist is not in the repo). **This same run also covers any still-pending prior-wave gist sync — one push publishes the whole current canonical file.**

- [ ] **Step 6: Confirm the full suite count is unchanged (no code was touched), then done**

This task edits only docs (`.md`) and the corp-site HTML — no Python source, no tests. Run the full backend suite to confirm the pass count is exactly the previous task's baseline (nothing was added or broken):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
```

**Expected:** the suite is green and the pass count is **unchanged** from the previous task (no `test_*` file was added or modified). Report the count as "X tests passing".

---

### Task 20: `smoke_moodle.py` — live Moodle read-only smoke test (mirrors `smoke_google.py`)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_moodle.py`

**Interfaces:**
- Consumes: `providers.get("moodle")` returning the registered `MoodleProvider` (contract §C, built in the P1 provider tasks); `store.get_provider_account("moodle")` and `store.get_provider_tokens("moodle")` (existing store accessors, mirroring the Google smoke); `MoodleProvider.set_tokens(tokens)`, `MoodleProvider.get_site_info(token) -> {"userid","sitename","release","functions"}`, `MoodleProvider.fetch_courses(userid)`, `MoodleProvider.fetch_deadlines(now)`, `MoodleProvider.fetch_grades(userid, course_ids)`, `MoodleProvider.fetch_announcements(userid, course_ids)`, `MoodleProvider.fetch_notifications(userid)` (contract §E, built in the P1 fetch tasks); `settings.owner` and `settings.database_url` and `settings.moodle_base_url` (contract §A); the `MoodleAuthError`/`MoodleError` classes from `app.providers.moodle` (contract §C).
- Produces: `app/smoke_moodle.py`, a hand-run live-credential script (never collected by pytest — filename is not `test_*`, imports no fixtures, all live calls stay inside `main()`) that: loads the stored Moodle token (exit 2 with connect + Security-keys instructions if none), validates it via `get_site_info` (PASS shows `sitename` + `release`), then does read-only pulls of courses / deadlines / grades / announcements / notifications, printing counts and never writing anything. Exit 0 = all passed, 1 = a live call failed, 2 = not connected. Import-inert: no top-level network/side effects.

- [ ] **Step 1: Create `app/smoke_moodle.py` — the full script**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_moodle.py`. This mirrors `smoke_google.py`'s `Reporter` + `main()` structure exactly (same exit-code contract, same `r.check(...)` reporting), adapted for Moodle's token-paste connect (there is no OAuth authorize URL — the connect help points at the Moodle Security-keys page):

```python
"""End-to-end smoke test for the live Moodle read-only pipeline (M6).

Drives the REAL MoodleProvider against a live Moodle web-services endpoint
(NC State WolfWare by default) using the stored wstoken, then exercises every
read-only fetch. Unlike the pytest suite (which fakes every provider via
conftest), this makes real authenticated Moodle requests. It performs NO
writes of any kind — Moodle slice-1 is read-only, so this only lists.

Moodle uses a static per-user wstoken (not an OAuth code exchange), so this
runs in two modes:

  * Already connected -- a `provider_accounts` row for 'moodle' exists with a
    token. The script validates it via core_webservice_get_site_info, then
    reads courses / deadlines / grades / announcements / notifications and
    prints counts.
  * Not connected -- prints how to obtain and paste a token (the Security-keys
    page on your Moodle site), then exits 2 (setup needed, not a failure).

Run it by hand once a token is stored (NOT in CI):

    python -m app.smoke_moodle

Exit status: 0 if every leg passed, 1 on a pipeline failure, 2 if Moodle isn't
connected yet (paste a token via POST /api/moodle/connect first).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from . import providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help() -> None:
    print("\nMoodle is not connected yet. To connect end-to-end:")
    print(f"  1. Sign in to your Moodle site ({settings.moodle_base_url}).")
    print("  2. Go to your profile -> Preferences -> Security keys (or")
    print("     '/user/managetoken.php') and copy the 'Moodle mobile web service'")
    print("     token (a 32-character hex string).")
    print("  3. Start the backend and POST the token to the connect endpoint:")
    print("       curl -s -X POST http://localhost:8000/api/moodle/connect \\")
    print("            -H 'Content-Type: application/json' \\")
    print("            -d '{\"token\": \"<your-wstoken>\"}'")
    print("     (or paste it into the Connect Moodle card on the School screen).")
    print("  4. Re-run `python -m app.smoke_moodle` afterwards.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS -- live Moodle read-only pipeline smoke test")
    print(f"  owner={settings.owner!r}  moodle_base_url={settings.moodle_base_url!r}")

    print("\nPreconditions:")
    if not r.check(bool(settings.database_url),
                   "DATABASE_URL configured (the stored token lives in the database)"):
        print("\nAborting: no DATABASE_URL -- there is nowhere for a token to be stored.")
        return 1

    provider = providers.get("moodle")
    if not r.check(provider is not None, "Moodle provider registered"):
        return 1

    account = store.get_provider_account("moodle")
    if account is None:
        r.check(False, "Moodle account connected (provider_accounts row exists)",
                "not connected -- see steps below")
        _print_connect_help()
        return 2
    r.check(True, "Moodle account connected",
            f"status={account['status']} provider_user_id={account.get('provider_user_id')}")

    try:
        print("\n1. Token validity (core_webservice_get_site_info):")
        tokens = store.get_provider_tokens("moodle")
        if not r.check(tokens is not None and bool(tokens.access_token),
                       "wstoken present server-side"):
            return 1
        provider.set_tokens(tokens)
        info = provider.get_site_info(tokens.access_token)
        userid = info.get("userid")
        r.check(bool(info.get("sitename")) and bool(info.get("release")),
                "site info resolved",
                f"sitename={info.get('sitename')!r} release={info.get('release')!r}")
        if not r.check(isinstance(userid, int) and userid > 0,
                       "site info returned a numeric userid", str(userid)):
            return 1

        print("\n2. Courses (core_enrol_get_users_courses):")
        courses = provider.fetch_courses(userid)
        r.check(True, "courses fetched", f"{len(courses)}")
        r.check(bool(courses), "Moodle returned at least one enrolled course")
        course_ids = [c.source_id for c in courses]
        for c in courses[:5]:
            print(f"        - {c.shortname!r} :: {c.fullname!r} "
                  f"(progress={c.progress})")

        print("\n3. Deadline timeline (core_calendar_get_action_events_by_timesort):")
        now = datetime.now(timezone.utc)
        deadlines = provider.fetch_deadlines(now)
        r.check(True, "deadlines fetched", f"{len(deadlines)}")
        for d in deadlines[:5]:
            print(f"        - {d.name!r} ({d.module_name}) due {d.due_at} "
                  f"course={d.course_id}")

        print("\n4. Grades (gradereport_user_get_grade_items, per course):")
        grades = provider.fetch_grades(userid, course_ids)
        r.check(True, "grades fetched", f"{len(grades)}")
        for g in grades[:5]:
            print(f"        - {g.item_name!r} ({g.item_type}) = {g.grade_formatted!r} "
                  f"course={g.course_id}")

        print("\n5. Announcements (mod_forum news forums):")
        announcements = provider.fetch_announcements(userid, course_ids)
        r.check(True, "announcements fetched", f"{len(announcements)}")
        for a in announcements[:5]:
            print(f"        - {a.subject!r} by {a.author!r} at {a.created_at} "
                  f"course={a.course_id}")

        print("\n6. Notifications (message_popup_get_popup_notifications):")
        notifications = provider.fetch_notifications(userid)
        r.check(True, "notifications fetched", f"{len(notifications)}")
        for n in notifications[:5]:
            print(f"        - {n.subject!r} read={n.read} at {n.created_at}")
    except Exception as exc:  # a live call blew up -- report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES -- see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

Note on the read-only guarantee: every provider method called here (`get_site_info`, `fetch_courses`, `fetch_deadlines`, `fetch_grades`, `fetch_announcements`, `fetch_notifications`) is a `core_*`/`mod_*_get_*`/`gradereport_*_get_*` **read** web-service function per contract §E — none submit, post, or mutate Moodle state. The script also writes nothing to the local database (it never calls a `store.upsert_*` or runs a sync tick); it only reads the stored token via `get_provider_tokens`.

- [ ] **Step 2: Verify import-inertness (no top-level network/side effects)**

**Run** (byte-compile / import check — proves nothing at module top level reaches the network; does NOT execute `main()`):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -c "import app.smoke_moodle as s; print('imports ok', callable(s.main))"
```

**Expected:** `imports ok True` with no network calls and no exception (every live call lives inside `main()`, which is not invoked by the import).

- [ ] **Step 3: Run the full backend suite to confirm the module stays inert / uncollected, then commit**

**Run:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
```

**Expected:** the suite is green and the pass count is **unchanged** from the previous task — `smoke_moodle.py` is not collected (its filename is not `test_*` and it imports no test fixtures). Report the count as "X tests passing".

**Commit:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/smoke_moodle.py
git commit -m "$(cat <<'EOF'
test(smoke): add live Moodle read-only smoke test (smoke_moodle.py)

Mirrors smoke_google.py's Reporter + main() and exit-code contract (0 pass /
1 fail / 2 not-connected). Loads the stored wstoken (exit 2 with connect +
Security-keys instructions if none), validates it via
core_webservice_get_site_info (PASS shows sitename + release), then read-only
pulls courses / deadlines / grades / announcements / notifications and prints
counts. No writes of any kind and no import-time side effects -- every live
call stays inside main(), so the pytest suite never collects or runs it.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Expected:** commit succeeds on branch `m6-school-moodle-slice1`.

---

### Task 21: Live validation against real WolfWare Moodle + final gate (manual — no code changes)

**Files:**
- None (verification gate only; no files created or modified except resolving any surviving `[confirm-against-live]` mismatches in `app/providers/moodle.py` under Step 7).

**Interfaces:**
- Consumes: The entire M6 slice-1 merged onto `m6-school-moodle-slice1`: `settings.moodle_base_url` (Task 1), the `NormalizedCourse`/`NormalizedDeadline`/`NormalizedAssignment`/`NormalizedGrade`/`NormalizedAnnouncement`/`NormalizedNotification`/`MoodleSnapshot` dataclasses + `MoodleProvider` protocol (Task 2), the `MoodleProvider` `_call` seam + `parse_pasted_token` + `get_site_info` + all six `fetch_*` methods + `fetch_school_snapshot` (Tasks 3–7), migration `0006_moodle` + the six `moodle_*` models (Task 8), the store moodle section + read-time Calendar/Tasks projectors (Tasks 9–11), `moodle_sync` (Task 12), the schemas + `routers/moodle.py` reads/sync + `POST /api/moodle/connect` (Tasks 13–14), the `get_courses`/`get_deadlines`/`get_grades` assistant tools (Task 15), the `SchoolScreen` + Calendar/Tasks/Home read-only Moodle markers (Tasks 16–18), privacy wave 1 + `docs/school.md` (Task 19), and `app/smoke_moodle.py` (Task 20).
- Produces: A recorded end-to-end live validation of the read-only school path against the real NC State WolfWare instance (`https://moodle-courses2527.wolfware.ncsu.edu`): a valid `wstoken` obtained via the mobile launch flow (or the Security-keys fallback), the local docker Postgres migrated to `0006`, the token pasted and accepted (`moodle` shows connected via `/api/oauth/status` with NO token in the body), every School surface browser-verified against live data, real Moodle deadlines confirmed as read-only "Moodle" items in Calendar / Tasks / Home, `python -m app.smoke_moodle` reporting `RESULT: ALL PASSED (read-only)`, every `[confirm-against-live]` marker in `app/providers/moodle.py` resolved against the real responses, and the full backend suite + frontend build reported green. This is a manual verification gate — no code changes beyond resolving `[confirm-against-live]` mismatches (Step 7).

- [ ] **Step 1: Obtain a WolfWare `wstoken` (mobile launch flow, with an always-works fallback)**

Manual browser step — no automated assertion (the gate is the connect in Step 3 succeeding). WolfWare is Shibboleth SSO (`typeoflogin=3`), so the plain `login/token.php?username=&password=` endpoint does NOT work — do not attempt it. Use one of the two flows below.

**Preferred — mobile launch flow (yields the real mobile-app token):**

1. Generate a random passport (any float works; the launch flow only uses it to sign the returned token blob). In a terminal:
   ```bash
   /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -c "import random; print(random.random())"
   ```
   Copy the printed value (e.g. `0.8134729…`) — this is `<rand>` below.
2. In a browser, open the launch URL (substitute `<rand>`):
   ```
   https://moodle-courses2527.wolfware.ncsu.edu/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=<rand>&urlscheme=moodlemobile
   ```
3. Complete the **Shibboleth SSO** login (Unity ID + password + Duo/2FA). On success Moodle attempts to redirect to a custom scheme URL of the form `moodlemobile://token=<base64blob>` — the browser will block the redirect (no app registered for `moodlemobile://`) and show an error, which is expected.
4. Open **devtools → Network** (or the browser's "blocked redirect" details) and copy the full `moodlemobile://token=…` URL. Paste that ENTIRE string into the SchoolScreen field in Step 3 — `parse_pasted_token` (contract §D) base64-decodes it, splits on `:::`, verifies the `md5(wwwroot+passport)` prefix when a passport is supplied, and extracts the bare `wstoken`.

   **SSO gotcha (frozen note):** `login/token.php` does NOT work for WolfWare because the identity provider is Shibboleth (`typeoflogin=3`); only the `admin/tool/mobile/launch.php` flow (or the Security-keys fallback below) yields a usable service token.

**Always-works fallback — Security keys page (yields a bare 32-hex token):**

1. Log in normally at `https://moodle-courses2527.wolfware.ncsu.edu` via Shibboleth SSO.
2. Go to **user menu → Preferences → Security keys** (labeled "Security keys" / "Manage mobile web service tokens" on this Moodle release).
3. Copy the **Moodle mobile web service** token — a bare 32-hex string. Paste it directly into the SchoolScreen field in Step 3; `parse_pasted_token` returns a bare 32-hex string as-is (no passport needed).

**Expected:** you hold either a `moodlemobile://token=…` launch URL OR a bare 32-hex `wstoken`. Do not paste it anywhere yet — the backend is not running until Step 2.

- [ ] **Step 2: Migrate the local docker Postgres to head (0006), then start the backend on :8000 against WolfWare**

The local docker Postgres (`pgvector/pgvector:pg17` on port 5433, per `backend/.env.example`) is already migrated through 0005 from prior milestones. Apply the Moodle migration:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
DATABASE_URL=postgresql://scuffed:scuffed@localhost:5433/scuffedos /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m alembic upgrade head
```

**Expected:** alembic reports the upgrade `0005 -> 0006` applied cleanly, creating the six `moodle_*` tables. (If email slice-2's `0006_email_actions` merged to `main` first, this branch's migration must have already been renumbered to `0007_moodle` with `down_revision="0006"` during the rebase — see the pre-PR checklist at the end of this task; in that case alembic reports `0006 -> 0007` instead. Either way `upgrade head` must apply with no multi-head error.)

Then start the backend on port 8000 against that same database, with `settings.moodle_base_url` pointing at WolfWare (it already defaults to `https://moodle-courses2527.wolfware.ncsu.edu` per contract §A, so no override is required — pass it explicitly only if your local `.env` overrides it):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
DATABASE_URL=postgresql://scuffed:scuffed@localhost:5433/scuffedos \
MOODLE_BASE_URL=https://moodle-courses2527.wolfware.ncsu.edu \
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Expected:** server starts with no startup errors; the `moodle_sync.run_loop()` background task launches behind `settings.moodle_sync_enabled` with no crash. Leave this running. In a second terminal, start the frontend:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend
npm run dev
```

**Expected:** Vite dev server comes up on `http://localhost:5173` with no build errors.

- [ ] **Step 3: Paste the token into the Connect Moodle card, then confirm `moodle` connected via `/api/oauth/status`**

In the browser, open `http://localhost:5173`, go to the **School** screen. Because no `moodle` provider account exists yet, the SchoolScreen renders the **Connect Moodle card** (contract §L) with a paste field and the Security-keys instructions.

1. Paste the token from Step 1 (either the full `moodlemobile://token=…` launch URL or the bare 32-hex string) into the field.
2. Click **Connect**. This calls `api.moodleConnect({token})` → `POST /api/moodle/connect`, which runs `parse_pasted_token` → `provider.get_site_info(wstoken)` (validating the token against live WolfWare) → `store.upsert_provider_account("moodle", Tokens(access_token=wstoken, …, provider_user_id=str(userid), meta={…}))` → `moodle_sync.tick()` → returns `OAuthStatus`.

**Expected:** the card transitions to the connected/syncing state (no "Moodle rejected the token" 502 banner — a 502 means the token is invalid or the SSO flow returned a scope-less blob; repeat Step 1). Then confirm via the API that the account is connected and NO token is serialized to the client:

```bash
curl -s http://localhost:8000/api/oauth/status | python3 -m json.tool
```

**Expected:** the `moodle` entry in `providers` has `"status": "connected"` and its `provider_user_id` set (the Moodle `userid` as a string). Confirm the body contains ONLY the safe keys per contract's frozen privacy rule — **assert by eye that `access_token`, `refresh_token`, `scopes`, `wstoken`, and `meta` are ABSENT** from every provider entry (`_provider_account_dict` emits only its safe keys; the token lives server-side only).

- [ ] **Step 4: Browser-verify the School screen renders real WolfWare data**

Drive the live SchoolScreen and confirm each surface populates from real Moodle (the reads are served from the DB after the connect-time `moodle_sync.tick()`; trigger a fresh sync if needed via the sync affordance or `curl -s -X POST http://localhost:8000/api/moodle/sync`):

1. **Courses** (left column): your real enrolled WolfWare courses render with shortnames/fullnames (and progress where Moodle reports it).
2. **Deadlines timeline** (right): real upcoming assignment/quiz due dates render in due-date order with human-readable `when` strings — cross-check a couple against the actual Moodle "Timeline" block dates.
3. **Grades:** current grade items render with their formatted display strings (HTML entities stripped).
4. **Announcements:** recent course news/announcement subjects + authors render (HTML summaries stripped for display).
5. **Notifications:** recent Moodle notifications render with read/unread state.

**Expected:** every panel shows real data with no error state and no raw HTML leaking into the display. No automated assertion — this is a human-observed browser pass. (If a panel is empty because your account genuinely has no data of that kind, note it as "empty (no live data)" rather than a failure — the contract requires missing optional features to degrade to an empty list, never crash.)

- [ ] **Step 5: Verify real Moodle deadlines appear as read-only "Moodle" items in Calendar, Tasks, and Home — and cannot be edited**

The Calendar/Tasks/Home feeds merge Moodle deadlines at read time (contract §H/§M) — they are NOT physical `tasks`/`events` rows, so they must render read-only with a "Moodle" chip and no edit/delete/toggle affordances.

1. **Calendar:** open the **Calendar** screen and navigate to a date range covering a known Moodle deadline. Confirm the deadline appears as an event titled `<name> · <course shortname>` with the grape tint and a small **"Moodle"** chip; confirm there is NO edit/delete affordance on it, and that clicking it does not open an editable editor.
2. **Tasks:** open the **Tasks** screen. Confirm each Moodle assignment with a due date appears in the **School** group/list as a task labeled `<name> · <course shortname>` with a "Moodle" chip; confirm the done-toggle/checkbox is disabled or absent (a submitted/reopened assignment shows as done, read-only) and there is no edit/delete affordance.
3. **Home agenda:** open the **Home** screen. Confirm today's/upcoming Moodle deadlines surface in the agenda with the "Moodle" marker and no edit affordance.
4. **Mutation is server-blocked:** confirm a Moodle-projected id is a string (`"moodle:<n>"`) — attempting any calendar/tasks mutation endpoint against such an id must 422 server-side (the mutation routes take `int` path ids), so no client guard is trusted alone. Optionally sanity-check:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "http://localhost:8000/api/tasks/moodle:123"
   ```
   **Expected:** `422` (FastAPI path-type validation rejects the string id) — never `200`/`204`.

**Expected:** Moodle deadlines are visible in all three surfaces, clearly marked, and provably non-mutable. No automated assertion beyond the optional 422 check — this is a human-observed browser pass.

- [ ] **Step 6: Run `python -m app.smoke_moodle` for a consolidated read-only live pass**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
DATABASE_URL=postgresql://scuffed:scuffed@localhost:5433/scuffedos \
MOODLE_BASE_URL=https://moodle-courses2527.wolfware.ncsu.edu \
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m app.smoke_moodle; echo "exit=$?"
```

**Expected:** `exit=0` with `RESULT: ALL PASSED (read-only)` printed — the smoke script (Task 20) exercises `get_site_info` + each `fetch_*` against live WolfWare using the stored token and confirms it makes NO write calls of any kind (read-only slice). If it prints any `[FAIL]` line, the slice is NOT complete — resolve it (most commonly a `[confirm-against-live]` field-path mismatch, handled in Step 7) and re-run.

- [ ] **Step 7: Resolve every `[confirm-against-live]` marker in `app/providers/moodle.py` against the real responses**

The frozen contract flags every Moodle endpoint path, `wsfunction` name, param name, and JSON field path in `moodle.py` as `[confirm-against-live]` — the constant NAMES are frozen, but the VALUES/field-paths were derived against a Moodle 5.2 demo and must be reconciled against the real WolfWare responses.

1. Search the provider for the markers:
   ```bash
   grep -n "confirm-against-live" /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/moodle.py
   ```
2. For each marker, compare the coded value/JSON-path against the live response observed during Steps 4–6 (the running backend logs the raw `_call` responses at debug; or hit the WS directly, e.g.):
   ```bash
   curl -s "https://moodle-courses2527.wolfware.ncsu.edu/webservice/rest/server.php" \
     --data-urlencode "wstoken=<WSTOKEN>" \
     --data-urlencode "wsfunction=core_webservice_get_site_info" \
     --data-urlencode "moodlewsrestformat=json" | python3 -m json.tool
   ```
   Repeat with each `wsfunction` (`core_enrol_get_users_courses`, `core_calendar_get_action_events_by_timesort`, `mod_assign_get_assignments`, `mod_assign_get_submission_status`, `gradereport_user_get_grade_items`, `mod_forum_get_forums_by_courses`, `mod_forum_get_forum_discussions`, `message_popup_get_popup_notifications`) and confirm every param name and every JSON field the mapper reads (`timesort`, `viewurl`, `usergrades[].gradeitems[]`, `type=='news'`, `notifications[]`, etc.) matches the live payload.
3. **Fix any mismatch in `app/providers/moodle.py` only** (values/field-paths — NEVER rename a frozen constant or change a method signature). If you change any mapping, re-run the affected `tests/test_moodle_*` unit tests and update their fake-JSON fixtures to match the real shape, then re-run the FULL suite (Step 8). If NO marker needed a change, note "all `[confirm-against-live]` markers matched live — no code change."

**Expected:** zero surviving unreconciled `[confirm-against-live]` markers; the grep output is reviewed line-by-line and every value/field-path is confirmed against a real WolfWare response.

- [ ] **Step 8: Full backend suite green + frontend build green, then report counts**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
```

**Expected:** all tests pass (0 failures, 0 errors). Report the exact printed count as "X tests passing" — confirm it is at least the Global Constraints baseline (`N passed, 1 skipped`, the 1 skip = the Postgres-only migration drift test) plus every new slice-1 test from Tasks 2–20 (the six normalized dataclasses, the provider `_call`/`parse_pasted_token`/`get_site_info`/`fetch_*` tests, migration `0006` + the six models, the store moodle section + Calendar/Tasks read-time-merge tests, the schema-widening tests asserting `id: int | str` + `source`/`editable`, `moodle_sync`, the router reads/sync/connect tests, and the assistant registration test asserting NO Moodle write tools exist).

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend
npm run build
```

**Expected:** the Vite production build completes with no errors (report any warnings, but they must not be new errors — the frontend has no test harness, so `npm run build` IS the frontend gate).

**No git commit for this task** — Steps 1–6 are manual/live actions, Step 7 touches source ONLY if a live mismatch is found (commit any such fix under its own `feat(school):`/`test(school):` scope as part of that step's normal TDD loop, not as a "gate commit"), and Step 8 is a verification gate.

**Pre-PR checklist (restate before opening the PR from `m6-school-moodle-slice1`):**

1. **MIGRATION-NUMBER REBASE HAZARD (user-decided 2026-07-03):** this branch's migration is `0006_moodle` (`down_revision="0005"`). The unmerged `m5-email-slice2` branch ALSO introduces a `0006_email_actions`. **If email slice-2 merged to `main` before this branch, you MUST renumber this migration to `0007_moodle` with `down_revision="0006"` (the email revision id) during the rebase** — two revisions sharing id `0006` is an Alembic multi-head that breaks `upgrade head`. After renumbering, re-run Step 2's `alembic upgrade head` (now `0006 -> 0007`) and re-run the full suite. If email slice-2 has NOT merged, leave it `0006_moodle`.
2. Confirm Step 3's `/api/oauth/status` check held: NO tokens/scopes/meta serialized to the client.
3. Confirm the `smoke_moodle` pass (Step 6) and the full suite + frontend build (Step 8) are green on the final rebased tree.
4. Privacy gist push (Task 19) is a **user-approval step** — confirm the user has performed (or explicitly deferred) the gist sync before merge; the agent does not push the gist.

If anything is red at Step 6, 7, or 8, the slice is NOT complete — fix before considering the work done. Once green (and the migration renumbering hazard is resolved per the checklist), the branch `m6-school-moodle-slice1` is ready to open a PR.
