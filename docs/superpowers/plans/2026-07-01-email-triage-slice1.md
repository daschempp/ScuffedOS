# M5 Email Slice-1 (Google OAuth + Gmail + triage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M5 email slice-1: connect a Google account through a REFACTORED shared OAuth layer, sync the Gmail INBOX read-only, LLM-triage each message (category + summary bullets) on sync and cache it on the row, and render the live read-only two-pane inbox + read-only assistant tools. The OAuth refactor generalizes M4's WHOOP substrate WITHOUT regressing the fitness path.

**Architecture:** FastAPI + SQLAlchemy(+Alembic) backend behind a Store facade (dict in / dict out, derive-on-read, _*_dict builders); provider registry with a configure(fake) test seam; a shared Anthropic client seam (llm.py); a background sync tick mirrored from fitness_sync; Vite/React SPA. THE REFACTOR: split providers/base.py's FitnessProvider Protocol into OAuthProvider (base) + FitnessProvider(OAuthProvider) + EmailProvider(OAuthProvider), each provider gaining success_redirect()/on_connected()/on_disconnect() hooks; extract the CSRF _STATES store + connect/callback/disconnect/status endpoints out of routers/fitness.py into a provider-agnostic routers/oauth.py (fitness DATA endpoints stay). Then ADD GoogleProvider (OAuth + Gmail read-only via httpx, no google SDK), an emails table (migration 0005, no body column), email_triage.py (Haiku, configure(fake) seam), email_sync.py (tick/trigger/run_loop mirroring fitness_sync), routers/email.py, read-only assistant tools, and an EmailScreen rewrite.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (JSON().with_variant(JSONB)), Alembic (0005 chains onto 0004), Pydantic v2 / pydantic-settings, httpx (hand-rolled OAuth + Gmail REST — NO google-api-python-client / google-auth), Anthropic SDK (Haiku tier for triage via llm.py), pytest + FastAPI TestClient over in-memory SQLite (TEST_DATABASE_URL swaps to Postgres). Frontend: React + Vite, frontend/src/lib/api.js client, frontend/src/screens/EmailScreen.jsx.

## Global Constraints

## Project-wide rules (verbatim; every phase author obeys these)

- **The full test suite must stay green — INCLUDING the entire M4 fitness suite.** The M4 OAuth suite is the refactor's guardrail: `backend/tests/test_fitness_oauth.py` MOVES to test the shared oauth router (repoint its URLs from `/api/fitness/*` to `/api/oauth/*` and `fitness._STATES` → `oauth._STATES`), and every fitness DATA test (`/today`, `/week`, `/workouts`, `/sync`, manual workouts) must keep passing untouched. Run `cd backend && python -m pytest` and report the pass count; the suite must be green before work is considered complete.
- **The WHOOP live path must not regress.** `WhoopProvider` keeps working end-to-end (OAuth + fetch_recovery/sleep/workouts); it only GAINS the three OAuthProvider hooks (`success_redirect`, `on_connected`, `on_disconnect`). `python -m app.smoke_whoop` behavior is unchanged.
- **No new runtime dependencies beyond what's already imported.** Google OAuth + Gmail are implemented over `httpx` (already the WHOOP transport) — NO `google-api-python-client`, `google-auth`, or `google-auth-oauthlib`. Mirror WhoopProvider's `_transport()` / `configure(fake_http=...)` seam exactly.
- **Email message BODIES are never persisted (privacy rule).** The `emails` table has NO `body` column. The list/inbox is always served from the `emails` table (never a live Gmail call). Only the reading pane fetches the body live via `EmailProvider.get_message(source_id)`, with a graceful fallback string if Gmail is unreachable.
- **Message content transits to Anthropic for triage but is not stored.** Triage input (subject + sender + snippet + a bounded ~2 KB body excerpt) is sent to the Claude Haiku tier via `app/llm.py`; only the derived `category` + `summary_json` land on the row. Bodies transit Gmail → server → Anthropic and are dropped.
- **Provider-agnostic `source` / `source_id`, `owner` defaults to `settings.owner` ("me").** `emails` keys on `(owner, source, source_id)` = `('google', <gmail message id>)`, matching M4's `daily_snapshots` / `workouts` conventions. `provider_accounts` is UNCHANGED and already provider-agnostic — Google tokens land there via the existing `store.upsert_provider_account`.
- **`configure(fake)` seams, no network in tests.** New seams to add mirroring the existing ones: `GoogleProvider` gets a `configure(fake_http=...)` http seam (like WhoopProvider); `email_triage` gets a module-level `configure(fake)` seam (like `llm` / `food_db`); `email_sync` gets a `configure(override)` tick seam (like `fitness_sync`). `conftest.py`'s `no_external_services` fixture must install/restore these fakes so no test reaches Google or Anthropic. `providers.configure([...])` continues to swap the whole registry (now holding WhoopProvider + GoogleProvider).
- **Store facade style:** routers/sync/tools call plain `store.*` methods that take and return API-shaped dicts; ORM/session detail stays inside `store.py`; new rows use `_email_dict(...)` builders and derive display fields on read; timestamps stored aware-UTC via `_to_utc`, read back via `aware_utc`.
- **Python/test conventions (from user CLAUDE.md):** run the full suite after changes and report "X tests passing"; in Bash avoid `&&` chains for steps that may return non-zero (use `;` or separate commands); for any PDF spec use `pdftotext`/Python, not the Read tool.
- **`[confirm-against-live]` Google/Gmail items are FROZEN by their normalized names for this contract.** The exact Google/Gmail endpoint URLs, request params (`access_type`, `prompt`), scope strings, the `sub`/id_token/userinfo field for `provider_user_id`, Gmail `messages.list` `q`/label filter + pagination, and `messages.get` header/snippet/base64url-body decoding are confirmed against the live API DURING implementation (spec §13) — but their SIGNATURES and the placeholder constant names below do NOT change. Downstream phases code against the frozen names.
- **Branch:** all M5 work lands on `m5-email-triage` (chains onto the merged M4 code on `main`).
- **Deferred to later slices — DO NOT build:** draft generation / tone variants, the send path, archive, cross-domain actions (email→task/calendar/people). EmailScreen omits the draft-tone tabs + Send/Edit/Regenerate buttons (no dead UI). No write/send assistant tools this slice.

## Interface Contract

## M5 Email Slice-1 — Interface Contract (single source of truth)

File paths are absolute under `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/` (backend) or `/frontend/` (frontend). Signatures below are frozen; where a name is marked `[confirm-against-live]` only the *value behind the constant* is confirmed during impl — the constant name and the method signature are frozen.

---
### A. Provider protocol split — `app/providers/base.py`

Split the single `FitnessProvider` Protocol into a base + two domain protocols. `AuthError`, `Tokens`, `NormalizedSnapshot`, `NormalizedWorkout` are UNCHANGED. Add `NormalizedEmail` and the base protocol.

```python
@runtime_checkable
class OAuthProvider(Protocol):
    name: str                              # 'whoop' | 'google'
    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def revoke(self, tokens: Tokens) -> None: ...
    def set_tokens(self, tokens: Tokens | None) -> None: ...
    # Screen to land on after a successful connect:
    #   whoop  -> "/?screen=fitness&connected=whoop"
    #   google -> "/?screen=email&connected=google"
    def success_redirect(self) -> str: ...
    # Post-connect hook (called by the shared callback AFTER tokens persist):
    #   whoop  -> fitness_sync.tick()   google -> email_sync.tick()
    def on_connected(self) -> None: ...
    # Disconnect hook (called by the shared disconnect AFTER best-effort revoke):
    #   whoop  -> delete daily_snapshots/workouts where source='whoop' (preserve manual)
    #   google -> delete emails where source='google'
    def on_disconnect(self) -> None: ...

@runtime_checkable
class FitnessProvider(OAuthProvider, Protocol):
    kind: Literal["pull", "push"]
    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...

@runtime_checkable
class EmailProvider(OAuthProvider, Protocol):
    def fetch_messages(self, since: datetime | None) -> list["NormalizedEmail"]: ...
    def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
```

`NormalizedEmail` dataclass (fields frozen; NO body stored anywhere durable — body is fetched via `get_message`; the ~2 KB excerpt lives only on `body_excerpt` for triage transit and is NOT persisted):

```python
@dataclass
class NormalizedEmail:
    source: str                            # 'google'
    source_id: str                         # gmail message id
    thread_id: str
    from_name: str
    from_email: str
    subject: str
    snippet: str                           # gmail preview
    received_at: datetime                  # aware UTC, sort key
    unread: bool = False
    body_excerpt: str = ""                 # bounded ~2 KB plain-text, triage-only, NOT persisted
```

NOTE: `set_tokens`, `success_redirect`, `on_connected`, `on_disconnect` are NEW on the protocol; `WhoopProvider` already has `set_tokens` and must GAIN the other three (see §C). The shared router calls the hooks via `getattr(impl, "on_connected", None)`-style guards is NOT required — every registered provider implements them; but keep `fetch_profile` access via `getattr` as the callback does today.

---
### B. Provider registry — `app/providers/__init__.py`

Keep the `configure(override)` seam and the four functions. Changes:
- Type the registry as `list[OAuthProvider]` (was `FitnessProvider`).
- `_build_real()` builds `[WhoopProvider(), GoogleProvider()]` (import GoogleProvider lazily like WhoopProvider; tolerate ImportError mid-plan → skip it).
- `all_providers() -> list[OAuthProvider]`, `get(name) -> OAuthProvider | None` UNCHANGED in signature.
- `pull_providers() -> list[FitnessProvider]` STAYS (filters `getattr(p, "kind", None) == "pull"`) — GoogleProvider has no `kind`, so it is naturally excluded from the fitness sync.

---
### C. `WhoopProvider` — `app/providers/whoop.py` (gains 3 hooks, else unchanged)

Add exactly these three methods; everything else (OAuth, fetch_*, fetch_profile, `_transport`, `configure`) is untouched:

```python
class WhoopProvider:
    name = "whoop"; kind = "pull"
    def success_redirect(self) -> str:
        return "/?screen=fitness&connected=whoop"
    def on_connected(self) -> None:
        from .. import fitness_sync
        fitness_sync.tick()
    def on_disconnect(self) -> None:
        from ..store import store
        store.delete_provider_data(self.name)   # deletes snapshots/workouts where source='whoop'
```

`delete_provider_data(provider)` already deletes the `provider_accounts` row + `daily_snapshots`/`workouts` where `source == provider` (manual preserved). For `on_disconnect` the account-row deletion is idempotent with the router's own delete path — see §I for how the shared router orchestrates revoke → delete-account → on_disconnect so behavior matches M4 exactly (the M4 disconnect test asserts `delete_provider_data` semantics and must stay green).

---
### D. Google OAuth + Gmail — `app/providers/google.py` (NEW; `GoogleProvider` implements `EmailProvider`)

Hand-rolled over httpx, mirroring `whoop.py`. Frozen constants (`[confirm-against-live]` = value confirmed at impl, NAME frozen):

```python
GOOGLE_AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"        # [confirm-against-live]
GOOGLE_TOKEN_URL  = "https://oauth2.googleapis.com/token"                 # [confirm-against-live]
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"               # [confirm-against-live]
GMAIL_API_BASE    = "https://gmail.googleapis.com/gmail/v1/users/me"      # [confirm-against-live]
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"  # [confirm-against-live] (sub for provider_user_id)
GOOGLE_SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.readonly"  # [confirm-against-live]
_REFRESH_SKEW = timedelta(seconds=60)

class GoogleAuthError(AuthError): ...   # subclass, like WhoopAuthError → sync flips needs_reauth
```

`authorize_url(state)` MUST include `access_type=offline` + `prompt=consent` (guarantees a refresh token) plus `client_id=settings.google_client_id`, `redirect_uri=settings.google_redirect_uri`, `response_type=code`, `scope=GOOGLE_SCOPES`, `state`.

Frozen methods (signatures identical to the protocol):
```python
class GoogleProvider:
    name = "google"
    def __init__(self) -> None: self._http = "unset"; self._client = None; self._tokens = None
    def configure(self, fake_http="unset") -> None: ...     # http seam, mirrors WhoopProvider
    def set_tokens(self, tokens: Tokens | None) -> None: ...
    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...       # includes client_secret, redirect_uri
    def refresh(self, tokens: Tokens) -> Tokens: ...        # keeps old refresh_token if Google omits one
    def revoke(self, tokens: Tokens) -> None: ...           # best-effort, POST token=..., never raises
    def fetch_profile(self, tokens: Tokens) -> str | None:  # returns Google 'sub' for provider_user_id; best-effort None
    def success_redirect(self) -> str: return "/?screen=email&connected=google"
    def on_connected(self) -> None:                         # from .. import email_sync; email_sync.tick()
    def on_disconnect(self) -> None:                        # store.delete_email_data('google')
    def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
    def get_message(self, source_id: str) -> str: ...
```

- `fetch_messages`: `GET {GMAIL_API_BASE}/messages?labelIds=INBOX&maxResults={settings.email_backfill_count}` (`q`/pagination `[confirm-against-live]`), then per id `GET {GMAIL_API_BASE}/messages/{id}?format=full` (or metadata+snippet) → map to `NormalizedEmail` (parse From into from_name/from_email; Date → aware-UTC `received_at`; `UNREAD` label → `unread`; decode base64url plain-text part, truncate to ~2 KB into `body_excerpt`). Auth failures raise `GoogleAuthError`. `[confirm-against-live]` on exact JSON paths.
- `get_message(source_id)`: `GET .../messages/{source_id}?format=full` → decoded full plain-text body string. Raises on transport error (router/store catches and substitutes the fallback string).

---
### E. `emails` table — `app/models.py` + migration `0005_email.py`

SQLAlchemy model (mirrors `Workout`/`DailySnapshot` style; NO `body` column):

```python
class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id", name="uq_emails_owner_source_source_id"),
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
    category: Mapped[str | None] = mapped_column(String(16))            # 'needs_reply' | 'fyi' | None (untriaged)
    summary_json: Mapped[list | None] = mapped_column(JSONField)        # list[str] bullets, or None
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

Migration file `alembic/versions/0005_email.py`: `revision = "0005"`, `down_revision = "0004"`, `branch_labels = None`, `depends_on = None`. `upgrade()` `op.create_table("emails", ...)` with the columns above + `op.create_index` on `owner`, `source`, `source_id`, `received_at` + the `UniqueConstraint("owner","source","source_id", name="uq_emails_owner_source_source_id")`; `JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")`. `downgrade()` `op.drop_table("emails")`. (No new registration step — `Email(Base)` auto-registers via the `Base.metadata` import chain used by conftest.)

---
### F. Store methods — `app/store.py` (all take/return dicts; add `Email` to the models import + register `_EMAIL_FIELDS`)

`_email_dict(e: Email) -> dict` builder (derive-on-read, mirrors `_workout_dict`):
```python
{"id","source","source_id","thread_id","from_name","from_email","subject","snippet",
 "received_at": aware_utc(e.received_at), "unread", "category",
 "summary": e.summary_json or [], "triaged_at": aware_utc(e.triaged_at),
 "when": <derived relative/clock display>,   # e.g. "8:24am" / "Yesterday" / "Jun 5"
 "created_at": aware_utc(e.created_at), "updated_at": aware_utc(e.updated_at)}
```

Frozen store method signatures:
```python
def upsert_email(self, email: NormalizedEmail, category: str | None, summary: list[str] | None) -> dict
    # get-or-create by (owner, source, source_id); writes metadata every pass;
    # sets category/summary_json/triaged_at only when category is not None (a triage
    # failure passes category=None → leaves the row untriaged for retry). @_retry_integrity.
def email_exists(self, source: str, source_id: str) -> bool
    # sync uses this to skip messages.get + triage for already-stored ids (idempotency).
def inbox(self) -> dict
    # {"needs_reply": [<_email_dict>...], "fyi": [<_email_dict>...],
    #  "untriaged": [<_email_dict>...], "needs_reply_count": <int>, "unread_count": <int>}
    # each list sorted received_at desc.
def get_email(self, email_id: int) -> dict | None                # _email_dict, or None
def delete_email_data(self, source: str) -> bool
    # disconnect hook: delete emails where (owner, source); returns True iff any deleted.
    # NOTE: separate from delete_provider_data (which handles the provider_accounts row +
    # fitness tables). The shared router deletes the account row; on_disconnect calls THIS.
```

`_EMAIL_FIELDS` set mirrors the model's writable columns. `list_provider_accounts()`, `get_provider_tokens()`, `upsert_provider_account()`, `set_provider_status()`, `set_provider_synced()`, `delete_provider_data()` are UNCHANGED and reused verbatim for Google.

---
### G. Config additions — `app/config.py` (append to `Settings`)

```python
google_client_id: str = ""
google_client_secret: str = ""
google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
email_sync_enabled: bool = True
email_sync_seconds: int = 900          # 15 min
email_backfill_count: int = 50
```
Triage reuses the existing `assistant_model` (Haiku tier) — no new model setting.

---
### H. Triage — `app/email_triage.py` (NEW)

```python
_override = "unset"   # tests install a fake (or None to disable); mirrors llm.py
def configure(override="unset") -> None: ...
def triage(subject: str, from_name: str, from_email: str, snippet: str, body_excerpt: str
          ) -> tuple[str | None, list[str] | None]:
    # Returns (category, summary): category in {"needs_reply","fyi"} (or None on failure),
    # summary = list of <=3 short bullet strings (or None on failure).
    # Uses app/llm.py Claude client at settings.assistant_model (Haiku). Validates the
    # model output (category clamped to the two-value enum; summary truncated to 3 bullets).
    # A failure / offline LLM returns (None, None) — the caller leaves the row untriaged
    # (message still shows) and retries next sync. Never raises.
```
The fake seam: `configure(fake)` where `fake.triage(...)` returns the tuple, OR `configure(None)` → always `(None, None)`. `email_sync` calls `email_triage.triage(...)`.

---
### I. Shared OAuth router — `app/routers/oauth.py` (NEW; extracted from `routers/fitness.py`)

