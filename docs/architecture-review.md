# Architecture Review

> Status: review · Last updated: 2026-06-09 · Reviewer: Claude (`/architecture`)
>
> An evaluation of the architecture described in these docs — what's sound, what's
> risky, and a recommendation on each open decision the docs flag. Scope is **design
> soundness**: the docs are taken at face value as the intended architecture, with the
> code read only to ground how the seams actually behave. This is not a docs-vs-code
> drift audit.
>
> Inputs: all 12 docs in this folder, the root `README.md`, the full backend
> (`backend/app/`), and the frontend seam files (`App.jsx`, `lib/api.js`,
> `assistant/ChatPanel.jsx`, `assistant/assistantLogic.js`, `screens/TasksScreen.jsx`).

## Verdict

This is a well-designed prototype with honest documentation. The three load-bearing
decisions — a pure, stateless assistant as the LLM seam; a layered
router → store → schema pattern with zero-inbound-coupling swap points; and graceful
degradation as a product property — are all sound, verified in the code, and correctly
identified by the docs as the places where the "prototype → real app" jump happens. The
docs' habit of flagging their own open questions is unusually good practice; every
significant risk found in this review is at least partially acknowledged somewhere in
them.

The review's main message: **the open decisions are not equally urgent, and four of
them gate the stated next phase** (real LLM + iPhone client). The task-model split, the
assistant write pattern, the offline-fallback promise, and the HTML-in-`text` question
should be resolved *before* the LLM swap — each gets more expensive to change after it.
The rest (integrations stance, auth, versioning) can be decided just-in-time, but two
gaps the docs don't yet name need plans: **secret/token storage** and the fact that
**webhooks are not an option** for a localhost-only app.

