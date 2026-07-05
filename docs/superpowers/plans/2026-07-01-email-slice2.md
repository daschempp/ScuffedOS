# M5 Email Slice-2 ("Act on mail") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gmail writes (trash / star / read-unread / labels), send / reply / forward with correct threading, a compose overlay whose editor carries a user-initiated AI-draft button, a sort dropdown, the `gmail.modify`+`gmail.send` scope upgrade with a re-consent gate, privacy wave 2, and migration 0006 — per the approved spec `docs/superpowers/specs/2026-07-01-email-slice2-design.md`.

**Architecture:** Extends slice-1's seams without rework: `GoogleProvider` gains four write methods over the same httpx `_transport()`/`configure(fake_http=...)` seam; the store gains flag/label/delete methods (all owner-scoped, confirm-first — Gmail succeeds before any local write); `routers/email.py` gains the write endpoints; `email_draft.py` mirrors `email_triage.py`'s configure-seam shape and runs ONLY on explicit user request; EmailScreen gains an action bar, sort, and a compose overlay. Write capability is surfaced as a derived `can_write_email` boolean (raw scopes are never serialized to the client — existing privacy decision in `_provider_account_dict`).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic (0006 chains onto 0005), httpx (hand-rolled Gmail REST — NO google SDK), stdlib `email.message` for RFC-822, Anthropic SDK via `app/llm.py` (drafts at `settings.assistant_model`), pytest + TestClient (SQLite), React + Vite frontend.

## Global Constraints

- **The full test suite must stay green — including the entire M4 fitness suite AND all slice-1 email tests.** Baseline on this branch: `346 passed, 1 skipped` (the 1 skip = Postgres-only migration test). Run `cd backend && python -m pytest` and report the count; green before any task is complete.
- **Message BODIES are never persisted** — the `emails` table gains `starred` and `label_ids` in 0006 but NO body column, ever. Draft text is never persisted server-side.
- **Deletion = Trash** (`users.messages.trash`), never permanent delete; the full-access `https://mail.google.com/` scope is NOT requested.
- **Confirm-first writes:** every action calls Gmail first and mutates local state ONLY on success. A Gmail failure returns an HTTP error (502 for upstream failures) and changes nothing locally. A failed send never loses compose content (frontend keeps the box intact).
- **AI drafting is user-initiated ONLY.** `email_draft.draft(...)` runs only from `POST /api/email/draft` (the ✨ button) or the assistant's `draft_email` tool. Nothing generates on message open/read/sync. Failure returns `None` → HTTP 503; never raises.
- **No autonomous assistant writes this slice.** The ONLY new assistant tool is `draft_email` (prepares a draft + action card that opens compose). The registration test must assert `send_email` / `trash_email` / `label_email` are absent.
- **Plain-text compose v1** (RFC-822 `text/plain; charset=utf-8`). HTML compose is out of scope.
- **No new runtime dependencies.** Gmail writes over `httpx` via the existing `_transport()` seam; RFC-822 via stdlib `email.message`; NO google SDK.
- **`[confirm-against-live]` names are FROZEN:** endpoint URL values, request params, and JSON paths are confirmed against live Gmail during Task 20, but the constant names and method signatures below never change. Downstream tasks code against the frozen names.
- **Scopes:** `GOOGLE_SCOPES` becomes `"openid email profile https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.send"` (readonly KEPT so slice-1 URL assertions hold; modify supersedes it functionally). Write capability = stored granted scopes contain BOTH `gmail.modify` and `gmail.send`.
- **Python/test conventions (user CLAUDE.md):** run the full suite after changes and report "X tests passing"; avoid `&&` chains for steps that may return non-zero; venv interpreter `/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python`, pytest runs from `backend/`.
- **Branch:** all slice-2 work lands on `m5-email-slice2` (already rebased on main at the merged slice-1 + owner-scope fix).
- **Deferred — DO NOT build:** threads view, pagination, search, bulk select, label CRUD management, attachments (view or send), multi-account, HTML compose, spam, notifications, autonomous assistant writes (spec §2/§14).

## Interface Contract (single source of truth — signatures frozen)

### A. Scope surface — `app/providers/google.py`, `app/store.py`, `app/schemas.py`

```python
# google.py (value change only; name frozen):
GOOGLE_SCOPES = ("openid email profile "
                 "https://www.googleapis.com/auth/gmail.readonly "
                 "https://www.googleapis.com/auth/gmail.modify "
                 "https://www.googleapis.com/auth/gmail.send")   # [confirm-against-live]

# store.py — module-level helper next to _provider_account_dict:
_EMAIL_WRITE_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",
                       "https://www.googleapis.com/auth/gmail.send")
def _can_write_email(scopes: str) -> bool: ...   # True iff BOTH substrings present
# _provider_account_dict gains ONE derived key (raw scopes still never serialized):
#   "can_write_email": _can_write_email(p.scopes)

# schemas.py — ProviderStatus gains (additive, default False so M4 tests pass unchanged):
#   can_write_email: bool = False
```

Frontend gate: google `connected` but `can_write_email == false` → "Enable email actions" banner (CTA = `api.oauthConnect('google')` → re-consent with the new checkboxes); write UI (action bar, compose) hidden until true.

### B. RFC-822 builder — `app/providers/google.py` (module-level, pure)

```python
def _build_rfc822(*, to: str, subject: str, body: str, cc: str | None = None,
                  in_reply_to: str | None = None, references: str | None = None) -> bytes: ...
# stdlib email.message.EmailMessage; text/plain utf-8; sets To/Cc/Subject/
# In-Reply-To/References when given; From is omitted (Gmail sets the
# authenticated sender). Returns as_bytes().
```

### C. Provider write methods — `EmailProvider` protocol (`base.py`) + `GoogleProvider`

```python
def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
    # POST {GMAIL_API_BASE}/messages/send  json={"raw": <base64url>, "threadId": ...?}
    # -> returns new message id (json["id"]). GoogleAuthError on status >= 400.
def trash_message(self, source_id: str) -> None: ...
    # POST {GMAIL_API_BASE}/messages/{id}/trash   (empty json body)
def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None: ...
    # POST {GMAIL_API_BASE}/messages/{id}/modify  json={"addLabelIds":[...],"removeLabelIds":[...]}
    # Read/unread == remove/add "UNREAD"; star/unstar == add/remove "STARRED".
def list_labels(self) -> list[dict]: ...
    # GET {GMAIL_API_BASE}/labels -> json["labels"] as [{"id","name","type"}, ...]
def get_message_meta(self, source_id: str) -> dict: ...
    # GET {GMAIL_API_BASE}/messages/{id}?format=metadata
    #     &metadataHeaders=Message-ID&metadataHeaders=References&metadataHeaders=Subject&metadataHeaders=From
    # -> {"message_id": <Message-ID hdr or "">, "references": <References hdr or "">,
    #     "subject": str, "from_email": str}   (reply threading inputs)
```

All five raise `GoogleAuthError` on auth/transport failure (same `_get`-style status check; POSTs go through a new `_post(url, json)` mirroring `_get`). A `FakeGmailHTTP` extension records POSTs: `self.posts: list[tuple[str, dict]]`, `def post(self, url, data=None, headers=None, json=None)` routes `/messages/send` → `{"id": "sent-1", "threadId": <echo>}`, `/trash` and `/modify` → `{}`; `get` routes `/labels` → `{"labels": [...]}` from a constructor param `labels=[...]`.

### D. Data model — migration `0006_email_actions` + model + `NormalizedEmail`

```python
# models.Email gains:
starred: Mapped[bool] = mapped_column(default=False)
label_ids: Mapped[list] = mapped_column(JSONField, default=list)
# migration 0006: revision "0006", down_revision "0005"; add_column starred
# (Boolean, nullable=False, server_default=sa.false()) + label_ids (JSONField,
# nullable=False, server_default='[]'); downgrade drops both. Parity with model.

# NormalizedEmail gains (frozen-field test updated to exactly 12 fields):
starred: bool = False
label_ids: list = field(default_factory=list)
# _to_email maps: starred = "STARRED" in labelIds; label_ids = msg["labelIds"] or [].
# _EMAIL_FIELDS gains "starred", "label_ids" (sync write-through keeps Gmail authoritative).
# _email_dict gains "starred": e.starred, "label_ids": e.label_ids or [].
```

### E. Store write methods — `app/store.py` (all owner-scoped, dicts out)

```python
def set_email_flags(self, email_id: int, unread: bool | None = None,
                    starred: bool | None = None) -> dict | None: ...
    # None field = unchanged; returns _email_dict or None if id absent (owner-scoped).
def set_email_labels(self, email_id: int, label_ids: list[str]) -> dict | None: ...
    # replaces the stored label list (router computes it from add/remove); also
    # re-derives unread/starred from the new list ("UNREAD"/"STARRED" membership).
def delete_email(self, email_id: int) -> bool: ...
    # single local row post-trash; True iff deleted (owner-scoped).
```

### F. API — `routers/email.py` additions + `schemas.py` request/response models

```python
class SendEmail(BaseModel):   to: str; cc: str | None = None; subject: str; body: str
class ReplyEmail(BaseModel):  body: str
class ForwardEmail(BaseModel): to: str; body: str
class FlagsPatch(BaseModel):  unread: bool | None = None; starred: bool | None = None
class LabelsPatch(BaseModel): add: List[str] = []; remove: List[str] = []
class DraftRequest(BaseModel):
    instructions: str; notes: str = ""; mode: Literal["new","reply","forward"] = "new"
    email_id: int | None = None
class LabelOut(BaseModel):    id: str; name: str; type: str
# EmailOut gains: starred: bool = False; label_ids: List[str] = []   (additive)

POST /api/email/send            SendEmail                    -> {"id": <new source id>}
POST /api/email/{id}/reply      ReplyEmail                   -> {"id": ...}   # to=original sender,
    # subject = "Re: <orig>" (no double-Re), In-Reply-To/References from get_message_meta,
    # thread_id passed to send_message.
POST /api/email/{id}/forward    ForwardEmail                 -> {"id": ...}   # subject "Fwd: <orig>"
POST /api/email/{id}/trash                                   -> 204          # provider.trash -> store.delete_email
POST /api/email/{id}/flags      FlagsPatch                   -> EmailOut     # modify_labels then set_email_flags
POST /api/email/{id}/labels     LabelsPatch                  -> EmailOut     # modify_labels then set_email_labels
GET  /api/email/labels                                       -> list[LabelOut]
POST /api/email/draft           DraftRequest                 -> {"draft": str}   # 503 when draft() -> None
```

Error mapping: unknown id → 404 (before any provider call); `GoogleAuthError`/provider failure → 502 `{"detail":"Gmail rejected the action"}` with NO local change. Route-order hazard: literal routes (`/send`, `/draft`, `/labels`) MUST be declared before `/{email_id}` in the router (slice-1 declares `/inbox` before `/{email_id}` — same pattern).

### G. AI draft — `app/email_draft.py` (NEW; mirrors `email_triage` seam shape)

```python
_override: object | None | str = "unset"
def configure(override="unset") -> None: ...     # fake with .draft(...) | None -> always None | "unset" real
def draft(instructions: str, notes: str, mode: str, original: dict | None) -> str | None: ...
    # original (reply/forward): {"from_name","from_email","subject","body_excerpt"} — body excerpt
    # bounded 2048 chars, fetched live by the ROUTER via provider.get_message + truncation
    # (transits, never stored). Claude via llm.stream at settings.assistant_model. Any
    # failure/offline -> None. NEVER raises. NEVER called except from the draft endpoint/tool.
```

conftest `no_external_services` installs `email_draft.configure(None)` / restores `"unset"` — committed atomically with the module (slice-1 conftest hazard rule).

### H. Assistant — `app/tools.py`

```python
{"name": "draft_email",
 "description": "Draft an email with AI from the user's instructions — optionally replying to an existing message by id (from get_inbox). Returns the draft text; the user reviews and sends it from the compose pane. Never sends.",
 "input_schema": {"type":"object","properties":{
     "instructions": {"type":"string"},
     "email_id": {"type":"integer"}},
   "required": ["instructions"], "additionalProperties": False},
 "run": _draft_email}
# _draft_email returns ({"draft": ..., "reply_to": <compact email or None>},
#                       _email_action("Draft ready", "Open compose to review & send"))
# NO send/trash/label tools; registration test asserts their absence.
```

### I. Frontend — `frontend/src/lib/api.js` + `frontend/src/screens/EmailScreen.jsx`

```js
emailSend:    (payload) => request('/api/email/send',    { method: 'POST', body: payload }),
emailReply:   (id, payload) => request(`/api/email/${id}/reply`,   { method: 'POST', body: payload }),
emailForward: (id, payload) => request(`/api/email/${id}/forward`, { method: 'POST', body: payload }),
emailTrash:   (id) => request(`/api/email/${id}/trash`,  { method: 'POST' }),
emailFlags:   (id, payload) => request(`/api/email/${id}/flags`,  { method: 'POST', body: payload }),
emailLabels:  (id, payload) => request(`/api/email/${id}/labels`, { method: 'POST', body: payload }),
emailLabelList: () => request('/api/email/labels'),
emailDraft:   (payload) => request('/api/email/draft',   { method: 'POST', body: payload }),
```
(Match the existing `request()` body convention in api.js exactly — check how POST bodies are passed in slice-1 helpers before assuming `body:`.)

EmailScreen: write-gate banner (contract §A); reading-pane action bar Reply · Forward · Star · Read/Unread · Label menu (from `emailLabelList`) · Trash; list star indicator; sort dropdown (`newest` default | `oldest` | `sender` | `unread first`) applied client-side inside the existing `groups` memo; compose overlay (modes new/reply/forward; reply/forward prefill quoted original from the already-loaded `detail.body` below `\n\n--- On <when>, <from> wrote: ---\n`); ✨ AI-draft button in the compose editor toolbar → inline instruction input → `emailDraft({instructions, notes: <current body>, mode, email_id})` → inserts result into the editor; Draft→Regenerate after first use; failed send keeps the box intact. All actions confirm-first then `refresh()`.

### J. Task → phase map

| Phase | Tasks | Owner theme |
|---|---|---|
| P1 provider writes | 1–4 | scopes + can_write_email; _build_rfc822; send_message; trash/modify/list/meta |
| P2 data layer | 5–7 | migration 0006 + model; NormalizedEmail/mapping/EmailOut; store write methods |
| P3 write API | 8–11 | trash; flags; labels+list; send/reply/forward |
| P4 AI draft | 12–14 | email_draft module; draft endpoint; assistant draft_email tool |
| P5 frontend | 15–17 | api.js helpers + write-gate; action bar + star + sort; compose + AI button |
| P6 privacy+smoke | 18–19 | privacy wave 2 (canonical + corp-site; gist = user-approved step); smoke write leg |
| P7 live gate | 20 | consent-screen scope update, re-consent, browser verify, full-suite green |

---

<!-- TASK BODIES 1-20 ASSEMBLED BELOW -->

### Task 1: Scope upgrade + can_write_email surface

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py`

**Interfaces:**
- Consumes: `app.providers.google.GOOGLE_SCOPES` (existing name, value changes); `ProviderAccount.scopes` (existing model column, `store.py` line 1179 `row.scopes = tokens.scopes or ""`); `app.schemas.ProviderStatus` (existing model, `schemas.py` lines 380-385).
- Produces: `app.store._EMAIL_WRITE_SCOPES: tuple[str, str]`; `app.store._can_write_email(scopes: str) -> bool`; `_provider_account_dict(p)["can_write_email"]: bool`; `app.schemas.ProviderStatus.can_write_email: bool = False` — consumed by Task 15 (frontend write-gate banner) and the live-gate Task 20.

- [ ] **Step 1: Write the failing scope-string test.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`, replace the existing `test_scopes_include_openid_email_profile_and_gmail_readonly` (current lines 74-78):
  ```python
  def test_scopes_include_openid_email_profile_and_gmail_readonly():
      # The frozen scope string — read-only Gmail plus identity for the sub.
      assert GOOGLE_SCOPES == (
          "openid email profile https://www.googleapis.com/auth/gmail.readonly"
      )
  ```
  with:
  ```python
  def test_scopes_include_openid_email_profile_readonly_modify_and_send():
      # The frozen scope string — readonly KEPT (slice-1 URL assertions hold)
      # plus modify (read-state/labels/trash) plus send.
      assert GOOGLE_SCOPES == (
          "openid email profile "
          "https://www.googleapis.com/auth/gmail.readonly "
          "https://www.googleapis.com/auth/gmail.modify "
          "https://www.googleapis.com/auth/gmail.send"
      )
      assert "https://www.googleapis.com/auth/gmail.modify" in GOOGLE_SCOPES
      assert "https://www.googleapis.com/auth/gmail.send" in GOOGLE_SCOPES
  ```
  This also requires updating `test_exchange_code_returns_tokens` (lines 81-101), which asserts `tok.scopes == GOOGLE_SCOPES` and `data["client_secret"] == "gsecret"` — that assertion needs no change since it compares against the (now-updated) `GOOGLE_SCOPES` constant directly, not a literal. Leave it as-is.

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_google_oauth.py -q
  ```
  Expected failure: `test_scopes_include_openid_email_profile_readonly_modify_and_send` fails because `GOOGLE_SCOPES` (google.py line 41) is still `"openid email profile https://www.googleapis.com/auth/gmail.readonly"`. `test_authorize_url_has_all_oauth_params_and_offline_consent` (line 58) also still passes since it compares `q["scope"] == [GOOGLE_SCOPES]` against the live constant (self-consistent), so only the new test fails.

- [ ] **Step 3: Implement the scope value change.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, replace line 41:
  ```python
  GOOGLE_SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.readonly"
  ```
  with:
  ```python
  GOOGLE_SCOPES = ("openid email profile "
                   "https://www.googleapis.com/auth/gmail.readonly "
                   "https://www.googleapis.com/auth/gmail.modify "
                   "https://www.googleapis.com/auth/gmail.send")   # [confirm-against-live]
  ```

- [ ] **Step 4: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_google_oauth.py -q
  ```
  Expected: all tests in the file pass (15 tests).

- [ ] **Step 5: Write the failing `_can_write_email` store test.** Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py` (after the last test, `test_fitness_oauth_routes_are_removed`, currently ending at line 187), first adding the needed import at the top of the file (alongside the existing `from .fakes import FakeProvider` at line 17):
  ```python
  from .fakes import FakeEmailProvider, FakeProvider
  ```
  then append:
  ```python
  def test_status_surfaces_can_write_email_false_when_scopes_lack_write(client):
      providers.configure([FakeEmailProvider()])
      store.upsert_provider_account(
          "google",
          Tokens(
              access_token="a", refresh_token="r", expires_at=None,
              scopes="openid email https://www.googleapis.com/auth/gmail.readonly",
              provider_user_id="g1",
          ),
      )
      body = client.get("/api/oauth/status").json()
      p = body["providers"][0]
      assert p["provider"] == "google"
      assert p["can_write_email"] is False


  def test_status_surfaces_can_write_email_true_when_modify_and_send_both_granted(client):
      providers.configure([FakeEmailProvider()])
      store.upsert_provider_account(
          "google",
          Tokens(
              access_token="a", refresh_token="r", expires_at=None,
              scopes=(
                  "openid email profile "
                  "https://www.googleapis.com/auth/gmail.readonly "
                  "https://www.googleapis.com/auth/gmail.modify "
                  "https://www.googleapis.com/auth/gmail.send"
              ),
              provider_user_id="g1",
          ),
      )
      body = client.get("/api/oauth/status").json()
      p = body["providers"][0]
      assert p["can_write_email"] is True


  def test_status_can_write_email_requires_both_scopes_not_just_one(client):
      providers.configure([FakeEmailProvider()])
      store.upsert_provider_account(
          "google",
          Tokens(
              access_token="a", refresh_token="r", expires_at=None,
              # modify only, no send — must NOT count as write-capable.
              scopes="openid email https://www.googleapis.com/auth/gmail.modify",
              provider_user_id="g1",
          ),
      )
      body = client.get("/api/oauth/status").json()
      assert body["providers"][0]["can_write_email"] is False
      # Raw scopes are still never serialized to the client (existing privacy rule).
      assert "scopes" not in body["providers"][0]
  ```

- [ ] **Step 6: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_oauth.py -q
  ```
  Expected failure: `KeyError: 'can_write_email'` (or a pydantic validation gap) — `ProviderStatus` has no such field yet and `_provider_account_dict` doesn't produce it, so `body["providers"][0]["can_write_email"]` raises `KeyError`.

- [ ] **Step 7: Implement `_can_write_email` + wire it into `_provider_account_dict`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, add the module-level constant and helper directly above `_provider_account_dict` (currently at line 329):
  ```python
  _EMAIL_WRITE_SCOPES = (
      "https://www.googleapis.com/auth/gmail.modify",
      "https://www.googleapis.com/auth/gmail.send",
  )


  def _can_write_email(scopes: str) -> bool:
      """True iff the stored scope string grants BOTH gmail.modify and
      gmail.send (write capability for trash/flags/labels AND send/reply/
      forward). A readonly-only or partially-upgraded token is False."""
      return all(scope in scopes for scope in _EMAIL_WRITE_SCOPES)


  def _provider_account_dict(p: ProviderAccount) -> dict:
      """Client-safe view of a provider account — NEVER includes tokens,
      scopes, or meta (those are server-side only; see /status). Exposes ONE
      derived boolean (can_write_email) computed from raw scopes so the
      frontend gate never sees the scope string itself."""
      return {
          "provider": p.provider,
          "status": p.status,
          "connected_at": aware_utc(p.connected_at),
          "last_sync_at": aware_utc(p.last_sync_at),
          "provider_user_id": p.provider_user_id,
          "can_write_email": _can_write_email(p.scopes or ""),
      }
  ```
  Note: this replaces the ENTIRE existing `_provider_account_dict` function body (currently lines 329-338) — delete the old `return {...}` block and use the one above (with the docstring's "NEVER includes tokens, scopes, or meta" wording kept verbatim per the plan's anchor-accuracy rule, plus the new sentence about the derived boolean).

  Then in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, add the field to `ProviderStatus` (currently lines 380-385):
  ```python
  class ProviderStatus(BaseModel):
      provider: str
      status: Literal["connected", "needs_reauth"]
      connected_at: datetime
      last_sync_at: datetime | None
      provider_user_id: str | None = None
      can_write_email: bool = False
  ```

- [ ] **Step 8: Run the two targeted test files and confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_oauth.py tests/test_google_oauth.py -q
  ```
  Expected: all pass (existing `test_status_reflects_a_connected_account_without_tokens`, which asserts `"access_token" not in p and "refresh_token" not in p` on a `whoop` account, still passes unchanged — `can_write_email` is additive and whoop's empty scopes string yields `False` harmlessly).

- [ ] **Step 9: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: `349 passed, 1 skipped` (346 baseline + 3 new store/status tests added in Step 5; Step 1 is a 1-for-1 rewrite of an existing test, net zero). This is a relative estimate — report the exact printed count as the actual gate. Report "X tests passing" per the user's global convention.

- [ ] **Step 10: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/google.py app/store.py app/schemas.py tests/test_google_oauth.py tests/test_oauth.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): upgrade Gmail scopes to modify+send, surface can_write_email

  Slice-2 needs Gmail write access (trash/labels/flags/send). GOOGLE_SCOPES
  now requests gmail.modify and gmail.send alongside the kept gmail.readonly
  (contract §A). Store derives can_write_email from stored granted scopes
  without ever serializing raw scopes to the client, and ProviderStatus
  surfaces it additively so existing M4 tests pass unchanged.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2: `_build_rfc822` pure helper

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_rfc822.py`

**Interfaces:**
- Consumes: nothing new (pure stdlib `email.message.EmailMessage`).
- Produces: `app.providers.google._build_rfc822(*, to: str, subject: str, body: str, cc: str | None = None, in_reply_to: str | None = None, references: str | None = None) -> bytes` — consumed by Task 3 (`send_message` raw payload) and Task 9/10/11 (send/reply/forward endpoints via the router).

- [ ] **Step 1: Write the failing test file.** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_rfc822.py`:
  ```python
  """_build_rfc822 (M5 slice-2 contract §B) — pure stdlib email.message builder,
  no network. Real RFC-822 bytes assembled here are what Task 3's
  send_message base64url-encodes into the Gmail 'raw' field."""
  from email import policy
  from email.parser import BytesParser

  from app.providers.google import _build_rfc822


  def test_sets_to_cc_subject_headers():
      raw = _build_rfc822(
          to="priya@lighthouse.io", cc="team@lighthouse.io",
          subject="Re: moved deadline", body="Works for me.",
      )
      msg = BytesParser().parsebytes(raw)
      assert msg["To"] == "priya@lighthouse.io"
      assert msg["Cc"] == "team@lighthouse.io"
      assert msg["Subject"] == "Re: moved deadline"


  def test_cc_omitted_when_not_given():
      raw = _build_rfc822(to="a@x.com", subject="s", body="b")
      msg = BytesParser().parsebytes(raw)
      assert msg["Cc"] is None


  def test_from_header_is_never_set():
      # Gmail sets the authenticated sender; a From header here would be
      # ignored or rejected by the API.
      raw = _build_rfc822(to="a@x.com", subject="s", body="b")
      msg = BytesParser().parsebytes(raw)
      assert msg["From"] is None


  def test_body_is_utf8_plain_text_and_round_trips_emoji():
      raw = _build_rfc822(to="a@x.com", subject="s", body="Ship it \U0001F680 — thanks!")
      # policy=policy.default gives an EmailMessage-compatible parse tree with
      # .get_content(); the header-only tests above use the legacy default
      # policy since they only read headers.
      msg = BytesParser(policy=policy.default).parsebytes(raw)
      assert msg.get_content_type() == "text/plain"
      assert msg.get_content_charset() == "utf-8"
      assert msg.get_content().strip() == "Ship it \U0001F680 — thanks!"


  def test_in_reply_to_and_references_present_only_when_given():
      raw_plain = _build_rfc822(to="a@x.com", subject="s", body="b")
      msg_plain = BytesParser().parsebytes(raw_plain)
      assert msg_plain["In-Reply-To"] is None
      assert msg_plain["References"] is None

      raw_threaded = _build_rfc822(
          to="a@x.com", subject="Re: s", body="b",
          in_reply_to="<abc123@mail.gmail.com>",
          references="<abc123@mail.gmail.com>",
      )
      msg_threaded = BytesParser().parsebytes(raw_threaded)
      assert msg_threaded["In-Reply-To"] == "<abc123@mail.gmail.com>"
      assert msg_threaded["References"] == "<abc123@mail.gmail.com>"


  def test_returns_bytes_parseable_by_email_parser():
      raw = _build_rfc822(to="a@x.com", subject="s", body="b")
      assert isinstance(raw, bytes)
      msg = BytesParser().parsebytes(raw)
      assert msg["To"] == "a@x.com"
  ```

- [ ] **Step 2: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_rfc822.py -q
  ```
  Expected failure: `ImportError: cannot import name '_build_rfc822' from 'app.providers.google'` (the function does not exist yet).

