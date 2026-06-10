# Assistant — Architecture

> Status: built (M2) · Last updated: 2026-06-10 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). The assistant is the
> universal interface: a server-side Claude tool loop with read + write reach
> over every built domain, persistent conversations, and Mem0-backed memory.

## Responsibility

Take one user message (plus optional `conversation_id`) and run a real agentic
turn: recall relevant memories, stream a reply, execute tools against the live
store, and persist the whole exchange. Returns
`{ conversation_id, text, actions[] }` — `text` is **plain text, never HTML**
(review R4), and each `ChatAction` is a *receipt for a tool that actually
executed*, with a deep link (review D2).

## Surface (current)

`app/routers/assistant.py`:

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/assistant/chat` | JSON: `ChatRequest { message, conversation_id? }` → `ChatResponse { conversation_id, text, actions[] }`. `503 service_unavailable` (with the real reason — missing key, billing, rate limit) when the LLM can't be reached. |
| `POST` | `/api/assistant/chat/stream` | SSE: `meta {conversation_id}` → `delta {text}`* → `tool {name}` / `action {…}`* → `done {text, actions}`. Mid-stream failures arrive as an `error` event. |
| `GET` | `/api/assistant/conversation` | Latest conversation + its messages — the chat panel resumes it across backend restarts. |

`ChatAction.screen` is a `Literal` over the sidebar's actual screens (review
R8) — the model can't deep-link to a screen that doesn't exist.

## Internal design (current)

- **`app/llm.py`** — the Anthropic seam (D3): lazy client, `pick_model()`
  routing (cheap/fast `claude-haiku-4-5` for chat; `claude-opus-4-8` for heavy
  work — day planning now, email drafts in M5), and one `stream()` entry point.
  Tests swap the whole seam via `llm.configure(fake)`.
- **`app/tools.py`** — the tool surface: tasks read+write (`list/create/update/
  delete_task`), memory read+write (`search_memory`, `remember` (verbatim),
  `list/update/forget_memory`), and read-only tools over seeded sample domains
  (calendar/nutrition/finance/habits/fitness from `app/seeds.py`, every payload
  labeled SAMPLE DATA until the real integration lands in M3/M4/M6). Write
  executors return the action card. Tool errors go back to the model
  (`{"error": …}` in the tool result), not to the user.
- **`app/assistant.py`** — the loop: build system prompt (persona + current
  time + top Mem0 recalls for this message), replay history from the
  conversations table, then stream/execute/feed-back for up to 8 tool rounds.
  Both endpoints drive the same `run_turn()` generator.
- **Persistence:** user + assistant messages (with action receipts) land in
  `conversation_messages`; the panel reloads them on open. Restart-survival is
  an M2 acceptance test.
- **Memory capture:** after each reply, the exchange goes to Mem0 auto-capture
  on a background thread — see [memory.md](memory.md).

## Offline fallback (review D4)

`frontend/src/assistant/assistantLogic.js` is now **capture-only**: when the
backend (or the LLM) is unreachable, the panel shows "Offline — capture only",
tries to file the message as a second-brain note, and says exactly what
happened. All canned replies and invented figures are gone.

## Voice

Browser `SpeechRecognition` (`frontend/src/lib/useSpeech.js`): dictation into
the chat composer (mic button) and the top-bar "Voice note" flow, which files
the transcript as a `voice note` memory. Server-side Whisper is the planned
upgrade path if quality disappoints.

## Resolved questions (were open pre-M2)

- **LLM:** Anthropic Claude; models above; `ANTHROPIC_API_KEY` via env.
- **Action vocabulary:** enum-constrained in `schemas.py` (R8) ✔
- **Conversation state:** threaded; lives in the DB; the "pure function" seam
  became the `llm.configure`/`memory_engine.configure` seams for tests.
- **Streaming:** SSE ✔ (through the Vite proxy in dev).
- **Offline fallback honesty:** capture-only ✔ — server/client engines can no
  longer drift because the client one no longer pretends to answer.
- **Server-side writes:** the assistant now writes tasks itself via tools; the
  old client-mediated `makeTask` flow is gone.
