# Assistant — Architecture

> Status: draft · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). The assistant turns a chat
> message into a friendly reply plus an optional "action card".

## Responsibility

Take one user message and return `{ text, action? }`:

- `text` — the reply to show in the chat panel (may contain inline `<strong>` HTML).
- `action` — an optional card the UI renders (icon, title, meta, a CTA, and a `screen`
  to deep-link to). When `action.makeTask` is set, it's also a signal to the client to
  create a real task.

It is **pure and stateless**: same input → same output, no history, no side effects, no
store access. That purity is the whole point — it's the seam where a real LLM drops in.

## Surface (current)

`POST /api/assistant/chat` — `app/routers/assistant.py`

| | |
| --- | --- |
| Request | `ChatRequest { message: str }` |
| Response | `ChatResponse { text: str, action: ChatAction | null }` |
| `ChatAction` | `{ icon, title, meta, cta, screen, makeTask?: str }` |

The endpoint is a one-liner that calls `reply(req.message)`. It never writes to the
store, even when the action implies a task — the client owns that follow-up POST.

## Internal design (current)

All logic lives in `app/assistant.py`, a faithful server-side port of the prototype's
`assistant-logic.js` (mirrored client-side as `frontend/src/assistant/assistantLogic.js`
for offline fallback — **keep the two in sync**).

- `reply(text) -> {text, action}` — lowercases the message, then runs an **ordered**
  chain of regex/keyword checks; first match wins; falls through to a help message.
- `clean_title(text)` / `clean_event(text)` — strip command prefixes ("remind me to",
  "schedule a meeting for", trailing punctuation) and capitalize, so the echoed task/
  event label reads naturally.

Intent order (order matters — earlier rules win):

| # | Intent | Screen / action |
| --- | --- | --- |
| 1 | Plan my day / agenda / brief me | `home` — "Day planned" |
| 2 | Explicit task phrasing ("add a task", "remind me", "to-do") | `tasks` + `makeTask` |
| 3 | Move/transfer money into savings | `finance` |
| 4 | Spending / budget / "how much" | `finance` |
| 5 | Schedule / meeting / calendar | `calendar` + cleaned event |
| 6 | Log meal / nutrition / water | `nutrition` |
| 7 | Generic reminder/task keywords (call, email, pay, buy…) | `tasks` + `makeTask` |
| 8 | Remember / note / second brain | `memory` |
| 9 | _fallback_ | help text, `action: null` |

> Rules 2 and 7 both create tasks; 2 exists so explicit task phrasing wins over a
> category keyword in the same sentence (e.g. "add a task to **book** the dentist"
> shouldn't be read as a calendar booking).

## Dependencies & interactions

- **Depends on:** `schemas.py` only (`ChatRequest`, `ChatResponse`, `ChatAction`).
- **Does _not_ depend on:** the store. No persistence, no shared state.
- **Interacts with Tasks indirectly:** an `action.makeTask` is the client's cue to call
  `POST /api/tasks`. The assistant never creates the task itself — see the cross-section
  sequence in the [overview](backend-overview.md#cross-section-flow-add-a-task-via-the-assistant).
- **Mirror in the frontend:** `assistantLogic.js` must return the identical shape so the
  offline fallback matches server behavior.

## How it _should_ function

> The target you're authoring. Seeds from the README's "clean seam for a real LLM":

- [ ] **Swap the intent engine for a live LLM** returning the same `{text, action}`
      shape. What model? Where does the prompt + the "available screens/actions" schema
      live?
- [ ] **Action vocabulary as a contract.** Today actions are ad-hoc dicts. Should the set
      of `screen`/`action` types be an enum the model is constrained to (tool/function
      calling) so it can't hallucinate a screen that doesn't exist?
- [ ] **Conversation state.** Stay stateless, or thread history? If stateful, where does
      it live, and does that break the "pure function" seam?
- [ ] **Streaming** responses to the chat panel?
- [ ] **Keeping the offline fallback honest** once the server uses a real LLM — what does
      `assistantLogic.js` do then?

## Design decisions & rationale

- _Why a pure function instead of writing tasks server-side?_ — Stateless `/chat` is
  idempotent and trivially testable; the client already owns optimistic UI. TODO: confirm
  this stays true with a real LLM.
- _Why ordered keyword rules?_ — Deterministic, debuggable, and an exact match for the
  prototype. TODO.

## Open questions / future work

- How do server and client intent engines stay in sync — shared source, codegen, or
  manual parity? (They drift silently today.)
- Should `text` keep returning HTML (`<strong>`), or move to a safer structured format?