- [ ] **Step 3: Implement `_build_rfc822`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, add the import at the top (alongside the existing `from email.utils import parseaddr, parsedate_to_datetime` at line 27):
  ```python
  from email.message import EmailMessage
  from email.utils import parseaddr, parsedate_to_datetime
  ```
  Then add the module-level function after `_parse_date` (currently ending at line 132, before the `class GoogleAuthError` at line 135):
  ```python
  def _build_rfc822(*, to: str, subject: str, body: str, cc: str | None = None,
                     in_reply_to: str | None = None, references: str | None = None) -> bytes:
      """Assemble a plain-text RFC-822 message for Gmail's messages.send (base64url
      of these bytes becomes the 'raw' field — see send_message). From is
      omitted: Gmail always sets it to the authenticated account regardless of
      what's supplied, so setting it here would be misleading. Uses stdlib
      email.message.EmailMessage so multi-byte body text (emoji, accents) is
      MIME-encoded correctly without a third-party dependency."""
      msg = EmailMessage()
      msg["To"] = to
      if cc:
          msg["Cc"] = cc
      msg["Subject"] = subject
      if in_reply_to:
          msg["In-Reply-To"] = in_reply_to
      if references:
          msg["References"] = references
      msg.set_content(body, subtype="plain", charset="utf-8")
      return msg.as_bytes()
  ```

- [ ] **Step 4: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_rfc822.py -q
  ```
  Expected: `6 passed`.

- [ ] **Step 5: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: baseline-from-Task-1 count + 6 new tests, `0 failed`. Report "X tests passing".

- [ ] **Step 6: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/google.py tests/test_rfc822.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): add _build_rfc822 pure RFC-822 message builder

  Module-level helper (stdlib email.message.EmailMessage, no new dependency)
  assembling plain-text send/reply/forward payloads per contract §B. From is
  intentionally omitted — Gmail always sets the authenticated sender.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 3: `GoogleProvider.send_message` + `_post` helper

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py`

**Interfaces:**
- Consumes: `_build_rfc822` (Task 2); `GoogleProvider._transport()`, `GoogleProvider._headers()`, `GoogleProvider._get()` (existing, google.py lines 163-170, 304-315); `GMAIL_API_BASE` (existing constant, google.py line 39); `GoogleAuthError` (existing, google.py line 135).
- Produces: `GoogleProvider._post(self, url: str, json: dict) -> dict` (mirrors `_get`); `GoogleProvider.send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str`; `EmailProvider.send_message(...)` protocol member (base.py) — consumed by Task 4 (sibling write methods reuse `_post`) and Task 11 (send/reply/forward router endpoints). `FakeGmailHTTP.posts: list[tuple[str, dict]]` and `FakeGmailHTTP.post(self, url, data=None, headers=None, json=None)` — consumed by Task 4's tests and Task 8-11's router tests.

- [ ] **Step 1: Extend `FakeGmailHTTP` to record and route POSTs first (test infra, not itself under test but needed by the failing tests below).** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`, replace the current `FakeGmailHTTP.post` (lines 218-219):
  ```python
      def post(self, url, data=None, headers=None):  # exchange/refresh/revoke
          return _FakeResponse({})
  ```
  with:
  ```python
      def post(self, url, data=None, headers=None, json=None):
          """OAuth token/revoke calls use data=; Gmail write calls use json=.
          Routes by URL suffix: /messages/send -> a synthetic sent message id
          (echoing threadId if the caller supplied one so threading tests can
          assert it round-trips); /trash and /modify -> {} (Gmail returns the
          updated message, but callers here don't need the body); anything
          else (OAuth) -> {} as before."""
          self.posts.append((url, json if json is not None else data))
          code = self._status_for(url)
          if code >= 400:
              return _FakeResponse({}, code)
          if url.endswith("/messages/send"):
              body = json or {}
              return _FakeResponse({"id": "sent-1", "threadId": body.get("threadId")})
          if url.endswith("/trash") or url.endswith("/modify"):
              return _FakeResponse({})
          return _FakeResponse({})
  ```
  And add `self.posts: list[tuple[str, dict]] = []` to `FakeGmailHTTP.__init__` (currently lines 193-198):
  ```python
      def __init__(self, messages: dict | None = None, list_ids: list[str] | None = None,
                   status: dict | None = None):
          self.messages = messages or {}          # id -> messages.get JSON
          self.list_ids = list_ids if list_ids is not None else list(self.messages)
          self.status = status or {}               # url-substring -> status_code
          self.gets: list[tuple[str, dict]] = []
          self.posts: list[tuple[str, dict]] = []
  ```

- [ ] **Step 2: Write the failing tests.** Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py` (after the last test, `test_html_only_body_is_stripped_to_plain_text_for_triage`, ending at line 141), adding a `base64` import at the top alongside existing imports:
  ```python
  import base64
  ```
  then append:
  ```python
  def test_send_message_posts_base64url_raw_and_returns_new_id():
      http = FakeGmailHTTP()
      raw = b"To: a@x.com\r\nSubject: s\r\n\r\nbody text\r\n"
      new_id = _provider(http).send_message(raw)
      assert new_id == "sent-1"
      url, payload = http.posts[0]
      assert url.endswith("/messages/send")
      decoded = base64.urlsafe_b64decode(payload["raw"] + "=" * (-len(payload["raw"]) % 4))
      assert decoded == raw
      assert "threadId" not in payload


  def test_send_message_passes_thread_id_when_given():
      http = FakeGmailHTTP()
      new_id = _provider(http).send_message(b"To: a@x.com\r\n\r\nb\r\n", thread_id="th1")
      assert new_id == "sent-1"
      url, payload = http.posts[0]
      assert payload["threadId"] == "th1"


  def test_send_message_auth_failure_raises_google_auth_error():
      http = FakeGmailHTTP(status={"/messages/send": 401})
      with pytest.raises(GoogleAuthError):
          _provider(http).send_message(b"To: a@x.com\r\n\r\nb\r\n")
  ```

- [ ] **Step 3: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_google_gmail.py -q
  ```
  Expected failure: `AttributeError: 'GoogleProvider' object has no attribute 'send_message'` (method does not exist yet).

- [ ] **Step 4: Implement `_post` + `send_message`.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, add the import at the top:
  ```python
  import base64
  ```
  (already present at line 22 — confirm, do not duplicate). Add `_post` immediately after `_get` (currently lines 311-315):
  ```python
      def _get(self, url: str, params: dict | None = None) -> dict:
          res = self._transport().get(url, headers=self._headers(), params=params)
          if getattr(res, "status_code", 200) >= 400:
              raise GoogleAuthError(f"Gmail GET {url} returned {res.status_code}")
          return res.json() or {}

      def _post(self, url: str, json: dict) -> dict:
          res = self._transport().post(url, headers=self._headers(), json=json)
          if getattr(res, "status_code", 200) >= 400:
              raise GoogleAuthError(f"Gmail POST {url} returned {res.status_code}")
          return res.json() or {}
  ```
  Then add `send_message` after `get_message` (the last method in the class, currently lines 358-365):
  ```python
      def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str:
          """POST messages.send with the RFC-822 bytes (from _build_rfc822)
          base64url-encoded into 'raw'. thread_id (when given, e.g. a reply)
          tells Gmail to thread the new message onto the existing conversation
          instead of starting a new one. Returns the new Gmail message id."""
          payload: dict = {"raw": base64.urlsafe_b64encode(raw_rfc822).decode("ascii").rstrip("=")}
          if thread_id:
              payload["threadId"] = thread_id
          result = self._post(f"{GMAIL_API_BASE}/messages/send", json=payload)
          return str(result["id"])
  ```

- [ ] **Step 5: Add `send_message` to the `EmailProvider` protocol.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`, replace the `EmailProvider` protocol (currently lines 101-104):
  ```python
  @runtime_checkable
  class EmailProvider(OAuthProvider, Protocol):
      def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
      def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
  ```
  with:
  ```python
  @runtime_checkable
  class EmailProvider(OAuthProvider, Protocol):
      def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
      def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
      def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
  ```

- [ ] **Step 6: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_google_gmail.py -q
  ```
  Expected: all tests in the file pass (13 tests: 10 existing + 3 new).

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior count + 3, `0 failed`. Report "X tests passing".

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/google.py app/providers/base.py tests/fakes.py tests/test_google_gmail.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): add GoogleProvider.send_message + _post transport helper

  _post mirrors the existing _get (auth headers, GoogleAuthError on >=400).
  send_message base64url-encodes an RFC-822 payload into Gmail's raw field,
  optionally threading onto an existing conversation via threadId (contract
  §C). FakeGmailHTTP now records/routes POSTs so downstream write methods and
  router tests stay network-free.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4: `trash_message` + `modify_labels` + `list_labels` + `get_message_meta`

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py`

**Interfaces:**
- Consumes: `GoogleProvider._post` and `GoogleProvider._get` (Task 3, google.py); `GMAIL_API_BASE` (existing constant); `_header` (existing helper, google.py lines 106-111); `GoogleAuthError`.
- Produces: `GoogleProvider.trash_message(self, source_id: str) -> None`; `GoogleProvider.modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None`; `GoogleProvider.list_labels(self) -> list[dict]`; `GoogleProvider.get_message_meta(self, source_id: str) -> dict` returning `{"message_id": str, "references": str, "subject": str, "from_email": str}`; matching `EmailProvider` protocol members — consumed by Task 8 (trash endpoint), Task 9 (flags endpoint), Task 10 (labels + list-labels endpoints), Task 11 (reply/forward threading via `get_message_meta`).

- [ ] **Step 1: Extend `FakeGmailHTTP` for `/trash`, `/modify`, `/labels`, and metadata-format GETs.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`, the `post` method already routes `/trash` and `/modify` to `{}` (added in Task 3 Step 1) — no change needed there. Add a `labels` constructor param and a `/labels` GET route. Replace the current `__init__` (as left by Task 3):
  ```python
      def __init__(self, messages: dict | None = None, list_ids: list[str] | None = None,
                   status: dict | None = None, labels: list[dict] | None = None):
          self.messages = messages or {}          # id -> messages.get JSON
          self.list_ids = list_ids if list_ids is not None else list(self.messages)
          self.status = status or {}               # url-substring -> status_code
          self.labels = labels or []               # [{"id","name","type"}, ...]
          self.gets: list[tuple[str, dict]] = []
          self.posts: list[tuple[str, dict]] = []
  ```
  and extend `get` (currently, post-Task-3, unchanged from the original lines 206-216) to route `/labels` before the messages.list fallback:
  ```python
      def get(self, url, headers=None, params=None):
          self.gets.append((url, dict(params or {})))
          code = self._status_for(url)
          if code >= 400:
              return _FakeResponse({}, code)
          if url.endswith("/labels"):
              return _FakeResponse({"labels": self.labels})
          # messages.get: '/messages/<id>' (has a segment after '/messages/')
          if "/messages/" in url:
              msg_id = url.rsplit("/messages/", 1)[1]
              return _FakeResponse(self.messages.get(msg_id, {}))
          # messages.list
          return _FakeResponse({"messages": [{"id": i} for i in self.list_ids]})
  ```
  (The `/messages/<id>` branch already handles `?format=metadata` requests transparently since `params` is recorded separately from the URL path and the same `messages` dict is keyed by id — a metadata-format test supplies a message dict containing only the requested headers.)

- [ ] **Step 2: Write the failing tests.** Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py` (after the Task 3 additions):
  ```python
  def test_trash_message_posts_to_trash_endpoint():
      http = FakeGmailHTTP()
      _provider(http).trash_message("m1")
      url, payload = http.posts[0]
      assert url.endswith("/messages/m1/trash")
      assert payload == {}


  def test_trash_message_auth_failure_raises():
      http = FakeGmailHTTP(status={"/trash": 401})
      with pytest.raises(GoogleAuthError):
          _provider(http).trash_message("m1")


  def test_modify_labels_posts_add_and_remove_label_ids():
      http = FakeGmailHTTP()
      _provider(http).modify_labels("m1", add=["STARRED"], remove=["UNREAD"])
      url, payload = http.posts[0]
      assert url.endswith("/messages/m1/modify")
      assert payload == {"addLabelIds": ["STARRED"], "removeLabelIds": ["UNREAD"]}


  def test_modify_labels_defaults_to_empty_lists():
      http = FakeGmailHTTP()
      _provider(http).modify_labels("m1")
      url, payload = http.posts[0]
      assert payload == {"addLabelIds": [], "removeLabelIds": []}


  def test_modify_labels_auth_failure_raises():
      http = FakeGmailHTTP(status={"/modify": 500})
      with pytest.raises(GoogleAuthError):
          _provider(http).modify_labels("m1", add=["STARRED"])


  def test_list_labels_gets_and_returns_label_dicts():
      http = FakeGmailHTTP(labels=[
          {"id": "STARRED", "name": "STARRED", "type": "system"},
          {"id": "Label_1", "name": "Family", "type": "user"},
      ])
      labels = _provider(http).list_labels()
      assert labels == [
          {"id": "STARRED", "name": "STARRED", "type": "system"},
          {"id": "Label_1", "name": "Family", "type": "user"},
      ]
      url, _ = http.gets[0]
      assert url.endswith("/labels")


  def test_list_labels_auth_failure_raises():
      http = FakeGmailHTTP(status={"/labels": 401})
      with pytest.raises(GoogleAuthError):
          _provider(http).list_labels()


  def test_get_message_meta_returns_headers_and_metadata_params():
      http = FakeGmailHTTP(messages={"m1": {
          "id": "m1",
          "payload": {"headers": [
              {"name": "Message-ID", "value": "<abc123@mail.gmail.com>"},
              {"name": "References", "value": "<xyz@mail.gmail.com>"},
              {"name": "Subject", "value": "Original subject"},
              {"name": "From", "value": "Priya Rao <priya@lighthouse.io>"},
          ]},
      }})
      meta = _provider(http).get_message_meta("m1")
      assert meta == {
          "message_id": "<abc123@mail.gmail.com>",
          "references": "<xyz@mail.gmail.com>",
          "subject": "Original subject",
          "from_email": "priya@lighthouse.io",
      }
      url, params = http.gets[0]
      assert url.endswith("/messages/m1")
      assert params["format"] == "metadata"
      assert params["metadataHeaders"] == ["Message-ID", "References", "Subject", "From"]


  def test_get_message_meta_missing_headers_are_empty_strings():
      http = FakeGmailHTTP(messages={"m1": {"id": "m1", "payload": {"headers": []}}})
      meta = _provider(http).get_message_meta("m1")
      assert meta == {"message_id": "", "references": "", "subject": "", "from_email": ""}


  def test_get_message_meta_auth_failure_raises():
      http = FakeGmailHTTP(messages={"m1": {}}, status={"/messages/m1": 500})
      with pytest.raises(GoogleAuthError):
          _provider(http).get_message_meta("m1")
  ```

- [ ] **Step 3: Run it and confirm the expected failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_google_gmail.py -q
  ```
  Expected failure: `AttributeError: 'GoogleProvider' object has no attribute 'trash_message'` (and the sibling methods) — none exist yet.

- [ ] **Step 4: Implement the four methods.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, add after `send_message` (added in Task 3, now the last method in the class):
  ```python
      def trash_message(self, source_id: str) -> None:
          """Move a message to Gmail Trash (users.messages.trash) — never a
          permanent delete (the full-access mail.google.com scope is not
          requested). Google auto-purges Trash after ~30 days."""
          self._post(f"{GMAIL_API_BASE}/messages/{source_id}/trash", json={})

      def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None:
          """Add/remove Gmail label ids on one message. Read/unread state and
          star are both modeled as labels: unread = presence of 'UNREAD',
          starred = presence of 'STARRED' — the router computes add/remove
          from the desired flag state before calling this."""
          self._post(
              f"{GMAIL_API_BASE}/messages/{source_id}/modify",
              json={"addLabelIds": list(add), "removeLabelIds": list(remove)},
          )

      def list_labels(self) -> list[dict]:
          """All Gmail labels (system + user) for the label-picker menu."""
          result = self._get(f"{GMAIL_API_BASE}/labels")
          return list(result.get("labels") or [])

      def get_message_meta(self, source_id: str) -> dict:
          """Bounded metadata-only fetch (format=metadata, four headers) used
          to build reply/forward threading headers without pulling the full
          body. Missing headers come back as '' rather than raising, so a
          message with an unusual header set still produces a usable (if
          empty) threading context."""
          msg = self._get(
              f"{GMAIL_API_BASE}/messages/{source_id}",
              params={
                  "format": "metadata",
                  "metadataHeaders": ["Message-ID", "References", "Subject", "From"],
              },
          )
          headers = (msg.get("payload") or {}).get("headers") or []
          _, from_email = _parse_from(_header(headers, "From"))
          return {
              "message_id": _header(headers, "Message-ID"),
              "references": _header(headers, "References"),
              "subject": _header(headers, "Subject"),
              "from_email": from_email,
          }
  ```

- [ ] **Step 5: Add the four methods to the `EmailProvider` protocol.** In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`, replace the `EmailProvider` protocol (as left by Task 3):
  ```python
  @runtime_checkable
  class EmailProvider(OAuthProvider, Protocol):
      def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
      def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
      def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
  ```
  with:
  ```python
  @runtime_checkable
  class EmailProvider(OAuthProvider, Protocol):
      def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
      def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
      def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
      def trash_message(self, source_id: str) -> None: ...
      def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None: ...
      def list_labels(self) -> list[dict]: ...
      def get_message_meta(self, source_id: str) -> dict: ...
  ```

- [ ] **Step 6: Run + confirm green.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_google_gmail.py -q
  ```
  Expected: all tests in the file pass (23 tests: 13 from Task 3 + 10 new).

- [ ] **Step 7: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: prior count + 10, `0 failed`. Report "X tests passing".

- [ ] **Step 8: Commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git add app/providers/google.py app/providers/base.py tests/fakes.py tests/test_google_gmail.py
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): add trash_message, modify_labels, list_labels, get_message_meta

  Completes the P1 Gmail write surface (contract §C): trash-only deletion
  (users.messages.trash, never permanent delete), label add/remove (backs
  read/unread + star), the label-menu listing, and a bounded metadata fetch
  that supplies reply/forward threading headers (Message-ID/References)
  without pulling a full message body.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```


### Task 5: Migration 0006 + Email model columns (starred + label_ids)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/alembic/versions/0006_email_actions.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py`

**Interfaces:**
- Consumes: the `Email(Base)` model at `backend/app/models.py` (current tail of the file, reproduced below) and the 0005 migration chain (`revision = "0005"`, confirmed in `backend/alembic/versions/0005_email.py`) as `down_revision`.
- Produces: `Email.starred: Mapped[bool]` and `Email.label_ids: Mapped[list]` columns (Task 6's `_EMAIL_FIELDS`/`_email_dict` and Task 7's store methods read/write these); migration `0006` (`revision = "0006"`, `down_revision = "0005"`) that builds the same two columns via `add_column`, keeping `compare_metadata` clean on Postgres.

- [ ] **Step 1: Write the failing tests**

The current tail of `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py` (the `Email` class) is:

```python
class Email(Base):
    """A synced email (M5). Keyed (owner, source, source_id) = ('google', gmail id)
    so re-sync upserts idempotently. Triage output (category + summary_json) is
    written on sync; NO body column — bodies are privacy-sensitive and fetched
    on demand via EmailProvider.get_message, never stored."""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_emails_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'google'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # gmail message id
    thread_id: Mapped[str] = mapped_column(String(128), default="")
    from_name: Mapped[str] = mapped_column(Text, default="")
    from_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    unread: Mapped[bool] = mapped_column(default=False)
    category: Mapped[str | None] = mapped_column(String(16))            # 'needs_reply' | 'fyi' | None
    summary_json: Mapped[list | None] = mapped_column(JSONField)        # list[str] bullets, or None
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
```

First, extend `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`. The current `test_upgrade_head_builds_full_schema` ends with:

```python
    email_cols = {c["name"] for c in inspect(engine).get_columns("emails")}
    assert {"owner", "source", "source_id", "thread_id", "from_name",
            "from_email", "subject", "snippet", "received_at", "unread",
            "category", "summary_json", "triaged_at"} <= email_cols
    assert "body" not in email_cols  # privacy: bodies never persisted
    engine.dispose()
```

Replace it with (adds `starred`/`label_ids` to the asserted column set):

```python
    email_cols = {c["name"] for c in inspect(engine).get_columns("emails")}
    assert {"owner", "source", "source_id", "thread_id", "from_name",
            "from_email", "subject", "snippet", "received_at", "unread",
            "category", "summary_json", "triaged_at", "starred", "label_ids"} <= email_cols
    assert "body" not in email_cols  # privacy: bodies never persisted
    engine.dispose()
```

Second, append a new test to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py` (after `test_email_column_defaults`, same file, same `store`/`Email`/`datetime`/`UTC` imports already present):

```python
def test_email_starred_and_label_ids_columns_default():
    with store._session() as s:
        insp = inspect(s.get_bind())
        cols = {c["name"] for c in insp.get_columns("emails")}
        assert {"starred", "label_ids"} <= cols
    with store._session() as s, s.begin():
        row = Email(owner="me", source="google", source_id="g-4",
                    subject="Slice2 defaults",
                    received_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC))
        s.add(row)
        s.flush()
        assert row.starred is False
        assert row.label_ids == []
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_migrations.py tests/test_email_models.py -q`

Expected: `test_upgrade_head_builds_full_schema` fails (`starred`/`label_ids` missing from `email_cols`) and `test_email_starred_and_label_ids_columns_default` fails with `AttributeError: 'Email' object has no attribute 'starred'`.

- [ ] **Step 3: Add the two columns to the Email model**

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py`, in the `Email` class, insert two new columns immediately after `unread: Mapped[bool] = mapped_column(default=False)` and before `category: Mapped[str | None] = mapped_column(String(16))`:

```python
    unread: Mapped[bool] = mapped_column(default=False)
    starred: Mapped[bool] = mapped_column(default=False)
    label_ids: Mapped[list] = mapped_column(JSONField, default=list)     # Gmail label ids, sync-authoritative
    category: Mapped[str | None] = mapped_column(String(16))            # 'needs_reply' | 'fyi' | None
```

