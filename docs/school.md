# School (Moodle) — Architecture

> Status: **built** (M6 — Moodle read-only; live sync gated on a real WolfWare token) · Last updated: 2026-07-11 · Owner: _Dylan_
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