Two routers exported (matching the fitness module's two-router pattern so `main.py` includes both):
```python
router = APIRouter(prefix="/api/oauth", tags=["oauth"])
auth_router = APIRouter(tags=["oauth"])           # NO prefix → /auth/{provider}/callback
_STATES: dict[str, str] = {}                       # moved from fitness._STATES (tests reference oauth._STATES now)
def _issue_state(provider: str) -> str: ...
def _consume_state(state: str) -> str | None: ...
```

Endpoints (provider-registry-driven, domain-agnostic):
```
GET  /api/oauth/connect/{provider}   -> response_model=ConnectUrl  -> {"authorize_url": impl.authorize_url(state)}; 404 unknown provider
GET  /api/oauth/status               -> response_model=OAuthStatus -> {"connected": bool, "providers": [ProviderStatus...]}
GET  /auth/{provider}/callback       (auth_router; code, state Query(...))
       verify one-time CSRF state (400 on mismatch/expired) -> impl.exchange_code(code)
       -> best-effort fetch_profile stamp (getattr, as today) -> store.upsert_provider_account(provider, tokens)
       -> impl.on_connected()  -> RedirectResponse(impl.success_redirect(), status_code=302)
POST /api/oauth/disconnect/{provider} -> response_model=OAuthStatus
       impl = providers.get(provider); tokens = store.get_provider_tokens(provider)
       best-effort impl.revoke(tokens) (swallow errors) ->
       existed = store.delete_provider_account(provider)  (see NOTE) ; if not existed -> 404
       impl.on_disconnect()  (deletes that provider's domain data) -> return status dict
```
NOTE on disconnect orchestration (must keep the M4 test green — it asserts revoke ran, account gone, data gone even when revoke fails): to preserve EXACT M4 behavior with the least churn, the recommended shape is: the shared router calls `store.delete_provider_data(provider)` (unchanged — removes the account row + fitness tables) and THEN `impl.on_disconnect()`. For WHOOP `on_disconnect` re-calling `delete_provider_data` is idempotent (row already gone, no-op). For Google, `delete_provider_data` removes the account row + (no fitness rows) and `on_disconnect` → `store.delete_email_data('google')` removes the emails. The `existed` return of `delete_provider_data` drives the 404. Phase author MAY instead split into `delete_provider_account(provider) -> bool` + per-provider `on_disconnect`; EITHER is acceptable AS LONG AS `test_fitness_oauth.py` (moved to `test_oauth.py`) passes unchanged in assertions. Freeze: the callback calls `on_connected()` (NOT a hardcoded `fitness_sync.tick()`); the redirect uses `impl.success_redirect()`.

`routers/fitness.py` after extraction keeps ONLY: `/today`, `/week`, `/workouts` (GET), `/workouts` (POST create), `/workouts/{id}` (DELETE), `/sync` (POST). It DROPS `connect/{provider}`, `status`, `disconnect/{provider}`, the callback, `_STATES`, and the `_FITNESS_REDIRECT` constant. Its remaining data endpoints and their schemas (`FitnessToday`, `FitnessWeek`, `WorkoutOut`, `WorkoutCreate`) are unchanged.

`main.py`: `from .routers import ... email, oauth`; add `app.include_router(oauth.router)`, `app.include_router(oauth.auth_router)`, `app.include_router(email.router)`; REMOVE `app.include_router(fitness.auth_router)` (the callback now lives on `oauth.auth_router`); keep `app.include_router(fitness.router)`. Lifespan gains: `if settings.email_sync_enabled: email_task = asyncio.create_task(email_sync.run_loop())` and cancels it in the shutdown loop alongside reminder/fitness tasks.

---
### J. Email sync — `app/email_sync.py` (NEW; mirrors `fitness_sync.py`)

```python
_override = "unset"
def configure(override="unset") -> None: ...        # test seam: fake with .tick(); None/"unset" = real
def tick(now: datetime | None = None) -> int:
    # One pass over every connected EmailProvider (providers.all_providers() filtered to
    # those implementing fetch_messages, i.e. exclude pull-fitness). Per account:
    #   load+refresh+inject tokens (reuse the _load_and_inject_tokens pattern; persist rotation),
    #   provider.fetch_messages(since=last_sync_at) -> for each NOT store.email_exists(...):
    #     triage(subject, from_name, from_email, snippet, body_excerpt) -> store.upsert_email(...),
    #   store.set_provider_synced(provider.name, now). Returns count upserted.
    # Per-account errors isolated + logged; tick never crashes; AuthError ->
    # store.set_provider_status(name, "needs_reauth"). RuntimeError(no DATABASE_URL) -> 0.
async def trigger() -> int:  return await asyncio.to_thread(tick)
async def run_loop() -> None:
    # gated by lifespan (settings.email_sync_enabled); sleeps settings.email_sync_seconds
```
Selecting email providers in the tick: iterate `providers.all_providers()` and keep those with a `fetch_messages` attribute (GoogleProvider); do NOT reuse `pull_providers()` (that's fitness-only). `on_connected` calls `email_sync.tick()` directly (immediate first-sync backfill; `since=None` on a fresh account → backfill via `messages.list maxResults=email_backfill_count`).

---
### K. Email API — `app/routers/email.py` (NEW) + schemas — `app/schemas.py`

Router:
```python
router = APIRouter(prefix="/api/email", tags=["email"])
GET  /api/email/inbox      -> response_model=Inbox        -> store.inbox()
GET  /api/email/{id}       -> response_model=EmailDetail  -> metadata + summary + on-demand body
       (store.get_email(id); 404 if None; body via providers.get('google').get_message(source_id),
        wrapped in try/except → fallback string "Message body is unavailable right now." on failure)
POST /api/email/sync       -> {"synced": <int>, "providers": [<name>...]}  -> email_sync.tick()
```
Connect/disconnect/status are NOT here — they live on `/api/oauth/*`.

Pydantic schemas (add to `schemas.py`, mirroring the fitness block):
```python
EmailCategory = Literal["needs_reply", "fyi"]

class EmailOut(BaseModel):            # list item — NO body
    id: int
    source: str
    from_name: str
    from_email: str
    subject: str
    snippet: str
    received_at: datetime
    unread: bool
    category: EmailCategory | None
    summary: List[str]                # [] when untriaged
    when: str                         # derived display

class EmailDetail(EmailOut):          # detail — adds live body
    thread_id: str
    body: str                         # on-demand Gmail fetch (or fallback string)

class Inbox(BaseModel):
    needs_reply: List[EmailOut]
    fyi: List[EmailOut]
    untriaged: List[EmailOut]
    needs_reply_count: int
    unread_count: int
```
Also extend the assistant `Screen` Literal — it ALREADY includes `"email"`, no change needed. Add `OAuthStatus` (generic, replaces the fitness-specific status shape at `/api/oauth/status`); reuse the existing `ProviderStatus` and `ConnectUrl` schemas verbatim:
```python
class OAuthStatus(BaseModel):
    connected: bool
    providers: List[ProviderStatus]
```
`FitnessStatus` STAYS in `schemas.py` (still used by any remaining fitness-status reference / the assistant `get_fitness_status` tool shape) but is no longer returned by an HTTP endpoint; `OAuthStatus` is structurally identical so the moved M4 status test passes.

---
### L. Assistant tools — `app/tools.py` (read-only this slice)

Add two READ-only tools (executors return `(result, None)` — no action card, like the fitness readers; errors return `{"error": ...}`):
```python
def _email_action(title, meta) -> dict:  # {"icon":"mail","title":...,"meta":...,"cta":"Open email","screen":"email"}
def _get_inbox(args: dict):    # store.inbox() -> compact {"needs_reply":[...], "fyi":[...], "needs_reply_count":N}
def _get_email(args: dict):    # args: {"email_id": int}; store.get_email + live get_message body; {"error":...} if missing
```
TOOLS entries (names FROZEN):
```
{"name":"get_inbox", "description":"Read the triaged inbox — what needs a reply and FYI items, with AI summaries. Call when the user asks about their email/inbox or what needs a response.",
 "input_schema":{"type":"object","properties":{},"additionalProperties":False}, "run":_get_inbox}
{"name":"get_email", "description":"Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
 "input_schema":{"type":"object","properties":{"email_id":{"type":"integer"}},"required":["email_id"],"additionalProperties":False}, "run":_get_email}
```
NO write/send/draft/archive tools this slice.

---
### M. Frontend

`frontend/src/lib/api.js` — REPOINT the fitness connect/status/disconnect helpers to the shared oauth routes AND add email helpers:
```js
// oauth (shared) — fitness screen repoints connect/status/disconnect here:
oauthStatus: () => request('/api/oauth/status'),
oauthConnect: (provider) => request(`/api/oauth/connect/${provider}`),
oauthDisconnect: (provider) => request(`/api/oauth/disconnect/${provider}`, { method: 'POST' }),
// email:
emailInbox: () => request('/api/email/inbox'),
emailDetail: (id) => request(`/api/email/${id}`),
emailSync: () => request('/api/email/sync', { method: 'POST' }),
```
`FitnessScreen.jsx` repoints `api.fitnessStatus/fitnessConnect/fitnessDisconnect` → `api.oauthStatus/oauthConnect('whoop')/oauthDisconnect('whoop')` (the fitness DATA calls `fitnessToday/fitnessWeek/fitnessWorkouts/fitnessSync/logWorkout/deleteWorkout` stay on `/api/fitness/*`). The old `fitnessStatus/fitnessConnect/fitnessDisconnect` helpers may be kept as thin aliases OR removed with the call sites updated — either way no `/api/fitness/connect|status|disconnect` route exists after the refactor.

`frontend/src/screens/EmailScreen.jsx` — rewrite from the hardcoded sample to LIVE data, following FitnessScreen's in-component fetch + connection-states convention:
- Loads `api.oauthStatus()` → find provider `google`; connection states mirror Fitness: not-connected → "Connect Google" CTA calling `api.oauthConnect('google')` then `window.location = r.authorize_url`; connected; `needs_reauth` (reconnect banner); syncing (connected + inbox empty + no last_sync yet).
- Loads `api.emailInbox()` → two-pane: left inbox grouped **Needs reply / FYI** with the "N need you" count (`needs_reply_count`); right reading pane shows from / subject / AI summary bullets (`summary`) + body from `api.emailDetail(id)` (loaded on selection).
- OMIT the draft-tone tabs and Send/Edit/Regenerate buttons entirely (deferred slice — no dead UI). Untriaged messages render with no category badge; FYI shows the "filed as FYI" note without the archive button (archive is deferred).

---
### N. Tests + smoke

- MOVE `backend/tests/test_fitness_oauth.py` → `backend/tests/test_oauth.py`: repoint every `/api/fitness/connect|status|disconnect` and callback assertion to `/api/oauth/*` (callback path `/auth/whoop/callback` is unchanged — it's on `oauth.auth_router` now); replace `from app.routers import fitness` / `fitness._STATES` with `from app.routers import oauth` / `oauth._STATES`. Assertions (exchange ran, account persisted, state single-use, disconnect revokes+deletes, revoke-fails-still-deletes, unknown provider 404) stay identical. `FakeProvider` in `tests/fakes.py` GAINS `success_redirect()`/`on_connected()`/`on_disconnect()` (no-ops or trivial) so it satisfies the new protocol.
- NEW `FakeEmailProvider` in `tests/fakes.py`: `name="google"`, implements `set_tokens`, `authorize_url`, `exchange_code`, `refresh`, `revoke`, `fetch_profile` (returns a fake `sub`), `success_redirect() -> "/?screen=email&connected=google"`, `on_connected`/`on_disconnect` (no-op or delegate to store), `fetch_messages(since) -> [NormalizedEmail...]`, `get_message(source_id) -> str`.
- `conftest.py` `no_external_services`: add `email_triage.configure(None)` on setup and `email_triage.configure("unset")` on teardown (mirrors `llm`). `providers.configure([])` / `email_sync.configure(None)` already cover the rest (add `email_sync.configure(None)`/`"unset"` alongside `fitness_sync`).
- Test coverage the phases must add (spec §11): moved oauth endpoints behave as before for WHOOP; Google connect stores an account (via FakeEmailProvider); fitness data endpoints still work; Gmail JSON → `NormalizedEmail` mapping; triage parse (category/summary from a fake LLM); `upsert_email` idempotency (`email_exists` skips); inbox grouping + `needs_reply_count`; on-demand body fetch (+fallback); `needs_reauth` flip on `GoogleAuthError`.
- NEW `app/smoke_google.py` mirroring `smoke_whoop.py` (real GoogleProvider + email_sync against live Gmail; prints authorize URL when not connected, exit 2; NOT in CI).

---
### O. Privacy policy — `docs/privacy-policy.md` (+ corp-site `/privacy/` + the gist, all three copies)

- Section 3 provider table: add a **Google** row — `| **Google (Gmail)** | Email source, read-only (only if you connect it) | OAuth authorization; ScuffedOS reads Gmail messages via the Gmail API | ...` and update the **Anthropic** row's "What is shared" to note email subject + a bounded body excerpt are sent for triage.
- Add an email domain paragraph (parallel to the WHOOP Section 4): Gmail accessed **read-only** via Google OAuth; message content (subject + a bounded body excerpt) is sent to **Anthropic** for triage; message **bodies are NOT stored** (fetched on demand); Google tokens stored server-side, deleted on disconnect.
- Supabase row: add "and email metadata (no message bodies)" to what's stored.

---
### P. Phasing → author mapping (7 parallel authors; §14 of spec)
1. OAuth refactor (§A protocol split, §B registry, §C WhoopProvider hooks, §I oauth router extraction + moved tests §N-first-bullet, main.py wiring) **AND the §M frontend OAuth repoint** (`api.js` gains `oauthStatus/oauthConnect/oauthDisconnect` + drops the three fitness OAuth helpers; `FitnessScreen.jsx` uses the oauth helpers — Task 7). — the SPINE; lands first. The frontend repoint lives HERE, once, so Phase 6 never re-does it.
2. Config (§G) + `GoogleProvider` OAuth (§D authorize/exchange/refresh/revoke + fetch_profile `sub`) against fixtures.
3. `emails` model + migration 0005 (§E) + store methods (§F).
4. `GoogleProvider` Gmail fetch (§D fetch_messages/get_message + mapping) + `email_triage` (§H) + `email_sync` tick (§J) + lifespan wiring.
5. Email API `routers/email.py` + schemas (§K) + read-only assistant tools (§L).
6. Frontend `EmailScreen` rewrite + the **email** `api.js` helpers (`emailInbox/emailDetail/emailSync`) + the inbox icon (§M). The oauth repoint (`api.js` oauth helpers + `FitnessScreen`) is NOT re-done here — Phase 1 owns it; Phase 6 only verifies it and adds the email surface.
7. Privacy-policy update (§O) + `smoke_google` (§N) + live Google localhost OAuth validation.

---
## Phase: OAuth refactor: split seam + shared oauth router

### Task 1: Split the provider Protocol into OAuthProvider + FitnessProvider + EmailProvider (+ NormalizedEmail)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_protocols.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_protocols.py`

**Interfaces:**
- Consumes: The single FitnessProvider Protocol in app/providers/base.py (OAuth methods bundled with fetch_recovery/sleep/workouts).
- Produces: A base OAuthProvider Protocol (name/authorize_url/exchange_code/refresh/revoke/set_tokens/success_redirect/on_connected/on_disconnect), FitnessProvider(OAuthProvider) adding kind + the three fetch_* methods, EmailProvider(OAuthProvider) adding fetch_messages/get_message, and the NormalizedEmail dataclass. AuthError/Tokens/NormalizedSnapshot/NormalizedWorkout unchanged.

- [ ] **Step 1: Write a failing test asserting the new protocol shape + NormalizedEmail**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_protocols.py`. It drives the split: `OAuthProvider` importable + runtime-checkable, `EmailProvider` importable, `WhoopProvider` still structurally satisfies `FitnessProvider`, and `NormalizedEmail` has the frozen fields/defaults.

```python
"""The M5 provider-protocol split: OAuthProvider base + Fitness/Email domains.

Guards that the refactor keeps WhoopProvider structurally a FitnessProvider,
and introduces the EmailProvider protocol + NormalizedEmail dataclass with the
frozen field set. No network — pure type/shape assertions.
"""
from dataclasses import fields
from datetime import datetime, timezone

from app.providers import base
from app.providers.whoop import WhoopProvider


def test_oauth_provider_is_runtime_checkable():
    assert hasattr(base, "OAuthProvider")
    assert getattr(base.OAuthProvider, "_is_runtime_protocol", False) is True


def test_email_provider_exists():
    assert hasattr(base, "EmailProvider")


def test_whoop_still_satisfies_fitness_provider():
    # runtime_checkable structural check — WhoopProvider must keep passing after
    # it gains the three OAuthProvider hooks (added in a later task; this only
    # asserts the protocol still admits it structurally today).
    assert isinstance(WhoopProvider(), base.FitnessProvider)


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

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_protocols.py -q`
Expected: FAILS at collection/import — `ImportError: cannot import name 'OAuthProvider'` (or `AttributeError` on `base.NormalizedEmail`), because base.py does not yet define the split.

- [ ] **Step 2: Split base.py: add OAuthProvider, re-parent FitnessProvider, add EmailProvider + NormalizedEmail**

Rewrite `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`. Keep `AuthError`, `Tokens`, `NormalizedSnapshot`, `NormalizedWorkout` byte-for-byte; add `NormalizedEmail`; introduce `OAuthProvider` and re-parent the two domain protocols onto it.

```python
"""Vendor-neutral provider seam: normalized dataclasses + Protocols + AuthError.

M5 split the single FitnessProvider Protocol into a shared OAuthProvider base
(the connect/callback/disconnect plumbing the shared router drives) plus two
domain protocols: FitnessProvider (WHOOP-style pull data) and EmailProvider
(Gmail-style message reads). No provider field names leak past the provider
module — every provider maps its payloads into these dataclasses. ``AuthError``
is the typed auth/refresh failure the sync engines catch to flip a provider to
``needs_reauth`` (the real providers raise WhoopAuthError / GoogleAuthError).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable


class AuthError(Exception):
    """Auth/refresh failure raised by a provider. The sync engines catch
    ``except AuthError`` and flip the provider to ``status='needs_reauth'``.
    The real providers' WhoopAuthError / GoogleAuthError subclass this."""


@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None          # aware UTC
    scopes: str = ""                      # space-delimited, as granted
    provider_user_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class NormalizedSnapshot:
    source: str                          # 'whoop'
    day: date
    recovery_pct: int | None = None
    day_strain: float | None = None
    sleep_quality_pct: int | None = None
    hrv_ms: float | None = None
    resting_hr: int | None = None
    respiratory_rate: float | None = None
    sleep_hours: float | None = None
    metrics_json: dict = field(default_factory=dict)


@dataclass
class NormalizedWorkout:
    source: str                          # 'whoop'
    source_id: str | None
    name: str
    sport: str | None
    started_at: datetime                 # aware UTC
    duration_min: int
    strain: float | None = None
    calories: int | None = None          # kcal (already kJ->kcal converted)
    avg_hr: int | None = None
    max_hr: int | None = None


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


@runtime_checkable
class OAuthProvider(Protocol):
    """The connect/callback/disconnect plumbing the shared oauth router drives.
    Both FitnessProvider and EmailProvider extend it."""
    name: str                            # 'whoop' | 'google'

    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def revoke(self, tokens: Tokens) -> None: ...
    def set_tokens(self, tokens: Tokens | None) -> None: ...
    def success_redirect(self) -> str: ...      # screen to land on after connect
    def on_connected(self) -> None: ...          # post-connect hook (kick a sync)
    def on_disconnect(self) -> None: ...         # delete this provider's domain data


@runtime_checkable
class FitnessProvider(OAuthProvider, Protocol):
    kind: Literal["pull", "push"]        # whoop/oura='pull'; apple_health='push'

    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...


@runtime_checkable
class EmailProvider(OAuthProvider, Protocol):
    def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
    def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
```

Note: `test_whoop_still_satisfies_fitness_provider` will pass because `FitnessProvider` is `runtime_checkable` and does structural (method-presence) checking — WhoopProvider already has all the non-hook methods, and `runtime_checkable` isinstance ignores the hook methods it does not yet implement (they get added in the next task). The strict guarantee that WhoopProvider implements the hooks is enforced by the M4 OAuth suite behaviorally, not by isinstance.

- [ ] **Step 3: Run the protocol test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_protocols.py -q`
Expected: `4 passed`.

- [ ] **Step 4: Run the full suite to confirm the split broke nothing**

The import surface of base.py changed (new symbols, re-parented protocols); confirm every existing importer (whoop.py, providers/__init__.py, fitness_sync.py, tests) still resolves.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: the whole suite passes, including the entire M4 fitness suite (`tests/test_fitness_oauth.py`, fitness data tests). Report the pass count (e.g. `N passed`).

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/providers/base.py backend/tests/test_provider_protocols.py
git commit -m "$(cat <<'EOF'
M5 refactor: split FitnessProvider into OAuthProvider base + Fitness/Email domains

Add OAuthProvider (name/authorize_url/exchange_code/refresh/revoke/set_tokens/
success_redirect/on_connected/on_disconnect); re-parent FitnessProvider onto it
(keeps kind + fetch_recovery/sleep/workouts); add EmailProvider (fetch_messages/
get_message) + NormalizedEmail dataclass. AuthError/Tokens/normalized fitness
dataclasses unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds on branch `m5-email-triage`.


### Task 2: Add the three OAuthProvider hooks to WhoopProvider (+ FakeProvider) so connect/disconnect stay symmetric

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/whoop.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_whoop_provider.py`

**Interfaces:**
- Consumes: The OAuthProvider protocol from the previous task; WhoopProvider (which already has set_tokens but lacks success_redirect/on_connected/on_disconnect); FakeProvider in tests/fakes.py.
- Produces: WhoopProvider.success_redirect() -> '/?screen=fitness&connected=whoop', on_connected() -> fitness_sync.tick(), on_disconnect() -> store.delete_provider_data('whoop'). FakeProvider gains no-op/trivial success_redirect/on_connected/on_disconnect so it satisfies the new protocol under the shared router.

- [ ] **Step 1: Write a failing test for the three WhoopProvider hooks**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_whoop_provider.py`. Assert the redirect string, that `on_connected` calls `fitness_sync.tick`, and that `on_disconnect` calls `store.delete_provider_data('whoop')`. Both hooks are exercised with monkeypatched collaborators — no network, no DB.

```python
"""WhoopProvider gains the three OAuthProvider hooks (M5 refactor).

success_redirect is a pure string; on_connected kicks the fitness sync;
on_disconnect deletes WHOOP's normalized data via the store. All exercised
with monkeypatched collaborators — no network, no DB.
"""
from app.providers.whoop import WhoopProvider


def test_success_redirect_targets_fitness_screen():
    assert WhoopProvider().success_redirect() == "/?screen=fitness&connected=whoop"


def test_on_connected_kicks_the_fitness_sync(monkeypatch):
    from app import fitness_sync
    calls = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: calls.append(now) or 0)
    WhoopProvider().on_connected()
    assert len(calls) == 1


def test_on_disconnect_deletes_whoop_provider_data(monkeypatch):
    from app import store as store_mod
    deleted = []
    monkeypatch.setattr(
        store_mod.store, "delete_provider_data",
        lambda provider: deleted.append(provider) or True,
    )
    WhoopProvider().on_disconnect()
    assert deleted == ["whoop"]
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_provider.py -q`
Expected: FAILS — `AttributeError: 'WhoopProvider' object has no attribute 'success_redirect'` (and the other two).

- [ ] **Step 2: Add the three hooks to WhoopProvider**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/whoop.py`. Insert the three hook methods right after `set_tokens` (before `_transport`). Use lazy imports inside the hooks (mirroring the contract) to avoid an import cycle (`fitness_sync` imports `providers`, which imports `whoop`).

Find this block:
```python
    def set_tokens(self, tokens: Tokens | None) -> None:
        """The sync engine injects the stored (possibly-refreshed) tokens here
        before calling fetch_recovery/sleep/workouts so authed calls carry a
        Bearer token. Without this every fetch would 401 (empty token)."""
        self._tokens = tokens

    def _transport(self):
```

Replace it with:
```python
    def set_tokens(self, tokens: Tokens | None) -> None:
        """The sync engine injects the stored (possibly-refreshed) tokens here
        before calling fetch_recovery/sleep/workouts so authed calls carry a
        Bearer token. Without this every fetch would 401 (empty token)."""
        self._tokens = tokens

    # ---- OAuthProvider hooks (M5: the shared oauth router drives these) ----
    def success_redirect(self) -> str:
        """Screen the SPA lands on after a successful WHOOP connect."""
        return "/?screen=fitness&connected=whoop"

    def on_connected(self) -> None:
        """Post-connect hook: kick an immediate fitness sync (backfill). The
        fresh account has no last_sync_at, so tick() backfills on this pass."""
        from .. import fitness_sync
        fitness_sync.tick()

    def on_disconnect(self) -> None:
        """Disconnect hook: delete WHOOP's daily_snapshots/workouts (source=
        'whoop'); manual workouts are preserved. Idempotent with the shared
        router's own delete_provider_data call (row already gone → no-op)."""
        from ..store import store
        store.delete_provider_data(self.name)

    def _transport(self):
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_provider.py -q`
Expected: `3 passed`.

- [ ] **Step 3: Add the hooks to FakeProvider so it satisfies the new protocol under the shared router**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`. `FakeProvider` (name='whoop') is what the moved OAuth tests install; under the shared router the callback calls `on_connected()` and disconnect calls `on_disconnect()`, so it must implement them. Give it a `success_redirect` matching WHOOP, an `on_connected` that records the call, and an `on_disconnect` that delegates to the store (so behavior matches the real provider's data-deletion).

Find the tail of `FakeProvider`:
```python
    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)
```

Replace it with:
```python
    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)

    # ---- OAuthProvider hooks (M5) — the shared oauth router drives these ----
    def success_redirect(self) -> str:
        return "/?screen=fitness&connected=whoop"

    def on_connected(self) -> None:
        self.connected_calls = getattr(self, "connected_calls", 0) + 1

    def on_disconnect(self) -> None:
        # Mirror the real provider: delete this provider's normalized data.
        # Idempotent with the router's own delete_provider_data (row gone).
        from app.store import store
        store.delete_provider_data(self.name)
```

Also initialise the counter in `__init__` so a test can assert it. Find:
```python
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []
```
Replace with:
```python
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []
        self.connected_calls = 0
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_provider.py -q`
Expected: still `3 passed` (fakes edit does not touch this file's behavior; this run just confirms no import breakage).

- [ ] **Step 4: Run the full suite — fitness path must stay green**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: whole suite passes including the M4 fitness suite. Report the pass count.

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/providers/whoop.py backend/tests/fakes.py backend/tests/test_whoop_provider.py
git commit -m "$(cat <<'EOF'
M5 refactor: WhoopProvider gains success_redirect/on_connected/on_disconnect

on_connected triggers the fitness sync; on_disconnect deletes WHOOP's
normalized data (delete_provider_data, manual preserved); success_redirect
lands on the fitness screen. FakeProvider gains the same hooks so it satisfies
the OAuthProvider protocol under the shared router.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds.


### Task 3: Retype the provider registry to OAuthProvider and let _build_real tolerate a missing GoogleProvider

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/__init__.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_registry.py`

**Interfaces:**
- Consumes: app/providers/__init__.py typed as list[FitnessProvider]; _build_real building only [WhoopProvider()].
- Produces: Registry typed as list[OAuthProvider]; _build_real builds [WhoopProvider(), GoogleProvider()] with GoogleProvider imported lazily and skipped on ImportError (it does not exist yet mid-plan); all_providers()/get() return OAuthProvider; pull_providers() filters getattr(p,'kind',None)=='pull' so a kind-less GoogleProvider is naturally excluded from fitness sync.

- [ ] **Step 1: Write a failing test for the widened registry + kind-safe pull filter**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_provider_registry.py`. It installs a mixed fake registry (a pull-fitness fake + a kind-less email-ish fake) and asserts `all_providers()` returns both, `get()` finds by name, and `pull_providers()` returns ONLY the one with `kind=='pull'` (never raising AttributeError on the kind-less one).

```python
"""The provider registry after the M5 widening to OAuthProvider.

pull_providers() must filter on getattr(p, 'kind', None) == 'pull' so a
kind-less email provider is naturally excluded from the fitness sync without
raising AttributeError. Uses the configure([...]) seam — no real providers.
"""
from app import providers


class _PullFake:
    name = "whoop"
    kind = "pull"


class _EmailFake:
    name = "google"  # NO kind attribute — an email provider


def test_all_providers_and_get_span_both_domains():
    providers.configure([_PullFake(), _EmailFake()])
    try:
        names = {p.name for p in providers.all_providers()}
        assert names == {"whoop", "google"}
        assert providers.get("google").name == "google"
        assert providers.get("nope") is None
    finally:
        providers.configure("unset")


def test_pull_providers_excludes_kindless_email_provider():
    providers.configure([_PullFake(), _EmailFake()])
    try:
        pulls = providers.pull_providers()
        assert [p.name for p in pulls] == ["whoop"]  # email fake excluded, no crash
    finally:
        providers.configure("unset")
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_registry.py -q`
Expected: `test_pull_providers_excludes_kindless_email_provider` FAILS with `AttributeError: '_EmailFake' object has no attribute 'kind'` (current `pull_providers` uses `p.kind`, not `getattr`).

- [ ] **Step 2: Widen the registry types and make _build_real + pull_providers tolerant**

Rewrite `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/__init__.py`.

```python
"""Provider registry + test seam (M4 §4; widened for M5's email domain).

The sync engines and the shared oauth router go through these four functions
only. The seam mirrors llm.py: `_override == "unset"` uses the real registry;
installing a list of fake providers via `configure([...])` swaps it wholesale
for tests — no network, no settings.

The real registry builds WhoopProvider + GoogleProvider lazily and caches them;
construction is cheap (each provider's httpx client is itself lazy), so
importing this package never makes a request. GoogleProvider is imported inside
a try/except so the registry still works mid-plan before that module lands.
"""
from __future__ import annotations

from .base import FitnessProvider, OAuthProvider

_override: object | str = "unset"   # "unset" → real registry; list → fakes
_real: list[OAuthProvider] | None = None


def configure(override: object | str = "unset") -> None:
    """Tests install a fake provider list; configure() restores the real registry."""
    global _override
    _override = override


def _build_real() -> list[OAuthProvider]:
    global _real
    if _real is None:
        built: list[OAuthProvider] = []
        try:
            from .whoop import WhoopProvider
            built.append(WhoopProvider())
        except ImportError:
            pass  # WhoopProvider not present (shouldn't happen) — skip it.
        try:
            from .google import GoogleProvider
            built.append(GoogleProvider())
        except ImportError:
            pass  # GoogleProvider not present yet (mid-plan) — skip it.
        _real = built
    return _real


def all_providers() -> list[OAuthProvider]:
    """Every registered provider (real, or the installed fake list)."""
    if _override != "unset":
        return list(_override)  # type: ignore[arg-type]
    return _build_real()


def get(name: str) -> OAuthProvider | None:
    """A provider by its `name` (e.g. 'whoop', 'google'), or None if absent."""
    for p in all_providers():
        if p.name == name:
            return p
    return None


def pull_providers() -> list[FitnessProvider]:
    """Providers the fitness sync tick may poll (kind == 'pull'). A kind-less
    provider (e.g. GoogleProvider) is naturally excluded."""
    return [p for p in all_providers() if getattr(p, "kind", None) == "pull"]
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_registry.py -q`
Expected: `2 passed`.

- [ ] **Step 3: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: whole suite green, M4 fitness suite included. Report the pass count. (Note: `from .google import GoogleProvider` raising `ImportError` mid-plan is caught — the real registry still returns `[WhoopProvider()]`, so any test that hits the real registry is unaffected.)

- [ ] **Step 4: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/providers/__init__.py backend/tests/test_provider_registry.py
git commit -m "$(cat <<'EOF'
M5 refactor: widen provider registry to OAuthProvider; tolerate missing GoogleProvider

_build_real now appends WhoopProvider + (lazily) GoogleProvider, skipping the
latter on ImportError mid-plan. pull_providers() filters getattr(p,'kind',None)
== 'pull' so a kind-less email provider is excluded without AttributeError.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds.


### Task 4: Add the generic OAuthStatus schema

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth_schema.py`

**Interfaces:**
- Consumes: schemas.py with ProviderStatus, FitnessStatus, ConnectUrl defined (M4).
- Produces: A generic OAuthStatus schema (structurally identical to FitnessStatus: connected: bool + providers: List[ProviderStatus]) returned by the shared /api/oauth/status endpoint. FitnessStatus stays (still referenced by the assistant fitness-status tool shape).

- [ ] **Step 1: Write a failing test asserting OAuthStatus exists and mirrors FitnessStatus**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth_schema.py`.

```python
"""The generic OAuthStatus schema (M5): connected + list[ProviderStatus].

Structurally identical to the M4 FitnessStatus so the moved status test passes;
it is what the shared /api/oauth/status endpoint returns.
"""
from datetime import datetime, timezone

from app import schemas


def test_oauth_status_shape():
    assert hasattr(schemas, "OAuthStatus")
    ps = schemas.ProviderStatus(
        provider="whoop", status="connected",
        connected_at=datetime(2026, 6, 1, tzinfo=timezone.utc), last_sync_at=None,
        provider_user_id="u1",
    )
    m = schemas.OAuthStatus(connected=True, providers=[ps])
    dumped = m.model_dump()
    assert dumped["connected"] is True
    assert dumped["providers"][0]["provider"] == "whoop"
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth_schema.py -q`
Expected: FAILS — `AttributeError: module 'app.schemas' has no attribute 'OAuthStatus'`.

- [ ] **Step 2: Add OAuthStatus to schemas.py right after FitnessStatus**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`. Find:
```python
class FitnessStatus(BaseModel):
    connected: bool  # any provider connected
    providers: List[ProviderStatus]


class ConnectUrl(BaseModel):
    authorize_url: str
```

Replace with:
```python
class FitnessStatus(BaseModel):
    connected: bool  # any provider connected
    providers: List[ProviderStatus]


# M5: generic OAuth status returned by the shared /api/oauth/status endpoint.
# Structurally identical to FitnessStatus (domain-agnostic) so the moved M4
# status test passes unchanged. FitnessStatus stays for the assistant tool shape.
class OAuthStatus(BaseModel):
    connected: bool  # any provider connected
    providers: List[ProviderStatus]


class ConnectUrl(BaseModel):
    authorize_url: str
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth_schema.py -q`
Expected: `1 passed`.

- [ ] **Step 3: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/schemas.py backend/tests/test_oauth_schema.py
git commit -m "$(cat <<'EOF'
M5 refactor: add generic OAuthStatus schema for the shared oauth router

Structurally identical to FitnessStatus (connected + list[ProviderStatus]);
returned by /api/oauth/status. FitnessStatus retained for the assistant tool.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds.


### Task 5: Create the shared oauth router (connect/status/disconnect/callback) alongside the fitness OAuth endpoints

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/oauth.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py`

**Interfaces:**
- Consumes: The OAuth logic still living in routers/fitness.py; the OAuthProvider hooks on WhoopProvider/FakeProvider; the OAuthStatus schema; store.upsert_provider_account/get_provider_tokens/list_provider_accounts/delete_provider_data.
- Produces: A new app/routers/oauth.py exporting router (prefix /api/oauth) + auth_router (no prefix, /auth/{provider}/callback) with _STATES/_issue_state/_consume_state, the connect/status/disconnect endpoints and the callback — all provider-registry-driven and calling impl.on_connected()/impl.on_disconnect()/impl.success_redirect(). main.py includes both new routers. A new test_oauth.py (the moved M4 OAuth tests) drives /api/oauth/* + /auth/whoop/callback and passes. The fitness OAuth endpoints still exist at this point (removed in the next task) — both coexist harmlessly.

- [ ] **Step 1: Create the moved OAuth test suite driving the shared /api/oauth/* router**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py` — the M4 `test_fitness_oauth.py` tests, repointed to `/api/oauth/*` and `oauth._STATES`, with the callback path unchanged (`/auth/whoop/callback`). Every assertion (exchange ran, account persisted, state single-use, disconnect revokes+deletes, revoke-fails-still-deletes, unknown provider 404, tokens never leak) is preserved. The callback test monkeypatches `fitness_sync.tick` because WhoopProvider.on_connected() calls it; it asserts the redirect hits the fitness screen (proving `impl.success_redirect()` is used).

```python
"""Shared OAuth router (M5): connect URL, callback, disconnect, status.

Moved from test_fitness_oauth.py — the M4 guardrail now drives /api/oauth/*
instead of /api/fitness/*. The callback path /auth/whoop/callback is unchanged
(it lives on oauth.auth_router now). Every test installs a FakeProvider via
providers.configure([...]) — no network. The CSRF state store is oauth._STATES.
"""
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app import providers
from app.providers.base import Tokens
from app.routers import oauth
from app.store import store

from .fakes import FakeProvider


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def res_text(obj) -> str:
    return json.dumps(obj)


def test_connect_returns_authorize_url_with_client_id_and_state(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/oauth/connect/whoop")
    assert res.status_code == 200
    url = res.json()["authorize_url"]
    assert "client_id=fake-client" in url
    qs = parse_qs(urlparse(url).query)
    assert qs["state"][0]


def test_connect_stores_a_one_time_state_server_side(client):
    providers.configure([FakeProvider()])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    assert oauth._STATES.get(state) == "whoop"
    state2 = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    assert state2 != state


def test_connect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/oauth/connect/garmin")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_status_empty_when_nothing_connected(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/oauth/status")
    assert res.status_code == 200
    assert res.json() == {"connected": False, "providers": []}


def test_status_reflects_a_connected_account_without_tokens(client):
    providers.configure([FakeProvider()])
    store.upsert_provider_account(
        "whoop",
        Tokens(
            access_token="secret-access", refresh_token="secret-refresh",
            expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scopes="read:recovery", provider_user_id="whoop-user-1",
        ),
    )
    body = client.get("/api/oauth/status").json()
    assert body["connected"] is True
    assert len(body["providers"]) == 1
    p = body["providers"][0]
    assert p["provider"] == "whoop"
    assert p["status"] == "connected"
    assert p["provider_user_id"] == "whoop-user-1"
    assert p["last_sync_at"] is None
    assert "secret-access" not in res_text(body)
    assert "access_token" not in p and "refresh_token" not in p


def test_callback_exchanges_persists_and_triggers_immediate_sync(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    ticks: list[object] = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: ticks.append(now) or 0)

    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(
        f"/auth/whoop/callback?code=the-code&state={state}",
        follow_redirects=False,
    )
    assert res.status_code in (302, 307)
    loc = res.headers["location"]
    assert "screen=fitness" in loc and "connected=whoop" in loc

    assert fake.exchanged == ["the-code"]
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"
    assert accounts[0]["provider_user_id"] == "whoop-user-1"
    # on_connected() ran WhoopProvider.on_connected → fitness_sync.tick once.
    assert len(ticks) == 1
    assert state not in oauth._STATES


def test_callback_with_bad_state_is_400_and_persists_nothing(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)

    res = client.get(
        "/auth/whoop/callback?code=x&state=forged-state",
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "bad_request"
    assert fake.exchanged == []
    assert store.list_provider_accounts() == []


def test_callback_state_is_single_use(client, monkeypatch):
    from app import fitness_sync

    providers.configure([FakeProvider()])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    first = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert first.status_code in (302, 307)
    replay = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_disconnect_revokes_then_deletes_and_returns_status(client):
    fake = FakeProvider()
    providers.configure([fake])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="a", refresh_token="r", expires_at=None,
               scopes="read:recovery", provider_user_id="u1"),
    )
    assert client.get("/api/oauth/status").json()["connected"] is True

    res = client.post("/api/oauth/disconnect/whoop")
    assert res.status_code == 200
    assert res.json() == {"connected": False, "providers": []}
    assert len(fake.revoked) == 1
    assert fake.revoked[0].access_token == "a"
    assert store.list_provider_accounts() == []


def test_disconnect_deletes_even_when_revoke_fails(client):
    class Boom(FakeProvider):
        def revoke(self, tokens):
            raise RuntimeError("whoop revoke endpoint down")

    providers.configure([Boom()])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="a", refresh_token="r", expires_at=None,
               scopes="", provider_user_id=None),
    )
    res = client.post("/api/oauth/disconnect/whoop")
    assert res.status_code == 200
    assert res.json()["connected"] is False
    assert store.list_provider_accounts() == []


def test_disconnect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])
    res = client.post("/api/oauth/disconnect/whoop")  # nothing connected
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth.py -q`
Expected: FAILS at import — `ModuleNotFoundError: No module named 'app.routers.oauth'` (or `ImportError: cannot import name 'oauth'`).

- [ ] **Step 2: Create app/routers/oauth.py with the generalized endpoints**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/oauth.py`. The connect/status/callback logic is the M4 fitness logic, generalized: the callback calls `impl.on_connected()` (not a hardcoded `fitness_sync.tick()`) and redirects to `impl.success_redirect()`; disconnect orchestrates `revoke` (best-effort) → `store.delete_provider_data(provider)` (drives the 404 via its `existed` return) → `impl.on_disconnect()`. `fetch_profile` is still accessed via `getattr` exactly as the M4 callback does.

```python
"""Shared OAuth router (M5) — provider-registry-driven connect/callback/
disconnect/status, extracted from routers/fitness.py so a second OAuth domain
(email) reuses the plumbing. Domain-specific behavior lives behind the
OAuthProvider hooks: success_redirect (where to land), on_connected (kick the
domain sync), on_disconnect (delete the domain's data). Tokens never leave the
server.

Two routers are exported: `router` under /api/oauth, and `auth_router` with NO
prefix so a provider-registered redirect lands at exactly /auth/{provider}/
callback (outside /api). main.py includes both.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from .. import providers
from ..schemas import ConnectUrl, OAuthStatus
from ..store import store

router = APIRouter(prefix="/api/oauth", tags=["oauth"])
auth_router = APIRouter(tags=["oauth"])

# One-time CSRF states: state token -> provider name. In-process is fine for a
# single-user desktop app (one-time CSRF check); a restart mid-flow just makes
# the user click Connect again.
_STATES: dict[str, str] = {}

logger = logging.getLogger("scuffed_os.oauth")


def _issue_state(provider: str) -> str:
    state = secrets.token_urlsafe(24)
    _STATES[state] = provider
    return state


def _consume_state(state: str) -> str | None:
    """Pop a state, returning the provider it was issued for (one-time use)."""
    return _STATES.pop(state, None)


def _status_dict() -> dict:
    accounts = store.list_provider_accounts()
    return {
        "connected": any(a["status"] == "connected" for a in accounts),
        "providers": accounts,
    }


@router.get("/connect/{provider}", response_model=ConnectUrl)
def connect(provider: str) -> dict:
    """Build the provider's authorize URL with a fresh one-time CSRF state."""
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    state = _issue_state(provider)
    return {"authorize_url": impl.authorize_url(state)}


@router.get("/status", response_model=OAuthStatus)
def status() -> dict:
    """Per-provider connection state. Reads safe dicts only — no tokens."""
    return _status_dict()


@auth_router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """OAuth redirect target (outside /api). Verify the one-time CSRF state,
    exchange the code, best-effort stamp the provider_user_id, persist tokens
    server-side, run the provider's post-connect hook (an immediate domain
    sync/backfill), then bounce back to the provider's screen."""
    issued_for = _consume_state(state)
    if issued_for is None or issued_for != provider:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    tokens = impl.exchange_code(code)
    # exchange_code does NOT carry provider_user_id. Fetch it from the
    # provider's profile endpoint (best-effort) and stamp it onto the tokens.
    fetch_profile = getattr(impl, "fetch_profile", None)
    if fetch_profile is not None and tokens.provider_user_id is None:
        uid = fetch_profile(tokens)
        if uid is not None:
            tokens.provider_user_id = uid
    store.upsert_provider_account(provider, tokens)
    impl.on_connected()   # immediate domain sync/backfill (fresh account → backfill)
    return RedirectResponse(impl.success_redirect(), status_code=302)


@router.post("/disconnect/{provider}", response_model=OAuthStatus)
def disconnect(provider: str) -> dict:
    """Revoke at the provider (best-effort), delete its tokens (+ any fitness
    data via delete_provider_data), then run the provider's on_disconnect hook
    to clear its domain data. Deletion is the user-facing guarantee, so a
    failed revoke never blocks it. A missing account → 404."""
    impl = providers.get(provider)
    tokens = store.get_provider_tokens(provider)
    if impl is not None and tokens is not None:
        try:
            impl.revoke(tokens)
        except Exception as exc:  # noqa: BLE001 — revoke is best-effort
            logger.warning("revoke failed for %s, deleting anyway: %s", provider, exc)
    # delete_provider_data removes the account row (+ fitness tables where
    # source==provider); its existed return drives the 404.
    if not store.delete_provider_data(provider):
        raise HTTPException(status_code=404, detail=f"No connected '{provider}' account")
    # on_disconnect clears the provider's domain data. For WHOOP this re-calls
    # delete_provider_data (idempotent — row already gone); for Google it
    # deletes the emails table. Best-effort so a hook error never 500s the
    # user-facing delete.
    if impl is not None:
        try:
            impl.on_disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_disconnect hook failed for %s: %s", provider, exc)
    return _status_dict()
```

Do NOT run the test yet — main.py must include the routers first (next step).

- [ ] **Step 3: Wire the oauth routers into main.py (keep fitness routers for now)**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`. Add `oauth` to the routers import and include both oauth routers. Leave the fitness routers as-is for this task (they are stripped of OAuth in the next task); the two connect/callback paths differ (`/api/fitness/*` vs `/api/oauth/*`) so they coexist without conflict.

Find:
```python
from .routers import assistant, calendar, fitness, habits, memory, nutrition, tasks
```
Replace with:
```python
from .routers import (
    assistant,
    calendar,
    fitness,
    habits,
    memory,
    nutrition,
    oauth,
    tasks,
)
```

Find:
```python
app.include_router(fitness.router)
app.include_router(fitness.auth_router)
```
Replace with:
```python
app.include_router(fitness.router)
app.include_router(fitness.auth_router)
app.include_router(oauth.router)
app.include_router(oauth.auth_router)
```

Note: both `fitness.auth_router` and `oauth.auth_router` register `/auth/{provider}/callback`. FastAPI keeps the FIRST match; `fitness.auth_router` is included first so it still serves the callback until the next task removes it. That is fine — the callback body is identical in behavior for WHOOP (it triggers a tick + redirects to the fitness screen), so `tests/test_oauth.py`'s callback assertions pass regardless of which router serves it. The next task removes `fitness.auth_router`, leaving `oauth.auth_router` as the sole handler.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth.py -q`
Expected: `12 passed`.

- [ ] **Step 4: Run the full suite — both old and new OAuth tests should pass**

At this point `tests/test_fitness_oauth.py` (old, /api/fitness/*) AND `tests/test_oauth.py` (new, /api/oauth/*) both exist and both pass — the endpoints coexist.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: whole suite green. Report the pass count.

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/routers/oauth.py backend/app/main.py backend/tests/test_oauth.py
git commit -m "$(cat <<'EOF'
M5 refactor: add shared /api/oauth router (connect/callback/disconnect/status)

Provider-registry-driven and domain-agnostic: callback runs impl.on_connected()
and redirects to impl.success_redirect(); disconnect does best-effort revoke ->
delete_provider_data (drives 404) -> impl.on_disconnect(). Moves the M4 OAuth
tests to test_oauth.py against /api/oauth/*; the fitness OAuth endpoints still
exist (removed next) and both coexist. main.py includes both oauth routers.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds.


### Task 6: Strip the OAuth endpoints from routers/fitness.py and delete the superseded fitness OAuth test

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness.py`

**Interfaces:**
- Consumes: routers/fitness.py still holding connect/status/disconnect/callback/_STATES/_FITNESS_REDIRECT; the old tests/test_fitness_oauth.py; main.py including fitness.auth_router.
- Produces: routers/fitness.py reduced to ONLY its data endpoints (/today, /week, /workouts GET+POST, /workouts/{id} DELETE, /sync); its `auth_router` export is dropped. tests/test_fitness_oauth.py deleted (superseded by test_oauth.py). main.py no longer includes fitness.auth_router. No /api/fitness/connect|status|disconnect route exists; fitness data behavior unchanged.

**ORDERING — callback route must never drop out mid-edit:** `/auth/{provider}/callback` is served by BOTH `fitness.auth_router` (included first, so it wins by FastAPI first-match until now) and `oauth.auth_router` (added in Task 5). This task removes `fitness.auth_router`. To keep the app importable AND the callback always served through the transition, the main.py edit that removes the `fitness.auth_router` include is done FIRST (Step 2), and only THEN is `fitness.py` rewritten to drop the `auth_router` export (Step 3). Doing it the other way round would leave `main.py` referencing a now-missing `fitness.auth_router` attribute → an ImportError that makes the whole app un-importable between steps. After Step 2, `oauth.auth_router` is the sole handler of `/auth/{provider}/callback` (it was already registered in Task 5), so the callback is continuously served.

- [ ] **Step 1: Add a guard test asserting the fitness OAuth routes are GONE**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py` a test that the old fitness OAuth routes no longer exist (405/404), locking the removal. Add this at the end of the file:

```python
def test_fitness_oauth_routes_are_removed(client):
    # The OAuth surface moved to /api/oauth/*; /api/fitness/connect|status|
    # disconnect must no longer be routable.
    providers.configure([FakeProvider()])
    assert client.get("/api/fitness/connect/whoop").status_code == 404
    assert client.get("/api/fitness/status").status_code == 404
    assert client.post("/api/fitness/disconnect/whoop").status_code == 404
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth.py::test_fitness_oauth_routes_are_removed -q`
Expected: FAILS — those routes still exist (`/api/fitness/status` returns 200, connect/disconnect return their current codes), so the 404 assertions fail.

- [ ] **Step 2: Remove fitness.auth_router from main.py FIRST (keeps the app importable)**

Do this BEFORE rewriting `fitness.py` (Step 3), so `main.py` never references a `fitness.auth_router` that the next step is about to delete. `oauth.auth_router` was registered in Task 5, so it takes over `/auth/{provider}/callback` the instant `fitness.auth_router` is dropped — the callback is served continuously.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`.

Find:
```python
app.include_router(fitness.router)
app.include_router(fitness.auth_router)
app.include_router(oauth.router)
app.include_router(oauth.auth_router)
```
Replace with:
```python
app.include_router(fitness.router)
app.include_router(oauth.router)
app.include_router(oauth.auth_router)
```

At this instant `fitness.auth_router` is still exported by `fitness.py` (harmless — just no longer included), and the callback is served by `oauth.auth_router`. The next step removes the now-unused export.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth.py -q`
Expected: `13 passed` (the 12 moved tests + the new removal guard; the callback is now served exclusively by `oauth.auth_router`).

- [ ] **Step 3: Reduce routers/fitness.py to its data endpoints only**

Now that `main.py` no longer includes `fitness.auth_router`, it is safe to drop that export. Rewrite `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`, dropping connect/status/disconnect/callback, `_STATES`, `_issue_state`/`_consume_state`, `_FITNESS_REDIRECT`, the `auth_router` export, and the now-unused imports (`secrets`, `RedirectResponse`; `Query` STAYS — the data endpoints still use it; `providers`, `ConnectUrl`, `FitnessStatus` for OAuth go, but `pull_providers` STAYS because /sync uses it).

```python
"""Fitness data endpoints (M4) — normalized reads/writes.

After the M5 OAuth refactor this module owns ONLY the fitness data surface:
/today, /week, /workouts (list/create/delete), and /sync. The OAuth dance
(connect/callback/disconnect/status + the CSRF state store + the auth_router
hosting /auth/{provider}/callback) moved to the shared routers/oauth.py. Reads
never touch a live WHOOP call — they come straight from the normalized tables.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Response

from .. import fitness_sync
from ..providers import pull_providers
from ..schemas import (
    FitnessToday,
    FitnessWeek,
    WorkoutCreate,
    WorkoutOut,
)
from ..store import store

router = APIRouter(prefix="/api/fitness", tags=["fitness"])


# ---- reads (normalized tables only; never a live provider call) ------------
@router.get("/today", response_model=FitnessToday)
def fitness_today(date_: date | None = Query(default=None, alias="date")) -> dict:
    return store.fitness_today(date_)


@router.get("/week", response_model=FitnessWeek)
def fitness_week(date_: date | None = Query(default=None, alias="date")) -> dict:
    return store.fitness_week(date_)


@router.get("/workouts", response_model=list[WorkoutOut])
def list_workouts(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    return store.list_workouts(limit)


# ---- manual workout write --------------------------------------------------
@router.post("/workouts", response_model=WorkoutOut, status_code=201)
def create_workout(body: WorkoutCreate) -> dict:
    return store.create_workout(body.model_dump())


@router.delete("/workouts/{workout_id}", status_code=204)
def delete_workout(workout_id: int) -> Response:
    if not store.delete_workout(workout_id):
        raise HTTPException(status_code=404, detail="Workout not found")
    return Response(status_code=204)


# ---- on-demand sync --------------------------------------------------------
@router.post("/sync")
def sync_now() -> dict:
    """Run one sync pass now. Delegates to fitness_sync.tick(); reads never
    depend on it, so a failing tick just returns 0. `providers` lists the
    pull-providers that were polled."""
    count = fitness_sync.tick()
    try:
        providers_list = [p.name for p in pull_providers()]
    except RuntimeError:
        providers_list = []
    return {"synced": count, "providers": providers_list}
```

Note: `auth_router` is intentionally removed from this module — the callback now lives solely on `oauth.auth_router`, and main.py already stopped including `fitness.auth_router` in Step 2, so there is no dangling reference.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_oauth.py -q`
Expected: `13 passed` (the app still imports cleanly — `main.py` no longer references `fitness.auth_router` — and the callback is served exclusively by `oauth.auth_router`).

- [ ] **Step 4: Delete the superseded fitness OAuth test file**

`tests/test_fitness_oauth.py` drove the now-removed `/api/fitness/connect|status|disconnect` routes and `fitness._STATES`; it is fully superseded by `tests/test_oauth.py`. Remove it.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git rm tests/test_fitness_oauth.py`
Expected: `rm 'backend/tests/test_fitness_oauth.py'` — the file is staged for deletion.

- [ ] **Step 5: Run the full suite — fitness data endpoints + shared oauth all green**

Confirm the fitness DATA tests (/today, /week, /workouts, /sync, manual workouts) still pass untouched and no stale reference to `fitness._STATES` / the removed routes lingers.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: whole suite green (no collection errors from the deleted test). Report the pass count.

If any test still imports `from app.routers import fitness` and references `fitness._STATES` or the removed OAuth handlers, it is a stale test that should have moved to test_oauth.py — grep for it: `grep -rn "_STATES\|fitness/connect\|fitness/status\|fitness/disconnect" tests/`. The only matches should be in `tests/test_oauth.py`, and they are EXPECTED there — namely (a) `oauth._STATES` (the moved CSRF state store the OAuth tests reference), and (b) the `/api/fitness/connect|status|disconnect` string literals inside `test_fitness_oauth_routes_are_removed` (Step 1's removal guard), which assert those routes now 404. Those substrings appearing in `test_oauth.py` are the guard doing its job, NOT a leftover. Any match OUTSIDE `test_oauth.py` is a stale test to move.

- [ ] **Step 6: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/routers/fitness.py backend/app/main.py backend/tests/test_oauth.py
git rm backend/tests/test_fitness_oauth.py
git commit -m "$(cat <<'EOF'
M5 refactor: strip OAuth endpoints from routers/fitness.py (now on shared oauth)

fitness.py keeps only /today, /week, /workouts (GET/POST/DELETE), /sync; drops
connect/status/disconnect/callback + _STATES + _FITNESS_REDIRECT + auth_router.
main.py no longer includes fitness.auth_router (the callback lives solely on
oauth.auth_router). Deletes the superseded test_fitness_oauth.py; test_oauth.py
guards that /api/fitness/connect|status|disconnect are gone.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds.


### Task 7: Repoint the frontend fitness connect/status/disconnect calls to the shared /api/oauth routes

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/FitnessScreen.jsx`

**Interfaces:**
- Consumes: api.js fitnessStatus/fitnessConnect/fitnessDisconnect hitting /api/fitness/*; FitnessScreen calling api.fitnessStatus/fitnessConnect/fitnessDisconnect. Backend now serves connect/status/disconnect only under /api/oauth/*.
- Produces: api.js exposes oauthStatus/oauthConnect/oauthDisconnect targeting /api/oauth/*; the fitness data helpers (fitnessToday/fitnessWeek/fitnessWorkouts/fitnessSync/logWorkout/deleteWorkout) stay on /api/fitness/*; FitnessScreen uses the oauth helpers for connect/status/disconnect. No /api/fitness/connect|status|disconnect call remains in the frontend.

- [ ] **Step 1: Repoint api.js: add oauth helpers, drop the three fitness OAuth helpers**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`. Replace the fitness block's connect/status/disconnect helpers with `/api/oauth/*` equivalents; keep every fitness DATA helper unchanged.

Find:
```js
  // Fitness (M4) — WHOOP connection + normalized reads/writes. Reads never
  // touch a live WHOOP call; they come straight from the normalized tables, so
  // the screen works while sync is mid-flight or WHOOP is down. Tokens never
  // cross this boundary — status/today/workouts responses omit them.
  fitnessStatus: () => request('/api/fitness/status'),
  fitnessToday: (isoDate) => request(`/api/fitness/today${isoDate ? `?date=${isoDate}` : ''}`),
  fitnessWeek: (isoDate) => request(`/api/fitness/week${isoDate ? `?date=${isoDate}` : ''}`),
  fitnessWorkouts: (limit) => request(`/api/fitness/workouts${limit != null ? `?limit=${limit}` : ''}`),
  fitnessConnect: (provider) => request(`/api/fitness/connect/${provider}`),
  fitnessDisconnect: (provider) => request(`/api/fitness/disconnect/${provider}`, { method: 'POST' }),
  logWorkout: (w) => request('/api/fitness/workouts', { method: 'POST', body: JSON.stringify(w) }),
  deleteWorkout: (id) => request(`/api/fitness/workouts/${id}`, { method: 'DELETE' }),
  fitnessSync: () => request('/api/fitness/sync', { method: 'POST' }),
```

Replace with:
```js
  // Shared OAuth (M5) — connect/status/disconnect are provider-agnostic and
  // live under /api/oauth/*. The fitness DATA reads/writes below stay on
  // /api/fitness/*. Tokens never cross this boundary.
  oauthStatus: () => request('/api/oauth/status'),
  oauthConnect: (provider) => request(`/api/oauth/connect/${provider}`),
  oauthDisconnect: (provider) => request(`/api/oauth/disconnect/${provider}`, { method: 'POST' }),

  // Fitness (M4) — normalized reads/writes. Reads never touch a live WHOOP
  // call; they come straight from the normalized tables, so the screen works
  // while sync is mid-flight or WHOOP is down.
  fitnessToday: (isoDate) => request(`/api/fitness/today${isoDate ? `?date=${isoDate}` : ''}`),
  fitnessWeek: (isoDate) => request(`/api/fitness/week${isoDate ? `?date=${isoDate}` : ''}`),
  fitnessWorkouts: (limit) => request(`/api/fitness/workouts${limit != null ? `?limit=${limit}` : ''}`),
  logWorkout: (w) => request('/api/fitness/workouts', { method: 'POST', body: JSON.stringify(w) }),
  deleteWorkout: (id) => request(`/api/fitness/workouts/${id}`, { method: 'DELETE' }),
  fitnessSync: () => request('/api/fitness/sync', { method: 'POST' }),
```

- [ ] **Step 2: Repoint FitnessScreen.jsx to the oauth helpers**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/FitnessScreen.jsx`. Swap the three fitness OAuth calls for the oauth helpers; leave the data calls (fitnessToday/fitnessWorkouts/fitnessWeek/fitnessSync) untouched.

Find:
```js
    api.fitnessStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
```
Replace with:
```js
    api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
```

Find:
```js
  const connect = () => {
    api.fitnessConnect('whoop')
      .then((r) => { if (r?.authorize_url) window.location = r.authorize_url })
      .catch(() => {})
  }
  const disconnect = () => {
    api.fitnessDisconnect('whoop')
      .then((s) => { if (s) setStatus(s); refresh() })
      .catch(() => {})
  }
```
Replace with:
```js
  const connect = () => {
    api.oauthConnect('whoop')
      .then((r) => { if (r?.authorize_url) window.location = r.authorize_url })
      .catch(() => {})
  }
  const disconnect = () => {
    api.oauthDisconnect('whoop')
      .then((s) => { if (s) setStatus(s); refresh() })
      .catch(() => {})
  }
```

- [ ] **Step 3: Verify no stale fitness OAuth call remains in the frontend**

Confirm the three removed helpers and any `/api/fitness/connect|status|disconnect` reference are gone from the frontend source (they now live only under oauth). Grep is expected to return no matches.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS && grep -rn "fitnessStatus\|fitnessConnect\|fitnessDisconnect\|fitness/connect\|fitness/status\|fitness/disconnect" frontend/src`
Expected: no output (exit code 1 from grep, no matches) — every OAuth call now goes through `oauthStatus/oauthConnect/oauthDisconnect`. If the frontend has a build/lint step, also run it: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build` and expect it to succeed (skip if there is no build script).

- [ ] **Step 4: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add frontend/src/lib/api.js frontend/src/screens/FitnessScreen.jsx
git commit -m "$(cat <<'EOF'
M5 refactor: repoint frontend fitness connect/status/disconnect to /api/oauth

api.js gains oauthStatus/oauthConnect/oauthDisconnect (/api/oauth/*) and drops
the three fitness OAuth helpers; the fitness data helpers stay on /api/fitness.
FitnessScreen uses the oauth helpers for its connection states.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds.


## Phase: Config + GoogleProvider OAuth half

### Task 8: Config: Google OAuth + email-sync settings

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_config.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_config.py`

**Interfaces:**
- Consumes: The M4 Settings model in app/config.py (whoop_* fields + fitness-sync knobs already present) and the config-defaults test convention from tests/test_fitness_config.py.
- Produces: Five new Settings fields (google_client_id, google_client_secret, google_redirect_uri, email_sync_enabled, email_sync_seconds, email_backfill_count) with spec defaults, asserted independent of any local .env. Downstream phases (GoogleProvider OAuth, email_sync, oauth router) read settings.google_client_id/secret/redirect_uri and the email-sync knobs.

- [ ] **Step 1: Write the failing config-defaults test**

Mirror `tests/test_fitness_config.py` — assert the DECLARED code defaults on `Settings.model_fields` (not on the live `settings` singleton, so a real `backend/.env` cannot break the check) and the annotated types.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_config.py`:

```python
"""M5 config: Google OAuth credentials + email-sync knobs land on Settings with spec defaults."""
from app.config import Settings


def test_google_and_email_sync_defaults():
    # Assert declared code defaults on the model fields, independent of any local
    # backend/.env or env vars — a real Google setup fills client_id/secret in .env,
    # which must NOT break this defaults check (matches test_fitness_config.py).
    d = Settings.model_fields
    assert d["google_client_id"].default == ""
    assert d["google_client_secret"].default == ""
    assert d["google_redirect_uri"].default == "http://localhost:8000/auth/google/callback"
    assert d["email_sync_enabled"].default is True
    assert d["email_sync_seconds"].default == 900
    assert d["email_backfill_count"].default == 50


def test_email_settings_have_the_annotated_types():
    fields = Settings.model_fields
    assert fields["google_client_id"].annotation is str
    assert fields["google_client_secret"].annotation is str
    assert fields["google_redirect_uri"].annotation is str
    assert fields["email_sync_enabled"].annotation is bool
    assert fields["email_sync_seconds"].annotation is int
    assert fields["email_backfill_count"].annotation is int
```

- [ ] **Step 2: Run the test — see it fail (fields absent)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_config.py -q`

Expected: both tests FAIL with `KeyError: 'google_client_id'` (raised inside `Settings.model_fields[...]`) — the fields do not exist on the model yet.

- [ ] **Step 3: Add the six Settings fields**

Append the Google OAuth + email-sync block to the M4 WHOOP/fitness block in `app/config.py`, immediately after the `whoop_backfill_days` line and before the closing `settings = Settings()`. Note Google (unlike WHOOP) permits `http://localhost` redirect URIs, so the default redirect is a real localhost callback.

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py`, replace:

```python
    # Background pull-sync (mirrors reminders_enabled / reminder_tick_seconds).
    fitness_sync_enabled: bool = True
    fitness_sync_seconds: int = 1800            # 30 min
    whoop_backfill_days: int = 30               # first-connect backfill window


settings = Settings()
```

with:

```python
    # Background pull-sync (mirrors reminders_enabled / reminder_tick_seconds).
    fitness_sync_enabled: bool = True
    fitness_sync_seconds: int = 1800            # 30 min
    whoop_backfill_days: int = 30               # first-connect backfill window

    # Google / Gmail (M5). OAuth credentials come from a Google Cloud "Web
    # application" OAuth 2.0 client; the redirect URI must be registered there
    # verbatim. Unlike WHOOP, Google permits http://localhost redirect URIs, so
    # local validation needs no tunnel. Tokens live in provider_accounts, never here.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Background email-sync (mirrors fitness_sync_enabled / fitness_sync_seconds).
    email_sync_enabled: bool = True
    email_sync_seconds: int = 900               # 15 min
    email_backfill_count: int = 50              # first-connect messages.list maxResults


settings = Settings()
```

- [ ] **Step 4: Run the test — see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_config.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Run the full suite and commit**

The config change is additive (new optional fields with defaults) and touches no runtime path, so the whole suite — including the entire M4 fitness suite — must stay green.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: every test passes (the prior green count + the 2 new email-config tests); report the pass count as "X tests passing". If anything is red, stop and fix before committing.

Commit (already on branch `m5-email-triage`):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/config.py backend/tests/test_email_config.py
git commit -m "$(cat <<'EOF'
M5 config: Google OAuth + email-sync settings

Add google_client_id/secret/redirect_uri (localhost callback — Google permits it)
plus email_sync_enabled/seconds and email_backfill_count, with spec defaults
asserted independent of any local .env (mirrors test_fitness_config.py).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```


### Task 9: GoogleProvider OAuth constants + authorize_url + http seam

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`

**Interfaces:**
- Consumes: The new google_client_id/secret/redirect_uri settings from Task 1. The WhoopProvider http-seam pattern (configure(fake_http=...), _transport, _http/_client) and the WHOOP OAuth test harness (FakeResp/FakeHttp) from tests/test_whoop_oauth.py. AuthError from app/providers/base.py.
- Produces: app/providers/google.py with the frozen Google/Gmail constants, GoogleAuthError(AuthError), a GoogleProvider skeleton (__init__/configure/_transport/set_tokens) and a fully-working authorize_url that includes access_type=offline + prompt=consent + all OAuth params. Task 3 adds exchange_code/refresh/revoke; Task 4 adds fetch_profile + hooks + registry.

- [ ] **Step 1: Write the failing authorize_url test**

Model the harness on `tests/test_whoop_oauth.py` (FakeResp/FakeHttp records .posts/.gets; a `_provider()` helper stamps settings then constructs the provider). Assert the authorize URL carries every OAuth param the shared oauth router needs, INCLUDING the two Google-specific params (`access_type=offline`, `prompt=consent`) that guarantee a refresh token.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`:

```python
"""Google OAuth: authorize URL, code exchange, refresh, refresh-failure, revoke, profile sub.

No network: GoogleProvider.configure(fake_http=...) swaps the httpx call layer
(mirrors WhoopProvider). Google field/endpoint names are [confirm-against-live]
(M5 design §3, §13) — verified against the live Google/Gmail API during impl.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.providers.base import Tokens
from app.providers.google import (
    GOOGLE_AUTH_URL,
    GOOGLE_REVOKE_URL,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    GoogleAuthError,
    GoogleProvider,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeHttp:
    """Records POSTs/GETs; replays scripted responses keyed by URL."""

    def __init__(self, responses):
        self.responses = responses         # {url: FakeResp}
        self.posts = []                    # [(url, data)]
        self.gets = []                     # [(url, params)]

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return self.responses.get(url, FakeResp(404, {}))

    def get(self, url, headers=None, params=None):
        self.gets.append((url, params))
        return self.responses.get(url, FakeResp(404, {}))


def _provider():
    settings.google_client_id = "gid"
    settings.google_client_secret = "gsecret"
    settings.google_redirect_uri = "http://localhost:8000/auth/google/callback"
    return GoogleProvider()


def test_authorize_url_has_all_oauth_params_and_offline_consent():
    p = _provider()
    url = p.authorize_url("st8tevalue")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == GOOGLE_AUTH_URL
    q = parse_qs(parsed.query)
    assert q["client_id"] == ["gid"]
    assert q["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == [GOOGLE_SCOPES]
    assert q["state"] == ["st8tevalue"]
    # Google-specific: these two guarantee a refresh_token is issued.
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]


def test_scopes_include_openid_email_profile_and_gmail_readonly():
    # The frozen scope string — read-only Gmail plus identity for the sub.
    assert GOOGLE_SCOPES == (
        "openid email profile https://www.googleapis.com/auth/gmail.readonly"
    )
```

- [ ] **Step 2: Run the test — see it fail (module missing)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_oauth.py -q`

Expected: collection ERROR — `ModuleNotFoundError: No module named 'app.providers.google'` (the import at the top of the test file fails). This is the expected red for a brand-new module.

- [ ] **Step 3: Create app/providers/google.py with constants + authorize_url + http seam**

Hand-rolled over httpx, mirroring `whoop.py` exactly (no google-api-python-client / google-auth). This step lands the constants, `GoogleAuthError`, the seam (`configure`/`_transport`/`set_tokens`), and `authorize_url`. `exchange_code`/`refresh`/`revoke`/`fetch_profile` and the connect/disconnect hooks arrive in Tasks 3-4 — do NOT stub them here beyond what this step defines.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`:

```python
"""GoogleProvider — Google OAuth + Gmail adapter (M5 design §3, §4, §13).

Hand-rolled OAuth + authed REST over httpx (no google-api-python-client /
google-auth; one provider doesn't justify the dependency). All Google/Gmail
field/endpoint names are confined to THIS module — everything past it speaks
the normalized dataclasses in base.py (NormalizedEmail lands in the Gmail
phase; this file owns the OAuth half).

The http layer is a test seam mirroring whoop.py / llm.py: configure(fake_http=obj)
installs a fake exposing .post()/.get(); configure() (fake_http='unset') restores
the lazy real httpx.Client. A token exchange/refresh failure raises
GoogleAuthError (an AuthError subclass), which the email sync engine translates
into status='needs_reauth'.

[confirm-against-live] — the endpoint URLs, the access_type/prompt params, the
GOOGLE_SCOPES string, and the userinfo 'sub' field for provider_user_id are
confirmed against the live Google/Gmail API during implementation (design §13);
their constant NAMES are frozen by the interface contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..config import settings
from .base import AuthError, Tokens

log = logging.getLogger("scuffed_os.google")

# [confirm-against-live] — verified against the live Google/Gmail API during M5 impl.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.readonly"

# Refresh when the access token is within this many seconds of expiring.
_REFRESH_SKEW = timedelta(seconds=60)


class GoogleAuthError(AuthError):
    """Token refresh/exchange failed irrecoverably — caller flips needs_reauth.

    Subclasses providers.base.AuthError (NOT RuntimeError) so the email sync
    engine's `except AuthError` catches it and flips the provider to
    needs_reauth."""


class GoogleProvider:
    name = "google"

    def __init__(self) -> None:
        self._http: object | str = "unset"   # 'unset' → lazy real httpx.Client
        self._client = None
        self._tokens: Tokens | None = None    # injected by the email sync engine

    # ---- http seam (mirrors WhoopProvider) ----
    def configure(self, fake_http: object | str = "unset") -> None:
        """Tests install a fake exposing .post()/.get(); configure() restores real."""
        self._http = fake_http
        self._client = None

    def set_tokens(self, tokens: Tokens | None) -> None:
        """The email sync engine injects the stored (possibly-refreshed) tokens
        here before calling fetch_messages/get_message so authed Gmail calls
        carry a Bearer token."""
        self._tokens = tokens

    def _transport(self):
        if self._http != "unset":
            return self._http
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=20.0)
        return self._client

    # ---- OAuth ----
    def authorize_url(self, state: str) -> str:
        # access_type=offline + prompt=consent guarantee Google issues a
        # refresh_token (without them a re-consent may omit it).
        q = urlencode({
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"{GOOGLE_AUTH_URL}?{q}"
```

- [ ] **Step 4: Run the test — see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_oauth.py -q`

Expected: `2 passed` (`test_authorize_url_has_all_oauth_params_and_offline_consent` and `test_scopes_include_openid_email_profile_and_gmail_readonly`).

- [ ] **Step 5: Run the full suite and commit**

The new module is not yet imported by any runtime path (the registry wiring comes in Task 4), so nothing else can regress.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass; report "X tests passing".

Commit:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/providers/google.py backend/tests/test_google_oauth.py
git commit -m "$(cat <<'EOF'
M5: GoogleProvider OAuth constants + authorize_url + http seam

Frozen Google/Gmail endpoint constants, GoogleAuthError(AuthError), and the
WhoopProvider-style http seam (configure(fake_http=...)/_transport/set_tokens).
authorize_url includes access_type=offline + prompt=consent to guarantee a
refresh token. exchange/refresh/revoke/profile + hooks land in follow-ups.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```


### Task 10: GoogleProvider exchange_code / refresh / revoke

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`

**Interfaces:**
- Consumes: The GoogleProvider skeleton + constants + http seam from Task 2, and the FakeResp/FakeHttp/_provider harness in tests/test_google_oauth.py. The Tokens dataclass and AuthError from app/providers/base.py.
- Produces: Working exchange_code, refresh (keeps the old refresh_token/scopes when Google omits them), and best-effort revoke on GoogleProvider — the full token lifecycle the shared oauth router (Phase 1) and email_sync (Phase 4) depend on. GoogleAuthError is raised on any token-endpoint failure so the sync engine flips needs_reauth.

- [ ] **Step 1: Add the failing token-lifecycle tests**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`. These assert exchange parses tokens and posts the authorization_code grant with client_secret+redirect_uri; refresh rotates near-expiry and keeps the old refresh_token when Google omits it; a token-endpoint 400+ raises GoogleAuthError; a missing refresh_token raises; and revoke posts to the revoke URL and swallows errors.

```python
def test_exchange_code_returns_tokens():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {
            "access_token": "AT", "refresh_token": "RT",
            "expires_in": 3600, "scope": GOOGLE_SCOPES,
        }),
    }))
    tok = p.exchange_code("thecode")
    assert tok.access_token == "AT"
    assert tok.refresh_token == "RT"
    assert tok.scopes == GOOGLE_SCOPES
    assert tok.expires_at is not None and tok.expires_at.tzinfo is not None
    # exchange posted grant_type=authorization_code with the code + redirect_uri + secret
    url, data = p._http.posts[0]
    assert url == GOOGLE_TOKEN_URL
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "thecode"
    assert data["redirect_uri"] == settings.google_redirect_uri
    assert data["client_id"] == "gid"
    assert data["client_secret"] == "gsecret"


def test_refresh_rotates_access_and_keeps_old_refresh_when_omitted():
    p = _provider()
    # Google commonly omits refresh_token on refresh — keep the old one.
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {"access_token": "AT2", "expires_in": 3600}),
    }))
    tok = Tokens("old", "oldRT", None, scopes=GOOGLE_SCOPES)
    fresh = p.refresh(tok)
    assert fresh.access_token == "AT2"
    assert fresh.refresh_token == "oldRT"      # preserved
    assert fresh.scopes == GOOGLE_SCOPES        # preserved
    url, data = p._http.posts[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "oldRT"
    assert data["client_id"] == "gid"
    assert data["client_secret"] == "gsecret"


def test_refresh_uses_new_refresh_token_when_google_returns_one():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {
            "access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600,
        }),
    }))
    fresh = p.refresh(Tokens("old", "oldRT", None))
    assert fresh.refresh_token == "RT2"


def test_refresh_failure_raises_google_auth_error():
    p = _provider()
    p.configure(fake_http=FakeHttp({GOOGLE_TOKEN_URL: FakeResp(400, {})}))
    with pytest.raises(GoogleAuthError):
        p.refresh(Tokens("old", "oldRT", None))


def test_refresh_without_refresh_token_raises():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))
    with pytest.raises(GoogleAuthError):
        p.refresh(Tokens("old", None, None))


def test_revoke_posts_to_revoke_url():
    p = _provider()
    p.configure(fake_http=FakeHttp({GOOGLE_REVOKE_URL: FakeResp(200, {})}))
    p.revoke(Tokens("AT", "RT", None))
    url, data = p._http.posts[0]
    assert url == GOOGLE_REVOKE_URL
    assert data["token"] == "AT"


def test_revoke_swallows_errors():
    """Disconnect must delete local data even if remote revoke fails (design §3/§7)."""
    p = _provider()
    p.configure(fake_http=FakeHttp({GOOGLE_REVOKE_URL: FakeResp(500, {})}))
    p.revoke(Tokens("AT", "RT", None))  # no raise


def test_google_auth_error_is_an_auth_error_subclass():
    """The email sync engine catches `except AuthError`; GoogleAuthError must be one."""
    from app.providers.base import AuthError
    assert issubclass(GoogleAuthError, AuthError)
```

- [ ] **Step 2: Run the new tests — see them fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_oauth.py -q`

Expected: the seven new tests FAIL with `AttributeError: 'GoogleProvider' object has no attribute 'exchange_code'` (and likewise for `refresh`/`revoke`). `test_google_auth_error_is_an_auth_error_subclass` already passes (the class exists), and the two authorize tests from Task 2 still pass.

- [ ] **Step 3: Implement exchange_code / refresh / revoke**

Append to `GoogleProvider` in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, right after `authorize_url`. Follow WhoopProvider's `_token_request`/`exchange_code`/`refresh`/`revoke` shape exactly: `_token_request` raises `GoogleAuthError` on `status_code >= 400`; `refresh` re-raises `GoogleAuthError`, wraps any other exception, and preserves the prior refresh_token/scopes when the response omits them; `revoke` is best-effort and never raises.

Insert after the `authorize_url` method:

```python
    def _token_request(self, data: dict) -> Tokens:
        res = self._transport().post(GOOGLE_TOKEN_URL, data=data)
        if getattr(res, "status_code", 200) >= 400:
            raise GoogleAuthError(
                f"Google token endpoint returned {getattr(res, 'status_code', '?')}"
            )
        payload = res.json()
        expires_at = None
        if payload.get("expires_in") is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(payload["expires_in"])
            )
        return Tokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scopes=payload.get("scope", "") or "",
        )

    def exchange_code(self, code: str) -> Tokens:
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        })

    def refresh(self, tokens: Tokens) -> Tokens:
        if not tokens.refresh_token:
            raise GoogleAuthError("no refresh_token on record")
        try:
            fresh = self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
            })
        except GoogleAuthError:
            raise
        except Exception as exc:  # network etc. — treat as reauth-needed
            raise GoogleAuthError(f"refresh failed: {exc}") from exc
        # Google usually omits refresh_token on refresh — keep the old one.
        if fresh.refresh_token is None:
            fresh.refresh_token = tokens.refresh_token
        if not fresh.scopes:
            fresh.scopes = tokens.scopes
        return fresh

    def _ensure_fresh(self, tokens: Tokens) -> Tokens:
        """Refresh transparently if within the skew of expiry; else pass through."""
        if tokens.expires_at is None:
            return tokens
        if datetime.now(timezone.utc) >= tokens.expires_at - _REFRESH_SKEW:
            return self.refresh(tokens)
        return tokens

    def revoke(self, tokens: Tokens) -> None:
        """Best-effort remote revoke; disconnect deletes local data regardless."""
        try:
            self._transport().post(
                GOOGLE_REVOKE_URL,
                data={"token": tokens.access_token},
            )
        except Exception as exc:
            log.warning("Google revoke failed (continuing): %s", exc)
```

- [ ] **Step 4: Run the tests — see them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_oauth.py -q`

Expected: `9 passed` (2 authorize tests from Task 2 + 7 lifecycle tests).

- [ ] **Step 5: Run the full suite and commit**

Still no runtime wiring, so nothing else is touched.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass; report "X tests passing".

Commit:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/providers/google.py backend/tests/test_google_oauth.py
git commit -m "$(cat <<'EOF'
M5: GoogleProvider token lifecycle (exchange/refresh/revoke)

exchange_code posts the authorization_code grant with client_secret+redirect_uri;
refresh rotates the access token and preserves the prior refresh_token/scopes
when Google omits them; token-endpoint failures raise GoogleAuthError (AuthError
subclass → sync flips needs_reauth); revoke is best-effort and never raises.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```


### Task 11: GoogleProvider fetch_profile (sub) + connect/disconnect hooks + Gmail stubs + registry

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/__init__.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`

**Interfaces:**
- Consumes: The GoogleProvider token lifecycle from Task 3 and the FakeResp/FakeHttp/_provider harness. GOOGLE_USERINFO_URL from Task 2. The providers registry (_build_real/all_providers/get) in app/providers/__init__.py, and the registry seam tests' tolerance pattern from tests/test_provider_registry.py (importlib.util.find_spec guard).
- Produces: fetch_profile returning the Google 'sub' for provider_user_id (best-effort None on failure); the three OAuthProvider hooks success_redirect/on_connected/on_disconnect (lazy imports of email_sync + store.delete_email_data — tolerant of those modules not existing mid-plan); fetch_messages/get_message STUBS ([]/"") the Gmail phase fills in; and GoogleProvider registered in the real registry alongside WhoopProvider. NOTE: `_build_real()` is rewritten by the Phase-1 spine (Task 3) to already append GoogleProvider, so Step 4 is verify-first (only edit if Phase 1 has not landed). After this, providers.get('google') resolves and the shared oauth router (Phase 1) can drive a full Google connect.

- [ ] **Step 1: Add the failing profile/hooks/stub/registry tests**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_oauth.py`. These assert: fetch_profile returns the stringified `sub` from the userinfo endpoint and returns None best-effort on failure; success_redirect is the frozen email screen path; the Gmail methods exist as stubs returning `[]`/`""`; and the real registry now includes `google` (guarded by find_spec so it is robust if the module were absent, matching test_provider_registry.py's pattern). The registry test brackets `providers.configure()` in try/finally so the conftest's `providers.configure([])` teardown is respected.

```python
def test_fetch_profile_returns_google_sub_as_provider_user_id():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_USERINFO_URL: FakeResp(200, {"sub": "108124972", "email": "a@b.com"}),
    }))
    uid = p.fetch_profile(Tokens("AT", "RT", None))
    assert uid == "108124972"                     # stringified Google sub
    assert p._http.gets[0][0] == GOOGLE_USERINFO_URL


def test_fetch_profile_failure_returns_none():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))            # 404 default → best-effort None
    assert p.fetch_profile(Tokens("AT", "RT", None)) is None


def test_success_redirect_targets_the_email_screen():
    assert GoogleProvider().success_redirect() == "/?screen=email&connected=google"


def test_gmail_methods_are_stubs_this_phase():
    # fetch_messages/get_message are filled in the Gmail phase; here they are
    # inert so the provider satisfies EmailProvider without doing network I/O.
    p = _provider()
    p.configure(fake_http=FakeHttp({}))
    assert p.fetch_messages(None) == []
    assert p.get_message("anyid") == ""


def test_name_and_no_kind_attr():
    p = GoogleProvider()
    assert p.name == "google"
    # No `kind` → naturally excluded from pull_providers() (fitness sync).
    assert getattr(p, "kind", None) is None


def test_real_registry_includes_google():
    import importlib.util

    from app import providers
    providers.configure()  # real registry
    try:
        if importlib.util.find_spec("app.providers.google") is None:
            return  # module not authored yet (defensive; it exists in this phase)
        names = [pr.name for pr in providers.all_providers()]
        assert "google" in names
        assert providers.get("google") is not None
        assert providers.get("google").name == "google"
        # google has no `kind`, so it is NOT a pull (fitness) provider.
        assert "google" not in [pr.name for pr in providers.pull_providers()]
    finally:
        providers.configure([])  # restore the conftest test default (no external services)
```

- [ ] **Step 2: Run the new tests — see them fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_oauth.py -q`

Expected: `test_fetch_profile_*`, `test_gmail_methods_are_stubs_this_phase` FAIL with `AttributeError` (methods absent); `test_real_registry_includes_google` FAILS its `assert "google" in names` (the registry still builds only `[WhoopProvider()]`). `test_success_redirect_*` and `test_name_and_no_kind_attr` FAIL on the missing `success_redirect` / pass on name respectively. The Task 2/3 tests still pass.

- [ ] **Step 3: Add fetch_profile, success_redirect, hooks, and Gmail stubs to GoogleProvider**

Append to `GoogleProvider` in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`, after `revoke`. `fetch_profile` GETs the userinfo endpoint and returns the stringified `sub` (best-effort None), mirroring WhoopProvider.fetch_profile. The hooks import `email_sync` / the store lazily so this module never hard-depends on the parallel Gmail-sync / store phases (an ImportError/AttributeError from a not-yet-authored module is swallowed and logged — the connect/disconnect still succeeds). `fetch_messages`/`get_message` are inert stubs the Gmail phase replaces.

Insert after the `revoke` method:

```python
    def fetch_profile(self, tokens: Tokens) -> str | None:
        """GET the Google userinfo endpoint and return the 'sub' (provider_user_id).

        Called by the shared OAuth callback right after exchange_code so the
        account's provider_user_id is populated. Best-effort: a failure returns
        None rather than blocking the connect. The 'sub' field is [confirm-against-live]."""
        try:
            res = self._transport().get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                params=None,
            )
            if getattr(res, "status_code", 200) >= 400:
                log.warning("Google userinfo returned %s", getattr(res, "status_code", "?"))
                return None
            body = res.json() or {}
            sub = body.get("sub")
            return str(sub) if sub is not None else None
        except Exception as exc:
            log.warning("Google userinfo fetch failed (continuing): %s", exc)
            return None

    # ---- OAuthProvider connect/disconnect hooks ----
    def success_redirect(self) -> str:
        return "/?screen=email&connected=google"

    def on_connected(self) -> None:
        """Post-connect hook (called by the shared callback AFTER tokens persist):
        kick an immediate first-sync backfill. Imported lazily so this module
        does not hard-depend on the Gmail-sync phase; a not-yet-authored
        email_sync is swallowed (the connect still succeeds)."""
        try:
            from .. import email_sync

            email_sync.tick()
        except Exception as exc:  # noqa: BLE001 — first-sync is best-effort
            log.warning("Google on_connected sync skipped: %s", exc)

    def on_disconnect(self) -> None:
        """Disconnect hook (called by the shared disconnect AFTER best-effort
        revoke): delete this provider's emails. Imported lazily; a store without
        delete_email_data yet (mid-plan) is swallowed."""
        try:
            from ..store import store

            store.delete_email_data(self.name)
        except Exception as exc:  # noqa: BLE001 — data deletion is idempotent/best-effort here
            log.warning("Google on_disconnect email delete skipped: %s", exc)

    # ---- Gmail (STUBS — filled in the Gmail-fetch phase) ----
    def fetch_messages(self, since):
        """[stub] Inbox messages → list[NormalizedEmail]. Filled in the Gmail phase."""
        return []

    def get_message(self, source_id: str) -> str:
        """[stub] Full plain-text body on demand. Filled in the Gmail phase."""
        return ""
```

- [ ] **Step 4: Ensure `_build_real()` registers GoogleProvider (verify-not-edit if Phase 1 landed)**

`_build_real()` is rewritten by the Phase-1 spine (Task 3), which retypes the registry to `OAuthProvider` AND already makes `_build_real` lazily append `GoogleProvider` alongside `WhoopProvider` (tolerating an ImportError so the registry degrades to whatever is importable mid-plan). So this step is **verify-first**, not a blind Edit — the two tasks converge on the same GoogleProvider-tolerant `_build_real`, but they start from different text (Task 3 has already replaced the original `WhoopProvider`-only form the Edit below anchors on).

First inspect the current `_build_real()`:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && grep -n -A16 "def _build_real" app/providers/__init__.py
```

- **If it already appends `GoogleProvider` (Phase 1 / Task 3 has landed — the intended ordering):** do NOTHING here — the registry already builds `[WhoopProvider(), GoogleProvider()]`. Leave the module's type hints exactly as Phase 1 set them (`OAuthProvider`). Skip straight to Step 5. (The `test_real_registry_includes_google` test from Step 1 already passes.)
- **If it still builds `WhoopProvider`-only (Phase 1 not merged yet):** apply the edit below. Leave the module's `FitnessProvider`-typed hints as-is — Phase 1 retypes them to `OAuthProvider` when it merges; this fallback only extends the built list, keeping the change conflict-free with Phase 1.

Replace:

```python
def _build_real() -> list[FitnessProvider]:
    global _real
    if _real is None:
        try:
            from .whoop import WhoopProvider
        except ImportError:
            return []  # WhoopProvider not present yet (mid-plan); empty registry.
        _real = [WhoopProvider()]
    return _real
```

with:

```python
def _build_real() -> list[FitnessProvider]:
    global _real
    if _real is None:
        built: list[FitnessProvider] = []
        try:
            from .whoop import WhoopProvider

            built.append(WhoopProvider())
        except ImportError:
            pass  # WhoopProvider not present yet (mid-plan); skip it.
        try:
            from .google import GoogleProvider

            built.append(GoogleProvider())
        except ImportError:
            pass  # GoogleProvider not present yet (mid-plan); skip it.
        _real = built
    return _real
```

- [ ] **Step 5: Run the tests — see them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_oauth.py tests/test_provider_registry.py -q`

Expected: all pass. `test_google_oauth.py` is now fully green (authorize + lifecycle + profile + hooks + stubs + registry), and `test_provider_registry.py` stays green — its `test_configure_restores_the_real_registry` uses `providers.get('whoop')` which still resolves, and the empty-fake-list / fake-list tests are unaffected by the extra real provider (they swap the whole registry).

- [ ] **Step 6: Run the full suite and commit**

GoogleProvider is now in the real registry, so the whole suite (including the M4 fitness suite and the assistant/registry tests) must be re-run to prove no regression — the conftest's `providers.configure([])` still fully disables external providers in every test, so no test reaches Google.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass; report "X tests passing". In particular the entire M4 fitness suite (test_fitness_*.py, test_whoop_*.py, test_provider_registry.py) stays green.

Commit:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git add backend/app/providers/google.py backend/app/providers/__init__.py backend/tests/test_google_oauth.py
git commit -m "$(cat <<'EOF'
M5: GoogleProvider profile sub + connect/disconnect hooks + registry

fetch_profile returns the Google 'sub' (userinfo) for provider_user_id;
success_redirect targets the email screen; on_connected/on_disconnect lazily
drive email_sync.tick()/store.delete_email_data (tolerant of the parallel
Gmail-sync + store phases). fetch_messages/get_message are inert stubs the
Gmail phase fills. GoogleProvider now registers alongside WhoopProvider.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```


## Phase: emails model + migration + store

### Task 12: Task D1 — consume the NormalizedEmail dataclass on the provider seam

> **NOTE (duplication guard):** `NormalizedEmail` is DEFINED once, by the Phase-1 spine (Task 1's `base.py` rewrite — see Interface Contract §A). This data-phase task only **consumes** it (imports it for the store layer) and locks it with a test. Do NOT re-add the dataclass here: if Phase 1 has landed (the intended ordering), a second definition would shadow the first and churn `base.py`; if a parallel author reaches this task before Phase 1 merges, add the dataclass defensively (Step 3), otherwise skip the add and keep only the test.

**Files:**
- Consume (import only; do NOT re-define `NormalizedEmail`): `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py`

**Interfaces:**
- Consumes: The `NormalizedEmail` dataclass added by the Phase-1 spine (Task 1) to `app/providers/base.py` (alongside Tokens, NormalizedSnapshot, NormalizedWorkout).
- Produces: A test that locks `NormalizedEmail`'s frozen field set/defaults so the store's `upsert_email` can rely on `from app.providers.base import NormalizedEmail`. Body is NEVER a durable field; body_excerpt is triage-transit-only (default ''). This task adds NO new definition when Phase 1 is present — it only imports/consumes.

- [ ] **Step 1: Write the test that locks NormalizedEmail's shape**

The store layer consumes a normalized, vendor-neutral email dataclass the same way M4 has NormalizedSnapshot / NormalizedWorkout. `NormalizedEmail` is defined by the Phase-1 spine (Task 1); this test locks its frozen fields so the data layer can import it safely. Add a new test file.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py`:

```python
"""The M5 email data layer: the NormalizedEmail seam + the emails table."""
from dataclasses import fields
from datetime import datetime, timezone

from app.providers.base import NormalizedEmail

UTC = timezone.utc


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

- [ ] **Step 2: Run the test**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_models.py -q`

Expected — depends on whether the Phase-1 spine (Task 1) has landed:
- **Phase 1 already merged (intended ordering):** the test PASSES immediately — `NormalizedEmail` is already defined in `base.py` by Task 1. Skip Step 3 entirely (the dataclass is present); go to Step 5.
- **Phase 1 not yet merged (a parallel author reached this task first):** collection/import error — `ImportError: cannot import name 'NormalizedEmail' from 'app.providers.base'`. This is the only case in which Step 3 runs.

- [ ] **Step 3: (ONLY if Phase 1 has not landed) defensively add the NormalizedEmail dataclass to base.py**

Skip this step if Step 2 already passed — `NormalizedEmail` is Phase 1's single definition (Interface Contract §A / Task 1) and re-adding it would create a duplicate that shadows the first. Run this step ONLY when Step 2 failed on the missing import (Phase 1 not merged yet). In that case, add the dataclass immediately after `NormalizedWorkout` in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/base.py`. It reuses the module's existing `dataclass` / `field` / `datetime` imports (already imported at the top). Insert this block right after the `NormalizedWorkout` class (which ends at the `max_hr: int | None = None` line, before the `@runtime_checkable` `FitnessProvider` Protocol):

```python
@dataclass
class NormalizedEmail:
    """Vendor-neutral email shape the store persists. NO body is stored durably:
    the ~2 KB ``body_excerpt`` is triage-transit only (fed to the LLM, then
    dropped) and the full body is fetched on demand via EmailProvider.get_message.
    """

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

Do NOT touch the `FitnessProvider` Protocol or `AuthError` — the protocol split (OAuthProvider/EmailProvider) is Phase 1's job; this fallback only lands the dataclass the data layer imports (and Phase 1 will converge on the identical definition when it merges).

- [ ] **Step 4: Run the test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_models.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit**

Add the test file, and `base.py` only if Step 3's defensive fallback actually modified it (with Phase 1 landed, `base.py` is unchanged and `git add` is a harmless no-op):
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/providers/base.py backend/tests/test_email_models.py && git commit -m "M5 data: lock the NormalizedEmail seam for the store layer

NormalizedEmail is defined by the Phase-1 spine (Task 1). This task consumes it
and adds test_email_models.py to lock its frozen fields; base.py is only touched
if Phase 1 has not merged yet (defensive add).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-triage` (verify with `git branch --show-current` → `m5-email-triage`).


### Task 13: Task D2 — emails SQLAlchemy model

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py`

**Interfaces:**
- Consumes: The models.py Base/JSONField/utcnow scaffolding and the Workout table style; Base.metadata auto-registers the new table for conftest's create_all.
- Produces: An `Email(Base)` ORM model (table `emails`) with a `(owner, source, source_id)` unique constraint and NO body column — the durable email row the store reads/writes.

- [ ] **Step 1: Write the failing model test**

The `emails` table must exist with the frozen columns, no `body`, and enforce uniqueness on `(owner, source, source_id)`. Append these tests to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_models.py` (after the `test_normalized_email_fields_and_defaults` test). Add the imports at the top of the file too.

Add to the existing imports block at the top of the file:

```python
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import Email
from app.store import store
```

Append these test functions:

```python
def test_emails_table_and_columns_exist():
    with store._session() as s:
        insp = inspect(s.get_bind())
        assert "emails" in set(insp.get_table_names())
        cols = {c["name"] for c in insp.get_columns("emails")}
        assert {
            "owner", "source", "source_id", "thread_id", "from_name",
            "from_email", "subject", "snippet", "received_at", "unread",
            "category", "summary_json", "triaged_at", "created_at", "updated_at",
        } <= cols
        # Privacy rule: bodies are never persisted.
        assert "body" not in cols


def test_email_owner_source_source_id_is_unique():
    received = datetime(2026, 6, 30, 15, 24, tzinfo=UTC)
    with store._session() as s, s.begin():
        s.add(Email(owner="me", source="google", source_id="g-1",
                    subject="Hi", received_at=received))
    # Same (owner, source, source_id) collides — synced rows upsert idempotently.
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(Email(owner="me", source="google", source_id="g-1",
                        subject="Hi again", received_at=received))
    # A different source_id is allowed.
    with store._session() as s, s.begin():
        s.add(Email(owner="me", source="google", source_id="g-2",
                    subject="Second", received_at=received))
    with store._session() as s:
        rows = s.scalars(select(Email)).all()
        assert len(rows) == 2


def test_email_column_defaults():
    with store._session() as s, s.begin():
        row = Email(owner="me", source="google", source_id="g-3",
                    subject="Defaults",
                    received_at=datetime(2026, 6, 30, 9, 0, tzinfo=UTC))
        s.add(row)
        s.flush()
        assert row.thread_id == ""
        assert row.from_name == ""
        assert row.from_email == ""
        assert row.snippet == ""
        assert row.unread is False
        assert row.category is None
        assert row.summary_json is None
        assert row.triaged_at is None
        assert row.created_at is not None
        assert row.updated_at is not None
```

- [ ] **Step 2: Run the test and see it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_models.py -q`

Expected: import error — `ImportError: cannot import name 'Email' from 'app.models'`.

- [ ] **Step 3: Add the Email model to models.py**

Append the `Email` class to the END of `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/models.py` (after the `Workout` class). It reuses the module's existing imports (`String`, `Text`, `DateTime`, `UniqueConstraint`, `JSONField`, `utcnow`, `Mapped`, `mapped_column`, `datetime`). Add:

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

- [ ] **Step 4: Run the test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_models.py -q`

Expected: `4 passed` (the D1 dataclass test plus the three model tests).

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/models.py backend/tests/test_email_models.py && git commit -m "M5 data: emails table model (no body column)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-triage`.


### Task 14: Task D3 — 0005_email migration chained onto 0004

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/alembic/versions/0005_email.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: The Email model (D2) and the 0004 fitness migration (revision '0004' — confirmed by reading alembic/versions/0004_fitness.py). The migration chain and the model must not drift (compare_metadata on Postgres).
- Produces: Migration `0005_email` (revision '0005', down_revision '0004') that builds the `emails` table so the production alembic-upgrade path matches the models; the migration test now asserts `emails` is in the built schema.

- [ ] **Step 1: Extend the migration test to require the emails table**

The migration chain must build every table the models declare, including `emails`. Update `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_migrations.py`.

Add `"emails"` to the `ALL_TABLES` set. Change:

```python
ALL_TABLES = {
    "tasks", "memories", "conversations", "conversation_messages",
    "task_reminders", "events", "habits", "habit_completions",
    "meals", "water_days", "nutrition_targets",
    "provider_accounts", "daily_snapshots", "workouts",
}
```

to:

```python
ALL_TABLES = {
    "tasks", "memories", "conversations", "conversation_messages",
    "task_reminders", "events", "habits", "habit_completions",
    "meals", "water_days", "nutrition_targets",
    "provider_accounts", "daily_snapshots", "workouts", "emails",
}
```

Also add a focused assertion inside `test_upgrade_head_builds_full_schema`, right before its final `engine.dispose()` line:

```python
    email_cols = {c["name"] for c in inspect(engine).get_columns("emails")}
    assert {"owner", "source", "source_id", "thread_id", "from_name",
            "from_email", "subject", "snippet", "received_at", "unread",
            "category", "summary_json", "triaged_at"} <= email_cols
    assert "body" not in email_cols  # privacy: bodies never persisted
```

- [ ] **Step 2: Run the migration test and see it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_migrations.py -q`

Expected: `test_upgrade_head_builds_full_schema` and `test_downgrade_base_removes_everything` FAIL — the alembic head builds the schema WITHOUT an `emails` table (no 0005 migration yet), so `ALL_TABLES <= tables` is False and the new `get_columns("emails")` call raises `NoSuchTableError`.

- [ ] **Step 3: Create the 0005_email migration**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/alembic/versions/0005_email.py`, mirroring `0004_fitness.py`'s style (JSONField variant, Python-side has no server defaults, explicit indexes). down_revision chains onto '0004' (confirmed from 0004_fitness.py's `revision = "0004"`).

```python
"""Email domain (M5): the synced Gmail inbox.

- emails: one row per (owner, source, source_id) = ('google', gmail message id);
  re-sync upserts idempotently. Triage output (category + summary_json) is
  written on sync. NO body column — message bodies are privacy-sensitive and
  fetched on demand, never stored.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("from_name", sa.Text(), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=True),
        sa.Column("summary_json", JSONField, nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_emails_owner_source_source_id"),
    )
    op.create_index(op.f("ix_emails_owner"), "emails", ["owner"])
    op.create_index(op.f("ix_emails_source"), "emails", ["source"])
    op.create_index(op.f("ix_emails_source_id"), "emails", ["source_id"])
    op.create_index(op.f("ix_emails_received_at"), "emails", ["received_at"])


def downgrade() -> None:
    op.drop_table("emails")
```

Note: the columns are declared `nullable=False` for the String/Text/Boolean fields that carry a Python-side default on the model (thread_id, from_name, from_email, subject, snippet, unread) — matching how 0004 declares `scopes`/`meta`/`status` NOT NULL against Python-side defaults. `category`, `summary_json`, `triaged_at` are nullable (the untriaged state). This keeps `compare_metadata` clean on Postgres against the `Email` model.

- [ ] **Step 4: Run the migration test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_migrations.py -q`

Expected: all migration tests pass (`test_migrations_build_models_schema_on_postgres` is skipped without a Postgres URL — that's the pre-existing 1 skip). The SQLite `upgrade head` now builds `emails` and `downgrade base` removes it.

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/alembic/versions/0005_email.py backend/tests/test_migrations.py && git commit -m "M5 data: 0005_email migration (emails table, chains onto 0004)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-triage`.


### Task 15: Task D4 — email_when_display helper

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/display.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_display.py`

**Interfaces:**
- Consumes: The display.py derive-on-read helpers (_local_clock, _aware).
- Produces: `email_when_display(received_at, now=None) -> str` — the inbox row's relative timestamp ('8:24am' today / 'Yesterday' / 'Jun 5'), used by store._email_dict's derived `when` field.

- [ ] **Step 1: Write the failing display test**

The inbox rows show a compact relative timestamp derived on read (never stored), matching the contract's examples: today shows the clock time, yesterday shows 'Yesterday', older shows the month/day. Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_display.py`.

First ensure the import line at the top of test_display.py includes `email_when_display`. If test_display.py imports helpers individually, add `email_when_display` to that import; otherwise add a fresh import line near the top of the file:

```python
from app.display import email_when_display
```

Append these tests:

```python
def test_email_when_today_shows_clock():
    now = datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)
    # Same local calendar day -> clock time (e.g. '8:24am' in local tz).
    out = email_when_display(received, now)
    assert out == _local_clock_expected(received)


def test_email_when_yesterday():
    now = datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    assert email_when_display(received, now) == "Yesterday"


def test_email_when_older_shows_month_day():
    now = datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)
    # Older than yesterday -> 'Mon D' in local tz.
    expected = received.astimezone().strftime("%b %-d")
    assert email_when_display(received, now) == expected


def _local_clock_expected(dt):
    from app.display import clock
    return clock(dt)
```

(The `datetime`/`timezone` imports already exist at the top of test_display.py; if not, add `from datetime import datetime, timezone`.)

- [ ] **Step 2: Run the display test and see it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_display.py -q`

Expected: `ImportError: cannot import name 'email_when_display' from 'app.display'`.

- [ ] **Step 3: Add email_when_display to display.py**

Append to the END of `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/display.py`. It reuses the module's `_aware`, `_local_clock`, `timedelta`, `timezone`, `datetime` (all already imported/defined at the top). Compare on LOCAL calendar days so 'today'/'yesterday' match the user's clock, mirroring `event_when_display`'s local-day logic.

```python
def email_when_display(received_at: datetime, now: datetime | None = None) -> str:
    """The inbox row's compact relative timestamp: today shows the clock
    time ('8:24am'), yesterday shows 'Yesterday', older shows 'Jun 5'.
    Derived on read from the stored aware-UTC received_at (never stored)."""
    now = _aware(now) if now else datetime.now(timezone.utc)
    received = _aware(received_at)
    today = now.astimezone().date()
    day = received.astimezone().date()
    if day == today:
        return _local_clock(received)
    if day == today - timedelta(days=1):
        return "Yesterday"
    return received.astimezone().strftime("%b %-d")
```

- [ ] **Step 4: Run the display test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_display.py -q`

Expected: all display tests pass (the three new email-when tests plus the existing ones).

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/display.py backend/tests/test_display.py && git commit -m "M5 data: email_when_display derive-on-read helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-triage`.


### Task 16: Task D5 — store.upsert_email + email_exists + _email_dict

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`

**Interfaces:**
- Consumes: The Email model (D2), NormalizedEmail (D1), email_when_display (D4), and the store facade patterns (_retry_integrity, _to_utc, aware_utc, settings.owner, the _*_dict builders).
- Produces: `store.upsert_email(email, category, summary) -> dict` (get-or-create by (owner, source, source_id); triage fields written only when category is not None), `store.email_exists(source, source_id) -> bool`, and the `_email_dict` builder with the derived `when` field. These are the write + idempotency-check seam the sync engine consumes.

- [ ] **Step 1: Write the failing store test for upsert + exists**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`:

```python
"""Store-layer email logic (M5): upsert idempotency, inbox grouping, detail, delete.

All against SQLite via the fresh_db fixture — no network, no providers, no LLM.
"""
from datetime import datetime, timezone

from app.providers.base import NormalizedEmail
from app.store import store

UTC = timezone.utc


def _email(**kw):
    base = dict(
        source="google", source_id="g-1", thread_id="t-1",
        from_name="Priya Rao", from_email="priya@example.com",
        subject="Lighthouse deadline", snippet="About the moved date",
        received_at=datetime(2026, 6, 30, 15, 24, tzinfo=UTC),
        unread=True, body_excerpt="Can you confirm the 30th works?",
    )
    base.update(kw)
    return NormalizedEmail(**base)


def test_upsert_email_creates_row_with_triage():
    out = store.upsert_email(_email(), category="needs_reply",
                             summary=["Confirm the 30th", "Loop in design"])
    assert out["source"] == "google"
    assert out["source_id"] == "g-1"
    assert out["thread_id"] == "t-1"
    assert out["from_name"] == "Priya Rao"
    assert out["from_email"] == "priya@example.com"
    assert out["subject"] == "Lighthouse deadline"
    assert out["snippet"] == "About the moved date"
    assert out["unread"] is True
    assert out["category"] == "needs_reply"
    assert out["summary"] == ["Confirm the 30th", "Loop in design"]
    assert out["triaged_at"] is not None
    assert out["received_at"] == datetime(2026, 6, 30, 15, 24, tzinfo=UTC)
    # No body ever leaves the store.
    assert "body" not in out
    assert "body_excerpt" not in out
    # Derived display field present.
    assert isinstance(out["when"], str) and out["when"]


def test_upsert_email_is_idempotent_by_source_id():
    store.upsert_email(_email(), category="fyi", summary=["first"])
    again = store.upsert_email(
        _email(subject="Lighthouse deadline (edited)", unread=False),
        category="needs_reply", summary=["second"],
    )
    # Same (owner, source, source_id) -> one row, metadata + triage updated.
    assert store.email_exists("google", "g-1") is True
    assert again["subject"] == "Lighthouse deadline (edited)"
    assert again["unread"] is False
    assert again["category"] == "needs_reply"
    assert again["summary"] == ["second"]
    from sqlalchemy import select
    from app.models import Email
    with store._session() as s:
        assert len(s.scalars(select(Email)).all()) == 1


def test_upsert_email_untriaged_when_category_none():
    # A triage failure passes category=None -> row stored, left untriaged.
    out = store.upsert_email(_email(), category=None, summary=None)
    assert out["category"] is None
    assert out["summary"] == []           # [] not None in the dict
    assert out["triaged_at"] is None
    assert store.email_exists("google", "g-1") is True


def test_upsert_email_none_category_preserves_prior_triage():
    # First pass triages the row.
    store.upsert_email(_email(), category="needs_reply", summary=["reply soon"])
    # A later pass with category=None (triage offline) must NOT clobber the
    # already-good triage — metadata refreshes, triage fields stay.
    out = store.upsert_email(_email(unread=False), category=None, summary=None)
    assert out["unread"] is False              # metadata refreshed
    assert out["category"] == "needs_reply"     # prior triage preserved
    assert out["summary"] == ["reply soon"]
    assert out["triaged_at"] is not None


def test_email_exists_false_when_absent():
    assert store.email_exists("google", "nope") is False
```

- [ ] **Step 2: Run the store test and see it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_store.py -q`

Expected: `AttributeError: 'Store' object has no attribute 'upsert_email'` (and `email_exists`).

- [ ] **Step 3: Add the Email import, _EMAIL_FIELDS, _email_dict, upsert_email, email_exists to store.py**

Three edits in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`.

(1) Add `Email` to the models import block (the `from .models import (...)` list, keep alphabetical-ish next to `Event`) and `NormalizedEmail` to the providers.base import. Change:

```python
from .models import (
    Conversation,
    ConversationMessage,
    DailySnapshot,
    Event,
```
to:
```python
from .models import (
    Conversation,
    ConversationMessage,
    DailySnapshot,
    Email,
    Event,
```
and change:
```python
from .providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
```
to:
```python
from .providers.base import NormalizedEmail, NormalizedSnapshot, NormalizedWorkout, Tokens
```
and add `email_when_display` to the `from .display import (...)` block (insert alphabetically after `clock`):
```python
from .display import (
    aware_utc,
    clock,
    email_when_display,
    event_when_display,
    meal_time_display,
    relative_when,
    reminder_label,
    task_due_display,
)
```

(2) Add the `_EMAIL_FIELDS` constant next to `_WORKOUT_FIELDS` (after the `_WORKOUT_FIELDS = {...}` block near line 95). These are the metadata columns upsert writes every pass (NOT the triage columns, which are conditional):

```python
_EMAIL_FIELDS = (
    "thread_id", "from_name", "from_email", "subject", "snippet",
    "received_at", "unread",
)
```

(3) Add the `_email_dict` builder as a module-level function right after `_workout_dict` (after its `return {...}` block, before `_apply_task_patch`):

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

(4) Add the store methods. Insert a new `# ---- emails (M5) ----` section right AFTER the `delete_provider_data` method (which ends with `return existed`) and BEFORE the `# ---- snapshots (derive-on-read) ----` comment:

```python
    # ---- emails (M5) ----
    def _email_row(self, s: Session, source: str, source_id: str) -> Email | None:
        from .config import settings

        return s.scalars(
            select(Email)
            .where(Email.owner == settings.owner)
            .where(Email.source == source)
            .where(Email.source_id == source_id)
        ).first()

    def email_exists(self, source: str, source_id: str) -> bool:
        """Sync skips messages.get + triage for ids already stored (idempotency)."""
        with self._session() as s:
            return self._email_row(s, source, source_id) is not None

    @_retry_integrity
    def upsert_email(
        self,
        email: NormalizedEmail,
        category: str | None,
        summary: list[str] | None,
    ) -> dict:
        """Get-or-create by (owner, source, source_id); writes metadata every
        pass. Triage fields (category/summary_json/triaged_at) are written
        ONLY when category is not None — a triage failure passes category=None,
        leaving the row untriaged for retry (and never clobbering prior good
        triage). Body is never persisted."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._email_row(s, email.source, email.source_id)
            if row is None:
                row = Email(
                    owner=settings.owner,
                    source=email.source,
                    source_id=email.source_id,
                )
                s.add(row)
            for field in _EMAIL_FIELDS:
                value = getattr(email, field)
                if field == "received_at":
                    value = _to_utc(value)
                setattr(row, field, value)
            if category is not None:
                row.category = category
                row.summary_json = summary
                row.triaged_at = utcnow()
            s.flush()
            return _email_dict(row)
```

- [ ] **Step 4: Run the store test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_store.py -q`

Expected: `5 passed` (the upsert/exists tests). Inbox/detail/delete tests come in D6.

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/store.py backend/tests/test_email_store.py && git commit -m "M5 data: store.upsert_email + email_exists + _email_dict

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-triage`.


### Task 17: Task D6 — store.inbox + get_email + delete_email_data

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`

**Interfaces:**
- Consumes: upsert_email / email_exists / _email_dict (D5) and the store facade patterns.
- Produces: `store.inbox() -> dict` (needs_reply/fyi/untriaged lists sorted received_at desc + needs_reply_count + unread_count), `store.get_email(id) -> dict | None`, and `store.delete_email_data(source) -> bool` (the GoogleProvider.on_disconnect hook — deletes emails where (owner, source)). These are the inbox-read + disconnect seam the email API and provider consume.

- [ ] **Step 1: Write the failing test for inbox / get_email / delete**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_store.py`:

```python
def test_inbox_groups_by_category_and_counts():
    # Two needs_reply (one unread), one fyi (unread), one untriaged (unread).
    store.upsert_email(
        _email(source_id="nr-1", subject="Reply A", unread=True,
               received_at=datetime(2026, 6, 30, 9, 0, tzinfo=UTC)),
        category="needs_reply", summary=["a"],
    )
    store.upsert_email(
        _email(source_id="nr-2", subject="Reply B", unread=False,
               received_at=datetime(2026, 6, 30, 11, 0, tzinfo=UTC)),
        category="needs_reply", summary=["b"],
    )
    store.upsert_email(
        _email(source_id="fyi-1", subject="FYI", unread=True,
               received_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC)),
        category="fyi", summary=["c"],
    )
    store.upsert_email(
        _email(source_id="un-1", subject="Untriaged", unread=True,
               received_at=datetime(2026, 6, 30, 7, 0, tzinfo=UTC)),
        category=None, summary=None,
    )
    box = store.inbox()
    assert [e["subject"] for e in box["needs_reply"]] == ["Reply B", "Reply A"]  # desc
    assert [e["subject"] for e in box["fyi"]] == ["FYI"]
    assert [e["subject"] for e in box["untriaged"]] == ["Untriaged"]
    assert box["needs_reply_count"] == 2
    assert box["unread_count"] == 3   # nr-1, fyi-1, un-1 unread


def test_inbox_empty_state():
    box = store.inbox()
    assert box == {
        "needs_reply": [], "fyi": [], "untriaged": [],
        "needs_reply_count": 0, "unread_count": 0,
    }


def test_get_email_returns_dict_or_none():
    created = store.upsert_email(_email(source_id="det-1", subject="Detail"),
                                 category="fyi", summary=["x"])
    fetched = store.get_email(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["subject"] == "Detail"
    assert fetched["source_id"] == "det-1"
    assert "body" not in fetched          # store never yields a body
    assert store.get_email(999999) is None


def test_delete_email_data_removes_only_that_source():
    store.upsert_email(_email(source_id="g-1"), category="fyi", summary=["a"])
    store.upsert_email(_email(source_id="g-2"), category="needs_reply", summary=["b"])
    assert store.delete_email_data("google") is True
    box = store.inbox()
    assert box["needs_reply"] == [] and box["fyi"] == [] and box["untriaged"] == []
    # A second delete with nothing left returns False.
    assert store.delete_email_data("google") is False
```

- [ ] **Step 2: Run the test and see it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_store.py -q`

Expected: `AttributeError: 'Store' object has no attribute 'inbox'` (and `get_email` / `delete_email_data`); the five D5 tests still pass.

- [ ] **Step 3: Add inbox / get_email / delete_email_data to store.py**

Append these three methods to the `# ---- emails (M5) ----` section in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/store.py` (right after the `upsert_email` method added in D5, still inside the `Store` class):

```python
    def inbox(self) -> dict:
        """The two-pane inbox: needs_reply / fyi / untriaged lists (each sorted
        received_at desc) + the needs_reply count and the unread count.
        Always served from the emails table — never a live Gmail call."""
        from .config import settings

        with self._session() as s:
            rows = s.scalars(
                select(Email)
                .where(Email.owner == settings.owner)
                .order_by(Email.received_at.desc())
            ).all()
        needs_reply, fyi, untriaged = [], [], []
        unread_count = 0
        for r in rows:
            if r.unread:
                unread_count += 1
            d = _email_dict(r)
            if r.category == "needs_reply":
                needs_reply.append(d)
            elif r.category == "fyi":
                fyi.append(d)
            else:
                untriaged.append(d)
        return {
            "needs_reply": needs_reply,
            "fyi": fyi,
            "untriaged": untriaged,
            "needs_reply_count": len(needs_reply),
            "unread_count": unread_count,
        }

    def get_email(self, email_id: int) -> dict | None:
        with self._session() as s:
            row = s.get(Email, email_id)
            return _email_dict(row) if row is not None else None

    def delete_email_data(self, source: str) -> bool:
        """Disconnect hook (GoogleProvider.on_disconnect): delete emails where
        (owner, source). Returns True iff any row was deleted. Separate from
        delete_provider_data (which owns the provider_accounts row + fitness
        tables); the shared router deletes the account, this deletes the domain
        data."""
        from .config import settings

        deleted = False
        with self._session() as s, s.begin():
            for row in s.scalars(
                select(Email)
                .where(Email.owner == settings.owner)
                .where(Email.source == source)
            ):
                s.delete(row)
                deleted = True
        return deleted
```

- [ ] **Step 4: Run the test and see it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_email_store.py -q`

Expected: `9 passed` (5 from D5 + 4 new).

- [ ] **Step 5: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/store.py backend/tests/test_email_store.py && git commit -m "M5 data: store.inbox + get_email + delete_email_data

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: a commit lands on branch `m5-email-triage`.


### Task 18: Task D7 — full-suite green gate for the data layer

**Files:**
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/`

**Interfaces:**
- Consumes: All D1–D6 changes (base.py, models.py, migration 0005, display.py, store.py) plus the entire existing M4 fitness suite.
- Produces: Verified evidence that the data layer is additive-only: the whole backend suite stays green (M4 fitness DATA + OAUTH tests untouched, new email tests passing), so downstream M5 phases build on a green base.

- [ ] **Step 1: Run the entire backend test suite**

The global constraint requires the FULL suite green, including every M4 fitness test. Run the whole thing.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest`

Expected: `X passed, 1 skipped` with X >= 271 (the pre-M5 baseline was `260 passed, 1 skipped`; D1 adds 1, D2 adds 3, D3 adds 0 new test functions but strengthens 2, D4 adds 3, D5 adds 5, D6 adds 4 → +16 email/display tests, so 276 passed, 1 skipped). ZERO failures. The 1 skip is the Postgres-only migration test (`test_migrations_build_models_schema_on_postgres`, skipped without a Postgres TEST_DATABASE_URL). If any fitness test fails, the data layer regressed a shared module (most likely the store.py import block or display.py) — fix before proceeding; do NOT edit fitness tests.

- [ ] **Step 2: Confirm the M4 fitness suite specifically is untouched and green**

Run the fitness-only slice to prove the guardrail explicitly.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && /Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest tests/test_fitness_store.py tests/test_fitness_models.py tests/test_fitness_oauth.py tests/test_fitness_api.py tests/test_fitness_sync.py tests/test_fitness_tools.py tests/test_whoop_mapping.py tests/test_whoop_oauth.py -q`

Expected: all pass, zero failures — the data layer added only `Email`/`NormalizedEmail`/email store methods/`email_when_display`/migration 0005 and did not alter any fitness code path.


## Phase: Gmail fetch + triage + email_sync

> **PHASE-4 CONFTEST NOTE (shared-file parallelism hazard — read before Tasks 20 & 21):** Both Task 20 (email_triage) and Task 21 (email_sync) edit the SAME shared `backend/tests/conftest.py` `no_external_services` fixture — the import line and the setup/teardown seam calls. Two rules keep this safe:
>
> 1. **Commit each conftest edit together with the module it seams, in the SAME commit.** Task 20 commits `app/email_triage.py` + its conftest edit together; Task 21 commits `app/email_sync.py` + its conftest edit together. A conftest that installs `email_triage.configure(None)` / `email_sync.configure(None)` while the corresponding `app/email_triage`/`app/email_sync` module does not yet exist makes EVERY test error at collection (`ModuleNotFoundError`), not just the new ones. Never land a half-applied conftest.
> 2. **Phase 4's conftest edits are SEQUENTIAL and are NOT safe to run concurrently with a full-suite green-gate in another phase.** Task 21's import edit assumes Task 20's already landed (its "Old" import line is `from app import email_triage, fitness_sync, ...`). Run Task 20 fully (module + conftest committed) before Task 21. A parallel author in another phase who runs the whole suite mid-Phase-4 could see a red collection from this conftest — that is expected transient state, not their regression. (If you want to harden against that, the `configure()` seam calls may be wrapped in `try/except ImportError` so a half-applied conftest never reds unrelated tests — optional.)
>
> The two edits target DIFFERENT, non-overlapping anchor lines within the fixture: Task 20 inserts its setup line right after `fitness_sync.configure(None)` and its teardown right after `fitness_sync.configure("unset")`; Task 21 inserts its setup line right after `email_triage.configure(None)` (Task 20's line) and its teardown right after `email_triage.configure("unset")` (Task 20's line). Because Task 21 anchors on the lines Task 20 just added, the two edits never target the same anchor and cannot conflict — provided the sequential ordering above is respected.

### Task 19: GoogleProvider Gmail fetch — fetch_messages + get_message (headers + snippet + bounded body excerpt, base64url plaintext)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py`

**Interfaces:**
- Consumes: GoogleProvider skeleton from Phase 2 (app/providers/google.py: name='google', __init__ with self._tokens/self._http/self._client, configure(fake_http) http seam, set_tokens, authorize_url/exchange_code/refresh/revoke/fetch_profile, GoogleAuthError(AuthError) subclass, GMAIL_API_BASE constant, _ensure_fresh); NormalizedEmail dataclass in app/providers/base.py from Phase 1; the httpx transport seam pattern copied verbatim from WhoopProvider._transport/_headers.
- Produces: GoogleProvider.fetch_messages(since) -> list[NormalizedEmail] (Gmail messages.list INBOX maxResults=settings.email_backfill_count -> per-id messages.get?format=full -> parsed From/Date/UNREAD-label + base64url-decoded ~2KB plaintext body_excerpt) and GoogleProvider.get_message(source_id) -> str (on-demand full plaintext body). Module-level _decode_b64url/_extract_plaintext/_parse_from/_parse_date/_excerpt helpers. Consumed by Task-2 (email_sync.tick) and by FakeEmailProvider in tests.

- [ ] **Step 1: Add FakeEmailProvider + a fake Gmail HTTP transport to tests/fakes.py**

The email tests need (a) a `FakeEmailProvider` satisfying the new `EmailProvider` protocol for sync/oauth tests, and (b) a scriptable fake httpx transport so we can drive the REAL `GoogleProvider.fetch_messages`/`get_message` code path with canned Gmail JSON (no network). Append both to the existing `tests/fakes.py` (it already imports `NormalizedSnapshot, NormalizedWorkout, Tokens` at the bottom).

Append this block to the END of `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`:

```python
# ---- email provider seam (M5) ---------------------------------------------
from app.providers.base import NormalizedEmail


class _FakeResponse:
    """Minimal httpx.Response stand-in: .status_code + .json()."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeGmailHTTP:
    """Scriptable transport for GoogleProvider.configure(fake_http=...).

    Routes GET by URL substring: '/messages/<id>' returns per-message JSON from
    `messages`; '/messages' (list) returns `{'messages': [{'id': ...}, ...]}`.
    A `status` override (keyed by url substring) forces an error status so the
    provider raises GoogleAuthError. Records every GET so tests can assert the
    label/maxResults query params reached Gmail.
    """

    def __init__(self, messages: dict | None = None, list_ids: list[str] | None = None,
                 status: dict | None = None):
        self.messages = messages or {}          # id -> messages.get JSON
        self.list_ids = list_ids if list_ids is not None else list(self.messages)
        self.status = status or {}               # url-substring -> status_code
        self.gets: list[tuple[str, dict]] = []

    def _status_for(self, url: str) -> int:
        for frag, code in self.status.items():
            if frag in url:
                return code
        return 200

    def get(self, url, headers=None, params=None):
        self.gets.append((url, dict(params or {})))
        code = self._status_for(url)
        if code >= 400:
            return _FakeResponse({}, code)
        # messages.get: '/messages/<id>' (has a segment after '/messages/')
        if "/messages/" in url:
            msg_id = url.rsplit("/messages/", 1)[1]
            return _FakeResponse(self.messages.get(msg_id, {}))
        # messages.list
        return _FakeResponse({"messages": [{"id": i} for i in self.list_ids]})

    def post(self, url, data=None, headers=None):  # exchange/refresh/revoke
        return _FakeResponse({})


def gmail_message(msg_id: str, *, thread_id: str = "t1", from_hdr: str,
                  subject: str, date_hdr: str, snippet: str = "",
                  label_ids: list[str] | None = None, body_text: str = "") -> dict:
    """Build a Gmail messages.get?format=full payload with a text/plain part."""
    import base64

    b64 = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": label_ids or [],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": from_hdr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date_hdr},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": b64}},
                {"mimeType": "text/html", "body": {"data": ""}},
            ],
        },
    }


class FakeEmailProvider:
    """Scriptable EmailProvider stand-in (name='google') — no network.

    Installed via ``providers.configure([FakeEmailProvider(...)])``. Satisfies the
    new EmailProvider protocol so the shared oauth router and email_sync accept it.
    """

    name = "google"

    def __init__(
        self,
        *,
        tokens: Tokens | None = None,
        messages: list[NormalizedEmail] | None = None,
        body: str = "Full body text.",
        raise_auth: bool = False,
    ) -> None:
        self.tokens = tokens or Tokens(
            access_token="g-access", refresh_token="g-refresh", expires_at=None,
            scopes="openid email https://www.googleapis.com/auth/gmail.readonly",
            provider_user_id="google-sub-1",
        )
        self.messages = messages or []
        self.body = body
        self.raise_auth = raise_auth
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []
        self.injected: list[Tokens | None] = []
        self.fetched_since: list = []
        self.fetched_bodies: list[str] = []

    # ---- OAuthProvider ----
    def set_tokens(self, tokens):
        self.injected.append(tokens)

    def authorize_url(self, state: str) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id=fake-google&response_type=code&state={state}"
        )

    def exchange_code(self, code: str) -> Tokens:
        self.exchanged.append(code)
        return self.tokens

    def refresh(self, tokens: Tokens) -> Tokens:
        self.refreshed.append(tokens)
        return self.tokens

    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)

    def fetch_profile(self, tokens: Tokens) -> str | None:
        return "google-sub-1"

    def success_redirect(self) -> str:
        return "/?screen=email&connected=google"

    def on_connected(self) -> None:
        from app import email_sync

        email_sync.tick()

    def on_disconnect(self) -> None:
        from app.store import store

        store.delete_email_data(self.name)

    # ---- EmailProvider ----
    def fetch_messages(self, since):
        from app.providers.google import GoogleAuthError

        if self.raise_auth:
            raise GoogleAuthError("gmail 401")
        self.fetched_since.append(since)
        return list(self.messages)

    def get_message(self, source_id: str) -> str:
        self.fetched_bodies.append(source_id)
        return self.body
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "import tests.fakes as f; f.FakeEmailProvider(); print(f.gmail_message('m1', from_hdr='A <a@x.com>', subject='Hi', date_hdr='Mon, 30 Jun 2026 08:24:00 -0700')['payload']['headers'][0])"`

Expected: prints `{'name': 'From', 'value': 'A <a@x.com>'}` (import succeeds — `NormalizedEmail` resolves from Phase-1 base.py, so the fakes module loads cleanly). Do NOT commit yet — the next step adds a failing test.

- [ ] **Step 2: Write the failing test for GoogleProvider.fetch_messages + get_message**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_google_gmail.py` driving the REAL `GoogleProvider` with the fake Gmail transport (`configure(fake_http=...)`) — asserting the messages.list query, the message-JSON -> NormalizedEmail mapping (From parse, Date -> aware UTC, UNREAD flag, ~2 KB body excerpt truncation), and get_message body decoding + the auth-error path.

```python
"""GoogleProvider Gmail fetch (M5) — real provider, fake httpx transport."""
from datetime import datetime, timezone

import pytest

from app.providers.base import NormalizedEmail
from app.providers.google import GoogleAuthError, GoogleProvider
from app.providers.base import Tokens

from .fakes import FakeGmailHTTP, gmail_message


def _provider(http) -> GoogleProvider:
    p = GoogleProvider()
    p.configure(fake_http=http)
    p.set_tokens(Tokens(access_token="tok", refresh_token="r", expires_at=None))
    return p


def test_fetch_messages_lists_inbox_then_maps_each_message():
    http = FakeGmailHTTP(messages={
        "m1": gmail_message(
            "m1", thread_id="th1",
            from_hdr="Priya Rao <priya@lighthouse.io>",
            subject="Re: moved deadline",
            date_hdr="Mon, 30 Jun 2026 08:24:00 -0700",
            snippet="Does the 30th still work?",
            label_ids=["INBOX", "UNREAD"],
            body_text="Hi — confirming the 30th. Loop in the design review please.",
        ),
    })
    emails = _provider(http).fetch_messages(since=None)

    assert len(emails) == 1
    e = emails[0]
    assert isinstance(e, NormalizedEmail)
    assert e.source == "google" and e.source_id == "m1" and e.thread_id == "th1"
    assert e.from_name == "Priya Rao" and e.from_email == "priya@lighthouse.io"
    assert e.subject == "Re: moved deadline"
    assert e.snippet == "Does the 30th still work?"
    assert e.unread is True
    # Date header -> aware UTC (08:24 -0700 == 15:24 UTC).
    assert e.received_at == datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)
    assert "design review" in e.body_excerpt


def test_fetch_messages_sends_inbox_label_and_backfill_count():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000")})
    from app.config import settings

    _provider(http).fetch_messages(since=None)
    # First GET is the list call — assert its params.
    list_url, list_params = http.gets[0]
    assert list_url.endswith("/messages")
    assert list_params.get("labelIds") == "INBOX"
    assert list_params.get("maxResults") == settings.email_backfill_count


def test_bare_email_from_header_has_empty_from_name():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="noreply@service.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000")})
    e = _provider(http).fetch_messages(since=None)[0]
    assert e.from_email == "noreply@service.com"
    assert e.from_name == ""
    assert e.unread is False  # no UNREAD label


def test_body_excerpt_truncated_to_about_2kb():
    big = "x" * 5000
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000", body_text=big)})
    e = _provider(http).fetch_messages(since=None)[0]
    assert len(e.body_excerpt) <= 2048


def test_fetch_messages_auth_failure_raises_google_auth_error():
    http = FakeGmailHTTP(list_ids=["m1"], status={"/messages": 401})
    with pytest.raises(GoogleAuthError):
        _provider(http).fetch_messages(since=None)


def test_get_message_returns_decoded_full_body():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000",
        body_text="The complete message body, all of it.")})
    body = _provider(http).get_message("m1")
    assert body == "The complete message body, all of it."


def test_get_message_raises_on_transport_error():
    http = FakeGmailHTTP(messages={"m1": {}}, status={"/messages/m1": 500})
    with pytest.raises(GoogleAuthError):
        _provider(http).get_message("m1")
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_gmail.py -q`

Expected: FAILS — collection/attribute errors because `GoogleProvider.fetch_messages` and `get_message` don't exist yet (Phase 2 only supplied the OAuth methods). Typical output includes `AttributeError: 'GoogleProvider' object has no attribute 'fetch_messages'` (or similar). This is the RED state.

- [ ] **Step 3: Implement fetch_messages + get_message + mapping helpers on GoogleProvider**

Fill the Gmail fetch methods on the Phase-2 `GoogleProvider` in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/providers/google.py`. Add module-level helpers (base64url decode, plain-text part walk, From/Date parsing, excerpt truncation) and the two protocol methods, mirroring WhoopProvider's `_headers`/`_get_records` transport style. Auth/transport failures raise `GoogleAuthError` (Phase-2 subclass of `AuthError`) so `email_sync` flips `needs_reauth`.

First add the imports needed for parsing. Near the TOP of the file, ensure these stdlib imports exist (add any that are missing — Phase 2 already imports `datetime`/`timedelta`/`timezone` and `urlencode`):

```python
import base64
from email.utils import parseaddr, parsedate_to_datetime
```

Also ensure `NormalizedEmail` is imported from `.base` (Phase 2 imported `AuthError, Tokens` from `.base`; extend that import):

```python
from .base import (
    AuthError,
    NormalizedEmail,
    Tokens,
)
```

Add these module-level helpers (place them just below the constants block, above the `class GoogleProvider`):

```python
# ~2 KB bounded plain-text excerpt sent to triage (never persisted).
_EXCERPT_LIMIT = 2048


def _decode_b64url(data: str | None) -> str:
    """Decode a Gmail base64url body part to text. Gmail omits '=' padding and
    uses the URL-safe alphabet; pad back to a multiple of 4 before decoding."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "replace")
    except Exception:  # malformed part — treat as empty rather than crashing sync
        return ""


def _walk_plaintext(part: dict) -> str:
    """Depth-first walk of a Gmail payload tree, returning the first text/plain
    body found (falling back to any decodable body if no text/plain exists)."""
    if not part:
        return ""
    mime = part.get("mimeType", "")
    body = part.get("body") or {}
    if mime == "text/plain" and body.get("data"):
        return _decode_b64url(body["data"])
    for child in part.get("parts") or []:
        found = _walk_plaintext(child)
        if found:
            return found
    # Leaf with a body but no text/plain sibling (rare single-part text emails).
    if not part.get("parts") and body.get("data") and mime.startswith("text/"):
        return _decode_b64url(body["data"])
    return ""


def _excerpt(text: str) -> str:
    return text[:_EXCERPT_LIMIT]


def _header(headers: list[dict], name: str) -> str:
    lname = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == lname:
            return h.get("value") or ""
    return ""


def _parse_from(value: str) -> tuple[str, str]:
    """'Priya Rao <priya@x.io>' -> ('Priya Rao', 'priya@x.io'); a bare address
    -> ('', addr). Uses stdlib parseaddr so quoting/comments are handled."""
    name, addr = parseaddr(value)
    return name.strip(), addr.strip()


def _parse_date(value: str) -> datetime:
    """RFC 2822 Date header -> aware UTC. Falls back to now(UTC) on a bad/absent
    header so a single malformed message never breaks the sort key."""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
```

Now add the authed-transport helper + the two protocol methods INSIDE `class GoogleProvider` (place them after the OAuth methods, mirroring WhoopProvider's `_headers`/`_get_records`). If Phase 2 already defined a `_headers`, reuse it; otherwise add this one:

```python
    # ---- authed Gmail read ----
    def _headers(self) -> dict:
        tokens = self._ensure_fresh(self._tokens) if self._tokens else None
        if tokens is not None:
            self._tokens = tokens
        access = tokens.access_token if tokens else ""
        return {"Authorization": f"Bearer {access}"}

    def _get(self, url: str, params: dict | None = None) -> dict:
        res = self._transport().get(url, headers=self._headers(), params=params)
        if getattr(res, "status_code", 200) >= 400:
            raise GoogleAuthError(f"Gmail GET {url} returned {res.status_code}")
        return res.json() or {}

    def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]:
        """List the INBOX (maxResults=email_backfill_count) then map each message
        (headers + snippet + a bounded plain-text body excerpt) to a
        NormalizedEmail. `since` is accepted for signature parity with the pull
        providers; Gmail idempotency is handled by store.email_exists in the
        sync (list returns the newest INBOX ids each pass). Auth/transport
        failures raise GoogleAuthError so the sync flips needs_reauth."""
        listing = self._get(
            f"{GMAIL_API_BASE}/messages",
            params={"labelIds": "INBOX", "maxResults": settings.email_backfill_count},
        )
        out: list[NormalizedEmail] = []
        for ref in listing.get("messages") or []:
            msg_id = ref.get("id")
            if not msg_id:
                continue
            msg = self._get(
                f"{GMAIL_API_BASE}/messages/{msg_id}", params={"format": "full"}
            )
            out.append(self._to_email(msg))
        return out

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

    def get_message(self, source_id: str) -> str:
        """On-demand full plain-text body for the reading pane. Raises
        GoogleAuthError on a transport error; the router/store catches it and
        substitutes the fallback string."""
        msg = self._get(
            f"{GMAIL_API_BASE}/messages/{source_id}", params={"format": "full"}
        )
        return _walk_plaintext(msg.get("payload") or {})
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_google_gmail.py -q`

Expected: PASSES — all 7 tests green (`7 passed`). The From/Date parse, UNREAD flag, ~2 KB truncation, INBOX+maxResults query params, body decode, and the 401/500 -> GoogleAuthError paths all satisfied.

- [ ] **Step 4: Run the full suite and commit the Gmail-fetch task**

Confirm the whole suite (M4 fitness guardrail included) is still green, then commit on the M5 branch.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && git rev-parse --abbrev-ref HEAD`
Expected: prints `m5-email-triage` (all M5 work lands here). If it prints something else, run `git checkout m5-email-triage` first.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: the whole suite passes — the final line reads `N passed` with 0 failures (the entire M4 fitness + oauth suite stays green; the new `tests/test_google_gmail.py` adds 7 passing tests). Report the pass count.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/providers/google.py backend/tests/fakes.py backend/tests/test_google_gmail.py && git commit -m "$(printf 'M5: GoogleProvider Gmail fetch — messages.list/get -> NormalizedEmail + on-demand body\n\nfetch_messages(since) lists the INBOX (maxResults=email_backfill_count) and maps\neach message (From/Date/UNREAD + base64url plain-text ~2KB body excerpt) into\nNormalizedEmail; get_message(source_id) returns the decoded full body on demand.\nBodies transit for triage/display but are never persisted. Fake Gmail transport\n+ FakeEmailProvider added for network-free tests.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"`
Expected: a commit is created on `m5-email-triage`; git prints the summary line with the three changed files.


### Task 20: email_triage — Claude Haiku category + summary with a configure(fake) seam (failure returns None, never raises)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_triage.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_triage.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_triage.py`

**Interfaces:**
- Consumes: The shared Claude client seam app/llm.py (llm.available(), llm.stream(...), the _FakeStream/FakeLLM playback harness in tests/fakes.py, settings.assistant_model Haiku tier). Bodies come from GoogleProvider.fetch_messages body_excerpt (Task-1) via email_sync (Task-2).
- Produces: app/email_triage.py: configure(override='unset') seam (fake with .triage(...) OR None -> always (None,None)) and triage(subject, from_name, from_email, snippet, body_excerpt) -> tuple[str|None, list[str]|None] — category clamped to {'needs_reply','fyi'}, summary truncated to <=3 bullets, any failure/offline -> (None,None), never raises. Consumed by email_sync.tick (Task-2) and the conftest no_external_services seam.

- [ ] **Step 1: Add the email_triage seam to conftest's no_external_services fixture**

> See the **PHASE-4 CONFTEST NOTE** at the top of this phase: this conftest edit must be committed together with `app/email_triage.py` in the SAME commit (Step 4 does this), and Task 21's conftest edit anchors on the lines this step adds — run this task before Task 21.

Triage must never reach Anthropic in tests. Wire the new `email_triage` module into the existing `no_external_services` autouse fixture in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`, mirroring how `llm`/`fitness_sync` are installed on setup and restored on teardown. (`email_sync` is added by Task-2; this task only adds `email_triage`.)

Edit the import line to add `email_triage` (the module is created in the next step; the import at fixture-run time is fine because pytest imports conftest after the app package exists):

Old:
```python
from app import fitness_sync, food_db, llm, memory_engine, providers, reminders
```
New:
```python
from app import email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
```

In the `no_external_services` fixture body, add the setup line just after `fitness_sync.configure(None)`:
```python
    email_triage.configure(None)
```
and the teardown line just after `fitness_sync.configure("unset")`:
```python
    email_triage.configure("unset")
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "import ast,sys; ast.parse(open('tests/conftest.py').read()); print('conftest ok')"`
Expected: prints `conftest ok` (the edit is syntactically valid). The suite can't run yet because `app/email_triage` doesn't exist — the next step's test drives its creation. Do NOT commit yet.

- [ ] **Step 2: Write the failing test for email_triage.triage + configure seam**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_triage.py`. It exercises: the fake-object seam (`.triage(...)` delegate), category clamping, summary truncation to 3 bullets, the offline `configure(None) -> (None, None)` path, and the real-parser path fed by a scripted `FakeLLM` turn (so we test the actual JSON extraction without a network) — including a **code-fenced / preamble-wrapped** JSON response (spec §11/§5: triage output must be structured/validated, so the extractor must recover the object even when the model wraps it in prose or a ```json fence).

```python
"""email_triage (M5): category + summary via the shared llm seam; never raises."""
from app import email_triage, llm

from .fakes import FakeLLM, text_turn


class _FakeTriage:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def triage(self, subject, from_name, from_email, snippet, body_excerpt):
        self.calls.append((subject, from_name, from_email, snippet, body_excerpt))
        return self.result


def test_configure_none_returns_none_pair():
    email_triage.configure(None)
    assert email_triage.triage("s", "n", "e@x", "snip", "body") == (None, None)


def test_fake_object_seam_is_delegated_to():
    fake = _FakeTriage(("needs_reply", ["Reply about the 30th"]))
    email_triage.configure(fake)
    cat, summary = email_triage.triage("Re: deadline", "Priya", "p@x", "snip", "body")
    assert cat == "needs_reply" and summary == ["Reply about the 30th"]
    assert fake.calls == [("Re: deadline", "Priya", "p@x", "snip", "body")]


def test_real_path_parses_category_and_summary_from_llm_json():
    llm.configure(FakeLLM(text_turn(
        '{"category": "needs_reply", '
        '"summary": ["Confirm the 30th works", "Loop in design review"]}'
    )))
    email_triage.configure("unset")
    cat, summary = email_triage.triage(
        "Re: moved deadline", "Priya Rao", "priya@x.io",
        "Does the 30th still work?", "Hi confirming the 30th ...",
    )
    assert cat == "needs_reply"
    assert summary == ["Confirm the 30th works", "Loop in design review"]


def test_real_path_recovers_json_from_code_fence_and_preamble():
    # The model often wraps JSON in prose and/or a ```json fence. The extractor
    # must still recover the object (spec §11/§5: triage output validated).
    llm.configure(FakeLLM(text_turn(
        "Here you go:\n"
        "```json\n"
        '{"category": "fyi", "summary": ["Newsletter digest", "No action needed"]}\n'
        "```\n"
        "Let me know if you need anything else."
    )))
    email_triage.configure("unset")
    cat, summary = email_triage.triage("Weekly digest", "News", "news@x.io", "snip", "body")
    assert cat == "fyi"
    assert summary == ["Newsletter digest", "No action needed"]


def test_real_path_clamps_unknown_category_to_none():
    llm.configure(FakeLLM(text_turn('{"category": "spam", "summary": ["x"]}')))
    email_triage.configure("unset")
    cat, summary = email_triage.triage("s", "n", "e@x", "snip", "body")
    assert cat is None  # not in the two-value enum
    assert summary == ["x"]


def test_real_path_truncates_summary_to_three_bullets():
    llm.configure(FakeLLM(text_turn(
        '{"category": "fyi", "summary": ["a", "b", "c", "d", "e"]}'
    )))
    email_triage.configure("unset")
    _, summary = email_triage.triage("s", "n", "e@x", "snip", "body")
    assert summary == ["a", "b", "c"]


def test_real_path_bad_json_returns_none_pair():
    llm.configure(FakeLLM(text_turn("sorry, I cannot help with that")))
    email_triage.configure("unset")
    assert email_triage.triage("s", "n", "e@x", "snip", "body") == (None, None)


def test_offline_llm_returns_none_pair_without_raising():
    # llm.configure(None) -> llm.available() is False; triage must not raise.
    llm.configure(None)
    email_triage.configure("unset")
    assert email_triage.triage("s", "n", "e@x", "snip", "body") == (None, None)
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_triage.py -q`
Expected: FAILS at import — `ModuleNotFoundError: No module named 'app.email_triage'` (the module doesn't exist yet). RED state.

- [ ] **Step 3: Implement app/email_triage.py**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_triage.py`. It builds a compact triage prompt, calls the shared `llm.stream(...)` at the Haiku tier (`settings.assistant_model`), reads the final text via the same streaming-context pattern the assistant loop uses (`with llm.stream(...) as s: for _ in s.text_stream: pass; msg = s.get_final_message()`), extracts the first JSON object, and validates it. Every failure path returns `(None, None)` and NEVER raises — the caller (`email_sync`) leaves the row untriaged and retries next pass.

```python
"""Email triage (M5) — one Claude (Haiku) call per synced message.

Input: subject + sender + snippet + a bounded ~2 KB plain-text body excerpt
(the excerpt transits Gmail -> server -> Anthropic and is NEVER persisted).
Output: (category, summary) where category is 'needs_reply' | 'fyi' (or None on
failure) and summary is a list of <=3 short bullet strings (or None on failure).

Seam mirrors llm.py / food_db.py: configure(fake) installs an object exposing
.triage(...); configure(None) disables triage (always returns (None, None));
configure("unset") uses the real Claude client via app/llm.py. A model/offline
failure returns (None, None) — the caller keeps the message untriaged (it still
shows) and re-triages on the next sync. This function never raises.
"""
from __future__ import annotations

import json
import logging
import re

from . import llm
from .config import settings

log = logging.getLogger("scuffed_os.email_triage")

_override: object | None | str = "unset"

_CATEGORIES = ("needs_reply", "fyi")
_MAX_BULLETS = 3

_SYSTEM = (
    "You triage a single email for a busy person's inbox. Decide whether it "
    "NEEDS A REPLY from the user or is just FYI (no reply needed), and write at "
    "most three very short summary bullets (each a terse phrase, not a sentence). "
    "Respond with ONLY a JSON object, no prose, of the exact form: "
    '{\"category\": \"needs_reply\"|\"fyi\", \"summary\": [\"bullet\", ...]}.'
)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def configure(override: object | None | str = "unset") -> None:
    """Tests install a fake with .triage(...); None disables; 'unset' uses real."""
    global _override
    _override = override


def _build_prompt(subject: str, from_name: str, from_email: str,
                  snippet: str, body_excerpt: str) -> str:
    sender = f"{from_name} <{from_email}>".strip()
    return (
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Preview: {snippet}\n"
        f"Body:\n{body_excerpt}"
    )


def _clamp(payload: dict) -> tuple[str | None, list[str] | None]:
    """Validate the model's JSON: category to the two-value enum (else None),
    summary to <=3 non-empty string bullets (else None)."""
    raw_cat = payload.get("category")
    category = raw_cat if raw_cat in _CATEGORIES else None
    raw_summary = payload.get("summary")
    summary: list[str] | None = None
    if isinstance(raw_summary, list):
        bullets = [str(b).strip() for b in raw_summary if str(b).strip()]
        summary = bullets[:_MAX_BULLETS] if bullets else None
    return category, summary


def _extract(text: str) -> tuple[str | None, list[str] | None]:
    match = _JSON_OBJECT.search(text or "")
    if not match:
        return None, None
    try:
        payload = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return _clamp(payload)


def _final_text(prompt: str) -> str:
    """One Haiku call via the shared llm seam; return the assistant's text.
    Reads the streaming context the same way the assistant loop does."""
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


def triage(subject: str, from_name: str, from_email: str,
           snippet: str, body_excerpt: str) -> tuple[str | None, list[str] | None]:
    """Return (category, summary). Any failure/offline -> (None, None). Never raises."""
    if _override is None:
        return None, None
    if _override != "unset":
        try:
            return _override.triage(subject, from_name, from_email, snippet, body_excerpt)
        except Exception:
            log.exception("fake triage raised; leaving untriaged")
            return None, None
    if not llm.available():
        return None, None
    try:
        text = _final_text(
            _build_prompt(subject, from_name, from_email, snippet, body_excerpt)
        )
        return _extract(text)
    except Exception:
        log.exception("triage call failed; leaving message untriaged")
        return None, None
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_triage.py -q`
Expected: PASSES — all 8 tests green (`8 passed`). The delegate seam, JSON parse, code-fence/preamble recovery, category clamp, 3-bullet truncation, bad-JSON -> (None,None), and offline -> (None,None) paths are satisfied.

- [ ] **Step 4: Run the full suite and commit email_triage**

Verify the whole suite (M4 guardrail + the new conftest seam) is green, then commit.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: the whole suite passes — final line `N passed`, 0 failures. The conftest change (installing `email_triage.configure(None)`) keeps all other tests offline. Report the pass count.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/email_triage.py backend/tests/test_email_triage.py backend/tests/conftest.py && git commit -m "$(printf 'M5: email_triage — Haiku category + summary with a configure(fake) seam\n\ntriage(subject, from_name, from_email, snippet, body_excerpt) -> (category, summary)\nvia the shared app/llm.py client (assistant_model / Haiku). category clamped to\nneeds_reply|fyi, summary truncated to <=3 bullets; any failure or offline LLM\nreturns (None, None) so the caller leaves the row untriaged and retries. Body\nexcerpt transits to Anthropic but is never persisted. conftest no_external_services\ninstalls the email_triage(None) seam.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"`
Expected: a commit lands on `m5-email-triage` listing the three changed files.


### Task 21: email_sync — tick over connected Google accounts (fetch -> triage -> upsert), trigger/run_loop, needs_reauth, lifespan wiring

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_sync.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_sync.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_sync.py`

**Interfaces:**
- Consumes: providers.all_providers() + the registry (Phase 1); the _load_and_inject_tokens token-refresh pattern mirrored from app/fitness_sync.py; store.email_exists / store.upsert_email / store.set_provider_synced / store.set_provider_status / store.list_provider_accounts (Phase 3 + M4); GoogleProvider.fetch_messages producing NormalizedEmail with body_excerpt (Task-1); email_triage.triage (Task-2); settings.email_sync_enabled/email_sync_seconds (Phase 2 config); main.py lifespan (M4).
- Produces: app/email_sync.py: configure(override) tick seam, tick(now) -> int (iterates connected EmailProviders = all_providers() with a fetch_messages attribute; per account load+refresh+inject tokens, fetch_messages(since=last_sync_at), skip store.email_exists ids, triage new ones, store.upsert_email, advance cursor; per-account try/except; AuthError->needs_reauth; RuntimeError(no DATABASE_URL)->0; never crashes), async trigger(), async run_loop(); main.py lifespan starts/cancels email_sync.run_loop() gated by settings.email_sync_enabled; conftest installs the email_sync(None) seam.

- [ ] **Step 1: Add the email_sync seam to conftest's no_external_services fixture**

> See the **PHASE-4 CONFTEST NOTE** at the top of this phase: run Task 20 first (its conftest edit adds the `email_triage` import + seam lines this step anchors on), and commit this conftest edit together with `app/email_sync.py` in the SAME commit (Step 4 does this). This edit anchors on Task 20's lines, so it never conflicts with Task 20's edit.

So `on_connected()` (which calls `email_sync.tick()`) and any /sync path stay offline in tests, wire `email_sync` into the autouse `no_external_services` fixture in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/conftest.py`, mirroring `fitness_sync`.

Edit the import to add `email_sync` (Task-2 already added `email_triage` to this line; add `email_sync` alphabetically):

Old:
```python
from app import email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
```
New:
```python
from app import email_sync, email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
```

In the fixture body add the setup line just after `email_triage.configure(None)`:
```python
    email_sync.configure(None)
```
and the teardown line just after `email_triage.configure("unset")`:
```python
    email_sync.configure("unset")
```

Note: `email_sync.configure(None)` installs the real tick as the DEFAULT (None/"unset" both run the real tick, like fitness_sync) — tests that want to exercise the real tick call `email_sync.configure("unset")` or rely on this default; tests that want to stub it install a fake explicitly. This matches fitness_sync's semantics exactly.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "import ast; ast.parse(open('tests/conftest.py').read()); print('conftest ok')"`
Expected: prints `conftest ok`. The suite can't fully run until `app/email_sync` exists (next step). Do NOT commit yet.

- [ ] **Step 2: Write the failing test for email_sync.tick**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_sync.py`. It drives the REAL tick with a `FakeEmailProvider` (Task-1) registered via `providers.configure([...])` and a fake triage via `email_triage.configure(fake)`, asserting: a connected Google account gets its messages fetched + triaged + upserted; the fitness pull path is untouched (a WHOOP FakeProvider in the registry is ignored by email_sync); already-stored ids are skipped (`email_exists` idempotency); an untriaged message ((None,None)) still lands; and an `AuthError` from the provider flips the account to `needs_reauth`.

```python
"""email_sync (M5): tick over connected Google accounts — real tick, fakes only."""
from datetime import datetime, timezone

from app import email_sync, email_triage, providers
from app.providers.base import NormalizedEmail, Tokens
from app.store import store

from .fakes import FakeEmailProvider, FakeProvider


class _FakeTriage:
    def __init__(self, result=("fyi", ["noted"])):
        self.result = result
        self.calls = []

    def triage(self, subject, from_name, from_email, snippet, body_excerpt):
        self.calls.append(source := (subject, body_excerpt))
        return self.result


def _email(source_id: str, *, subject: str = "Hi", unread: bool = True) -> NormalizedEmail:
    return NormalizedEmail(
        source="google", source_id=source_id, thread_id="th",
        from_name="Priya", from_email="p@x.io", subject=subject,
        snippet="snip", received_at=datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc),
        unread=unread, body_excerpt="body excerpt text",
    )


def _connect_google():
    store.upsert_provider_account("google", Tokens(
        access_token="g", refresh_token="r", expires_at=None,
        scopes="gmail.readonly", provider_user_id="sub1"))


def test_tick_fetches_triages_and_upserts_new_messages():
    prov = FakeEmailProvider(messages=[_email("m1"), _email("m2", subject="FYI note")])
    providers.configure([prov])
    triage = _FakeTriage(("needs_reply", ["Reply about the 30th"]))
    email_triage.configure(triage)
    _connect_google()

    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 2
    # Tokens were injected before the authed fetch.
    assert prov.injected and prov.injected[-1].access_token == "g"
    # Both messages triaged + stored.
    assert len(triage.calls) == 2
    inbox = store.inbox()
    stored_ids = {e["source_id"] for e in inbox["needs_reply"] + inbox["fyi"] + inbox["untriaged"]}
    assert stored_ids == {"m1", "m2"}
    # Cursor advanced.
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "google")
    assert acct["last_sync_at"] is not None


def test_tick_skips_already_stored_ids():
    prov = FakeEmailProvider(messages=[_email("m1")])
    providers.configure([prov])
    triage = _FakeTriage()
    email_triage.configure(triage)
    _connect_google()
    # Pre-store m1 so email_exists short-circuits it.
    store.upsert_email(_email("m1"), "fyi", ["already"])

    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 0
    assert triage.calls == []  # never re-triaged


def test_tick_stores_untriaged_message_when_triage_returns_none():
    prov = FakeEmailProvider(messages=[_email("m1")])
    providers.configure([prov])
    email_triage.configure(_FakeTriage((None, None)))
    _connect_google()

    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 1
    inbox = store.inbox()
    ids = {e["source_id"] for e in inbox["untriaged"]}
    assert "m1" in ids  # shows as untriaged, retried next pass


def test_tick_ignores_fitness_pull_providers():
    # A WHOOP FakeProvider has no fetch_messages -> email_sync must skip it.
    providers.configure([FakeProvider()])
    email_triage.configure(_FakeTriage())
    store.upsert_provider_account("whoop", Tokens(
        access_token="w", refresh_token="r", expires_at=None, scopes="", provider_user_id=None))
    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 0  # nothing email-shaped connected


def test_tick_flips_account_to_needs_reauth_on_auth_error():
    providers.configure([FakeEmailProvider(raise_auth=True)])
    email_triage.configure(_FakeTriage())
    _connect_google()
    email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "google")
    assert acct["status"] == "needs_reauth"


def test_tick_skips_disconnected_account():
    providers.configure([FakeEmailProvider(messages=[_email("m1")])])
    email_triage.configure(_FakeTriage())
    # No account row at all -> nothing to sync.
    assert email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc)) == 0
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_sync.py -q`
Expected: FAILS at import — `ModuleNotFoundError: No module named 'app.email_sync'` (module not created yet). RED state. (This test also depends on Phase-3 `store.inbox`/`upsert_email`/`email_exists`; if those are absent it will error there instead — either way it is RED until this task + Phase 3 land.)

- [ ] **Step 3: Implement app/email_sync.py**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/email_sync.py`, mirroring `app/fitness_sync.py` (same tick-seam, per-account isolation, AuthError->needs_reauth, RuntimeError-no-DATABASE_URL->0 shape). Email providers are selected by having a `fetch_messages` attribute (GoogleProvider); the fitness `pull_providers()` filter is NOT reused. Reuse the exact token-load/refresh/inject helper shape from fitness_sync.

```python
"""Email sync engine (M5) — a background tick + on-demand trigger.

A near-clone of app/fitness_sync.py: a plain asyncio loop (started from the app
lifespan, guarded by settings.email_sync_enabled) wakes every
settings.email_sync_seconds, and for each connected email provider fetches the
Gmail INBOX since its cursor, triages each NEW message, upserts it into the
`emails` table, and advances the cursor.

Email providers are the registry entries that implement fetch_messages (i.e.
GoogleProvider). The fitness pull_providers() filter is deliberately NOT reused
— a fitness pull provider has no fetch_messages and is skipped here, exactly as
GoogleProvider (no `kind`) is skipped by the fitness tick.

Reads never depend on a live Gmail call for the inbox list (served from the
`emails` table); only the message body is fetched live for the reading pane.
A failed sync just logs and retries next tick; the tick never crashes. Auth
failures flip the account to needs_reauth. Test seam: configure(fake) installs
an object with a .tick() that tick() delegates to; configure(None)/"unset" run
the real pass (matching fitness_sync). Providers are swapped via
providers.configure(...).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import email_triage, providers
from .config import settings
from .providers.base import AuthError
from .store import store

logger = logging.getLogger("scuffed_os.email_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Test seam for mocking tick(); install a fake with .tick() to delegate to
    it. None or "unset" run the real tick. Does NOT gate run_loop (the lifespan,
    gated by settings.email_sync_enabled, controls that). The provider registry
    is swapped separately via providers.configure(...)."""
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _email_providers() -> list:
    """Registry entries that implement fetch_messages (email domain)."""
    return [p for p in providers.all_providers() if hasattr(p, "fetch_messages")]


def _load_and_inject_tokens(provider, now: datetime) -> bool:
    """Load stored tokens, refresh if within the skew of expiry (persist the
    rotation), and inject them so the authed Gmail calls carry a Bearer token.
    Returns False if no tokens are stored. Raises AuthError on a refresh failure
    so the caller flips needs_reauth. Mirrors fitness_sync._load_and_inject_tokens."""
    tokens = store.get_provider_tokens(provider.name)
    if tokens is None:
        return False
    refresh = getattr(provider, "refresh", None)
    if (
        tokens.expires_at is not None
        and refresh is not None
        and now >= tokens.expires_at - timedelta(seconds=60)
    ):
        tokens = refresh(tokens)                              # may raise AuthError
        store.upsert_provider_account(provider.name, tokens)  # persist rotation
    set_tokens = getattr(provider, "set_tokens", None)
    if set_tokens is not None:
        set_tokens(tokens)
    return True


def _sync_provider(provider, now: datetime) -> int:
    """One email provider's pass. Returns messages upserted. Raises AuthError on
    an auth/refresh failure so the caller flips needs_reauth; other errors
    propagate so the caller can log-and-continue."""
    acct = next(
        (a for a in store.list_provider_accounts() if a["provider"] == provider.name),
        None,
    )
    if acct is None or acct["status"] != "connected":
        return 0
    if not _load_and_inject_tokens(provider, now):
        return 0

    since = acct["last_sync_at"]  # None on a fresh account -> full backfill via list
    count = 0
    for email in provider.fetch_messages(since):
        if store.email_exists(email.source, email.source_id):
            continue
        category, summary = email_triage.triage(
            email.subject, email.from_name, email.from_email,
            email.snippet, email.body_excerpt,
        )
        store.upsert_email(email, category, summary)
        count += 1
    store.set_provider_synced(provider.name, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every connected email provider. Returns messages
    upserted. Safe to call any time — per-account errors are caught and logged
    so the tick never crashes; auth failures flip the account to needs_reauth.
    Returns 0 when no database is configured (RuntimeError caught).

    Test seam: if configure() installed an object with a .tick(), that is called
    instead of the real pass.
    """
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]
    now = now or _utcnow()
    try:
        provider_list = _email_providers()
    except RuntimeError:  # no DATABASE_URL behind the registry — nothing to do
        return 0
    total = 0
    for provider in provider_list:
        try:
            total += _sync_provider(provider, now)
        except AuthError:
            logger.warning("%s needs re-auth; flipping status", provider.name)
            try:
                store.set_provider_status(provider.name, "needs_reauth")
            except Exception:
                logger.exception("could not flip %s to needs_reauth", provider.name)
        except RuntimeError as exc:
            if "DATABASE_URL" in str(exc):
                return total
            logger.exception("email sync failed for %s", provider.name)
        except Exception:
            logger.exception("email sync failed for %s", provider.name)
    return total


async def trigger() -> int:
    """Run one sync pass off the event loop and return its count. Awaited by the
    OAuth callback (via on_connected) and by POST /api/email/sync. Errors are
    already swallowed inside tick, so this never raises for provider problems."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """The lifespan background task; ticks forever until cancelled."""
    logger.info("email sync loop started (every %ss)", settings.email_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d email(s)", synced)
        except Exception:
            logger.exception("email sync tick failed")
        await asyncio.sleep(settings.email_sync_seconds)
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_sync.py -q`
Expected: PASSES — all 6 tests green (`6 passed`): fetch+triage+upsert, email_exists skip, untriaged storage, fitness-provider exclusion, needs_reauth flip, and disconnected-account no-op.

- [ ] **Step 4: Wire email_sync.run_loop into the app lifespan (gated by email_sync_enabled)**

Register the email-sync background loop alongside the reminder + fitness loops in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`, gated by `settings.email_sync_enabled`, and cancel it on shutdown. This is the only main.py change THIS phase owns (Phase 5 adds the `email`/`oauth` router includes; Phase 1 owns the fitness->oauth router swap). Edit only the imports + the lifespan body so the changes compose cleanly with the other phases' edits.

Edit the module import to add `email_sync`:

Old:
```python
from . import fitness_sync, reminders
```
New:
```python
from . import email_sync, fitness_sync, reminders
```

In the `lifespan` function, add an `email_task` handle and start it when enabled. Replace the existing lifespan body:

Old:
```python
    reminder_task: asyncio.Task | None = None
    fitness_task: asyncio.Task | None = None
    if settings.reminders_enabled:
        reminder_task = asyncio.create_task(reminders.run_loop())
    if settings.fitness_sync_enabled:
        fitness_task = asyncio.create_task(fitness_sync.run_loop())
    yield
    for task in (reminder_task, fitness_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
```
New:
```python
    reminder_task: asyncio.Task | None = None
    fitness_task: asyncio.Task | None = None
    email_task: asyncio.Task | None = None
    if settings.reminders_enabled:
        reminder_task = asyncio.create_task(reminders.run_loop())
    if settings.fitness_sync_enabled:
        fitness_task = asyncio.create_task(fitness_sync.run_loop())
    if settings.email_sync_enabled:
        email_task = asyncio.create_task(email_sync.run_loop())
    yield
    for task in (reminder_task, fitness_task, email_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
```

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "import app.main; print('lifespan wired:', 'email_sync' in dir(app.main))"`
Expected: prints `lifespan wired: True` (module imports cleanly; `email_sync` is in scope). The background loop does not start on plain import — only under the ASGI lifespan — so this import is safe.

- [ ] **Step 5: Run the full suite and commit email_sync + lifespan wiring**

Confirm everything (M4 guardrail, the two new email test modules, and the lifespan wiring) is green, then commit.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: the whole suite passes — final line `N passed`, 0 failures. The email_sync tick, triage, Gmail-fetch, and every M4 fitness/oauth test are green together. Report the pass count.

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/email_sync.py backend/app/main.py backend/tests/test_email_sync.py backend/tests/conftest.py && git commit -m "$(printf 'M5: email_sync tick + lifespan wiring — fetch -> triage -> upsert, needs_reauth\n\nMirrors fitness_sync: tick() iterates connected email providers (registry entries\nwith a fetch_messages attribute -> GoogleProvider; fitness pull providers are\nskipped), loads+refreshes+injects tokens, fetch_messages(since=last_sync_at),\nskips store.email_exists ids, triages each new message, store.upsert_email, and\nadvances the cursor. Per-account try/except; AuthError -> needs_reauth; the tick\nnever crashes. trigger()/run_loop() coroutines; run_loop registered in the app\nlifespan gated by settings.email_sync_enabled. conftest installs the\nemail_sync(None) seam.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"`
Expected: a commit lands on `m5-email-triage` listing the four changed files. Phase complete: Gmail fetch (Task-1) + triage (Task-2) + sync/lifespan (Task-3) are implemented, tested, and committed with the full suite green.


## Phase: Email API + schemas + read-only tools

### Task 22: Email API schemas — EmailOut / EmailDetail / Inbox / EmailCategory

> **NOTE (duplication guard):** `OAuthStatus` is DEFINED once, by the Phase-1 spine (Task 4 — see Interface Contract §K). This task adds ONLY the email schemas (`EmailCategory`/`EmailOut`/`EmailDetail`/`Inbox`) and IMPORTS/consumes `OAuthStatus` (its test validates it); it must NOT re-add the `OAuthStatus` class, or a second definition would shadow Task 4's.

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_schemas.py`

**Interfaces:**
- Consumes: schemas.py already defines the assistant Screen Literal (includes "email"), the fitness ProviderStatus schema, the derive-on-read dict conventions, AND the generic `OAuthStatus` schema added by the Phase-1 spine (Task 4). No runtime code from other phases is needed for the email schemas themselves — they are pure Pydantic shapes validated against literal dicts.
- Produces: EmailOut (list item, NO body), EmailDetail (adds thread_id + live body), Inbox (grouped needs_reply/fyi/untriaged lists + needs_reply_count + unread_count), and the EmailCategory Literal — all importable from app.schemas for routers/email.py. `OAuthStatus` is NOT re-added here (Task 4 owns it); this task's test imports it to confirm the moved oauth status test can rely on it.

- [ ] **Step 1: Write the failing schema test**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_schemas.py` asserting the four new schemas validate the store-dict shape (frozen by contract §K/§F) and that EmailOut carries NO `body` field while EmailDetail does.

```python
"""M5 email schemas: EmailOut (no body), EmailDetail (adds body), Inbox, OAuthStatus."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import EmailDetail, EmailOut, Inbox, OAuthStatus


def _row(**over) -> dict:
    base = {
        "id": 1,
        "source": "google",
        "from_name": "Ada Lovelace",
        "from_email": "ada@example.com",
        "subject": "Re: dinner",
        "snippet": "Are we still on for",
        "received_at": datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc),
        "unread": True,
        "category": "needs_reply",
        "summary": ["Wants to confirm dinner", "Asks about time"],
        "when": "8:24am",
    }
    base.update(over)
    return base


def test_email_out_validates_list_row_and_has_no_body():
    out = EmailOut.model_validate(_row())
    assert out.category == "needs_reply"
    assert out.summary == ["Wants to confirm dinner", "Asks about time"]
    assert out.when == "8:24am"
    assert "body" not in EmailOut.model_fields  # privacy: list item never carries a body


def test_email_out_allows_untriaged_null_category_and_empty_summary():
    out = EmailOut.model_validate(_row(category=None, summary=[]))
    assert out.category is None
    assert out.summary == []


def test_email_out_rejects_out_of_vocab_category():
    with pytest.raises(ValidationError):
        EmailOut.model_validate(_row(category="spam"))


def test_email_detail_adds_thread_id_and_body():
    detail = EmailDetail.model_validate(_row(thread_id="t-1", body="Full plain text body."))
    assert detail.thread_id == "t-1"
    assert detail.body == "Full plain text body."
    assert detail.subject == "Re: dinner"  # inherits EmailOut fields


def test_inbox_groups_and_counts():
    inbox = Inbox.model_validate({
        "needs_reply": [_row(id=1)],
        "fyi": [_row(id=2, category="fyi")],
        "untriaged": [_row(id=3, category=None, summary=[])],
        "needs_reply_count": 1,
        "unread_count": 3,
    })
    assert [e.id for e in inbox.needs_reply] == [1]
    assert [e.id for e in inbox.fyi] == [2]
    assert [e.id for e in inbox.untriaged] == [3]
    assert inbox.needs_reply_count == 1
    assert inbox.unread_count == 3


def test_oauth_status_is_generic_provider_status_list():
    status = OAuthStatus.model_validate({
        "connected": True,
        "providers": [{
            "provider": "google",
            "status": "connected",
            "connected_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "last_sync_at": None,
        }],
    })
    assert status.connected is True
    assert status.providers[0].provider == "google"
```

- [ ] **Step 2: Run the test — see it fail on the missing imports**

Run:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_schemas.py -q
```

Expected: collection/import error — `ImportError: cannot import name 'EmailDetail' from 'app.schemas'` (the four schemas do not exist yet), so the module fails to import and every test errors.

- [ ] **Step 3: Add ONLY the email schemas to schemas.py (do NOT re-add OAuthStatus)**

Append the email block after the fitness read/write schemas (end of file, after the `FitnessWeek` class). `EmailDetail` subclasses `EmailOut` so it inherits every list field and adds `thread_id` + the live `body`. The email schemas reuse `Literal` / `List` / `BaseModel` / `datetime`, already imported at the top of `schemas.py`.

**Do NOT add an `OAuthStatus` class here** — it is defined once by the Phase-1 spine (Task 4, right after `FitnessStatus`). Task 22's test only imports `OAuthStatus` to confirm it is present; re-adding it would create a second, shadowing definition. First confirm it exists (should print `1`):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && grep -c "^class OAuthStatus" app/schemas.py
```

If that prints `0` (Phase 1 not merged yet), STOP and land Task 4 first — do not add `OAuthStatus` in this task; keeping the single definition in Task 4 is what avoids the duplicate.

Then edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`, appending at the very end of the file:

```python


# ---- Email schemas (M5) -----------------------------------------------------
# EmailOut is the inbox list item and carries NO body (privacy: bodies are
# never persisted and never travel in the list). EmailDetail adds the live,
# on-demand body fetched from Gmail in the reading pane.
# (OAuthStatus lives above, added by the Phase-1 spine / Task 4 — not re-added
# here.)
EmailCategory = Literal["needs_reply", "fyi"]


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


class EmailDetail(EmailOut):
    thread_id: str
    body: str  # on-demand Gmail fetch (or a graceful fallback string)


class Inbox(BaseModel):
    needs_reply: List[EmailOut]
    fyi: List[EmailOut]
    untriaged: List[EmailOut]
    needs_reply_count: int
    unread_count: int
```

- [ ] **Step 4: Run the test — see it pass**

Run:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_schemas.py -q
```

Expected: `6 passed`.

- [ ] **Step 5: Run the full suite and commit**

Confirm nothing else regressed (schemas are additive), then commit on the M5 branch.

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q
```

Expected: the whole suite passes — the previous green count plus 6 new (`test_email_schemas.py`). Report the number (e.g. "N tests passing").

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git checkout m5-email-triage && git add backend/app/schemas.py backend/tests/test_email_schemas.py && git commit -m "M5: email API schemas — EmailOut/EmailDetail/Inbox/EmailCategory

OAuthStatus is not re-added here — it is owned by the Phase-1 spine (Task 4);
this task's test only imports it to confirm the moved oauth status test can rely
on it.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit created on `m5-email-triage` (the branch already exists from phase 1; `git checkout m5-email-triage` switches onto it).


### Task 23: Email API router — /api/email inbox, detail (on-demand body), sync

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`

**Interfaces:**
- Consumes: EmailOut/EmailDetail/Inbox schemas (Task 1); store.inbox() / store.get_email(id) / store.upsert_email(...) and the Email model + NormalizedEmail (phase 3); email_sync.tick()/configure() (phase 4); providers.get('google').get_message(source_id) + the registry configure([...]) seam (phase 1/4). Tests set up rows via store.upsert_email and install a local fake email provider + a fake email_sync via their configure seams.
- Produces: routers/email.py exporting `router` (prefix /api/email) with GET /inbox, GET /{id} (metadata + summary + on-demand body via provider.get_message, graceful fallback on failure), POST /sync (email_sync.tick, returns synced count + polled provider names). Registered in main.py alongside the oauth + email-sync lifespan wiring done by other phases.

- [ ] **Step 1: Write the failing router test**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_api.py`. It seeds rows through `store.upsert_email`, installs a local fake email provider via `providers.configure([...])` for the body path, and a `FakeEmailSync` via `email_sync.configure(...)` for `/sync`. The fake provider only needs the attributes the router touches (`name`, `fetch_messages` marker, `get_message`).

```python
"""M5 email API: GET /inbox grouping, GET /{id} on-demand body + fallback, POST /sync."""
from datetime import datetime, timedelta, timezone

from app import email_sync, providers
from app.providers.base import NormalizedEmail, Tokens
from app.store import store

NOW = datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)


def _email(source_id: str, subject: str, minutes_ago: int = 0, unread: bool = False) -> NormalizedEmail:
    return NormalizedEmail(
        source="google",
        source_id=source_id,
        thread_id=f"t-{source_id}",
        from_name="Ada Lovelace",
        from_email="ada@example.com",
        subject=subject,
        snippet="preview text",
        received_at=NOW - timedelta(minutes=minutes_ago),
        unread=unread,
    )


class FakeEmailProvider:
    """Only the surface the email router calls: name, fetch_messages (marker), get_message."""

    name = "google"

    def __init__(self, *, body: str = "Full body text.", raise_on_get: bool = False):
        self._body = body
        self._raise = raise_on_get
        self.got: list[str] = []

    def fetch_messages(self, since):  # marks this as an EmailProvider for the sync
        return []

    def get_message(self, source_id: str) -> str:
        self.got.append(source_id)
        if self._raise:
            raise RuntimeError("gmail down")
        return self._body


class FakeEmailSync:
    def __init__(self, count: int = 4):
        self.count = count
        self.calls = 0

    def tick(self, now=None) -> int:
        self.calls += 1
        return self.count


def test_inbox_groups_needs_reply_fyi_untriaged_with_counts(client):
    store.upsert_email(_email("m1", "Reply please", minutes_ago=1, unread=True),
                       category="needs_reply", summary=["Wants a reply"])
    store.upsert_email(_email("m2", "Newsletter", minutes_ago=2, unread=True),
                       category="fyi", summary=["Weekly digest"])
    store.upsert_email(_email("m3", "Just arrived", minutes_ago=3, unread=False),
                       category=None, summary=None)

    body = client.get("/api/email/inbox").json()
    assert [e["subject"] for e in body["needs_reply"]] == ["Reply please"]
    assert [e["subject"] for e in body["fyi"]] == ["Newsletter"]
    assert [e["subject"] for e in body["untriaged"]] == ["Just arrived"]
    assert body["needs_reply_count"] == 1
    assert body["unread_count"] == 2
    # list items never carry a body
    assert all("body" not in e for group in ("needs_reply", "fyi", "untriaged") for e in body[group])


def test_get_email_returns_metadata_plus_on_demand_body(client):
    fake = FakeEmailProvider(body="Hey Ada here is the plan.")
    providers.configure([fake])
    row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])

    detail = client.get(f"/api/email/{row['id']}").json()
    assert detail["subject"] == "The plan"
    assert detail["thread_id"] == "t-m9"
    assert detail["summary"] == ["A plan"]
    assert detail["body"] == "Hey Ada here is the plan."
    assert fake.got == ["m9"]  # body fetched live by source_id


def test_get_email_falls_back_when_gmail_unreachable(client):
    providers.configure([FakeEmailProvider(raise_on_get=True)])
    row = store.upsert_email(_email("m5", "Offline"), category="fyi", summary=[])

    detail = client.get(f"/api/email/{row['id']}").json()
    assert detail["body"] == "Message body is unavailable right now."


def test_get_email_404_for_missing_id(client):
    assert client.get("/api/email/999999").status_code == 404


def test_sync_triggers_email_sync_and_lists_email_providers(client):
    fake_sync = FakeEmailSync(count=7)
    email_sync.configure(fake_sync)
    providers.configure([FakeEmailProvider()])

    body = client.post("/api/email/sync").json()
    assert body == {"synced": 7, "providers": ["google"]}
    assert fake_sync.calls == 1
```

- [ ] **Step 2: Run the test — see it fail**

Run:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_api.py -q
```

Expected: import/collection error — `ModuleNotFoundError: No module named 'app.routers.email'` (the router does not exist and is not registered in main.py), so all tests error.

- [ ] **Step 3: Create routers/email.py**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/email.py`. Reads (`/inbox`, `/{id}`) always serve the `emails` table — never a live Gmail call for the list. Only `/{id}` fetches the body live via `providers.get('google').get_message(source_id)`, wrapped in try/except → the frozen fallback string. `/sync` mirrors the fitness `/sync`: call `email_sync.tick()` synchronously (its configure seam makes it test-safe) and list the polled email providers (those exposing `fetch_messages`).

```python
"""Email API (M5): the triaged inbox, one message with its live body, and sync.

Reads serve the normalized `emails` table only — the list is never a live Gmail
call (privacy: bodies are not persisted). The reading pane is the sole place a
body is fetched, on demand via EmailProvider.get_message, with a graceful
fallback string when Gmail is unreachable. Connect/disconnect/status live on
the shared /api/oauth/* router, not here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .. import email_sync, providers
from ..schemas import EmailDetail, Inbox
from ..store import store

router = APIRouter(prefix="/api/email", tags=["email"])

logger = logging.getLogger("scuffed_os.email")

# Shown in the reading pane when the live Gmail body fetch fails — the row's
# metadata + AI summary still render, so the pane is never blank.
_BODY_UNAVAILABLE = "Message body is unavailable right now."


@router.get("/inbox", response_model=Inbox)
def inbox() -> dict:
    """The triaged inbox: needs_reply / fyi / untriaged groups + counts. Served
    from the emails table (never a live provider call)."""
    return store.inbox()


@router.get("/{email_id}", response_model=EmailDetail)
def email_detail(email_id: int) -> dict:
    """One message: stored metadata + AI summary, plus the full body fetched
    live from Gmail on demand. A failed fetch degrades to a fallback string so
    the pane still shows the sender/subject/summary."""
    row = store.get_email(email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    body = _BODY_UNAVAILABLE
    impl = providers.get(row["source"])
    get_message = getattr(impl, "get_message", None)
    if get_message is not None:
        try:
            body = get_message(row["source_id"])
        except Exception as exc:  # noqa: BLE001 — body fetch is best-effort
            logger.warning("body fetch failed for email %s: %s", email_id, exc)
    return {**row, "body": body}


@router.post("/sync")
def sync_now() -> dict:
    """Run one email sync pass now (manual/test/assistant). Delegates to
    email_sync.tick(); reads never depend on it, so a failing tick returns 0.
    `providers` lists the email providers that were polled."""
    count = email_sync.tick()
    try:
        names = [p.name for p in providers.all_providers()
                 if hasattr(p, "fetch_messages")]
    except RuntimeError:
        names = []
    return {"synced": count, "providers": names}
```

- [ ] **Step 4: Register the router in main.py**

Add the email router to `main.py` imports and `include_router` calls. (The oauth router include and the `email_sync` lifespan task are wired by phase 1 / phase 4; this task only adds the email data router so its endpoints resolve.)

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`.

Replace the router import line:

```python
from .routers import assistant, calendar, fitness, habits, memory, nutrition, tasks
```

with:

```python
from .routers import assistant, calendar, email, fitness, habits, memory, nutrition, tasks
```

Then add the email include after the fitness includes. Replace:

```python
app.include_router(fitness.router)
app.include_router(fitness.auth_router)
```

with:

```python
app.include_router(fitness.router)
app.include_router(fitness.auth_router)
app.include_router(email.router)
```

Note: phase 1 later swaps `fitness.auth_router` for `oauth.auth_router` and adds the oauth router; that edit is orthogonal to this line and both phases' includes coexist. Do NOT remove `fitness.auth_router` here — that is phase 1's change.

- [ ] **Step 5: Run the email API test — see it pass**

Run:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_api.py -q
```

Expected: `5 passed` (inbox grouping + counts, on-demand body, fallback, 404, sync).

- [ ] **Step 6: Run the full suite and commit**

Confirm the whole suite (including the entire M4 fitness path) stays green, then commit.

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q
```

Expected: all tests pass — prior green count plus the 5 new email-API tests. Report the number (e.g. "N tests passing").

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git checkout m5-email-triage && git add backend/app/routers/email.py backend/app/main.py backend/tests/test_email_api.py && git commit -m "M5: email API router — inbox, on-demand body detail, sync

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit on `m5-email-triage`.


### Task 24: Read-only assistant email tools — get_inbox, get_email

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_tools.py`

**Interfaces:**
- Consumes: store.inbox() / store.get_email(id) / store.upsert_email(...) + NormalizedEmail (phase 3); providers.get('google').get_message + the registry configure([...]) seam (phase 1/4); the tools.execute(name, args) dispatch + _email_action ChatAction shape (Screen already includes "email"). Tests install a local fake email provider via providers.configure and drive tools.execute directly.
- Produces: Two READ-only tool executors + their frozen TOOLS entries in tools.py: get_inbox (compact needs_reply/fyi + needs_reply_count) and get_email (metadata + AI summary + full body fetched live, {"error":...} when missing). No write/send/draft/archive tools. Both return (result, None) — no action card, matching the fitness readers.

- [ ] **Step 1: Write the failing tools test**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_email_tools.py`. It seeds rows via `store.upsert_email`, installs a local fake email provider for the body path, and calls `tools.execute` directly (the executors return `(result, None)`; `execute` json-encodes the result).

```python
"""M5 assistant email tools (read-only): get_inbox compact shape, get_email body + errors."""
import json
from datetime import datetime, timedelta, timezone

from app import providers, tools
from app.providers.base import NormalizedEmail
from app.store import store

NOW = datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)


def _email(source_id: str, subject: str, minutes_ago: int = 0) -> NormalizedEmail:
    return NormalizedEmail(
        source="google",
        source_id=source_id,
        thread_id=f"t-{source_id}",
        from_name="Ada Lovelace",
        from_email="ada@example.com",
        subject=subject,
        snippet="preview",
        received_at=NOW - timedelta(minutes=minutes_ago),
        unread=True,
    )


class FakeEmailProvider:
    name = "google"

    def __init__(self, *, body: str = "Full body.", raise_on_get: bool = False):
        self._body = body
        self._raise = raise_on_get
        self.got: list[str] = []

    def fetch_messages(self, since):
        return []

    def get_message(self, source_id: str) -> str:
        self.got.append(source_id)
        if self._raise:
            raise RuntimeError("gmail down")
        return self._body


def test_email_tools_are_registered_read_only():
    names = {t["name"] for t in tools.TOOLS}
    assert {"get_inbox", "get_email"} <= names
    # No write/send/draft/archive tools this slice.
    assert not any(n in names for n in ("send_email", "draft_email", "archive_email"))


def test_get_inbox_returns_compact_groups_and_count(client):
    store.upsert_email(_email("m1", "Reply please", minutes_ago=1),
                       category="needs_reply", summary=["Wants a reply"])
    store.upsert_email(_email("m2", "Newsletter", minutes_ago=2),
                       category="fyi", summary=["Digest"])

    result_json, action = tools.execute("get_inbox", {})
    result = json.loads(result_json)
    assert action is None  # reader — no action card
    assert result["needs_reply_count"] == 1
    assert [e["subject"] for e in result["needs_reply"]] == ["Reply please"]
    assert [e["subject"] for e in result["fyi"]] == ["Newsletter"]
    # compact: no body ever, and summary carried through
    assert result["needs_reply"][0]["summary"] == ["Wants a reply"]
    assert "body" not in result["needs_reply"][0]


def test_get_email_reads_metadata_summary_and_live_body(client):
    fake = FakeEmailProvider(body="Here is the full text.")
    providers.configure([fake])
    row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])

    result_json, action = tools.execute("get_email", {"email_id": row["id"]})
    result = json.loads(result_json)
    assert action is None
    assert result["subject"] == "The plan"
    assert result["summary"] == ["A plan"]
    assert result["body"] == "Here is the full text."
    assert fake.got == ["m9"]


def test_get_email_body_falls_back_when_gmail_unreachable(client):
    providers.configure([FakeEmailProvider(raise_on_get=True)])
    row = store.upsert_email(_email("m5", "Offline"), category="fyi", summary=[])

    result = json.loads(tools.execute("get_email", {"email_id": row["id"]})[0])
    assert result["body"] == "Message body is unavailable right now."


def test_get_email_errors_for_missing_id(client):
    result = json.loads(tools.execute("get_email", {"email_id": 987654})[0])
    assert "error" in result
```

- [ ] **Step 2: Run the test — see it fail**

Run:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_tools.py -q
```

Expected: failures — `test_email_tools_are_registered_read_only` fails its `assert {"get_inbox", "get_email"} <= names` (the tools aren't registered yet) and the `get_inbox`/`get_email` execute calls return `{"error": "Unknown tool ..."}`, so those assertions fail too.

- [ ] **Step 3: Add the email tool action helper + read-only executors**

Add a `_email_action` helper (mirrors `_fitness_action`) and the two read-only executors to `tools.py`. The `get_email` executor fetches the body live via the registry, with the same fallback string the router uses, so the assistant and the UI agree.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`.

First, add `providers` to the top-level import. Replace:

```python
from . import fitness_sync, food_db, memory_engine, recurrence
```

with:

```python
from . import fitness_sync, food_db, memory_engine, providers, recurrence
```

Next, add the `_email_action` helper right after `_fitness_action` (which ends the action-helper block before the executors comment):

```python


def _email_action(title: str, meta: str) -> dict:
    return {"icon": "mail", "title": title, "meta": meta,
            "cta": "Open email", "screen": "email"}
```

Then add the two executors immediately after `_sync_fitness` (right before the `# ---- task reminders` comment):

```python


# ---- email (real from M5, read-only) ----------------------------------------

_EMAIL_BODY_UNAVAILABLE = "Message body is unavailable right now."


def _compact_email(e: dict) -> dict:
    """List item for the model — sender/subject/summary, never a body."""
    return {"id": e["id"], "from_name": e["from_name"], "from_email": e["from_email"],
            "subject": e["subject"], "snippet": e["snippet"], "unread": e["unread"],
            "category": e["category"], "summary": e["summary"], "when": e["when"]}


def _get_inbox(args: dict):
    inbox = store.inbox()
    return {"needs_reply": [_compact_email(e) for e in inbox["needs_reply"]],
            "fyi": [_compact_email(e) for e in inbox["fyi"]],
            "needs_reply_count": inbox["needs_reply_count"]}, None


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

- [ ] **Step 4: Register the two tool definitions in TOOLS**

Add the frozen `get_inbox` + `get_email` tool definitions to the `TOOLS` list. Insert them after the `sync_fitness` entry — i.e. immediately before the closing `]` of the `TOOLS: list[dict] = [ ... ]` literal.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`. Replace the tail of the `sync_fitness` entry and the list close:

```python
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _sync_fitness},
]
```

with:

```python
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _sync_fitness},
    {"name": "get_inbox",
     "description": "Read the triaged inbox — what needs a reply and FYI items, with AI summaries. Call when the user asks about their email/inbox or what needs a response.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_inbox},
    {"name": "get_email",
     "description": "Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
     "input_schema": {"type": "object", "properties": {
         "email_id": {"type": "integer"}},
         "required": ["email_id"], "additionalProperties": False},
     "run": _get_email},
]
```

(The `DEFINITIONS` / `_BY_NAME` derivations below the list pick these up automatically.)

- [ ] **Step 5: Run the tools test — see it pass**

Run:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_email_tools.py -q
```

Expected: `5 passed` (registration/no-write, compact inbox + count, live body, fallback, missing-id error).

- [ ] **Step 6: Run the full suite and commit**

Confirm the whole suite — including the M4 fitness tools/assistant tests — stays green, then commit.

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q
```

Expected: all tests pass — prior green count plus the 5 new email-tools tests. Report the number (e.g. "N tests passing").

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git checkout m5-email-triage && git add backend/app/tools.py backend/tests/test_email_tools.py && git commit -m "M5: read-only assistant email tools — get_inbox, get_email

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit on `m5-email-triage`.


## Phase: EmailScreen rewrite (live inbox)

### Task 25: EmailScreen rewrite (live inbox) + add email api helpers

> **NOTE (duplication guard):** The frontend fitness connect/status/disconnect repoint to `/api/oauth/*` — including adding `oauthStatus`/`oauthConnect`/`oauthDisconnect` to `api.js` and swapping `api.fitnessStatus/fitnessConnect/fitnessDisconnect` in `FitnessScreen.jsx` — was ALREADY done by the Phase-1 spine (Task 7). This task must NOT re-do it: the old `/api/fitness/connect|status|disconnect` helper strings no longer exist after Task 7, so a blind find-and-delete Edit would hard-fail its anchor. Step 1 here VERIFIES (grep) the oauth repoint is in place and adds ONLY the email helpers (plus the oauth helpers as a defensive fallback if — and only if — Task 7 has not landed). Step 2 VERIFIES FitnessScreen already points at the oauth helpers rather than re-repointing it.

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js` (add email helpers; oauth helpers already added by Task 7)
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx`
- Verify only (repointed by Task 7): `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/FitnessScreen.jsx`
- Test: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build`

**Interfaces:**
- Consumes: Backend (phases 1-5): shared OAuth router at /api/oauth/status, /api/oauth/connect/{provider}, /api/oauth/disconnect/{provider} (ProviderStatus.provider='google'|'whoop', .status='connected'|'needs_reauth', .last_sync_at); email API at GET /api/email/inbox (Inbox: needs_reply[], fyi[], untriaged[], needs_reply_count, unread_count; each EmailOut has id/from_name/from_email/subject/snippet/unread/category/summary[]/when), GET /api/email/{id} (EmailDetail: EmailOut + thread_id + body), POST /api/email/sync. Frontend from the Phase-1 spine (Task 7): `api.js` already exposes `oauthStatus`/`oauthConnect`/`oauthDisconnect` targeting `/api/oauth/*`, and `FitnessScreen.jsx` already uses them. Existing frontend: api.request/ApiError in lib/api.js; Card/Badge/Button/IconButton in components/ui.jsx; Icon in lib/Icon.jsx; kit-mail/kit-bullets/kit-insight/kit-grid/kit-col/kit-stack in styles/kit.css; App.jsx renders <EmailScreen /> with no props.
- Produces: A live EmailScreen: connection-state gating (not-connected Connect-Google CTA, needs_reauth reconnect banner, syncing state, connected two-pane) mirroring FitnessScreen; two-pane inbox grouped Needs reply / FYI (+ untriaged) with the N-need-you count and a reading pane (from/subject/AI-summary bullets/live body). NEW api.js email helpers (emailInbox/emailDetail/emailSync); the oauth helpers are Task 7's and are only verified here (added defensively only if Task 7 has not landed). The inbox `Inbox` Lucide icon. No draft-tone tabs / Send / Edit / Regenerate (deferred). npm run build green.

- [ ] **Step 1: Verify the oauth helpers are present (Task 7) and add ONLY the email helpers to api.js**

The backend OAuth refactor moved connect/status/disconnect onto `/api/oauth/*`, and the Phase-1 spine (Task 7) already repointed `api.js` accordingly and added `oauthStatus`/`oauthConnect`/`oauthDisconnect`. This task must not re-do that — it only ADDS the three email helpers. There is no frontend test harness, so we verify by grep here and by `npm run build` at the end.

First VERIFY Task 7's oauth repoint landed (this is the expected state):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && echo "--- oauth helpers (expect 3) ---" ; grep -c 'oauthStatus\|oauthConnect\|oauthDisconnect' frontend/src/lib/api.js ; echo "--- stale fitness OAuth helpers (expect none) ---" ; grep -n 'fitnessStatus\|fitnessConnect\|fitnessDisconnect\|fitness/connect\|fitness/status\|fitness/disconnect' frontend/src/lib/api.js
```

Expected: the first grep prints `3` (the oauth helpers exist), and the second prints NOTHING (the three fitness OAuth helpers were removed by Task 7). Do NOT attempt to find-and-delete `fitness/connect|status|disconnect` here — those strings are already gone.

- **If the oauth helpers ARE present (expected — Task 7 landed):** add ONLY the email helpers. Immediately after the closing of the fitness DATA section (right after the `fitnessSync: () => request('/api/fitness/sync', { method: 'POST' }),` line), insert:

```js

  // Email (M5) — the inbox/detail come straight from the emails table server-
  // side (list never triggers a live Gmail call). Only emailDetail fetches the
  // body live, with a graceful fallback string if Gmail is unreachable. Bodies
  // are never persisted. emailSync kicks a foreground sync pass.
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),
```

- **If the oauth helpers are ABSENT (defensive — Task 7 not merged yet):** land Task 7 first (it owns the fitness OAuth repoint). If that is not possible, add the oauth helpers alongside the email helpers here as a fallback, inserting BOTH blocks after the `fitnessSync` line:

```js

  // OAuth (shared, M5) — provider-agnostic connect/status/disconnect. Both
  // WHOOP (fitness) and Google (email) authorize through these. Tokens never
  // cross this boundary — status responses omit them.
  oauthStatus: () => request('/api/oauth/status'),
  oauthConnect: (provider) => request(`/api/oauth/connect/${provider}`),
  oauthDisconnect: (provider) => request(`/api/oauth/disconnect/${provider}`, { method: 'POST' }),

  // Email (M5) — the inbox/detail come straight from the emails table server-
  // side (list never triggers a live Gmail call). Only emailDetail fetches the
  // body live, with a graceful fallback string if Gmail is unreachable. Bodies
  // are never persisted. emailSync kicks a foreground sync pass.
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),
```

Do NOT change any other helper. Save the file. No commit yet — the EmailScreen rewrite in later steps consumes the email helpers; commit them together at the end so the tree stays compiling.

- [ ] **Step 2: Verify FitnessScreen already uses the shared oauth helpers (Task 7)**

The Phase-1 spine (Task 7) already repointed FitnessScreen's connect/status/disconnect to `api.oauthStatus()` / `api.oauthConnect('whoop')` / `api.oauthDisconnect('whoop')`. Do NOT re-repoint it — confirm it is already correct:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && echo "--- oauth calls in FitnessScreen (expect >=1 of each) ---" ; grep -n 'oauthStatus\|oauthConnect\|oauthDisconnect' frontend/src/screens/FitnessScreen.jsx ; echo "--- stale fitness OAuth calls (expect none) ---" ; grep -n 'fitnessStatus\|fitnessConnect\|fitnessDisconnect' frontend/src/screens/FitnessScreen.jsx
```

Expected: the first grep shows `api.oauthStatus()`, `api.oauthConnect('whoop')`, `api.oauthDisconnect('whoop')`; the second prints NOTHING. The fitness DATA calls (`fitnessToday`, `fitnessWorkouts`, `fitnessWeek`, `fitnessSync`, `logWorkout`, `deleteWorkout`) stay on `/api/fitness/*` and must be untouched. `OAuthStatus` is structurally identical to the old `FitnessStatus` (`{connected, providers:[{provider, status, connected_at, last_sync_at, provider_user_id}]}`), so the existing `whoop = (status?.providers || []).find((p) => p.provider === 'whoop')` logic in FitnessScreen is already correct.

(Only if Task 7 has NOT landed and the grep shows stale `api.fitnessStatus/fitnessConnect/fitnessDisconnect` calls: repoint them to the oauth helpers as Task 7 specifies — but the intended path is that Task 7 already did this.)

Verify the whole app still compiles:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
```

Expected: build succeeds — a line like `✓ built in <N>s` and a `dist/` bundle written, exit code 0. (EmailScreen still renders the hardcoded sample at this point — that is fine; it compiles.)

Commit the email helpers (and the oauth helpers only if this task had to add them defensively):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git checkout m5-email-triage 2>/dev/null || git checkout -b m5-email-triage; git add frontend/src/lib/api.js; git commit -m "$(cat <<'EOF'
M5 frontend: add email api helpers (emailInbox/emailDetail/emailSync)

The oauth connect/status/disconnect helpers + FitnessScreen repoint were done by
the Phase-1 spine (Task 7); this only adds the three email helpers.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Register the `inbox` Lucide icon**

The rewritten EmailScreen's not-connected and empty states use an `inbox` icon (parallel to Fitness's `activity` glyph). Every icon must be statically registered in `Icon.jsx` or `<Icon name="inbox" />` renders nothing (and warns in dev). `mail`, `sparkles`, `check`, `check-check`, `alert-triangle`, `refresh-cw`, `unplug` are already registered — only `inbox` is new.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`.

1) Add the import. Find the line:

```js
  House,
```

and insert `Inbox,` right after it (keeping the alphabetical grouping — `Inbox` sorts after `House`):

```js
  House,
  Inbox,
```

2) Add the name→component entry. Find the line in the `ICONS` map:

```js
  house: House,
```

and insert after it:

```js
  house: House,
  inbox: Inbox,
```

Save. Do NOT reorder or remove any other icon. `Inbox` is a real export of `lucide-react` (^0.460.0, already installed), so no dependency change.

Verify it compiles:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
```

Expected: build succeeds, exit code 0.

Commit:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/lib/Icon.jsx; git commit -m "$(cat <<'EOF'
M5 frontend: register inbox lucide icon for the email screen

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Rewrite EmailScreen to live data (connection states + two-pane inbox)**

Replace the entire hardcoded-sample EmailScreen with a live, self-fetching screen that mirrors FitnessScreen's convention: in-component `useState`/`useEffect` fetch (App.jsx renders `<EmailScreen />` with no props), `oauthStatus()` drives the connection-state gate, `emailInbox()` feeds the two-pane view, and `emailDetail(id)` lazily loads the reading-pane body. Draft-tone tabs / Send / Edit / Regenerate / Archive are OMITTED (deferred slice — no dead UI): untriaged rows show no category badge, FYI rows show the 'filed as FYI' note without an archive button.

Connection states, in the same spirit as FitnessScreen:
- `status === null` → nothing decided yet; render the skeleton connected shell (empty lists) so there's no flash.
- not connected (`status && !connected && !needsReauth`) → single Connect-Google CTA card.
- `needsReauth` (google provider `status === 'needs_reauth'`) → reconnect banner above the panes.
- syncing (connected, no reauth, inbox has zero messages across all groups, and google has no `last_sync_at` yet) → a 'Syncing…' banner with a Check-again button.

  NOTE on the `syncing` gate: it is effectively a **pre-first-tick** state, and this matches FitnessScreen exactly. `email_sync._sync_provider` always calls `store.set_provider_synced` (stamping `last_sync_at` even on a 0-message pass), so once the first backfill tick finishes, `last_sync_at` is non-null and a genuinely-empty inbox falls through to the normal "Inbox is clear" empty state rather than showing "Syncing…". The window in which "Syncing…" shows is the brief interval before the first tick completes. This is acceptable for the slice. If a longer syncing indicator is ever wanted, gate on an explicit account status or a backend message count rather than on `last_sync_at` — not a blocker here.

Data shapes consumed (frozen by the contract):
- `oauthStatus()` → `{connected, providers:[{provider, status, last_sync_at, ...}]}`. Find the `google` provider.
- `emailInbox()` → `{needs_reply:[EmailOut], fyi:[EmailOut], untriaged:[EmailOut], needs_reply_count, unread_count}`. Each `EmailOut`: `{id, from_name, from_email, subject, snippet, unread, category, summary:[], when}`.
- `emailDetail(id)` → `EmailOut` + `{thread_id, body}` (body is the live Gmail fetch or the fallback string; already resolved server-side).

Overwrite `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/EmailScreen.jsx` with EXACTLY:

```jsx
/* Scuffed OS — Email triage (live, synced with Gmail via Google OAuth).
   Owns its own state (App.jsx renders <EmailScreen /> with no props), mirroring
   FitnessScreen's in-component fetch convention. /api/oauth/status drives which
   connection state renders; /api/email/inbox feeds the two-pane view. The inbox
   comes straight from the emails table server-side (never a live Gmail call), so
   it works while a sync is mid-flight or Gmail is down — it shows what's landed.
   Only the reading pane fetches a body live (/api/email/{id}), with a graceful
   fallback string. Message bodies are never persisted; tokens never reach the
   client. Draft/send is a later slice — no draft UI here. */
import React from 'react'
import { Card, Badge, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

/* Category → the left-column group label + list. Untriaged messages still show
   (under 'Other') so a triage hiccup never hides mail. */
const GROUPS = [
  { key: 'needs_reply', label: 'Needs reply' },
  { key: 'fyi', label: 'FYI' },
  { key: 'untriaged', label: 'Other' },
]

export function EmailScreen() {
  const [status, setStatus] = React.useState(null)   // null = /status not answered yet
  const [inbox, setInbox] = React.useState(null)     // null = not loaded
  const [selId, setSelId] = React.useState(null)
  const [detail, setDetail] = React.useState(null)   // full email incl. body, for selId

  const refresh = React.useCallback(() => {
    api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.emailInbox().then((i) => { if (i) setInbox(i) }).catch(() => {})
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const google = (status?.providers || []).find((p) => p.provider === 'google') || null
  const connected = !!google
  const needsReauth = google?.status === 'needs_reauth'

  const groups = React.useMemo(() => GROUPS.map((g) => ({
    ...g, items: (inbox?.[g.key] || []),
  })), [inbox])
  const total = groups.reduce((n, g) => n + g.items.length, 0)
  // Connected, no reauth, nothing has landed yet, and google has never synced →
  // first backfill is still running. This is a pre-first-tick state (matches
  // FitnessScreen): email_sync always stamps last_sync_at, so once the first
  // tick completes a genuinely-empty inbox shows the "Inbox is clear" state, not
  // this banner.
  const syncing = connected && !needsReauth && inbox != null && total === 0 && !google?.last_sync_at

  // Auto-select the first message once the inbox lands (and keep a valid
  // selection if the current one disappears after a refresh).
  React.useEffect(() => {
    if (total === 0) { setSelId(null); return }
    const flat = groups.flatMap((g) => g.items)
    if (selId == null || !flat.some((e) => e.id === selId)) setSelId(flat[0].id)
  }, [groups, total, selId])

  // Load the body (and fresh metadata) whenever the selection changes.
  React.useEffect(() => {
    if (selId == null) { setDetail(null); return }
    let live = true
    setDetail(null)
    api.emailDetail(selId).then((d) => { if (live && d) setDetail(d) }).catch(() => {})
    return () => { live = false }
  }, [selId])

  const connect = () => {
    api.oauthConnect('google')
      .then((r) => { if (r?.authorize_url) window.location = r.authorize_url })
      .catch(() => {})
  }
  const sync = () => { api.emailSync().then(() => refresh()).catch(() => {}) }

  // —— not connected: single CTA card ——
  if (status && !connected && !needsReauth) {
    return (
      <Card variant="flat" style={{ textAlign: 'center', padding: '56px 24px' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="mail" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect Google</h3>
        <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Sync your Gmail inbox into Scuffed OS. Messages are triaged into what needs a reply vs. FYI, with AI summaries. Read-only — your tokens stay server-side and message bodies are never stored.</p>
        <Button variant="primary" iconLeft={<Icon name="mail" />} onClick={connect}>Connect Google</Button>
      </Card>
    )
  }

  const eyebrow = google?.last_sync_at
    ? `Synced with Gmail · ${new Date(google.last_sync_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : 'Connected with Gmail'
  const needCount = inbox?.needs_reply_count ?? 0

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
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
        <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
          <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
            <Icon name="refresh-cw" />
          </div>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Syncing…</h3>
          <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Pulling and triaging your inbox from Gmail. This usually takes a moment — hang tight.</p>
          <Button variant="secondary" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Check again</Button>
        </Card>
      )}

      {!syncing && (
        <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1.15fr' }}>
          <Card title="Inbox" eyebrow={eyebrow}
            action={
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                {needCount > 0 && <Badge color="green" dot>{needCount} need you</Badge>}
                <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
              </div>
            }>
            {total === 0 && <p className="kit-muted" style={{ marginTop: 6 }}>Inbox is clear — nothing to triage right now.</p>}
            {groups.map((g) => g.items.length === 0 ? null : (
              <div key={g.key}>
                <p className="sa-card__eyebrow" style={{ margin: '12px 0 4px' }}>{g.label}</p>
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
              </div>
            ))}
          </Card>

          <div className="kit-col">
            {detail ? (
              <>
                <Card eyebrow={`${detail.from_name || detail.from_email}${detail.from_email && detail.from_name ? ` · ${detail.from_email}` : ''}`} title={detail.subject || '(no subject)'}>
                  {(detail.summary || []).length > 0 && (
                    <>
                      <p className="sa-card__eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}><Icon name="sparkles" style={{ width: 13, height: 13 }} />AI summary</p>
                      <div className="kit-bullets" style={{ marginBottom: 14 }}>
                        {detail.summary.map((b, i) => (
                          <div className="kit-bullet" key={i}><Icon name="check" />{b}</div>
                        ))}
                      </div>
                    </>
                  )}
                  <div className="kit-draft">{detail.body}</div>
                </Card>

                {detail.category === 'fyi' && (
                  <Card variant="sunken">
                    <div className="kit-insight">
                      <div className="kit-insight__icon"><Icon name="check-check" /></div>
                      <p>No reply needed — I've filed this as <strong>FYI</strong>.</p>
                    </div>
                  </Card>
                )}
              </>
            ) : (
              <Card><p className="kit-muted">{selId == null ? 'Select a message to read it.' : 'Loading…'}</p></Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

Notes on choices (all satisfy the contract §M and the global constraints):
- No draft-tone tabs, Send/Edit/Regenerate, or Archive button — deferred slice, no dead UI.
- Untriaged (`category === null`) rows render under the 'Other' group with no badge and no FYI note; only `category === 'fyi'` shows the filed-as-FYI note.
- The reading pane always shows the body from `emailDetail` (the server already substitutes the fallback string when Gmail is unreachable) inside `kit-draft` (an existing pre-wrap block).
- The inbox list is served entirely from `emailInbox()` (the emails table) — the screen never issues a live Gmail call for the list, matching the privacy rule.

Save the file.

Verify the app builds:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
```

Expected: build succeeds — `✓ built in <N>s`, `dist/` written, exit code 0. No `[Icon] unknown icon` concerns (all icon names used — `mail`, `sparkles`, `check`, `check-check`, `alert-triangle`, `refresh-cw` — are registered; `inbox` was registered in the prior step but is not referenced here, which is fine).

- [ ] **Step 5: Build clean + manual verification, then commit**

Final gate for the frontend phase. The frontend has no pytest — `npm run build` (Vite production build = full parse/transform/bundle of every touched module) is the automated check, backed by concrete manual verification steps against the running app.

1) Clean production build:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && rm -rf dist && npm run build
```

Expected: exit code 0, ends with a line like `✓ built in <N>s`, and `dist/index.html` + `dist/assets/*.js` exist. No `Could not resolve` / `is not exported` errors (which would flag a bad import — e.g. a mistyped `api.*` helper or an unregistered icon import in `Icon.jsx`).

2) Confirm the dead `/api/fitness/connect|status|disconnect` routes are gone from the client and the new ones are present:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && grep -n 'fitnessConnect\|fitnessStatus\|fitnessDisconnect' frontend/src/ -r ; echo "--- oauth/email helpers ---" ; grep -n 'oauthStatus\|oauthConnect\|oauthDisconnect\|emailInbox\|emailDetail\|emailSync' frontend/src/lib/api.js
```

Expected: the first grep prints NOTHING (no remaining references to the removed helpers anywhere in `frontend/src/`), and the second grep lists the three oauth + three email helper definitions in `api.js`. (The `grep` returning non-zero on the first command with no match is expected and fine — it's on its own line, not in an `&&` chain.)

3) Manual verification against the live app. Start backend + frontend (per the run-scuffedos convention) and open the dashboard:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m uvicorn app.main:app --reload --port 8000
```
(in a second shell)
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run dev
```

Then in the browser (Vite dev URL, typically http://localhost:5173), navigate to the Email screen and verify:
- (a) NOT CONNECTED (fresh DB / Google not connected): the Email screen shows the single 'Connect Google' CTA card (mail glyph, read-only copy) — NOT the old hardcoded Priya/Oak-St sample. Clicking 'Connect Google' calls `GET /api/oauth/connect/google` and navigates to the returned `authorize_url` (check the Network tab: a 200 on `/api/oauth/connect/google`, then a top-level navigation to accounts.google.com). If Google isn't configured server-side you'll see the request but the redirect may 4xx — that's a backend-config concern, the frontend behavior (issue connect → navigate) is what's being verified.
- (b) CONNECTED WITH DATA (seed a couple of `emails` rows, or after a real sync): two-pane layout renders — left column grouped 'Needs reply' / 'FYI' / 'Other' with the green 'N need you' badge equal to `needs_reply_count`; clicking a row activates it (accent tint) and the right pane loads sender · email, subject, the AI-summary bullets (when present), and the body text (from `GET /api/email/{id}`; confirm one such request fires per selection in the Network tab). An FYI message shows the 'filed as FYI' note; a needs_reply/untriaged message does NOT. Confirm there are NO draft-tone tabs and NO Send / Edit / Regenerate / Archive buttons anywhere.
- (c) FITNESS NOT REGRESSED: open the Fitness screen — its status/connect/disconnect now go through `/api/oauth/*` (verify `GET /api/oauth/status` fires on load in the Network tab, not `/api/fitness/status`), while Today/Workouts/Week still load from `/api/fitness/*`. Connect/Disconnect WHOOP still work.
- (d) SYNCING / NEEDS-REAUTH (optional, if easy to reproduce): a connected-but-never-synced empty inbox shows the 'Syncing…' banner with 'Check again'; a `needs_reauth` google provider shows the reconnect banner above the panes.

4) Commit:

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/screens/EmailScreen.jsx; git commit -m "$(cat <<'EOF'
M5 frontend: rewrite EmailScreen to live inbox (connection states + two-pane triage)

Live /api/oauth/status gate (Connect Google CTA / needs_reauth / syncing) +
two-pane inbox from /api/email/inbox grouped Needs reply / FYI / Other with the
N-need-you count, and a reading pane loading the body live via /api/email/{id}.
Draft-tone tabs, Send/Edit/Regenerate and Archive omitted (deferred slice).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: the commit lands on `m5-email-triage`. This completes the EmailScreen frontend phase — build green, fitness path intact, no dead draft UI.


## Phase: Privacy update + smoke + live validation

### Task 26: Privacy policy: add Gmail/Google email domain (all three copies)

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`
- Modify: `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`

**Interfaces:**
- Consumes: The live docs/privacy-policy.md (canonical), the corp-site copy scuffed-corporation/privacy/index.html, and the public gist 439cee7cba3ac9077da6a5b81f83527c. Google/Gmail read-only email connect + triage-to-Anthropic + bodies-not-stored behavior built by phases 1-6.
- Produces: All three privacy-policy copies (markdown canonical, corp-site HTML, gist) updated with: a Google (Gmail) row in the Section 3 provider table, an updated Anthropic 'what is shared' cell, an updated Supabase 'what is shared' cell, and a new Section 4 Gmail-data paragraph block. The three copies stay verbatim-in-sync (allowing for HTML entity encoding on the site).

- [ ] **Step 1: Edit the canonical markdown: Section 3 table (add Google row, update Anthropic + Supabase 'what is shared')**

This is a docs-only slice with no automated test — the guardrail is that the three copies stay in sync and read correctly. Do the markdown first (it is the canonical source), then mirror to the HTML site and the gist.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`.

**(a)** Update the **Anthropic** row's "What is shared" cell to note the email triage input. Replace the line:

```
| **Anthropic** (Claude API) | Powers the AI assistant and memory extraction | Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, etc.) in order to respond |
```

with:

```
| **Anthropic** (Claude API) | Powers the AI assistant, memory extraction, and email triage | Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, etc.) in order to respond. When you connect Gmail, each email's sender, subject, preview snippet, and a bounded body excerpt (~2 KB) are sent to Anthropic to classify it and generate a short summary |
```

**(b)** Update the **Supabase** row's "What is shared" cell to include email metadata (and make explicit that bodies are not stored). Replace:

```
| **Supabase** | Managed Postgres database hosting | Structured app data: tasks, events, habits, nutrition logs, conversations, memories and their embeddings, and synced WHOOP data |
```

with:

```
| **Supabase** | Managed Postgres database hosting | Structured app data: tasks, events, habits, nutrition logs, conversations, memories and their embeddings, synced WHOOP data, and email metadata (sender, subject, snippet, and AI-derived category/summary — no message bodies) |
```

**(c)** Add a **Google (Gmail)** row to the Section 3 table, immediately after the WHOOP row. Replace:

```
| **WHOOP** | Health data source (only if you connect it) | OAuth authorization; ScuffedOS receives data from WHOOP, not the reverse |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |
```

with:

```
| **WHOOP** | Health data source (only if you connect it) | OAuth authorization; ScuffedOS receives data from WHOOP, not the reverse |
| **Google (Gmail)** | Email source, read-only (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage — see Section 4 |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |
```

**Run:**

```bash
grep -c "Google (Gmail)" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "and email triage" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "no message bodies" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
```

**Expected:** each prints `1`.

Do NOT commit yet — the section-4 paragraph (next step) lands in the same commit.

- [ ] **Step 2: Edit the canonical markdown: add a Gmail data paragraph (new Section 4 subsection) + retention/storage mentions**

Continue editing `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md`.

**(a)** Add a Gmail-data block parallel to the WHOOP Section 4. Insert it right after the WHOOP section's closing sentence. Replace:

```
ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by WHOOP.

## 5. Data storage and security
```

with:

```
ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by WHOOP.

If you choose to connect Gmail:

- Access is **read-only** and is granted only after you explicitly authorize ScuffedOS through Google's OAuth consent flow (the `gmail.readonly` scope). You can review and revoke this access at any time from your Google Account's security settings.
- ScuffedOS reads your inbox messages to display them and to triage them. For each message, the sender, subject, preview snippet, and a bounded plain-text body excerpt (~2 KB) are sent to **Anthropic** to classify the message (needs-reply vs. FYI) and generate a short summary. Only the derived category and summary — never the message body — are stored.
- **Message bodies are not stored.** The inbox list and AI summaries live in the database; the full body of a message is fetched live from the Gmail API only when you open that message, and is never written to disk.
- Gmail data is never sold, never shared with third parties for their own purposes, and never used for advertising.
- You can disconnect Gmail within ScuffedOS at any time. On disconnect, stored email metadata and your Google OAuth tokens are deleted, and ScuffedOS revokes its Google access token. As with all deletions, this is honored within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.

## 5. Data storage and security
```

**(b)** Update Section 6 (retention/deletion) to mention Gmail disconnect. Replace:

```
Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4.
```

with:

```
Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens.
```

**(c)** Update Section 7 (rights and choices) to name Gmail alongside WHOOP. Replace:

```
You can decline to connect WHOOP (the rest of the app works without it), disable voice dictation by simply not using the microphone, and disconnect any integration at any time.
```

with:

```
You can decline to connect WHOOP or Gmail (the rest of the app works without either), disable voice dictation by simply not using the microphone, and disconnect any integration at any time.
```

**(d)** Update the intro line in the opening paragraph to name Gmail as a connected service. Replace:

```
It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP.
```

with:

```
It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP and Gmail.
```

**Run:**

```bash
grep -c "gmail.readonly" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "Message bodies are not stored" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "sponsored by Google" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
grep -c "such as WHOOP and Gmail" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md
```

**Expected:** each prints `1`.

**Commit (canonical markdown only — the two copies follow in the next steps):**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git checkout m5-email-triage
git add docs/privacy-policy.md
git commit -m "docs(privacy): add Gmail read-only email domain to the policy

Section 3 gains a Google (Gmail) provider row; Anthropic + Supabase rows note
the triage excerpt and stored email metadata (no bodies). New Section 4
Gmail block: read-only OAuth, subject+body-excerpt to Anthropic for triage,
bodies fetched-not-stored, tokens+metadata deleted on disconnect.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**Expected:** commit succeeds on branch `m5-email-triage`.

- [ ] **Step 3: Mirror to the corp-site HTML copy (scuffed-corporation/privacy/index.html)**

The corp site is a **separate git repo** at `~/PycharmProjects/scuffed-corporation`. Apply the same content in HTML (using HTML entities to match the site's existing style: `&rsquo;`, `&ldquo;`/`&rdquo;`, `&mdash;`, `&middot;`).

Edit `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`.

**(a)** Intro line — replace:

```html
        <p>This policy describes what data Scuffed OS stores, how it is used, and which service providers process it. It applies to the Scuffed OS application and any data obtained through connected services such as WHOOP.</p>
```

with:

```html
        <p>This policy describes what data Scuffed OS stores, how it is used, and which service providers process it. It applies to the Scuffed OS application and any data obtained through connected services such as WHOOP and Gmail.</p>
```

**(b)** Anthropic table row — replace:

```html
              <tr>
                <th scope="row"><strong>Anthropic</strong> (Claude API)</th>
                <td>Powers the AI assistant and memory extraction</td>
                <td>Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, etc.) in order to respond</td>
              </tr>
```

with:

```html
              <tr>
                <th scope="row"><strong>Anthropic</strong> (Claude API)</th>
                <td>Powers the AI assistant, memory extraction, and email triage</td>
                <td>Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, etc.) in order to respond. When you connect Gmail, each email&rsquo;s sender, subject, preview snippet, and a bounded body excerpt (~2&nbsp;KB) are sent to Anthropic to classify it and generate a short summary</td>
              </tr>
```

**(c)** Supabase table row — replace:

```html
                <td>Structured app data: tasks, events, habits, nutrition logs, conversations, memories and their embeddings, and synced WHOOP data</td>
```

with:

```html
                <td>Structured app data: tasks, events, habits, nutrition logs, conversations, memories and their embeddings, synced WHOOP data, and email metadata (sender, subject, snippet, and AI-derived category/summary &mdash; no message bodies)</td>
```

**(d)** Insert the Google row after the WHOOP row — replace:

```html
              <tr>
                <th scope="row"><strong>WHOOP</strong></th>
                <td>Health data source (only if you connect it)</td>
                <td>OAuth authorization; Scuffed OS receives data from WHOOP, not the reverse</td>
              </tr>
              <tr>
                <th scope="row"><strong>USDA FoodData Central</strong></th>
```

with:

```html
              <tr>
                <th scope="row"><strong>WHOOP</strong></th>
                <td>Health data source (only if you connect it)</td>
                <td>OAuth authorization; Scuffed OS receives data from WHOOP, not the reverse</td>
              </tr>
              <tr>
                <th scope="row"><strong>Google</strong> (Gmail)</th>
                <td>Email source, read-only (only if you connect it)</td>
                <td>OAuth authorization; Scuffed OS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage &mdash; see <a href="#gmail-data">Section 4</a></td>
              </tr>
              <tr>
                <th scope="row"><strong>USDA FoodData Central</strong></th>
```

**(e)** Insert a Gmail data `<section>` after the WHOOP section's closing `</section>`. Replace:

```html
        <p>Scuffed OS is an independent application and is not affiliated with, endorsed by, or sponsored by WHOOP.</p>
      </div>
    </section>

    <!-- 05 / data storage and security -->
```

with:

```html
        <p>Scuffed OS is an independent application and is not affiliated with, endorsed by, or sponsored by WHOOP.</p>
      </div>
    </section>

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

    <!-- 05 / data storage and security -->
```

**(f)** Section 6 retention line — replace:

```html
Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in <a href="#whoop-data">Section 4</a>.
```

with:

```html
Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in <a href="#whoop-data">Section 4</a>; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens.
```

**(g)** Section 7 line — replace:

```html
You can decline to connect WHOOP (the rest of the app works without it), disable voice dictation by simply not using the microphone, and disconnect any integration at any time.
```

with:

```html
You can decline to connect WHOOP or Gmail (the rest of the app works without either), disable voice dictation by simply not using the microphone, and disconnect any integration at any time.
```

**Run** (verify the HTML edits and that the file is still well-formed):

```bash
grep -c 'id="gmail-data"' /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c 'Google</strong> (Gmail)' /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
grep -c 'no message bodies' /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
python3 -c "import html.parser,sys; p=html.parser.HTMLParser(); p.feed(open('/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html').read()); print('html-parses-ok')"
```

**Expected:** the three `grep -c` print `1`, `1`, `1`; the python line prints `html-parses-ok` (no exception).

**Commit in the corp-site repo:**

```bash
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation
git add privacy/index.html
git commit -m "privacy: add Gmail read-only email domain (sync with app policy)

Mirrors docs/privacy-policy.md in the ScuffedOS repo: Google (Gmail) provider
row, updated Anthropic + Supabase cells, and a Section 4a Gmail block
(read-only, triage excerpt to Anthropic, bodies fetched-not-stored, tokens +
metadata deleted on disconnect).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**Expected:** commit succeeds. (The corp site is a static-HTML repo; deploying it to scuffedcorporation.com is out of scope for this slice — the commit is the deliverable, matching the WHOOP-era convention.)

- [ ] **Step 4: Sync the public gist (439cee7cba3ac9077da6a5b81f83527c) to the updated markdown**

The gist hosts the same markdown at `https://gist.github.com/daschempp/439cee7cba3ac9077da6a5b81f83527c` (file `privacy-policy.md`). It must match the canonical `docs/privacy-policy.md` verbatim. Push the updated file via the GitHub API.

**Run** (uploads the current canonical markdown as the gist file content; `jq -Rs` JSON-encodes the whole file safely):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
CONTENT=$(jq -Rs . < docs/privacy-policy.md)
gh api -X PATCH gists/439cee7cba3ac9077da6a5b81f83527c \
  -f 'description=ScuffedOS Privacy Policy' \
  --raw-field "files[privacy-policy.md][content]=$(jq -Rs . < docs/privacy-policy.md | sed -e 's/^"//' -e 's/"$//')" \
  > /dev/null 2>&1 || true
```

If the `--raw-field` form is awkward on your shell, use the equivalent Python one-liner (same result, avoids shell-escaping the markdown):

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

**Expected:** prints `gist-patched` (the Python form) with no error.

**Verify the gist now matches the canonical markdown byte-for-byte:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
gh gist view 439cee7cba3ac9077da6a5b81f83527c --raw > /tmp/gist_privacy.md
diff docs/privacy-policy.md /tmp/gist_privacy.md && echo "GIST-IN-SYNC"
```

**Expected:** `diff` prints nothing and the line `GIST-IN-SYNC` appears (exit 0). If `diff` shows differences, re-run the Python PATCH block — the gist API is last-write-wins.

No git commit for this step (the gist is not in the repo). This completes the three-copy sync: canonical markdown (committed), corp-site HTML (committed), gist (patched).


### Task 27: smoke_google.py — live Gmail pipeline smoke test (not CI)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_google.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py`

**Interfaces:**
- Consumes: The real GoogleProvider (phases 2 + 4), email_sync (phase 4), the emails table + store methods (phase 3), config additions (phase 2), and the shared oauth callback (phase 1) that stores the google provider_account.
- Produces: backend/app/smoke_google.py — a manual `python -m app.smoke_google` end-to-end check that drives the REAL GoogleProvider against live Gmail, runs an email_sync tick, and reads the emails table back. Prints the authorize URL and exits 2 when Google isn't connected; exits 0 on full pass, 1 on a pipeline failure. Not imported by any test; not in CI.

- [ ] **Step 1: Write smoke_google.py (mirrors smoke_whoop.py; real GoogleProvider + email_sync + emails read-back)**

This is a manual live-credential script, not a pytest — it is never imported by the suite and must not reach the network on import (all live calls are inside `main()`). The only automated guardrail is that it imports cleanly (byte-compiles) and that the full suite stays green (unaffected). Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/smoke_google.py`:

```python
"""End-to-end smoke test for the live Gmail pipeline (M5).

Drives the REAL GoogleProvider against Google's production OAuth + the Gmail
API and the real email_sync engine, then reads the emails table back. Unlike
the pytest suite (which fakes every provider and the triage LLM via conftest),
this makes real authenticated Gmail requests, sends real triage input to
Anthropic, and writes synced rows to the configured database.

Google OAuth needs a one-time browser authorize, so this runs in two modes:

  * Already connected -- a `provider_accounts` row for 'google' exists with
    tokens. The script refreshes if needed, runs a real email_sync tick, and
    asserts messages landed in the emails table with triage populated.
  * Not connected -- prints the authorize URL (built from settings) and the
    exact steps to connect, then exits 2 (setup needed, not a pipeline
    failure).

Google ALLOWS localhost redirect URIs, so no tunnel is needed: register
http://localhost:8000/auth/google/callback on the OAuth client and point
GOOGLE_REDIRECT_URI at it.

Prerequisites (see the M5 design spec): GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
set, ANTHROPIC_API_KEY set (triage runs live), and the redirect URI above
registered on the Google Cloud OAuth Web client.

Run it by hand once credentials are live (NOT in CI):

    python -m app.smoke_google

Exit status: 0 if every leg passed, 1 on a pipeline failure, 2 if Google isn't
connected yet (run the OAuth connect first).
"""
from __future__ import annotations

import logging
import secrets
import sys

from . import email_sync, providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help(provider) -> None:
    state = secrets.token_urlsafe(16)
    print("\nGoogle is not connected yet. To connect end-to-end:")
    print("  1. Start the backend on http://localhost:8000 (Google allows localhost).")
    print("  2. Register http://localhost:8000/auth/google/callback as an authorized")
    print("     redirect URI on the Google Cloud OAuth Web client, and set")
    print("     GOOGLE_REDIRECT_URI to match.")
    print("  3. Open this authorize URL in a browser and approve:")
    print("\n     " + provider.authorize_url(state))
    print("\n  4. Google redirects to /auth/google/callback, which stores tokens.")
    print("     Re-run `python -m app.smoke_google` afterwards.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS -- live Gmail pipeline smoke test")
    print(f"  owner={settings.owner!r}  redirect_uri={settings.google_redirect_uri!r}  "
          f"backfill_count={settings.email_backfill_count}")

    print("\nPreconditions:")
    if not r.check(bool(settings.google_client_id and settings.google_client_secret),
                   "Google credentials configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)"):
        print("\nAborting: Google client credentials are not set.")
        return 1
    if not r.check(bool(settings.database_url),
                   "DATABASE_URL configured (synced rows need a database)"):
        print("\nAborting: no DATABASE_URL -- sync writes nowhere.")
        return 1
    r.check(bool(settings.anthropic_api_key),
            "ANTHROPIC_API_KEY configured (triage runs live; without it rows stay untriaged)")

    provider = providers.get("google")
    if not r.check(provider is not None, "Google provider registered"):
        return 1

    account = store.get_provider_account("google")
    if account is None:
        r.check(False, "Google account connected (provider_accounts row exists)",
                "not connected -- see steps below")
        _print_connect_help(provider)
        return 2
    r.check(True, "Google account connected",
            f"status={account['status']} provider_user_id={account.get('provider_user_id')}")

    try:
        print("\n1. Token validity (refresh if within the expiry guard):")
        tokens = store.get_provider_tokens("google")
        if not r.check(tokens is not None and bool(tokens.access_token),
                       "access token present server-side"):
            return 1
        provider.set_tokens(tokens)

        print("\n2. Live fetch (Gmail INBOX messages):")
        messages = provider.fetch_messages(None)
        r.check(True, "messages fetched", f"{len(messages)}")
        r.check(bool(messages), "Gmail returned at least one INBOX message")
        for m in messages[:3]:
            print(f"        - {m.subject!r} from {m.from_name!r} <{m.from_email}> "
                  f"unread={m.unread} at {m.received_at}")
            r.check(bool(m.source_id), "message has a source_id")
            r.check(m.source == "google", f"source is 'google' (got {m.source!r})")
            r.check(len(m.body_excerpt) <= 4096,
                    f"body_excerpt is bounded (~2 KB): {len(m.body_excerpt)} chars")

        print("\n3. On-demand body fetch (first message):")
        if messages:
            body = provider.get_message(messages[0].source_id)
            r.check(isinstance(body, str) and bool(body.strip()),
                    "get_message returned a non-empty body", f"{len(body)} chars")

        print("\n4. Real email_sync tick (provider -> triage -> emails table):")
        upserted = email_sync.tick()
        r.check(isinstance(upserted, int), "tick returned a count of upserted rows", str(upserted))
        synced = store.list_provider_accounts()
        g_row = next((a for a in synced if a["provider"] == "google"), None)
        r.check(g_row is not None and g_row["status"] == "connected",
                "sync left the account 'connected' (no auth failure)")
        r.check(g_row is not None and g_row["last_sync_at"] is not None,
                "last_sync_at was stamped")

        print("\n5. Read-back (emails table, no live call):")
        inbox = store.inbox()
        total = len(inbox["needs_reply"]) + len(inbox["fyi"]) + len(inbox["untriaged"])
        print(f"        inbox: needs_reply={len(inbox['needs_reply'])} "
              f"fyi={len(inbox['fyi'])} untriaged={len(inbox['untriaged'])} "
              f"needs_reply_count={inbox['needs_reply_count']} "
              f"unread_count={inbox['unread_count']}")
        r.check(total > 0, "emails table populated (inbox has messages)")
        triaged = inbox["needs_reply"] + inbox["fyi"]
        if settings.anthropic_api_key:
            r.check(bool(triaged),
                    "at least one message was triaged (category + summary present)")
            for e in triaged[:3]:
                print(f"        - [{e['category']}] {e['subject']!r} :: "
                      + " | ".join(e["summary"][:3]))
    except Exception as exc:  # a live call blew up -- report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES -- see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

**Run** (byte-compile — proves it imports with no top-level network/side effects; does NOT execute `main()`):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
python -c "import app.smoke_google as s; print('imports ok', callable(s.main))"
```

**Expected:** `imports ok True` (no network calls, no exception — every live call lives inside `main()`, which is not invoked).

- [ ] **Step 2: Run the full backend suite to confirm the new module is inert, then commit**

The smoke script must not affect the test suite. Per the project rule, run the full suite and report the pass count.

**Run:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
python -m pytest -q
```

**Expected:** the suite is green and the pass count is unchanged from the previous phase (the new `smoke_google.py` is not collected — its filename is not `test_*` — and imports no test fixtures). Report the count as "X tests passing", including the moved `test_oauth.py` and every M4 fitness data test.

**Commit:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git checkout m5-email-triage
git add backend/app/smoke_google.py
git commit -m "test(smoke): add live Gmail pipeline smoke test (app.smoke_google)

Mirrors app.smoke_whoop: real GoogleProvider + email_sync against live Gmail,
reads the emails table back, asserts triage populated. Prints the authorize
URL and exits 2 when Google is not connected. Manual only; not in CI.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**Expected:** commit succeeds on branch `m5-email-triage`.


### Task 28: Live Google OAuth validation + full-suite green

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_oauth.py`

**Interfaces:**
- Consumes: The entire M5 slice merged onto m5-email-triage: the shared oauth router + /auth/google/callback (phase 1), GoogleProvider OAuth + Gmail fetch (phases 2, 4), emails table + store (phase 3), email_sync + triage + lifespan wiring (phase 4), email API + EmailScreen (phases 5, 6), config additions (phase 2), and app.smoke_google + updated privacy policy (this phase's earlier tasks).
- Produces: A recorded end-to-end live validation: a Google Cloud OAuth Web client created, http://localhost:8000/auth/google/callback registered, google_client_id/secret in backend/.env, Gmail connected end-to-end, inbox synced + triage populated + a message body fetched live, and the full backend suite (incl. M4 fitness) reported green with its pass count. This is a manual verification gate, not a code change.

- [ ] **Step 1: Document the Google env vars in .env.example (the only code change in this task)**

Everything else in this task is manual live validation. First make the env contract discoverable so the next operator can reproduce the connect. Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example` by **appending the Google/Gmail block to the END of the file**.

NOTE: `.env.example` does NOT contain a WHOOP section — WHOOP creds live only in `app/config.py`, not this file. Do NOT try to anchor the insert on a WHOOP section or a `WHOOP_CLIENT_ID` line; there is none. The file may be minimal; its last content line is the `# FDC_API_KEY=DEMO_KEY` comment. Simply append the block below at the very end of the file (leaving the mention of WHOOP in the block's copy as a *contrast* — "unlike WHOOP" — which is descriptive prose, not a required anchor).

Add at the end of the file:

```bash

# --- Gmail email triage (M5) ---
# Google Cloud OAuth *Web application* client (console.cloud.google.com ->
# APIs & Services -> Credentials -> Create OAuth client ID -> Web application).
# Unlike WHOOP, Google ALLOWS localhost redirect URIs, so no tunnel is needed:
# register http://localhost:8000/auth/google/callback as an authorized redirect
# URI on the client, and enable the Gmail API for the project.
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
# GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
# Background email sync (mirrors EMAIL_SYNC_ENABLED / _SECONDS):
# EMAIL_SYNC_ENABLED=true
# EMAIL_SYNC_SECONDS=900
# EMAIL_BACKFILL_COUNT=50
```

**Run:**

```bash
grep -c "GOOGLE_CLIENT_ID" /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example
grep -c "localhost:8000/auth/google/callback" /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example
```

**Expected:** prints `1` and `1` (the redirect URI appears once as the example value). (No assertion is made about a WHOOP anchor — there is none.)

**Commit:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS
git checkout m5-email-triage
git add backend/.env.example
git commit -m "docs(env): document Google/Gmail OAuth env vars in .env.example

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**Expected:** commit succeeds.

- [ ] **Step 2: Create the Google Cloud OAuth client + set credentials in backend/.env**

Manual browser + local-file setup (no automated assertion — the gate is the connect succeeding in the next step). Do this once with your own Google account:

1. Go to https://console.cloud.google.com/ and create (or select) a project, e.g. `scuffed-os`.
2. **APIs & Services -> Library -> Gmail API -> Enable.**
3. **APIs & Services -> OAuth consent screen:** User type **External**; app name `Scuffed OS`; support + developer contact = your email; add scopes `openid`, `email`, `profile`, and `https://www.googleapis.com/auth/gmail.readonly`; add your own Google account under **Test users** (the app stays in *Testing* mode — no verification needed for a single test user).
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth client ID -> Application type: Web application.** Name it `Scuffed OS local`. Under **Authorized redirect URIs** add exactly:

   ```
   http://localhost:8000/auth/google/callback
   ```

   (Google accepts `http://localhost` — no HTTPS, no tunnel required, unlike WHOOP.)
5. Copy the generated **Client ID** and **Client secret** into `backend/.env`:

   ```bash
   # backend/.env (gitignored)
   GOOGLE_CLIENT_ID=<paste client id>.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=<paste client secret>
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
   ```

**Run** (confirm the app now sees the credentials and builds a well-formed authorize URL, without connecting yet):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
python -c "from app.config import settings; from app import providers; p=providers.get('google'); assert settings.google_client_id and settings.google_client_secret, 'creds not loaded from .env'; u=p.authorize_url('teststate123'); print(u); assert 'accounts.google.com' in u and 'access_type=offline' in u and 'prompt=consent' in u and 'gmail.readonly' in u and 'state=teststate123' in u and settings.google_client_id in u"
```

**Expected:** prints a `https://accounts.google.com/o/oauth2/v2/auth?...` URL containing `access_type=offline`, `prompt=consent`, the `gmail.readonly` scope, `state=teststate123`, and your client id; the assert passes with no `AssertionError`. If it fails on "creds not loaded", check that `backend/.env` is in the backend dir and the var names match.

- [ ] **Step 3: Connect Gmail end-to-end via the running app + confirm inbox sync, triage, and live body fetch**

Now drive the real OAuth + sync path against live Gmail. `ANTHROPIC_API_KEY` must be set in `backend/.env` so triage runs live.

1. **Start the backend on port 8000** (the port the redirect URI expects):

   ```bash
   cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. **Kick off the connect** and open the returned authorize URL in a browser:

   ```bash
   curl -s http://localhost:8000/api/oauth/connect/google
   ```

   **Expected:** JSON `{"authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?..."}`. Open that URL, sign in with your **test-user** Google account, and approve the read-only Gmail consent.

3. Google redirects to `http://localhost:8000/auth/google/callback?...`, which exchanges the code, stores tokens in `provider_accounts`, runs `on_connected()` (an immediate `email_sync.tick()` backfill), and 302-redirects to `/?screen=email&connected=google`.

4. **Confirm the account + first sync landed:**

   ```bash
   curl -s http://localhost:8000/api/oauth/status | python3 -m json.tool
   ```

   **Expected:** `"connected": true`, with a `google` entry in `providers` whose `status` is `"connected"` and a non-null `last_sync_at`.

5. **Confirm the inbox synced + triage populated:**

   ```bash
   curl -s http://localhost:8000/api/email/inbox | python3 -m json.tool
   ```

   **Expected:** `needs_reply` and/or `fyi` lists contain real messages from your inbox; `needs_reply_count` and `unread_count` are integers; at least one item has a non-empty `summary` array and a `category` of `"needs_reply"` or `"fyi"` (proving live triage ran). Untriaged items (if any) appear under `untriaged` with `summary: []`.

6. **Confirm on-demand body fetch works** (pick an `id` from the inbox output above):

   ```bash
   curl -s http://localhost:8000/api/email/<ID> | python3 -m json.tool
   ```

   **Expected:** an `EmailDetail` object whose `body` is the live-fetched full message text (NOT the fallback string `"Message body is unavailable right now."`). Getting the real body proves `GoogleProvider.get_message` + the router's live-fetch path work end-to-end.

7. **(Optional) Re-run the smoke script for a consolidated PASS report:**

   ```bash
   cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
   python -m app.smoke_google
   ```

   **Expected:** exit 0 with `RESULT: ALL PASSED` (messages fetched, body fetched, tick upserted, inbox populated, at least one triaged). Stop the uvicorn server (Ctrl-C) when done.

- [ ] **Step 4: Run the full backend suite (incl. M4 fitness) and report the pass count**

Final gate: the entire suite must be green — the moved `test_oauth.py`, every M4 fitness data test, and all new M5 email tests. This is the slice's completion criterion.

**Run:**

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
python -m pytest -q
```

**Expected:** all tests pass (0 failures, 0 errors). Report the exact count as "X tests passing". Specifically confirm in the output:

- `tests/test_oauth.py` passes (the moved M4 OAuth suite, now hitting `/api/oauth/*` and `oauth._STATES`) — the WHOOP connect/callback/disconnect + revoke-fails-still-deletes + unknown-provider-404 assertions are all green.
- The M4 fitness **data** tests (`/today`, `/week`, `/workouts` GET/POST/DELETE, `/sync`, manual workouts) still pass untouched.
- The new M5 email tests (Gmail JSON -> NormalizedEmail mapping, triage parse, upsert_email idempotency, inbox grouping + needs_reply_count, on-demand body + fallback, needs_reauth flip on GoogleAuthError) all pass.

If anything is red, the slice is NOT complete — fix before considering the work done. No commit for this step (it is a verification gate); the branch `m5-email-triage` is now ready to open a PR against `main`.

**Also re-confirm WHOOP did not regress** (behavior unchanged, no code diff expected):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
python -m app.smoke_whoop; echo "exit=$?"
```

**Expected:** same result as before the M5 slice — `exit=0` with `ALL PASSED` if WHOOP is connected, or `exit=2` with the connect-help text if it isn't. Either is fine; the point is that `smoke_whoop` behaves exactly as it did on `main` (the OAuth refactor only added the three hooks to WhoopProvider).