- [ ] **Step 4: Create the 0006_email_actions migration**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/alembic/versions/0006_email_actions.py`, mirroring `0005_email.py`'s style (JSONField variant, explicit `server_default` so the `add_column` on an existing populated table doesn't fail on NOT NULL, downgrade drops both columns):

```python
"""Email actions (M5 slice-2): starred + label_ids on the emails table.

- emails.starred: bool, from Gmail's STARRED label — surfaced in the reading
  pane and list star indicator.
- emails.label_ids: JSON list of Gmail label ids — the label menu source of
  truth; sync + the label-write endpoints keep Gmail authoritative.
  NO body column — still never persisted (unchanged from 0005).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "emails",
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "emails",
        sa.Column("label_ids", JSONField, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("emails", "label_ids")
    op.drop_column("emails", "starred")
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_migrations.py tests/test_email_models.py -q`

Expected: all pass (the Postgres-only `test_migrations_build_models_schema_on_postgres` stays skipped — the pre-existing 1 skip).

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q`

Expected: `369 passed, 1 skipped` (368 carried forward from Tasks 1-4 [349 after Task 1 + 6 from Task 2 + 3 from Task 3 + 10 from Task 4] + 1 new test function in this task — `test_migrations.py` only gains extended assertions inside an existing test, no new function; no test elsewhere references the old `test_normalized_email_fields_and_defaults` field-count yet — Task 6 updates that one). This is a relative estimate — report the exact printed count as the actual gate.

- [ ] **Step 7: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/models.py backend/alembic/versions/0006_email_actions.py backend/tests/test_migrations.py backend/tests/test_email_models.py && git commit -m "M5 slice-2 data: 0006 migration + Email.starred/label_ids columns

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-slice2`.


### Task 6: NormalizedEmail + Gmail mapping + store fields + EmailOut additions (starred, label_ids)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_protocols.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_schemas.py`

**Interfaces:**
- Consumes: `Email.starred`/`Email.label_ids` columns (Task 5); `NormalizedEmail` dataclass and `GoogleProvider._to_email` at `backend/app/providers/base.py` / `backend/app/providers/google.py`; `store._EMAIL_FIELDS` / `_email_dict` at `backend/app/store.py`; `EmailOut` at `backend/app/schemas.py`.
- Produces: `NormalizedEmail.starred: bool = False`, `NormalizedEmail.label_ids: list = field(default_factory=list)` (Task 7's store methods and the sync write-through consume these); `GoogleProvider._to_email` populates both from Gmail's `labelIds`; `store._email_dict` gains `"starred"` and `"label_ids"` keys (Task 7's `set_email_flags`/`set_email_labels` return these via `_email_dict`); `EmailOut.starred: bool = False` and `EmailOut.label_ids: List[str] = []` (Task 8's `FlagsPatch`/`LabelsPatch` endpoints return `EmailOut` carrying these).

**IMPORTANT — two frozen-field tests exist for `NormalizedEmail`, not one:** `backend/tests/test_email_models.py::test_normalized_email_fields_and_defaults` AND `backend/tests/test_provider_protocols.py::test_normalized_email_fields_and_defaults` (same name, different file — the latter was added by slice-1's Task 1 provider-protocol split and was NOT mentioned in the slice-2 contract's task map, but it asserts the identical 10-name frozen set against `base.NormalizedEmail` and WILL fail the moment `starred`/`label_ids` are added unless updated in lockstep). Both must be updated in this task or the full-suite gate fails.

- [ ] **Step 1: Write the failing tests**

First, update `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py`'s `test_normalized_email_fields_and_defaults`. The current test is:

```python
def test_normalized_email_fields_and_defaults():
    field_names = {f.name for f in fields(NormalizedEmail)}
    assert field_names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
    }
    # unread / body_excerpt are the only optional fields.
    e = NormalizedEmail(
        source="google", source_id="g-1", thread_id="t-1",
        from_name="Priya", from_email="priya@example.com",
        subject="Lighthouse", snippet="About the deadline",
        received_at=datetime(2026, 6, 30, 15, 24, tzinfo=UTC),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
    # Provided values round-trip.
    e2 = NormalizedEmail(
        source="google", source_id="g-2", thread_id="t-2",
        from_name="Sam", from_email="sam@example.com",
        subject="Lunch", snippet="Thursday?",
        received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        unread=True, body_excerpt="Hey, are you free Thursday for lunch?",
    )
    assert e2.unread is True
    assert e2.body_excerpt.startswith("Hey")
```

Replace it with (exact 12-name field set + starred/label_ids default assertions):

```python
def test_normalized_email_fields_and_defaults():
    field_names = {f.name for f in fields(NormalizedEmail)}
    assert field_names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
        "starred", "label_ids",
    }
    # unread / body_excerpt / starred / label_ids are the only optional fields.
    e = NormalizedEmail(
        source="google", source_id="g-1", thread_id="t-1",
        from_name="Priya", from_email="priya@example.com",
        subject="Lighthouse", snippet="About the deadline",
        received_at=datetime(2026, 6, 30, 15, 24, tzinfo=UTC),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
    assert e.starred is False
    assert e.label_ids == []
    # Provided values round-trip.
    e2 = NormalizedEmail(
        source="google", source_id="g-2", thread_id="t-2",
        from_name="Sam", from_email="sam@example.com",
        subject="Lunch", snippet="Thursday?",
        received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        unread=True, body_excerpt="Hey, are you free Thursday for lunch?",
        starred=True, label_ids=["INBOX", "STARRED"],
    )
    assert e2.unread is True
    assert e2.body_excerpt.startswith("Hey")
    assert e2.starred is True
    assert e2.label_ids == ["INBOX", "STARRED"]
```

Second, the SAME frozen-set assertion is duplicated in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_protocols.py` (added by slice-1's provider-protocol-split task; it imports `NormalizedEmail` via `from app.providers import base` and calls it `base.NormalizedEmail`). The current test is:

```python
def test_normalized_email_fields_and_defaults():
    names = {f.name for f in fields(base.NormalizedEmail)}
    assert names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
    }
    e = base.NormalizedEmail(
        source="google", source_id="m1", thread_id="t1",
        from_name="Ada", from_email="ada@example.com", subject="Hi",
        snippet="preview", received_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
```

Replace it with:

```python
def test_normalized_email_fields_and_defaults():
    names = {f.name for f in fields(base.NormalizedEmail)}
    assert names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
        "starred", "label_ids",
    }
    e = base.NormalizedEmail(
        source="google", source_id="m1", thread_id="t1",
        from_name="Ada", from_email="ada@example.com", subject="Hi",
        snippet="preview", received_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
    assert e.starred is False
    assert e.label_ids == []
```

Fourth, append a store-level test to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py` (after `test_upsert_email_creates_row_with_triage`, using the file's existing `_email()` helper and `store`/`UTC` imports):

```python
def test_upsert_email_writes_through_starred_and_label_ids():
    out = store.upsert_email(
        _email(starred=True, label_ids=["INBOX", "STARRED"]),
        category="fyi", summary=["x"],
    )
    assert out["starred"] is True
    assert out["label_ids"] == ["INBOX", "STARRED"]
    # A later sync pass re-derives from Gmail's authoritative label list.
    again = store.upsert_email(
        _email(starred=False, label_ids=["INBOX"]),
        category="fyi", summary=["x"],
    )
    assert again["starred"] is False
    assert again["label_ids"] == ["INBOX"]
```

Fifth, add a mapping assertion to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py`'s `test_fetch_messages_lists_inbox_then_maps_each_message`. The current test body (inside the function, after `emails = _provider(http).fetch_messages(since=None)`) ends with:

```python
    assert e.unread is True
    # Date header -> aware UTC (08:24 -0700 == 15:24 UTC).
    assert e.received_at == datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)
    assert "design review" in e.body_excerpt
```

Replace it with:

```python
    assert e.unread is True
    # Date header -> aware UTC (08:24 -0700 == 15:24 UTC).
    assert e.received_at == datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)
    assert "design review" in e.body_excerpt
    assert e.starred is False
    assert e.label_ids == ["INBOX", "UNREAD"]
```

Then append a new focused test to the same file (after `test_bare_email_from_header_has_empty_from_name`):

```python
def test_fetch_messages_maps_starred_label():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000",
        label_ids=["INBOX", "STARRED"])})
    e = _provider(http).fetch_messages(since=None)[0]
    assert e.starred is True
    assert e.label_ids == ["INBOX", "STARRED"]
```

Sixth, and finally, append two schema tests to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_schemas.py` (after `test_email_out_rejects_out_of_vocab_category`, using the file's existing `_row()` helper):

```python
def test_email_out_defaults_starred_false_and_label_ids_empty():
    out = EmailOut.model_validate(_row())
    assert out.starred is False
    assert out.label_ids == []


def test_email_out_accepts_starred_and_label_ids():
    out = EmailOut.model_validate(_row(starred=True, label_ids=["INBOX", "STARRED"]))
    assert out.starred is True
    assert out.label_ids == ["INBOX", "STARRED"]
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_models.py tests/test_provider_protocols.py tests/test_email_store.py tests/test_google_gmail.py tests/test_email_schemas.py -q`

Expected: both `test_normalized_email_fields_and_defaults` functions (in `test_email_models.py` and in `test_provider_protocols.py`) fail with a set-mismatch `AssertionError`, and the round-trip assertions in each fail with `TypeError: NormalizedEmail.__init__() got an unexpected keyword argument 'starred'`; `test_upsert_email_writes_through_starred_and_label_ids` fails with the same `TypeError` from `_email(starred=...)`; `test_fetch_messages_maps_starred_label` and the extended mapping assertion fail with `AttributeError: 'NormalizedEmail' object has no attribute 'starred'`; the two new `EmailOut` tests fail with `AttributeError: 'EmailOut' object has no attribute 'starred'` (pydantic's `__getattr__` on an undeclared field).

- [ ] **Step 3: Add starred/label_ids to NormalizedEmail**

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`, the current `NormalizedEmail` dataclass is:

```python
@dataclass
class NormalizedEmail:
    source: str                          # 'google'
    source_id: str                       # gmail message id
    thread_id: str
    from_name: str
    from_email: str
    subject: str
    snippet: str                         # gmail preview
    received_at: datetime                # aware UTC, sort key
    unread: bool = False
    body_excerpt: str = ""               # bounded ~2 KB plain-text, triage-only, NOT persisted
```

Add two fields after `body_excerpt`:

```python
@dataclass
class NormalizedEmail:
    source: str                          # 'google'
    source_id: str                       # gmail message id
    thread_id: str
    from_name: str
    from_email: str
    subject: str
    snippet: str                         # gmail preview
    received_at: datetime                # aware UTC, sort key
    unread: bool = False
    body_excerpt: str = ""               # bounded ~2 KB plain-text, triage-only, NOT persisted
    starred: bool = False                # 'STARRED' in Gmail labelIds
    label_ids: list = field(default_factory=list)   # Gmail labelIds, sync-authoritative
```

- [ ] **Step 4: Map starred/label_ids in GoogleProvider._to_email**

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, the current `_to_email` staticmethod is:

```python
    @staticmethod
    def _to_email(msg: dict) -> NormalizedEmail:
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        from_name, from_email = _parse_from(_header(headers, "From"))
        label_ids = msg.get("labelIds") or []
        return NormalizedEmail(
            source="google",
            source_id=str(msg.get("id") or ""),
            thread_id=str(msg.get("threadId") or ""),
            from_name=from_name,
            from_email=from_email,
            subject=_header(headers, "Subject"),
            snippet=msg.get("snippet") or "",
            received_at=_parse_date(_header(headers, "Date")),
            unread="UNREAD" in label_ids,
            body_excerpt=_excerpt(_walk_plaintext(payload)),
        )
```

Replace the `return NormalizedEmail(...)` block to add `starred` and `label_ids` (the local `label_ids` variable is already computed):

```python
    @staticmethod
    def _to_email(msg: dict) -> NormalizedEmail:
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        from_name, from_email = _parse_from(_header(headers, "From"))
        label_ids = msg.get("labelIds") or []
        return NormalizedEmail(
            source="google",
            source_id=str(msg.get("id") or ""),
            thread_id=str(msg.get("threadId") or ""),
            from_name=from_name,
            from_email=from_email,
            subject=_header(headers, "Subject"),
            snippet=msg.get("snippet") or "",
            received_at=_parse_date(_header(headers, "Date")),
            unread="UNREAD" in label_ids,
            body_excerpt=_excerpt(_walk_plaintext(payload)),
            starred="STARRED" in label_ids,
            label_ids=label_ids,
        )
```

- [ ] **Step 5: Add starred/label_ids to the store's _EMAIL_FIELDS and _email_dict**

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, the current `_EMAIL_FIELDS` tuple is:

```python
_EMAIL_FIELDS = (
    "thread_id", "from_name", "from_email", "subject", "snippet",
    "received_at", "unread",
)
```

Replace with:

```python
_EMAIL_FIELDS = (
    "thread_id", "from_name", "from_email", "subject", "snippet",
    "received_at", "unread", "starred", "label_ids",
)
```

Then, the current `_email_dict` function is:

```python
def _email_dict(e: Email) -> dict:
    received = aware_utc(e.received_at)
    return {
        "id": e.id,
        "source": e.source,
        "source_id": e.source_id,
        "thread_id": e.thread_id,
        "from_name": e.from_name,
        "from_email": e.from_email,
        "subject": e.subject,
        "snippet": e.snippet,
        "received_at": received,
        "unread": e.unread,
        "category": e.category,
        "summary": e.summary_json or [],
        "triaged_at": aware_utc(e.triaged_at),
        "when": email_when_display(received),
        "created_at": aware_utc(e.created_at),
        "updated_at": aware_utc(e.updated_at),
    }
```

Add `"starred"` and `"label_ids"` keys right after `"unread": e.unread,`:

```python
def _email_dict(e: Email) -> dict:
    received = aware_utc(e.received_at)
    return {
        "id": e.id,
        "source": e.source,
        "source_id": e.source_id,
        "thread_id": e.thread_id,
        "from_name": e.from_name,
        "from_email": e.from_email,
        "subject": e.subject,
        "snippet": e.snippet,
        "received_at": received,
        "unread": e.unread,
        "starred": e.starred,
        "label_ids": e.label_ids or [],
        "category": e.category,
        "summary": e.summary_json or [],
        "triaged_at": aware_utc(e.triaged_at),
        "when": email_when_display(received),
        "created_at": aware_utc(e.created_at),
        "updated_at": aware_utc(e.updated_at),
    }
```

`upsert_email`'s `for field in _EMAIL_FIELDS: setattr(row, field, getattr(email, field))` loop (unchanged) now write-throughs `starred`/`label_ids` on every sync pass automatically since both names were added to `_EMAIL_FIELDS`.

- [ ] **Step 6: Add starred/label_ids to EmailOut**

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, the current `EmailOut` is:

```python
class EmailOut(BaseModel):
    id: int
    source: str
    from_name: str
    from_email: str
    subject: str
    snippet: str
    received_at: datetime
    unread: bool
    category: EmailCategory | None  # None = untriaged (retry next sync)
    summary: List[str]              # [] when untriaged
    when: str                       # derived display, e.g. "8:24am" / "Yesterday"
```

Add the two additive fields (defaults keep M4/slice-1 call sites and tests passing unchanged) right after `unread: bool`:

```python
class EmailOut(BaseModel):
    id: int
    source: str
    from_name: str
    from_email: str
    subject: str
    snippet: str
    received_at: datetime
    unread: bool
    starred: bool = False
    label_ids: List[str] = []
    category: EmailCategory | None  # None = untriaged (retry next sync)
    summary: List[str]              # [] when untriaged
    when: str                       # derived display, e.g. "8:24am" / "Yesterday"
```

- [ ] **Step 7: Run the tests and see them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_models.py tests/test_provider_protocols.py tests/test_email_store.py tests/test_google_gmail.py tests/test_email_schemas.py -q`

Expected: all pass.

- [ ] **Step 8: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q`

Expected: `373 passed, 1 skipped` (369 from Task 5 + 4 new test functions in this task: 1 store test + 1 gmail mapping test + 2 schema tests; the two `test_normalized_email_fields_and_defaults` functions and the gmail inbox-mapping test are extended in place, not added, so they don't change the function count). This is a relative estimate — report the exact printed count as the actual gate.

- [ ] **Step 9: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/providers/base.py backend/app/providers/google.py backend/app/store.py backend/app/schemas.py backend/tests/test_email_models.py backend/tests/test_provider_protocols.py backend/tests/test_email_store.py backend/tests/test_google_gmail.py backend/tests/test_email_schemas.py && git commit -m "M5 slice-2 data: NormalizedEmail/mapping/store/EmailOut gain starred + label_ids

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-slice2`.


### Task 7: store.set_email_flags / set_email_labels / delete_email

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`

**Interfaces:**
- Consumes: `Email.starred`/`Email.label_ids` columns (Task 5); `_email_dict` (Task 6, now emitting `starred`/`label_ids`); the existing owner-scoped `_email_row(s, source, source_id)` helper and the owner-scoped `get_email` pattern already in `store.py` (`.where(Email.id == email_id).where(Email.owner == settings.owner)` — the merged `m5-email-get-email-owner-scope` fix).
- Produces: `store.set_email_flags(email_id, unread=None, starred=None) -> dict | None`, `store.set_email_labels(email_id, label_ids: list[str]) -> dict | None`, `store.delete_email(email_id) -> bool` — all owner-scoped, all consumed by Task 9/10/11's write endpoints (`routers/email.py`'s `/trash`, `/flags`, `/labels`) AFTER the corresponding Gmail provider call already succeeded (confirm-first; these methods themselves do no Gmail I/O).

- [ ] **Step 1: Write the failing tests**

The current owner-scoped read pattern in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`'s `get_email` (to mirror for scoping):

```python
    def get_email(self, email_id: int) -> dict | None:
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Email)
                .where(Email.id == email_id)
                .where(Email.owner == settings.owner)
            ).first()
            return _email_dict(row) if row is not None else None
```

Append these tests to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`, after the existing `test_delete_email_data_is_source_scoped` function (Task 6 will have already appended one more test — `test_upsert_email_writes_through_starred_and_label_ids` — after it by this point, so that will be the true last function in the file; uses the file's existing `_email()` helper, `store`, `UTC`, `datetime` imports):

```python
def test_set_email_flags_updates_only_given_fields():
    created = store.upsert_email(_email(source_id="fl-1", unread=True), category="fyi", summary=["x"])
    out = store.set_email_flags(created["id"], starred=True)
    assert out["starred"] is True
    assert out["unread"] is True   # unread untouched (None = unchanged)
    out2 = store.set_email_flags(created["id"], unread=False)
    assert out2["unread"] is False
    assert out2["starred"] is True   # starred untouched by the second call
    out3 = store.set_email_flags(created["id"], unread=True, starred=False)
    assert out3["unread"] is True
    assert out3["starred"] is False


def test_set_email_flags_returns_none_for_absent_id():
    assert store.set_email_flags(999999, starred=True) is None


def test_set_email_flags_is_owner_scoped():
    from app.models import Email

    mine = store.upsert_email(_email(source_id="fl-mine"), category="fyi", summary=["x"])
    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="fl-theirs",
            subject="Theirs", received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.set_email_flags(foreign_id, starred=True) is None
    with store._session() as s:
        untouched = s.get(Email, foreign_id)
        assert untouched.starred is False


def test_set_email_labels_replaces_list_and_rederives_unread_starred():
    created = store.upsert_email(
        _email(source_id="lb-1", unread=True, starred=False, label_ids=["INBOX", "UNREAD"]),
        category="fyi", summary=["x"],
    )
    out = store.set_email_labels(created["id"], ["INBOX", "STARRED"])
    assert out["label_ids"] == ["INBOX", "STARRED"]
    assert out["starred"] is True     # re-derived from STARRED membership
    assert out["unread"] is False     # re-derived: UNREAD no longer present

    out2 = store.set_email_labels(created["id"], ["INBOX", "UNREAD", "STARRED"])
    assert out2["label_ids"] == ["INBOX", "UNREAD", "STARRED"]
    assert out2["unread"] is True
    assert out2["starred"] is True


def test_set_email_labels_returns_none_for_absent_id():
    assert store.set_email_labels(999999, ["INBOX"]) is None


def test_set_email_labels_is_owner_scoped():
    from app.models import Email

    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="lb-theirs",
            subject="Theirs", received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            label_ids=["INBOX"],
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.set_email_labels(foreign_id, ["INBOX", "STARRED"]) is None
    with store._session() as s:
        untouched = s.get(Email, foreign_id)
        assert untouched.label_ids == ["INBOX"]


def test_delete_email_removes_single_row():
    created = store.upsert_email(_email(source_id="del-1"), category="fyi", summary=["x"])
    other = store.upsert_email(_email(source_id="del-2"), category="fyi", summary=["y"])
    assert store.delete_email(created["id"]) is True
    assert store.get_email(created["id"]) is None
    assert store.get_email(other["id"]) is not None   # sibling row untouched


def test_delete_email_returns_false_for_absent_id():
    assert store.delete_email(999999) is False


def test_delete_email_is_owner_scoped():
    from app.models import Email

    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="del-theirs",
            subject="Theirs", received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.delete_email(foreign_id) is False
    with store._session() as s:
        assert s.get(Email, foreign_id) is not None   # a cross-owner delete must not succeed
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_store.py -q`

Expected: `AttributeError: 'Store' object has no attribute 'set_email_flags'` (and, once that's stubbed away as you iterate locally, equivalent failures for `set_email_labels` and `delete_email`) — all nine new tests fail; the pre-existing email-store tests still pass.

- [ ] **Step 3: Add set_email_flags / set_email_labels / delete_email to store.py**

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`, append these three methods to the `# ---- emails (M5) ----` section, right after `get_email` and before `delete_email_data` (so all four owner-scoped single-row accessors sit together):

```python
    def get_email(self, email_id: int) -> dict | None:
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Email)
                .where(Email.id == email_id)
                .where(Email.owner == settings.owner)
            ).first()
            return _email_dict(row) if row is not None else None

    def _owned_email_row(self, s: Session, email_id: int) -> Email | None:
        from .config import settings

        return s.scalars(
            select(Email)
            .where(Email.id == email_id)
            .where(Email.owner == settings.owner)
        ).first()

    def set_email_flags(
        self, email_id: int, unread: bool | None = None, starred: bool | None = None
    ) -> dict | None:
        """Owner-scoped read-state/star patch. A None field is left unchanged;
        called by the router AFTER GoogleProvider.modify_labels has already
        succeeded (confirm-first — this method does no Gmail I/O itself)."""
        with self._session() as s, s.begin():
            row = self._owned_email_row(s, email_id)
            if row is None:
                return None
            if unread is not None:
                row.unread = unread
            if starred is not None:
                row.starred = starred
            s.flush()
            return _email_dict(row)

    def set_email_labels(self, email_id: int, label_ids: list[str]) -> dict | None:
        """Owner-scoped label replace. The router computes the full post-add/
        remove list from Gmail's response; unread/starred are re-derived here
        from UNREAD/STARRED membership in the new list so the two stay
        consistent with whatever labels now apply."""
        with self._session() as s, s.begin():
            row = self._owned_email_row(s, email_id)
            if row is None:
                return None
            row.label_ids = list(label_ids)
            row.unread = "UNREAD" in label_ids
            row.starred = "STARRED" in label_ids
            s.flush()
            return _email_dict(row)

    def delete_email(self, email_id: int) -> bool:
        """Owner-scoped single-row delete, called by the router AFTER
        GoogleProvider.trash_message has already succeeded (confirm-first)."""
        with self._session() as s, s.begin():
            row = self._owned_email_row(s, email_id)
            if row is None:
                return False
            s.delete(row)
            return True
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_store.py -q`

Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q`

Expected: `382 passed, 1 skipped` (373 from Task 6 + 9 new test functions in this task). This is a relative estimate — report the exact printed count as the actual gate.

- [ ] **Step 6: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/store.py backend/tests/test_email_store.py && git commit -m "M5 slice-2 data: store.set_email_flags/set_email_labels/delete_email (owner-scoped)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-slice2`.


### Task 8: `POST /api/email/{id}/trash` — Gmail trash, confirm-first, local row removed

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`

**Interfaces:**
- Consumes: `providers.get(name) -> OAuthProvider | None` (existing, `app/providers/__init__.py`); `store.get_email(email_id) -> dict | None` (existing); `store.delete_email(email_id) -> bool` (Task 7, contract §E); `GoogleProvider.trash_message(source_id: str) -> None` raising `GoogleAuthError` on failure (Task 3, contract §C); `FakeEmailProvider` from `tests/test_email_api.py` (existing, gains `trash_message` this task).
- Produces: route `POST /api/email/{email_id}/trash -> 204` wired ahead of any future dynamic-route conflicts; the extended `FakeEmailProvider` (`.trash_message`, and stub attrs for T9-T11's methods added incrementally) that T9/T10/T11's tests build on.

- [ ] **Step 1: Write the failing tests for trash — extend `FakeEmailProvider` in `test_email_api.py` first.**
  Read the current `FakeEmailProvider` at the top of `test_email_api.py` (lines 25-42) — it only has `name`, `fetch_messages`, `get_message`. Replace that class with one that also records write calls:
  ```python
  class FakeEmailProvider:
      """Only the surface the email router calls: name, fetch_messages (marker),
      get_message, plus the M5 slice-2 write methods (trash/modify/labels/send/meta)."""

      name = "google"

      def __init__(self, *, body: str = "Full body text.", raise_on_get: bool = False,
                   raise_on_write: bool = False, labels: list[dict] | None = None,
                   meta: dict | None = None, send_result: dict | None = None):
          self._body = body
          self._raise = raise_on_get
          self._raise_write = raise_on_write
          self._labels = labels if labels is not None else []
          self._meta = meta or {"message_id": "", "references": "", "subject": "", "from_email": ""}
          self._send_result = send_result or {"id": "sent-1"}
          self.got: list[str] = []
          self.trashed: list[str] = []
          self.modified: list[tuple[str, list[str], list[str]]] = []
          self.sent: list[tuple[bytes, str | None]] = []
          self.meta_fetched: list[str] = []

      def fetch_messages(self, since):  # marks this as an EmailProvider for the sync
          return []

      def get_message(self, source_id: str) -> str:
          self.got.append(source_id)
          if self._raise:
              raise RuntimeError("gmail down")
          return self._body

      def _maybe_raise(self):
          if self._raise_write:
              from app.providers.google import GoogleAuthError
              raise GoogleAuthError("gmail rejected the action")

      def trash_message(self, source_id: str) -> None:
          self._maybe_raise()
          self.trashed.append(source_id)

      def modify_labels(self, source_id: str, add=(), remove=()) -> None:
          self._maybe_raise()
          self.modified.append((source_id, list(add), list(remove)))

      def list_labels(self) -> list[dict]:
          self._maybe_raise()
          return list(self._labels)

      def get_message_meta(self, source_id: str) -> dict:
          self._maybe_raise()
          self.meta_fetched.append(source_id)
          return dict(self._meta)

      def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str:
          self._maybe_raise()
          self.sent.append((raw_rfc822, thread_id))
          return self._send_result["id"]
  ```
  This is a pure rename/superset of the existing class — every existing test in the file (`fetch_messages`, `get_message`, `got`) keeps working unchanged. Now append the trash tests at the end of `test_email_api.py`:
  ```python
  def test_trash_email_calls_gmail_then_deletes_local_row(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m20", "Junk"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/trash")

      assert res.status_code == 204
      assert fake.trashed == ["m20"]
      assert store.get_email(row["id"]) is None


  def test_trash_email_404_before_any_provider_call(client):
      fake = FakeEmailProvider()
      providers.configure([fake])

      res = client.post("/api/email/999999/trash")

      assert res.status_code == 404
      assert fake.trashed == []


  def test_trash_email_502_on_gmail_failure_leaves_row_untouched(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])
      row = store.upsert_email(_email("m21", "Keep me"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/trash")

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"
      assert store.get_email(row["id"]) is not None
  ```
  Add the `providers` import if not already present at the top of the file (it already is: `from app import email_sync, providers`).

- [ ] **Step 2: Run the tests — expect failure (no `/trash` route yet).**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: `404 Not Found` for the trash tests (FastAPI's default for an undeclared route), i.e. `test_trash_email_calls_gmail_then_deletes_local_row` fails asserting `res.status_code == 204` (got 404) and `fake.trashed == ["m20"]` (got `[]`). `test_trash_email_404_before_any_provider_call` and the "before any provider call" assertion may spuriously pass since the route doesn't exist at all — that's expected and gets superseded once the real route lands in Step 3.

- [ ] **Step 3: Implement `POST /api/email/{email_id}/trash` in `routers/email.py`.**
  Read the current file first — it ends at line 66 with `sync_now`. The dynamic `GET /{email_id}` is declared at line 35, and there are no other dynamic-suffix routes yet, so `/trash` (a suffix on the dynamic segment, not a literal top-level route) can be added after `sync_now` without a route-order hazard — FastAPI matches `/{email_id}/trash` distinctly from `/{email_id}` because of the extra path segment. Add:
  ```python
  @router.post("/{email_id}/trash", status_code=204)
  def trash_email(email_id: int) -> Response:
      """Trash in Gmail first; the local row is removed ONLY on success
      (confirm-first — a Gmail failure leaves the row untouched)."""
      row = store.get_email(email_id)
      if row is None:
          raise HTTPException(status_code=404, detail="Email not found")
      impl = providers.get(row["source"])
      trash_message = getattr(impl, "trash_message", None)
      if trash_message is None:
          raise HTTPException(status_code=502, detail="Gmail rejected the action")
      try:
          trash_message(row["source_id"])
      except Exception as exc:  # noqa: BLE001 — any provider failure is a 502, never a local change
          logger.warning("trash failed for email %s: %s", email_id, exc)
          raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
      store.delete_email(email_id)
      return Response(status_code=204)
  ```
  Add `Response` to the fastapi import line (`from fastapi import APIRouter, HTTPException, Response`) — matches the `Response` usage pattern in `routers/fitness.py`'s `delete_workout`.

- [ ] **Step 4: Run the tests — expect pass.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: all tests in the file pass, including the three new trash tests.

- [ ] **Step 5: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: all prior-baseline tests plus the new ones pass, `0 failed`. Report the exact "X passed, Y skipped" count.

- [ ] **Step 6: Commit.**
  ```
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py
  git commit -m "$(cat <<'EOF'
  feat(email): POST /api/email/{id}/trash — confirm-first Gmail trash

  404 before any provider call; Gmail trash_message must succeed before the
  local row is deleted; any provider failure returns 502 with no local change.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 9: `POST /api/email/{id}/flags` — read/unread + star, confirm-first

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`

**Interfaces:**
- Consumes: `FlagsPatch` (this task, contract §F — first task that needs it, per the assignment split); `store.set_email_flags(email_id, unread=None, starred=None) -> dict | None` (Task 7, contract §E); `GoogleProvider.modify_labels(source_id, add=(), remove=()) -> None` (Task 3, contract §C); `providers.get`; `store.get_email`; the extended `FakeEmailProvider.modify_labels` from Task 8.
- Produces: `FlagsPatch` schema (`schemas.py`) that Task 10/11 do NOT redefine; route `POST /api/email/{email_id}/flags -> EmailOut`.

- [ ] **Step 1: Write the failing tests in `test_email_api.py`.**
  Append (the file already imports `store`, `providers`, `_email`, `FakeEmailProvider` from Task 8):
  ```python
  def test_flags_mark_read_removes_unread_label_and_updates_row(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m30", "Ping", unread=True), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/flags", json={"unread": False})

      assert res.status_code == 200
      body = res.json()
      assert body["unread"] is False
      assert fake.modified == [("m30", [], ["UNREAD"])]


  def test_flags_mark_unread_adds_unread_label(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m31", "Ping", unread=False), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/flags", json={"unread": True})

      assert res.status_code == 200
      assert res.json()["unread"] is True
      assert fake.modified == [("m31", ["UNREAD"], [])]


  def test_flags_star_adds_starred_label(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m32", "Ping"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/flags", json={"starred": True})

      assert res.status_code == 200
      assert res.json()["starred"] is True
      assert fake.modified == [("m32", ["STARRED"], [])]


  def test_flags_unstar_removes_starred_label(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m33", "Ping"), category="fyi", summary=[])
      store.set_email_flags(row["id"], starred=True)

      res = client.post(f"/api/email/{row['id']}/flags", json={"starred": False})

      assert res.status_code == 200
      assert res.json()["starred"] is False
      assert fake.modified == [("m33", [], ["STARRED"])]


  def test_flags_both_fields_combine_add_and_remove(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m34", "Ping", unread=True), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/flags",
                        json={"unread": False, "starred": True})

      assert res.status_code == 200
      assert fake.modified == [("m34", ["STARRED"], ["UNREAD"])]


  def test_flags_empty_patch_is_a_no_op_and_skips_the_provider_call(client):
      # PINNED behavior: {} (both fields None/untouched) returns the current
      # row unchanged and never calls modify_labels — there is nothing to
      # confirm with Gmail, so no network round-trip is made.
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m35", "Ping", unread=True), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/flags", json={})

      assert res.status_code == 200
      assert res.json()["unread"] is True
      assert fake.modified == []


  def test_flags_404_before_any_provider_call(client):
      fake = FakeEmailProvider()
      providers.configure([fake])

      res = client.post("/api/email/999999/flags", json={"unread": True})

      assert res.status_code == 404
      assert fake.modified == []


  def test_flags_502_on_gmail_failure_leaves_row_unchanged(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])
      row = store.upsert_email(_email("m36", "Ping", unread=True), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/flags", json={"unread": False})

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"
      assert store.get_email(row["id"])["unread"] is True
  ```

- [ ] **Step 2: Run the tests — expect failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: the new `test_flags_*` tests fail with 404 (route not declared) or `KeyError`/`AssertionError` on `body["starred"]` (EmailOut does not carry `starred` until Task 6's schema change lands, and `set_email_flags` does not exist until Task 7 — both are prerequisite tasks already merged onto this branch per the phase map; if run before those land, this step's failure is a collection/attribute error instead, which is still the expected "red" state for TDD purposes here).

- [ ] **Step 3: Add `FlagsPatch` to `schemas.py`.**
  Read the current `# ---- Email schemas (M5) ----` block (lines 471-505) — `EmailOut` at line 480 and `Inbox` at line 499 are the last two classes in the file. Insert `FlagsPatch` directly above `Inbox` (after `EmailDetail`):
  ```python
  class FlagsPatch(BaseModel):
      """None field = unchanged. unread=True adds Gmail's UNREAD label (marks
      unread); unread=False removes it (marks read). starred=True adds
      STARRED; starred=False removes it. See routers/email.py's add/remove
      computation."""

      unread: bool | None = None
      starred: bool | None = None
  ```

- [ ] **Step 4: Implement `POST /{email_id}/flags` in `routers/email.py`.**
  Add the import `FlagsPatch` to the existing `from ..schemas import EmailDetail, Inbox` line, making it `from ..schemas import EmailDetail, EmailOut, FlagsPatch, Inbox` (EmailOut is needed as the response_model). Append below Task 8's `trash_email`:
  ```python
  @router.post("/{email_id}/flags", response_model=EmailOut)
  def set_email_flags(email_id: int, patch: FlagsPatch) -> dict:
      """Read/unread + star. Gmail's UNREAD label is the inverse of our
      `unread` field's truthiness the other direction: unread=True -> add
      UNREAD; unread=False -> remove UNREAD. starred=True -> add STARRED;
      starred=False -> remove STARRED. Both None (an empty patch) is a no-op
      that skips the Gmail call entirely and returns the row unchanged."""
      row = store.get_email(email_id)
      if row is None:
          raise HTTPException(status_code=404, detail="Email not found")
      add: list[str] = []
      remove: list[str] = []
      if patch.unread is True:
          add.append("UNREAD")
      elif patch.unread is False:
          remove.append("UNREAD")
      if patch.starred is True:
          add.append("STARRED")
      elif patch.starred is False:
          remove.append("STARRED")
      if add or remove:
          impl = providers.get(row["source"])
          modify_labels = getattr(impl, "modify_labels", None)
          if modify_labels is None:
              raise HTTPException(status_code=502, detail="Gmail rejected the action")
          try:
              modify_labels(row["source_id"], add=add, remove=remove)
          except Exception as exc:  # noqa: BLE001 — any provider failure is a 502, never a local change
              logger.warning("flags update failed for email %s: %s", email_id, exc)
              raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
      updated = store.set_email_flags(email_id, unread=patch.unread, starred=patch.starred)
      return updated
  ```

- [ ] **Step 5: Run the tests — expect pass.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: all tests pass, including the 8 new flag tests.

- [ ] **Step 6: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: 0 failed. Report the exact "X passed, Y skipped" count.

- [ ] **Step 7: Commit.**
  ```
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py
  git commit -m "$(cat <<'EOF'
  feat(email): POST /api/email/{id}/flags — read/unread + star, confirm-first

  Empty patch (both fields None) is pinned as a no-op that skips the Gmail
  call; any real change confirms against Gmail's modify_labels before the
  local row updates. A provider failure returns 502 with the row unchanged.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 10: `POST /api/email/{id}/labels` + `GET /api/email/labels`

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`

**Interfaces:**
- Consumes: `LabelsPatch`, `LabelOut` (this task, contract §F — first task that needs them); `store.set_email_labels(email_id, label_ids: list[str]) -> dict | None` (Task 7, contract §E); `GoogleProvider.modify_labels` (Task 3); `GoogleProvider.list_labels() -> list[dict]` (Task 3, contract §C); `store.get_email`; the extended `FakeEmailProvider.list_labels`/`.modify_labels` from Task 8.
- Produces: `LabelsPatch`/`LabelOut` schemas; routes `POST /api/email/{email_id}/labels -> EmailOut` and `GET /api/email/labels -> list[LabelOut]` (the literal `/labels` route MUST be declared before the dynamic `/{email_id}` GET route per the contract's route-order hazard note — see Step 4).

- [ ] **Step 1: Write the failing tests in `test_email_api.py`.**
  Append:
  ```python
  def test_labels_add_and_remove_computes_union_minus_removed(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m40", "Ping"), category="fyi", summary=[])
      store.set_email_labels(row["id"], ["INBOX", "IMPORTANT"])

      res = client.post(f"/api/email/{row['id']}/labels",
                        json={"add": ["STARRED"], "remove": ["IMPORTANT"]})

      assert res.status_code == 200
      body = res.json()
      assert sorted(body["label_ids"]) == sorted(["INBOX", "STARRED"])
      assert fake.modified == [("m40", ["STARRED"], ["IMPORTANT"])]


  def test_labels_add_only(client):
      fake = FakeEmailProvider()
      providers.configure([fake])
      row = store.upsert_email(_email("m41", "Ping"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/labels", json={"add": ["Label_1"]})

      assert res.status_code == 200
      assert res.json()["label_ids"] == ["Label_1"]
      assert fake.modified == [("m41", ["Label_1"], [])]


  def test_labels_404_before_any_provider_call(client):
      fake = FakeEmailProvider()
      providers.configure([fake])

      res = client.post("/api/email/999999/labels", json={"add": ["Label_1"]})

      assert res.status_code == 404
      assert fake.modified == []


  def test_labels_502_on_gmail_failure_leaves_row_unchanged(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])
      row = store.upsert_email(_email("m42", "Ping"), category="fyi", summary=[])
      store.set_email_labels(row["id"], ["INBOX"])

      res = client.post(f"/api/email/{row['id']}/labels", json={"add": ["Label_2"]})

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"
      assert store.get_email(row["id"])["label_ids"] == ["INBOX"]


  def test_labels_unknown_provider_returns_502(client):
      # No providers configured at all -> providers.get('google') is None.
      providers.configure([])
      row = store.upsert_email(_email("m43", "Ping"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/labels", json={"add": ["Label_1"]})

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"


  def test_get_labels_lists_from_provider(client):
      fake = FakeEmailProvider(labels=[
          {"id": "INBOX", "name": "INBOX", "type": "system"},
          {"id": "Label_1", "name": "Work", "type": "user"},
      ])
      providers.configure([fake])

      res = client.get("/api/email/labels")

      assert res.status_code == 200
      body = res.json()
      assert body == [
          {"id": "INBOX", "name": "INBOX", "type": "system"},
          {"id": "Label_1", "name": "Work", "type": "user"},
      ]


  def test_get_labels_502_on_gmail_failure(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])

      res = client.get("/api/email/labels")

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"
  ```

- [ ] **Step 2: Run the tests — expect failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: all new `test_labels_*`/`test_get_labels_*` tests fail — `/labels` (both the `GET` list route and the `POST .../labels` suffix) is undeclared, so FastAPI returns 404 for routes it doesn't recognize (or, for `GET /api/email/labels` specifically, it would incorrectly match nothing since `/{email_id}` requires an int path param and `labels` isn't one — 422 or 404 depending on FastAPI's path-conversion failure — either way, not the expected 200).

- [ ] **Step 3: Add `LabelsPatch` and `LabelOut` to `schemas.py`.**
  Insert directly below Task 9's `FlagsPatch` (still above `Inbox`):
  ```python
  class LabelsPatch(BaseModel):
      add: List[str] = []
      remove: List[str] = []


  class LabelOut(BaseModel):
      id: str
      name: str
      type: str
  ```

- [ ] **Step 4: Implement the routes in `routers/email.py` — literal `/labels` BEFORE the dynamic `/{email_id}`.**
  Update the schemas import to `from ..schemas import EmailDetail, EmailOut, FlagsPatch, Inbox, LabelOut, LabelsPatch`. Read the current file structure: `GET /inbox` (literal, line 28) is declared before `GET /{email_id}` (dynamic, line 35) — the established pattern. `GET /api/email/labels` is ALSO a literal top-level route competing with the dynamic `GET /{email_id}`, so it MUST be declared before `email_detail`. Insert it immediately after the `inbox()` function and before `email_detail`:
  ```python
  @router.get("/labels", response_model=list[LabelOut])
  def list_labels() -> list[dict]:
      """The label menu's options, straight from Gmail (no local labels table)."""
      impl = providers.get("google")
      list_labels_fn = getattr(impl, "list_labels", None)
      if list_labels_fn is None:
          raise HTTPException(status_code=502, detail="Gmail rejected the action")
      try:
          return list_labels_fn()
      except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
          logger.warning("list_labels failed: %s", exc)
          raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
  ```
  The `POST /{email_id}/labels` route is a suffix on the dynamic segment (like `/trash` and `/flags`), so it has no ordering conflict with `GET /{email_id}` — append it after Task 9's `set_email_flags`:
  ```python
  @router.post("/{email_id}/labels", response_model=EmailOut)
  def set_email_labels(email_id: int, patch: LabelsPatch) -> dict:
      """New label list = (stored ∪ add) − remove, confirmed against Gmail
      first via modify_labels, then written locally via store.set_email_labels
      (which also re-derives unread/starred from the new list)."""
      row = store.get_email(email_id)
      if row is None:
          raise HTTPException(status_code=404, detail="Email not found")
      impl = providers.get(row["source"])
      modify_labels = getattr(impl, "modify_labels", None)
      if modify_labels is None:
          raise HTTPException(status_code=502, detail="Gmail rejected the action")
      try:
          modify_labels(row["source_id"], add=patch.add, remove=patch.remove)
      except Exception as exc:  # noqa: BLE001 — any provider failure is a 502, never a local change
          logger.warning("labels update failed for email %s: %s", email_id, exc)
          raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
      current = set(row.get("label_ids") or [])
      new_labels = list((current | set(patch.add)) - set(patch.remove))
      updated = store.set_email_labels(email_id, new_labels)
      return updated
  ```

- [ ] **Step 5: Run the tests — expect pass.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: all tests pass, including the 7 new label tests.

- [ ] **Step 6: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: 0 failed. Report the exact "X passed, Y skipped" count.

- [ ] **Step 7: Commit.**
  ```
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py
  git commit -m "$(cat <<'EOF'
  feat(email): POST /api/email/{id}/labels + GET /api/email/labels

  New label set = (stored ∪ add) − remove, confirmed against Gmail's
  modify_labels before the local row updates. GET /labels lists the Gmail
  label menu directly (no local labels table). Literal /labels is declared
  before the dynamic /{email_id} route to avoid the FastAPI route-order hazard.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 11: `POST /api/email/send` + `POST /{id}/reply` + `POST /{id}/forward`

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`

**Interfaces:**
- Consumes: `SendEmail`, `ReplyEmail`, `ForwardEmail` (this task, contract §F — first task that needs them); `_build_rfc822(*, to, subject, body, cc=None, in_reply_to=None, references=None) -> bytes` (Task 2, contract §B, imported from `app.providers.google`); `GoogleProvider.send_message(raw_rfc822: bytes, thread_id: str | None = None) -> str` (Task 3, contract §C); `GoogleProvider.get_message_meta(source_id: str) -> dict` returning `{"message_id", "references", "subject", "from_email"}` (Task 3, contract §C); `store.get_email`; the extended `FakeEmailProvider.send_message`/`.get_message_meta` from Task 8.
- Produces: `SendEmail`/`ReplyEmail`/`ForwardEmail` schemas; routes `POST /api/email/send -> {"id": str}`, `POST /api/email/{id}/reply -> {"id": str}`, `POST /api/email/{id}/forward -> {"id": str}`. `/send` is a literal route declared before the dynamic `/{email_id}` GET (route-order hazard); `/reply`/`/forward` are dynamic-segment suffixes like `/trash`/`/flags`/`/labels`, no ordering conflict.

- [ ] **Step 1: Write the failing tests in `test_email_api.py`.**
  Append (uses stdlib `email.message_from_bytes` to decode the fake's recorded raw RFC-822 for header assertions):
  ```python
  from email import message_from_bytes


  def test_send_builds_rfc822_and_posts_via_provider(client):
      fake = FakeEmailProvider(send_result={"id": "sent-42"})
      providers.configure([fake])

      res = client.post("/api/email/send", json={
          "to": "priya@lighthouse.io", "cc": "team@lighthouse.io",
          "subject": "Kickoff", "body": "See you Monday.",
      })

      assert res.status_code == 200
      assert res.json() == {"id": "sent-42"}
      assert len(fake.sent) == 1
      raw, thread_id = fake.sent[0]
      assert thread_id is None
      msg = message_from_bytes(raw)
      assert msg["To"] == "priya@lighthouse.io"
      assert msg["Cc"] == "team@lighthouse.io"
      assert msg["Subject"] == "Kickoff"
      assert msg.get_content().strip() == "See you Monday."


  def test_send_502_on_gmail_failure(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])

      res = client.post("/api/email/send", json={
          "to": "a@x.com", "subject": "S", "body": "B",
      })

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"


  def test_reply_threads_and_prefixes_subject_with_re(client):
      fake = FakeEmailProvider(
          send_result={"id": "reply-1"},
          meta={"message_id": "<orig@gmail.com>", "references": "<older@gmail.com>",
                "subject": "Kickoff", "from_email": "priya@lighthouse.io"},
      )
      providers.configure([fake])
      row = store.upsert_email(_email("m50", "Kickoff"), category="needs_reply", summary=[])

      res = client.post(f"/api/email/{row['id']}/reply", json={"body": "Sounds good."})

      assert res.status_code == 200
      assert res.json() == {"id": "reply-1"}
      assert fake.meta_fetched == ["m50"]
      raw, thread_id = fake.sent[0]
      assert thread_id == "t-m50"  # original row's thread_id, per _email() helper
      msg = message_from_bytes(raw)
      assert msg["To"] == "priya@lighthouse.io"
      assert msg["Subject"] == "Re: Kickoff"
      assert msg["In-Reply-To"] == "<orig@gmail.com>"
      assert msg["References"] == "<older@gmail.com> <orig@gmail.com>"
      assert msg.get_content().strip() == "Sounds good."


  def test_reply_does_not_double_prefix_an_existing_re_subject(client):
      fake = FakeEmailProvider(
          meta={"message_id": "<orig@gmail.com>", "references": "",
                "subject": "Re: Kickoff", "from_email": "priya@lighthouse.io"},
      )
      providers.configure([fake])
      row = store.upsert_email(_email("m51", "Re: Kickoff"), category="needs_reply", summary=[])

      client.post(f"/api/email/{row['id']}/reply", json={"body": "Ack."})

      raw, _ = fake.sent[0]
      msg = message_from_bytes(raw)
      assert msg["Subject"] == "Re: Kickoff"


  def test_reply_case_insensitive_re_prefix_check(client):
      fake = FakeEmailProvider(
          meta={"message_id": "<orig@gmail.com>", "references": "",
                "subject": "RE: kickoff", "from_email": "priya@lighthouse.io"},
      )
      providers.configure([fake])
      row = store.upsert_email(_email("m52", "RE: kickoff"), category="needs_reply", summary=[])

      client.post(f"/api/email/{row['id']}/reply", json={"body": "Ack."})

      raw, _ = fake.sent[0]
      msg = message_from_bytes(raw)
      assert msg["Subject"] == "RE: kickoff"


  def test_reply_404_before_any_provider_call(client):
      fake = FakeEmailProvider()
      providers.configure([fake])

      res = client.post("/api/email/999999/reply", json={"body": "Ack."})

      assert res.status_code == 404
      assert fake.sent == []
      assert fake.meta_fetched == []


  def test_reply_502_on_gmail_failure(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])
      row = store.upsert_email(_email("m53", "Kickoff"), category="needs_reply", summary=[])

      res = client.post(f"/api/email/{row['id']}/reply", json={"body": "Ack."})

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"


  def test_forward_prefixes_subject_with_fwd_and_carries_no_threading_headers(client):
      fake = FakeEmailProvider(
          send_result={"id": "fwd-1"},
          meta={"message_id": "<orig@gmail.com>", "references": "<older@gmail.com>",
                "subject": "Kickoff", "from_email": "priya@lighthouse.io"},
      )
      providers.configure([fake])
      row = store.upsert_email(_email("m54", "Kickoff"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/forward",
                        json={"to": "other@x.com", "body": "FYI, see below."})

      assert res.status_code == 200
      assert res.json() == {"id": "fwd-1"}
      raw, thread_id = fake.sent[0]
      assert thread_id is None  # forward does not thread
      msg = message_from_bytes(raw)
      assert msg["To"] == "other@x.com"
      assert msg["Subject"] == "Fwd: Kickoff"
      assert msg["In-Reply-To"] is None
      assert msg["References"] is None
      assert msg.get_content().strip() == "FYI, see below."


  def test_forward_does_not_double_prefix_an_existing_fwd_subject(client):
      fake = FakeEmailProvider(
          meta={"message_id": "<orig@gmail.com>", "references": "",
                "subject": "Fwd: Kickoff", "from_email": "priya@lighthouse.io"},
      )
      providers.configure([fake])
      row = store.upsert_email(_email("m55", "Fwd: Kickoff"), category="fyi", summary=[])

      client.post(f"/api/email/{row['id']}/forward", json={"to": "other@x.com", "body": "FYI."})

      raw, _ = fake.sent[0]
      msg = message_from_bytes(raw)
      assert msg["Subject"] == "Fwd: Kickoff"


  def test_forward_404_before_any_provider_call(client):
      fake = FakeEmailProvider()
      providers.configure([fake])

      res = client.post("/api/email/999999/forward", json={"to": "a@x.com", "body": "FYI."})

      assert res.status_code == 404
      assert fake.sent == []


  def test_forward_502_on_gmail_failure(client):
      fake = FakeEmailProvider(raise_on_write=True)
      providers.configure([fake])
      row = store.upsert_email(_email("m56", "Kickoff"), category="fyi", summary=[])

      res = client.post(f"/api/email/{row['id']}/forward",
                        json={"to": "other@x.com", "body": "FYI."})

      assert res.status_code == 502
      assert res.json()["detail"] == "Gmail rejected the action"
  ```

- [ ] **Step 2: Run the tests — expect failure.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: all new `test_send_*`/`test_reply_*`/`test_forward_*` tests fail — none of `/send`, `/{id}/reply`, `/{id}/forward` are declared yet (404s), and `SendEmail`/`ReplyEmail`/`ForwardEmail` don't exist in `schemas.py` yet (would be an `ImportError`/`AttributeError` once referenced, but at this step the router doesn't reference them either, so the failure mode is purely the missing routes).

- [ ] **Step 3: Add `SendEmail`, `ReplyEmail`, `ForwardEmail` to `schemas.py`.**
  Insert directly below Task 10's `LabelOut` (still above `Inbox`):
  ```python
  class SendEmail(BaseModel):
      to: str
      cc: str | None = None
      subject: str
      body: str


  class ReplyEmail(BaseModel):
      body: str


  class ForwardEmail(BaseModel):
      to: str
      body: str
  ```

- [ ] **Step 4: Implement the routes in `routers/email.py`.**
  Update the schemas import to `from ..schemas import (EmailDetail, EmailOut, FlagsPatch, ForwardEmail, Inbox, LabelOut, LabelsPatch, ReplyEmail, SendEmail)` and add `from ..providers.google import _build_rfc822` to the imports (a new import line, since `providers/google.py` is the module `_build_rfc822` lives in per contract §B). `POST /send` is a literal route — declare it directly after the `GET /labels` route from Task 10 (both literal routes now sit before the dynamic `GET /{email_id}`):
  ```python
  @router.post("/send")
  def send_email(payload: SendEmail) -> dict:
      """Compose-new send. No local row is touched — sends are confirmed
      straight through to Gmail; the Sent-folder truth lives in Gmail itself."""
      impl = providers.get("google")
      send_message = getattr(impl, "send_message", None)
      if send_message is None:
          raise HTTPException(status_code=502, detail="Gmail rejected the action")
      raw = _build_rfc822(
          to=payload.to, cc=payload.cc, subject=payload.subject, body=payload.body,
      )
      try:
          new_id = send_message(raw)
      except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
          logger.warning("send failed: %s", exc)
          raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
      return {"id": new_id}
  ```
  `POST /{email_id}/reply` and `POST /{email_id}/forward` are dynamic-segment suffixes (no ordering conflict) — append them after Task 10's `set_email_labels`:
  ```python
  def _prefixed(subject: str, prefix: str) -> str:
      """Add `prefix` (e.g. 'Re: ') unless subject already starts with it,
      case-insensitively (contract: no double-Re/double-Fwd)."""
      if subject.lower().startswith(prefix.lower()):
          return subject
      return f"{prefix}{subject}"


  @router.post("/{email_id}/reply")
  def reply_email(email_id: int, payload: ReplyEmail) -> dict:
      """Reply threads on the original: In-Reply-To/References from Gmail's
      live message-meta, thread_id from the stored row, subject 'Re: <orig>'
      (no double-Re), to = the original sender. No local row changes — Gmail's
      Sent folder is the source of truth for outbound mail."""
      original = store.get_email(email_id)
      if original is None:
          raise HTTPException(status_code=404, detail="Email not found")
      impl = providers.get(original["source"])
      send_message = getattr(impl, "send_message", None)
      get_message_meta = getattr(impl, "get_message_meta", None)
      if send_message is None or get_message_meta is None:
          raise HTTPException(status_code=502, detail="Gmail rejected the action")
      try:
          meta = get_message_meta(original["source_id"])
          subject = _prefixed(meta["subject"] or original["subject"], "Re: ")
          references = f"{meta['references']} {meta['message_id']}".strip()
          raw = _build_rfc822(
              to=meta["from_email"], subject=subject, body=payload.body,
              in_reply_to=meta["message_id"], references=references,
          )
          new_id = send_message(raw, thread_id=original["thread_id"])
      except HTTPException:
          raise
      except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
          logger.warning("reply failed for email %s: %s", email_id, exc)
          raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
      return {"id": new_id}


  @router.post("/{email_id}/forward")
  def forward_email(email_id: int, payload: ForwardEmail) -> dict:
      """Forward carries no threading headers (a fresh conversation for the new
      recipient) and always prefixes 'Fwd: ' (no double-Fwd). To comes from the
      payload, not the original sender."""
      original = store.get_email(email_id)
      if original is None:
          raise HTTPException(status_code=404, detail="Email not found")
      impl = providers.get(original["source"])
      send_message = getattr(impl, "send_message", None)
      get_message_meta = getattr(impl, "get_message_meta", None)
      if send_message is None or get_message_meta is None:
          raise HTTPException(status_code=502, detail="Gmail rejected the action")
      try:
          meta = get_message_meta(original["source_id"])
          subject = _prefixed(meta["subject"] or original["subject"], "Fwd: ")
          raw = _build_rfc822(to=payload.to, subject=subject, body=payload.body)
          new_id = send_message(raw)
      except HTTPException:
          raise
      except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
          logger.warning("forward failed for email %s: %s", email_id, exc)
          raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
      return {"id": new_id}
  ```
  Note: `get_message_meta` is called inside the same `try` so a meta-fetch failure also maps to 502 (it's a provider call too); `HTTPException` is re-raised bare so the 404-before-provider-call path (already outside this `try`) is unaffected.

- [ ] **Step 5: Run the tests — expect pass.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q
  ```
  Expected: all tests pass, including the 12 new send/reply/forward tests.

- [ ] **Step 6: Run the full suite before committing.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: 0 failed. Report the exact "X passed, Y skipped" count — this closes out Phase P3 (Tasks 8-11), so confirm the full suite (M4 fitness + all M5 email tests) is green before Phase P4 begins.

- [ ] **Step 7: Commit.**
  ```
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py
  git commit -m "$(cat <<'EOF'
  feat(email): POST /send + /{id}/reply + /{id}/forward with RFC-822 threading

  Reply carries In-Reply-To/References from Gmail's live message-meta plus the
  stored thread_id; forward starts a fresh thread. Both prefix Re:/Fwd: without
  double-prefixing an already-prefixed subject. No local row changes on send —
  Gmail's Sent folder is the source of truth for outbound mail. A provider
  failure returns 502 and never touches local state.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```


### Task 12: `email_draft.py` module + conftest seam

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_draft.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_draft.py`

**Interfaces:**
- Consumes: `app.llm.stream(*, model, system, messages, tools)` / `app.llm.available()` (`/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/llm.py`); `settings.assistant_model` (`/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py:40`); mirrors the seam shape of `app/email_triage.py` (`_override`, `configure`, never-raises contract).
- Produces: `email_draft.configure(override: object | None | str = "unset") -> None` and `email_draft.draft(instructions: str, notes: str, mode: str, original: dict | None) -> str | None` — consumed by Task 13 (`routers/email.py` `POST /api/email/draft`) and Task 14 (`tools.py` `_draft_email`).

This task's conftest edit and the new module MUST land in the SAME commit — per the slice-1 conftest hazard note (`no_external_services` in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py` configures every module's fake-seam atomically; a module added without its conftest line lets that module's tests silently hit the real network/API in the full suite run, because the autouse fixture doesn't know about it yet).

- [ ] **Step 1: Write the failing seam test for `configure(None)`**

  Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_draft.py`:

  ```python
  """email_draft (M5 slice-2): AI-drafted email body via the shared llm seam;
  user-initiated only; never raises."""
  from app import email_draft, llm

  from .fakes import FakeLLM, text_turn


  class _FakeDraft:
      def __init__(self, result):
          self.result = result
          self.calls = []

      def draft(self, instructions, notes, mode, original):
          self.calls.append((instructions, notes, mode, original))
          return self.result


  def test_configure_none_returns_none():
      email_draft.configure(None)
      assert email_draft.draft("write it", "", "new", None) is None


  def test_fake_object_seam_is_delegated_to():
      fake = _FakeDraft("Hi Priya, confirming the 30th works for me.")
      email_draft.configure(fake)
      text = email_draft.draft("confirm the date", "typed notes", "reply",
                               {"from_name": "Priya", "from_email": "priya@x.io",
                                "subject": "Re: date", "body_excerpt": "Does the 30th work?"})
      assert text == "Hi Priya, confirming the 30th works for me."
      assert fake.calls == [("confirm the date", "typed notes", "reply",
                             {"from_name": "Priya", "from_email": "priya@x.io",
                              "subject": "Re: date", "body_excerpt": "Does the 30th work?"})]


  def test_real_path_returns_stripped_llm_text():
      llm.configure(FakeLLM(text_turn("  Hi Priya,\n\nConfirming the 30th works.\n  ")))
      email_draft.configure("unset")
      text = email_draft.draft("confirm the date", "", "reply",
                               {"from_name": "Priya", "from_email": "priya@x.io",
                                "subject": "Re: date", "body_excerpt": "Does the 30th work?"})
      assert text == "Hi Priya,\n\nConfirming the 30th works."


  def test_real_path_new_mode_with_no_original():
      llm.configure(FakeLLM(text_turn("Hey team, quick update on the launch.")))
      email_draft.configure("unset")
      text = email_draft.draft("write an update to the team", "launch is on track", "new", None)
      assert text == "Hey team, quick update on the launch."


  def test_offline_llm_returns_none_without_raising():
      llm.configure(None)
      email_draft.configure("unset")
      assert email_draft.draft("write it", "", "new", None) is None


  def test_fake_raising_returns_none_without_raising():
      class _Raises:
          def draft(self, *a, **k):
              raise RuntimeError("boom")

      email_draft.configure(_Raises())
      assert email_draft.draft("write it", "", "new", None) is None
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_draft.py -q`
  Expected: `ModuleNotFoundError: No module named 'app.email_draft'` (collection error — the module doesn't exist yet).

- [ ] **Step 2: Implement `app/email_draft.py`**

  Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_draft.py`:

  ```python
  """AI email drafting (M5 slice-2) — one Claude call per user-initiated draft
  request. NEVER runs automatically: only `POST /api/email/draft` (the compose
  editor's AI-draft button) and the assistant's `draft_email` tool call this.

  Input: user instructions + whatever the user has already typed (notes) +, for
  reply/forward, the original message's sender/subject/a bounded ~2KB
  body_excerpt (fetched live by the router — transits, never persisted, same
  posture as email_triage). Output: a plain-text email body (no subject line,
  no signature placeholders) or None on any failure/offline. Drafts are never
  persisted server-side.

  Seam mirrors email_triage.py: configure(fake) installs an object exposing
  .draft(...); configure(None) disables drafting (always returns None);
  configure("unset") uses the real Claude client via app/llm.py. This function
  never raises.
  """
  from __future__ import annotations

  import logging

  from . import llm
  from .config import settings

  log = logging.getLogger("scuffed_os.email_draft")

  _override: object | None | str = "unset"

  _SYSTEM = (
      "You draft a single email body for a busy person, at their request. "
      "Write ONLY the plain-text body of the email — no subject line, no "
      "greeting-less filler, no signature placeholder (e.g. no '[Your Name]'). "
      "Follow the user's instructions exactly. If the user has already typed "
      "notes, treat them as raw material to turn into a proper email, not as "
      "a suggestion to ignore. If this is a reply or forward, use the original "
      "message's sender, subject, and body excerpt as context so the draft "
      "makes sense in that thread. Respond with ONLY the email body text — no "
      "prose about what you did, no markdown fences, no quotation marks around it."
  )


  def configure(override: object | None | str = "unset") -> None:
      """Tests install a fake with .draft(...); None disables; 'unset' uses real."""
      global _override
      _override = override


  def _build_prompt(instructions: str, notes: str, mode: str, original: dict | None) -> str:
      lines = [f"Mode: {mode}", f"Instructions: {instructions}"]
      if notes:
          lines.append(f"Notes already typed (raw material, not a final draft):\n{notes}")
      if original is not None:
          sender = f"{original.get('from_name', '')} <{original.get('from_email', '')}>".strip()
          lines.append(
              f"Original message being {('replied to' if mode == 'reply' else 'forwarded')}:\n"
              f"From: {sender}\n"
              f"Subject: {original.get('subject', '')}\n"
              f"Body:\n{original.get('body_excerpt', '')}"
          )
      return "\n\n".join(lines)


  def _final_text(prompt: str) -> str:
      """One Claude call via the shared llm seam; return the assistant's text.
      Reads the streaming context the same way email_triage._final_text does."""
      with llm.stream(
          model=settings.assistant_model,
          system=_SYSTEM,
          messages=[{"role": "user", "content": prompt}],
          tools=[],
      ) as stream:
          for _ in stream.text_stream:
              pass
          message = stream.get_final_message()
      parts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
      return "".join(parts)


  def draft(instructions: str, notes: str, mode: str, original: dict | None) -> str | None:
      """Return the drafted plain-text body, or None on any failure/offline.
      Never raises. NEVER called except from the draft endpoint/tool."""
      if _override is None:
          return None
      if _override != "unset":
          try:
              return _override.draft(instructions, notes, mode, original)
          except Exception:
              log.exception("fake draft raised; returning None")
              return None
      if not llm.available():
          return None
      try:
          text = _final_text(_build_prompt(instructions, notes, mode, original))
          text = text.strip()
          return text or None
      except Exception:
          log.exception("draft call failed")
          return None
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_draft.py -q`
  Expected: 6 passed.

- [ ] **Step 3: Wire the conftest seam (same commit as the module)**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`, the current `no_external_services` fixture reads:

  ```python
  from app import email_sync, email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
  ```

  and:

  ```python
  @pytest.fixture(autouse=True)
  def no_external_services():
      """Tests never reach the Claude API, OpenAI, Mem0, USDA, osascript, or
      WHOOP — install a fake explicitly (each module's configure seam) when needed."""
      llm.configure(None)
      memory_engine.configure(None)
      food_db.configure(None)
      reminders.configure(None)
      providers.configure([])
      fitness_sync.configure(None)
      email_triage.configure(None)
      email_sync.configure(None)
      yield
      llm.configure()
      memory_engine.configure("unset")
      food_db.configure("unset")
      reminders.configure("unset")
      providers.configure("unset")
      fitness_sync.configure("unset")
      email_triage.configure("unset")
      email_sync.configure("unset")
  ```

  Edit the import line to add `email_draft`:

  ```python
  from app import email_draft, email_sync, email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
  ```

  Add `email_draft.configure(None)` immediately after the `email_sync.configure(None)` line, and `email_draft.configure("unset")` immediately after the `email_sync.configure("unset")` line:

  ```python
      llm.configure(None)
      memory_engine.configure(None)
      food_db.configure(None)
      reminders.configure(None)
      providers.configure([])
      fitness_sync.configure(None)
      email_triage.configure(None)
      email_sync.configure(None)
      email_draft.configure(None)
      yield
      llm.configure()
      memory_engine.configure("unset")
      food_db.configure("unset")
      reminders.configure("unset")
      providers.configure("unset")
      fitness_sync.configure("unset")
      email_triage.configure("unset")
      email_sync.configure("unset")
      email_draft.configure("unset")
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_draft.py -q`
  Expected: still 6 passed (the fixture's `configure(None)`/`configure("unset")` bracket each test; `test_email_draft.py`'s own explicit `email_draft.configure(...)` calls inside each test override the autouse default for that test body, matching how `test_email_triage.py` behaves against the same fixture).

- [ ] **Step 4: Run the full suite and commit**

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest`
  Expected: `418 passed, 1 skipped` (412 carried forward from Tasks 1-11 [382 after Task 7 + 3 from Task 8 + 8 from Task 9 + 7 from Task 10 + 12 from Task 11] + 6 new `test_email_draft.py` tests). This is a relative estimate — report the exact printed count as the actual gate.

  ```bash
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_draft.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_draft.py
  git commit -m "$(cat <<'EOF'
  feat(email): add email_draft module — user-initiated AI drafting seam

  Mirrors email_triage's configure()/never-raises shape; only the draft
  endpoint/tool may call draft(). conftest wires the fake seam atomically
  with the module per the slice-1 hazard note.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 13: `POST /api/email/draft` endpoint

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`

**Interfaces:**
- Consumes: `email_draft.draft(instructions, notes, mode, original) -> str | None` (Task 12); `store.get_email(email_id) -> dict | None` (`/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py:1318`, keys include `from_name`, `from_email`, `subject`, `source`, `source_id`); `providers.get(source)` + `impl.get_message(source_id) -> str` (raises on failure) — same pattern as `email_detail` in `routers/email.py:44-50`.
- Produces: `DraftRequest` schema (contract §F) consumed by the frontend `emailDraft` helper (Task 15) and by Task 14's assistant tool via direct `email_draft.draft(...)` call (the tool does NOT go through this HTTP endpoint — it calls the module directly, matching how `_get_email` in `tools.py` calls `store`/`providers` directly rather than hitting the router).

- [ ] **Step 1: Write the failing schema + route tests**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`, the file currently ends with:

  ```python
  def test_sync_triggers_email_sync_and_lists_email_providers(client):
      fake_sync = FakeEmailSync(count=7)
      email_sync.configure(fake_sync)
      providers.configure([FakeEmailProvider()])

      body = client.post("/api/email/sync").json()
      assert body == {"synced": 7, "providers": ["google"]}
      assert fake_sync.calls == 1
  ```

  Add the import line `from app import email_draft` next to the existing `from app import email_sync, providers` import at the top of the file, then append:

  ```python
  class _FakeDraft:
      def __init__(self, text):
          self.text = text
          self.calls = []

      def draft(self, instructions, notes, mode, original):
          self.calls.append((instructions, notes, mode, original))
          return self.text


  def test_draft_new_mode_ignores_email_id(client):
      email_draft.configure(_FakeDraft("Hey team, launch update inside."))

      resp = client.post("/api/email/draft", json={
          "instructions": "write a launch update", "notes": "on track",
          "mode": "new", "email_id": 999999,
      })
      assert resp.status_code == 200
      assert resp.json() == {"draft": "Hey team, launch update inside."}


  def test_draft_reply_mode_builds_original_from_store_and_live_excerpt(client):
      fake_provider = FakeEmailProvider(body="Full original body, quite long, " * 100)
      providers.configure([fake_provider])
      row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])
      fake_draft = _FakeDraft("Sounds good, confirming.")
      email_draft.configure(fake_draft)

      resp = client.post("/api/email/draft", json={
          "instructions": "confirm it works", "mode": "reply", "email_id": row["id"],
      })
      assert resp.status_code == 200
      assert resp.json() == {"draft": "Sounds good, confirming."}
      assert len(fake_draft.calls) == 1
      _, _, mode, original = fake_draft.calls[0]
      assert mode == "reply"
      assert original["from_name"] == "Ada Lovelace"
      assert original["from_email"] == "ada@example.com"
      assert original["subject"] == "The plan"
      assert len(original["body_excerpt"]) <= 2048


  def test_draft_reply_mode_404_when_email_id_absent(client):
      email_draft.configure(_FakeDraft("text"))
      resp = client.post("/api/email/draft", json={
          "instructions": "confirm it works", "mode": "reply", "email_id": 999999,
      })
      assert resp.status_code == 404


  def test_draft_reply_mode_excerpt_falls_back_to_empty_on_fetch_failure(client):
      providers.configure([FakeEmailProvider(raise_on_get=True)])
      row = store.upsert_email(_email("m5", "Offline"), category="fyi", summary=[])
      fake_draft = _FakeDraft("Drafted anyway.")
      email_draft.configure(fake_draft)

      resp = client.post("/api/email/draft", json={
          "instructions": "reply anyway", "mode": "reply", "email_id": row["id"],
      })
      assert resp.status_code == 200
      assert resp.json() == {"draft": "Drafted anyway."}
      _, _, _, original = fake_draft.calls[0]
      assert original["body_excerpt"] == ""


  def test_draft_returns_503_when_draft_unavailable(client):
      email_draft.configure(None)
      resp = client.post("/api/email/draft", json={"instructions": "write it", "mode": "new"})
      assert resp.status_code == 503
      assert resp.json()["detail"] == "Couldn't draft — try again."


  def test_draft_never_persists_anything(client):
      email_draft.configure(_FakeDraft("Some draft text."))
      before = store.inbox()
      client.post("/api/email/draft", json={"instructions": "write it", "mode": "new"})
      after = store.inbox()
      assert before == after
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q`
  Expected: `AttributeError: module 'app.email_draft' has no attribute 'configure'` is NOT the failure (Task 12 already lands that) — instead expect `404` for `/api/email/draft` (route doesn't exist yet, FastAPI returns 404 Not Found for all six new tests since neither the schema nor the route exists).

- [ ] **Step 2: Add `DraftRequest` to `schemas.py`**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, the email schemas section currently ends with:

  ```python
  class Inbox(BaseModel):
      needs_reply: List[EmailOut]
      fyi: List[EmailOut]
      untriaged: List[EmailOut]
      needs_reply_count: int
      unread_count: int
  ```

  Append immediately after it:

  ```python


  class DraftRequest(BaseModel):
      instructions: str
      notes: str = ""
      mode: Literal["new", "reply", "forward"] = "new"
      email_id: int | None = None
  ```

  (`Literal` is already imported at the top of `schemas.py`.)

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q`
  Expected: still failing (404s) — the route isn't wired yet.

