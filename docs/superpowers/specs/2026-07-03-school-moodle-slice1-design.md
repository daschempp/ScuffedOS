# M6 School Slice-1 — "Glance at school": Moodle read + Calendar/Tasks feeds

**Status:** user-approved design (brainstormed 2026-07-03). Implementation plan to follow via writing-plans.
**Depends on:** nothing in M5 email; branches from `main`. (Roadmap renumber: School = **M6**, Plaid finance → M7, Ship/Tauri → M8 — user-approved 2026-07-03.)
**Branch:** `m6-school-moodle-slice1`.
**Owner:** Dylan Schempp.
**Target instance:** NC State WolfWare — `https://moodle-courses2527.wolfware.ncsu.edu` (Moodle web services + mobile service confirmed enabled; `typeoflogin: 3`, Shibboleth SSO — see §4).
**Supersedes:** the "planned" School sketch — none exists yet; this milestone is net-new. Adds `docs/school.md` + `docs/README.md` row.

## 1. Goal

Add a **School** section that reads the user's Moodle courses and surfaces the daily-glance data a student
actually checks: upcoming assignment/quiz due dates (Moodle's "Timeline"), current grades, course
announcements, and notifications — and threads those due dates into the existing **Calendar** and **Tasks**
sections so school deadlines live alongside everything else. All read-only. This is slice 1 of a 3-slice
program whose end state replaces day-to-day use of the Moodle web UI, including submitting assignments.

## 2. Program roadmap (user-approved decomposition — read-first, submit-last)

| Slice | Name | Scope |
|---|---|---|
| **1 (this spec)** | Glance at school | Connect flow + token storage (SSO-compatible, §4); sync courses, deadline timeline, assignments (metadata + submission status), grades, announcements, notifications; School screen (course list + deadlines + grades + announcements panes); **feeds Calendar + Tasks**; read assistant tools; privacy wave 1; migration `0007_moodle` |
| 2 | Course content | Live (unsynced) course-content browsing: sections → modules → files (token-appended file links); assignment **detail** view (intro HTML, due/cutoff dates, submission status, attempt info); open-in-Moodle deep links |
| 3 | Submit assignments | Upload file(s) → Moodle draft file area → `mod_assign_save_submission` → `mod_assign_submit_for_grading`; confirm-first; submit UI on the assignment detail view; `can_submit` capability gate; privacy wave 2 (write actions) |

Explicitly deferred beyond slice 1: any Moodle **write** (submit, forum post, message send, mark-complete);
course-content persistence (content is live-fetched from slice 2 on); quizzes-taking; messaging/replies;
multi-instance (one Moodle site v1); autonomous assistant writes.

## 3. Architecture (hybrid — user-approved)

Clones the M5 Gmail integration groove: **provider → registry → shared OAuth router → sync loop → store →
domain router → screen**. Split matches the user's hybrid choice:

- **Synced to Postgres (daily-glance, survives Moodle downtime, feeds Calendar/Tasks):** courses, deadline
  timeline, assignment metadata + per-assignment submission status, grades, announcements, notifications.
- **Fetched live on demand (never stored):** course content trees + files (slice 2), assignment intro/detail
  bodies, file bytes.

Module layout (all new unless noted):

- `backend/app/providers/moodle.py` — hand-rolled `httpx` client (no vendor SDK, repo rule). All Moodle
  endpoint/field names confined here; downstream speaks normalized dataclasses. `configure(fake_http=)` test
  seam + lazy `httpx.Client(timeout=20.0)`. `MoodleAuthError(AuthError)`. `logging.getLogger("scuffed_os.moodle")`.
- `backend/app/providers/base.py` (modify) — add `NormalizedCourse`, `NormalizedDeadline`,
  `NormalizedAssignment`, `NormalizedGrade`, `NormalizedAnnouncement`, `NormalizedNotification` dataclasses
  (aware-UTC datetimes; `source`/`source_id` fields) and a `MoodleProvider` protocol (extends `OAuthProvider`;
  distinguishing method `fetch_school_snapshot` used by the sync `hasattr` filter).
- `backend/app/providers/__init__.py` (modify) — register `MoodleProvider()` in `_build_real` try/except.
- `backend/app/moodle_sync.py` — clone of `email_sync.py`: `configure()` seam, `tick()` (never crashes;
  `except AuthError` → `set_provider_status("moodle","needs_reauth")`; DATABASE_URL `RuntimeError` → no-op),
  `trigger()`, `run_loop()` gated by `settings.moodle_sync_enabled`.
- `backend/app/models.py` (modify) + `backend/alembic/versions/0007_moodle.py` — new tables (§6).
- `backend/app/store.py` (modify) — `# ---- moodle ----` section (§6).
- `backend/app/routers/moodle.py` — `APIRouter(prefix="/api/moodle")`, reads from store only (§7).
- `backend/app/schemas.py` (modify) — Moodle response models.
- `backend/app/main.py` (modify) — `include_router`; lifespan sync loop behind the flag.
- `backend/app/config.py` + `backend/.env.example` (modify) — settings (§4/§5).
- `backend/app/tools.py` (modify) — read assistant tools + deep-link card (§10).
- `frontend/src/screens/SchoolScreen.jsx` + `api.js`/`App.jsx`/`Sidebar.jsx`/`Icon.jsx` (modify) — §9.
- Cross-feeds: Calendar + Tasks **read-endpoint** merge + shared-hook/UI markers (§8) — no schema change to
  `tasks`/`events`.

Reads never depend on a live Moodle call; the synced tables *are* the cache (no separate caching layer, no
rate limiting — the sync tick is the only scheduled caller). Sync ticks never crash.

## 4. Auth — SSO token acquisition (frozen decision)

Moodle web services authenticate with a **static `wstoken`** (query/POST param), not OAuth2. The target
instance is **`typeoflogin: 3` (embedded-browser SSO) with a Shibboleth identity provider**, so
`/login/token.php` with username/password is unavailable (returns `invalidlogin` for SSO accounts). The
connect flow therefore obtains the token through the browser, then stores it:

**Primary flow — launch + paste-back:**
1. School screen "Connect Moodle" card → button opens Moodle's
   `…/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=<random>&urlscheme=<scheme>` in the
   user's browser (the `launchurl` from `tool_mobile_get_public_config`).
2. User completes NC State Shibboleth SSO in that tab.
3. Moodle redirects to `<scheme>://token=<base64>` where
   `base64 = base64(md5(wwwroot + passport) + ":::" + token [+ ":::" + privatetoken])`. Because we are not a
   registered mobile app, the redirect will not be intercepted; the screen shows a **paste field**. The user
   pastes either the raw `token=` value (from browser devtools / the failed-redirect address bar) **or** the
   token copied from **Preferences → Security keys** (`/user/managetoken.php`). The backend accepts both:
   a bare 32-hex token, or the `<scheme>://token=<base64>` URL which it base64-decodes and validates the
   `md5(wwwroot+passport)` prefix against the passport it issued.

**Always-works fallback — manual token:** the connect card documents "log in to Moodle in your browser →
Preferences → Security keys → copy the *Moodle mobile web service* token → paste here."

**Validation on connect:** backend calls `core_webservice_get_site_info` with the pasted token; on success
it stores `userid`, `sitename`, `release`, and the `functions[]` allowlist (drives feature-detection, §11),
and marks the account connected. On failure (`invalidtoken`) the card shows an inline error and stores
nothing.

**Storage:** the existing `ProviderAccount` row (`models.py`) — `provider="moodle"`, `access_token=<wstoken>`,
`refresh_token=None`, `expires_at=None` (Moodle tokens are long-lived, site default ~12 weeks; no refresh
endpoint). Tokens/scopes are **never serialized to the client** — only derived booleans. Token expiry
surfaces as `invalidtoken` on the next sync tick → `MoodleAuthError` → `needs_reauth` → a "Reconnect Moodle"
banner (reuses the email re-auth machinery). `settings.moodle_base_url` is the one required config value;
the connect passport/scheme handling lives in the provider.

**OAuth router reuse:** connect/status/disconnect ride the existing `/api/oauth/*` + `/auth/*` router once
`MoodleProvider` implements the protocol hooks. Because token entry is a paste (not a redirect code
exchange), the provider adds a thin `POST /api/moodle/connect {token}` endpoint that does the site-info
validation + `upsert_provider_account` + kicks `moodle_sync.tick()`; disconnect uses the standard
`POST /api/oauth/disconnect/moodle` → `delete_moodle_data("moodle")`.

## 5. Settings + `.env.example`

```
# ---- M6 School (Moodle) ----
moodle_base_url: str = "https://moodle-courses2527.wolfware.ncsu.edu"   # site wwwroot, no trailing slash
moodle_sync_enabled: bool = True
moodle_sync_seconds: int = 900          # 15 min; gentle — mobile app-level cadence
moodle_backfill_days_ahead: int = 60    # deadline timeline horizon
```

No client secret (token-based). `moodle_base_url` documented in `.env.example` under an M6 section.

## 6. Data model + store (migration `0007_moodle`)

All tables carry `owner` (default `settings.owner`), aware-UTC `DateTime(timezone=True)` with Python-side
`default=utcnow`, `JSONField = JSON().with_variant(JSONB(), "postgresql")`, and a unique constraint on
`(owner, source, source_id)` where `source="moodle"`. Idempotent upserts (metadata every pass). No HTML
bodies or file bytes stored — HTML summaries stored are short (course/announcement) and treated as display
text; assignment/detail bodies are live-only (slice 2).

| Table | Key columns | Source function |
|---|---|---|
| `moodle_courses` | `source_id`(=course id), `shortname`, `fullname`, `progress`, `startdate`, `enddate`, `last_access`, `hidden`, `meta` | `core_enrol_get_users_courses` |
| `moodle_deadlines` | `source_id`(=event id), `course_id`, `name`, `modulename`, `event_type`, `timesort`(due, UTC), `overdue`, `view_url`, `meta` | `core_calendar_get_action_events_by_timesort` |
| `moodle_assignments` | `source_id`(=assign id), `course_id`, `cmid`, `name`, `duedate`, `cutoffdate`, `grade_max`, `submission_status`(new/draft/submitted/reopened), `grading_status`, `graded`(bool), `meta` | `mod_assign_get_assignments` + `mod_assign_get_submission_status` |
| `moodle_grades` | `source_id`(=grade item id), `course_id`, `item_name`, `item_type`, `grade_formatted`, `grade_raw`, `grade_min`, `grade_max`, `graded_at`, `meta` | `gradereport_user_get_grade_items` |
| `moodle_announcements` | `source_id`(=discussion id), `course_id`, `forum_id`, `subject`, `author`, `created`(UTC), `summary_html`, `view_url`, `meta` | `mod_forum_get_forums_by_courses`(type="news") + `mod_forum_get_forum_discussions` |
| `moodle_notifications` | `source_id`(=notification id), `subject`, `full_message`, `contexturl`, `created`(UTC), `read`(bool), `meta` | `message_popup_get_popup_notifications` |

Store: `# ---- moodle ----` section — `_moodle_<x>_row` finders, `_<x>_dict` serializers, idempotent
`upsert_moodle_*`, read methods (`school_snapshot()`, `deadlines(window)`, `grades()`, `announcements()`,
`notifications()`), the two **read-time projectors** for §8 (`moodle_calendar_events(window)`,
`moodle_tasks()`), and `delete_moodle_data(source)` for disconnect. Client-safe `_provider_account_dict`
gains no Moodle-specific fields beyond the standard derived booleans. Migration `0007_moodle` **only creates
the six new tables — it does not alter `tasks`/`events`** (§8 merges at read time). Add all six table names
to `tests/test_migrations.py` `ALL_TABLES`.

## 7. Moodle API surface (`routers/moodle.py`)

```
POST /api/moodle/connect        {token}                 -> ProviderStatus   # validate + store + kick sync (§4)
GET  /api/moodle/courses                                -> [CourseOut]
GET  /api/moodle/deadlines      ?days=60                -> [DeadlineOut]     # from synced timeline
GET  /api/moodle/grades         ?course_id=             -> [GradeOut]
GET  /api/moodle/announcements  ?course_id=             -> [AnnouncementOut]
GET  /api/moodle/notifications                          -> [NotificationOut]
POST /api/moodle/sync                                   -> {synced_at}       # delegates to moodle_sync.tick()
```

All reads come from the DB only. Connect/status/disconnect otherwise via `/api/oauth/*`. Provider methods
looked up defensively via `getattr(impl, "…", None)`; any live provider failure inside `/connect` →
`HTTPException(502, "Moodle rejected the request")`. Error envelope via plain `HTTPException`.

## 8. Calendar + Tasks feeds (user-approved "feed both") — read-time merge

Moodle deadlines appear in the existing **Calendar** and **Tasks** sections so school lives alongside
everything else. **Frozen decision — virtual projection, not physical rows.** The existing M3 `tasks` and
`events` tables have integer PKs and *no `source` column* and are mutated by established M3 routers +
recurrence/reminder machinery. Rather than alter those two core tables and guard every existing mutation
endpoint against foreign rows (large, error-prone blast radius), Moodle keeps a **single home** (the
`moodle_*` tables) and is **merged in at read time**:

- New store projectors map synced Moodle rows into the *output shape* of Calendar events / Tasks:
  `store.moodle_calendar_events(window)` (from `moodle_deadlines`, one event at `timesort`, titled
  `"<assignment> — <course shortname>"`) and `store.moodle_tasks()` (from `moodle_assignments` with a future
  `duedate`; `done` mirrors submission status `submitted`/`reopened`). Each projected item carries
  `source:"moodle"`, a namespaced `id:"moodle:<source_id>"`, `editable:false`, and a deep link to the School
  screen.
- The **Calendar and Tasks read endpoints** concatenate these projected items into their responses. The
  `useCalendar`/`useTasks` shared hooks then surface them on **Home's agenda too** (desirable — school
  deadlines on the dashboard). The frontend renders `source:"moodle"` items with a subtle "Moodle" marker
  and **no edit/delete/toggle affordances**.
