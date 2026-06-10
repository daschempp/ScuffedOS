# People (Personal CRM) — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). A personal CRM: contacts,
> relationship cadence, reach-out nudges, and important dates.

## Responsibility

Own the user's contacts and relationship metadata (type, closeness, last contact), drive
"reach out" nudges when a relationship is overdue, and track upcoming important dates.

## Current state

Not implemented in the backend. `frontend/src/screens/CRMScreen.jsx` renders **sample
people, nudges, and upcoming dates held in the component** ("142 contacts"). This doc
describes the backend function that should own it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Person** | `name`, `relationship` (Colleague/Family/Friend/Network), `last_contacted`, `strength` (1–5), `tint`, `due?`/`overdue?` | `due`/`overdue` are derived from cadence vs. `last_contacted`. |
| **Reach-out nudge** | derived: `{ name, why }` | Computed when contact is overdue ("usually catch up every 2 weeks"). |
| **Important date** | `name`, `date`, `icon`/`tint` | Birthdays, anniversaries, work-iversaries. |

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/people?search=` | Contacts (with derived due/overdue). |
| `POST`/`PATCH` | `/api/people` · `/api/people/{id}` | Add / edit a contact. |
| `POST` | `/api/people/{id}/log-contact` | Record an interaction (resets cadence). |
| `GET` | `/api/people/reach-out` | Overdue nudges. |
| `GET` | `/api/people/upcoming` | Important dates. |

## Dependencies & interactions

- **Assistant → People.** The screen shows "Assistant nudges" and "Draft a hello"/"Draft
  a note" — LLM-generated outreach, same model seam as [assistant.md](assistant.md).
- **People ↔ Email.** Email senders are contacts; `last_contacted` could update from sent/
  received mail. See [email.md](email.md).
- **People → Calendar.** "Upcoming" dates (birthdays/anniversaries) are calendar-like —
  decide if they render as events. See [calendar.md](calendar.md).
- **People ↔ Memory.** Memories reference people ("Mom's birthday", "loop in Priya") —
  could link memories to contacts. See [memory.md](memory.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [ ] **Cadence model** — per-contact expected frequency → derives due/overdue + nudges.
- [ ] **Interaction history** feeding `last_contacted` (manual log, or auto from
      email/calendar).
- [ ] **Important dates** with recurrence + reminders.
- [ ] **Contact source** — manual, or imported from a contacts provider / email.

## Open questions / future work

- Auto-update closeness/last-contacted from Email/Calendar activity, or keep manual?
- Where do important dates live — here or in Calendar?