| # | Severity | Finding | Where |
| --- | --- | --- | --- |
| F1 | High | The offline-parity promise ("keep the two engines in sync") is unsustainable once a real LLM lands — parity becomes impossible by definition, and sync is already manual. | [R1](#r1--offline-parity-cannot-survive-the-llm-swap) · [D4](#d4--offline-fallback-and-engine-parity) |
| F2 | High | The assistant claims side effects that never happen — only `makeTask` is real; transfer, schedule, log-meal, and remember replies are fabrications. Becomes acute with a real LLM. | [R2](#r2--the-assistant-claims-actions-it-doesnt-perform) · [D2](#d2--assistant-write-pattern) |
| F3 | High | Two disjoint task stores live in the same app (synced simple list vs. purely-local rich list). Correctly called "the key architectural question" in [tasks.md](tasks.md). | [R3](#r3--two-disjoint-task-stores) · [D1](#d1--the-two-task-model-split) |
| F4 | Medium | Assistant `text` is HTML rendered via `dangerouslySetInnerHTML`, with user input reflected into it. Benign today; a real injection channel once LLM + Email land. | [R4](#r4--html-in-text-is-a-future-injection-channel) |
| F5 | Medium | Five planned integrations need OAuth tokens, but no doc has a secret-storage design; and the proposed "(or webhook)" sync options are impossible while the app is localhost-only. | [R5](#r5--no-secrets-story-and-webhooks-are-off-the-table) · [D6](#d6--external-integrations-stance) |
| F6 | Medium | Presentation leaks into stored data (`when="just now"`, display-string `due`); needs a "store facts, derive display" rule before persistence lands. | [R6](#r6--presentation-baked-into-contracts) · [D5](#d5--persistence-migration) |
| F7 | Low | Store-interface subtleties to pin before the DB swap: double `None`-filtering makes fields un-nullable; the shallow-copy claim protects less than stated; reads are unlocked. | [R7](#r7--store-contract-subtleties) |
| F8 | Low | `screen` strings are an unvalidated cross-tier enum; the docs propose constraining the action vocabulary — do it for screens too. | [R8](#r8--the-screen-vocabulary-is-unvalidated) |

## What's sound

**The stateless assistant seam is real, not aspirational.** `reply(text)` in
`backend/app/assistant.py` touches nothing but its input; the router
(`app/routers/assistant.py`) is a one-liner. The `{ text, action }` contract is exactly
the shape an LLM integration would return. The claim in [assistant.md](assistant.md)
that this is "the seam where a real LLM drops in" holds up — the swap is one module.

**The zero-inbound-coupling swap points hold up.** `store.py` imports only `threading`;
`schemas.py` imports only Pydantic. The routers are genuinely thin (the tasks router is
27 lines). Replacing the store's backing without touching routers is credible — the
method signatures in [data-store.md](data-store.md) really are the whole interface.

**Graceful degradation is a coherent product property, consistently applied.** Every
caller in the frontend handles backend absence the same way: `App.jsx` falls back to
`SEED_TASKS`, `ChatPanel.jsx` falls back to the local engine, `MemoryScreen` to sample
data. Seed data mirrored on both sides makes the demo seamless. This is the right
contract for a desktop app whose backend is a sidecar process.

**Client-mediated writes were the right prototype call.** Having the client POST
`makeTask` keeps `/chat` idempotent and testable and reuses the optimistic-UI path the
client already owns. (D2 below recommends this *not* survive the LLM swap — but as a
prototype decision it was correct, and the docs were right to flag "confirm this stays
true with a real LLM" rather than assume it.)

**The docs themselves are an asset.** One template per function, explicit
built-vs-planned status, "TODO is a prompt, not a decision", and self-flagged open
questions. The planned-function docs extract their data models from the prototype
screens, which is exactly the right source of truth at this stage.

## Risks, ranked

### R1 — Offline parity cannot survive the LLM swap

[assistant.md](assistant.md) instructs "keep the two in sync" between
`app/assistant.py` and `frontend/src/assistant/assistantLogic.js`, and separately
admits "they drift silently today." Manual parity between a Python and a JS port is
already fragile — but the deeper problem is that the parity goal itself expires: the
moment the server answers with a real LLM, no client-side keyword engine can match it.
The fallback then silently becomes a *different, worse assistant* wearing the same UI.
Decide now what offline means post-LLM (see [D4](#d4--offline-fallback-and-engine-parity))
rather than inheriting it.

### R2 — The assistant claims actions it doesn't perform

Of the nine intents, only the task intents have a write path (`makeTask` → client POST).
The others return replies that assert completed side effects that never occurred:
"Moved **$120** from Dining to Savings", "Scheduled X… and sent the invite",
"Logged it. You're at **1,910 kcal**", "Saved to your second brain." The memory case is
the sharpest: [memory.md](memory.md) notes there is no `makeNote`, so a user who says
"remember X" is told it's saved and it is not. For a design prototype this is fine —
the screens are sample data anyway — but architecturally it means the **action
vocabulary owes a debt to the copy**. When a real LLM lands, either every claimed
action must be executable, or the model must be constrained to only claim what it can
do. Closing the `makeNote` gap is cheap and should happen first (the endpoint already
exists; `api.createMemory` is already in `lib/api.js`).

### R3 — Two disjoint task stores

`App.jsx` holds the simple list and syncs it with `/api/tasks`; `TasksScreen.jsx` holds
ten rich tasks in component state and never touches the API. Toggling "Pay rent" on
Home does not affect the Tasks screen, and vice versa — same labels, different ids, no
linkage. The docs know this ([tasks.md](tasks.md) calls it the key architectural
question); the review's contribution is urgency and a recommendation
([D1](#d1--the-two-task-model-split)): resolve it *at DB-migration time* so the schema
lands once, and don't add any task field on either side before then.

### R4 — HTML in `text` is a future injection channel

`ChatPanel.jsx` renders assistant text with `dangerouslySetInnerHTML`, and
`clean_title()` reflects user input into that HTML ("Done — I've added
`<strong>` + *your text* + …"). Today that's self-XSS in a single-user local app —
harmless. But the docs' own roadmap turns it into a real channel: Email content →
LLM-generated summary/reply → `text` → `dangerouslySetInnerHTML`. A hostile email that
prompt-injects the triage model can then emit live HTML into the app shell.
[assistant.md](assistant.md) already asks whether `text` should "move to a safer
structured format" — the answer is yes, and **before** the LLM lands: plain text plus a
minimal emphasis schema (or markdown rendered through a sanitizer), never raw HTML.

### R5 — No secrets story, and webhooks are off the table

Fitness, Email, Calendar, Finance, and People all require per-user OAuth tokens — and
Finance and Email hold the most sensitive data in the app — but no doc has a concrete
token/secret-storage design (only open questions). Separately, [fitness.md](fitness.md)
and [email.md](email.md) propose "webhook vs. scheduled pull" as an open choice; for a
localhost desktop app there is no choice — **webhooks require a publicly reachable URL
the app doesn't have**. Polling (or sync-on-demand) is the only viable mode until a
hosted component exists. Both decisions should be written down before the first
integration: OS-keychain-backed token storage (e.g. the `keyring` library), and
poll-based sync.

### R6 — Presentation baked into contracts

`store.create_memory()` stamps `when="just now"` — a display string stored as data.
Once persisted, every memory would read "just now" forever. The rich task model carries
the same confusion: `due: "11:00am" | "Overdue" | "Tomorrow"` is display text alongside
a real `deadline` date. The docs already note the fix in places (real timestamps in
[data-store.md](data-store.md); `late` marked derived in [tasks.md](tasks.md);
[habits.md](habits.md) gets it exactly right with "streak should be derived, not
stored"). Elevate that instinct to a stated rule for all schemas: **store facts (UTC
timestamps, dates, numbers), derive display strings on read** — and apply it before any
row is durably written, because it's a data migration afterwards.

### R7 — Store contract subtleties

Three behaviors of `store.py` should be pinned down as intended-or-not before they
become the de-facto DB contract ([data-store.md](data-store.md) already asks for this):

- **Fields can never be set to null.** The router strips unset fields
  (`exclude_unset=True`) and the store *also* skips `None` values. Harmless for
  `{label, done}`, but the moment the model grows optional fields (clearing a
  `deadline`), this double filter makes "set to null" inexpressible. Decide the
  patch semantics once, in one layer.
- **The shallow-copy claim oversells.** `list(self.tasks)` copies the list, not the
  dicts inside it — a caller mutating a returned dict mutates the store. Routers
  serialize immediately so nothing breaks today, but the documented guarantee
  ("callers can't mutate internal state") is stronger than the code.
- **Reads are unlocked.** Fine under CPython for these operations, and the DB swap
  dissolves it — but the interface contract should say what concurrent readers may
  assume.

### R8 — The `screen` vocabulary is unvalidated

The backend emits screen names (`"home"`, `"tasks"`, …) as bare strings and `App.jsx`
switches on them; an unknown value dead-ends into the Placeholder. The docs already
propose constraining the *action* vocabulary so an LLM "can't hallucinate a screen that
doesn't exist" — do the same for `screen`: one enum in `schemas.py`, validated by
Pydantic, mirrored in the action contract the LLM is constrained to.

## The open decisions

Each decision the docs flag, with options and a recommendation. Effort/fit columns are
relative to the stated next phase (real LLM + iPhone client).

### D1 — The two-task-model split

**Context.** Backend serves `{id, label, done}`; the Tasks screen keeps a rich local
model (group, deadline, priority, list, subtasks, labels, reminders, files).
[tasks.md](tasks.md): "resolve it before adding fields piecemeal."

| Option | Effort now | Cost later | Fit with LLM/iPhone |
| --- | --- | --- | --- |
| A. Keep two models (status quo) | None | High — every future task feature lands twice, and Home/Tasks stay inconsistent | Poor — iPhone would inherit the split |
| B. **Unify on the rich model server-side; simple list = a projection** | Moderate — schema + migrate `TasksScreen` to the API | Low — one model, optional fields | Strong — iPhone needs the rich model anyway; assistant tools get one target |
| C. Two tiers with a sync/link protocol | High — invent tier reconciliation | High — a sync protocol is more machinery than optional fields | Weak — complexity without a payoff |

**Recommendation: B.** The rich model is a strict superset and is already fully
specified in [tasks.md](tasks.md)'s table — the schema design work is done. Home and
the assistant read the same rows and simply use fewer fields (or a
`?view=simple` projection if payload size ever matters). Do it together with the DB
migration ([D5](#d5--persistence-migration)) so the schema lands once. The only heavy
field is `files` (implies upload/storage) — keep the column, defer the upload path.
Until then: freeze both models.

### D2 — Assistant write pattern

**Context.** Today: assistant returns `action.makeTask`, the client POSTs. The docs ask
whether to mirror that per domain (`makeEvent`, `logMeal`, `makeNote`, `transfer`) or
have the assistant call domain services directly.

| Option | Effort now | Cost later | Fit with LLM/iPhone |
| --- | --- | --- | --- |
| A. Client-mediated `makeX` per domain | Low per action | High — N clients × M actions; every new action is re-implemented per client; replies assert success before the write happens | Poor — iPhone re-implements every action; LLM can't see tool results before composing its reply |
| B. **Server-side tool execution** (LLM tool loop calls domain services; `action` card reports what happened) | Moderate — arrives naturally with the LLM swap | Low — new actions are server-only; all clients get them for free | Strong — this is exactly the tool-use shape of modern LLM APIs; replies become truthful by construction |
| C. Hybrid: server executes, client confirms destructive actions | B + a confirmation protocol | Low | Needed eventually for sensitive domains (finance) |

**Recommendation: B, adopted at the LLM swap — evolving toward C for sensitive
actions.** The property worth preserving from today's design is *no hidden conversation
state in the server process* — and that survives B: keep `/chat` stateless-per-request
by having the client send the transcript with each call. The property **not** worth
preserving is *no side effects*: that was the mock's property, not the product's — the
product promises "an assistant that performs actions," and R2 shows the copy already
writes checks the architecture can't cash. With server-side execution the reply is
composed *after* the tools run, so "Done — added to Tasks" is true by construction, and
the iPhone client inherits every action for free. Keep client-mediated `makeTask` (and
add `makeNote` now — it's a one-day change) as the interim pattern only.

### D3 — Shared LLM client

**Context.** Assistant chat, Email triage/drafts, and People outreach are all
LLM-backed. One client or three?

**Recommendation: one module (`app/llm.py`), no provider abstraction yet.** A single
client owns the API key, model config, retry/timeout policy, request logging, and a
cost ledger; each feature owns only its prompts and tool schemas. Wrap one provider
with a deliberately small surface (a `complete()` and a `tool_loop()`), and skip the
multi-provider abstraction layer until a second provider is actually wanted — an
interface with one implementation is the cheapest abstraction to add later and the most
speculative one to add now. This module is also the single place to enforce the
redaction/privacy policy [email.md](email.md) asks about (what message content is sent
to the model).

### D4 — Offline fallback and engine parity

**Context.** R1: parity is already manual and becomes impossible post-LLM.
[assistant.md](assistant.md): "what does `assistantLogic.js` do then?"

| Option | Effort now | Cost later | Fit with LLM/iPhone |
| --- | --- | --- | --- |
| A. Keep chasing parity | Ongoing manual sync | Unpayable post-LLM — parity becomes undefined | Fails at the swap |
| B. **Honest degraded mode** — shrink fallback to capture intents only, with copy that admits offline | Small — delete most of `assistantLogic.js` | Low | Clean — offline still captures tasks/notes, never fabricates |
| C. Queue-and-sync — capture offline, process on reconnect | High — outbox, reconciliation | Moderate | Right shape for iPhone (real offline windows) — later |

**Recommendation: B now, C when the iPhone client lands.** Redefine the fallback's job
from "impersonate the assistant" to "don't lose the user's input": keep only the
task/note capture intents, label the state in the UI ("offline — saved, I'll think
about this properly later"), and delete the canned-figure replies ("you're at 1,910
kcal", "Moved $120…") — offline, those are fabrications twice over. This also dissolves
the sync problem: a ~20-line capture matcher doesn't need parity with anything.

### D5 — Persistence migration

**Context.** In-memory store → real DB behind the same method names. The README and
[data-store.md](data-store.md) suggest Postgres + SQLAlchemy.

| Option | Effort now | Cost later | Fit with LLM/iPhone |
| --- | --- | --- | --- |
| A. **SQLite + SQLAlchemy + Alembic** | Low — no server process, file-backed | Low — same ORM code; Postgres swap stays open behind the same interface | Strong — one backend process is all an iPhone-on-LAN needs; fits a local-first "personal OS" |
| B. Postgres + SQLAlchemy | Moderate — a database server to install, run, back up | Low | Only pays off if a *hosted* backend appears |
| C. Stay in-memory longer | None | High — every planned function is blocked on persistence | Blocks the roadmap |

**Recommendation: A.** For a single-user local app with one backend process and low
write volume, Postgres is operational burden with no benefit at this scale; SQLite
gives durability now and identical SQLAlchemy code. The moment a hosted/multi-device
sync story appears (possibly with the iPhone), revisit — behind the same store
interface. Alongside the swap: real UTC timestamps (R6), the owner/user column
[data-store.md](data-store.md) says to "decide early" (add it defaulted to a single
user — cheap insurance against a painful backfill), Alembic migrations from day one,
and write the store-interface contract down, including the patch-null and copy
semantics from R7. Keep the single `Store` facade; carve per-domain SQLAlchemy models
underneath it as functions graduate.

> **Decision (2026-06-10) — supersedes the recommendation: B, hosted on Supabase (free
> tier), from the start.** User call — the account is already in hand, and it
> pre-positions the off-LAN iPhone story. Everything else in this section stands
> (SQLAlchemy + Alembic, same `Store` facade, owner column, UTC timestamps); only the
> backing moves from a local file to a Supabase connection string, used as **plain
> Postgres** — no supabase-js in the frontend, no Supabase Auth/RLS/realtime. Connect
> via the session pooler (direct is IPv6-only on free tier); mitigate free-tier
> inactivity-pause and no-automated-backups with daily use/keepalive + local `pg_dump`.

### D6 — External integrations stance

**Context.** Whoop, Gmail, Google Calendar, Plaid-style aggregation, contacts. Open per
doc: mirror vs. canonical, webhook vs. poll, token storage, and whether `/transfer`
moves real money.

**Recommendation, in four parts:**

- **Mirror-plus-annotations.** External systems stay the source of truth for what they
  originate (Whoop telemetry, email messages, bank transactions, provider events); the
  app layers its own data on top (triage category and drafts on email, budget category
  on transactions, manual workouts beside synced ones). The app is canonical only for
  what it originates: tasks, habits, memories, people-cadence metadata. This answers
  the "read-only mirror or own record?" question in [fitness.md](fitness.md) and keeps
  every sync one-directional to start — conflict resolution deferred until a real
  two-way need appears (likely Calendar, last).
- **Poll, don't webhook** — not a preference but a constraint while the app is
  localhost-only (R5). Sync on app focus + a timer is plenty for one user.
- **Tokens in the OS keychain** (via `keyring`), never plaintext on disk; decided and
  documented *before* the first integration lands.
- **`/transfer` is category reallocation only.** Never real money movement — the
  liability, auth, and provider complexity are out of scope for a personal dashboard,
  and the prototype's copy ("Moved $120 from Dining to Savings") is satisfied by a
  budget reallocation. Record this in [finance.md](finance.md) so it's a decision, not
  a default.

### D7 — Auth, multi-user, versioning, error model

**Context.** None today, single local user. The iPhone client is the forcing function.

**Recommendation: defer multi-user indefinitely; don't defer the iPhone's
prerequisites.** This is a personal OS — true multi-tenancy may never be needed (the
owner column from D5 covers the schema risk). What the iPhone actually forces:

- **Transport + pairing.** The moment the API leaves localhost, it needs at minimum a
  device-pairing bearer token, and TLS if it leaves the LAN. Design this with the
  iPhone work, not before.
- **Versioning: additive-only, no `/v1` ceremony.** With two first-party clients, a
  versioned-path scheme is process overhead; commit instead to additive-only schema
  evolution (new fields optional, nothing removed or renamed without a deprecation
  window), and expose a schema version in `/api/health` so clients can detect skew.
  Revisit only if a third-party client ever appears.
- **Error model: one envelope, and stop swallowing.** Standardize
  `{ error: { code, message } }` on the backend; in the frontend, distinguish
  "backend unreachable → graceful fallback" (correct today) from "backend errored →
  surface it" — the blanket `.catch(() => {})` will otherwise hide real sync failures
  the moment integrations land.

## Suggested build order

The docs leave sequencing open ("suggested order is yours to set"). Given the stated
next phase, foundations first, then domains ordered cheap-and-local before
integration-heavy:

| Phase | Work | Why this order |
| --- | --- | --- |
| 0 — Foundations | Supabase Postgres migration (per the D5 decision note) + rich task model + real timestamps + owner column (D1, D5) · `app/llm.py` + LLM swap with server-side tools, action/screen enums, structured `text` (D2, D3, R4, R8) · fallback shrunk to capture-only (D4) · `makeNote` immediately | Everything else depends on persistence and the LLM seam; these are also the decisions that get more expensive after the swap |
| 1 — Local domains | Habits → Calendar (local events, no Google sync yet) → Nutrition (manual log; LLM estimates macros) | No external dependencies; each adds a real assistant tool (`logMeal`, `makeEvent`), exercising the new write path |
| 2 — Integrations | Keychain token storage first · then Whoop (read-only mirror, simplest) → Email (read-only triage before send) → People (bootstrap from email senders) → Finance last (heaviest + most sensitive; consider CSV import before Plaid) | Ascending sensitivity and complexity; each integration reuses the token + poll machinery the first one builds |
| 3 — iPhone client | Port the iOS kit against the now-stable API; pairing/auth + error envelope land here (D7) | The API will have survived phases 0–2; freezing it earlier would be premature |

One forward-looking note for phase 2: once the LLM both *reads email* and *executes
tools*, untrusted email content enters the tool loop — a prompt-injected message could
try to invoke actions. Constrain which tools are callable from email-derived contexts
(triage/summarize: yes; transfer/send/delete: no, or behind the D2-option-C
confirmation), and treat that allowlist as part of the email function's design, not a
hardening afterthought.

## Action items

1. [ ] Add `makeNote` (assistant action + `ChatPanel` handler) — closes the only dishonest *capture* path; one-day change.
2. [ ] Freeze both task models; adopt D1 (rich model server-side) as part of the DB migration.
3. [ ] ~~Pick SQLite~~ Decided 2026-06-10: **Supabase Postgres (free tier)** + SQLAlchemy + Alembic (see D5 decision note); write the store-interface contract into [data-store.md](data-store.md), including patch-null and copy semantics (R7).
4. [ ] Replace `when`/display strings with stored UTC facts + derived display (R6) before first durable write.
5. [ ] Create `app/llm.py` (D3); swap the assistant to a server-side tool loop (D2); constrain `screen`/action vocabulary via enums in `schemas.py` (R8).
6. [ ] Move `text` to a structured/sanitized format and remove `dangerouslySetInnerHTML` (R4) — before the LLM swap.
7. [ ] Shrink `assistantLogic.js` to labeled capture-only fallback; delete canned-figure replies (D4).
8. [ ] Document the integrations stance in [backend-overview.md](backend-overview.md): mirror-plus-annotations, poll-only while local, keychain token storage (D6).
9. [ ] Record `/transfer` = budget reallocation only in [finance.md](finance.md) (D6).
10. [ ] Adopt the additive-only API policy + error envelope; stop blanket-swallowing API errors in the frontend (D7).
