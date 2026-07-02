# M5 Email Slice-2 — "Act on mail": Gmail writes + compose + user-initiated AI drafts

**Status:** user-approved design (brainstormed 2026-07-01). Implementation plan to follow via writing-plans.
**Depends on:** slice-1 (`m5-email-triage`, PR #2) merged to `main`; the stacked `m5-email-get-email-owner-scope` fix folded in first.
**Branch:** `m5-email-slice2` (stacked on slice-1 until PR #2 merges, then rebased onto `main`).

## 1. Goal

Turn the read-only triaged inbox into an email client you can *act from*: trash, reply, forward, send,
star, mark read/unread, and apply/remove labels — plus AI-drafted replies that are generated **only when
the user asks, with the user's own instructions**. This is the first slice of a 3-slice program whose end
state replaces day-to-day use of other email sites.

## 2. Program roadmap (user-approved decomposition — approach A: writes-first, staged)

| Slice | Name | Scope |
|---|---|---|
| **2 (this spec)** | Act on mail | Scope upgrade + re-consent; trash / read-unread / star / label apply-remove; send / reply / forward (plain-text, correct threading); AI-draft button in the compose editor; sort dropdown; privacy wave 2; migration 0006 |
| 3 | The whole mailbox | Gmail history-API incremental sync; full pagination; conversation-thread view; labels sidebar + label management (create/rename/delete); search (Gmail `q` proxy); bulk multi-select; attachment view/download |
| 4 | Many accounts | Multi-account model; **unified inbox + account filter chip** (user-chosen UX); correct From per reply; attachment upload on compose |

Explicitly deferred beyond slice 2: HTML/rich-text compose (plain text v1), autonomous assistant write
actions, spam controls, notifications, contacts autocomplete.

## 3. OAuth scopes + consent (slice 2)

- Request `https://www.googleapis.com/auth/gmail.modify` + `https://www.googleapis.com/auth/gmail.send`
  (replacing `gmail.readonly`; `modify` covers read-state/labels/trash, `send` covers sending). Both
  restricted; Testing mode + test user remains sufficient.
- Existing tokens keep reading but cannot write. A token lacking write scope is surfaced through the
  **existing needs-reauth machinery**: a "Grant email actions" reconnect banner until re-consent. Consent
  copy reminds the user to **tick the Gmail checkboxes** (live-validated gotcha: Google presents restricted
  scopes as unchecked checkboxes; an unticked box grants a scope-less token).
- The Google Cloud consent screen's scope list must be updated (user console action, documented in the plan).

## 4. Deletion = Trash (frozen decision)

`users.messages.trash` only. Permanent delete requires the full-access `https://mail.google.com/` scope —
not requested. Trashed mail leaves the app (local row deleted after Gmail confirms) and sits in Gmail's
Trash (Google auto-purges ~30 days). Recoverable from Gmail; matches Gmail's own UX.

## 5. Provider layer — `EmailProvider` protocol + `GoogleProvider` (httpx, no SDK)

New protocol methods (names frozen; Gmail endpoints `[confirm-against-live]` values only):

```python
def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
    # POST {GMAIL_API_BASE}/messages/send  {"raw": base64url(raw), "threadId": thread_id?}
    # returns the new message id. Raises GoogleAuthError on auth/transport failure.
def trash_message(self, source_id: str) -> None: ...
    # POST {GMAIL_API_BASE}/messages/{id}/trash
def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None: ...
    # POST {GMAIL_API_BASE}/messages/{id}/modify {"addLabelIds":[...], "removeLabelIds":[...]}
    # Also implements read/unread (UNREAD label) and star (STARRED label).
def list_labels(self) -> list[dict]: ...
    # GET {GMAIL_API_BASE}/labels -> [{"id","name","type"}...] for the label menu.
```

RFC-822 assembly is a pure helper (`_build_rfc822(to, cc, subject, body, in_reply_to, references) -> bytes`)
using stdlib `email.message` — replies carry `In-Reply-To`/`References` from the original so Gmail threads
on both ends; `thread_id` (already stored per row) is passed to `send_message`.

## 6. Data model + store (migration `0006_email_actions`)

- `emails` gains `starred: bool default False` (from Gmail `STARRED` label) and `label_ids: JSON list
  default []`. **NO body column — unchanged.** `NormalizedEmail` gains the same two fields; sync maps them
  every pass (frozen-field tests updated accordingly).
- Store methods (all owner-scoped): `set_email_flags(id, unread=None, starred=None)`,
  `set_email_labels(id, label_ids)`, `delete_email(id)` (single local row, post-trash). Fold in the
  stacked `get_email` owner-scope fix first so every email accessor is consistent.

## 7. Email API additions (`routers/email.py`)

```
POST /api/email/send            {to, cc?, subject, body}                    -> {id}
POST /api/email/{id}/reply      {body}                                      -> {id}   # quotes original, threads
POST /api/email/{id}/forward    {to, body?}                                 -> {id}   # quotes original, Fwd:
POST /api/email/{id}/trash                                                  -> 204    # local row removed
POST /api/email/{id}/flags      {unread?: bool, starred?: bool}             -> EmailOut
POST /api/email/{id}/labels     {add: [label_id], remove: [label_id]}       -> EmailOut
GET  /api/email/labels                                                      -> [{id,name,type}]
POST /api/email/draft           {instructions, email_id?, mode: new|reply|forward, notes?} -> {draft}
```

**Confirm-first everywhere:** the Gmail call happens first; the local row/response updates only on success.
A Gmail failure returns an HTTP error and changes nothing locally.

## 8. Compose + AI drafting (user-approved UX)

One compose overlay in EmailScreen (right pane, app card style) shared by New / Reply / Forward. Reply
pre-fills recipient + `Re:` + quoted original below a divider; Forward pre-fills `Fwd:` + quote. Plain-text
send (v1).

**AI drafting is a button IN the compose editor's toolbar** (user-specified):

- A ✨ **AI draft** button in the body editor's toolbar. Clicking it opens a small inline instruction input
  ("what should it say?"). Anything already typed in the body is passed as context — rough notes become the
  email — or the body can be empty and instructions alone drive the draft.
- **Draft** inserts the generated text into the editor (replacing notes); fully editable; the button then
  offers **Regenerate** (same or tweaked instructions).
- **Nothing is ever generated automatically** — the model runs only on that button press. **Send is always
  a separate human click.** Drafts are not persisted server-side; they live in the compose box until sent
  or discarded.
- Backend: `app/email_draft.py` mirroring `email_triage`'s shape — module-level `configure(fake)` seam,
  `draft(instructions, notes, original: dict | None, mode) -> str | None`, Claude via `app/llm.py` at
  `settings.assistant_model`, failure returns `None` (UI shows "couldn't draft — try again"), never raises.
  Input context: instructions + typed notes + (for reply/forward) the original's sender/subject/snippet +
  bounded body excerpt fetched on demand (transits, never stored — same posture as triage).

## 9. Assistant (chat) stance — read-only writes, draft hand-off

No autonomous send/trash/label tools this slice. One new tool: `draft_email` — the assistant prepares a
draft (via `email_draft`) and returns it with an action card that opens the compose pane pre-filled; the
send is always the user's click. Autonomous write tools (with confirmation cards) are a later-slice
decision once the write path has mileage.

## 10. UI (EmailScreen additions)

- Reading-pane **action bar**: Reply · Forward · Star · Read/Unread · Label menu (from `GET /labels`) ·
  Trash.
- List rows gain a star indicator (unread dot exists).
- **Sort dropdown** on the inbox: newest / oldest / sender / unread-first — client-side over the synced
  list (sort-at-scale arrives with slice 3 pagination).
- Compose overlay per §8. All actions confirm-first with inline error states; a failed send never clears
  the compose box.

## 11. Known interim gap (accepted)

Slice 2 is **write-through only**: changes made elsewhere (e.g., reading mail on the phone) do not reflect
in ScuffedOS until slice 3's history-API incremental sync. The app's own actions keep both sides
consistent; the sync tick continues to pick up *new* mail.

## 12. Privacy policy wave 2 (all three copies)

"Read-only" language becomes "reads your mailbox, and acts on it **only when you take an action**": lists
the user-initiated actions (trash/label/read-state/send), states AI drafts are generated only on the
user's request with the user's instructions (and not stored), and that outbound mail is sent through
Gmail itself (Sent folder stays truthful). Canonical markdown → corp-site HTML → gist, same sync
convention.

## 13. Testing + validation

- TDD per task; suite + M4 fitness guardrail stay green; frontend `npm run build` green.
- `FakeGmailHTTP` extended to record `POST`s (send/trash/modify bodies + URLs) so the REAL provider write
  methods are driven network-free; label-list fixtures.
- `email_draft.configure(None)` seam installed in conftest's `no_external_services` (mirrors triage;
  committed atomically with the module).
- RFC-822 builder unit-tested (headers, quoting, In-Reply-To/References, unicode).
- `smoke_google` gains a live **write leg**: send a message to self → verify it arrives + threads → trash
  it → verify gone. Live validation includes the re-consent flow (scope upgrade) and browser verification
  of the action bar + compose + AI-draft button.

## 14. Out of scope (this slice)

Threads view, pagination, search, bulk select, label management CRUD, attachments (view or send), multiple
accounts, HTML compose, autonomous assistant writes, spam, notifications, contacts — all assigned to
slices 3/4 per §2.