- [ ] **Step 3: Add the route to `routers/email.py`**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`, the current imports are:

  ```python
  from .. import email_sync, providers
  from ..schemas import EmailDetail, Inbox
  from ..store import store
  ```

  Change to:

  ```python
  from .. import email_draft, email_sync, providers
  from ..schemas import DraftRequest, EmailDetail, Inbox
  from ..store import store
  ```

  The router currently declares routes in this order: `GET /inbox`, `GET /{email_id}`, `POST /sync`. Per the contract's route-order hazard (literal routes MUST be declared before `/{email_id}`), insert the new `/draft` route BETWEEN `GET /inbox` and `GET /{email_id}` — i.e. replace:

  ```python
  @router.get("/inbox", response_model=Inbox)
  def inbox() -> dict:
      """The triaged inbox: needs_reply / fyi / untriaged groups + counts. Served
      from the emails table (never a live provider call)."""
      return store.inbox()


  @router.get("/{email_id}", response_model=EmailDetail)
  ```

  with:

  ```python
  @router.get("/inbox", response_model=Inbox)
  def inbox() -> dict:
      """The triaged inbox: needs_reply / fyi / untriaged groups + counts. Served
      from the emails table (never a live provider call)."""
      return store.inbox()


  # Max characters of the original message's live body handed to the drafting
  # model as context — bounded so a huge thread doesn't blow the prompt; the
  # excerpt transits Gmail -> server -> Anthropic and is never persisted.
  _DRAFT_EXCERPT_CHARS = 2048


  def _draft_original(email_id: int) -> dict:
      """Build the `original` context dict for reply/forward drafting: stored
      metadata + a best-effort live body excerpt (empty string on any fetch
      failure — drafting still proceeds with metadata only)."""
      row = store.get_email(email_id)
      if row is None:
          raise HTTPException(status_code=404, detail="Email not found")
      excerpt = ""
      impl = providers.get(row["source"])
      get_message = getattr(impl, "get_message", None)
      if get_message is not None:
          try:
              excerpt = get_message(row["source_id"])[:_DRAFT_EXCERPT_CHARS]
          except Exception as exc:  # noqa: BLE001 — excerpt fetch is best-effort
              logger.warning("draft excerpt fetch failed for email %s: %s", email_id, exc)
              excerpt = ""
      return {
          "from_name": row["from_name"],
          "from_email": row["from_email"],
          "subject": row["subject"],
          "body_excerpt": excerpt,
      }


  @router.post("/draft")
  def draft_email(payload: DraftRequest) -> dict:
      """User-initiated AI draft (the compose editor's AI-draft button, or the
      assistant's draft_email tool for the HTTP path). NEVER runs automatically."""
      original = None
      if payload.mode in ("reply", "forward"):
          if payload.email_id is None:
              raise HTTPException(status_code=404, detail="Email not found")
          original = _draft_original(payload.email_id)
      text = email_draft.draft(payload.instructions, payload.notes, payload.mode, original)
      if text is None:
          raise HTTPException(status_code=503, detail="Couldn't draft — try again.")
      return {"draft": text}


  @router.get("/{email_id}", response_model=EmailDetail)
  ```

  Note: `mode="new"` ignores `email_id` entirely per the contract (`test_draft_new_mode_ignores_email_id` passes a nonexistent `email_id=999999` and still expects 200) — the `if payload.mode in ("reply", "forward")` guard is what makes that true.

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_api.py -q`
  Expected: all tests in the file pass, including the 6 new ones.