- **Writes are inherently safe:** existing mutation endpoints look up by integer PK, so a namespaced
  `"moodle:123"` id simply isn't found — foreign rows can't be edited, completed, or deleted through
  Calendar/Tasks. No new guards needed. (Submitting is slice 3; until then these are view-only.)
- **No new sync/reconcile logic and no schema change to `tasks`/`events`.** Disconnect deletes the
  `moodle_*` rows (§6) and the projections vanish from the merged views automatically.

Direction is **Moodle → Calendar/Tasks only** (one-way, read-time); editing in Calendar/Tasks never writes
back to Moodle.

## 9. Frontend — School screen + registration

- **Registration:** `graduation-cap` lucide icon in `lib/Icon.jsx`; `{id:'school', label:'School',
  icon:'graduation-cap'}` in `shell/Sidebar.jsx`; `school:{title:'School', sub:'Courses, deadlines & grades'}`
  in `App.jsx` `SCREENS`; `else if (screen==='school') body=<SchoolScreen/>` branch; `api.js` `school*` method
  block.
- **`screens/SchoolScreen.jsx`** (self-owned state, clones EmailScreen structure + render-state ladder):
  1. **Not-connected** card — "Connect Moodle": passport-launch button + paste field + the Security-keys
     fallback instructions (§4).
  2. **needs-reauth** banner — "Reconnect Moodle" (token expired/invalid).
  3. **syncing** first-backfill card ("Fetching your courses…", Check-again).
  4. **Main layout** (`kit-grid`): left = **course list** (`kit-mail`-style selectable rows, progress);
     right column = **Upcoming deadlines** timeline (grouped Today/This week/Later, overdue tinted),
     **Grades** pane (per selected course, course-total highlighted), **Announcements** feed (per course,
     HTML summary sanitized/stripped for display), and a **Notifications** strip. Empty/loading fallbacks per
     pane. Manual **Sync** button in the header (`POST /api/moodle/sync` → refresh).
  - No polling; `refresh` on mount + after Sync (`.catch(()=>{})` so a down backend keeps the UI).
  - HTML from Moodle (summaries, announcements) is **stripped/sanitized** before render (no `dangerouslySet…`
    of raw Moodle HTML in v1; plain-text/limited rendering).
