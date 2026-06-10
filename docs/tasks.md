# Tasks — Architecture

> Status: draft · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). The simple home/assistant task
> list — create, list, and toggle tasks.

## Responsibility

Own the **simple** task list shown on Home and created by the assistant: a flat list of
`{ id, label, done }`. This is deliberately _not_ the rich task model on the Tasks screen
(subtasks, files, priority, deadline) — see Open questions.

## Surface (current)

`app/routers/tasks.py`, prefix `/api/tasks`:

| Method | Path | Body | Returns | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/tasks` | — | `list[Task]` | Newest first. |
| `POST` | `/api/tasks` | `TaskCreate { label, done=false }` | `Task` | `201 Created`. |
| `PATCH` | `/api/tasks/{id}` | `TaskUpdate { label?, done? }` | `Task` | `404` if id unknown. |

Models (`schemas.py`):

- `Task { id: int, label: str, done: bool = false }`
- `TaskCreate { label: str, done: bool = false }`
- `TaskUpdate { label?: str, done?: bool }` — only the fields sent are applied
  (`exclude_unset`), so `PATCH` is a true partial update.

There is **no delete** endpoint today.

## Internal design (current)

The router is thin; all state lives in `store.py` (see [data-store.md](data-store.md)):

- `store.list_tasks()` — returns a shallow copy of the list.
- `store.create_task(label, done)` — assigns `_next_task_id`, **inserts at the front**
  (newest-first, matching the prototype), returns the new task.
- `store.update_task(id, patch)` — finds by id, applies only non-`None` patch values,
  returns the updated task or `None` (router turns `None` into `404`).

Seeded with 5 tasks that mirror the frontend's `App.jsx` `SEED_TASKS` (ids 1–5,
"Pay rent" done, the rest open). Mutations are lock-guarded.

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

> Target design to author:

- [ ] **Durable persistence** via the real store (DB). Same router, new backing.
- [ ] **Reconcile with the Tasks-screen model.** Today the backend serves a _simple_
      list while the Tasks screen keeps its own rich local model (subtasks, reminders,
      list, priority, deadline, files). Do these merge into one backend model, stay two
      tiers, or does the rich model also move server-side? This is the biggest open call.
- [ ] **Delete / archive / complete semantics** — is `done` enough, or do we need
      soft-delete and a separate "archived" state?
- [ ] **Due dates & reminders** as first-class fields (the UI hints "tap to set a due
      date").
- [ ] **Ordering** — newest-first is hardcoded; should clients control sort/filter?

## Design decisions & rationale

- _Why insert newest-first?_ — Matches the prototype's home list. TODO.
- _Why `PATCH` with `exclude_unset` rather than `PUT`?_ — Lets the UI toggle `done`
  without resending `label`. TODO.

## Open questions / future work

- The two-task-model split (simple backend list vs. rich Tasks screen) is the key
  architectural question — resolve it before adding fields piecemeal.
- Validation: should empty/whitespace `label` be rejected? (Not enforced today.)