- [ ] **Step 4: Run the full suite and commit**

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest`
  Expected: `424 passed, 1 skipped` (418 from Task 12 + 6 new `test_email_api.py` tests). This is a relative estimate — report the exact printed count as the actual gate.

  ```bash
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py
  git commit -m "$(cat <<'EOF'
  feat(email): add POST /api/email/draft endpoint

  Builds reply/forward context from the stored row + a bounded live body
  excerpt (best-effort, empty on fetch failure); draft() -> None maps to
  503. Declared before /{email_id} per the route-order hazard. Never
  persists anything.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 14: assistant `draft_email` tool

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_tools.py`

**Interfaces:**
- Consumes: `store.get_email(email_id) -> dict | None` (`/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py:1318`); `_compact_email(e: dict) -> dict` (existing helper, `tools.py:438-442`); `providers.get(name) -> OAuthProvider | None` + `impl.get_message(source_id) -> str` (existing, same best-effort live-fetch pattern as `_get_email`/Task 13's `_draft_original`, bounded per contract §G — NOT `row["snippet"]`); `email_draft.draft(instructions, notes, mode, original) -> str | None` (Task 12); `_email_action(title, meta) -> dict` (existing helper, `tools.py:95-97`).
- Produces: the `draft_email` tool entry in `TOOLS` (contract §H), executor `_draft_email(args: dict) -> tuple[dict, dict | None]` returning `({"draft": ..., "reply_to": <compact email or None>}, _email_action("Draft ready", "Open compose to review & send"))` on success or `({"error": ...}, None)` on failure — consumed by the assistant loop's tool dispatch (`tools.execute`, unchanged) and by the frontend's action-card renderer (existing `_email_action` shape, no frontend change this task).

- [ ] **Step 1: Write the failing tool tests**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_tools.py`, the file currently starts:

  ```python
  """M5 assistant email tools (read-only): get_inbox compact shape, get_email body + errors."""
  import json
  from datetime import datetime, timedelta, timezone

  from app import providers, tools
  from app.providers.base import NormalizedEmail
  from app.store import store
  ```

  and has this registration test:

  ```python
  def test_email_tools_are_registered_read_only():
      names = {t["name"] for t in tools.TOOLS}
      assert {"get_inbox", "get_email"} <= names
      # No write/send/draft/archive tools this slice.
      assert not any(n in names for n in ("send_email", "draft_email", "archive_email"))
  ```

  Update the module docstring and imports, and STRENGTHEN the registration test to assert `draft_email` IS present while `send_email`/`trash_email`/`label_email` remain absent (per the contract, slice-2 adds exactly one write-adjacent tool). Replace the docstring/import block with:

  ```python
  """M5 assistant email tools: get_inbox compact shape, get_email body + errors,
  draft_email (slice-2, the only write-adjacent tool this slice)."""
  import json
  from datetime import datetime, timedelta, timezone

  from app import email_draft, providers, tools
  from app.providers.base import NormalizedEmail
  from app.store import store
  ```

  Replace the registration test:

  ```python
  def test_email_tools_are_registered_read_only():
      names = {t["name"] for t in tools.TOOLS}
      assert {"get_inbox", "get_email"} <= names
      # No write/send/archive tools this slice.
      assert not any(n in names for n in ("send_email", "trash_email", "label_email"))
  ```

  with:

  ```python
  def test_email_tools_are_registered():
      names = {t["name"] for t in tools.TOOLS}
      assert {"get_inbox", "get_email", "draft_email"} <= names
      # draft_email is the ONLY write-adjacent email tool this slice — it never
      # sends/trashes/labels; those remain assistant-inaccessible.
      assert not any(n in names for n in ("send_email", "trash_email", "label_email"))
  ```

  Then append two new tests at the end of the file (after `test_get_email_errors_for_missing_id`):

  ```python
  class _FakeDraft:
      def __init__(self, text):
          self.text = text
          self.calls = []

      def draft(self, instructions, notes, mode, original):
          self.calls.append((instructions, notes, mode, original))
          return self.text


  def test_draft_email_happy_path_with_reply_to(client):
      fake = FakeEmailProvider(body="Full live body text, not the snippet.")
      providers.configure([fake])
      row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])
      fake_draft = _FakeDraft("Sounds good, confirming.")
      email_draft.configure(fake_draft)

      result_json, action = tools.execute(
          "draft_email", {"instructions": "confirm it works", "email_id": row["id"]}
      )
      result = json.loads(result_json)
      assert result["draft"] == "Sounds good, confirming."
      assert result["reply_to"]["id"] == row["id"]
      assert result["reply_to"]["subject"] == "The plan"
      assert "body" not in result["reply_to"]
      assert action == {"icon": "mail", "title": "Draft ready",
                        "meta": "Open compose to review & send", "cta": "Open email", "screen": "email"}
      # contract §G: body_excerpt is fetched live via provider.get_message,
      # never the DB-cached snippet (row["snippet"] == "preview" per _email()).
      assert fake.got == ["m9"]
      _, _, _, original = fake_draft.calls[0]
      assert original["body_excerpt"] == "Full live body text, not the snippet."


  def test_draft_email_without_email_id_has_no_reply_to():
      email_draft.configure(_FakeDraft("A fresh note."))

      result_json, action = tools.execute("draft_email", {"instructions": "write a note"})
      result = json.loads(result_json)
      assert result["draft"] == "A fresh note."
      assert result["reply_to"] is None
      assert action is not None


  def test_draft_email_errors_when_draft_unavailable():
      email_draft.configure(None)

      result_json, action = tools.execute("draft_email", {"instructions": "write it"})
      result = json.loads(result_json)
      assert "error" in result
      assert action is None


  def test_draft_email_errors_for_missing_email_id():
      email_draft.configure(_FakeDraft("text"))

      result_json, action = tools.execute(
          "draft_email", {"instructions": "reply", "email_id": 987654}
      )
      result = json.loads(result_json)
      assert "error" in result
      assert action is None
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_tools.py -q`
  Expected: `test_email_tools_are_registered` fails (`draft_email` not in `names`); the four new `test_draft_email_*` tests fail with `KeyError`/`AssertionError` because `tools.execute("draft_email", ...)` returns the "Unknown tool" error path (executor not registered yet).

