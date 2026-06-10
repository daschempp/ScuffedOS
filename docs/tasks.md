# Tasks — Architecture

> Status: built (M1; reminders/files/recurrence M3) · Last updated: 2026-06-10 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). THE task model (review D1):
> one rich, durable task that Home, the Tasks screen, and the assistant all share.

## Responsibility

Own the **one rich task model**: the former TasksScreen shape (group, deadline,
priority, list, description, subtasks, labels, reminders, file metadata), stored in
Postgres. Home renders the `Today` slice of the same rows; the assistant's
`makeTask` flow creates the same rows. The old simple/rich split is resolved — merged
server-side in M1.

## Surface (current)

`app/routers/tasks.py`, prefix `/api/tasks`:

| Method | Path | Body | Returns | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/tasks` | — | `list[Task]` | Newest first (id desc). |
| `POST` | `/api/tasks` | `TaskCreate` (label required, rest defaulted) | `Task` | `201 Created`. Bad RRULE → `422`. |
| `PATCH` | `/api/tasks/{id}` | `TaskUpdate` (all optional) | `Task` | `404` if id unknown. Completing a recurring task spawns the next occurrence (see below). |
| `DELETE` | `/api/tasks/{id}` | — | `204` | `404` if id unknown. Removes reminders (cascade) and the attachment dir. |
| `GET`/`POST` | `/api/tasks/{id}/reminders` | `TaskReminderCreate` | `list[TaskReminderOut]` / `TaskReminderOut` | M3 — reminders that fire (see below). |
| `DELETE` | `/api/tasks/{id}/reminders/{rid}` | — | `204` | |
| `POST` | `/api/tasks/{id}/files` | multipart `file` | `Task` | M3 — bytes to `ATTACHMENTS_DIR/{task_id}/{uuid}`, metadata onto the row. |
| `GET`/`DELETE` | `/api/tasks/{id}/files/{fid}` | — | download / `204` | Download serves the original filename. |

Models (`schemas.py`):

- `Task` — `{ id, label, done, group, deadline, prio, list, description, subtasks,
  labels, reminders, files, due, late, created_at, updated_at, completed_at }`.
  `group` and `prio` are Literal-constrained (`Today|Upcoming|Someday`, `low|med|high`
  — review R8). `due`/`late` are **derived display facts** computed on read from
  `deadline`/`done`/`completed_at` (review R6) — never stored, read-only.
- `TaskCreate` — label (non-empty) + optional everything else, with prototype defaults
  (`group=Today`, `prio=med`, `list=Personal`).
- `TaskUpdate` — all-optional partial update (`exclude_unset`); explicit `null` clears
  `deadline`/`recurrence` and is ignored for non-nullable fields (review R7).
- `files` holds metadata (`{id, name, size}`) mirroring real bytes on disk (M3);
  server-issued ids are uuid hex strings.
- `reminders` are **structured rows** (`{id, remind_at, label, fired_at, display}`,
  M3) served embedded in the task and written via the reminder endpoints — they
  graduated out of the JSON column because the scheduler queries them.
- `recurrence` is an RFC 5545 RRULE string (presets in the UI: daily/weekdays/
  weekly/monthly); `recurrence_label` is its derived description.

## Internal design (current)

The router is thin; persistence lives in `store.py` over SQLAlchemy
(see [data-store.md](data-store.md)):

- `tasks` table (`app/models.py`): `group` is stored in a `bucket` column (SQL-name
  hygiene), `list` in a `list` column mapped to `list_name`; subtasks/labels/files are
  JSONB (JSON on SQLite). Real UTC `created_at`/`updated_at`/`completed_at`.
  `task_reminders` is its own table (M3) — the scheduler queries it.
- `done: true` sets `completed_at` (drives the "Done 8:02am" display); un-completing
  clears it.
- **Recurring tasks (M3)** — completing a task with a `recurrence` rule spawns a
  fresh row for the next occurrence (deadline = next date after max(deadline,
  today); subtasks reset; reminders copied shifted by the deadline delta; group
  re-bucketed Today/Upcoming) and strips the rule from the completed row, so
  history stays plain and re-completing can't double-spawn. Shared engine:
  `app/recurrence.py` (see [calendar.md](calendar.md)).
- **Reminders that fire (M3)** — `app/reminders.py`: an asyncio tick (started in
  the FastAPI lifespan, `REMINDER_TICK_SECONDS`) queries unfired, past-due
  reminders on open tasks, posts a macOS notification per row via
  `osascript display notification` (no app bundle needed), and stamps `fired_at`.
  Catch-up after sleep is implicit — anything missed fires on the next tick.
  Reminders on completed tasks never fire.
- **Attachments (M3)** — bytes at `ATTACHMENTS_DIR/{task_id}/{file_id}` (disk names
  are server uuids, never client input); the task's `files` JSON is the metadata
  mirror; deleting the task removes the directory.
- `store.seed_demo()` / `python -m app.seed` inserts the 10 design-prototype tasks with
  deadlines computed relative to today, so Today/Upcoming/Someday look right whenever
  it runs. The 5 Home tasks are the `Today` group of the same rows.

Frontend: `lib/useTasks.js` owns the shared list (optimistic updates, 400 ms debounced
PATCH per task so the detail drawer doesn't write per keystroke); `App.jsx` passes the
same state to Home (`Today` filter) and TasksScreen.

## Dependencies & interactions

- **Depends on:** `schemas.py` (`Task`, `TaskCreate`, `TaskUpdate`) and `store.py`.
- **Called by:** the frontend Home list, and the assistant flow — when a chat reply
  carries `action.makeTask`, the **client** POSTs here. The tasks router has no knowledge
  of the assistant; the link is one-directional and client-mediated. See the
  [overview sequence](backend-overview.md#cross-section-flow-add-a-task-via-the-assistant).
- **Shares the store with Memory** — same concurrency model, same swap seam.

## Rich task model (Tasks screen — target superset)

The Tasks **screen** (`frontend/src/screens/TasksScreen.jsx` + `TaskDetail.jsx`) already
works against a far richer task than the backend's `{ id, label, done }`. If/when that
model moves server-side, this is the shape to support — the home/assistant list is a thin
slice of it:

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `label`, `done` | int, str, bool | What the backend already serves. |
| `group` | `Today` \| `Upcoming` \| `Someday` | Section bucket. |
| `due` | str | Display string today ("11:00am", "Overdue", "Tomorrow"). |
| `late` | bool | Derived (overdue). |
| `deadline` | date (`YYYY-MM-DD`) | Real date in the detail drawer. |
| `prio` | `low` \| `med` \| `high` | Priority. |
| `list` / `listColor` | `Work`/`Health`/`Finance`/`Personal` (+ color) | User-defined lists. |
| `description` | str | Free text. |
| `subtasks` | `[{ id, label, done }]` | Checklist; `n/m` shown. |
| `labels` | `string[]` | Tags (e.g. "savings", "planning"). |
| `reminders` | `string[]` | e.g. "1 hour before", "9:00am". |
| `files` | `[{ id, name, size }]` | Attachments — implies **file upload/storage**. |

## How it _should_ function

- [x] **Durable persistence** — M1: Postgres + SQLAlchemy + Alembic.
- [x] **Reconcile with the Tasks-screen model** — M1: merged; the rich model is THE model.
- [x] **Delete** — hard delete endpoint (M1). Archive/soft-delete deferred until a need shows.
- [x] **Due dates** first-class (`deadline`, M1).
- [x] **Reminders that fire** — M3: `task_reminders` table + tick scheduler +
      osascript notifications.
- [x] **Real file attachments** — M3: upload + app-data-dir storage + download.
- [x] **Recurring tasks** — M3: RRULE recurrence shared with Calendar,
      spawn-next-on-complete.
- [ ] **Ordering** — newest-first is hardcoded; client sort/filter still open.

## Design decisions & rationale

- _Why insert newest-first?_ — Matches the prototype's home list.
- _Why `PATCH` with `exclude_unset` rather than `PUT`?_ — Lets the UI toggle `done`
  without resending `label`, and makes null-to-clear semantics explicit (R7).
- _Why JSON columns for subtasks/labels/files?_ — The UI patches them wholesale;
  they graduate to real tables only when something needs to query them — which is
  exactly what happened to reminders in M3 (the scheduler queries `task_reminders`).
- _Why store `group` rather than derive it from `deadline`?_ — "Someday" is a user
  intent, not a date fact; deriving would erase it.

## Open questions / future work

- Lists are free-form strings with a fixed color map in the UI; the "New list" button
  is still decorative. Real user-defined lists (own table, colors) when needed.
- `done` on a `Someday` task still counts toward "Done today" in the Progress card —
  prototype behavior, revisit with real analytics.