- **No frontend tests exist**; verify with `npm run build`. Reuse `ui.jsx` primitives + `kit-*`/`sa-*`
  classes + design tokens (no hardcoded colors, no new deps).

## 10. Assistant (chat) stance — read tools only

New read tools in `app/tools.py`: `get_courses`, `get_deadlines` (upcoming, windowed), `get_grades`
(optionally per course), each returning data + a deep-link action card (`"screen":"school"`). **No write
tools this slice** — submitting an assignment (slice 3) will be **user-initiated only**; the assistant will
never submit coursework autonomously. Tools registered with tests mirroring `test_email_tools.py`.

## 11. Feature detection + version notes

On connect, `core_webservice_get_site_info.functions[]` is stored as the authoritative per-token allowlist.
The sync tick checks presence before calling optional functions and degrades gracefully (a missing feature
yields an empty pane, never a crash). Version gates to guard: timeline API (`core_calendar_get_action_events_by_timesort`, 3.3+),
`mod_forum_get_forum_discussions` (3.7+; older sites use `_paginated`), notifications
(`message_popup_get_popup_notifications`, 3.2+). The target instance is Moodle 4.x/5.x (modern), so all are
expected present; feature-detect anyway rather than version-sniff. Endpoint/param constants in `moodle.py`
carry `[confirm-against-live]` markers resolved in the live gate.