- [ ] **Step 2: Implement the `_draft_email` executor and register the tool**

  In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`, add the `email_draft` import. Current import line:

  ```python
  from . import fitness_sync, food_db, memory_engine, providers, recurrence
  ```

  Change to:

  ```python
  from . import email_draft, fitness_sync, food_db, memory_engine, providers, recurrence
  ```

  The email section currently ends with `_get_email` (lines 452-466):

  ```python
  def _get_email(args: dict):
      row = store.get_email(args["email_id"])
      if row is None:
          return {"error": f"No email with id {args['email_id']}."}, None
      body = _EMAIL_BODY_UNAVAILABLE
      impl = providers.get(row["source"])
      get_message = getattr(impl, "get_message", None)
      if get_message is not None:
          try:
              body = get_message(row["source_id"])
          except Exception:  # noqa: BLE001 — body fetch is best-effort
              body = _EMAIL_BODY_UNAVAILABLE
      return {"id": row["id"], "from_name": row["from_name"], "from_email": row["from_email"],
              "subject": row["subject"], "category": row["category"],
              "summary": row["summary"], "when": row["when"], "body": body}, None
  ```

  Append immediately after `_get_email`, before the `# ---- task reminders (real from M3) ----` section:

  ```python


  # Max characters of the original message's live body handed to the drafting
  # model as context — same bound as routers/email.py's _draft_original
  # (contract §G: body_excerpt is fetched live via provider.get_message +
  # truncation, never the DB-cached snippet). Kept as a separate module-level
  # constant here since tools.py and routers/email.py don't share imports for
  # this value.
  _DRAFT_EXCERPT_CHARS = 2048


  def _draft_email(args: dict):
      """User-initiated AI draft (slice-2's only write-adjacent email tool).
      Never sends/trashes/labels — the result is a draft the user reviews in
      compose. email_id is optional; when given, its row becomes reply_to
      context for both the model prompt and the returned action payload."""
      reply_to = None
      original = None
      if args.get("email_id") is not None:
          row = store.get_email(args["email_id"])
          if row is None:
              return {"error": f"No email with id {args['email_id']}."}, None
          reply_to = _compact_email(row)
          excerpt = ""
          impl = providers.get(row["source"])
          get_message = getattr(impl, "get_message", None)
          if get_message is not None:
              try:
                  excerpt = get_message(row["source_id"])[:_DRAFT_EXCERPT_CHARS]
              except Exception:  # noqa: BLE001 — excerpt fetch is best-effort
                  excerpt = ""
          original = {"from_name": row["from_name"], "from_email": row["from_email"],
                      "subject": row["subject"], "body_excerpt": excerpt}
      text = email_draft.draft(args["instructions"], "", "reply" if original else "new", original)
      if text is None:
          return {"error": "Couldn't draft right now — try again."}, None
      return {"draft": text, "reply_to": reply_to}, _email_action(
          "Draft ready", "Open compose to review & send"
      )
  ```

  Register the tool in the `TOOLS` list. The list currently ends with:

  ```python
      {"name": "get_email",
       "description": "Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
       "input_schema": {"type": "object", "properties": {
           "email_id": {"type": "integer"}},
           "required": ["email_id"], "additionalProperties": False},
       "run": _get_email},
  ]
  ```

  Insert a new entry right after `get_email`, before the closing `]`:

  ```python
      {"name": "get_email",
       "description": "Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
       "input_schema": {"type": "object", "properties": {
           "email_id": {"type": "integer"}},
           "required": ["email_id"], "additionalProperties": False},
       "run": _get_email},
      {"name": "draft_email",
       "description": "Draft an email with AI from the user's instructions — optionally replying to an existing message by id (from get_inbox). Returns the draft text; the user reviews and sends it from the compose pane. Never sends.",
       "input_schema": {"type": "object", "properties": {
           "instructions": {"type": "string"},
           "email_id": {"type": "integer"}},
           "required": ["instructions"], "additionalProperties": False},
       "run": _draft_email},
  ]
  ```

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_tools.py -q`
  Expected: all tests pass, including the updated registration test and the 4 new `test_draft_email_*` tests.

- [ ] **Step 3: Run the full suite and commit**

  Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest`
  Expected: `428 passed, 1 skipped` (424 from Task 13 + 4 new `test_draft_email_*` tests; the registration test was replaced 1-for-1, not added). This is a relative estimate — report the exact printed count as the actual gate.

  ```bash
  git add /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_tools.py
  git commit -m "$(cat <<'EOF'
  feat(email): add assistant draft_email tool

  The only write-adjacent email tool this slice: prepares a draft (never
  sends/trashes/labels) and returns an action card that opens compose for
  the user's review. Registration test now asserts draft_email is present
  while send/trash/label tools remain absent.

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```


