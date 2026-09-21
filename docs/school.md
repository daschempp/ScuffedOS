# School (Moodle) — Architecture

> Status: **implemented** (M6 slice-1) · Last updated: 2026-09-17 · Owner: _Dylan_
>
> Part of the [backend overview](backend-overview.md). A read-only view of the student's
> Moodle learning-management data — courses, deadlines, grades, and announcements — that
> also feeds assignment due dates into the existing Calendar and Tasks.

## Responsibility

Connect to a Moodle instance (NC State's WolfWare, `moodle-courses2527.wolfware.ncsu.edu`)
by signing in through the browser (or, as a fallback, a pasted access token), **sync** the
student's courses, deadline timeline, assignments (+ submission status), grades,
announcements, and notifications into Postgres, and serve them to a `SchoolScreen`. Project
assignment deadlines into the Calendar/Tasks output at read time so they appear on
Home/Calendar/Tasks as **read-only** markers.

## Surface / current state

M6 slice-1 is implemented. The screen is served from the DB — every `/api/moodle/*` GET
reads stored rows; only the two connect paths (validate the token) and
`POST /api/moodle/sync` (the tick) reach Moodle.

**Browser sign-in.** WolfWare is Shibboleth SSO, so there is no username/password token
endpoint. `GET /api/oauth/connect/moodle` issues a one-time state and returns Moodle's
mobile-app launch URL carrying it as the `passport`
(`/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=…&urlscheme=scuffedos`),
which the app opens in the system browser. Once the user signs in, Moodle redirects to
`<scheme>://token=<blob>`, where `<scheme>` is `scuffedos` when the site honors the
requested `urlscheme` or `moodlemobile` (the official app's scheme, which Moodle's
`tool_mobile/forcedurlscheme` setting forces by default) — the shell registers and
accepts both — and `blob = base64(md5(wwwroot + passport) ':::' wstoken [':::'
privatetoken])`; the Tauri shell catches that deep link and replays the blob once to
`POST /auth/moodle/launch` as a JSON body, `{"token": "<blob>"}`. The blob carries the
wstoken, so it travels in the body and never the URL — a query string would land in
uvicorn's access log and from there in the sidecar's stderr drain. That endpoint finds
the pending sign-in whose `md5(wwwroot + passport)` matches the blob's signature (the
site root is compared trailing-slash-normalized, as Moodle signs with its own unslashed
`$CFG->wwwroot`), burns it (single-use, success or failure), validates the token with
`core_webservice_get_site_info`, persists it exactly as the paste flow does, and renders
the same inline success/error page. A blob matching no pending sign-in persists nothing
and leaves pending sign-ins untouched. Pasting a token remains as a manual fallback.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/oauth/connect/moodle` | Issue a passport and return the Moodle sign-in URL. |
| `POST` | `/auth/moodle/launch` | Browser sign-in callback (JSON body from the desktop shell): verify the passport, store the `wstoken`, kick a first sync. |
| `POST` | `/api/moodle/connect` | Fallback: validate a pasted `wstoken`, store it, kick a first sync. |
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

- **OAuth plumbing (shared).** Reuses the `/api/oauth/status` + disconnect surface and the
  shared one-time state store (`oauth._STATES`, matched by signature via
  `_consume_state_where`) plus the inline callback pages. There is no code exchange — Moodle
  uses a static `wstoken` — so the launch callback stands in for `/auth/{provider}/callback`.
- **School → Calendar / Tasks.** Assignment deadlines are projected read-time into
  `store.events_between()` / `store.list_tasks()` output (tagged `source="moodle"`,
  `editable=False`) — no rows are copied into the `events`/`tasks` tables. See
  [calendar.md](calendar.md) and [tasks.md](tasks.md).
- **Assistant / LLM.** Read tools (`get_courses`, `get_deadlines`, `get_grades`) let the
  assistant answer school questions; course data reaches Anthropic only on such a request.
  See [assistant.md](assistant.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [x] **Sync pipeline** (`moodle_sync.py`, a clone of `email_sync.py`) that upserts the six
      record types idempotently and flips the account to `needs_reauth` on an auth error.
- [x] **Read-time Calendar/Tasks merge** — deadlines/assignments projected into the existing
      output shapes, never physical rows, so those tables need no schema change or write-guards.
- [x] **Privacy** — token stored server-side only; course files and full page bodies are not
      requested or stored; source links open in Moodle; disconnect immediately removes the
      account and synced Moodle rows.

## External integrations

- **Moodle web services** (`{base}/webservice/rest/server.php`) — hand-rolled `httpx` over the
  REST endpoint (no vendor SDK), static per-user `wstoken`, JSON format. Errors come back
  HTTP 200 with an `"exception"` key. Read-only this slice — no submit/post/message writes.

## Open questions / future work

- Assignment **submission** (upload a file, mark done) — deferred to a later slice.
- Course-content/file browsing and rich HTML rendering of Moodle pages.
- Multi-instance support (more than one Moodle) and calendar/tasks → Moodle write-back.