## 12. Privacy policy wave 1 (all three copies)

New "If you choose to connect Moodle" disclosure across canonical `docs/privacy-policy.md` (§1 connected-
service data, §3 provider table row, §4 per-integration block, §6 retention), corp
`scuffed-corporation/privacy/index.html`, and the gist (gist sync is a **user-approval action**). Content:
explicit-consent connection via a token the user provides; what is **stored** (course names, due dates,
assignment/grade metadata, announcement/notification text) vs **fetched live and not stored** (course files,
assignment bodies); that deadline data is projected into Calendar/Tasks locally; that **no data is sent to
Anthropic except** when the user asks the assistant about school (then the relevant snapshot transits, not
stored beyond the reply); disconnect deletes all Moodle data within 30 days; "not affiliated with Moodle or
NC State." Effective-date bump.

## 13. Testing + validation

- TDD per task; full suite stays green (**baseline 427 passed / 1 skipped**); M4 fitness + M5 email guardrails
  intact; frontend `npm run build` green. Report pass count after changes (user rule).
- **Fakes** (`tests/fakes.py`): `FakeMoodleHTTP` (transport-level — scriptable `wsfunction`→JSON routing by
  param, records calls, `status`/`exception` injection to exercise error handling and the HTTP-200-with-
  `exception` convention) drives the **real** `MoodleProvider` parsing/auth; `FakeMoodleProvider` (protocol-
  level) drives sync/router logic. `gmail_message()`-style builders for course/deadline/grade payloads.