### Task 15: api.js write helpers + write-gate banner

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx`

**Interfaces:**
- Consumes: `POST /api/email/send`, `POST /api/email/{id}/reply`, `POST /api/email/{id}/forward`, `POST /api/email/{id}/trash`, `POST /api/email/{id}/flags`, `POST /api/email/{id}/labels`, `GET /api/email/labels`, `POST /api/email/draft` (contract §F, built in Tasks 8-14); `ProviderStatus.can_write_email: bool` (contract §A, Task 1); existing `request()` helper in api.js (does **not** auto-stringify — every helper below must call `JSON.stringify` explicitly, matching `logWorkout`/`createEvent`/`updateTask` etc.).
- Produces: `api.emailSend(payload)`, `api.emailReply(id, payload)`, `api.emailForward(id, payload)`, `api.emailTrash(id)`, `api.emailFlags(id, payload)`, `api.emailLabels(id, payload)`, `api.emailLabelList()`, `api.emailDraft(payload)` — all named/shaped exactly per contract §I, all returning `request()`'s promise. `EmailScreen`'s local `canWrite` boolean (derived from `google?.can_write_email`) and the "Enable email actions" banner — consumed by Tasks 16-17 to gate all write UI.

There is no test harness for `api.js` or `EmailScreen.jsx` (slice-1 shipped none — confirmed by `ls frontend/src/**/*.test.*` returning nothing). The gate for every step in this task is `npm run build` exiting 0, plus a `grep` verification that the new exports/markup exist. Full browser verification of live behavior happens in Task 20.

- [ ] **Step 1: Confirm the current `request()` body convention before adding anything.**
  Run:
  ```
  grep -n "body: JSON.stringify\|body: payload\|body: form" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js
  ```
  Expected: every POST/PATCH/PUT helper in the file passes `body: JSON.stringify(...)` — e.g. `logWorkout: (w) => request('/api/fitness/workouts', { method: 'POST', body: JSON.stringify(w) })`. None pass a raw object as `body`. This confirms the contract's `body: payload` sketch in §I is illustrative only — every new helper below must wrap its payload in `JSON.stringify`.

- [ ] **Step 2: Add the 8 email write helpers to `api.js`, matching the file's existing conventions exactly.**
  Open `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js` and locate the existing Email (M5) block:
  ```js
  // Email (M5) — the inbox/detail come straight from the emails table server-
  // side (list never triggers a live Gmail call). Only emailDetail fetches the
  // body live, with a graceful fallback string if Gmail is unreachable. Bodies
  // are never persisted. emailSync kicks a foreground sync pass.
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),
  ```
  Replace it with (appending the 8 write helpers and an updated comment; `emailInbox`/`emailDetail`/`emailSync` unchanged):
  ```js
  // Email (M5) — the inbox/detail come straight from the emails table server-
  // side (list never triggers a live Gmail call). Only emailDetail fetches the
  // body live, with a graceful fallback string if Gmail is unreachable. Bodies
  // are never persisted. emailSync kicks a foreground sync pass.
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),

  // Email writes (M5 slice-2) — confirm-first server-side (Gmail call happens
  // before any local change); gated client-side on can_write_email (see
  // EmailScreen's canWrite banner). emailDraft never persists and only runs on
  // explicit user request (the ✨ button).
  emailSend: (payload) => request('/api/email/send', { method: 'POST', body: JSON.stringify(payload) }),
  emailReply: (id, payload) => request(`/api/email/${id}/reply`, { method: 'POST', body: JSON.stringify(payload) }),
  emailForward: (id, payload) => request(`/api/email/${id}/forward`, { method: 'POST', body: JSON.stringify(payload) }),
  emailTrash: (id) => request(`/api/email/${id}/trash`, { method: 'POST' }),
  emailFlags: (id, payload) => request(`/api/email/${id}/flags`, { method: 'POST', body: JSON.stringify(payload) }),
  emailLabels: (id, payload) => request(`/api/email/${id}/labels`, { method: 'POST', body: JSON.stringify(payload) }),
  emailLabelList: () => request('/api/email/labels'),
  emailDraft: (payload) => request('/api/email/draft', { method: 'POST', body: JSON.stringify(payload) }),
  ```

- [ ] **Step 3: Verify the helpers compile and are exported.**
  Run:
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0 (no test harness exists for api.js — build is the gate). Then run:
  ```
  grep -c "emailSend:\|emailReply:\|emailForward:\|emailTrash:\|emailFlags:\|emailLabels:\|emailLabelList:\|emailDraft:" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js
  ```
  Expected: `8`.

- [ ] **Step 4: Commit the api.js helpers on their own (separable from the EmailScreen change below).**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/lib/api.js
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): add write API helpers (send/reply/forward/trash/flags/labels/draft)

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

- [ ] **Step 5: Add the `canWrite` derivation to `EmailScreen.jsx`, right after the existing `needsReauth` derivation.**
  Current code (read via `Read` tool to confirm line numbers before editing — anchor text below is exact as of slice-1):
  ```js
  const google = (status?.providers || []).find((p) => p.provider === 'google') || null
  const connected = !!google
  const needsReauth = google?.status === 'needs_reauth'
  ```
  Replace with:
  ```js
  const google = (status?.providers || []).find((p) => p.provider === 'google') || null
  const connected = !!google
  const needsReauth = google?.status === 'needs_reauth'
  // Raw scopes never reach the client (privacy decision from slice-1) — the
  // server derives this boolean from the stored granted scopes (contract §A).
  const canWrite = connected && !needsReauth && !!google?.can_write_email
  ```

- [ ] **Step 6: Add the "Enable email actions" banner, mirroring the `needsReauth` banner's markup shape, immediately after that banner block.**
  Current code (the `needsReauth` banner, unchanged, followed by the `syncing` block):
  ```jsx
      {needsReauth && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Google needs to be reconnected</p>
            <p className="kit-muted">Your authorization expired or was revoked. Reconnect to resume syncing your inbox.</p>
          </div>
          <Button variant="primary" size="sm" onClick={connect}>Reconnect</Button>
        </Card>
      )}

      {syncing && (
  ```
  Replace with (inserting the new banner between them):
  ```jsx
      {needsReauth && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Google needs to be reconnected</p>
            <p className="kit-muted">Your authorization expired or was revoked. Reconnect to resume syncing your inbox.</p>
          </div>
          <Button variant="primary" size="sm" onClick={connect}>Reconnect</Button>
        </Card>
      )}

      {connected && !needsReauth && !canWrite && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--sky-100)', color: 'var(--sky-600)' }}><Icon name="mail" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Enable email actions</p>
            <p className="kit-muted">ScuffedOS has read-only access. Re-connect Google and tick the Gmail checkboxes to allow replying, deleting, starring and labeling.</p>
          </div>
          <Button variant="primary" size="sm" onClick={connect}>Enable</Button>
        </Card>
      )}

      {syncing && (
  ```

- [ ] **Step 7: Verify the banner and gate compile and render conditionally.**
  Run:
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0. Then run:
  ```
  grep -n "canWrite\|Enable email actions\|ScuffedOS has read-only access" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx
  ```
  Expected: three matches — the `canWrite` derivation, the banner title, and the banner body text.

- [ ] **Step 8: Run the full backend suite (this task touched no backend code, but Global Constraints require reporting the count before any task is complete) and the frontend build together, then commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: `428 passed, 1 skipped` (unchanged from Task 14's count — this task is frontend-only, no backend test files touched). This is a relative estimate — report the exact printed count as the actual gate. Then:
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/screens/EmailScreen.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): gate write UI on can_write_email + add Enable-actions banner

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 16: action bar + star indicator + sort dropdown

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`

**Interfaces:**
- Consumes: `api.emailFlags(id, {unread?, starred?})`, `api.emailLabels(id, {add, remove})`, `api.emailLabelList()`, `api.emailTrash(id)` (Task 15); `EmailOut.starred: bool`, `EmailOut.label_ids: List[str]` (contract §D/§F, Task 6/8); `LabelOut {id, name, type}` (contract §F, Task 10); `canWrite` boolean and `refresh()`/`groups` memo (Task 15 / slice-1 EmailScreen).
- Produces: reading-pane action bar (Reply/Forward open `composeMode`, consumed by Task 17); `labels` state (`LabelOut[]`) and `emailLabelList()` fetch-on-open, consumed by Task 17's label checkboxes if reused; `sortKey` state and the sorted `groups` ordering, consumed by no later task (terminal within P5 for sorting); inline `actionError` state string, rendered pattern reused by Task 17's compose overlay.

No test harness exists for EmailScreen (slice-1 shipped none). The gate for every step is `npm run build` exiting 0 plus targeted `grep` verification; full interactive verification happens in Task 20's browser pass.

- [ ] **Step 1: Register the missing icons (reply, forward, star, tag) in `Icon.jsx`.**
  Run first to confirm they are not already registered:
  ```
  grep -n "reply\|forward\|star\|tag" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx
  ```
  Expected: no matches (none of Reply/Forward/Star/Tag are currently imported or mapped). Current import block tail and map tail (verify via `Read` before editing):
  ```js
  import {
    Activity,
    AlarmClock,
    AlertTriangle,
    AlignLeft,
    Apple,
    Archive,
    ArrowDownLeft,
    ArrowRight,
    ArrowUp,
    ArrowUpRight,
    AudioLines,
    Bell,
    Bike,
    BookOpen,
    Brain,
    Cake,
    Calendar,
    CalendarDays,
    ChartLine,
    Check,
    CheckCheck,
    ChevronLeft,
    ChevronRight,
    CircleCheckBig,
    Clock,
    CornerDownLeft,
    Droplet,
    Dumbbell,
    Egg,
    File,
    FileText,
    Flag,
    Flame,
    Flower2,
    Folder,
    Footprints,
    Heart,
    House,
    Inbox,
    LayoutDashboard,
    Lightbulb,
    ListChecks,
    Mail,
    MapPin,
    Mic,
    Moon,
    Paperclip,
    PartyPopper,
    PenLine,
    Plus,
    RefreshCw,
    Repeat,
    Sandwich,
    Search,
    Send,
    Settings,
    SlidersHorizontal,
    Smartphone,
    Sparkles,
    Square,
    Table,
    Trash2,
    TrendingUp,
    Unplug,
    Upload,
    Users,
    Utensils,
    Video,
    Wallet,
    Waves,
    Wifi,
    Wind,
    X,
    Zap,
  } from 'lucide-react'
  ```
  Replace the import list with (inserting `Forward`, `Reply`, `Star`, `Tag` alphabetically):
  ```js
  import {
    Activity,
    AlarmClock,
    AlertTriangle,
    AlignLeft,
    Apple,
    Archive,
    ArrowDownLeft,
    ArrowRight,
    ArrowUp,
    ArrowUpRight,
    AudioLines,
    Bell,
    Bike,
    BookOpen,
    Brain,
    Cake,
    Calendar,
    CalendarDays,
    ChartLine,
    Check,
    CheckCheck,
    ChevronLeft,
    ChevronRight,
    CircleCheckBig,
    Clock,
    CornerDownLeft,
    Droplet,
    Dumbbell,
    Egg,
    File,
    FileText,
    Flag,
    Flame,
    Flower2,
    Folder,
    Footprints,
    Forward,
    Heart,
    House,
    Inbox,
    LayoutDashboard,
    Lightbulb,
    ListChecks,
    Mail,
    MapPin,
    Mic,
    Moon,
    Paperclip,
    PartyPopper,
    PenLine,
    Plus,
    RefreshCw,
    Repeat,
    Reply,
    Sandwich,
    Search,
    Send,
    Settings,
    SlidersHorizontal,
    Smartphone,
    Sparkles,
    Square,
    Star,
    Table,
    Tag,
    Trash2,
    TrendingUp,
    Unplug,
    Upload,
    Users,
    Utensils,
    Video,
    Wallet,
    Waves,
    Wifi,
    Wind,
    X,
    Zap,
  } from 'lucide-react'
  ```
  Current `ICONS` map (tail, verify via `Read` before editing):
  ```js
    footprints: Footprints,
    heart: Heart,
    house: House,
    inbox: Inbox,
    'layout-dashboard': LayoutDashboard,
    lightbulb: Lightbulb,
    'list-checks': ListChecks,
    mail: Mail,
    'map-pin': MapPin,
    mic: Mic,
    moon: Moon,
    paperclip: Paperclip,
    'party-popper': PartyPopper,
    'pen-line': PenLine,
    plus: Plus,
    'refresh-cw': RefreshCw,
    repeat: Repeat,
    sandwich: Sandwich,
    search: Search,
    send: Send,
    settings: Settings,
    'sliders-horizontal': SlidersHorizontal,
    smartphone: Smartphone,
    sparkles: Sparkles,
    square: Square,
    table: Table,
    'trash-2': Trash2,
  ```
  Replace with (inserting `forward`, `reply`, `star`, `tag` in kebab-case at their alphabetical slots):
  ```js
    footprints: Footprints,
    forward: Forward,
    heart: Heart,
    house: House,
    inbox: Inbox,
    'layout-dashboard': LayoutDashboard,
    lightbulb: Lightbulb,
    'list-checks': ListChecks,
    mail: Mail,
    'map-pin': MapPin,
    mic: Mic,
    moon: Moon,
    paperclip: Paperclip,
    'party-popper': PartyPopper,
    'pen-line': PenLine,
    plus: Plus,
    'refresh-cw': RefreshCw,
    repeat: Repeat,
    reply: Reply,
    sandwich: Sandwich,
    search: Search,
    send: Send,
    settings: Settings,
    'sliders-horizontal': SlidersHorizontal,
    smartphone: Smartphone,
    sparkles: Sparkles,
    square: Square,
    star: Star,
    table: Table,
    tag: Tag,
    'trash-2': Trash2,
  ```

- [ ] **Step 2: Verify the icon registration compiles.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  grep -c "forward: Forward\|reply: Reply\|star: Star\|tag: Tag" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx
  ```
  Expected: `4`.

- [ ] **Step 3: Commit the icon registration on its own.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/lib/Icon.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(icons): register reply/forward/star/tag from lucide-react

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

- [ ] **Step 4: Add action-bar state, sort state, label-menu state, and the sort/action handlers to `EmailScreen`.**
  Current top-of-component state block (verify via `Read` before editing — this is the state block as left by Task 15):
  ```js
  export function EmailScreen() {
    const [status, setStatus] = React.useState(null)   // null = /status not answered yet
    const [inbox, setInbox] = React.useState(null)     // null = not loaded
    const [selId, setSelId] = React.useState(null)
    const [detail, setDetail] = React.useState(null)   // full email incl. body, for selId
  ```
  Replace with:
  ```js
  export function EmailScreen() {
    const [status, setStatus] = React.useState(null)   // null = /status not answered yet
    const [inbox, setInbox] = React.useState(null)     // null = not loaded
    const [selId, setSelId] = React.useState(null)
    const [detail, setDetail] = React.useState(null)   // full email incl. body, for selId
    const [sortKey, setSortKey] = React.useState('newest')  // newest | oldest | sender | unread
    const [composeMode, setComposeMode] = React.useState(null)  // null | 'new' | 'reply' | 'forward' (Task 17)
    const [labels, setLabels] = React.useState(null)   // LabelOut[] | null = not loaded yet
    const [labelMenuOpen, setLabelMenuOpen] = React.useState(false)
    const [actionError, setActionError] = React.useState('')  // transient inline error, cleared on next successful action
  ```

- [ ] **Step 5: Update the `groups` memo to apply `sortKey`, right after the existing memo.**
  Current code (verify via `Read` before editing):
  ```js
    const groups = React.useMemo(() => GROUPS.map((g) => ({
      ...g, items: (inbox?.[g.key] || []),
    })), [inbox])
  ```
  Replace with:
  ```js
    const sortItems = React.useCallback((items) => {
      const arr = [...items]
      if (sortKey === 'oldest') arr.sort((a, b) => new Date(a.received_at) - new Date(b.received_at))
      else if (sortKey === 'sender') arr.sort((a, b) => (a.from_name || a.from_email).localeCompare(b.from_name || b.from_email))
      else if (sortKey === 'unread') arr.sort((a, b) => (b.unread === a.unread ? 0 : b.unread ? 1 : -1))
      else arr.sort((a, b) => new Date(b.received_at) - new Date(a.received_at))  // 'newest' (default)
      return arr
    }, [sortKey])
    const groups = React.useMemo(() => GROUPS.map((g) => ({
      ...g, items: sortItems(inbox?.[g.key] || []),
    })), [inbox, sortItems])
  ```

- [ ] **Step 6: Add the write-action handlers (star toggle, read/unread toggle, trash, label add/remove, label-menu open) after the existing `sync` handler.**
  Current code (verify via `Read` before editing):
  ```js
    const connect = () => {
      api.oauthConnect('google')
        .then((r) => { if (r?.authorize_url) window.location = r.authorize_url })
        .catch(() => {})
    }
    const sync = () => { api.emailSync().then(() => refresh()).catch(() => {}) }
  ```
  Replace with:
  ```js
    const connect = () => {
      api.oauthConnect('google')
        .then((r) => { if (r?.authorize_url) window.location = r.authorize_url })
        .catch(() => {})
    }
    const sync = () => { api.emailSync().then(() => refresh()).catch(() => {}) }

    // Confirm-first writes (contract §F): the Gmail call happens server-side
    // before any local change; on failure the store is untouched and we only
    // set actionError — nothing else in the pane changes.
    const runAction = (promise) => {
      setActionError('')
      return promise
        .then((result) => { refresh(); return result })
        .catch((err) => { setActionError(err?.message || 'That action failed. Try again.') })
    }
    const toggleStar = (e) => {
      runAction(api.emailFlags(e.id, { starred: !e.starred })).then(() => {
        if (selId === e.id) api.emailDetail(e.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
      })
    }
    const toggleRead = (e) => {
      runAction(api.emailFlags(e.id, { unread: !e.unread })).then(() => {
        if (selId === e.id) api.emailDetail(e.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
      })
    }
    const trashSelected = () => {
      if (selId == null) return
      runAction(api.emailTrash(selId)).then(() => { setSelId(null); setDetail(null) })
    }
    const openLabelMenu = () => {
      setLabelMenuOpen((v) => !v)
      if (labels == null) api.emailLabelList().then((ls) => { if (Array.isArray(ls)) setLabels(ls) }).catch(() => setLabels([]))
    }
    const toggleLabel = (labelId) => {
      if (!detail) return
      const has = (detail.label_ids || []).includes(labelId)
      const payload = has ? { add: [], remove: [labelId] } : { add: [labelId], remove: [] }
      runAction(api.emailLabels(detail.id, payload)).then(() => {
        api.emailDetail(detail.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
      })
    }
  ```

- [ ] **Step 7: Add the star glyph to list rows.**
  Current row markup (verify via `Read` before editing):
  ```jsx
                {g.items.map((e) => (
                  <div key={e.id} className={'kit-mail' + (e.id === selId ? ' is-active' : '')} onClick={() => setSelId(e.id)}>
                    <span className={'kit-mail__dot' + (e.unread ? '' : ' read')} />
                    <div className="kit-mail__main">
                      <div className="kit-mail__top">
                        <span className="kit-mail__from">{e.from_name || e.from_email}</span>
                        <span className="kit-mail__time">{e.when}</span>
                      </div>
                      <p className="kit-mail__subj">{e.subject || '(no subject)'}</p>
                      <p className="kit-mail__snip">{e.snippet}</p>
                    </div>
                  </div>
                ))}
  ```
  Replace with (star glyph inserted into `kit-mail__top`, next to `kit-mail__time`):
  ```jsx
                {g.items.map((e) => (
                  <div key={e.id} className={'kit-mail' + (e.id === selId ? ' is-active' : '')} onClick={() => setSelId(e.id)}>
                    <span className={'kit-mail__dot' + (e.unread ? '' : ' read')} />
                    <div className="kit-mail__main">
                      <div className="kit-mail__top">
                        <span className="kit-mail__from">{e.from_name || e.from_email}</span>
                        <span className="kit-inline" style={{ gap: 6 }}>
                          {e.starred && <Icon name="star" style={{ width: 13, height: 13, color: 'var(--honey-600)', fill: 'var(--honey-600)' }} />}
                          <span className="kit-mail__time">{e.when}</span>
                        </span>
                      </div>
                      <p className="kit-mail__subj">{e.subject || '(no subject)'}</p>
                      <p className="kit-mail__snip">{e.snippet}</p>
                    </div>
                  </div>
                ))}
  ```

- [ ] **Step 8: Add the sort `<select>` next to Sync in the Inbox card's action area, gated on nothing (sort works read-only regardless of `canWrite`).**
  Current Inbox card header (verify via `Read` before editing):
  ```jsx
          <Card title="Inbox" eyebrow={eyebrow}
            action={
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                {needCount > 0 && <Badge color="green" dot>{needCount} need you</Badge>}
                <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
              </div>
            }>
  ```
  Replace with:
  ```jsx
          <Card title="Inbox" eyebrow={eyebrow}
            action={
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                {needCount > 0 && <Badge color="green" dot>{needCount} need you</Badge>}
                <select value={sortKey} onChange={(e) => setSortKey(e.target.value)} style={sortSelectStyle} aria-label="Sort inbox">
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                  <option value="sender">Sender</option>
                  <option value="unread">Unread first</option>
                </select>
                <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
              </div>
            }>
  ```
  Then add the `sortSelectStyle` constant just above the `return (` of the component (verify via `Read` for the exact line above `return (`), mirroring `NutritionScreen`'s `selectStyle`:
  ```js
    const sortSelectStyle = {
      padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
      border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
      color: 'var(--text-strong)', cursor: 'pointer',
    }

    return (
  ```

- [ ] **Step 9: Add the reading-pane action bar (Reply/Forward/Star/Read-Unread/Label menu/Trash) plus the inline error line, gated on `canWrite`, placed inside the detail Card right after the eyebrow/title header (before the AI-summary block).**
  Current detail Card open (verify via `Read` before editing):
  ```jsx
              <>
                <Card eyebrow={`${detail.from_name || detail.from_email}${detail.from_email && detail.from_name ? ` · ${detail.from_email}` : ''}`} title={detail.subject || '(no subject)'}>
                  {(detail.summary || []).length > 0 && (
  ```
  Replace with (action bar + label dropdown + inline error inserted between the Card open and the summary block):
  ```jsx
              <>
                <Card eyebrow={`${detail.from_name || detail.from_email}${detail.from_email && detail.from_name ? ` · ${detail.from_email}` : ''}`} title={detail.subject || '(no subject)'}>
                  {canWrite && (
                    <div className="kit-inline" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 12, position: 'relative' }}>
                      <Button variant="soft" size="sm" iconLeft={<Icon name="reply" />} onClick={() => setComposeMode('reply')}>Reply</Button>
                      <Button variant="soft" size="sm" iconLeft={<Icon name="forward" />} onClick={() => setComposeMode('forward')}>Forward</Button>
                      <IconButton label={detail.starred ? 'Unstar' : 'Star'} size="sm" onClick={() => toggleStar(detail)}>
                        <Icon name="star" style={detail.starred ? { color: 'var(--honey-600)', fill: 'var(--honey-600)' } : undefined} />
                      </IconButton>
                      <IconButton label={detail.unread ? 'Mark read' : 'Mark unread'} size="sm" onClick={() => toggleRead(detail)}><Icon name="check-check" /></IconButton>
                      <IconButton label="Labels" size="sm" onClick={openLabelMenu}><Icon name="tag" /></IconButton>
                      <IconButton label="Trash" size="sm" onClick={trashSelected}><Icon name="trash-2" /></IconButton>
                      {labelMenuOpen && (
                        <div className="sa-card" style={{ position: 'absolute', top: 40, left: 0, zIndex: 20, padding: 10, minWidth: 180, boxShadow: 'var(--shadow-lg)' }}>
                          {(labels || []).length === 0 && <p className="kit-muted">No labels.</p>}
                          {(labels || []).map((l) => (
                            <Checkbox key={l.id} checked={(detail.label_ids || []).includes(l.id)} onChange={() => toggleLabel(l.id)} label={l.name} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {actionError && <p className="kit-muted" style={{ color: 'var(--clay-600)', marginBottom: 10 }}>{actionError}</p>}
                  {(detail.summary || []).length > 0 && (
  ```

- [ ] **Step 10: Import `IconButton` and `Checkbox` in `EmailScreen.jsx` (not previously imported).**
  Current import line (verify via `Read` before editing):
  ```js
  import { Card, Badge, Button } from '../components/ui.jsx'
  ```
  Replace with:
  ```js
  import { Card, Badge, Button, IconButton, Checkbox } from '../components/ui.jsx'
  ```

- [ ] **Step 11: Verify everything compiles and the new markup/handlers exist.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  grep -c "toggleStar\|toggleRead\|trashSelected\|openLabelMenu\|toggleLabel\|sortKey\|actionError" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx
  ```
  Expected: a nonzero count for each name (run individually if a combined grep count is ambiguous):
  ```
  for n in toggleStar toggleRead trashSelected openLabelMenu toggleLabel sortKey actionError; do echo "$n: $(grep -c "$n" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx)"; done
  ```
  Expected: every count >= 1.

- [ ] **Step 12: Run the full backend suite (unchanged by this frontend-only task) and the frontend build, then commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: `428 passed, 1 skipped` (unchanged from Task 15's count — this task is frontend-only, no backend test files touched). This is a relative estimate — report the exact printed count as the actual gate.
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/screens/EmailScreen.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): add reading-pane action bar, star indicator, and sort dropdown

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 17: compose overlay + AI-draft button

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx`

**Interfaces:**
- Consumes: `composeMode` state (`null | 'new' | 'reply' | 'forward'`, Task 16); `api.emailSend`, `api.emailReply`, `api.emailForward`, `api.emailDraft` (Task 15); `canWrite` (Task 15); `detail` (`EmailDetail` with `from_email`, `from_name`, `subject`, `body`, `when`, `id` — slice-1 + contract §F); `runAction`/`actionError` inline-error pattern (Task 16).
- Produces: the compose overlay UI — terminal within P5; consumed by Task 20's browser verification only (no later plan task depends on new exports from this one).

No test harness exists for EmailScreen. The gate for every step is `npm run build` exiting 0 plus targeted `grep` verification; full interactive verification (including the live AI-draft round trip) happens in Task 20's browser pass.

- [ ] **Step 1: Add compose-local state (fields, AI-instruction toggle, draft-in-flight) and the quote-block builder, placed with the other state declarations from Task 16.**
  Current state block (as left by Task 16, verify via `Read` before editing):
  ```js
    const [sortKey, setSortKey] = React.useState('newest')  // newest | oldest | sender | unread
    const [composeMode, setComposeMode] = React.useState(null)  // null | 'new' | 'reply' | 'forward' (Task 17)
    const [labels, setLabels] = React.useState(null)   // LabelOut[] | null = not loaded yet
    const [labelMenuOpen, setLabelMenuOpen] = React.useState(false)
    const [actionError, setActionError] = React.useState('')  // transient inline error, cleared on next successful action
  ```
  Replace with:
  ```js
    const [sortKey, setSortKey] = React.useState('newest')  // newest | oldest | sender | unread
    const [composeMode, setComposeMode] = React.useState(null)  // null | 'new' | 'reply' | 'forward'
    const [labels, setLabels] = React.useState(null)   // LabelOut[] | null = not loaded yet
    const [labelMenuOpen, setLabelMenuOpen] = React.useState(false)
    const [actionError, setActionError] = React.useState('')  // transient inline error, cleared on next successful action
    const [composeTo, setComposeTo] = React.useState('')
    const [composeSubject, setComposeSubject] = React.useState('')
    const [composeBody, setComposeBody] = React.useState('')
    const [composeError, setComposeError] = React.useState('')  // separate from actionError — scoped to the overlay, never clears the box
    const [aiOpen, setAiOpen] = React.useState(false)
    const [aiInstructions, setAiInstructions] = React.useState('')
    const [aiDrafted, setAiDrafted] = React.useState(false)  // false = "Draft", true = "Regenerate"
    const [aiBusy, setAiBusy] = React.useState(false)
    const [sending, setSending] = React.useState(false)
  ```

- [ ] **Step 2: Add the quote-block builder and the compose-open/close/send handlers, placed after the Task-16 write-action handlers (`toggleLabel`).**
  Current tail of the handler block (as left by Task 16, verify via `Read` before editing):
  ```js
    const toggleLabel = (labelId) => {
      if (!detail) return
      const has = (detail.label_ids || []).includes(labelId)
      const payload = has ? { add: [], remove: [labelId] } : { add: [labelId], remove: [] }
      runAction(api.emailLabels(detail.id, payload)).then(() => {
        api.emailDetail(detail.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
      })
    }
  ```
  Replace with (appending compose helpers after `toggleLabel`):
  ```js
    const toggleLabel = (labelId) => {
      if (!detail) return
      const has = (detail.label_ids || []).includes(labelId)
      const payload = has ? { add: [], remove: [labelId] } : { add: [labelId], remove: [] }
      runAction(api.emailLabels(detail.id, payload)).then(() => {
        api.emailDetail(detail.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
      })
    }

    // Quote-block divider format is frozen by contract §I: reply/forward prefill
    // quotes the already-loaded detail.body below this exact divider line.
    const quoteBlock = (d) => `\n\n--- On ${d.when}, ${d.from_name || d.from_email} wrote: ---\n${d.body || ''}`

    const openCompose = (mode) => {
      setComposeError('')
      setAiOpen(false); setAiInstructions(''); setAiDrafted(false)
      if (mode === 'reply' && detail) {
        setComposeTo(detail.from_email)
        setComposeSubject(detail.subject?.toLowerCase().startsWith('re:') ? detail.subject : `Re: ${detail.subject || '(no subject)'}`)
        setComposeBody(quoteBlock(detail))
      } else if (mode === 'forward' && detail) {
        setComposeTo('')
        setComposeSubject(detail.subject?.toLowerCase().startsWith('fwd:') ? detail.subject : `Fwd: ${detail.subject || '(no subject)'}`)
        setComposeBody(quoteBlock(detail))
      } else {
        setComposeTo(''); setComposeSubject(''); setComposeBody('')
      }
      setComposeMode(mode)
    }
    const closeCompose = () => {
      setComposeMode(null); setComposeTo(''); setComposeSubject(''); setComposeBody('')
      setComposeError(''); setAiOpen(false); setAiInstructions(''); setAiDrafted(false)
    }
    const draftWithAi = () => {
      if (!aiInstructions.trim()) return
      setAiBusy(true)
      // notes must be only what the user has actually typed — for reply/forward,
      // composeBody was seeded with the full quote block (quoteBlock(detail)),
      // which is redundant with (and differently formatted from) the same
      // content the backend already fetches live via original.body_excerpt
      // (contract §G). Strip everything from the quote divider onward before
      // sending, matching the pre-quote-only framing used when the response
      // handler below re-appends the quote after drafting.
      const notes = composeBody.split(/\n\n--- On .+ wrote: ---\n/)[0]
      api.emailDraft({
        instructions: aiInstructions,
        notes,
        mode: composeMode,
        email_id: composeMode !== 'new' && detail ? detail.id : null,
      }).then((r) => {
        setAiBusy(false)
        if (!r || typeof r.draft !== 'string') { setComposeError("Couldn't draft — try again."); return }
        // Pin (contract §I / spec §8): the draft replaces only the pre-quote
        // section; the quote block (if any) stays appended below it.
        const quote = (composeMode === 'reply' || composeMode === 'forward') && detail ? quoteBlock(detail) : ''
        setComposeBody(r.draft + quote)
        setAiDrafted(true)
      }).catch(() => { setAiBusy(false); setComposeError("Couldn't draft — try again.") })
    }
    const sendCompose = () => {
      if (!composeTo.trim() && composeMode !== 'reply') { setComposeError('To is required.'); return }
      if (!composeSubject.trim() && composeMode !== 'reply') { setComposeError('Subject is required.'); return }
      setSending(true)
      setComposeError('')
      let promise
      if (composeMode === 'reply' && detail) promise = api.emailReply(detail.id, { body: composeBody })
      else if (composeMode === 'forward' && detail) promise = api.emailForward(detail.id, { to: composeTo, body: composeBody })
      else promise = api.emailSend({ to: composeTo, subject: composeSubject, body: composeBody })
      promise.then(() => {
        setSending(false)
        closeCompose()
        refresh()
      }).catch((err) => {
        // Failure keeps EVERYTHING intact (contract §Global Constraints) — only
        // composeError is set; composeTo/composeSubject/composeBody untouched.
        setSending(false)
        setComposeError(err?.message || 'Send failed. Your draft is still here — try again.')
      })
    }
  ```

- [ ] **Step 3: Add the "Compose" button to the Inbox card header (next to the sort `<select>` and Sync button), gated on `canWrite`.**
  Current Inbox card header (as left by Task 16, verify via `Read` before editing):
  ```jsx
          <Card title="Inbox" eyebrow={eyebrow}
            action={
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                {needCount > 0 && <Badge color="green" dot>{needCount} need you</Badge>}
                <select value={sortKey} onChange={(e) => setSortKey(e.target.value)} style={sortSelectStyle} aria-label="Sort inbox">
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                  <option value="sender">Sender</option>
                  <option value="unread">Unread first</option>
                </select>
                <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
              </div>
            }>
  ```
  Replace with (Compose button inserted before Sync):
  ```jsx
          <Card title="Inbox" eyebrow={eyebrow}
            action={
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                {needCount > 0 && <Badge color="green" dot>{needCount} need you</Badge>}
                <select value={sortKey} onChange={(e) => setSortKey(e.target.value)} style={sortSelectStyle} aria-label="Sort inbox">
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                  <option value="sender">Sender</option>
                  <option value="unread">Unread first</option>
                </select>
                {canWrite && <Button variant="soft" size="sm" iconLeft={<Icon name="pen-line" />} onClick={() => openCompose('new')}>Compose</Button>}
                <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
              </div>
            }>
  ```

- [ ] **Step 4: Add the compose overlay Card, rendered above the two-pane grid when `composeMode != null`.**
  Current wrapper start (as left by slice-1 / Task 16, verify via `Read` before editing):
  ```jsx
    return (
      <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
        {needsReauth && (
  ```
  Replace with (compose overlay inserted as the first child of the stack, before the `needsReauth` banner):
  ```jsx
    return (
      <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
        {canWrite && composeMode != null && (
          <Card variant="flat" title={composeMode === 'reply' ? 'Reply' : composeMode === 'forward' ? 'Forward' : 'New message'}
            action={<IconButton label="Close" size="sm" onClick={closeCompose}><Icon name="x" /></IconButton>}>
            <div className="kit-stack" style={{ gap: 10 }}>
              <div className="kit-field">
                <span className="kit-field__label">To</span>
                {composeMode === 'reply' ? (
                  <p className="kit-muted" style={{ margin: 0 }}>{composeTo}</p>
                ) : (
                  <input value={composeTo} onChange={(e) => setComposeTo(e.target.value)} placeholder="name@example.com" style={composeInputStyle} />
                )}
              </div>
              {/* cc omitted from the UI this slice — the API supports it (SendEmail.cc), not exposed here. */}
              <div className="kit-field">
                <span className="kit-field__label">Subject</span>
                <input value={composeSubject} onChange={(e) => setComposeSubject(e.target.value)} placeholder="Subject" style={composeInputStyle} disabled={composeMode === 'reply'} />
              </div>
              <div className="kit-inline" style={{ gap: 8 }}>
                <IconButton label={aiDrafted ? 'Regenerate with AI' : 'Draft with AI'} size="sm" onClick={() => setAiOpen((v) => !v)}><Icon name="sparkles" /></IconButton>
                {aiOpen && (
                  <>
                    <input value={aiInstructions} onChange={(e) => setAiInstructions(e.target.value)} placeholder="What should it say?" style={{ ...composeInputStyle, flex: 1 }} />
                    <Button variant="soft" size="sm" onClick={draftWithAi} disabled={aiBusy || !aiInstructions.trim()}>{aiBusy ? 'Drafting…' : aiDrafted ? 'Regenerate' : 'Draft'}</Button>
                  </>
                )}
              </div>
              <textarea className="kit-desc" value={composeBody} onChange={(e) => setComposeBody(e.target.value)} rows={10} placeholder="Write your message…" style={composeTextareaStyle} />
              {composeError && <p className="kit-muted" style={{ color: 'var(--clay-600)' }}>{composeError}</p>}
              <div className="kit-inline" style={{ gap: 8, justifyContent: 'flex-end' }}>
                <Button variant="ghost" size="sm" onClick={closeCompose}>Cancel</Button>
                <Button variant="primary" size="sm" iconLeft={<Icon name="send" />} onClick={sendCompose} disabled={sending}>{sending ? 'Sending…' : 'Send'}</Button>
              </div>
            </div>
          </Card>
        )}

        {needsReauth && (
  ```

- [ ] **Step 5: Add the `composeInputStyle`/`composeTextareaStyle` constants next to `sortSelectStyle` (Task 16), just above `return (`.**
  Current code (as left by Task 16, verify via `Read` before editing):
  ```js
    const sortSelectStyle = {
      padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
      border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
      color: 'var(--text-strong)', cursor: 'pointer',
    }

    return (
  ```
  Replace with:
  ```js
    const sortSelectStyle = {
      padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
      border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
      color: 'var(--text-strong)', cursor: 'pointer',
    }
    const composeInputStyle = {
      padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
      border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
      color: 'var(--text-strong)', width: '100%',
    }
    const composeTextareaStyle = {
      padding: '10px 12px', borderRadius: 'var(--radius-md)', background: 'var(--surface-sunken)',
      border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
      color: 'var(--text-strong)', width: '100%', resize: 'vertical', lineHeight: 1.5,
    }

    return (
  ```

- [ ] **Step 6: Verify the overlay compiles and every new symbol is present.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  for n in openCompose closeCompose draftWithAi sendCompose quoteBlock composeMode aiDrafted; do echo "$n: $(grep -c "$n" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx)"; done
  ```
  Expected: every count >= 1.
  ```
  grep -n "cc omitted from the UI this slice" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx
  ```
  Expected: one match (documents the deliberate cc omission called out in the task).

- [ ] **Step 7: Manually trace the "failed send keeps the box intact" pin against the code (no test harness exists to assert this automatically — Task 20's browser pass exercises it live).**
  Run:
  ```
  grep -n "setComposeError(err" /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx
  ```
  Expected: one match inside `sendCompose`'s `.catch`, and confirm by inspection that the `.catch` branch calls only `setSending(false)` and `setComposeError(...)` — it must NOT call `closeCompose()` or clear `composeTo`/`composeSubject`/`composeBody`. This is the confirm-first / never-loses-content guarantee from Global Constraints.

- [ ] **Step 8: Run the full backend suite (unchanged by this frontend-only task) and the frontend build, then commit.**
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
  ```
  Expected: `428 passed, 1 skipped` (unchanged from Task 16's count — this task is frontend-only, no backend test files touched). This is a relative estimate — report the exact printed count as the actual gate.
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
  ```
  Expected: exits 0.
  ```
  cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/screens/EmailScreen.jsx
  ```
  ```
  git commit -m "$(cat <<'EOF'
  feat(email): add compose overlay (new/reply/forward) with AI-draft button

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```


### Task 18: Privacy policy wave 2 — read + user-initiated actions (all three copies)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`
- Modify: `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`

**Interfaces:**
- Consumes: The wave-1 canonical markdown and corp-site HTML (both already describe Gmail as read-only, from slice-1 Task 26); the frozen scope string `GOOGLE_SCOPES` (contract §A) which now includes `gmail.modify` + `gmail.send`; the write/compose/AI-draft behavior built by Phases P1–P5 (confirm-first Gmail writes, `email_draft.draft()` user-initiated only, send-through-Gmail via `send_message`).
- Produces: All three privacy-policy copies (markdown canonical, corp-site HTML, gist) updated so the Gmail domain reads "read plus the modify/send scopes" instead of read-only, lists the user-initiated actions (send/reply/forward, trash, star, read/unread, labels), states AI drafts are generated only on explicit user request with the user's own instructions and are never stored, and states outbound mail is sent through Gmail itself (appears in the user's Sent folder). The canonical markdown and corp-site HTML are committed in their own repos; the gist sync is a documented-but-not-executed step requiring explicit user approval.

- [ ] **Step 1: Edit the canonical markdown — Section 1 collect-paragraph + Section 3 Google row**

This is a docs-only slice with no automated test — the guardrail is that the three copies stay in sync and read correctly, verified with `grep -c` after each edit. Do the markdown first (it is the canonical source), then mirror to the HTML site, then document (but do not execute) the gist sync.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`.

**(a)** Section 1's "Connected service data" paragraph currently ends its Gmail sentence with the read-only scope. Replace the exact current line:

```
**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, ScuffedOS reads your inbox messages read-only via the Gmail API after you authorize access through Google's OAuth flow (the `gmail.readonly` scope); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. See Section 4 for how WHOOP and Gmail data are handled.
```

with:

```
**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, ScuffedOS reads your inbox messages via the Gmail API after you authorize access through Google's OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, ScuffedOS acts on your mailbox only when you take an explicit action — sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. See Section 4 for how WHOOP and Gmail data are handled.
```

**(b)** Section 3's Google (Gmail) provider-table row currently reads "read-only". Replace the exact current line:

```
| **Google (Gmail)** | Email source, read-only (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage — see Section 4 |
```

with:

```
| **Google (Gmail)** | Email source — read and user-initiated actions (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage or, when you ask for an AI draft, to generate one — see Section 4. Actions you take (send, reply, forward, trash, star, read/unread, labels) are carried out via the Gmail API using your own account; sent mail is delivered through Gmail and appears in your Sent folder |
```

**Run:**

```bash
grep -c "read plus the modify/send scopes" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "read and user-initiated actions" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "gmail.readonly" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
```

**Expected:** first two print `1`; the third prints `0` (the wave-1 `gmail.readonly` scope mention in Section 1 is gone — Section 4 still names it in step 2 below, which this step does not yet touch, so run this grep again after step 2 where it becomes `0` too).

Do NOT commit yet — the Section 4 block (next step) lands in the same commit.

- [ ] **Step 2: Edit the canonical markdown — Section 4 Gmail block (scope + actions + AI-draft + send-via-Gmail)**

Continue editing `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`. Replace the entire current Gmail paragraph block in Section 4 (the wave-1 read-only block, exact current text):

```
If you choose to connect Gmail:

- Access is **read-only** and is granted only after you explicitly authorize ScuffedOS through Google's OAuth consent flow (the `gmail.readonly` scope). You can review and revoke this access at any time from your Google Account's security settings.
- ScuffedOS reads your inbox messages to display them and to triage them. For each message, the sender, subject, preview snippet, and a bounded plain-text body excerpt (~2 KB) are sent to **Anthropic** to classify the message (needs-reply vs. FYI) and generate a short summary. Only the derived category and summary — never the message body — are stored.
- **Message bodies are not stored.** The inbox list and AI summaries live in the database; the full body of a message is fetched live from the Gmail API only when you open that message, and is never written to disk.
- Gmail data is never sold, never shared with third parties for their own purposes, and never used for advertising.
- You can disconnect Gmail within ScuffedOS at any time. On disconnect, stored email metadata and your Google OAuth tokens are deleted, and ScuffedOS revokes its Google access token. As with all deletions, this is honored within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.
```

with:

```
If you choose to connect Gmail:

- Access is granted only after you explicitly authorize ScuffedOS through Google's OAuth consent flow, and covers **read plus the modify/send scopes** (`gmail.readonly`, `gmail.modify`, `gmail.send`). You can review and revoke this access at any time from your Google Account's security settings.
- ScuffedOS reads your inbox messages to display them and to triage them. For each message, the sender, subject, preview snippet, and a bounded plain-text body excerpt (~2 KB) are sent to **Anthropic** to classify the message (needs-reply vs. FYI) and generate a short summary. Only the derived category and summary — never the message body — are stored.
- **Message bodies are not stored.** The inbox list and AI summaries live in the database; the full body of a message is fetched live from the Gmail API only when you open that message, and is never written to disk.
- Beyond reading, ScuffedOS **acts on your mailbox only on your explicit action.** You can send a new message, reply, or forward; move a message to Trash; star or unstar it; mark it read or unread; and apply or remove labels. Every one of these actions happens only when you click the corresponding control — nothing is automated.
- **AI-drafted replies are generated only when you ask for one**, using the instructions and any notes you type into the compose box at that moment. A draft is never generated automatically (not on opening a message, not on sync). Draft text is **never stored server-side** — it exists only in your compose box until you send it or discard it.
- **Outbound mail is sent through Gmail itself.** When you send, reply, or forward, ScuffedOS submits the message to the Gmail API using your own authorized account; Gmail delivers it, and it appears in your Gmail Sent folder exactly as if you had sent it from Gmail directly.
- Gmail data is never sold, never shared with third parties for their own purposes, and never used for advertising.
- You can disconnect Gmail within ScuffedOS at any time. On disconnect, stored email metadata and your Google OAuth tokens are deleted, and ScuffedOS revokes its Google access token. As with all deletions, this is honored within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.
```

**Run:**

```bash
grep -c "acts on your mailbox only on your explicit action" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "AI-drafted replies are generated only when you ask" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "Outbound mail is sent through Gmail itself" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "gmail.readonly" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "read plus the modify/send scopes" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
```

**Expected:** the first three print `1`; `gmail.readonly` now prints `1` (only the Section 4 scope-list mention remains — Section 1's earlier reference was replaced in Step 1); `read plus the modify/send scopes` prints `2` (Section 1 + Section 4).

**Commit (canonical markdown only — the corp-site copy follows in the next step):**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git checkout m5-email-slice2
git add docs/privacy-policy.md
git commit -m "$(cat <<'EOF'
docs(privacy): wave 2 — Gmail reads plus user-initiated actions

Section 1 + Section 3's Google row and Section 4's Gmail block now describe
the gmail.modify/gmail.send scope upgrade: user-initiated send/reply/forward,
trash, star, read/unread, and label actions; AI drafts generated only on
explicit request and never stored; outbound mail sent through Gmail itself
(lands in the user's Sent folder).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Expected:** commit succeeds on branch `m5-email-slice2`.

- [ ] **Step 3: Mirror to the corp-site HTML copy (scuffed-corporation/privacy/index.html)**

The corp site is a **separate git repo** at `/Users/dylanschempp/PycharmProjects/scuffed-corporation`. Apply the same content in HTML, using the site's existing entity style (`&rsquo;`, `&ldquo;`/`&rdquo;`, `&mdash;`, `&middot;`, `&nbsp;`). The wave-1 Gmail section there is `id="gmail-data"` (heading "4a. Gmail data"), added by slice-1's corp-site commit `8386752`.

Edit `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`.

**(a)** Section 1 paragraph — replace the exact current line:

```html
        <p><strong>Connected service data (with your consent).</strong> If you connect a WHOOP account, Scuffed OS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP&rsquo;s OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, Scuffed OS reads your inbox messages read-only via the Gmail API after you authorize access through Google&rsquo;s OAuth flow (the <code>gmail.readonly</code> scope); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. See <a href="#whoop-data">Section 4</a> and <a href="#gmail-data">Section 4a</a> for how WHOOP and Gmail data are handled.</p>
```

with:

```html
        <p><strong>Connected service data (with your consent).</strong> If you connect a WHOOP account, Scuffed OS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP&rsquo;s OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, Scuffed OS reads your inbox messages via the Gmail API after you authorize access through Google&rsquo;s OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, Scuffed OS acts on your mailbox only when you take an explicit action &mdash; sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. See <a href="#whoop-data">Section 4</a> and <a href="#gmail-data">Section 4a</a> for how WHOOP and Gmail data are handled.</p>
```

**(b)** Section 3 Google table row — replace the exact current block:

```html
              <tr>
                <th scope="row"><strong>Google</strong> (Gmail)</th>
                <td>Email source, read-only (only if you connect it)</td>
                <td>OAuth authorization; Scuffed OS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage &mdash; see <a href="#gmail-data">Section 4a</a></td>
              </tr>
```

with:

```html
              <tr>
                <th scope="row"><strong>Google</strong> (Gmail)</th>
                <td>Email source &mdash; read and user-initiated actions (only if you connect it)</td>
                <td>OAuth authorization; Scuffed OS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage or, when you ask for an AI draft, to generate one &mdash; see <a href="#gmail-data">Section 4a</a>. Actions you take (send, reply, forward, trash, star, read/unread, labels) are carried out via the Gmail API using your own account; sent mail is delivered through Gmail and appears in your Sent folder</td>
              </tr>
```

**(c)** Section 4a Gmail block — replace the entire current `<section id="gmail-data">` body (exact current block):

```html
    <!-- 04b / gmail data -->
    <section class="sec" aria-labelledby="gmail-data">
      <p class="sec-label"><span>04 &mdash; gmail data</span><span>read-only &middot; bodies not stored</span></p>
      <div class="sec-main">
        <h2 id="gmail-data">4a. Gmail data</h2>
        <p>If you choose to connect Gmail:</p>
        <ul>
          <li>Access is <strong>read-only</strong> and is granted only after you explicitly authorize Scuffed OS through Google&rsquo;s OAuth consent flow (the <code>gmail.readonly</code> scope). You can review and revoke this access at any time from your Google Account&rsquo;s security settings.</li>
          <li>Scuffed OS reads your inbox messages to display them and to triage them. For each message, the sender, subject, preview snippet, and a bounded plain-text body excerpt (~2&nbsp;KB) are sent to <strong>Anthropic</strong> to classify the message (needs-reply vs. FYI) and generate a short summary. Only the derived category and summary &mdash; never the message body &mdash; are stored.</li>
          <li><strong>Message bodies are not stored.</strong> The inbox list and AI summaries live in the database; the full body of a message is fetched live from the Gmail API only when you open that message, and is never written to disk.</li>
          <li>Gmail data is never sold, never shared with third parties for their own purposes, and never used for advertising.</li>
          <li>You can disconnect Gmail within Scuffed OS at any time. On disconnect, stored email metadata and your Google OAuth tokens are deleted, and Scuffed OS revokes its Google access token. As with all deletions, this is honored within 30 days.</li>
        </ul>
        <p>Scuffed OS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.</p>
      </div>
    </section>
```

with:

```html
    <!-- 04b / gmail data -->
    <section class="sec" aria-labelledby="gmail-data">
      <p class="sec-label"><span>04 &mdash; gmail data</span><span>read &middot; user-initiated actions &middot; bodies not stored</span></p>
      <div class="sec-main">
        <h2 id="gmail-data">4a. Gmail data</h2>
        <p>If you choose to connect Gmail:</p>
        <ul>
          <li>Access is granted only after you explicitly authorize Scuffed OS through Google&rsquo;s OAuth consent flow, and covers <strong>read plus the modify/send scopes</strong> (<code>gmail.readonly</code>, <code>gmail.modify</code>, <code>gmail.send</code>). You can review and revoke this access at any time from your Google Account&rsquo;s security settings.</li>
          <li>Scuffed OS reads your inbox messages to display them and to triage them. For each message, the sender, subject, preview snippet, and a bounded plain-text body excerpt (~2&nbsp;KB) are sent to <strong>Anthropic</strong> to classify the message (needs-reply vs. FYI) and generate a short summary. Only the derived category and summary &mdash; never the message body &mdash; are stored.</li>
          <li><strong>Message bodies are not stored.</strong> The inbox list and AI summaries live in the database; the full body of a message is fetched live from the Gmail API only when you open that message, and is never written to disk.</li>
          <li>Beyond reading, Scuffed OS <strong>acts on your mailbox only on your explicit action.</strong> You can send a new message, reply, or forward; move a message to Trash; star or unstar it; mark it read or unread; and apply or remove labels. Every one of these actions happens only when you click the corresponding control &mdash; nothing is automated.</li>
          <li><strong>AI-drafted replies are generated only when you ask for one</strong>, using the instructions and any notes you type into the compose box at that moment. A draft is never generated automatically (not on opening a message, not on sync). Draft text is <strong>never stored server-side</strong> &mdash; it exists only in your compose box until you send it or discard it.</li>
          <li><strong>Outbound mail is sent through Gmail itself.</strong> When you send, reply, or forward, Scuffed OS submits the message to the Gmail API using your own authorized account; Gmail delivers it, and it appears in your Gmail Sent folder exactly as if you had sent it from Gmail directly.</li>
          <li>Gmail data is never sold, never shared with third parties for their own purposes, and never used for advertising.</li>
          <li>You can disconnect Gmail within Scuffed OS at any time. On disconnect, stored email metadata and your Google OAuth tokens are deleted, and Scuffed OS revokes its Google access token. As with all deletions, this is honored within 30 days.</li>
        </ul>
        <p>Scuffed OS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.</p>
      </div>
    </section>
```

**Run** (verify the HTML edits and that the file is still well-formed):

```bash
grep -c "read and user-initiated actions" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "acts on your mailbox only on your explicit action" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "Outbound mail is sent through Gmail itself" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c "gmail.readonly" /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
python3 -c "import html.parser; p=html.parser.HTMLParser(); p.feed(open('/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html').read()); print('html-parses-ok')"
```

**Expected:** first three `grep -c` print `1`; `gmail.readonly` prints `1` (only the `<code>` scope-list mention remains, matching the markdown); the python line prints `html-parses-ok` with no exception.

**Commit in the corp-site repo:**

```bash
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation
git add privacy/index.html
git commit -m "$(cat <<'EOF'
privacy: wave 2 — Gmail reads plus user-initiated actions (sync with app policy)

Mirrors docs/privacy-policy.md in the ScuffedOS repo (M5 email slice-2): the
Section 3 Google row and Section 4a block now describe the gmail.modify/
gmail.send scope upgrade, user-initiated send/reply/forward/trash/star/
read-unread/label actions, AI drafts generated only on request and never
stored, and outbound mail sent through Gmail (lands in Sent).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Expected:** commit succeeds. (Deploying the static site is out of scope for this slice — the commit is the deliverable, matching the slice-1 convention.)

- [ ] **Step 4: Document (do NOT execute) the gist sync — REQUIRES EXPLICIT USER APPROVAL**

The gist `439cee7cba3ac9077da6a5b81f83527c` (file `privacy-policy.md`, viewable at `https://gist.github.com/daschempp/439cee7cba3ac9077da6a5b81f83527c`) is the third copy and must eventually match the updated canonical markdown verbatim. **Learned in slice-1 (M5 Task 26): the auto-mode permission classifier blocks this PATCH as a public publish.** Do NOT attempt to run it as part of this task. Instead, hand the exact command to the user for them to run or explicitly approve:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
python3 - <<'PY'
import json, subprocess
body = json.dumps({
    "description": "ScuffedOS Privacy Policy",
    "files": {"privacy-policy.md": {"content": open("docs/privacy-policy.md").read()}},
})
subprocess.run(
    ["gh", "api", "-X", "PATCH", "gists/439cee7cba3ac9077da6a5b81f83527c", "--input", "-"],
    input=body, text=True, check=True,
)
print("gist-patched")
PY
```

**Verification command for the user to run afterward** (also do not auto-run):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
gh gist view 439cee7cba3ac9077da6a5b81f83527c --raw > /tmp/gist_privacy.md
diff docs/privacy-policy.md /tmp/gist_privacy.md && echo "GIST-IN-SYNC"
```

**Expected once the user runs it:** `gist-patched` prints with no error, then `diff` prints nothing and `GIST-IN-SYNC` appears. Until the user runs this, note the gist as the one remaining out-of-sync copy — same posture as slice-1's PENDING USER item. No git commit for this step (the gist is not in the repo).

---

### Task 19: smoke_google write leg (send-to-self → verify → trash)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_google.py`

**Interfaces:**
- Consumes: `store._can_write_email(scopes: str) -> bool` and `store.get_provider_account("google")["can_write_email"]` (contract §A, built in Task 1); `GoogleProvider.send_message(raw_rfc822: bytes, thread_id: str | None = None) -> str` and `GoogleProvider.trash_message(source_id: str) -> None` (contract §C, built in Tasks 3–4); `google._build_rfc822(*, to, subject, body, cc=None, in_reply_to=None, references=None) -> bytes` (contract §B, built in Task 2); `GMAIL_API_BASE` constant from `app/providers/google.py`; the existing `Reporter` class and `main()` structure already in `smoke_google.py` (read above — sections 1–5 stay unchanged, this task appends section 6 inside the same `try` block before the `except`).
- Produces: `smoke_google.py` gains a "6. Write path" section that: (a) if the connected account cannot write (`can_write_email` false), prints a re-consent-help note and a `SKIPPED` check that does NOT flip `r.failed` (exit stays 0 for read-only tokens); (b) else sends a message to the connected account's own address, polls for arrival, trashes it, and verifies it is gone. The module stays import-inert (no top-level network calls); `main()` is unchanged in its non-write behavior.

- [ ] **Step 1: Read the current end of `main()` to anchor the insertion point**

Read `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_google.py` (already done above — the exact current tail of the `try` block, immediately before the bare `except Exception as exc:` line, is):

```python
        triaged = inbox["needs_reply"] + inbox["fyi"]
        if settings.anthropic_api_key:
            r.check(bool(triaged),
                    "at least one message was triaged (category + summary present)")
            for e in triaged[:3]:
                print(f"        - [{e['category']}] {e['subject']!r} :: "
                      + " | ".join(e["summary"][:3]))
    except Exception as exc:  # a live call blew up -- report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])
```

This is a manual live-credential script, not a pytest — it is never imported by the suite and must not reach the network on import (all live calls stay inside `main()`). The only automated guardrails are the import-inertness check (Step 2) and the full suite staying green (Step 3).

- [ ] **Step 2: Add imports + the write-leg section 6, then verify import-inertness**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_google.py`. First, extend the imports at the top of the file. Replace the current:

```python
from __future__ import annotations

import logging
import secrets
import sys

from . import email_sync, providers
from .config import settings
from .store import store
```

with:

```python
from __future__ import annotations

import logging
import secrets
import sys
import time
from datetime import datetime, timezone

from . import email_sync, providers
from .config import settings
from .providers.google import GMAIL_API_BASE, _build_rfc822
from .store import store
```

Now replace the exact current tail block (same anchor as Step 1) with the same code plus the new section 6 inserted before the `except`:

```python
        triaged = inbox["needs_reply"] + inbox["fyi"]
        if settings.anthropic_api_key:
            r.check(bool(triaged),
                    "at least one message was triaged (category + summary present)")
            for e in triaged[:3]:
                print(f"        - [{e['category']}] {e['subject']!r} :: "
                      + " | ".join(e["summary"][:3]))

        print("\n6. Write path (send-to-self -> verify -> trash):")
        account = store.get_provider_account("google")
        if not account or not account.get("can_write_email"):
            r.check(True, "SKIPPED -- account lacks gmail.modify/gmail.send scopes",
                    "re-consent to grant email actions: connect Google again and tick "
                    "BOTH the Gmail modify and send checkboxes on the consent screen")
        else:
            # [confirm-against-live]: GET {GMAIL_API_BASE}/profile -> {"emailAddress": ...}
            profile = provider._get(f"{GMAIL_API_BASE}/profile")
            self_addr = profile.get("emailAddress", "")
            r.check(bool(self_addr), "resolved the connected account's own address",
                    self_addr or "<empty>")

            subject = f"ScuffedOS smoke {datetime.now(timezone.utc).isoformat()}"
            raw = _build_rfc822(to=self_addr, subject=subject,
                                 body="Automated write-leg smoke test -- safe to ignore.")
            sent_id = provider.send_message(raw)
            r.check(bool(sent_id), "send_message returned a new message id", sent_id)

            print("        polling for arrival (up to ~30s)...")
            found_id = None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not found_id:
                hits = provider._get(
                    f"{GMAIL_API_BASE}/messages",
                    # Gmail search phrases use double quotes, not Python repr()'s
                    # single quotes -- [confirm-against-live] the exact query
                    # syntax against the real Gmail search API in Task 19/20.
                    params={"q": f'subject:"{subject}"'},
                )
                ids = [m["id"] for m in hits.get("messages", [])]
                if sent_id in ids:
                    found_id = sent_id
                else:
                    time.sleep(3)
            r.check(found_id is not None,
                    "sent message appeared in messages.list by subject", subject)

            provider.trash_message(sent_id)
            r.check(True, "trash_message call completed", sent_id)

            time.sleep(2)
            after = provider._get(
                f"{GMAIL_API_BASE}/messages", params={"q": f'subject:"{subject}"'}
            )
            after_ids = [m["id"] for m in after.get("messages", [])]
            r.check(sent_id not in after_ids,
                    "trashed message no longer returned by messages.list", subject)
    except Exception as exc:  # a live call blew up -- report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])
```

Note: `provider._get(url, params=None) -> dict` is `GoogleProvider`'s existing authed-GET helper (already defined in `app/providers/google.py`, used internally by `fetch_messages`/`get_message`). Calling it on the same `provider` object that sections 1–5 above already hold (from `providers.get("google")` + `provider.set_tokens(tokens)` earlier in `main()`) keeps this script's only new Gmail-specific knowledge to endpoint paths already exposed via `GMAIL_API_BASE`, exactly matching how `send_message`/`trash_message` build their own URLs in `google.py`.

**Run** (byte-compile / import-inertness — proves no top-level network/side effects; does NOT execute `main()`):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -c "import app.smoke_google as s; print('imports ok', callable(s.main))"
```

**Expected:** `imports ok True` with no network calls and no exception (every live call lives inside `main()`, which is not invoked by the import).

- [ ] **Step 3: Run the full backend suite to confirm the module stays inert and unaffects collection, then commit**

**Run:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
```

**Expected:** the suite is green and the pass count is unchanged from the previous task (the new write-leg code in `smoke_google.py` is not collected — its filename is not `test_*` and it imports no test fixtures). Report the count as "X tests passing".

**Commit:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/smoke_google.py
git commit -m "$(cat <<'EOF'
test(smoke): add write leg to the live Gmail smoke test (send/verify/trash)

Section 6 sends a message to the connected account's own address, polls
messages.list for arrival by subject, trashes it, and verifies a follow-up
list no longer returns it. Guards on can_write_email first: read-only tokens
print re-consent help and SKIP the section without failing (exit stays 0).
No import-time side effects -- all live calls remain inside main().

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Expected:** commit succeeds.

---

### Task 20: Live validation + final gate (manual — no code changes)

**Files:**
- None (verification gate only; no files created or modified in this task).

**Interfaces:**
- Consumes: The entire M5 slice-2 merged onto `m5-email-slice2`: `GOOGLE_SCOPES` with `gmail.modify`+`gmail.send` (Task 1), `can_write_email` surfaced via `GET /api/oauth/status` (Task 1), all provider write methods (Tasks 2–4), migration `0006` (Task 5), all write API endpoints (Tasks 8–11), `email_draft` + `POST /api/email/draft` + the `draft_email` assistant tool (Tasks 12–14), the EmailScreen write-gate banner + action bar + sort + compose overlay + AI-draft button (Tasks 15–17), the updated privacy policy (Task 18), and `smoke_google.py`'s write leg (Task 19).
- Produces: A recorded end-to-end live validation of the write path: consent-screen scope upgrade, re-consent with both new checkboxes ticked, `can_write_email: true` confirmed via the API, every write surface browser-verified against real Gmail, `python -m app.smoke_google` reporting `RESULT: ALL PASSED` including the write leg, and the full backend suite + frontend build reported green. This is a manual verification gate — no code changes beyond none.

- [ ] **Step 1: Google Cloud console — add the write scopes to the OAuth consent screen**

Manual browser step (no automated assertion — the gate is the re-consent succeeding in Step 3). In the same GCP project used for slice-1 (Testing mode; your test user is already listed — do not re-add it, slice-1's memory notes an already-listed address can trigger a confusing "not eligible" error if you try):

1. Go to `console.cloud.google.com` → **APIs & Services → OAuth consent screen → Edit app → Scopes**.
2. Click **Add or remove scopes** and add, alongside the existing `openid`/`email`/`profile`/`gmail.readonly`:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.send`
3. Save. Confirm the app stays in **Testing** mode (no Google verification review needed for restricted scopes with a single test user).

**Expected:** the consent screen's scope list now shows five scopes (openid, email, profile, gmail.readonly, gmail.modify, gmail.send). No automated check — visual confirmation in the console.

- [ ] **Step 2: Migrate the local docker Postgres to 0006, then restart the backend against it**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
DATABASE_URL=postgresql://scuffed:scuffed@localhost:5433/scuffedos /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m alembic upgrade head
```

**Expected:** alembic reports the upgrade `0005 -> 0006` applied cleanly (the local docker PG is already migrated through 0005 per prior M5 live validation). Then start the backend against that same database on port 8000 (the port the registered redirect URI expects):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
DATABASE_URL=postgresql://scuffed:scuffed@localhost:5433/scuffedos uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Expected:** server starts with no startup errors; the existing Google `provider_accounts` row from the slice-1 live validation is still present (its scopes are the old read-only set until Step 3 re-consents).

- [ ] **Step 3: Trigger the "Enable email actions" banner, re-consent ticking ALL Gmail checkboxes**

In the browser, open the app (EmailScreen). Because the stored token's scopes lack `gmail.modify`/`gmail.send`, the write-gate banner from contract §A ("Enable email actions") should appear. Click **Enable** — this calls `api.oauthConnect('google')`, which re-runs the OAuth authorize flow.

**Expected + known gotcha (from slice-1's live validation memory):** Google's consent screen presents `gmail.readonly`, `gmail.modify`, and `gmail.send` as **unchecked checkboxes** since they are restricted scopes. **You must manually tick every Gmail checkbox** (both the read/modify box and the send box now appear, alongside the existing one) — an unticked box grants a scope-less token and the app will stay in the pre-write state. Approve consent.

- [ ] **Step 4: Verify `can_write_email: true` via `/api/oauth/status`**

```bash
curl -s http://localhost:8000/api/oauth/status | python3 -m json.tool
```

**Expected:** the `google` entry in `providers` has `"status": "connected"` and `"can_write_email": true` (contract §A's derived field, driven by `_can_write_email` checking both `gmail.modify` and `gmail.send` are present in the stored scopes). If `can_write_email` is `false`, the re-consent in Step 3 did not grant both write scopes — repeat Step 3, ticking every box.

- [ ] **Step 5: Browser-verify every write surface against real Gmail**

Drive the live EmailScreen and cross-check each action lands in the real Gmail web UI (open Gmail in a separate tab, same account):

1. **Action bar round-trip:** open a message, click **Star** — confirm the star indicator updates in ScuffedOS AND the message shows starred in Gmail web. Toggle **Read/Unread** — confirm the unread dot and Gmail's bold/unbold state agree.
2. **Label menu:** open the label menu (populated from `GET /api/email/labels`), apply a label, confirm it appears on the message in Gmail web; remove it, confirm it's gone.
3. **Trash:** click **Trash** on a message — confirm it disappears from the ScuffedOS inbox list AND lands in Gmail's Trash folder (not permanently deleted — contract's frozen "deletion = Trash" decision).
4. **Compose + AI draft:** open compose (New), click the ✨ AI-draft button, type instructions, confirm the draft inserts into the editor; edit it; click **Send** — confirm it arrives in the recipient's mailbox (or your own second address) and appears in your Gmail **Sent** folder.
5. **Reply threading:** open a message, click **Reply**, confirm the quoted original + `Re:` subject prefill, send it, and confirm in Gmail web that the reply threads into the same conversation as the original (not a new thread).

**Expected:** every action above succeeds with no error banner, and the corresponding state is visible in Gmail's own web UI within a few seconds. No automated assertion — this is a human-observed browser pass.

- [ ] **Step 6: Run `python -m app.smoke_google` for a consolidated pass, including the write leg**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
DATABASE_URL=postgresql://scuffed:scuffed@localhost:5433/scuffedos /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m app.smoke_google; echo "exit=$?"
```

**Expected:** `exit=0` with `RESULT: ALL PASSED` printed, and section "6. Write path" shows `[PASS]` (not `SKIPPED`) for every check — since `can_write_email` is now true from Step 4, the send/verify/trash leg runs for real rather than skipping.

- [ ] **Step 7: Full backend suite green + frontend build green, then report counts**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q
```

**Expected:** all tests pass (0 failures, 0 errors). Report the exact count as "X tests passing" — confirm it is at least the Global Constraints baseline of 346 passed / 1 skipped, plus every new slice-2 test from Tasks 1–19 (provider write methods, migration 0006 + model + `NormalizedEmail`, store write methods, all new `/api/email/*` write endpoints, `email_draft`, the `draft_email` tool registration test asserting `send_email`/`trash_email`/`label_email` are absent, and the RFC-822 builder unit tests).

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend
npm run build
```

**Expected:** build completes with no errors (Vite production build succeeds; report any warnings but they must not be new errors).

If anything is red at Step 6 or Step 7, the slice is NOT complete — fix before considering the work done. No git commit for this task (Step 1–6 are manual/live actions and Step 7 is a verification gate); once green, the branch `m5-email-slice2` is ready to open a PR.
