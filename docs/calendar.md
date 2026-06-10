# Calendar — Architecture

> Status: built (M3) · Last updated: 2026-06-10 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns events and the day/week/
> month views plus the "Up next" feed.

## Responsibility

Own the user's schedule: events with real datetimes, a category tint, optional
location, and an optional recurrence rule; serve concrete *occurrences* for any
window (day/week/month rendering); and surface the "Up next" agenda. The
assistant writes here through the `create_event` tool ("dentist Friday 2pm").

## Surface (current)

`app/routers/calendar.py`, prefix `/api/calendar`:

| Method | Path | Body / params | Returns | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/events?from=&to=` | ISO datetimes (default: current Mon-start week) | `list[EventOccurrence]` | Recurring series **expanded on read**; sorted by start. |
| `POST` | `/events` | `EventCreate` | `EventOccurrence` | `201`. `end` defaults to start + 1h; bad RRULE / end ≤ start → `422`. |
| `PATCH` | `/events/{id}` | `EventUpdate` | `EventOccurrence` | Edits apply to the **whole series** for recurring events. |
| `DELETE` | `/events/{id}` | `?occurrence_start=` optional | `204` | With the param: removes one occurrence (recorded as an exdate). Without: deletes the series. |
| `GET` | `/up-next?limit=` | — | `list[UpNextItem]` | Ongoing first, then next starts; `when` is a derived display string. |

Models (`schemas.py`): `EventOccurrence` — `{id, title, start, end, tint, location,
description, recurring, recurrence_label, at}`. `id` is the series row for recurring
events; occurrences are identified by `(id, start)`. `at` ("9:00am") and `when`
("Now · 9:00am–10:30am" / "Tomorrow 4:00pm · Oak Street") are derived display
facts (R6), computed in `display.py`.

## Internal design (current)

- `events` table (`app/models.py`): `start_at`/`end_at` as real UTC timestamps,
  `tint` from the design palette (`green|sky|plum|honey|clay`, Literal-constrained —
  R8), `recurrence` as an RFC 5545 RRULE string, `exdates` as a JSON list of
  deleted occurrence starts (ISO, UTC). Nothing is materialized.
- **Recurrence engine** lives in `app/recurrence.py` (shared with recurring tasks):
  python-dateutil `rrulestr`, expanded in *local wall-clock time* so a 9:00am
  standup stays 9:00am across DST, results returned UTC. Expansion is capped
  (`MAX_OCCURRENCES`) so a pathological rule can't hang a request.
- Window queries widen the left edge by the event duration so an occurrence that
  starts before the window but overlaps into it still renders.
- Frontend: `lib/useCalendar.js` owns the visible week (prev/next/today), the
  month-grid dots, and the up-next feed; `CalendarScreen.jsx` renders occurrences
  into the prototype's hour grid, which widens past 8am–6pm whenever the week
  holds earlier/later events (nothing is silently dropped).

## Dependencies & interactions

- **Assistant → Calendar.** `create_event` / `update_event` / `delete_event` /
  `get_calendar` tools in `app/tools.py`; action cards deep-link to the calendar
  screen. Naive datetimes from the model are treated as the user's local time.
- **Tasks → Calendar (future).** Task deadlines could render as client-side
  overlays (the shared task list already lives in `App.jsx`) rather than
  calendar rows — not surfaced yet.
- **Recurrence is shared with Tasks** — same `app/recurrence.py`, same RRULE
  vocabulary, one set of correctness tests.
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [x] **Datetime model** with timezone handling — M3 (UTC stored, local expansion).
- [x] **Recurring events** — M3 (RRULE + exdates, expanded on read).
- [x] **Assistant write path** (`create_event`) — M3.
- [ ] **External calendar sync** — Google Calendar explicitly deferred (out of spec).
- [ ] **Free-slot finding** for "find me a slot tomorrow" — the assistant can read
      the day and reason about gaps; a dedicated tool is future work.

## Design decisions & rationale

- _Why expand on read instead of materializing occurrences?_ — No second copy to
  keep consistent; edits to a series are one-row writes; exdates make single-
  occurrence deletes cheap. Single-user volumes make expansion trivially fast.
- _Why RRULE strings?_ — The interoperable standard (Google sync later maps 1:1),
  dateutil parses them natively, and the UI only needs a few presets.
- _Why do PATCHes hit the whole series?_ — "Edit this occurrence only" requires
  detached-instance bookkeeping that nothing needs yet; delete-occurrence +
  create-standalone covers the rare case.

## Open questions / future work

- Day/Month main views are still cosmetic buttons (Week renders); revisit with
  real usage.
- Event reminders (the task reminder scheduler could serve events too).