- **conftest:** add `moodle_sync.configure(None)` to `no_external_services` (setup + teardown) so no test
  reaches the network.
- **Test files:** `test_moodle_{config,models,store,sync,api,provider,tools}.py`; provider tests cover token
  paste-back parsing (bare hex + `scheme://token=base64` decode + passport md5 validation), the HTTP-200
  exception convention, PHP-array param flattening, HTML-strip, epoch→UTC conversion; Calendar/Tasks
  **read-merge** tests (projectors emit `source:"moodle"` + namespaced ids; existing mutation endpoints 404
  on a `"moodle:<id>"` id and never mutate a `moodle_*` row). Migration parity via `test_migrations.py`.
- **Live smoke** `app/smoke_moodle.py` (Reporter pattern, exit 0/1/2, not in CI): connect with a real token
  → `get_site_info` → pull courses/deadlines/grades/announcements → print counts; read-only (no writes this
  slice).
- **Live gate (final task, no code):** user connects the real WolfWare instance (launch-flow or Security-keys
  token), verifies courses/deadlines/grades/announcements render, and that deadlines appear in Calendar +
  Tasks; resolve `[confirm-against-live]` endpoint markers.

## 14. Out of scope (this slice)

Any Moodle write (submit, post, message, mark-complete), course-content/file persistence, live content
browsing + assignment detail view (slice 2), assignment submission (slice 3), quizzes, messaging/replies,
multiple Moodle instances, calendar/tasks → Moodle write-back, autonomous assistant writes, rich HTML
rendering of Moodle content — assigned to slices 2/3 or explicitly dropped per §2.
