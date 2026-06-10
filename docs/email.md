# Email — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). AI triage + draft replies over a
> synced inbox — the most LLM-heavy surface after the assistant.

## Responsibility

Sync the inbox, **triage** each message (categorize + AI summary), and generate **draft
replies** in selectable tones. Serve the two-pane inbox/reading UI and support archive.

## Current state

Not implemented in the backend. `frontend/src/screens/EmailScreen.jsx` renders **sample
emails — including pre-baked AI summaries and drafts — held in the component**. This doc
describes the backend function that should own it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Email** | `from`, `time`, `subject`, `snippet`, `unread`, `category` | Synced from a provider. |
| **Category** | `Needs reply` \| `FYI` | AI triage output; drives inbox grouping + "4 need you". |
| **Summary** | `string[]` of bullets | AI-generated per message. |
| **Drafts** | `{ Friendly, Brief, Formal }` | AI-generated reply variants by tone; regenerate/edit/send. |

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/email/inbox` | Triaged messages grouped by category. |
| `GET` | `/api/email/{id}` | Message + AI summary. |
| `POST` | `/api/email/{id}/draft` | Generate/regenerate a reply for a tone. |
| `POST` | `/api/email/{id}/send` | Send a (possibly edited) reply. |
| `POST` | `/api/email/{id}/archive` | Archive. |
| `POST` | `/api/email/sync` | Pull from provider (or webhook). |

## Dependencies & interactions

- **Assistant / LLM (core).** Triage summaries and tone drafts are LLM outputs — the
  same model seam as [assistant.md](assistant.md). Share one LLM client/config.
- **Email → Tasks.** A "Needs reply" message maps cleanly to a task ("Reply to Priya
  about Lighthouse" already exists in the seed tasks) — consider a "make task from email"
  action. See [tasks.md](tasks.md).
- **Email → Calendar.** Messages carry dates/deadlines (lease decision by Jun 25, dinner
  Saturday) — extractable into events. See [calendar.md](calendar.md).
- **Email → People.** Senders are contacts (Priya, Jordan) — ties to [people.md](people.md)
  ("last contacted").
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## External integrations

- **Email provider** (Gmail API / IMAP+SMTP) — OAuth, sync (history/webhook), sending.
  Decide read-only triage vs. full send, and how much of the body we store vs. fetch.

## How it _should_ function

- [ ] **Sync pipeline** + a triage step (LLM) that assigns category + summary.
- [ ] **Draft generation** on demand vs. precomputed; caching of summaries/drafts.
- [ ] **Send path** with edited content, threading, and "from" identity.
- [ ] **Privacy** — message content is sensitive; what's stored vs. fetched live, and is
      it sent to the LLM?

## Open questions / future work

- One LLM service shared with the assistant, or a dedicated email-AI module?
- How are user edits to a draft reconciled with regenerate?
