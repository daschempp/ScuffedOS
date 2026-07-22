# Email — Architecture

> Status: **built** (M5 — live Gmail sync, AI triage + draft) · Last updated: 2026-07-21 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). AI triage + draft replies over a
> synced inbox — the most LLM-heavy surface after the assistant.

## Responsibility

Sync the inbox, **triage** each message (categorize + AI summary), and generate **draft
replies** on demand. Serve the two-pane inbox/reading UI and user-initiated
send, reply, forward, label, flag, and Trash actions.

## Current state

Built and live (M5). `app/routers/email.py` serves the triaged inbox, message read, sync,
flags, labels, send and AI draft; `app/email_sync.py` runs the background Gmail sync loop,
`app/email_triage.py` categorizes + summarizes each message on sync, and `app/email_draft.py`
generates replies — all over `app/providers/google.py`. Bodies are never stored; they're
fetched live on demand. `frontend/src/screens/EmailScreen.jsx` renders the live synced inbox.

## Data model

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Email** | `from`, `time`, `subject`, `snippet`, `unread`, `category` | Synced from a provider. |
| **Category** | `Needs reply` \| `FYI` | AI triage output; drives inbox grouping + "4 need you". |
| **Summary** | `string[]` of bullets | AI-generated per message. |
| **Draft** | generated text | Generated on demand, editable before send; not precomputed on sync. |

## Surface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/email/inbox` | Triaged messages grouped by category. |
| `GET` | `/api/email/labels` | Gmail labels available to apply. |
| `GET` | `/api/email/{id}` | Message + AI summary. |
| `POST` | `/api/email/draft` | Generate a compose/reply draft from user instructions. |
| `POST` | `/api/email/send` | Send a new message through Gmail. |
| `POST` | `/api/email/{id}/reply` | Send a threaded reply. |
| `POST` | `/api/email/{id}/forward` | Forward a message. |
| `POST` | `/api/email/{id}/flags` | Confirm read/unread and star changes with Gmail. |
| `POST` | `/api/email/{id}/labels` | Confirm label changes with Gmail. |
| `POST` | `/api/email/{id}/trash` | Trash in Gmail, then delete the local row. |
| `POST` | `/api/email/sync` | Run a Gmail pull now. |

## Dependencies & interactions

- **Assistant / LLM (core).** Triage summaries and requested drafts are LLM outputs — the
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

- **Gmail API** — OAuth, scheduled pull sync, live body fetch, labels/flags/trash, and
  send/reply/forward. Stored rows contain metadata, snippets, categories, and summaries;
  full message bodies are fetched on demand and are not persisted.

## How it _should_ function

- [x] **Sync pipeline** + an LLM triage step that assigns category + summary.
- [x] **Draft generation** on demand; triage summaries are cached, drafts remain editable.
- [x] **Send path** for compose, threaded reply, and forward.
- [x] **Privacy boundary** — full bodies are fetched live, never stored, and bounded message
      content reaches the LLM only for triage or a user-requested draft.

## Open questions / future work

- Direct Email → Tasks/Calendar/People projections are not built.
- Push/webhook sync and richer offline body access remain future work.
