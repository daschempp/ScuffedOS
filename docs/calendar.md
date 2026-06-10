# Calendar — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns events and the day/week/
> month views plus the "Up next" feed.

## Responsibility

Own the user's schedule: events with a time, title, category color, and location;
serve them for day/week/month rendering; and surface an "Up next" agenda. The
assistant's "schedule a meeting" intent and task deadlines both feed in here.

## Current state

Not implemented in the backend. `frontend/src/screens/CalendarScreen.jsx` renders
**sample data held in the component** — events keyed by weekday index, a month grid,
and a hardcoded "Up next" list. This doc describes the backend function that should own
it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Event** | `title`, `start`, `end`, `color`/category, `at` (display time), `location?` | Prototype stores `start`/`end` as fractional hours (e.g. `11.5`) keyed by day index; the real model needs full **datetimes**. "Up next" shows locations ("Oak Street", "Google Meet"). |
| **Up next** | derived: next N events with `when` + color | A query/projection, not stored. |
| **Month dot** | derived: days that have ≥1 event | Computed from events. |

Categories map to the design palette (green/sky/plum/honey/clay) — likely a small
fixed set or a per-calendar color.

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/calendar/events?from=&to=` | Events in a date range (powers day/week/month). |
| `POST` | `/api/calendar/events` | Create an event. |
| `PATCH` | `/api/calendar/events/{id}` | Reschedule / edit. |
| `DELETE` | `/api/calendar/events/{id}` | Remove. |
| `GET` | `/api/calendar/up-next?limit=` | Agenda projection. |

## Dependencies & interactions

- **Assistant → Calendar.** The assistant's `schedule|meeting|calendar` intent already
  returns an action pointing at the `calendar` screen with a cleaned event title, but
  there's no write path yet. Mirror the `makeTask` pattern with a `makeEvent` action (or
  have the assistant call this service) so "schedule design review Friday" creates a real
  event. See [assistant.md](assistant.md).
- **Tasks → Calendar.** Tasks carry a `deadline` and `reminders`; deadlines/reminders
  could surface as calendar entries. See [tasks.md](tasks.md).
- **People → Calendar.** CRM "upcoming" dates (birthdays, anniversaries) are calendar-like
  events. Decide if they live here or in [people.md](people.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [ ] **Datetime model** with timezone handling (prototype uses fractional hours).
- [ ] **Recurring events** (standups, "Deep work" blocks repeat).
- [ ] **External calendar sync** — Google Calendar is implied ("Google Meet"). One-way
      import, or two-way sync? Conflict resolution?
- [ ] **Assistant write path** (`makeEvent`) + free-slot finding (the assistant claims
      "I found a free slot tomorrow afternoon").

## Open questions / future work

- Source of truth: local events vs. a synced external provider (or both)?
- Do task deadlines and CRM dates render as first-class events or as overlays?
