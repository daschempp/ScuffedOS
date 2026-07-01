# M4 WHOOP Fitness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sample Fitness stub with a real full vertical slice: connect a WHOOP account over OAuth, sync recovery/sleep/strain/workouts on a schedule into normalized local tables, serve them through /api/fitness/*, wire the Fitness screen to live data, and let the assistant read and act on real fitness data.

**Architecture:** Follows the established per-domain pattern (model -> migration -> store -> router -> schemas -> tools) plus a vendor-neutral provider seam: app/providers/base.py defines a FitnessProvider Protocol + normalized dataclasses, app/providers/whoop.py implements WhoopProvider (hand-rolled httpx OAuth + WHOOP->normalized mapping), and app/fitness_sync.py is a background tick loop (near-clone of reminders.py) registered in the FastAPI lifespan. Three new tables (provider_accounts, daily_snapshots, workouts) carry a provider-agnostic `source`; reads derive deltas/trends on read and never depend on a live WHOOP call. Every external boundary has a configure(fake) test seam mirroring llm.py/memory_engine.py.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (Postgres/SQLite), Alembic, Pydantic v2 / pydantic-settings, httpx (hand-rolled OAuth, no Authlib), pytest + FastAPI TestClient, React/Vite frontend

## Global Constraints

- **Branch:** all M4 work lands on `m4-whoop-fitness` (per task instructions).
- **Suite must stay green.** Run the full pytest suite after every change and report the pass count; keep it green before considering work complete (global CLAUDE.md rule). New tests are additive; existing tests must keep passing. (Note: `tests/test_assistant_domains.py` does not reference the fitness tools today — its domain-reads test calls `get_finance_summary`, not fitness — so no existing assertion about a fitness tool surface needs updating. New fitness assistant coverage lands additively in `tests/test_assistant_fitness.py`.)
- **No new dependencies** beyond `httpx` (already present). OAuth is hand-rolled with `httpx`, NOT Authlib (spec §3). No Supabase SDKs, no WHOOP SDK.
- **Owner default `"me"`** on every new table (`owner: Mapped[str] = mapped_column(String(64), default="me", index=True)`), stamped from `settings.owner` on create, consistent with every existing table.
- **Python/style conventions:** `from __future__ import annotations`; SQLAlchemy `Mapped[...]`/`mapped_column(...)`; Python-side defaults (not server defaults) so SQLite and Postgres behave identically under tests; real UTC `DateTime(timezone=True)` timestamps with display strings derived on read; reuse module-level `JSONField` and `utcnow()`.
- **Derive-on-read:** deltas (e.g. HRV "+6") and the weekly strain trend are computed on read (this-day vs prior-day; week of `day_strain`), never stored — mirrors habits/nutrition.
- **kJ→kcal:** WHOOP reports kilojoules; `workout.calories` is stored as kcal (`round(kilojoule * 0.239006)`).
- **Tokens server-side only:** OAuth access/refresh tokens live in `provider_accounts` and are NEVER serialized to the client — store `_provider_account_dict` and all response models omit them. (Privacy-policy line reworded to "stored server-side, never in the client" across `docs/privacy-policy.md`, the gist, and the corp-site `/privacy/` page.)
- **Provider-agnostic rule:** no WHOOP field names in tables or schemas. Every persisted row carries `source` (`'whoop'|'oura'|'apple_health'|'manual'`). Rows mapping 1:1 to a provider record (workouts) also carry `source_id` for idempotent upsert; daily snapshots have NO `source_id` and are keyed/upserted by `(owner, source, day)`.
- **Idempotent upsert** of *synced* workouts only (unique `(source, source_id)` where `source_id` not null). No fuzzy manual↔synced dedupe — a manual row and a later synced row of the same session coexist; the user deletes the manual one.
- **Disconnect guarantees deletion:** disconnect deletes the `provider_accounts` row + that provider's `daily_snapshots`/`workouts` (`source == provider`) even if the remote `revoke` call fails; **manual workouts are preserved**.
- **Reads never depend on a live WHOOP call:** `/today`, `/workouts`, `/week` read normalized tables, so the screen works when WHOOP is down or sync is mid-flight. Sync failures log and retry next tick; the tick never crashes; auth failures flip `status='needs_reauth'`.
- **Tool errors return `{"error": …}`** to the model (existing `tools.execute` convention), not exceptions to the user.
- **`configure(fake)` test seam** on every external boundary (`providers`, `WhoopProvider` http, `fitness_sync`), mirroring `llm.py`/`memory_engine.py`/`reminders.py` (`"unset"` = real, `None` = disabled, object = fake). Tests run against fixture payloads, no network.
- **No webhooks (pull only);** no Oura/Apple Health adapters (extension points only); no provider settings UI; no generic multi-provider plugin framework (YAGNI boundary, spec §2).
- **Confirm-against-live (spec §13) items** — verify during implementation but do NOT block on them; the normalized names in the contract are frozen: WHOOP auth/token/revoke URLs, API base `https://api.prod.whoop.com/developer/v2/`, collection paths (recovery/sleep/cycle/workout/profile), pagination (`start`/`end`/`nextToken`/`limit`), v2 UUID ids, exact score field names (`recovery_score`, `hrv_rmssd_milli`, `resting_heart_rate`, `strain`, `sleep_performance_percentage`, `respiratory_rate`, `kilojoule`, `average_heart_rate`/`max_heart_rate`, `sport`), the cycle→calendar-day + timezone rule, and the scope string `read:recovery read:sleep read:workout read:cycles read:profile offline`.

## Interface Contract

## M4 Fitness (WHOOP) — Interface Contract (single source of truth)

> Copy every name VERBATIM. Items tagged **[confirm-against-live]** use the spec §13 placeholder name; phase author must verify the exact WHOOP v2 string/path during implementation but the *normalized* names below are frozen and never change. Branch: `m4-whoop-fitness`.

---

### A. SQLAlchemy models (`app/models.py`) — append after `ConversationMessage`

Follow existing style exactly: `from __future__ import annotations`, `Mapped[...]`/`mapped_column(...)`, module-level `JSONField = JSON().with_variant(JSONB(),"postgresql")` and `utcnow()` already exist — reuse them. All timestamps `DateTime(timezone=True)`, Python-side defaults. Nullable float columns are declared as bare `Mapped[float | None]` (SQLAlchemy infers `Float` from the annotation — no explicit `Float` import is needed). New imports needed: only `Index` and `text` from sqlalchemy.

```python
class ProviderAccount(Base):
    """OAuth credentials + incremental-sync cursor. One row per (owner, provider).
    Tokens live server-side only, never serialized to the client."""
    __tablename__ = "provider_accounts"
    __table_args__ = (UniqueConstraint("owner", "provider", name="uq_provider_accounts_owner_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)        # 'whoop'
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str] = mapped_column(Text, default="")               # space-delimited
    provider_user_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="connected") # 'connected' | 'needs_reauth'
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailySnapshot(Base):
    """Per-day physiological summary; one row per (owner, source, day) — the upsert key.
    No source_id: a day folds together several provider records. Deltas + weekly trend derive on read."""
    __tablename__ = "daily_snapshots"
    __table_args__ = (UniqueConstraint("owner", "source", "day", name="uq_daily_snapshots_owner_source_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)         # 'whoop'|'oura'|'apple_health'|'manual'
    day: Mapped[date] = mapped_column(Date, index=True)
    recovery_pct: Mapped[int | None]
    day_strain: Mapped[float | None]
    sleep_quality_pct: Mapped[int | None]
    hrv_ms: Mapped[float | None]
    resting_hr: Mapped[int | None]
    respiratory_rate: Mapped[float | None]
    sleep_hours: Mapped[float | None]
    metrics_json: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Workout(Base):
    """Synced + manual sessions. Unique on (source, source_id) WHERE source_id IS NOT NULL —
    synced rows upsert idempotently; manual rows (null source_id) never collide."""
    __tablename__ = "workouts"
    __table_args__ = (
        Index("uq_workouts_source_source_id", "source", "source_id",
              unique=True, sqlite_where=text("source_id IS NOT NULL"),
              postgresql_where=text("source_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)         # 'whoop' | 'manual'
    source_id: Mapped[str | None] = mapped_column(String(64))           # provider id; null for manual
    name: Mapped[str] = mapped_column(Text)
    sport: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_min: Mapped[int] = mapped_column(default=0)
    strain: Mapped[float | None]
    calories: Mapped[int | None]                                        # kJ->kcal converted on map
    avg_hr: Mapped[int | None]
    max_hr: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

Add to model imports: `Index, text` (alongside existing `Date, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint`). No `Float` import — bare `Mapped[float | None]` annotations let SQLAlchemy infer the Float type.

---

### B. Normalized dataclasses + Protocol (`app/providers/base.py`) — NEW

Vendor-neutral seam. No WHOOP field names leak past this module.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable

class AuthError(Exception):
    """Auth/refresh failure raised by a provider; the sync engine catches this
    (`except AuthError`) and flips the provider to status='needs_reauth'.
    The real provider's WhoopAuthError subclasses this."""

@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None          # aware UTC
    scopes: str = ""                     # space-delimited, as granted
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

@runtime_checkable
class FitnessProvider(Protocol):
    name: str                            # 'whoop'
    kind: Literal["pull", "push"]        # whoop/oura='pull'; apple_health='push'
    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...
    def revoke(self, tokens: Tokens) -> None: ...
```

`fetch_recovery` and `fetch_sleep` both return `NormalizedSnapshot` lists keyed by `day`; the sync engine merges same-`day` snapshots field-by-field before upsert (non-None wins).

---

### C. Providers registry + seam (`app/providers/__init__.py`) — NEW

Mirrors the `llm`/`memory_engine`/`reminders` `configure(fake)` seam (`"unset"` = real, object = fake). Module-level functions:

```python
_override = "unset"   # "unset" → real registry; object → fake provider list/dict

def configure(override="unset") -> None: ...        # tests install a fake; configure() restores real
def all_providers() -> list[FitnessProvider]: ...   # every registered provider
def get(name: str) -> FitnessProvider | None: ...   # by name, e.g. 'whoop'
def pull_providers() -> list[FitnessProvider]: ...   # [p for p in all_providers() if p.kind == "pull"]
```

Real registry lazily builds `WhoopProvider()` from settings. `WhoopProvider` itself exposes `configure(fake_http="unset")` for swapping the httpx transport in tests (mirrors `llm._override`), but tests primarily use `providers.configure([FakeProvider()])`.

---

### D. `WhoopProvider` (`app/providers/whoop.py`) — NEW

Class attrs `name = "whoop"`, `kind = "pull"`. Hand-rolled OAuth with `httpx` (no new deps). Lazy client. Implements the `FitnessProvider` protocol. **[confirm-against-live]** constants (use these exact Python names; verify their values against WHOOP v2 docs during impl):

```python
WHOOP_AUTH_URL   = "https://api.prod.whoop.com/oauth/oauth2/auth"      # [confirm-against-live]
WHOOP_TOKEN_URL  = "https://api.prod.whoop.com/oauth/oauth2/token"     # [confirm-against-live]
WHOOP_REVOKE_URL = "https://api.prod.whoop.com/oauth/oauth2/revoke"    # [confirm-against-live]
WHOOP_API_BASE   = "https://api.prod.whoop.com/developer/v2/"          # [confirm-against-live]
WHOOP_SCOPES     = "read:recovery read:sleep read:workout read:cycles read:profile offline"  # [confirm-against-live]
KJ_TO_KCAL = 0.239006                                                  # calories = round(kilojoule * KJ_TO_KCAL)
```

Collection paths, score field names (`recovery_score`, `hrv_rmssd_milli`, `resting_heart_rate`, `strain`, `sleep_performance_percentage`, `respiratory_rate`, `kilojoule`, `average_heart_rate`/`max_heart_rate`, `sport`), the basic-profile path (for `provider_user_id`), pagination (`start`/`end`/`nextToken`/`limit`), v2 UUID ids, and the cycle→calendar-day rule are all **[confirm-against-live]** (spec §13). Token-refresh guard: refresh when within ~60s of `expires_at`; on refresh failure raise `WhoopAuthError` (a subclass of `providers.base.AuthError`, NOT `RuntimeError`) so `fitness_sync`'s `except AuthError` flips the provider to `status='needs_reauth'`.

`WhoopProvider` also exposes `fetch_profile(tokens: Tokens) -> str | None` — a GET of the WHOOP basic-profile endpoint **[confirm-against-live]** returning the WHOOP user id, used to populate `Tokens.provider_user_id`. The OAuth callback calls it after `exchange_code` (see §G) so `provider_user_id` is persisted; it is NOT inferred from the token payload. And `set_tokens(tokens: Tokens | None) -> None` — the slot the sync engine (§H) injects the stored/refreshed tokens into before each authed `fetch_*` call, so requests carry a real Bearer token. These two methods are provider-specific (not part of the `FitnessProvider` Protocol); callers reach them via `getattr` so a fake without them is fine.

---

### E. Store methods (`app/store.py`) — add to the `Store` class

Dict builders `_provider_account_dict`, `_snapshot_dict`, `_workout_dict` mirror existing `_meal_dict`/`_habit_dict` style (use `aware_utc(...)` for timestamps). Tokens are NEVER included in `_provider_account_dict` output. Use `@_retry_integrity` on upserts; sessions via `with self._session() as s, s.begin():`.

```python
# ---- provider accounts (OAuth, server-side only) ----
def get_provider_account(self, provider: str) -> dict | None: ...        # safe dict (no tokens); None if absent
def get_provider_tokens(self, provider: str) -> Tokens | None: ...        # internal: tokens for provider/sync use
def list_provider_accounts(self) -> list[dict]: ...                       # safe dicts, for /status
def upsert_provider_account(self, provider: str, tokens: Tokens) -> dict: ... # get-or-create by (owner,provider); writes tokens+scopes+provider_user_id+meta, status='connected', connected_at on create; returns safe dict
def set_provider_status(self, provider: str, status: str) -> None: ...    # 'connected' | 'needs_reauth'
def set_provider_synced(self, provider: str, when: datetime | None = None) -> None: ...  # stamps last_sync_at
def delete_provider_data(self, provider: str) -> bool: ...               # deletes provider_accounts row + daily_snapshots + workouts WHERE source==provider; MANUAL workouts preserved; True if an account existed

# ---- snapshots (derive-on-read) ----
def upsert_snapshot(self, snap: NormalizedSnapshot) -> dict: ...          # by (owner, source, day); merges non-None fields onto existing row
def fitness_today(self, day: date | None = None) -> dict:                 # rings + vitals with derived deltas (today vs prior day). Default today. Shape = FitnessToday. Owner-scoped; on a multi-source day prefers source 'whoop'.
def fitness_week(self, end_day: date | None = None) -> dict:              # Mon-first 7-day day_strain trend. Shape = FitnessWeek. Owner-scoped; on a multi-source day prefers source 'whoop'.

# ---- workouts ----
def list_workouts(self, limit: int = 50) -> list[dict]:                   # synced + manual, newest started_at first; each dict = WorkoutOut shape
def upsert_workout(self, w: NormalizedWorkout) -> dict:                   # by (source, source_id) when source_id not null; returns workout dict
def create_workout(self, data: dict) -> dict:                            # manual: source='manual', source_id=None; data keys per WorkoutCreate; triggers habit auto-complete for started_at's local day
def delete_workout(self, workout_id: int) -> bool: ...
```

**Day mapping for workouts:** the local calendar day = `started_at` converted to local tz `.date()`. After any synced OR manual workout lands, call the existing `self.auto_complete_linked("workout", day, True)` (the M3 hook — never clobbers a manual tap). `upsert_workout` and `create_workout` both run it.

Derived deltas in `fitness_today`: per-vital `*_delta` numeric (this-day minus prior-day snapshot; `None` if no prior). `fitness_week` returns 7 entries `{date, dow, strain, frac}` where `frac = min(1.0, round(day_strain/21, 2))` (strain scale 0–21), `dow` Mon-first single letters `["M","T","W","T","F","S","S"]` (matches nutrition_week convention).

New store imports: `ProviderAccount, DailySnapshot, Workout` from `.models`; `Tokens, NormalizedSnapshot, NormalizedWorkout` from `.providers.base`.

---

### F. Pydantic schemas (`app/schemas.py`) — append

Use existing conventions: `Day` alias where a field is named `date`; derived display fields read-only. New literal `FitnessSource = Literal["whoop", "oura", "apple_health", "manual"]`.

```python
class ProviderStatus(BaseModel):
    provider: str
    status: Literal["connected", "needs_reauth"]
    connected_at: datetime
    last_sync_at: datetime | None
    provider_user_id: str | None = None

class FitnessStatus(BaseModel):
    connected: bool                       # any provider connected
    providers: List[ProviderStatus]

class FitnessVital(BaseModel):
    key: str                              # 'hrv'|'resting_hr'|'respiratory_rate'|'sleep_hours'
    label: str
    value: float | None
    unit: str
    delta: float | None                   # vs prior day; None if no prior
    icon: str
    tint: Tint

class FitnessToday(BaseModel):
    date: Day
    source: str | None                    # which provider produced today's snapshot; None if no data
    recovery_pct: int | None
    day_strain: float | None
    sleep_quality_pct: int | None
    vitals: List[FitnessVital]
    has_data: bool

class WorkoutOut(BaseModel):
    id: int
    source: FitnessSource
    name: str
    sport: str | None
    started_at: datetime
    duration_min: int
    strain: float | None
    calories: int | None
    avg_hr: int | None
    max_hr: int | None
    when: str                             # derived display, e.g. "Today · 6:10am" (mirror event_when style)
    icon: str                             # derived from sport
    tint: Tint                            # derived from sport

class WorkoutCreate(BaseModel):
    name: str = Field(min_length=1)
    sport: str | None = None
    started_at: datetime
    duration_min: int = Field(ge=0)
    strain: float | None = Field(default=None, ge=0)
    calories: int | None = Field(default=None, ge=0)
    avg_hr: int | None = Field(default=None, ge=0)
    max_hr: int | None = Field(default=None, ge=0)

class FitnessWeekDay(BaseModel):
    date: Day
    dow: str                              # "M"/"T"/... Mon-first
    strain: float | None
    frac: float                           # day_strain/21, capped 1.0

class FitnessWeek(BaseModel):
    days: List[FitnessWeekDay]
    avg_strain: float
    peak_day: Day | None

class ConnectUrl(BaseModel):
    authorize_url: str
```

---

### G. API routes (`app/routers/fitness.py`) — NEW. Two routers exported.

`router = APIRouter(prefix="/api/fitness", tags=["fitness"])` AND `auth_router = APIRouter(tags=["fitness-oauth"])` (mounted outside `/api` for the callback). All store-missing cases raise `HTTPException(404, ...)`; deletes return `Response(status_code=204)`; provider path param is `provider: str`.

| Method | Path | Request body | response_model | Notes |
| --- | --- | --- | --- | --- |
| GET | `/api/fitness/status` | — | `FitnessStatus` | per-provider state |
| GET | `/api/fitness/connect/{provider}` | — | `ConnectUrl` | builds + stores one-time `state`, returns authorize URL; 404 if provider unknown |
| GET | `/auth/{provider}/callback` | query `code`, `state` | — (`RedirectResponse`) | on `auth_router`; verify state → exchange → `upsert_provider_account` → fetch profile → enqueue immediate sync + backfill → redirect to Fitness screen with success flag |
| POST | `/api/fitness/disconnect/{provider}` | — | `FitnessStatus` | best-effort `revoke`; `delete_provider_data`; manual workouts kept |
| GET | `/api/fitness/today` | query `date` (alias, optional) | `FitnessToday` | reads normalized tables only |
| GET | `/api/fitness/workouts` | query `limit` (default 50) | `list[WorkoutOut]` | synced + manual |
| POST | `/api/fitness/workouts` | `WorkoutCreate` | `WorkoutOut` (201) | manual; triggers habit auto-complete |
| DELETE | `/api/fitness/workouts/{id}` | — | — (204) | 404 if missing |
| GET | `/api/fitness/week` | query `date` (alias, optional) | `FitnessWeek` | weekly strain trend |
| POST | `/api/fitness/sync` | — | `{"synced": int, "providers": list[str]}` | triggers `fitness_sync.tick()`; used by post-connect, manual test, assistant |

The one-time `state` store: in-process dict in the fitness router module (or `provider_accounts.meta`); spec calls it "stored server-side, one-time CSRF check." Date query params follow nutrition's pattern: `date_: date | None = Query(default=None, alias="date")`.

---

### H. Sync engine (`app/fitness_sync.py`) — NEW. Near-clone of `reminders.py`.

```python
def configure(override="unset") -> None: ...   # tests install a fake provider list / disable; mirrors reminders seam (None disables)
def tick(now: datetime | None = None) -> int:  # one sync pass over pull_providers(); returns count of new/updated records. Catches per-provider errors, never raises. Auth failure -> store.set_provider_status(p.name,'needs_reauth'). Returns 0 if no DATABASE_URL (RuntimeError caught, like reminders.tick).
async def run_loop() -> None: ...              # lifespan task; while True: await asyncio.to_thread(tick); await asyncio.sleep(settings.fitness_sync_seconds)
```

Each `tick`: for each connected pull-provider → load its stored tokens via `store.get_provider_tokens(p.name)` → refresh if expired and persist the rotated tokens back via `store.upsert_provider_account` → inject them into the provider (`provider.set_tokens(tokens)`) so authed calls carry a Bearer token → `since = last_sync_at or (now - whoop_backfill_days)` → fetch recovery/sleep/workouts since `since` → merge same-day snapshots → `store.upsert_snapshot` / `store.upsert_workout` (the latter runs habit auto-complete) → `store.set_provider_synced(p.name, now)`. An `AuthError` (refresh/exchange failure) propagates out of `_sync_provider` so `tick`'s `except AuthError` flips the provider to `needs_reauth`. Reads `settings.fitness_sync_enabled` / `fitness_sync_seconds` / `whoop_backfill_days`.

---

### I. Config additions (`app/config.py`) — append to `Settings`

```python
whoop_client_id: str = ""
whoop_client_secret: str = ""
whoop_redirect_uri: str = "https://scuffedcorporation.com/auth/whoop/callback"
fitness_sync_enabled: bool = True
fitness_sync_seconds: int = 1800            # 30 min
whoop_backfill_days: int = 30
```

---

### J. Assistant tools (`app/tools.py`)

Add `_fitness_action(title, meta)` → `{"icon": "activity", "title": title, "meta": meta, "cta": "View fitness", "screen": "fitness"}` (`"fitness"` is already in the `Screen` literal). REMOVE the seed reader entry `get_fitness_today` using `_seed_reader(FITNESS_TODAY)` and its `FITNESS_TODAY` import. Add six tools (exact `name` strings frozen):

| name | run executor | reads/writes | returns action? |
| --- | --- | --- | --- |
| `get_fitness_today` | `_get_fitness_today` | `store.fitness_today` | no |
| `get_workouts` | `_get_workouts` | `store.list_workouts` | no |
| `get_fitness_week` | `_get_fitness_week` | `store.fitness_week` | no |
| `get_fitness_status` | `_get_fitness_status` | `store.list_provider_accounts` | no |
| `log_workout` | `_log_workout` | `store.create_workout` (source='manual') | yes (`_fitness_action`) |
| `sync_fitness` | `_sync_fitness` | `fitness_sync.tick()` | yes (`_fitness_action`) |

Each executor returns `(result_dict, action_or_None)` and `execute()` json-encodes — unchanged. `log_workout` input schema: `name` (required string), `sport`, `started_at` (ISO; `_parse_dt`), `duration_min`, `strain`, `calories`, `avg_hr`, `max_hr`. Tools file imports `from . import fitness_sync` and drops `FITNESS_TODAY` from the `.seeds` import.

---

### K. Migration (`alembic/versions/0004_fitness.py`) — NEW

`revision = "0004"`, `down_revision = "0003"`. Match 0003 style exactly (`op.create_table`, `sa.Column`, `op.create_index(op.f("ix_..."))`, `JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")`). Tables: `provider_accounts`, `daily_snapshots`, `workouts`, with the three unique constraints from §A (the partial unique index on `workouts(source, source_id)` uses `postgresql_where`/`sqlite_where=sa.text("source_id IS NOT NULL")`). Float columns use `sa.Float()`. Add all three table names to `test_migrations.py::ALL_TABLES`. `downgrade()` drops the three tables in reverse FK-safe order.

---

### L. Lifespan wiring (`app/main.py`)

Import `fitness_sync` and the fitness routers. In `lifespan`, after the reminder task, start `fitness_sync.run_loop()` guarded by `settings.fitness_sync_enabled` (track a second task var, cancel both on shutdown). Add `app.include_router(fitness.router)` and `app.include_router(fitness.auth_router)`.

---

### M. Frontend (`frontend/src/screens/FitnessScreen.jsx` + `frontend/src/lib/api.js`)

Keep components (`Card`, `ProgressRing`, `Badge`, `Button`, `IconButton`, `Icon`). Follow M3 screens' load-on-mount + fetch pattern. Add to the `api` object (camelCase, same `request()` helper):

```js
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

Screen states: not-connected (Connect WHOOP CTA → `fitnessConnect('whoop')` → `window.location = authorize_url`), connected (live rings/vitals/workouts/week + last-sync eyebrow + disconnect), needs_reauth (reconnect banner), just-connected/syncing (empty "Syncing…" state), Log-workout form → `logWorkout`.

---

### N. Tests (`backend/tests/`) — mirror existing pytest style

Use the autouse `fresh_db` + `no_external_services` fixtures and the `client` fixture. Add `providers.configure([...])` and `fitness_sync.configure(...)` to teardown in `conftest.py::no_external_services` (mirror the `reminders`/`food_db` lines). A `FakeProvider` (in `tests/fakes.py` or per-test, like `FakeFood`/`FakeLLM`) returns fixture `NormalizedSnapshot`/`NormalizedWorkout`/`Tokens` — no network. New test files: `test_fitness_store.py` (upsert idempotency, disconnect deletes synced/keeps manual, workout→habit auto-complete, derived deltas/week), `test_whoop_provider.py` (WHOOP JSON→normalized, kJ→kcal, state/refresh, refresh-failure→needs_reauth), `test_fitness_api.py` (connect URL, fake callback stores+syncs, disconnect, /today /workouts /week shapes, manual POST, /sync), `test_fitness_sync.py` (tick upserts + flips needs_reauth, never raises). `smoke_whoop.py` mirrors `smoke_memory` (manual, not CI).

### O. Smoke test (`app/smoke_whoop.py`) — NEW, optional

`python -m app.smoke_whoop` — validates real WHOOP credentials end-to-end against the live API (mirrors `app/smoke_memory`). Not run in CI.

---
## Phase: Data layer (migration, models, store)

### Task 1: Normalized provider dataclasses (app/providers/base.py + package)

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Create: `backend/tests/test_providers_base.py`
- Test: `backend/tests/test_providers_base.py`

**Interfaces:**
- Consumes: nothing
- Produces: app.providers.base module exporting dataclasses Tokens, NormalizedSnapshot, NormalizedWorkout, the runtime-checkable FitnessProvider Protocol, and the AuthError base exception (verbatim from contract §B). This is the SINGLE creation of base.py — the provider-seam phase (Task 11/12) only adds WhoopProvider + the registry and never recreates this module. base.py is imported by store.py (dataclasses) and fitness_sync.py (AuthError) in later tasks. The app/providers/__init__.py file exists as an empty package marker for now; the provider registry seam (configure/all_providers/get/pull_providers) is added in a later phase.

- [ ] **Step 1: Write the failing test for the dataclasses, Protocol and AuthError**

The store layer (next tasks) imports `Tokens`, `NormalizedSnapshot`, `NormalizedWorkout` from `app.providers.base`, and the sync engine imports `AuthError`. This is the single, canonical creation of `app/providers/base.py` (the provider-seam phase only ADDS `WhoopProvider` + the registry — it never recreates this module). So base.py ships here with the vendor-neutral dataclasses, the `FitnessProvider` runtime-checkable Protocol, AND the `AuthError` base exception, all verbatim from contract §B.

Create `backend/tests/test_providers_base.py`:

```python
"""The vendor-neutral normalized dataclasses + Protocol + AuthError the store,
sync engine and providers share."""
from datetime import date, datetime, timezone

from app.providers.base import (
    AuthError,
    FitnessProvider,
    NormalizedSnapshot,
    NormalizedWorkout,
    Tokens,
)


def test_auth_error_is_an_exception():
    # The sync engine catches `except AuthError`; the real provider's
    # WhoopAuthError subclasses this. It must be a plain Exception.
    assert issubclass(AuthError, Exception)
    err = AuthError("token revoked")
    assert isinstance(err, Exception)


def test_tokens_defaults():
    t = Tokens(access_token="a", refresh_token="r", expires_at=None)
    assert t.access_token == "a"
    assert t.refresh_token == "r"
    assert t.expires_at is None
    assert t.scopes == ""
    assert t.provider_user_id is None
    assert t.meta == {}
    # meta default is not shared across instances
    t.meta["k"] = 1
    assert Tokens(access_token="b", refresh_token=None, expires_at=None).meta == {}


def test_normalized_snapshot_optional_fields_default_none():
    snap = NormalizedSnapshot(source="whoop", day=date(2026, 6, 30))
    assert snap.source == "whoop"
    assert snap.day == date(2026, 6, 30)
    assert snap.recovery_pct is None
    assert snap.day_strain is None
    assert snap.sleep_quality_pct is None
    assert snap.hrv_ms is None
    assert snap.resting_hr is None
    assert snap.respiratory_rate is None
    assert snap.sleep_hours is None
    assert snap.metrics_json == {}


def test_normalized_workout_required_and_optional():
    started = datetime(2026, 6, 30, 6, 10, tzinfo=timezone.utc)
    w = NormalizedWorkout(
        source="whoop", source_id="uuid-1", name="Run", sport="running",
        started_at=started, duration_min=42,
    )
    assert (w.source, w.source_id, w.name, w.sport) == ("whoop", "uuid-1", "Run", "running")
    assert w.started_at == started
    assert w.duration_min == 42
    assert w.strain is None
    assert w.calories is None
    assert w.avg_hr is None
    assert w.max_hr is None


class _MinimalProvider:
    name = "whoop"
    kind = "pull"

    def authorize_url(self, state): return ""
    def exchange_code(self, code): return Tokens("a", None, None)
    def refresh(self, tokens): return tokens
    def fetch_recovery(self, since): return []
    def fetch_sleep(self, since): return []
    def fetch_workouts(self, since): return []
    def revoke(self, tokens): return None


def test_runtime_checkable_protocol_accepts_a_conforming_object():
    assert isinstance(_MinimalProvider(), FitnessProvider)


def test_runtime_checkable_protocol_rejects_a_missing_method():
    class Broken:
        name = "x"
        kind = "pull"
        def authorize_url(self, state): return ""
        # no other methods
    assert not isinstance(Broken(), FitnessProvider)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_providers_base.py -q`

Expected: collection/import error — `ModuleNotFoundError: No module named 'app.providers'` (the package doesn't exist yet).

- [ ] **Step 3: Create the providers package and base dataclasses**

Create `backend/app/providers/__init__.py` (empty package marker; the registry seam is added in the provider phase):

```python
"""Fitness provider integrations (M4).

The vendor-neutral seam lives in ``base`` (normalized dataclasses, the
``FitnessProvider`` protocol, and ``AuthError``). Concrete providers (WHOOP
today) register here. The ``configure``/``all_providers`` registry lands with
the provider phase.
"""
from __future__ import annotations
```

Create `backend/app/providers/base.py` — copy verbatim from contract §B (dataclasses + the `FitnessProvider` Protocol + `AuthError`). This is the ONE place base.py is created; the provider-seam phase adds `WhoopProvider` and the registry without recreating this file.

```python
"""Vendor-neutral fitness seam: normalized dataclasses + Protocol + AuthError.

No provider field names (WHOOP's ``recovery_score`` etc.) leak past the
provider module — every provider maps its payloads into these dataclasses,
and the store/sync engine only ever see these. ``AuthError`` is the typed
auth/refresh failure the sync engine catches to flip a provider to
``needs_reauth``; the real ``WhoopProvider`` raises a ``WhoopAuthError``
subclass of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable


class AuthError(Exception):
    """Auth/refresh failure raised by a provider. ``fitness_sync.tick`` catches
    ``except AuthError`` and flips the provider to ``status='needs_reauth'``.
    The real provider's ``WhoopAuthError`` subclasses this."""


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


@runtime_checkable
class FitnessProvider(Protocol):
    name: str                            # 'whoop'
    kind: Literal["pull", "push"]        # whoop/oura='pull'; apple_health='push'

    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...
    def revoke(self, tokens: Tokens) -> None: ...
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_providers_base.py -q`

Expected: `6 passed`.

- [ ] **Step 5: Commit**

Run:
```bash
cd backend && git add app/providers/__init__.py app/providers/base.py tests/test_providers_base.py
git commit -m "feat(fitness): provider seam base — dataclasses + FitnessProvider Protocol + AuthError"
```


### Task 2: Fitness models (ProviderAccount, DailySnapshot, Workout)

**Files:**
- Create: `backend/tests/test_fitness_models.py`
- Modify: `backend/app/models.py (imports line 17; append after ConversationMessage ~line 242)`
- Test: `backend/tests/test_fitness_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: ORM classes ProviderAccount, DailySnapshot, Workout on Base.metadata (tables provider_accounts, daily_snapshots, workouts) with the unique constraints from contract §A: uq_provider_accounts_owner_provider, uq_daily_snapshots_owner_source_day, and the partial unique index uq_workouts_source_source_id (source, source_id) WHERE source_id IS NOT NULL. Imported by store.py in later tasks.

- [ ] **Step 1: Write the failing test for the three tables and their constraints**

Create `backend/tests/test_fitness_models.py`. It builds the schema from the models (the `fresh_db` autouse fixture already does `create_all`) and asserts the columns, the snapshot unique key, and that the partial unique on workouts only bites when `source_id` is non-null.

```python
"""The three M4 fitness tables: columns + unique-constraint behavior."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import DailySnapshot, ProviderAccount, Workout
from app.store import store


def test_tables_and_columns_exist():
    with store._session() as s:
        insp = inspect(s.get_bind())
        names = set(insp.get_table_names())
        assert {"provider_accounts", "daily_snapshots", "workouts"} <= names
        snap_cols = {c["name"] for c in insp.get_columns("daily_snapshots")}
        assert {"owner", "source", "day", "recovery_pct", "day_strain",
                "sleep_quality_pct", "hrv_ms", "resting_hr", "respiratory_rate",
                "sleep_hours", "metrics_json", "created_at", "updated_at"} <= snap_cols
        wk_cols = {c["name"] for c in insp.get_columns("workouts")}
        assert {"owner", "source", "source_id", "name", "sport", "started_at",
                "duration_min", "strain", "calories", "avg_hr", "max_hr"} <= wk_cols
        pa_cols = {c["name"] for c in insp.get_columns("provider_accounts")}
        assert {"owner", "provider", "access_token", "refresh_token",
                "expires_at", "scopes", "provider_user_id", "status", "meta",
                "connected_at", "last_sync_at"} <= pa_cols


def test_provider_account_owner_provider_is_unique():
    with store._session() as s, s.begin():
        s.add(ProviderAccount(owner="me", provider="whoop"))
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(ProviderAccount(owner="me", provider="whoop"))


def test_snapshot_owner_source_day_is_unique():
    day = date(2026, 6, 30)
    with store._session() as s, s.begin():
        s.add(DailySnapshot(owner="me", source="whoop", day=day))
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(DailySnapshot(owner="me", source="whoop", day=day))
    # A different source on the same day is allowed (two providers fold in).
    with store._session() as s, s.begin():
        s.add(DailySnapshot(owner="me", source="oura", day=day))


def test_workout_source_id_partial_unique():
    started = datetime(2026, 6, 30, 6, 0, tzinfo=timezone.utc)
    with store._session() as s, s.begin():
        s.add(Workout(owner="me", source="whoop", source_id="abc",
                      name="Run", started_at=started, duration_min=30))
    # Same (source, source_id) collides — synced rows upsert idempotently.
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(Workout(owner="me", source="whoop", source_id="abc",
                          name="Run again", started_at=started, duration_min=31))
    # Null source_id (manual rows) never collide, even many of them.
    with store._session() as s, s.begin():
        s.add(Workout(owner="me", source="manual", source_id=None,
                      name="M1", started_at=started, duration_min=10))
        s.add(Workout(owner="me", source="manual", source_id=None,
                      name="M2", started_at=started, duration_min=20))
    with store._session() as s:
        manual = s.scalars(
            select(Workout).where(Workout.source == "manual")
        ).all()
        assert len(manual) == 2
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_models.py -q`

Expected: collection error — `ImportError: cannot import name 'DailySnapshot' from 'app.models'`.

- [ ] **Step 3: Extend the models imports**

In `backend/app/models.py`, replace the sqlalchemy import line (line 17) to add `Index` and `text` (nullable floats use bare `Mapped[float | None]`, so no `Float` import is needed):

```python
from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, JSON, String, Text,
    UniqueConstraint, text,
)
```

- [ ] **Step 4: Append the three models after ConversationMessage**

At the end of `backend/app/models.py` (after the `ConversationMessage` class), append the three tables verbatim from contract §A. `JSONField` and `utcnow()` already exist at module scope and are reused.

```python


class ProviderAccount(Base):
    """OAuth credentials + incremental-sync cursor. One row per (owner, provider).
    Tokens live server-side only, never serialized to the client (M4)."""

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint("owner", "provider", name="uq_provider_accounts_owner_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)        # 'whoop'
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str] = mapped_column(Text, default="")                # space-delimited
    provider_user_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="connected")  # 'connected' | 'needs_reauth'
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailySnapshot(Base):
    """Per-day physiological summary; one row per (owner, source, day) — the upsert key.
    No source_id: a day folds together several provider records. Deltas + weekly
    trend derive on read."""

    __tablename__ = "daily_snapshots"
    __table_args__ = (
        UniqueConstraint("owner", "source", "day", name="uq_daily_snapshots_owner_source_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)          # 'whoop'|'oura'|'apple_health'|'manual'
    day: Mapped[date] = mapped_column(Date, index=True)
    recovery_pct: Mapped[int | None]
    day_strain: Mapped[float | None]
    sleep_quality_pct: Mapped[int | None]
    hrv_ms: Mapped[float | None]
    resting_hr: Mapped[int | None]
    respiratory_rate: Mapped[float | None]
    sleep_hours: Mapped[float | None]
    metrics_json: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Workout(Base):
    """Synced + manual sessions. Unique on (source, source_id) WHERE source_id IS NOT NULL —
    synced rows upsert idempotently; manual rows (null source_id) never collide."""

    __tablename__ = "workouts"
    __table_args__ = (
        Index("uq_workouts_source_source_id", "source", "source_id",
              unique=True, sqlite_where=text("source_id IS NOT NULL"),
              postgresql_where=text("source_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)          # 'whoop' | 'manual'
    source_id: Mapped[str | None] = mapped_column(String(64))            # provider id; null for manual
    name: Mapped[str] = mapped_column(Text)
    sport: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_min: Mapped[int] = mapped_column(default=0)
    strain: Mapped[float | None]
    calories: Mapped[int | None]                                        # kJ->kcal converted on map
    avg_hr: Mapped[int | None]
    max_hr: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
```

- [ ] **Step 5: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_models.py -q`

Expected: `4 passed`.

Then run the full suite to confirm the new tables don't disturb anything:
Run: `cd backend && python -m pytest -q`

Expected: all tests pass (report the count, e.g. `N passed`).

- [ ] **Step 6: Commit**

Run:
```bash
cd backend && git add app/models.py tests/test_fitness_models.py
git commit -m "feat(fitness): ProviderAccount, DailySnapshot, Workout models"
```


### Task 3: Migration 0004_fitness.py

**Files:**
- Create: `backend/alembic/versions/0004_fitness.py`
- Modify: `backend/tests/test_migrations.py (ALL_TABLES set ~line 30)`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: ProviderAccount, DailySnapshot, Workout models (Task 2) — the migration builds the identical schema
- Produces: Alembic revision 0004 (down_revision 0003) creating provider_accounts, daily_snapshots, workouts with the three unique constraints. ALL_TABLES in test_migrations.py covers the three new tables so the upgrade-head / downgrade-base assertions exercise them.

- [ ] **Step 1: Add the three tables to the migration test's ALL_TABLES**

In `backend/tests/test_migrations.py`, extend the `ALL_TABLES` set (currently ends at `"meals", "water_days", "nutrition_targets",`) to include the M4 tables:

```python
ALL_TABLES = {
    "tasks", "memories", "conversations", "conversation_messages",
    "task_reminders", "events", "habits", "habit_completions",
    "meals", "water_days", "nutrition_targets",
    "provider_accounts", "daily_snapshots", "workouts",
}
```

- [ ] **Step 2: Run the migration test and watch it fail**

Run: `cd backend && python -m pytest tests/test_migrations.py -q`

Expected: `test_upgrade_head_builds_full_schema` fails — `ALL_TABLES <= tables` is False because the head migration (0003) doesn't create `provider_accounts`, `daily_snapshots`, `workouts`.

- [ ] **Step 3: Write the 0004 migration**

Create `backend/alembic/versions/0004_fitness.py`, matching 0003's style exactly. The partial unique index on `workouts(source, source_id)` uses `sqlite_where`/`postgresql_where` with `sa.text("source_id IS NOT NULL")`. Float columns use `sa.Float()`.

```python
"""Fitness domain (M4): provider OAuth accounts, daily snapshots, workouts.

- provider_accounts: one row per (owner, provider); server-side OAuth tokens
  + the incremental-sync cursor (last_sync_at).
- daily_snapshots: per-day physiological summary, keyed (owner, source, day);
  no source_id — a day folds together several provider records.
- workouts: synced + manual sessions; partial-unique on (source, source_id)
  WHERE source_id IS NOT NULL so synced rows upsert idempotently while manual
  rows (null source_id) never collide.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "provider_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner", "provider", name="uq_provider_accounts_owner_provider"),
    )
    op.create_index(op.f("ix_provider_accounts_owner"), "provider_accounts", ["owner"])
    op.create_index(op.f("ix_provider_accounts_provider"), "provider_accounts", ["provider"])

    op.create_table(
        "daily_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("recovery_pct", sa.Integer(), nullable=True),
        sa.Column("day_strain", sa.Float(), nullable=True),
        sa.Column("sleep_quality_pct", sa.Integer(), nullable=True),
        sa.Column("hrv_ms", sa.Float(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("respiratory_rate", sa.Float(), nullable=True),
        sa.Column("sleep_hours", sa.Float(), nullable=True),
        sa.Column("metrics_json", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "day", name="uq_daily_snapshots_owner_source_day"),
    )
    op.create_index(op.f("ix_daily_snapshots_owner"), "daily_snapshots", ["owner"])
    op.create_index(op.f("ix_daily_snapshots_source"), "daily_snapshots", ["source"])
    op.create_index(op.f("ix_daily_snapshots_day"), "daily_snapshots", ["day"])

    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sport", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("strain", sa.Float(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_workouts_owner"), "workouts", ["owner"])
    op.create_index(op.f("ix_workouts_source"), "workouts", ["source"])
    op.create_index(op.f("ix_workouts_started_at"), "workouts", ["started_at"])
    op.create_index(
        "uq_workouts_source_source_id",
        "workouts",
        ["source", "source_id"],
        unique=True,
        sqlite_where=sa.text("source_id IS NOT NULL"),
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("workouts")
    op.drop_table("daily_snapshots")
    op.drop_table("provider_accounts")
```

Note: `op.drop_table` drops the table's own indexes with it, so the partial unique index needs no separate drop (matching how 0003's downgrade drops tables without dropping their indexes first).

- [ ] **Step 4: Run the migration tests and watch them pass**

Run: `cd backend && python -m pytest tests/test_migrations.py -q`

Expected: `2 passed` (`test_upgrade_head_builds_full_schema` and `test_downgrade_base_removes_everything`; the Postgres test is skipped without TEST_DATABASE_URL).

This confirms upgrade-to-head creates all three tables and downgrade-to-base removes them. (The models-vs-migration drift check runs only on Postgres in CI; the head build proves the migration matches the SQLite schema the tests use.)

- [ ] **Step 5: Commit**

Run:
```bash
cd backend && git add alembic/versions/0004_fitness.py tests/test_migrations.py
git commit -m "feat(fitness): 0004 migration for provider_accounts, daily_snapshots, workouts"
```


### Task 4: Store: provider-account CRUD + tokens

**Files:**
- Modify: `backend/app/store.py (imports ~lines 33-46; add provider-account methods + _provider_account_dict to Store class)`
- Test: `backend/tests/test_fitness_store.py`

**Interfaces:**
- Consumes: Tokens from app.providers.base (Task 1); ProviderAccount model (Task 2)
- Produces: Store methods get_provider_account, get_provider_tokens, list_provider_accounts, upsert_provider_account, set_provider_status, set_provider_synced, and the _provider_account_dict builder (which NEVER includes tokens). These back the OAuth/status routes and the sync engine in later phases.

- [ ] **Step 1: Write the failing test for provider-account CRUD**

Create `backend/tests/test_fitness_store.py` (this file grows across the next store tasks). First batch covers the provider-account methods, asserting tokens are never in the safe dict and that upsert is get-or-create by (owner, provider).

```python
"""Store-layer fitness logic: provider accounts, snapshots, workouts (M4).

All against SQLite via the fresh_db fixture — no network, no providers.
"""
from datetime import date, datetime, timedelta, timezone

from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
from app.store import store

UTC = timezone.utc


def _tokens(**kw):
    base = dict(
        access_token="acc-1", refresh_token="ref-1",
        expires_at=datetime(2026, 7, 1, tzinfo=UTC),
        scopes="read:recovery read:workout", provider_user_id="whoop-user-9",
        meta={"foo": "bar"},
    )
    base.update(kw)
    return Tokens(**base)


def test_get_provider_account_absent_is_none():
    assert store.get_provider_account("whoop") is None
    assert store.get_provider_tokens("whoop") is None
    assert store.list_provider_accounts() == []


def test_upsert_provider_account_creates_safe_dict_without_tokens():
    safe = store.upsert_provider_account("whoop", _tokens())
    assert safe["provider"] == "whoop"
    assert safe["status"] == "connected"
    assert safe["provider_user_id"] == "whoop-user-9"
    assert safe["connected_at"] is not None
    assert safe["last_sync_at"] is None
    # Tokens must never appear in the client-safe dict.
    assert "access_token" not in safe
    assert "refresh_token" not in safe
    assert "scopes" not in safe
    assert "meta" not in safe


def test_get_provider_tokens_round_trips_secrets():
    store.upsert_provider_account("whoop", _tokens())
    tok = store.get_provider_tokens("whoop")
    assert tok.access_token == "acc-1"
    assert tok.refresh_token == "ref-1"
    assert tok.expires_at == datetime(2026, 7, 1, tzinfo=UTC)
    assert tok.scopes == "read:recovery read:workout"
    assert tok.provider_user_id == "whoop-user-9"
    assert tok.meta == {"foo": "bar"}


def test_upsert_is_get_or_create_by_owner_provider():
    first = store.upsert_provider_account("whoop", _tokens())
    second = store.upsert_provider_account("whoop", _tokens(access_token="acc-2"))
    assert first["connected_at"] == second["connected_at"]  # same row, not recreated
    assert len(store.list_provider_accounts()) == 1
    assert store.get_provider_tokens("whoop").access_token == "acc-2"  # rotated in place
    # Reconnecting flips a needs_reauth row back to connected.
    store.set_provider_status("whoop", "needs_reauth")
    again = store.upsert_provider_account("whoop", _tokens())
    assert again["status"] == "connected"


def test_set_provider_status_and_synced():
    store.upsert_provider_account("whoop", _tokens())
    store.set_provider_status("whoop", "needs_reauth")
    assert store.get_provider_account("whoop")["status"] == "needs_reauth"
    when = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store.set_provider_synced("whoop", when)
    assert store.get_provider_account("whoop")["last_sync_at"] == when
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -q`

Expected: collection error or AttributeError — `store` has no attribute `upsert_provider_account` (the methods don't exist yet).

- [ ] **Step 3: Extend the store's model + dataclass imports**

In `backend/app/store.py`, add the three new models to the existing `from .models import (...)` block (keep it alphabetized within the block; insert `DailySnapshot`, `ProviderAccount`, `Workout`):

```python
from .models import (
    Conversation,
    ConversationMessage,
    DailySnapshot,
    Event,
    Habit,
    HabitCompletion,
    Meal,
    Memory,
    NutritionTargets,
    ProviderAccount,
    Task,
    TaskReminder,
    WaterDay,
    Workout,
    utcnow,
)
```

Directly below that import block, add the providers-dataclass import:

```python
from .providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
```

- [ ] **Step 4: Add the _provider_account_dict builder**

In `backend/app/store.py`, add a module-level dict builder near the other `_*_dict` helpers (e.g. right after `_message_dict`, before `_apply_task_patch`). It deliberately omits every token/secret field:

```python
def _provider_account_dict(p: ProviderAccount) -> dict:
    """Client-safe view of a provider account — NEVER includes tokens,
    scopes, or meta (those are server-side only; see /status)."""
    return {
        "provider": p.provider,
        "status": p.status,
        "connected_at": aware_utc(p.connected_at),
        "last_sync_at": aware_utc(p.last_sync_at),
        "provider_user_id": p.provider_user_id,
    }
```

- [ ] **Step 5: Add the provider-account store methods**

In `backend/app/store.py`, add a new section to the `Store` class (place it after the nutrition methods, before `# ---- demo data ----`). These mirror the get-or-create + `@_retry_integrity` style of `_targets_inner`/`get_targets`.

```python
    # ---- provider accounts (OAuth, server-side only) ----
    def _provider_row(self, s: Session, provider: str) -> ProviderAccount | None:
        from .config import settings

        return s.scalars(
            select(ProviderAccount)
            .where(ProviderAccount.owner == settings.owner)
            .where(ProviderAccount.provider == provider)
        ).first()

    def get_provider_account(self, provider: str) -> dict | None:
        with self._session() as s:
            row = self._provider_row(s, provider)
            return _provider_account_dict(row) if row else None

    def get_provider_tokens(self, provider: str) -> Tokens | None:
        with self._session() as s:
            row = self._provider_row(s, provider)
            if row is None:
                return None
            return Tokens(
                access_token=row.access_token,
                refresh_token=row.refresh_token,
                expires_at=aware_utc(row.expires_at),
                scopes=row.scopes or "",
                provider_user_id=row.provider_user_id,
                meta=dict(row.meta or {}),
            )

    def list_provider_accounts(self) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(ProviderAccount).order_by(ProviderAccount.id)).all()
            return [_provider_account_dict(p) for p in rows]

    @_retry_integrity
    def upsert_provider_account(self, provider: str, tokens: Tokens) -> dict:
        """Get-or-create by (owner, provider); writes the tokens, scopes,
        provider_user_id and meta, sets status='connected' (a reconnect
        clears a prior needs_reauth). connected_at is stamped only on create."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            if row is None:
                row = ProviderAccount(owner=settings.owner, provider=provider)
                s.add(row)
            row.access_token = tokens.access_token
            row.refresh_token = tokens.refresh_token
            row.expires_at = _to_utc(tokens.expires_at) if tokens.expires_at else None
            row.scopes = tokens.scopes or ""
            if tokens.provider_user_id is not None:
                row.provider_user_id = tokens.provider_user_id
            if tokens.meta:
                row.meta = dict(tokens.meta)
            row.status = "connected"
            s.flush()
            return _provider_account_dict(row)

    def set_provider_status(self, provider: str, status: str) -> None:
        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            if row is not None:
                row.status = status

    def set_provider_synced(self, provider: str, when: datetime | None = None) -> None:
        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            if row is not None:
                row.last_sync_at = _to_utc(when) if when else utcnow()
```

- [ ] **Step 6: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -q`

Expected: `5 passed`.

- [ ] **Step 7: Commit**

Run:
```bash
cd backend && git add app/store.py tests/test_fitness_store.py
git commit -m "feat(fitness): store provider-account CRUD with server-side-only tokens"
```


### Task 5: Store: upsert_snapshot (merge non-None by day)

**Files:**
- Modify: `backend/app/store.py (add _snapshot_dict + upsert_snapshot to Store class)`
- Test: `backend/tests/test_fitness_store.py`

**Interfaces:**
- Consumes: NormalizedSnapshot from app.providers.base (Task 1); DailySnapshot model (Task 2); the providers-dataclass import added in Task 4
- Produces: Store.upsert_snapshot(snap) — get-or-create by (owner, source, day), merging non-None fields onto an existing row (recovery + sleep snapshots for the same day fold together). Used by fitness_today/fitness_week (next task) and the sync engine.

- [ ] **Step 1: Write the failing test for snapshot upsert + merge**

Append to `backend/tests/test_fitness_store.py`:

```python
DAY = date(2026, 6, 30)


def test_upsert_snapshot_creates_row():
    out = store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, day_strain=14.2,
        hrv_ms=88.5, resting_hr=52,
    ))
    assert out["source"] == "whoop"
    assert out["day"] == DAY
    assert out["recovery_pct"] == 72
    assert out["day_strain"] == 14.2
    assert out["hrv_ms"] == 88.5
    assert out["resting_hr"] == 52


def test_upsert_snapshot_is_idempotent_by_owner_source_day():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=80))
    from sqlalchemy import select as _select

    from app.models import DailySnapshot
    with store._session() as s:
        rows = s.scalars(_select(DailySnapshot)).all()
    assert len(rows) == 1
    assert rows[0].recovery_pct == 80  # latest non-None wins


def test_upsert_snapshot_merges_recovery_and_sleep_same_day():
    # Recovery snapshot lands first (recovery + hrv), no sleep fields.
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, hrv_ms=88.5, resting_hr=52,
    ))
    # Sleep snapshot lands second (sleep fields), recovery fields all None.
    merged = store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, sleep_quality_pct=91,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    # Non-None from both lands on the one row; the earlier values survive.
    assert merged["recovery_pct"] == 72
    assert merged["hrv_ms"] == 88.5
    assert merged["resting_hr"] == 52
    assert merged["sleep_quality_pct"] == 91
    assert merged["respiratory_rate"] == 14.6
    assert merged["sleep_hours"] == 7.4


def test_upsert_snapshot_none_does_not_clobber():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    out = store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=None, day_strain=10.0))
    assert out["recovery_pct"] == 72  # None left the prior value intact
    assert out["day_strain"] == 10.0
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k snapshot -q`

Expected: AttributeError — `store` has no attribute `upsert_snapshot`.

- [ ] **Step 3: Add the _snapshot_dict builder**

In `backend/app/store.py`, add a module-level builder near `_provider_account_dict`:

```python
def _snapshot_dict(d: DailySnapshot) -> dict:
    return {
        "source": d.source,
        "day": d.day,
        "recovery_pct": d.recovery_pct,
        "day_strain": d.day_strain,
        "sleep_quality_pct": d.sleep_quality_pct,
        "hrv_ms": d.hrv_ms,
        "resting_hr": d.resting_hr,
        "respiratory_rate": d.respiratory_rate,
        "sleep_hours": d.sleep_hours,
        "metrics_json": d.metrics_json or {},
        "created_at": aware_utc(d.created_at),
        "updated_at": aware_utc(d.updated_at),
    }
```

Also add the snapshot field tuple near the other `_*_FIELDS` constants at module top (after `_TARGET_FIELDS`):

```python
_SNAPSHOT_FIELDS = (
    "recovery_pct", "day_strain", "sleep_quality_pct", "hrv_ms",
    "resting_hr", "respiratory_rate", "sleep_hours",
)
```

- [ ] **Step 4: Add upsert_snapshot to the Store class**

In `backend/app/store.py`, start a new section after the provider-account methods (before `# ---- demo data ----`):

```python
    # ---- snapshots (derive-on-read) ----
    @_retry_integrity
    def upsert_snapshot(self, snap: NormalizedSnapshot) -> dict:
        """Get-or-create by (owner, source, day); merges non-None fields onto
        the existing row so a day's recovery and sleep records fold together
        (non-None wins, None never clobbers). metrics_json shallow-merges."""
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.source == snap.source)
                .where(DailySnapshot.day == snap.day)
            ).first()
            if row is None:
                row = DailySnapshot(owner=settings.owner, source=snap.source, day=snap.day)
                s.add(row)
            for field in _SNAPSHOT_FIELDS:
                value = getattr(snap, field)
                if value is not None:
                    setattr(row, field, value)
            if snap.metrics_json:
                row.metrics_json = {**(row.metrics_json or {}), **snap.metrics_json}
            s.flush()
            return _snapshot_dict(row)
```

- [ ] **Step 5: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k snapshot -q`

Expected: `4 passed`.

- [ ] **Step 6: Commit**

Run:
```bash
cd backend && git add app/store.py tests/test_fitness_store.py
git commit -m "feat(fitness): store.upsert_snapshot merges same-day records by (owner, source, day)"
```


### Task 6: Store: workouts (upsert, create manual, list, delete) + habit auto-complete

**Files:**
- Modify: `backend/app/store.py (add _workout_dict + workout methods to Store class)`
- Test: `backend/tests/test_fitness_store.py`

**Interfaces:**
- Consumes: NormalizedWorkout from app.providers.base (Task 1); Workout model (Task 2); existing Store.auto_complete_linked('workout', day, True) (M3 hook, store.py ~line 834); existing event_when_display / clock display helpers
- Produces: Store.list_workouts, upsert_workout, create_workout (manual), delete_workout, plus _workout_dict (WorkoutOut shape with derived when/icon/tint) and _workout_chip mapping. Both upsert_workout and create_workout run auto_complete_linked('workout', local-day, True) after the row lands, reusing the M3 hook that never clobbers a manual tap.

- [ ] **Step 1: Write the failing test for workout upsert/create/list/delete + auto-complete**

Append to `backend/tests/test_fitness_store.py`:

```python
def _nw(**kw):
    base = dict(
        source="whoop", source_id="w-1", name="Morning run", sport="running",
        started_at=datetime(2026, 6, 30, 6, 10, tzinfo=UTC), duration_min=42,
        strain=11.3, calories=430, avg_hr=148, max_hr=171,
    )
    base.update(kw)
    return NormalizedWorkout(**base)


def test_upsert_workout_is_idempotent_by_source_id():
    store.upsert_workout(_nw())
    again = store.upsert_workout(_nw(name="Morning run (v2)", duration_min=45))
    rows = store.list_workouts()
    assert len(rows) == 1                      # same (source, source_id) -> one row
    assert again["name"] == "Morning run (v2)"  # fields updated in place
    assert again["duration_min"] == 45
    assert again["source"] == "whoop"


def test_workout_dict_has_derived_display_fields():
    out = store.upsert_workout(_nw(sport="running"))
    assert out["icon"]                          # sport-derived, non-empty
    assert out["tint"] in {"green", "sky", "plum", "honey", "clay"}
    assert isinstance(out["when"], str) and out["when"]
    assert out["calories"] == 430


def test_create_manual_workout_has_null_source_id():
    out = store.create_workout({
        "name": "Lunch lift", "sport": "strength",
        "started_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "duration_min": 35, "strain": 8.0,
    })
    assert out["source"] == "manual"
    assert out["id"] > 0
    rows = store.list_workouts()
    assert any(r["name"] == "Lunch lift" and r["source"] == "manual" for r in rows)


def test_list_workouts_newest_started_first_and_limit():
    store.upsert_workout(_nw(source_id="a", started_at=datetime(2026, 6, 28, 6, tzinfo=UTC)))
    store.upsert_workout(_nw(source_id="b", started_at=datetime(2026, 6, 30, 6, tzinfo=UTC)))
    store.upsert_workout(_nw(source_id="c", started_at=datetime(2026, 6, 29, 6, tzinfo=UTC)))
    rows = store.list_workouts()
    starts = [r["started_at"] for r in rows]
    assert starts == sorted(starts, reverse=True)
    assert len(store.list_workouts(limit=2)) == 2


def test_delete_workout():
    out = store.create_workout({
        "name": "Doomed", "started_at": datetime(2026, 6, 30, 9, tzinfo=UTC),
        "duration_min": 10,
    })
    assert store.delete_workout(out["id"]) is True
    assert store.delete_workout(out["id"]) is False
    assert store.list_workouts() == []


def test_synced_workout_auto_completes_linked_habit():
    store.create_habit({"name": "Workout", "link": "workout"})
    local_day = datetime(2026, 6, 30, 6, 10, tzinfo=UTC).astimezone().date()
    store.upsert_workout(_nw(started_at=datetime(2026, 6, 30, 6, 10, tzinfo=UTC)))
    week = store.habits_week(local_day - timedelta(days=local_day.weekday()))
    habit = week["habits"][0]
    assert habit["days"][local_day.weekday()] is True


def test_manual_workout_auto_completes_and_does_not_clobber_manual_tap():
    h = store.create_habit({"name": "Workout", "link": "workout"})
    local_day = datetime(2026, 6, 30, 12, 0, tzinfo=UTC).astimezone().date()
    # User manually taps the habit first.
    store.toggle_habit(h["id"], local_day)
    # A manual workout lands -> auto-complete is a no-op on an already-complete day.
    store.create_workout({
        "name": "Lift", "started_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "duration_min": 30,
    })
    from sqlalchemy import select as _select

    from app.models import HabitCompletion
    with store._session() as s:
        comp = s.scalars(
            _select(HabitCompletion).where(HabitCompletion.date == local_day)
        ).all()
    assert len(comp) == 1
    assert comp[0].source == "manual"  # the manual tap was never clobbered
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k workout -q`

Expected: AttributeError — `store` has no attribute `upsert_workout`.

- [ ] **Step 3: Add the workout chip mapping and _workout_dict builder**

In `backend/app/store.py`, near the `_SLOT_CHIP` mapping at module top, add a sport→(icon, tint) chip map with a default, mirroring the meal-chip pattern:

```python
# Workout chip icon/tint by sport — derived on read (mirrors _SLOT_CHIP).
# Every icon name here MUST exist in frontend/src/lib/Icon.jsx's ICONS map or it
# renders blank. 'running' uses 'activity' (Lucide has no plain run glyph);
# 'swimming' uses 'waves', which Task 27 adds to the Icon registry.
_SPORT_CHIP = {
    "running": ("activity", "green"),
    "cycling": ("bike", "sky"),
    "strength": ("dumbbell", "clay"),
    "weightlifting": ("dumbbell", "clay"),
    "swimming": ("waves", "sky"),
    "yoga": ("flower-2", "plum"),
    "walking": ("footprints", "honey"),
}
_WORKOUT_CHIP_DEFAULT = ("activity", "clay")
```

Then add the dict builder near `_snapshot_dict`. `when` reuses the calendar `event_when_display` helper (already imported in store.py) for an "Up next"-style relative line:

```python
def _workout_chip(sport: str | None) -> tuple[str, str]:
    if not sport:
        return _WORKOUT_CHIP_DEFAULT
    return _SPORT_CHIP.get(sport.lower(), _WORKOUT_CHIP_DEFAULT)


def _workout_dict(w: Workout) -> dict:
    started = aware_utc(w.started_at)
    icon, tint = _workout_chip(w.sport)
    end = started + timedelta(minutes=w.duration_min or 0)
    return {
        "id": w.id,
        "source": w.source,
        "source_id": w.source_id,
        "name": w.name,
        "sport": w.sport,
        "started_at": started,
        "duration_min": w.duration_min,
        "strain": w.strain,
        "calories": w.calories,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "when": event_when_display(started, end),
        "icon": icon,
        "tint": tint,
    }
```

Also add the manual-create field whitelist near the other `_*_FIELDS` constants:

```python
_WORKOUT_FIELDS = {
    "name", "sport", "started_at", "duration_min", "strain",
    "calories", "avg_hr", "max_hr",
}
```

- [ ] **Step 4: Add the workout store methods**

In `backend/app/store.py`, add a section after the snapshot methods (before `# ---- demo data ----`). Both write paths convert `started_at` to the local calendar day and call the existing M3 `auto_complete_linked` hook.

```python
    # ---- workouts ----
    def _workout_local_day(self, started_at: datetime) -> date:
        """The calendar day a workout belongs to = its start in local tz."""
        return aware_utc(started_at).astimezone().date()

    def list_workouts(self, limit: int = 50) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(
                select(Workout).order_by(Workout.started_at.desc()).limit(limit)
            ).all()
            return [_workout_dict(w) for w in rows]

    @_retry_integrity
    def upsert_workout(self, w: NormalizedWorkout) -> dict:
        """Upsert a synced workout by (source, source_id); manual rows (null
        source_id) go through create_workout. Runs the workout->habit
        auto-complete for the workout's local day after the row lands."""
        from .config import settings

        with self._session() as s, s.begin():
            row = None
            if w.source_id is not None:
                row = s.scalars(
                    select(Workout)
                    .where(Workout.source == w.source)
                    .where(Workout.source_id == w.source_id)
                ).first()
            if row is None:
                row = Workout(owner=settings.owner, source=w.source, source_id=w.source_id)
                s.add(row)
            row.name = w.name
            row.sport = w.sport
            row.started_at = _to_utc(w.started_at)
            row.duration_min = w.duration_min
            row.strain = w.strain
            row.calories = w.calories
            row.avg_hr = w.avg_hr
            row.max_hr = w.max_hr
            s.flush()
            result = _workout_dict(row)
            day = self._workout_local_day(row.started_at)
        self.auto_complete_linked("workout", day, True)
        return result

    def create_workout(self, data: dict) -> dict:
        """Manual workout: source='manual', source_id=None. Triggers the
        workout->habit auto-complete for the started_at local day."""
        from .config import settings

        with self._session() as s, s.begin():
            fields = {k: v for k, v in data.items() if k in _WORKOUT_FIELDS and v is not None}
            started = fields.pop("started_at")
            row = Workout(
                owner=settings.owner, source="manual", source_id=None,
                started_at=_to_utc(started), **fields,
            )
            s.add(row)
            s.flush()
            result = _workout_dict(row)
            day = self._workout_local_day(row.started_at)
        self.auto_complete_linked("workout", day, True)
        return result

    def delete_workout(self, workout_id: int) -> bool:
        with self._session() as s, s.begin():
            row = s.get(Workout, workout_id)
            if row is None:
                return False
            s.delete(row)
            return True
```

Note: `auto_complete_linked` opens its own session+transaction, so it is called *after* the workout's `with ... s.begin()` block has committed (the `result`/`day` are captured inside, the hook runs outside) — exactly how `set_water`/`update_targets` call it today.

- [ ] **Step 5: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k workout -q`

Expected: `7 passed`.

Then run the whole fitness store test file:
Run: `cd backend && python -m pytest tests/test_fitness_store.py -q`

Expected: all snapshot + provider + workout tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd backend && git add app/store.py tests/test_fitness_store.py
git commit -m "feat(fitness): store workout upsert/create/list/delete + workout->habit auto-complete"
```


### Task 7: Store: fitness_today (rings + vitals with derived deltas)

**Files:**
- Modify: `backend/app/store.py (add fitness_today + vitals helper to Store class)`
- Test: `backend/tests/test_fitness_store.py`

**Interfaces:**
- Consumes: DailySnapshot model (Task 2); upsert_snapshot (Task 5); existing _local_today helper
- Produces: Store.fitness_today(day=None) -> FitnessToday-shaped dict: date, source, recovery_pct, day_strain, sleep_quality_pct, vitals (list of {key,label,value,unit,delta,icon,tint}), has_data. Deltas are this-day minus prior-day snapshot (None if no prior). Consumed by the /api/fitness/today route and the get_fitness_today tool in later phases.

- [ ] **Step 1: Write the failing test for fitness_today rings, vitals and deltas**

Append to `backend/tests/test_fitness_store.py`:

```python
def test_fitness_today_empty_state():
    out = store.fitness_today(DAY)
    assert out["date"] == DAY
    assert out["has_data"] is False
    assert out["source"] is None
    assert out["recovery_pct"] is None
    assert out["day_strain"] is None
    assert out["sleep_quality_pct"] is None
    # vitals are always the same four keys, values None when no data.
    keys = [v["key"] for v in out["vitals"]]
    assert keys == ["hrv", "resting_hr", "respiratory_rate", "sleep_hours"]
    assert all(v["value"] is None and v["delta"] is None for v in out["vitals"])


def test_fitness_today_rings_and_vitals():
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, day_strain=14.2,
        sleep_quality_pct=88, hrv_ms=82.0, resting_hr=52,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    out = store.fitness_today(DAY)
    assert out["has_data"] is True
    assert out["source"] == "whoop"
    assert out["recovery_pct"] == 72
    assert out["day_strain"] == 14.2
    assert out["sleep_quality_pct"] == 88
    by_key = {v["key"]: v for v in out["vitals"]}
    assert by_key["hrv"]["value"] == 82.0
    assert by_key["hrv"]["unit"] == "ms"
    assert by_key["resting_hr"]["value"] == 52
    assert by_key["respiratory_rate"]["value"] == 14.6
    assert by_key["sleep_hours"]["value"] == 7.4
    # no prior day -> no deltas
    assert all(v["delta"] is None for v in out["vitals"])


def test_fitness_today_deltas_vs_prior_day():
    prior = DAY - timedelta(days=1)
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=prior, hrv_ms=76.0, resting_hr=55,
        respiratory_rate=15.0, sleep_hours=7.0,
    ))
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, hrv_ms=82.0, resting_hr=52,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    by_key = {v["key"]: v for v in store.fitness_today(DAY)["vitals"]}
    assert by_key["hrv"]["delta"] == 6.0           # 82 - 76
    assert by_key["resting_hr"]["delta"] == -3      # 52 - 55
    assert by_key["respiratory_rate"]["delta"] == round(14.6 - 15.0, 1)
    assert by_key["sleep_hours"]["delta"] == round(7.4 - 7.0, 1)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k fitness_today -q`

Expected: AttributeError — `store` has no attribute `fitness_today`.

- [ ] **Step 3: Add the vitals spec constant**

In `backend/app/store.py`, near the chip-mapping constants at module top, add the fixed vitals layout (key, snapshot-field, label, unit, icon, tint). This drives both the empty-state and the populated vitals so the four rows are always present:

```python
# The four vitals shown under the rings — fixed layout; values + deltas
# derive on read from the day's snapshot (None when absent).
_VITALS_SPEC = (
    ("hrv", "hrv_ms", "HRV", "ms", "activity", "green"),
    ("resting_hr", "resting_hr", "Resting HR", "bpm", "heart", "clay"),
    ("respiratory_rate", "respiratory_rate", "Respiratory", "rpm", "wind", "sky"),
    ("sleep_hours", "sleep_hours", "Sleep", "h", "moon", "plum"),
)
```

- [ ] **Step 4: Add fitness_today to the Store class**

In `backend/app/store.py`, add to the snapshots section (after `upsert_snapshot`). The delta is `round(this - prior, 1)` for floats, plain int subtraction for `resting_hr`; `None` when either side is missing.

`_snapshot_row` uses `case` for the source precedence — ensure `case` is in the SQLAlchemy import at the top of store.py (add it to the existing `from sqlalchemy import ...` line if absent, alongside `select`):

```python
from sqlalchemy import case, select  # (plus whatever else store.py already imports)
```

```python
    def _snapshot_row(self, s: Session, day: date) -> DailySnapshot | None:
        """The owner's snapshot for `day`. When multiple sources wrote the same
        day (e.g. a future 'oura' alongside 'whoop'), prefer 'whoop' so reads
        don't flip between providers; ties fall back to newest id."""
        from .config import settings

        # Source precedence: prefer 'whoop' (0) over any other source (1).
        precedence = case((DailySnapshot.source == "whoop", 0), else_=1)
        return s.scalars(
            select(DailySnapshot)
            .where(DailySnapshot.owner == settings.owner)
            .where(DailySnapshot.day == day)
            .order_by(precedence, DailySnapshot.id.desc())
        ).first()

    @staticmethod
    def _vital_delta(field: str, today_val, prior_val):
        if today_val is None or prior_val is None:
            return None
        if field == "resting_hr":
            return today_val - prior_val
        return round(today_val - prior_val, 1)

    def fitness_today(self, day: date | None = None) -> dict:
        """Rings + vitals for `day` (default today). Vital deltas are this-day
        minus the prior-day snapshot (None if there's no prior)."""
        day = day or _local_today()
        with self._session() as s:
            today_row = self._snapshot_row(s, day)
            prior_row = self._snapshot_row(s, day - timedelta(days=1))
        vitals = []
        for key, field, label, unit, icon, tint in _VITALS_SPEC:
            value = getattr(today_row, field) if today_row else None
            prior = getattr(prior_row, field) if prior_row else None
            vitals.append({
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "delta": self._vital_delta(field, value, prior),
                "icon": icon,
                "tint": tint,
            })
        return {
            "date": day,
            "source": today_row.source if today_row else None,
            "recovery_pct": today_row.recovery_pct if today_row else None,
            "day_strain": today_row.day_strain if today_row else None,
            "sleep_quality_pct": today_row.sleep_quality_pct if today_row else None,
            "vitals": vitals,
            "has_data": today_row is not None,
        }
```

- [ ] **Step 5: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k fitness_today -q`

Expected: `3 passed`.

- [ ] **Step 6: Commit**

Run:
```bash
cd backend && git add app/store.py tests/test_fitness_store.py
git commit -m "feat(fitness): store.fitness_today rings + vitals with derived prior-day deltas"
```


### Task 8: Store: fitness_week (derived weekly strain trend)

**Files:**
- Modify: `backend/app/store.py (add fitness_week to Store class)`
- Test: `backend/tests/test_fitness_store.py`

**Interfaces:**
- Consumes: DailySnapshot model (Task 2); upsert_snapshot (Task 5); existing recurrence.week_start + _local_today helpers (mirror nutrition_week)
- Produces: Store.fitness_week(end_day=None) -> FitnessWeek-shaped dict: days (7 entries {date, dow, strain, frac}), avg_strain, peak_day. frac = min(1.0, round(day_strain/21, 2)); dow Mon-first single letters. Consumed by /api/fitness/week and the get_fitness_week tool in later phases.

- [ ] **Step 1: Write the failing test for the weekly strain trend**

Append to `backend/tests/test_fitness_store.py`. This mirrors the nutrition_week conventions (Mon-first, dow letters, frac capped at 1.0) but on `day_strain` over a 0–21 scale.

```python
MONDAY = date(2026, 6, 29)  # 2026-06-29 is a Monday


def test_fitness_week_empty_state():
    out = store.fitness_week(MONDAY + timedelta(days=3))
    assert len(out["days"]) == 7
    assert [d["dow"] for d in out["days"]] == ["M", "T", "W", "T", "F", "S", "S"]
    assert out["days"][0]["date"] == MONDAY
    assert all(d["strain"] is None and d["frac"] == 0.0 for d in out["days"])
    assert out["avg_strain"] == 0
    assert out["peak_day"] is None


def test_fitness_week_strain_trend_and_frac_cap():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=MONDAY, day_strain=10.5))
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=MONDAY + timedelta(days=1), day_strain=21.0,
    ))
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=MONDAY + timedelta(days=2), day_strain=5.0,
    ))
    out = store.fitness_week(MONDAY + timedelta(days=2))
    days = out["days"]
    assert days[0]["strain"] == 10.5
    assert days[0]["frac"] == round(10.5 / 21, 2)
    assert days[1]["strain"] == 21.0
    assert days[1]["frac"] == 1.0                # capped
    assert days[2]["strain"] == 5.0
    assert all(d["strain"] is None and d["frac"] == 0.0 for d in days[3:])
    # avg over days with a strain reading only.
    assert out["avg_strain"] == round((10.5 + 21.0 + 5.0) / 3, 1)
    assert out["peak_day"] == MONDAY + timedelta(days=1)  # day_strain 21 is the peak
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k fitness_week -q`

Expected: AttributeError — `store` has no attribute `fitness_week`.

- [ ] **Step 3: Add fitness_week to the Store class**

In `backend/app/store.py`, add to the snapshots section (after `fitness_today`). It mirrors `nutrition_week` structurally — Mon-first 7-day window from `recurrence.week_start`, dow letters, `frac` capped at 1.0 — but keys on `day_strain` (scale 0–21). It reuses the `case` import added in Task 7 for the source precedence.

```python
    def fitness_week(self, end_day: date | None = None) -> dict:
        """Mon-first 7-day day_strain trend for the week containing `end_day`
        (default today). frac = day_strain / 21, capped at 1.0. Scoped to the
        owner; when several sources wrote the same day, 'whoop' wins (matching
        _snapshot_row's precedence) so the trend doesn't flip between providers."""
        from .config import settings

        end_day = end_day or _local_today()
        start = recurrence.week_start(end_day)
        # 'whoop' (0) sorts before other sources (1); within a day the last
        # write seen for that ordering wins.
        precedence = case((DailySnapshot.source == "whoop", 0), else_=1)
        with self._session() as s:
            rows = s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.day >= start)
                .where(DailySnapshot.day <= start + timedelta(days=6))
                .order_by(precedence.desc(), DailySnapshot.id.desc())
            ).all()
        # Iterating worst-precedence-first means the preferred ('whoop') row is
        # written LAST and wins the dict slot for its day.
        strain_by_day: dict[date, float] = {}
        for r in rows:
            if r.day_strain is not None:
                strain_by_day[r.day] = r.day_strain
        dows = ["M", "T", "W", "T", "F", "S", "S"]
        days = []
        for i in range(7):
            d = start + timedelta(days=i)
            strain = strain_by_day.get(d)
            days.append({
                "date": d,
                "dow": dows[i],
                "strain": strain,
                "frac": min(1.0, round(strain / 21, 2)) if strain is not None else 0.0,
            })
        logged = [d["strain"] for d in days if d["strain"] is not None]
        peak = max(days, key=lambda d: d["strain"] if d["strain"] is not None else -1.0)
        return {
            "days": days,
            "avg_strain": round(sum(logged) / len(logged), 1) if logged else 0,
            "peak_day": peak["date"] if logged else None,
        }
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k fitness_week -q`

Expected: `2 passed`.

- [ ] **Step 5: Run the full fitness store file, then the whole suite**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -q`

Expected: every provider/snapshot/workout/today/week test passes.

Then the full suite (CLAUDE.md rule — keep it green and report the count):
Run: `cd backend && python -m pytest -q`

Expected: all tests pass; note the total (e.g. `N passed`). Nothing in the data layer touches routers/tools/frontend, so no existing test should regress.

- [ ] **Step 6: Commit**

Run:
```bash
cd backend && git add app/store.py tests/test_fitness_store.py
git commit -m "feat(fitness): store.fitness_week derived Mon-first strain trend"
```


### Task 9: Store: disconnect_delete (delete provider data, preserve manual)

**Files:**
- Modify: `backend/app/store.py (add delete_provider_data to Store class)`
- Test: `backend/tests/test_fitness_store.py`

**Interfaces:**
- Consumes: ProviderAccount, DailySnapshot, Workout models (Task 2); upsert_provider_account/upsert_snapshot/upsert_workout/create_workout (Tasks 4-6)
- Produces: Store.delete_provider_data(provider) -> bool: deletes the provider_accounts row + daily_snapshots + workouts WHERE source==provider; MANUAL workouts preserved; returns True only if an account existed. Backs POST /api/fitness/disconnect in the router phase.

- [ ] **Step 1: Write the failing test for disconnect deletion semantics**

Append to `backend/tests/test_fitness_store.py`:

```python
def test_delete_provider_data_removes_synced_keeps_manual():
    store.upsert_provider_account("whoop", _tokens())
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    store.upsert_workout(_nw(source_id="synced-1"))
    store.create_workout({
        "name": "Manual lift",
        "started_at": datetime(2026, 6, 30, 12, tzinfo=UTC),
        "duration_min": 30,
    })

    assert store.delete_provider_data("whoop") is True

    # Account + tokens gone.
    assert store.get_provider_account("whoop") is None
    assert store.get_provider_tokens("whoop") is None
    assert store.list_provider_accounts() == []
    # Synced snapshot + workout gone; manual workout preserved.
    assert store.fitness_today(DAY)["has_data"] is False
    remaining = store.list_workouts()
    assert [w["name"] for w in remaining] == ["Manual lift"]
    assert remaining[0]["source"] == "manual"


def test_delete_provider_data_absent_returns_false():
    # No account, but a manual workout exists and must be untouched.
    store.create_workout({
        "name": "Solo", "started_at": datetime(2026, 6, 30, 8, tzinfo=UTC),
        "duration_min": 20,
    })
    assert store.delete_provider_data("whoop") is False
    assert [w["name"] for w in store.list_workouts()] == ["Solo"]
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k delete_provider -q`

Expected: AttributeError — `store` has no attribute `delete_provider_data`.

- [ ] **Step 3: Add delete_provider_data to the Store class**

In `backend/app/store.py`, add to the provider-accounts section (after `set_provider_synced`). It deletes the account row and the provider's snapshots/workouts in one transaction; manual rows (`source='manual'`) are left because the delete is scoped to `source == provider`.

```python
    def delete_provider_data(self, provider: str) -> bool:
        """Disconnect: delete the provider_accounts row + that provider's
        daily_snapshots and workouts (source == provider). Manual workouts
        are preserved (their source is 'manual'). Returns True iff an account
        existed. Deletion is the user-facing guarantee, so the router calls
        this even when the remote revoke fails."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._provider_row(s, provider)
            existed = row is not None
            if row is not None:
                s.delete(row)
            for snap in s.scalars(
                select(DailySnapshot)
                .where(DailySnapshot.owner == settings.owner)
                .where(DailySnapshot.source == provider)
            ):
                s.delete(snap)
            for w in s.scalars(
                select(Workout)
                .where(Workout.owner == settings.owner)
                .where(Workout.source == provider)
            ):
                s.delete(w)
            return existed
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd backend && python -m pytest tests/test_fitness_store.py -k delete_provider -q`

Expected: `2 passed`.

- [ ] **Step 5: Run the full suite a final time for this phase**

Run: `cd backend && python -m pytest -q`

Expected: all tests pass (report the count, e.g. `N passed`). This is the data-layer phase complete: migration 0004, three models, and the full set of store methods (provider CRUD, snapshot upsert/merge, workout upsert/create/list/delete with habit auto-complete, fitness_today deltas, fitness_week trend, disconnect deletion) are green with no regressions.

- [ ] **Step 6: Commit**

Run:
```bash
cd backend && git add app/store.py tests/test_fitness_store.py
git commit -m "feat(fitness): store.delete_provider_data wipes synced data, preserves manual workouts"
```


## Phase: Provider seam + WhoopProvider + config

### Task 10: Config settings for WHOOP + fitness sync (config.py)

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_fitness_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: settings.whoop_client_id, settings.whoop_client_secret, settings.whoop_redirect_uri, settings.fitness_sync_enabled, settings.fitness_sync_seconds, settings.whoop_backfill_days (all on the existing app.config.Settings singleton, with the exact defaults from spec section 11)

- [ ] **Step 1: Write the failing test for the new settings defaults**

Create `backend/tests/test_fitness_config.py`. It asserts the six new settings exist on the `settings` singleton with the exact defaults from spec section 11. This mirrors the plain-import assertion style of `test_db_config.py` (no fixtures needed).

```python
"""M4 config: WHOOP credentials + fitness-sync knobs land on Settings with spec defaults."""
from app.config import Settings, settings


def test_whoop_and_sync_defaults():
    assert settings.whoop_client_id == ""
    assert settings.whoop_client_secret == ""
    assert settings.whoop_redirect_uri == "https://scuffedcorporation.com/auth/whoop/callback"
    assert settings.fitness_sync_enabled is True
    assert settings.fitness_sync_seconds == 1800
    assert settings.whoop_backfill_days == 30


def test_settings_have_the_annotated_types():
    fields = Settings.model_fields
    assert fields["whoop_client_id"].annotation is str
    assert fields["fitness_sync_enabled"].annotation is bool
    assert fields["fitness_sync_seconds"].annotation is int
    assert fields["whoop_backfill_days"].annotation is int
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_config.py -q`

Expected: both tests fail with `AttributeError: 'Settings' object has no attribute 'whoop_client_id'` (and a `KeyError: 'whoop_client_id'` in the second test). The module is missing the fields.

- [ ] **Step 3: Add the six settings to Settings**

Edit `backend/app/config.py`. Append a new block to the `Settings` class, immediately after the `fdc_api_key` field (the last field today) and before the class ends. Match the existing comment-then-field style of the file.

Insert after the `fdc_api_key: str = "DEMO_KEY"` line:

```python

    # WHOOP fitness (M4). OAuth credentials come from the WHOOP developer
    # dashboard; the redirect URI must be registered there verbatim (WHOOP
    # rejects localhost — use a tunnel URL in dev, see the M4 design §14).
    # Tokens themselves are never config: they live in provider_accounts.
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "https://scuffedcorporation.com/auth/whoop/callback"

    # Background pull-sync (mirrors reminders_enabled / reminder_tick_seconds).
    fitness_sync_enabled: bool = True
    fitness_sync_seconds: int = 1800            # 30 min
    whoop_backfill_days: int = 30               # first-connect backfill window
```

Use the Edit tool with `old_string` = `    fdc_api_key: str = "DEMO_KEY"\n\n\nsettings = Settings()` and `new_string` = the same `fdc_api_key` line, then the block above, then `\n\nsettings = Settings()` — so the module-level `settings = Settings()` stays the final statement.

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_config.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass (the prior green count + 2 new). Report the pass count. Adding optional settings with defaults cannot break existing behavior.

- [ ] **Step 6: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/config.py backend/tests/test_fitness_config.py && git commit -m "M4: config — WHOOP credentials + fitness-sync settings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit on `m4-whoop-fitness` with the two files.


### Task 11: Provider seam: verify base.py (dataclasses + FitnessProvider Protocol + AuthError) is complete

**Files:**
- Test: `backend/tests/test_providers_base.py` (already created in Task 1 — re-run, do not recreate)

**Interfaces:**
- Consumes: `app/providers/base.py` and `app/providers/__init__.py`, both created in the data-layer phase (Task 1)
- Produces: nothing new — this is a verification checkpoint at the head of the provider-seam phase confirming the seam Task 1 shipped (Tokens, NormalizedSnapshot, NormalizedWorkout, the runtime-checkable FitnessProvider Protocol, and AuthError) is present and correct before the registry (Task 12) and WhoopProvider (Tasks 13-14) build on it. base.py is NOT recreated here.

> **Why this task adds no files:** the original plan created `app/providers/base.py` twice (once here, once in the data-layer phase). The data-layer Task 1 owns the single creation because `store.py` imports the dataclasses there. This task is now a guard so the provider-seam phase starts from a known-good seam. There is exactly ONE base test file — `tests/test_providers_base.py` (from Task 1). Do NOT create a second `tests/test_provider_base.py` (singular).

- [ ] **Step 1: Confirm the seam is present (it was created in Task 1)**

`app/providers/__init__.py` (package marker) and `app/providers/base.py` (the dataclasses + `FitnessProvider` Protocol + `AuthError`) already exist from Task 1. Sanity-check by importing every name the rest of the phase consumes:

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "from app.providers.base import AuthError, FitnessProvider, NormalizedSnapshot, NormalizedWorkout, Tokens; print('seam ok')"`

Expected: prints `seam ok` (no ImportError). If this fails, the data-layer phase (Task 1) was not run — go back and complete it; do NOT recreate base.py here.

- [ ] **Step 2: Run the base test from Task 1 and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_providers_base.py -q`

Expected: `6 passed` — the dataclass defaults, the AuthError-is-an-Exception check, and the runtime-checkable Protocol accept/reject checks all pass against the base.py Task 1 created. (There is no separate `test_provider_base.py`; if one exists from an older draft, delete it — it duplicates this file.)

- [ ] **Step 3: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all pass (unchanged from the end of the data-layer phase — this task adds no code). Report the pass count.

- [ ] **Step 4: No commit**

This task creates and changes nothing, so there is nothing to commit. It is a verification gate at the start of the provider-seam phase. Proceed to Task 12 (the registry), which is the first task in this phase that actually adds code (`app/providers/__init__.py` gains the registry).


### Task 12: Providers registry + configure(fake) seam (providers/__init__.py)

**Files:**
- Create: `backend/tests/test_provider_registry.py`
- Modify: `backend/app/providers/__init__.py`
- Test: `backend/tests/test_provider_registry.py`

**Interfaces:**
- Consumes: FitnessProvider, NormalizedSnapshot, NormalizedWorkout, Tokens from app.providers.base
- Produces: app.providers.configure(override='unset'), app.providers.all_providers() -> list[FitnessProvider], app.providers.get(name) -> FitnessProvider | None, app.providers.pull_providers() -> list[FitnessProvider]; the '"unset" = real, object = fake list' seam that every later test and the sync engine use. (Does NOT touch conftest.py — the providers/fitness_sync fixture resets are added once, in Task 15.)

- [ ] **Step 1: Write the failing test for the registry + seam**

Create `backend/tests/test_provider_registry.py`. A tiny in-test `FakeProvider` (conforming to the Protocol) is installed via `providers.configure([...])`; the test checks `get`, `all_providers`, `pull_providers`, and that `configure()` restores the real registry (which lazily builds the real WhoopProvider — verified by name only, no network).

```python
"""The providers registry seam: configure(fake) swaps the registered providers; '\"unset\"' restores real."""
from datetime import datetime

from app import providers
from app.providers.base import Tokens


class FakePull:
    name = "whoop"
    kind = "pull"

    def authorize_url(self, state): return f"https://fake/auth?state={state}"
    def exchange_code(self, code): return Tokens("a", "r", None)
    def refresh(self, tokens): return tokens
    def fetch_recovery(self, since): return []
    def fetch_sleep(self, since): return []
    def fetch_workouts(self, since): return []
    def revoke(self, tokens): return None


class FakePush:
    name = "apple_health"
    kind = "push"

    def authorize_url(self, state): return ""
    def exchange_code(self, code): return Tokens("a", None, None)
    def refresh(self, tokens): return tokens
    def fetch_recovery(self, since): return []
    def fetch_sleep(self, since): return []
    def fetch_workouts(self, since): return []
    def revoke(self, tokens): return None


def test_configure_installs_a_fake_list():
    providers.configure([FakePull(), FakePush()])
    try:
        names = [p.name for p in providers.all_providers()]
        assert names == ["whoop", "apple_health"]
        assert providers.get("whoop").name == "whoop"
        assert providers.get("nope") is None
        assert [p.name for p in providers.pull_providers()] == ["whoop"]
    finally:
        providers.configure()


def test_configure_restores_the_real_registry():
    providers.configure([FakePull()])
    providers.configure()  # back to real
    # The real registry builds a WhoopProvider lazily from settings — no network
    # until a method is called; we only assert it is registered by name.
    assert providers.get("whoop") is not None
    assert providers.get("whoop").name == "whoop"
    assert "whoop" in [p.name for p in providers.pull_providers()]


def test_empty_fake_list_disables_everything():
    providers.configure([])
    try:
        assert providers.all_providers() == []
        assert providers.pull_providers() == []
        assert providers.get("whoop") is None
    finally:
        providers.configure()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_registry.py -q`

Expected: failures — `AttributeError: module 'app.providers' has no attribute 'configure'` (the package `__init__.py` only has a docstring so far).

- [ ] **Step 3: Implement the registry + seam in __init__.py**

Replace `backend/app/providers/__init__.py` (currently just a docstring) with the full registry. Mirror the `llm`/`memory_engine` seam: `_override == "unset"` means real; an object (a list) is the installed fake. The real registry builds `WhoopProvider()` lazily and caches it; building does NOT touch the network (the WhoopProvider client is lazy — see the next task). `get`/`pull_providers` derive off `all_providers()`.

Write the whole file:

```python
"""Fitness provider registry + test seam (M4 design §4).

The sync engine and routers go through these four functions only. The seam
mirrors llm.py / memory_engine.py / reminders.py: `_override == "unset"`
uses the real registry; installing an object (a list of fake providers via
`configure([...])`) swaps it wholesale for tests — no network, no settings.

The real registry builds WhoopProvider lazily and caches it; construction is
cheap (the httpx client is itself lazy inside WhoopProvider), so importing
this package never makes a request.
"""
from __future__ import annotations

from .base import FitnessProvider

_override: object | str = "unset"   # "unset" → real registry; list → fakes
_real: list[FitnessProvider] | None = None


def configure(override: object | str = "unset") -> None:
    """Tests install a fake provider list; configure() restores the real registry."""
    global _override
    _override = override


def _build_real() -> list[FitnessProvider]:
    global _real
    if _real is None:
        from .whoop import WhoopProvider

        _real = [WhoopProvider()]
    return _real


def all_providers() -> list[FitnessProvider]:
    """Every registered provider (real, or the installed fake list)."""
    if _override != "unset":
        return list(_override)  # type: ignore[arg-type]
    return _build_real()


def get(name: str) -> FitnessProvider | None:
    """A provider by its `name` (e.g. 'whoop'), or None if not registered."""
    for p in all_providers():
        if p.name == name:
            return p
    return None


def pull_providers() -> list[FitnessProvider]:
    """Providers the sync tick may poll (kind == 'pull')."""
    return [p for p in all_providers() if p.kind == "pull"]
```

Note: `test_configure_restores_the_real_registry` imports `.whoop` via `_build_real()`. The next task creates `providers/whoop.py`; until then that one test errors on import. That is expected and resolved by the next task — but to keep THIS task's suite green, the test file above is authored to also pass once whoop.py exists. To avoid a red suite between tasks, run the registry test with the whoop import guarded: see the next step.

- [ ] **Step 4: Add a temporary import guard so the suite stays green before whoop.py exists**

The registry test `test_configure_restores_the_real_registry` calls `_build_real()`, which imports `app.providers.whoop` — not created until the next task. To keep the suite green at THIS task boundary (per the global 'suite must stay green' rule), make `_build_real()` tolerate a missing whoop module by returning an empty list, and relax the one test that asserts the real whoop is present so it skips when whoop.py is absent.

First, the test: change `test_configure_restores_the_real_registry` to skip gracefully when the real provider module is not yet present:

```python
def test_configure_restores_the_real_registry():
    import importlib.util
    providers.configure([FakePull()])
    providers.configure()  # back to real
    if importlib.util.find_spec("app.providers.whoop") is None:
        # WhoopProvider not authored yet (earlier in the plan); real registry empty.
        assert providers.get("whoop") is None
        return
    assert providers.get("whoop") is not None
    assert providers.get("whoop").name == "whoop"
    assert "whoop" in [p.name for p in providers.pull_providers()]
```

Second, make `_build_real()` resilient in `__init__.py` (replace the existing `_build_real`):

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

This guard is permanent and harmless — once whoop.py exists the import succeeds and the registry is populated. It also documents that the registry degrades to empty rather than crashing if the provider module is ever unimportable.

> **Conftest note:** this task does NOT edit `conftest.py`. The `no_external_services` fixture gains its `providers`/`fitness_sync` resets in ONE place — Task 15 (the sync phase, the earliest task where both seams exist). The registry tests above install their fakes inside a `try/finally: providers.configure()` so they self-restore without a conftest reset; the full suite stays green between here and Task 15.

- [ ] **Step 5: Run the registry test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_registry.py -q`

Expected: `3 passed` (the restore test takes the skip-branch since `app.providers.whoop` does not exist yet).

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all pass (prior count + 3 new). Report the pass count. No conftest change here, so existing tests are untouched.

- [ ] **Step 7: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/providers/__init__.py backend/tests/test_provider_registry.py && git commit -m "M4: provider registry + configure(fake) seam

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit with the two files.


### Task 13: WhoopProvider OAuth: authorize_url / exchange_code / refresh / revoke (providers/whoop.py)

**Files:**
- Create: `backend/app/providers/whoop.py`
- Create: `backend/tests/test_whoop_oauth.py`
- Test: `backend/tests/test_whoop_oauth.py`

**Interfaces:**
- Consumes: Tokens and AuthError from app.providers.base; settings.whoop_client_id/whoop_client_secret/whoop_redirect_uri; FitnessProvider protocol (whoop must conform). providers.configure(...) seam from app.providers
- Produces: app.providers.whoop.WhoopProvider with name='whoop', kind='pull', the frozen WHOOP_* URL/scope/profile-path constants, KJ_TO_KCAL, WhoopAuthError (a subclass of providers.base.AuthError, NOT RuntimeError), WhoopProvider.configure(fake_http='unset') http seam, set_tokens(tokens) (the sync-engine injection point), fetch_profile(tokens)->str|None (basic-profile -> provider_user_id, called by the OAuth callback), and working authorize_url/exchange_code/refresh/revoke. The fetch_recovery/sleep/workouts methods exist as stubs returning [] (filled in next task) so the Protocol is satisfied

- [ ] **Step 1: Write the failing OAuth test with a fake httpx transport**

Create `backend/tests/test_whoop_oauth.py`. It installs a fake HTTP layer via `WhoopProvider.configure(fake_http=...)` so NO network is touched, then checks: authorize URL composition (client_id, redirect_uri, response_type=code, scope, state), code→tokens exchange, refresh near expiry, refresh-failure raises `WhoopAuthError`, and revoke posts to the revoke URL. The fake exposes `post(url, **kw)` returning an object with `.status_code`, `.json()`, `.raise_for_status()` — the same surface `httpx` gives.

```python
"""WHOOP OAuth: authorize URL, code exchange, refresh-near-expiry, refresh failure, revoke.

No network: WhoopProvider.configure(fake_http=...) swaps the httpx call layer.
WHOOP field/endpoint names are [confirm-against-live] (M4 design §13) — verified
against the live v2 docs during implementation.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.providers.base import Tokens
from app.providers.whoop import (
    WHOOP_API_BASE,
    WHOOP_AUTH_URL,
    WHOOP_PROFILE_PATH,
    WHOOP_REVOKE_URL,
    WHOOP_SCOPES,
    WHOOP_TOKEN_URL,
    WhoopAuthError,
    WhoopProvider,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class FakeHttp:
    """Records POSTs/GETs; replays scripted responses keyed by URL."""

    def __init__(self, responses):
        self.responses = responses        # {url: FakeResp}
        self.posts = []                    # [(url, data)]
        self.gets = []                     # [(url, params)]

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return self.responses.get(url, FakeResp(404, {}))

    def get(self, url, headers=None, params=None):
        self.gets.append((url, params))
        return self.responses.get(url, FakeResp(404, {}))


def _provider():
    settings.whoop_client_id = "cid"
    settings.whoop_client_secret = "secret"
    settings.whoop_redirect_uri = "https://example.test/auth/whoop/callback"
    return WhoopProvider()


def test_authorize_url_has_all_oauth_params():
    p = _provider()
    url = p.authorize_url("st8tevalue")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == WHOOP_AUTH_URL
    q = parse_qs(parsed.query)
    assert q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["https://example.test/auth/whoop/callback"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == [WHOOP_SCOPES]
    assert q["state"] == ["st8tevalue"]


def test_exchange_code_returns_tokens():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        WHOOP_TOKEN_URL: FakeResp(200, {
            "access_token": "AT", "refresh_token": "RT",
            "expires_in": 3600, "scope": WHOOP_SCOPES,
        }),
    }))
    tok = p.exchange_code("thecode")
    assert tok.access_token == "AT"
    assert tok.refresh_token == "RT"
    assert tok.scopes == WHOOP_SCOPES
    assert tok.expires_at is not None and tok.expires_at.tzinfo is not None
    # exchange posted grant_type=authorization_code with the code + redirect_uri
    url, data = p._http.posts[0]
    assert url == WHOOP_TOKEN_URL
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "thecode"
    assert data["redirect_uri"] == settings.whoop_redirect_uri


def test_refresh_when_near_expiry_rotates_tokens():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        WHOOP_TOKEN_URL: FakeResp(200, {
            "access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600,
        }),
    }))
    soon = datetime.now(timezone.utc) + timedelta(seconds=30)  # within 60s guard
    tok = Tokens("old", "oldRT", soon, scopes=WHOOP_SCOPES)
    fresh = p.refresh(tok)
    assert fresh.access_token == "AT2"
    assert fresh.refresh_token == "RT2"
    url, data = p._http.posts[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "oldRT"


def test_refresh_failure_raises_whoop_auth_error():
    p = _provider()
    p.configure(fake_http=FakeHttp({WHOOP_TOKEN_URL: FakeResp(401, {})}))
    soon = datetime.now(timezone.utc) + timedelta(seconds=10)
    with pytest.raises(WhoopAuthError):
        p.refresh(Tokens("old", "oldRT", soon))


def test_refresh_without_refresh_token_raises():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))
    soon = datetime.now(timezone.utc) + timedelta(seconds=10)
    with pytest.raises(WhoopAuthError):
        p.refresh(Tokens("old", None, soon))


def test_revoke_posts_to_revoke_url():
    p = _provider()
    p.configure(fake_http=FakeHttp({WHOOP_REVOKE_URL: FakeResp(200, {})}))
    p.revoke(Tokens("AT", "RT", None))
    assert p._http.posts[0][0] == WHOOP_REVOKE_URL


def test_revoke_swallows_errors():
    """Disconnect must delete local data even if remote revoke fails (design §7)."""
    p = _provider()
    p.configure(fake_http=FakeHttp({WHOOP_REVOKE_URL: FakeResp(500, {})}))
    p.revoke(Tokens("AT", "RT", None))  # no raise


def test_whoop_auth_error_is_an_auth_error_subclass():
    """The sync engine catches `except AuthError`; WhoopAuthError must be one."""
    from app.providers.base import AuthError
    assert issubclass(WhoopAuthError, AuthError)


def test_fetch_profile_returns_provider_user_id():
    p = _provider()
    profile_url = WHOOP_API_BASE + WHOOP_PROFILE_PATH
    p.configure(fake_http=FakeHttp({
        profile_url: FakeResp(200, {"user_id": 10129, "first_name": "Sam"}),
    }))
    uid = p.fetch_profile(Tokens("AT", "RT", None))
    assert uid == "10129"                       # stringified WHOOP user id
    assert p._http.gets[0][0] == profile_url     # hit the basic-profile path


def test_fetch_profile_failure_returns_none():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))          # 404 default → best-effort None
    assert p.fetch_profile(Tokens("AT", "RT", None)) is None


def test_provider_conforms_to_protocol():
    from app.providers.base import FitnessProvider
    assert isinstance(_provider(), FitnessProvider)
    assert _provider().name == "whoop"
    assert _provider().kind == "pull"
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_oauth.py -q`

Expected: import error — `ModuleNotFoundError: No module named 'app.providers.whoop'`.

- [ ] **Step 3: Create whoop.py with the OAuth half (and fetch_* stubs)**

Create `backend/app/providers/whoop.py`. This task implements the constants, the `WhoopAuthError`, the `configure(fake_http=...)` http seam (mirrors `llm._override`), a lazy real httpx client, and `authorize_url`/`exchange_code`/`refresh`/`revoke`. The `fetch_recovery`/`fetch_sleep`/`fetch_workouts` are stubs returning `[]` so the Protocol is satisfied now; the NEXT task fills them in (TDD against fixtures).

VERIFIED against live WHOOP v2 docs during implementation: auth URL `…/oauth/oauth2/auth`, token URL `…/oauth/oauth2/token`, base `…/developer/v2/`. The revoke path and scope string are the design's frozen [confirm-against-live] values — keep them as-is; if live revoke differs only the constant value changes (callers are unaffected since revoke is best-effort).

```python
"""WhoopProvider — WHOOP v2 adapter (M4 design §4, §13).

Hand-rolled OAuth + authed REST over httpx (no Authlib; one provider doesn't
justify a dependency). All WHOOP field/endpoint names are confined to THIS
module — everything past it speaks the normalized dataclasses in base.py.

The http layer is a test seam mirroring llm.py: configure(fake_http=obj)
installs a fake exposing .post()/.get(); configure() (fake_http='unset')
restores the lazy real httpx.Client. Tokens are refreshed transparently when
within ~60s of expiry; a refresh failure raises WhoopAuthError, which the
sync engine/store translate into status='needs_reauth'.

CONFIRMED against the live v2 docs:
  auth   https://api.prod.whoop.com/oauth/oauth2/auth
  token  https://api.prod.whoop.com/oauth/oauth2/token
  base   https://api.prod.whoop.com/developer/v2/
  list responses: {"records": [...], "next_token": "..."}; query param nextToken
  metrics nested under a per-record "score" object; score_state in
          {"SCORED","PENDING_SCORE","UNSCORABLE"}
  workout sport field is "sport_name" in v2 (v1 used sport_id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..config import settings
from .base import (
    AuthError,
    NormalizedSnapshot,
    NormalizedWorkout,
    Tokens,
)

log = logging.getLogger("scuffed_os.whoop")

# [confirm-against-live] — verified against WHOOP v2 docs during M4 impl.
WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_REVOKE_URL = "https://api.prod.whoop.com/oauth/oauth2/revoke"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2/"
WHOOP_PROFILE_PATH = "user/profile/basic"  # [confirm-against-live] basic-profile collection
WHOOP_SCOPES = "read:recovery read:sleep read:workout read:cycles read:profile offline"
KJ_TO_KCAL = 0.239006  # calories = round(kilojoule * KJ_TO_KCAL)

# Refresh when the access token is within this many seconds of expiring.
_REFRESH_SKEW = timedelta(seconds=60)


class WhoopAuthError(AuthError):
    """Token refresh/exchange failed irrecoverably — caller flips needs_reauth.

    Subclasses providers.base.AuthError (NOT RuntimeError) so the sync engine's
    `except AuthError` catches it and flips the provider to needs_reauth."""


class WhoopProvider:
    name = "whoop"
    kind = "pull"

    def __init__(self) -> None:
        self._http: object | str = "unset"   # 'unset' → lazy real httpx.Client
        self._client = None
        self._tokens: Tokens | None = None    # injected by the sync engine before fetch_*

    # ---- http seam (mirrors llm._override) ----
    def configure(self, fake_http: object | str = "unset") -> None:
        """Tests install a fake exposing .post()/.get(); configure() restores real."""
        self._http = fake_http
        self._client = None

    def set_tokens(self, tokens: Tokens | None) -> None:
        """The sync engine injects the stored (possibly-refreshed) tokens here
        before calling fetch_recovery/sleep/workouts so authed calls carry a
        Bearer token. Without this every fetch would 401 (empty token)."""
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
        q = urlencode({
            "client_id": settings.whoop_client_id,
            "redirect_uri": settings.whoop_redirect_uri,
            "response_type": "code",
            "scope": WHOOP_SCOPES,
            "state": state,
        })
        return f"{WHOOP_AUTH_URL}?{q}"

    def _token_request(self, data: dict) -> Tokens:
        res = self._transport().post(WHOOP_TOKEN_URL, data=data)
        if getattr(res, "status_code", 200) >= 400:
            raise WhoopAuthError(f"WHOOP token endpoint returned {res.status_code}")
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
            "redirect_uri": settings.whoop_redirect_uri,
            "client_id": settings.whoop_client_id,
            "client_secret": settings.whoop_client_secret,
        })

    def refresh(self, tokens: Tokens) -> Tokens:
        if not tokens.refresh_token:
            raise WhoopAuthError("no refresh_token on record")
        try:
            fresh = self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "scope": "offline",
            })
        except WhoopAuthError:
            raise
        except Exception as exc:  # network etc. — treat as reauth-needed
            raise WhoopAuthError(f"refresh failed: {exc}") from exc
        # WHOOP may not echo a new refresh_token — keep the old one if absent.
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
                WHOOP_REVOKE_URL,
                data={
                    "client_id": settings.whoop_client_id,
                    "client_secret": settings.whoop_client_secret,
                    "token": tokens.access_token,
                },
            )
        except Exception as exc:
            log.warning("WHOOP revoke failed (continuing): %s", exc)

    def fetch_profile(self, tokens: Tokens) -> str | None:
        """GET the WHOOP basic profile and return the provider user id.

        Called by the OAuth callback right after exchange_code so the account's
        provider_user_id is populated (it is NOT inferred from the token
        payload). Best-effort: a profile fetch failure returns None rather than
        blocking the connect — the id is non-critical metadata. The id field
        name is [confirm-against-live] (WHOOP v2 basic profile)."""
        try:
            res = self._transport().get(
                WHOOP_API_BASE + WHOOP_PROFILE_PATH,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                params=None,
            )
            if getattr(res, "status_code", 200) >= 400:
                log.warning("WHOOP profile returned %s", getattr(res, "status_code", "?"))
                return None
            body = res.json() or {}
            uid = body.get("user_id")
            return str(uid) if uid is not None else None
        except Exception as exc:
            log.warning("WHOOP profile fetch failed (continuing): %s", exc)
            return None

    # ---- pull (stubs; filled in next task) ----
    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]:
        return []

    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]:
        return []

    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]:
        return []
```

- [ ] **Step 4: Run the OAuth test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_oauth.py -q`

Expected: `11 passed`. All OAuth behaviors verified against the fake http layer; no network — including fetch_profile -> provider_user_id and that WhoopAuthError is an AuthError subclass.

- [ ] **Step 5: Confirm the real registry now resolves the whoop provider**

The registry's `test_configure_restores_the_real_registry` (prior task) skipped when whoop.py was absent; now it should take the real branch. Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_provider_registry.py -q`

Expected: `3 passed` — and now `providers.get('whoop')` returns the real `WhoopProvider` (the find_spec branch is no longer taken). No network, because constructing `WhoopProvider()` does not build the httpx client (lazy).

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all pass (prior count + 11 new). Report the pass count. Note: tests that drive the real registry never call a `fetch_*`, `fetch_profile` or token method without first installing a fake, so no test makes a live request.

- [ ] **Step 7: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/providers/whoop.py backend/tests/test_whoop_oauth.py && git commit -m "M4: WhoopProvider OAuth — authorize/exchange/refresh/revoke over httpx

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit with the two files.


### Task 14: WhoopProvider data fetch + WHOOP-to-normalized mapping (providers/whoop.py)

**Files:**
- Create: `backend/tests/test_whoop_mapping.py`
- Modify: `backend/app/providers/whoop.py`
- Test: `backend/tests/test_whoop_mapping.py`

**Interfaces:**
- Consumes: WhoopProvider, WHOOP_API_BASE, KJ_TO_KCAL, the configure(fake_http) seam, _ensure_fresh, WhoopAuthError from the prior task; NormalizedSnapshot, NormalizedWorkout from base
- Produces: WhoopProvider.fetch_recovery / fetch_sleep / fetch_workouts that page through the WHOOP v2 API and map records to NormalizedSnapshot/NormalizedWorkout (kJ->kcal, cycle/recovery/workout -> local calendar day, sleep ms -> hours, score_state guarding). This is the mapping the sync engine consumes in a later phase

- [ ] **Step 1: Write the failing mapping test with WHOOP-shaped fixtures**

Create `backend/tests/test_whoop_mapping.py`. The fake http now also answers `.get(url, headers=, params=)` with WHOOP-shaped list payloads (`records` + `next_token`). Fixtures use the live v2 field names (commented `confirm-against-live`). The test sets up tokens (non-expiring) and asserts the mapping: recovery→snapshot (recovery_pct/hrv_ms/resting_hr), sleep→snapshot (sleep_quality_pct/respiratory_rate/sleep_hours from ms), cycle strain folded by the sync layer is NOT here (cycle strain is part of recovery-day? no — strain comes from cycle; see note) — to keep this provider self-contained, `fetch_recovery` returns recovery+cycle strain merged per day (recovery records carry `cycle_id`; the provider fetches cycles too and stamps `day_strain`). The test covers kJ→kcal on workouts, sport_name mapping, pagination via next_token, and score_state guarding.

```python
"""WHOOP v2 JSON → normalized dataclasses: recovery/cycle/sleep/workout mapping.

Fixtures use live v2 field names (confirm-against-live, M4 §13): records[] +
next_token; metrics nested under 'score'; score_state gates scored records;
workout sport field is 'sport_name'; energy is kilojoule (→kcal).
No network — WhoopProvider.configure(fake_http=...) replays the payloads.
"""
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import NormalizedSnapshot, NormalizedWorkout
from app.providers.whoop import (
    WHOOP_API_BASE,
    WhoopProvider,
)


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("x", request=None, response=None)


class FakeHttp:
    """Replays GET responses keyed by path; supports next_token paging.

    `pages` maps a path suffix (e.g. 'recovery') to a LIST of payloads;
    each successive GET to that path pops the next page.
    """

    def __init__(self, pages):
        self.pages = {k: list(v) for k, v in pages.items()}
        self.gets = []

    def _key(self, url):
        for k in self.pages:
            if url.endswith(k) or ("/" + k) in url:
                return k
        return None

    def get(self, url, headers=None, params=None):
        self.gets.append((url, params))
        key = self._key(url)
        queue = self.pages.get(key, [])
        payload = queue.pop(0) if queue else {"records": [], "next_token": None}
        return FakeResp(payload)

    def post(self, url, data=None, **kw):  # not used here
        return FakeResp({})


def _provider_with(pages):
    settings.whoop_client_id = "cid"
    settings.whoop_client_secret = "sec"
    p = WhoopProvider()
    p.configure(fake_http=FakeHttp(pages))
    # Tokens far from expiry so _ensure_fresh is a pass-through.
    p._tokens = _far_tokens()
    return p


def _far_tokens():
    from datetime import timedelta
    from app.providers.base import Tokens
    return Tokens("AT", "RT", datetime.now(timezone.utc) + timedelta(days=1), scopes="read:recovery")


# ---- recovery + cycle (strain) fixtures ----
RECOVERY_PAGE = {
    "records": [{
        "cycle_id": 93845,
        "sleep_id": "ecfc6a15-4661-442f-a9a4-f160dd7afae8",
        "user_id": 10129,
        "created_at": "2026-06-30T11:25:44.774Z",
        "updated_at": "2026-06-30T11:25:44.774Z",
        "score_state": "SCORED",
        "score": {  # confirm-against-live field names
            "recovery_score": 67,
            "resting_heart_rate": 52,
            "hrv_rmssd_milli": 88.4,
        },
    }],
    "next_token": None,
}
CYCLE_PAGE = {
    "records": [{
        "id": 93845,
        "user_id": 10129,
        "start": "2026-06-30T05:00:00.000Z",
        "end": "2026-07-01T05:00:00.000Z",
        "score_state": "SCORED",
        "score": {"strain": 14.2, "kilojoule": 8200.0,
                   "average_heart_rate": 71, "max_heart_rate": 165},
    }],
    "next_token": None,
}

# ---- sleep fixtures (ms durations) ----
SLEEP_PAGE = {
    "records": [{
        "id": "11111111-1111-1111-1111-111111111111",
        "cycle_id": 93845,
        "start": "2026-06-30T04:00:00.000Z",
        "end": "2026-06-30T11:00:00.000Z",
        "nap": False,
        "score_state": "SCORED",
        "score": {
            "sleep_performance_percentage": 82,
            "respiratory_rate": 15.1,
            "stage_summary": {
                "total_in_bed_time_milli": 27000000,        # 7.5 h in bed
                "total_awake_time_milli": 1800000,          # 0.5 h awake → 7.0 h asleep
            },
        },
    }],
    "next_token": None,
}

# ---- workout fixtures (paginated, kJ→kcal, sport_name) ----
WORKOUT_PAGE_1 = {
    "records": [{
        "id": "22222222-2222-2222-2222-222222222222",
        "start": "2026-06-30T06:10:00.000Z",
        "end": "2026-06-30T06:52:00.000Z",
        "sport_name": "running",          # confirm-against-live: v2 uses sport_name
        "score_state": "SCORED",
        "score": {"strain": 9.4, "kilojoule": 2510.0,
                   "average_heart_rate": 148, "max_heart_rate": 171},
    }],
    "next_token": "PAGE2",
}
WORKOUT_PAGE_2 = {
    "records": [{
        "id": "33333333-3333-3333-3333-333333333333",
        "start": "2026-06-29T18:00:00.000Z",
        "end": "2026-06-29T18:30:00.000Z",
        "sport_name": "weightlifting",
        "score_state": "SCORED",
        "score": {"strain": 6.1, "kilojoule": 900.0,
                   "average_heart_rate": 110, "max_heart_rate": 140},
    }],
    "next_token": None,
}
# An unscored record must be skipped.
UNSCORED_WORKOUT = {
    "records": [{
        "id": "44444444-4444-4444-4444-444444444444",
        "start": "2026-06-28T07:00:00.000Z",
        "end": "2026-06-28T07:20:00.000Z",
        "sport_name": "walking",
        "score_state": "PENDING_SCORE",
        "score": None,
    }],
    "next_token": None,
}


def test_fetch_recovery_maps_recovery_and_cycle_strain_by_day():
    p = _provider_with({"recovery": [RECOVERY_PAGE], "cycle": [CYCLE_PAGE]})
    snaps = p.fetch_recovery(since=None)
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, NormalizedSnapshot)
    assert s.source == "whoop"
    assert s.recovery_pct == 67
    assert s.resting_hr == 52
    assert s.hrv_ms == 88.4
    # cycle strain folded onto the same physiological day (cycle start, local date)
    assert s.day_strain == 14.2
    # day comes from the cycle start in local tz
    expected_day = datetime(2026, 6, 30, 5, 0, tzinfo=timezone.utc).astimezone().date()
    assert s.day == expected_day


def test_fetch_sleep_maps_quality_rr_and_hours_from_ms():
    p = _provider_with({"sleep": [SLEEP_PAGE]})
    snaps = p.fetch_sleep(since=None)
    assert len(snaps) == 1
    s = snaps[0]
    assert s.sleep_quality_pct == 82
    assert s.respiratory_rate == 15.1
    # 7.5h in bed - 0.5h awake = 7.0h asleep
    assert s.sleep_hours == 7.0
    expected_day = datetime(2026, 6, 30, 4, 0, tzinfo=timezone.utc).astimezone().date()
    assert s.day == expected_day


def test_fetch_workouts_paginates_and_converts_kj_to_kcal():
    p = _provider_with({"workout": [WORKOUT_PAGE_1, WORKOUT_PAGE_2]})
    outs = p.fetch_workouts(since=None)
    assert [w.source_id for w in outs] == [
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    run = outs[0]
    assert isinstance(run, NormalizedWorkout)
    assert run.source == "whoop"
    assert run.sport == "running"
    assert run.name == "Running"            # titled from sport_name
    assert run.duration_min == 42
    assert run.strain == 9.4
    assert run.avg_hr == 148 and run.max_hr == 171
    assert run.calories == round(2510.0 * 0.239006)  # kJ→kcal
    # page 2 followed the next_token
    assert any(params and params.get("nextToken") == "PAGE2" for _u, params in p._http.gets)


def test_unscored_records_are_skipped():
    p = _provider_with({"workout": [UNSCORED_WORKOUT]})
    assert p.fetch_workouts(since=None) == []


def test_since_is_passed_as_start_param():
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    p = _provider_with({"workout": [{"records": [], "next_token": None}]})
    p.fetch_workouts(since=since)
    _url, params = p._http.gets[0]
    assert params["start"] == "2026-06-01T00:00:00+00:00"
```

- [ ] **Step 2: Run the mapping test and watch it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_mapping.py -q`

Expected: failures — the `fetch_*` methods are stubs returning `[]`, plus `WhoopProvider` has no `_tokens` attribute used by the helpers yet, so assertions like `len(snaps) == 1` fail (`0 != 1`).

- [ ] **Step 3: Implement the fetch + mapping methods**

Edit `backend/app/providers/whoop.py`. The `_tokens` slot and `set_tokens` already exist (added in Task 13). This task adds an auth-header helper, a generic paged `_get_records` helper, three small WHOOP→normalized mappers, and replaces the three `fetch_*` stubs. We use `.astimezone().date()` for the local-day rule (matches app/display.py).

Add these helpers and mappers below the existing `fetch_profile` (and replace the three stubs). Insert before the `# ---- pull (stubs ...)` comment, replacing everything from that comment to end-of-class:

```python
    # ---- authed pull ----
    def _headers(self) -> dict:
        tokens = self._ensure_fresh(self._tokens) if self._tokens else None
        if tokens is not None:
            self._tokens = tokens   # keep rotated tokens for the rest of the run
        access = tokens.access_token if tokens else ""
        return {"Authorization": f"Bearer {access}"}

    def _get_records(self, path: str, since: datetime | None) -> list[dict]:
        """Page through a v2 collection, returning every record across pages.

        Query params (confirm-against-live): start (ISO), limit, nextToken.
        Response body: {"records": [...], "next_token": "..."}.
        """
        url = WHOOP_API_BASE + path
        headers = self._headers()
        records: list[dict] = []
        params: dict = {"limit": 25}
        if since is not None:
            params["start"] = since.isoformat()
        next_token: str | None = None
        for _ in range(50):  # hard page cap — never loop forever
            if next_token:
                params["nextToken"] = next_token
            res = self._transport().get(url, headers=headers, params=dict(params))
            if getattr(res, "status_code", 200) >= 400:
                raise WhoopAuthError(f"WHOOP {path} returned {res.status_code}")
            body = res.json()
            records.extend(body.get("records", []))
            next_token = body.get("next_token")
            if not next_token:
                break
        return records

    @staticmethod
    def _scored(rec: dict) -> dict | None:
        """The score object for a SCORED record, else None (skip unscored)."""
        if rec.get("score_state") != "SCORED":
            return None
        return rec.get("score") or None

    @staticmethod
    def _local_day(iso: str):
        """WHOOP timestamp (ISO, UTC) → local calendar day (matches display.py)."""
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().date()

    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]:
        """Recovery (recovery_pct/hrv/resting_hr) folded with cycle strain by day.

        Recovery records key on cycle_id; cycle records carry the physiological
        day's start + strain. We index cycles by id, then stamp each recovery
        day with that cycle's strain so one snapshot per day carries both.
        """
        cycles = {c["id"]: c for c in self._get_records("cycle", since)}
        snaps: list[NormalizedSnapshot] = []
        for rec in self._get_records("recovery", since):
            score = self._scored(rec)
            if score is None:
                continue
            cycle = cycles.get(rec.get("cycle_id"))
            # Day = cycle start (physiological day) when available, else the
            # recovery's created_at; both in local tz.
            day_src = (cycle or {}).get("start") or rec.get("created_at")
            if not day_src:
                continue
            cyc_score = self._scored(cycle) if cycle else None
            snaps.append(NormalizedSnapshot(
                source=self.name,
                day=self._local_day(day_src),
                recovery_pct=score.get("recovery_score"),
                resting_hr=score.get("resting_heart_rate"),
                hrv_ms=score.get("hrv_rmssd_milli"),
                day_strain=(cyc_score or {}).get("strain"),
            ))
        return snaps

    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]:
        snaps: list[NormalizedSnapshot] = []
        for rec in self._get_records("activity/sleep", since):
            if rec.get("nap"):
                continue  # naps don't define the day's sleep summary
            score = self._scored(rec)
            start = rec.get("start")
            if score is None or not start:
                continue
            stages = score.get("stage_summary") or {}
            in_bed = stages.get("total_in_bed_time_milli")
            awake = stages.get("total_awake_time_milli") or 0
            sleep_hours = None
            if in_bed is not None:
                sleep_hours = round((in_bed - awake) / 3_600_000, 1)
            snaps.append(NormalizedSnapshot(
                source=self.name,
                day=self._local_day(start),
                sleep_quality_pct=score.get("sleep_performance_percentage"),
                respiratory_rate=score.get("respiratory_rate"),
                sleep_hours=sleep_hours,
            ))
        return snaps

    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]:
        outs: list[NormalizedWorkout] = []
        for rec in self._get_records("activity/workout", since):
            score = self._scored(rec)
            start, end = rec.get("start"), rec.get("end")
            if score is None or not start or not end:
                continue
            started = datetime.fromisoformat(start.replace("Z", "+00:00"))
            ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
            duration_min = max(0, round((ended - started).total_seconds() / 60))
            sport = rec.get("sport_name")
            kj = score.get("kilojoule")
            outs.append(NormalizedWorkout(
                source=self.name,
                source_id=str(rec["id"]),
                name=(sport or "Workout").replace("_", " ").title(),
                sport=sport,
                started_at=started,
                duration_min=duration_min,
                strain=score.get("strain"),
                calories=round(kj * KJ_TO_KCAL) if kj is not None else None,
                avg_hr=score.get("average_heart_rate"),
                max_hr=score.get("max_heart_rate"),
            ))
        return outs
```

Delete the old three stub methods and the `# ---- pull (stubs; filled in next task) ----` comment they sat under.

- [ ] **Step 4: Run the mapping test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_mapping.py -q`

Expected: `5 passed`. Note the day-of-month assertions use `.astimezone().date()` on both sides, so the test is timezone-agnostic (it computes the expected local day the same way the mapper does).

- [ ] **Step 5: Run the OAuth + registry + base tests to confirm no regression in the provider package**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_whoop_oauth.py tests/test_whoop_mapping.py tests/test_provider_registry.py tests/test_providers_base.py -q`

Expected: all pass. The `__init__` change (adding `_tokens`) and the new methods don't touch the OAuth surface.

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all pass (prior count + 5 new). Report the pass count.

- [ ] **Step 7: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/providers/whoop.py backend/tests/test_whoop_mapping.py && git commit -m "M4: WhoopProvider fetch + WHOOP-to-normalized mapping (kJ->kcal, cycle->day, paging)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit with the two files.


## Phase: Sync engine (module, trigger, lifespan)

### Task 15: fitness_sync.tick() happy path — iterate pull providers, compute since, fetch + upsert, advance cursor

**Files:**
- Create: `backend/tests/test_fitness_sync.py`
- Modify: `backend/app/fitness_sync.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_fitness_sync.py`

**Interfaces:**
- Consumes: providers.configure(override) / providers.pull_providers() / providers.get(name) (the providers seam, app/providers/__init__.py — "unset"=real registry, object=fake provider list, from the provider-seam phase); providers.base.Tokens, NormalizedSnapshot, NormalizedWorkout (app/providers/base.py); the FitnessProvider Protocol methods fetch_recovery(since)->list[NormalizedSnapshot], fetch_sleep(since)->list[NormalizedSnapshot], fetch_workouts(since)->list[NormalizedWorkout], plus attrs name:str and kind:Literal['pull','push']; store.list_provider_accounts()->list[dict] (safe dicts with keys provider/status/last_sync_at), store.get_provider_tokens(provider)->Tokens|None, store.upsert_snapshot(NormalizedSnapshot)->dict, store.upsert_workout(NormalizedWorkout)->dict (runs habit auto-complete internally), store.set_provider_synced(provider, when) (all from the store phase); settings.whoop_backfill_days:int, settings.fitness_sync_enabled:bool, settings.fitness_sync_seconds:int (config phase)
- Produces: app/fitness_sync.py module exposing: _override (module global, "unset"=real), configure(override="unset")->None, tick(now: datetime | None = None) -> int (one sync pass over connected pull-providers; per provider it loads stored tokens via store.get_provider_tokens, refreshes+persists them if expired, injects them via provider.set_tokens before any authed fetch, merges same-day recovery+sleep snapshots field-by-field non-None wins, upserts snapshots+workouts, advances each provider's cursor via store.set_provider_synced; returns count of upserted snapshot+workout records). conftest.py no_external_services teardown now resets the providers + fitness_sync seams (the single conftest rewrite for the whole M4 plan).

- [ ] **Step 1: Add the providers + fitness_sync seam resets to conftest teardown**

The autouse `no_external_services` fixture must keep tests isolated from the real provider registry and disable the sync loop, mirroring the existing `reminders`/`food_db` lines. Add `fitness_sync` and `providers` to the import and to both the setup and teardown of the fixture.

Edit `backend/tests/conftest.py`. Change the import line:

```python
from app import food_db, llm, memory_engine, reminders
```

to:

```python
from app import fitness_sync, food_db, llm, memory_engine, providers, reminders
```

Then replace the whole `no_external_services` fixture body with:

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
    yield
    llm.configure()
    memory_engine.configure("unset")
    food_db.configure("unset")
    reminders.configure("unset")
    providers.configure("unset")
    fitness_sync.configure("unset")
```

Note: `providers.configure([])` makes the *default* in every test an empty registry (no providers, no network); a test that wants providers calls `providers.configure([fake])` itself. `fitness_sync.configure(None)` disables the background loop in tests. The teardown restores both seams to real.

This edit references `fitness_sync` and `providers`, which must already exist as importable modules (the providers seam ships in the provider-seam phase; `app/fitness_sync.py` is created in the next step of this task). Do not run the suite yet — the next step creates the module the test imports.

- [ ] **Step 2: Write the failing test for tick() happy path**

Create `backend/tests/test_fitness_sync.py`. It installs a `FakeProvider` (kind='pull') through the providers seam, seeds a connected provider account in the store, runs one `tick()`, and asserts: snapshots and workouts landed in the normalized tables, recovery+sleep snapshots for the same day merged into one row, the cursor advanced (`last_sync_at` stamped), and the returned count equals snapshots+workouts upserted.

```python
"""Sync engine (M4): one tick pulls connected providers into normalized tables,
advances the cursor, and never crashes — a near-clone of the reminders tick."""
from datetime import date, datetime, timedelta, timezone

from app import fitness_sync, providers
from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
from app.store import store


def _utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class FakeProvider:
    """A pull provider that replays fixture rows and records the `since` it saw."""

    name = "whoop"
    kind = "pull"

    def __init__(self, recovery=(), sleep=(), workouts=(), fail_auth=False):
        self._recovery = list(recovery)
        self._sleep = list(sleep)
        self._workouts = list(workouts)
        self._fail_auth = fail_auth
        self.since_seen: list = []
        self.injected_tokens: list = []   # records set_tokens() calls

    def authorize_url(self, state):
        return f"https://example.test/auth?state={state}"

    def exchange_code(self, code):
        return Tokens(access_token="a", refresh_token="r", expires_at=None)

    def refresh(self, tokens):
        return tokens

    def set_tokens(self, tokens):
        self.injected_tokens.append(tokens)

    def fetch_recovery(self, since):
        self.since_seen.append(("recovery", since))
        return list(self._recovery)

    def fetch_sleep(self, since):
        self.since_seen.append(("sleep", since))
        return list(self._sleep)

    def fetch_workouts(self, since):
        self.since_seen.append(("workouts", since))
        return list(self._workouts)

    def revoke(self, tokens):
        pass


def _connect(provider="whoop"):
    store.upsert_provider_account(
        provider,
        Tokens(access_token="a", refresh_token="r",
               expires_at=_utc(2030, 1, 1), scopes="read:recovery"),
    )


def test_tick_upserts_merged_snapshot_and_workout_then_advances_cursor():
    day = date(2026, 6, 28)
    recovery = [NormalizedSnapshot(source="whoop", day=day, recovery_pct=66, hrv_ms=48.0,
                                   resting_hr=54)]
    sleep = [NormalizedSnapshot(source="whoop", day=day, sleep_quality_pct=82,
                               sleep_hours=7.4, respiratory_rate=14.2)]
    workouts = [NormalizedWorkout(source="whoop", source_id="w-uuid-1", name="Run",
                                  sport="running", started_at=_utc(2026, 6, 28, 13, 0),
                                  duration_min=42, strain=11.3, calories=480,
                                  avg_hr=150, max_hr=171)]
    fake = FakeProvider(recovery=recovery, sleep=sleep, workouts=workouts)
    providers.configure([fake])
    _connect()

    n = fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0))
    assert n == 2  # one merged snapshot + one workout

    today = store.fitness_today(day)
    assert today["recovery_pct"] == 66
    assert today["sleep_quality_pct"] == 82          # sleep merged onto recovery row
    assert today["day_strain"] is None               # no strain in this fixture
    assert {v["key"]: v["value"] for v in today["vitals"]}["hrv"] == 48.0

    rows = store.list_workouts()
    assert [w["source_id"] for w in rows] == ["w-uuid-1"]
    assert rows[0]["calories"] == 480

    # Cursor advanced to the tick's `now`.
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "whoop")
    assert acct["last_sync_at"] == _utc(2026, 6, 30, 12, 0)


def test_tick_injects_stored_tokens_into_provider_before_fetch():
    """The sync engine must load the connected account's stored tokens and
    inject them (set_tokens) so authed fetch_* carry a Bearer token. Without
    this, real WHOOP calls 401 — a bug FakeProvider would otherwise hide."""
    fake = FakeProvider()
    providers.configure([fake])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="the-access", refresh_token="r",
               expires_at=_utc(2030, 1, 1), scopes="read:recovery"),
    )
    fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0))
    # set_tokens was called once, with the stored access token.
    assert len(fake.injected_tokens) == 1
    assert fake.injected_tokens[0].access_token == "the-access"


def test_first_tick_backfills_from_now_minus_backfill_days():
    fake = FakeProvider()
    providers.configure([fake])
    _connect()
    now = _utc(2026, 6, 30, 12, 0)
    fitness_sync.tick(now=now)
    # No prior last_sync_at -> since == now - whoop_backfill_days (default 30).
    since_values = {kind: s for kind, s in fake.since_seen}
    assert since_values["recovery"] == now - timedelta(days=30)
    assert since_values["sleep"] == now - timedelta(days=30)
    assert since_values["workouts"] == now - timedelta(days=30)


def test_second_tick_uses_stored_cursor_as_since():
    fake = FakeProvider()
    providers.configure([fake])
    _connect()
    first = _utc(2026, 6, 30, 12, 0)
    fitness_sync.tick(now=first)
    fake.since_seen.clear()
    second = _utc(2026, 6, 30, 18, 0)
    fitness_sync.tick(now=second)
    since_values = {kind: s for kind, s in fake.since_seen}
    # The cursor from the first tick (its `now`) is the new `since`.
    assert since_values["recovery"] == first
```

Run the test — it fails because `app/fitness_sync.py` does not exist yet (or only the reminders module exists). Expected: collection/import error.

- [ ] **Step 3: Run the failing test**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py -q
```

Expected: an import error / collection error such as `ModuleNotFoundError: No module named 'app.fitness_sync'` (or `AttributeError: module 'app.fitness_sync' has no attribute 'tick'` if a stub exists). The three tests in this file error out. This confirms the test exercises code that does not yet exist.

- [ ] **Step 4: Implement fitness_sync.py with configure() + tick() (happy path + cursor)**

Create `backend/app/fitness_sync.py`. It mirrors `reminders.py`: a `configure(override)` seam (`"unset"`=real loop active, `None`=disabled), a synchronous `tick(now)` that does one sync pass, and (added in a later task) `trigger()`/`run_loop()`. This step implements `configure` + `tick`'s happy path and cursor logic. Error resilience and `needs_reauth` come in the next task; `trigger`/`run_loop` in the task after.

```python
"""Fitness sync engine (M4) — a background tick + on-demand trigger.

A near-clone of `reminders.py`: a plain asyncio loop (started from the app
lifespan, guarded by `fitness_sync_enabled`) wakes every
`fitness_sync_seconds`, pulls each connected pull-provider since its cursor,
maps the results into the normalized tables, and advances the cursor. The
catch-up is implicit — anything that arrived while the laptop slept lands on
the next tick.

Reads never depend on a live WHOOP call (the screen reads the normalized
tables), so a failed sync just logs and retries next tick; the tick never
crashes. Auth failures flip the provider to `needs_reauth`. Same test seam
as reminders.py: `configure(None)` disables the loop, `configure("unset")`
restores it; providers themselves are swapped via `providers.configure(...)`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import providers
from .config import settings
from .providers.base import NormalizedSnapshot
from .store import store

logger = logging.getLogger("scuffed_os.fitness_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """None disables the background loop (tests); 'unset' restores it.

    The provider *registry* is swapped separately via providers.configure(...).
    This seam only gates run_loop, mirroring reminders.configure.
    """
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _merge_snapshot(into: NormalizedSnapshot, other: NormalizedSnapshot) -> None:
    """Fold `other`'s set fields onto `into` (non-None wins, existing kept).

    recovery and sleep arrive as separate NormalizedSnapshot lists keyed by
    day; the same calendar day must become one row before upsert.
    """
    for f in ("recovery_pct", "day_strain", "sleep_quality_pct", "hrv_ms",
              "resting_hr", "respiratory_rate", "sleep_hours"):
        val = getattr(other, f)
        if val is not None and getattr(into, f) is None:
            setattr(into, f, val)
    merged_metrics = {**other.metrics_json, **into.metrics_json}
    into.metrics_json = merged_metrics


def _merge_by_day(*lists: list[NormalizedSnapshot]) -> list[NormalizedSnapshot]:
    by_day: dict = {}
    for snaps in lists:
        for snap in snaps:
            key = snap.day
            if key in by_day:
                _merge_snapshot(by_day[key], snap)
            else:
                by_day[key] = snap
    return list(by_day.values())


def _load_and_inject_tokens(provider, now: datetime) -> bool:
    """Load the provider's stored tokens, refresh if expired (persisting the
    rotated tokens back), and inject them into the provider so its authed
    fetch_* calls carry a Bearer token. Returns False if no tokens are stored
    (nothing to sync). Raises AuthError on a refresh failure so the caller
    flips needs_reauth. Without this every fetch_* runs with an empty Bearer
    token and 401s — the bug FakeProvider hides because it ignores tokens."""
    tokens = store.get_provider_tokens(provider.name)
    if tokens is None:
        return False
    # Refresh proactively when within ~the skew of expiry. The provider's
    # refresh raises AuthError on failure (propagated to tick).
    refresh = getattr(provider, "refresh", None)
    if (
        tokens.expires_at is not None
        and refresh is not None
        and now >= tokens.expires_at - timedelta(seconds=60)
    ):
        tokens = refresh(tokens)                      # may raise AuthError
        store.upsert_provider_account(provider.name, tokens)  # persist rotation
    set_tokens = getattr(provider, "set_tokens", None)
    if set_tokens is not None:
        set_tokens(tokens)                            # inject for the authed fetch
    return True


def _sync_provider(provider, now: datetime) -> int:
    """One provider's pass. Returns records upserted. Raises AuthError on an
    auth/refresh failure so the caller flips needs_reauth; raises other errors
    so the caller can log-and-continue."""
    acct = next(
        (a for a in store.list_provider_accounts() if a["provider"] == provider.name),
        None,
    )
    if acct is None or acct["status"] != "connected":
        return 0

    # Load + refresh + inject tokens before any authed fetch. No stored tokens
    # (shouldn't happen for a connected account) → nothing to sync.
    if not _load_and_inject_tokens(provider, now):
        return 0

    since = acct["last_sync_at"]
    if since is None:
        since = now - timedelta(days=settings.whoop_backfill_days)

    recovery = provider.fetch_recovery(since)
    sleep = provider.fetch_sleep(since)
    workouts = provider.fetch_workouts(since)

    count = 0
    for snap in _merge_by_day(recovery, sleep):
        store.upsert_snapshot(snap)
        count += 1
    for w in workouts:
        store.upsert_workout(w)  # runs the workout->habit auto-complete
        count += 1

    store.set_provider_synced(provider.name, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every connected pull-provider. Returns how many
    snapshot/workout records were upserted. Safe to call any time; never
    raises (per-provider errors are caught in a later task's hardening)."""
    now = now or _utcnow()
    total = 0
    for provider in providers.pull_providers():
        total += _sync_provider(provider, now)
    return total
```

Note: `_sync_provider` reads `acct["last_sync_at"]` from the safe dict returned by `store.list_provider_accounts()`; that dict carries `provider`, `status`, and `last_sync_at` but never tokens (tokens are server-side only). Provider-error handling and the no-DATABASE_URL guard are added in the next task, so this `tick` still propagates exceptions for now — the happy-path tests don't trigger any.

- [ ] **Step 5: Run the test and see it pass**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py -q
```

Expected: `4 passed`. The merged-snapshot, token-injection, backfill-window, and stored-cursor tests all pass.

- [ ] **Step 6: Run the full suite**

Run the whole suite to confirm the conftest seam edits didn't disturb other tests:

```
cd backend && python -m pytest -q
```

Expected: all tests pass (the suite was green before this phase plus the 3 new tests). Report the pass count, e.g. `N passed`.

- [ ] **Step 7: Commit**

```
cd backend && git add app/fitness_sync.py tests/test_fitness_sync.py tests/conftest.py
git commit -m "feat(fitness): sync tick pulls providers into normalized tables

fitness_sync.tick() iterates connected pull-providers, computes the
incremental since cursor (last_sync_at or now - whoop_backfill_days),
merges same-day recovery+sleep snapshots, upserts snapshots/workouts,
and advances the cursor. Mirrors the reminders tick + configure seam.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: the commit lands on branch `m4-whoop-fitness`.


### Task 16: tick() resilience — per-provider errors never crash, auth failure flips needs_reauth, no DATABASE_URL returns 0

**Files:**
- Modify: `backend/app/fitness_sync.py`
- Modify: `backend/tests/test_fitness_sync.py`
- Test: `backend/tests/test_fitness_sync.py`

**Interfaces:**
- Consumes: Everything from the previous task plus: providers.base.AuthError (the typed auth/refresh-failure error raised by WhoopProvider per contract §D, defined in the provider phase; fitness_sync imports it to classify auth failures); store.set_provider_status(provider, status) where status in {'connected','needs_reauth'} (store phase); the store raising RuntimeError when settings.database_url is unset (existing store._session behaviour, mirrored by reminders.tick)
- Produces: Hardened tick(): a per-provider try/except that catches providers.base.AuthError -> store.set_provider_status(name, 'needs_reauth') and continues; catches every other Exception, logs it, continues (the tick never raises); and a top-level RuntimeError guard returning 0 when no DATABASE_URL is configured (mirrors reminders.tick).

- [ ] **Step 1: Write the failing resilience tests**

Append three tests to `backend/tests/test_fitness_sync.py`: an auth failure on one provider flips it to `needs_reauth` and does NOT raise; a generic (non-auth) error in one provider is swallowed and a second healthy provider still syncs; and `tick()` returns 0 (no raise) when the store has no database configured.

Add these imports at the top of the existing test file if not already present — `pytest` and `AuthError`:

```python
import pytest

from app.providers.base import AuthError
```

(Keep the existing imports; just add `AuthError` to the `from app.providers.base import ...` line and add the `import pytest` line.)

Then append:

```python
class _AuthFailProvider(FakeProvider):
    """A pull provider whose fetch raises the typed auth error."""

    def fetch_recovery(self, since):
        raise AuthError("refresh failed; token revoked")


class _BoomProvider(FakeProvider):
    """A pull provider that raises a generic (non-auth) error."""

    def fetch_recovery(self, since):
        raise RuntimeError("WHOOP 500")


def test_auth_failure_flips_needs_reauth_and_does_not_raise():
    providers.configure([_AuthFailProvider()])
    _connect()
    # Must not raise.
    assert fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0)) == 0
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "whoop")
    assert acct["status"] == "needs_reauth"


def test_generic_error_is_swallowed_and_other_providers_still_sync():
    boom = _BoomProvider()
    boom.name = "whoop"
    healthy = FakeProvider(
        recovery=[NormalizedSnapshot(source="oura", day=date(2026, 6, 28),
                                     recovery_pct=70)],
    )
    healthy.name = "oura"
    providers.configure([boom, healthy])
    store.upsert_provider_account(
        "whoop", Tokens(access_token="a", refresh_token="r", expires_at=_utc(2030, 1, 1)))
    store.upsert_provider_account(
        "oura", Tokens(access_token="a", refresh_token="r", expires_at=_utc(2030, 1, 1)))

    # Boom is swallowed; the healthy provider's one snapshot still lands.
    assert fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0)) == 1
    # The crashing provider is NOT flipped to needs_reauth (that's auth-only).
    whoop = next(a for a in store.list_provider_accounts() if a["provider"] == "whoop")
    assert whoop["status"] == "connected"


def test_tick_returns_zero_when_no_database(monkeypatch):
    from app.store import store as real_store
    # Simulate the store with no DATABASE_URL: list_provider_accounts raises
    # RuntimeError, exactly like reminders.tick's due_reminders guard.
    def _boom():
        raise RuntimeError("DATABASE_URL is not set")
    monkeypatch.setattr(real_store, "list_provider_accounts", _boom)
    providers.configure([FakeProvider()])
    assert fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0)) == 0
```

Run the file — the auth and generic tests fail (current `tick` re-raises) and the no-database test fails (current `tick` propagates the RuntimeError).

- [ ] **Step 2: Run the failing tests**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py -q
```

Expected: the three new tests fail/error — `test_auth_failure_flips_needs_reauth_and_does_not_raise` raises `AuthError`, `test_generic_error_is_swallowed_and_other_providers_still_sync` raises `RuntimeError`, and `test_tick_returns_zero_when_no_database` raises `RuntimeError`. The earlier happy-path tests still pass.

- [ ] **Step 3: Harden tick(): per-provider try/except + needs_reauth + no-DB guard**

Edit `backend/app/fitness_sync.py`. Add the `AuthError` import and rewrite `tick` to wrap each provider in try/except and guard the whole pass against a missing database. The `_sync_provider`, `_merge_*` helpers from the previous task are unchanged.

Change the import block — add `AuthError`:

```python
from .providers.base import AuthError, NormalizedSnapshot
```

Replace the `tick` function body with:

```python
def tick(now: datetime | None = None) -> int:
    """One sync pass over every connected pull-provider. Returns how many
    snapshot/workout records were upserted. Safe to call any time — per-provider
    errors are caught and logged so the tick never crashes; auth failures flip
    the provider to needs_reauth. Returns 0 when no database is configured
    (RuntimeError caught, like reminders.tick)."""
    now = now or _utcnow()
    try:
        provider_list = providers.pull_providers()
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
            # No DATABASE_URL surfaced mid-pass (e.g. list_provider_accounts) —
            # treat the whole pass as a no-op, like reminders.tick.
            if "DATABASE_URL" in str(exc):
                return total
            logger.exception("sync failed for %s", provider.name)
        except Exception:
            logger.exception("sync failed for %s", provider.name)
    return total
```

Note: the `RuntimeError` branch first checks for the DATABASE_URL message so the no-database test returns 0 (the `_BoomProvider` raises `RuntimeError("WHOOP 500")`, which does NOT contain `DATABASE_URL`, so it falls through to log-and-continue). `AuthError` is matched before generic `Exception` so a revoked token never reaches the generic branch. Because `AuthError` subclasses `Exception` (not `RuntimeError`), ordering the `except AuthError` first is required.

- [ ] **Step 4: Run the tests and see them pass**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py -q
```

Expected: `7 passed` (the 4 happy-path/token-injection tests from the previous task plus the 3 resilience tests).

- [ ] **Step 5: Run the full suite**

```
cd backend && python -m pytest -q
```

Expected: all tests pass. Report the pass count.

- [ ] **Step 6: Commit**

```
cd backend && git add app/fitness_sync.py tests/test_fitness_sync.py
git commit -m "feat(fitness): harden sync tick against provider failures

Per-provider try/except so one provider's network/500 error never
crashes the tick; a typed AuthError flips the provider to needs_reauth
and other providers still sync. A missing DATABASE_URL returns 0,
mirroring reminders.tick.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: commit on `m4-whoop-fitness`.


### Task 17: trigger() coroutine + run_loop() background task

**Files:**
- Modify: `backend/app/fitness_sync.py`
- Modify: `backend/tests/test_fitness_sync.py`
- Test: `backend/tests/test_fitness_sync.py`

**Interfaces:**
- Consumes: tick(now) from the previous tasks; settings.fitness_sync_seconds:int (config phase); asyncio (stdlib). No new store/provider symbols.
- Produces: async def trigger() -> int — an awaitable that runs ONE tick off the event loop (await asyncio.to_thread(tick)) and returns its count; this is the coroutine the OAuth callback (router phase) and POST /api/fitness/sync (api phase) await for an immediate sync. async def run_loop() -> None — the lifespan task that ticks forever every settings.fitness_sync_seconds until cancelled. Signature for downstream phases: `await fitness_sync.trigger() -> int`.

- [ ] **Step 1: Write the failing test for trigger()**

Append a test to `backend/tests/test_fitness_sync.py` proving `trigger()` is an awaitable that runs exactly one tick (upserting fixture data) and returns the upserted count. Use `asyncio.run` to drive the coroutine inside a sync test (the suite has no async plugin; `asyncio.run` is the established pattern for the rare coroutine).

Add `import asyncio` at the top of the test file (next to `import pytest`), then append:

```python
def test_trigger_runs_one_tick_and_returns_count():
    fake = FakeProvider(
        workouts=[NormalizedWorkout(source="whoop", source_id="w-1", name="Lift",
                                    sport="weightlifting",
                                    started_at=_utc(2026, 6, 29, 7, 0),
                                    duration_min=55)],
    )
    providers.configure([fake])
    _connect()
    n = asyncio.run(fitness_sync.trigger())
    assert n == 1
    assert [w["source_id"] for w in store.list_workouts()] == ["w-1"]
```

Run the file — fails with `AttributeError: module 'app.fitness_sync' has no attribute 'trigger'`.

- [ ] **Step 2: Run the failing test**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py::test_trigger_runs_one_tick_and_returns_count -q
```

Expected: failure — `AttributeError: module 'app.fitness_sync' has no attribute 'trigger'`.

- [ ] **Step 3: Implement trigger() and run_loop()**

Append `trigger` and `run_loop` to `backend/app/fitness_sync.py` (after `tick`). `trigger` runs one tick off the event loop and returns the count; `run_loop` is the lifespan task, gated only by being created (the lifespan in main.py decides whether to start it via `settings.fitness_sync_enabled` — `run_loop` itself just ticks forever, exactly like `reminders.run_loop`).

```python
async def trigger() -> int:
    """Run one sync pass off the event loop and return its count.

    Awaited by the OAuth callback (immediate post-connect sync + backfill)
    and by POST /api/fitness/sync. Errors are already swallowed inside tick,
    so this never raises for provider problems.
    """
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """The lifespan background task; ticks forever until cancelled."""
    logger.info("fitness sync loop started (every %ss)", settings.fitness_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d fitness record(s)", synced)
        except Exception:
            logger.exception("fitness sync tick failed")
        await asyncio.sleep(settings.fitness_sync_seconds)
```

Note: `tick` already catches per-provider errors, so the `try/except` in `run_loop` is belt-and-braces (mirrors `reminders.run_loop`) for anything outside the provider loop. `trigger` deliberately does NOT loop — it is a single immediate pass.

- [ ] **Step 4: Run the test and see it pass**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py -q
```

Expected: `7 passed` (the 6 prior tests plus `test_trigger_runs_one_tick_and_returns_count`).

- [ ] **Step 5: Run the full suite**

```
cd backend && python -m pytest -q
```

Expected: all tests pass. Report the pass count.

- [ ] **Step 6: Commit**

```
cd backend && git add app/fitness_sync.py tests/test_fitness_sync.py
git commit -m "feat(fitness): add trigger() coroutine and run_loop() for sync

trigger() runs one immediate tick off the event loop (awaited by the
OAuth callback and POST /api/fitness/sync); run_loop() is the lifespan
task ticking every fitness_sync_seconds, mirroring reminders.run_loop.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: commit on `m4-whoop-fitness`.


### Task 18: Lifespan wiring — start the fitness sync loop alongside reminders

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_fitness_sync.py`
- Test: `backend/tests/test_fitness_sync.py`

**Interfaces:**
- Consumes: fitness_sync.run_loop() and settings.fitness_sync_enabled from the prior tasks/config phase; the existing main.lifespan + reminders.run_loop wiring; TestClient (fastapi.testclient) used as a context manager to actually drive lifespan startup/shutdown.
- Produces: main.lifespan starts a second background task (settings.fitness_sync_enabled-guarded) running fitness_sync.run_loop(), tracked separately and cancelled on shutdown alongside the reminder task. No public signature changes.

- [ ] **Step 1: Write the failing test for lifespan startup**

Append a test to `backend/tests/test_fitness_sync.py` proving the app lifespan creates the fitness-sync task when enabled. Drive the lifespan by entering the `TestClient` as a context manager (FastAPI runs startup on `__enter__`, shutdown on `__exit__`), and spy on `fitness_sync.run_loop` so no real loop runs.

Append:

```python
def test_lifespan_starts_fitness_sync_loop_when_enabled(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings as app_settings
    from app.main import app

    started = {"fitness": False}

    async def fake_run_loop():
        started["fitness"] = True
        # Sleep forever so the task is alive across the client's lifetime;
        # cancellation on shutdown ends it.
        await asyncio.sleep(3600)

    monkeypatch.setattr(app_settings, "fitness_sync_enabled", True)
    monkeypatch.setattr(app_settings, "reminders_enabled", False)  # isolate this loop
    monkeypatch.setattr(fitness_sync, "run_loop", fake_run_loop)

    with TestClient(app):
        pass  # entering/exiting runs startup then shutdown

    assert started["fitness"] is True


def test_lifespan_skips_fitness_sync_loop_when_disabled(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings as app_settings
    from app.main import app

    started = {"fitness": False}

    async def fake_run_loop():
        started["fitness"] = True
        await asyncio.sleep(3600)

    monkeypatch.setattr(app_settings, "fitness_sync_enabled", False)
    monkeypatch.setattr(app_settings, "reminders_enabled", False)
    monkeypatch.setattr(fitness_sync, "run_loop", fake_run_loop)

    with TestClient(app):
        pass

    assert started["fitness"] is False
```

Run the file — `test_lifespan_starts_fitness_sync_loop_when_enabled` fails because the current `main.lifespan` never calls `fitness_sync.run_loop` (so `started["fitness"]` stays False); the disabled test passes vacuously.

- [ ] **Step 2: Run the failing test**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py::test_lifespan_starts_fitness_sync_loop_when_enabled -q
```

Expected: failure — `assert started["fitness"] is True` fails because the fitness loop is never started by the current lifespan.

- [ ] **Step 3: Wire fitness_sync.run_loop into main.lifespan**

Edit `backend/app/main.py`. Import `fitness_sync` and the fitness routers (the routers are created in the api phase; import them here so the wiring is complete — if the api phase has not landed yet, import only `fitness_sync` and add the router includes when `app/routers/fitness.py` exists). Track a second task var and cancel both on shutdown.

Change the import line:

```python
from . import reminders
```

to:

```python
from . import fitness_sync, reminders
```

Replace the `lifespan` function with:

```python
@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the reminder tick and the fitness-sync loop alongside the server;
    stop them on shutdown."""
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

Do NOT add the `fitness.router` / `fitness.auth_router` includes in this phase if `app/routers/fitness.py` does not yet exist — those `app.include_router(...)` lines belong to the api phase (contract §L). This task only owns the lifespan loop wiring. (If the api phase has already landed and the module exists, the includes are already present; leave them.)

- [ ] **Step 4: Run the test and see it pass**

Run:

```
cd backend && python -m pytest tests/test_fitness_sync.py -q
```

Expected: `9 passed` (the 7 prior tests plus the two lifespan tests). The enabled test now observes `started["fitness"] is True`; the disabled test confirms the guard.

- [ ] **Step 5: Run the full suite**

```
cd backend && python -m pytest -q
```

Expected: all tests pass — the lifespan change is guarded by `settings.fitness_sync_enabled` and uses the same cancel-on-shutdown pattern as the reminder task, so existing app/lifespan tests are unaffected. Report the pass count.

- [ ] **Step 6: Commit**

```
cd backend && git add app/main.py tests/test_fitness_sync.py
git commit -m "feat(fitness): start the sync loop in the app lifespan

lifespan now starts fitness_sync.run_loop() alongside the reminder tick,
guarded by settings.fitness_sync_enabled, and cancels both tasks on
shutdown. Router includes stay with the API phase.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: commit on `m4-whoop-fitness`.


## Phase: OAuth endpoints + router creation

### Task 19: Fitness router skeleton + CSRF state store + connect endpoint + main.py wiring

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`

**Interfaces:**
- Consumes: From the provider seam phase (app/providers/): providers.configure(override="unset"), providers.get(name) -> FitnessProvider | None, and the FitnessProvider protocol with name: str / kind / authorize_url(self, state: str) -> str. From the schemas defined at the top of this OAuth phase (Task 19 Step 5a, below): ConnectUrl(authorize_url: str), ProviderStatus, FitnessStatus. From the sync phase: fitness_sync.configure(override="unset") and the conftest seam resets (already wired in Task 15). (The connect endpoint never touches the store or sync; it only needs the provider + a CSRF state dict.)
- Produces: The OAuth-phase Pydantic schemas (ConnectUrl, ProviderStatus, FitnessStatus) appended to schemas.py so every later OAuth task (status/callback/disconnect) imports a defined name. app/routers/fitness.py exporting two routers: router = APIRouter(prefix="/api/fitness", tags=["fitness"]) and auth_router = APIRouter(tags=["fitness-oauth"]). A module-level CSRF state store: _STATES: dict[str, str] mapping random state -> provider, plus helpers _issue_state(provider) -> str and _consume_state(state) -> str | None (pop, one-time). GET /api/fitness/connect/{provider} -> ConnectUrl. Both routers wired into app in main.py. tests/fakes.py gains FakeProvider. (conftest is NOT edited here — its providers/fitness_sync resets landed in Task 15.)

- [ ] **Step 1: Add FakeProvider to tests/fakes.py**

The OAuth router tests run against a fake provider installed via `providers.configure([FakeProvider()])` — no network. Append this class to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/fakes.py` (it imports the normalized dataclasses from the provider seam phase). It records `exchange_code` / `refresh` / `revoke` calls so later tasks can assert them, and builds an authorize URL that embeds `client_id` and the `state` so the connect test can assert both appear.

```python
# ---- fitness provider seam (M4) -------------------------------------------
from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens


class FakeProvider:
    """Scriptable stand-in for WhoopProvider — no network.

    Installed with ``providers.configure([FakeProvider()])``. Records the
    calls the OAuth router makes so tests can assert exchange/revoke ran.
    """

    name = "whoop"
    kind = "pull"

    def __init__(
        self,
        *,
        tokens: Tokens | None = None,
        snapshots: list[NormalizedSnapshot] | None = None,
        workouts: list[NormalizedWorkout] | None = None,
    ) -> None:
        self.tokens = tokens or Tokens(
            access_token="fake-access",
            refresh_token="fake-refresh",
            expires_at=None,
            scopes="read:recovery read:workout",
            provider_user_id="whoop-user-1",
        )
        self.snapshots = snapshots or []
        self.workouts = workouts or []
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []

    def authorize_url(self, state: str) -> str:
        return (
            "https://api.prod.whoop.com/oauth/oauth2/auth"
            f"?client_id=fake-client&response_type=code&state={state}"
        )

    def exchange_code(self, code: str) -> Tokens:
        self.exchanged.append(code)
        return self.tokens

    def refresh(self, tokens: Tokens) -> Tokens:
        self.refreshed.append(tokens)
        return self.tokens

    def fetch_recovery(self, since):
        return list(self.snapshots)

    def fetch_sleep(self, since):
        return []

    def fetch_workouts(self, since):
        return list(self.workouts)

    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)
```

- [ ] **Step 2: Confirm the conftest seam is already wired (no edit here)**

The `no_external_services` fixture already resets the `providers` and `fitness_sync` seams — that single rewrite landed in Task 15 (the sync phase), which runs before this OAuth phase. Do NOT re-edit `conftest.py` here. The default in every test is `providers.configure([])` (empty registry) with `fitness_sync.configure(None)` (sync loop disabled); each connect/status/callback/disconnect test below installs its own `FakeProvider` via `providers.configure([FakeProvider()])`.

Sanity-check the fixture is in place before writing the router tests:

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && grep -n "fitness_sync.configure\|providers.configure" tests/conftest.py`

Expected: shows the `providers.configure([])` / `fitness_sync.configure(None)` setup lines and the `providers.configure("unset")` / `fitness_sync.configure("unset")` teardown lines from Task 15. If they are missing, the sync phase was not completed — finish Task 15 first rather than editing conftest here.

- [ ] **Step 3: Write the failing test for GET /api/fitness/connect/{provider}**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py` with the connect tests. The fake's authorize URL embeds `client_id=fake-client` and the issued `state`; the test asserts both are present and that the state was actually stored server-side (a second, distinct connect issues a different state).

```python
"""WHOOP OAuth router (M4): connect URL, callback, disconnect, status.

Every test installs a FakeProvider via providers.configure([...]) — no network.
The CSRF state store is the fitness router's in-process dict.
"""
from urllib.parse import parse_qs, urlparse

from app import providers
from app.routers import fitness

from .fakes import FakeProvider


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def test_connect_returns_authorize_url_with_client_id_and_state(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/fitness/connect/whoop")
    assert res.status_code == 200
    url = res.json()["authorize_url"]
    assert "client_id=fake-client" in url
    qs = parse_qs(urlparse(url).query)
    assert qs["state"][0]  # a non-empty state made it into the URL


def test_connect_stores_a_one_time_state_server_side(client):
    providers.configure([FakeProvider()])
    state = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    # The issued state is recorded server-side, mapped to its provider.
    assert fitness._STATES.get(state) == "whoop"
    # A second connect issues a fresh, distinct state (not reused).
    state2 = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    assert state2 != state


def test_connect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])  # only 'whoop' registered
    res = client.get("/api/fitness/connect/garmin")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
```

- [ ] **Step 4: Run the test and watch it fail (no router yet)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -q`

Expected: collection/import error because `app.routers.fitness` does not exist yet (and the route is unregistered):
```
E   ModuleNotFoundError: No module named 'app.routers.fitness'
```
(If the providers seam phase has not landed, you may instead see `ModuleNotFoundError: No module named 'app.providers'` from the conftest import — that is the upstream dependency this phase consumes; it must be present before this phase runs.)

- [ ] **Step 5: Define the OAuth-phase schemas in schemas.py (BEFORE the router imports them)**

The router this phase builds imports `ConnectUrl` (and Tasks 20-22 import `ProviderStatus` / `FitnessStatus`). Those schemas must be DEFINED before any OAuth task consumes them, so define them here, at the head of the OAuth phase. The remaining read/write schemas (`FitnessVital`, `FitnessToday`, `WorkoutOut`, `WorkoutCreate`, `FitnessWeekDay`, `FitnessWeek`, `FitnessSource`) are appended later in Task 23; Task 23 guards against re-defining the three added here.

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py` (after the `FoodHit` class, end of file). These mirror the existing conventions (`Literal` status, `datetime` timestamps):

```python


# ---- Fitness OAuth schemas (M4) — defined at the head of the OAuth phase ----
# (Task 19; the read/write schemas land in Task 23, which skips these three.)
class ProviderStatus(BaseModel):
    provider: str
    status: Literal["connected", "needs_reauth"]
    connected_at: datetime
    last_sync_at: datetime | None
    provider_user_id: str | None = None


class FitnessStatus(BaseModel):
    connected: bool  # any provider connected
    providers: List[ProviderStatus]


class ConnectUrl(BaseModel):
    authorize_url: str
```

Quick check that the names import:

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "from app.schemas import ConnectUrl, FitnessStatus, ProviderStatus; print('schemas ok')"`

Expected: prints `schemas ok`.

- [ ] **Step 6: Create app/routers/fitness.py with the state store, both routers, and the connect endpoint**

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`. Two routers are exported: `router` (prefixed `/api/fitness`) and `auth_router` (no prefix — its callback path is registered verbatim at `/auth/{provider}/callback`, outside `/api`). The CSRF state store is a module-level dict; `_issue_state` mints a `secrets.token_urlsafe` state mapped to its provider, `_consume_state` pops it (one-time). Only the connect endpoint exists for now; the callback/disconnect/status land in later tasks.

```python
"""Fitness endpoints (M4) — WHOOP OAuth + normalized reads/writes.

The read/write surface (/today, /workouts, /week) lands in a later phase;
this module owns the OAuth dance: connect (build authorize URL + issue a
one-time CSRF state), the callback (verify state -> exchange -> persist ->
immediate sync), disconnect (revoke best-effort -> delete provider data),
and per-provider status. Tokens never leave the server.

Two routers are exported: `router` under /api/fitness, and `auth_router`
with NO prefix so the WHOOP-registered redirect lands at exactly
/auth/{provider}/callback (outside /api). main.py includes both.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException

from .. import providers
from ..schemas import ConnectUrl

router = APIRouter(prefix="/api/fitness", tags=["fitness"])
auth_router = APIRouter(tags=["fitness-oauth"])

# One-time CSRF states: state token -> provider name. In-process is fine for
# a single-user desktop app (the spec's "stored server-side, one-time CSRF
# check"); a process restart mid-flow just makes the user click Connect again.
_STATES: dict[str, str] = {}


def _issue_state(provider: str) -> str:
    state = secrets.token_urlsafe(24)
    _STATES[state] = provider
    return state


def _consume_state(state: str) -> str | None:
    """Pop a state, returning the provider it was issued for (one-time use)."""
    return _STATES.pop(state, None)


@router.get("/connect/{provider}", response_model=ConnectUrl)
def connect(provider: str) -> dict:
    """Build the provider's authorize URL with a fresh one-time CSRF state."""
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    state = _issue_state(provider)
    return {"authorize_url": impl.authorize_url(state)}
```

- [ ] **Step 7: Wire both routers into main.py**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py`. Import the fitness routers and include both — `auth_router` carries no prefix, so its callback registers at `/auth/{provider}/callback`, outside `/api`.

Change the router import:
```python
from .routers import assistant, calendar, habits, memory, nutrition, tasks
```
to:
```python
from .routers import assistant, calendar, fitness, habits, memory, nutrition, tasks
```

Add the includes after the existing `nutrition` line:
```python
app.include_router(nutrition.router)
```
becomes:
```python
app.include_router(nutrition.router)
app.include_router(fitness.router)
app.include_router(fitness.auth_router)
```

(Lifespan registration of `fitness_sync.run_loop()` belongs to the sync phase — leave the lifespan untouched here.)

- [ ] **Step 8: Run the connect tests and watch them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -q`

Expected: the three connect tests pass:
```
...                                                                      [100%]
3 passed in 0.XXs
```

- [ ] **Step 9: Run the full suite to confirm green**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: every test passes (the new connect tests plus all existing ones), reported as e.g.:
```
XXX passed in X.XXs
```
Report the pass count. If the providers/schemas/sync phases are present this is fully green; the only acceptable change vs. the pre-phase baseline is the 3 new passing tests.

- [ ] **Step 10: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/schemas.py backend/app/routers/fitness.py backend/app/main.py backend/tests/test_fitness_oauth.py backend/tests/fakes.py && git commit -m "feat(fitness): WHOOP OAuth router skeleton + connect endpoint + OAuth schemas

Add the OAuth-phase schemas (ProviderStatus, FitnessStatus, ConnectUrl)
to schemas.py so the router and later OAuth tasks import defined names.
Add app/routers/fitness.py exporting the /api/fitness router and a
prefix-less auth_router (callback mounts at /auth/{provider}/callback).
GET /api/fitness/connect/{provider} issues a one-time CSRF state and
returns the provider authorize URL. Wire both routers into main.py;
add FakeProvider to tests/fakes.py.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit created on the `m4-whoop-fitness` branch.


### Task 20: GET /api/fitness/status endpoint

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`

**Interfaces:**
- Consumes: From this phase's Task 1: app/routers/fitness.py `router`. From the store phase: store.list_provider_accounts() -> list[dict] (safe dicts, no tokens; each has provider/status/connected_at/last_sync_at/provider_user_id) and store.upsert_provider_account(provider, tokens) -> dict (used by the test to seed a connected account). From the schemas phase: FitnessStatus(connected: bool, providers: List[ProviderStatus]) and ProviderStatus(provider, status, connected_at, last_sync_at, provider_user_id). From the provider seam: the Tokens dataclass (the test builds one to seed an account).
- Produces: GET /api/fitness/status -> FitnessStatus on `router`. `connected` is True iff any provider account has status 'connected'.

- [ ] **Step 1: Write the failing test for GET /api/fitness/status**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`. Empty state reports no providers; after seeding a connected account via the store, status reflects it and never leaks tokens.

```python
from datetime import datetime, timezone

from app.providers.base import Tokens
from app.store import store


def test_status_empty_when_nothing_connected(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/fitness/status")
    assert res.status_code == 200
    body = res.json()
    assert body == {"connected": False, "providers": []}


def test_status_reflects_a_connected_account_without_tokens(client):
    providers.configure([FakeProvider()])
    store.upsert_provider_account(
        "whoop",
        Tokens(
            access_token="secret-access",
            refresh_token="secret-refresh",
            expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scopes="read:recovery",
            provider_user_id="whoop-user-1",
        ),
    )
    body = client.get("/api/fitness/status").json()
    assert body["connected"] is True
    assert len(body["providers"]) == 1
    p = body["providers"][0]
    assert p["provider"] == "whoop"
    assert p["status"] == "connected"
    assert p["provider_user_id"] == "whoop-user-1"
    assert p["last_sync_at"] is None
    # Tokens must never reach the client.
    assert "secret-access" not in res_text(body)
    assert "access_token" not in p and "refresh_token" not in p


def res_text(obj) -> str:
    import json
    return json.dumps(obj)
```

- [ ] **Step 2: Run the test and watch it fail (route 404)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -k status -q`

Expected: failures because `/api/fitness/status` is not registered yet — FastAPI returns 404 with the not_found envelope, so the `status_code == 200` assertion fails:
```
E   assert 404 == 200
```

- [ ] **Step 3: Add the status endpoint**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`. Add `FitnessStatus` to the schema import and append the route. `connected` is derived from the safe dicts the store returns (tokens already stripped there).

Change the import:
```python
from ..schemas import ConnectUrl
```
to:
```python
from ..schemas import ConnectUrl, FitnessStatus
```

Add the import for the store near the top (after the providers import):
```python
from .. import providers
```
becomes:
```python
from .. import providers
from ..store import store
```

Append the route (after `connect`):
```python
@router.get("/status", response_model=FitnessStatus)
def status() -> dict:
    """Per-provider connection state. Reads safe dicts only — no tokens."""
    accounts = store.list_provider_accounts()
    return {
        "connected": any(a["status"] == "connected" for a in accounts),
        "providers": accounts,
    }
```

- [ ] **Step 4: Run the status tests and watch them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -k status -q`

Expected:
```
..                                                                       [100%]
2 passed in 0.XXs
```

- [ ] **Step 5: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass; report the pass count (2 new status tests on top of the prior total).

- [ ] **Step 6: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/routers/fitness.py backend/tests/test_fitness_oauth.py && git commit -m "feat(fitness): GET /api/fitness/status per-provider state

Returns FitnessStatus from store.list_provider_accounts (safe dicts,
never tokens); connected is true iff any account is connected.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit on `m4-whoop-fitness`.


### Task 21: GET /auth/{provider}/callback — verify state, exchange, persist, immediate sync, redirect

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`

**Interfaces:**
- Consumes: From this phase's Task 1: auth_router, _issue_state, _consume_state, _STATES. From the provider seam: providers.get(name); the FakeProvider.exchange_code(code) -> Tokens recorder; the real WhoopProvider.fetch_profile(tokens) -> str | None (the callback calls it via getattr so a fake without the method is fine — FakeProvider's Tokens already carry provider_user_id, so the fetch branch is skipped in tests). From the store phase: store.upsert_provider_account(provider, tokens) -> dict (creates/updates the account, status='connected'). From the sync phase: fitness_sync.tick(now=None) -> int (one immediate sync pass; backfill is implicit because the fresh account's last_sync_at is null, so the sync engine reads since = now - whoop_backfill_days). The test spies on tick by monkeypatching fitness_sync.tick.
- Produces: GET /auth/{provider}/callback on auth_router (path verbatim, outside /api). Query params code: str, state: str. On a valid state: consumes it, calls provider.exchange_code, store.upsert_provider_account, then fitness_sync.tick() for an immediate sync+backfill, and returns a RedirectResponse to the Fitness screen with a success flag (/?screen=fitness&connected=whoop). Bad/replayed state -> HTTPException(400). Unknown provider -> 404.

- [ ] **Step 1: Write the failing callback tests**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`. The happy path: connect issues a real state, the callback with that state + a fake code exchanges tokens, persists the account, fires exactly one immediate sync, and 302-redirects to the Fitness screen with a success flag. A forged/replayed state is rejected with 400 and persists nothing.

```python
def test_callback_exchanges_persists_and_triggers_immediate_sync(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    ticks: list[object] = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: ticks.append(now) or 0)

    state = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    res = client.get(
        f"/auth/whoop/callback?code=the-code&state={state}",
        follow_redirects=False,
    )
    assert res.status_code in (302, 307)
    loc = res.headers["location"]
    assert "screen=fitness" in loc and "connected=whoop" in loc

    # The code was exchanged exactly once and the account was persisted.
    assert fake.exchanged == ["the-code"]
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"
    assert accounts[0]["provider_user_id"] == "whoop-user-1"
    # An immediate sync (backfill) was triggered once.
    assert len(ticks) == 1
    # The state was one-time: it is gone from the store.
    assert state not in fitness._STATES


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
    state = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    first = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert first.status_code in (302, 307)
    # Replaying the same state must now fail — it was consumed.
    replay = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert replay.status_code == 400
```

- [ ] **Step 2: Run the test and watch it fail (callback route missing)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -k callback -q`

Expected: the callback path is unregistered, so FastAPI 404s and the redirect/status assertions fail:
```
E   assert 404 in (302, 307)
```

- [ ] **Step 3: Implement the callback on auth_router**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`. Add imports for `Query`, `RedirectResponse`, and `fitness_sync`, then append the callback to `auth_router`. The state must be consumed and matched to the path provider before any token exchange; the immediate `tick()` does the backfill (the just-created account has `last_sync_at=None`).

Change the FastAPI import:
```python
from fastapi import APIRouter, HTTPException
```
to:
```python
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
```

Add `fitness_sync` to the package import group:
```python
from .. import providers
from ..store import store
```
becomes:
```python
from .. import fitness_sync, providers
from ..store import store
```

Append the callback route (on `auth_router`, after the `/connect` and `/status` routes):
```python
# Redirect target after a successful connect — the SPA reads screen/connected.
_FITNESS_REDIRECT = "/?screen=fitness&connected={provider}"


@auth_router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """OAuth redirect target (outside /api). Verify the one-time CSRF state,
    exchange the code, fetch the profile id, persist tokens server-side, kick
    off an immediate sync+backfill, then bounce back to the Fitness screen."""
    issued_for = _consume_state(state)
    if issued_for is None or issued_for != provider:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    tokens = impl.exchange_code(code)
    # exchange_code does NOT carry provider_user_id (the token payload has no
    # profile). Fetch it from the provider's basic-profile endpoint and stamp
    # it onto the tokens so upsert persists it server-side. fetch_profile is
    # best-effort: a None just leaves provider_user_id unset.
    fetch_profile = getattr(impl, "fetch_profile", None)
    if fetch_profile is not None and tokens.provider_user_id is None:
        uid = fetch_profile(tokens)
        if uid is not None:
            tokens.provider_user_id = uid
    store.upsert_provider_account(provider, tokens)
    # Immediate sync: the fresh account has no last_sync_at, so the sync
    # engine backfills whoop_backfill_days on this first pass.
    fitness_sync.tick()
    return RedirectResponse(_FITNESS_REDIRECT.format(provider=provider), status_code=302)
```

- [ ] **Step 4: Run the callback tests and watch them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -k callback -q`

Expected:
```
...                                                                      [100%]
3 passed in 0.XXs
```

- [ ] **Step 5: Run the full suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass; report the pass count (3 new callback tests added).

- [ ] **Step 6: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/routers/fitness.py backend/tests/test_fitness_oauth.py && git commit -m "feat(fitness): OAuth callback at /auth/{provider}/callback

Verify the one-time CSRF state, exchange the code, persist tokens
server-side via upsert_provider_account, trigger an immediate
sync+backfill (fitness_sync.tick), and redirect to the Fitness screen.
Forged/replayed state -> 400; the state is single-use.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit on `m4-whoop-fitness`.


### Task 22: POST /api/fitness/disconnect/{provider} — best-effort revoke then delete

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`

**Interfaces:**
- Consumes: From this phase's Tasks 1-2: `router`, the FitnessStatus response shape, the status endpoint. From the provider seam: providers.get(name); FakeProvider.revoke(tokens) recorder. From the store phase: store.get_provider_tokens(provider) -> Tokens | None (the tokens handed to revoke), store.delete_provider_data(provider) -> bool (deletes account + that provider's daily_snapshots/workouts, preserving manual workouts), store.list_provider_accounts() (to rebuild FitnessStatus), and store.upsert_provider_account (test seeds an account to disconnect).
- Produces: POST /api/fitness/disconnect/{provider} -> FitnessStatus on `router`. Best-effort revoke (swallows revoke errors so deletion is the guarantee), then delete_provider_data, then returns the refreshed FitnessStatus. Unknown provider with no account -> 404.

- [ ] **Step 1: Write the failing disconnect tests**

Append to `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_oauth.py`. Disconnect revokes at the provider, deletes the account, and returns an empty FitnessStatus. A provider revoke that raises must NOT block deletion (deletion is the user-facing guarantee). Disconnecting something never connected is a 404.

```python
def test_disconnect_revokes_then_deletes_and_returns_status(client):
    fake = FakeProvider()
    providers.configure([fake])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="a", refresh_token="r", expires_at=None,
               scopes="read:recovery", provider_user_id="u1"),
    )
    assert client.get("/api/fitness/status").json()["connected"] is True

    res = client.post("/api/fitness/disconnect/whoop")
    assert res.status_code == 200
    assert res.json() == {"connected": False, "providers": []}
    # The provider's revoke was attempted with the stored tokens.
    assert len(fake.revoked) == 1
    assert fake.revoked[0].access_token == "a"
    # And the account is gone.
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
    res = client.post("/api/fitness/disconnect/whoop")
    assert res.status_code == 200
    assert res.json()["connected"] is False
    assert store.list_provider_accounts() == []  # deleted despite the revoke error


def test_disconnect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])
    res = client.post("/api/fitness/disconnect/whoop")  # nothing connected
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Run the test and watch it fail (route 404)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -k disconnect -q`

Expected: the disconnect route is unregistered, so the POST 404s and the `status_code == 200` assertions fail:
```
E   assert 404 == 200
```
(The `test_disconnect_unknown_provider_is_404` case happens to want a 404 too, but for the wrong reason — method-not-allowed/route-missing rather than the intended no-account 404 — so it is not a reliable pass yet; the implementation makes all three pass for the right reasons.)

- [ ] **Step 3: Implement the disconnect endpoint**

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`. Add a module logger, then append the disconnect route to `router`. Revoke is best-effort and wrapped so a provider-side failure never blocks the local deletion; if no account existed, `delete_provider_data` returns False and we 404.

Add `logging` to the stdlib imports at the top:
```python
import secrets
```
becomes:
```python
import logging
import secrets
```

Add a logger after the router definitions (near `_STATES`):
```python
logger = logging.getLogger("scuffed_os.fitness")
```

Append the route (after `status`):
```python
@router.post("/disconnect/{provider}", response_model=FitnessStatus)
def disconnect(provider: str) -> dict:
    """Revoke at the provider (best-effort), then delete its tokens + synced
    data. Manual workouts are preserved (the store keeps source != provider).
    Deletion is the user-facing guarantee, so a failed revoke never blocks it."""
    impl = providers.get(provider)
    tokens = store.get_provider_tokens(provider)
    if impl is not None and tokens is not None:
        try:
            impl.revoke(tokens)
        except Exception as exc:  # noqa: BLE001 — revoke is best-effort
            logger.warning("revoke failed for %s, deleting anyway: %s", provider, exc)
    if not store.delete_provider_data(provider):
        raise HTTPException(status_code=404, detail=f"No connected '{provider}' account")
    accounts = store.list_provider_accounts()
    return {
        "connected": any(a["status"] == "connected" for a in accounts),
        "providers": accounts,
    }
```

- [ ] **Step 4: Run the disconnect tests and watch them pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -k disconnect -q`

Expected:
```
...                                                                      [100%]
3 passed in 0.XXs
```

- [ ] **Step 5: Run the full OAuth file then the whole suite**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_oauth.py -q`
Expected: all OAuth router tests pass (connect 3 + status 2 + callback 3 + disconnect 3 = 11):
```
11 passed in 0.XXs
```

Then run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`
Expected: everything green; report the total pass count.

- [ ] **Step 6: Commit**

Run:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add backend/app/routers/fitness.py backend/tests/test_fitness_oauth.py && git commit -m "feat(fitness): POST /api/fitness/disconnect/{provider}

Best-effort provider revoke (failures logged, never block), then
delete_provider_data removes the account + synced rows while keeping
manual workouts; returns the refreshed FitnessStatus. 404 when no
account exists.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit on `m4-whoop-fitness`. This completes the OAuth-endpoints phase; the read/write endpoints (/today, /workouts, /week, /sync) are a later phase.


## Phase: Read/write API + schemas + assistant tools

### Task 23: Fitness read/write Pydantic schemas (schemas.py)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_schemas.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py (append after FoodHit, ~line 376)`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_schemas.py`

**Interfaces:**
- Consumes: the OAuth-phase schemas already in schemas.py from Task 19 (ProviderStatus, FitnessStatus, ConnectUrl). Otherwise pure Pydantic models. Mirrors existing Tint/Day/Literal conventions in schemas.py.
- Produces: schemas.FitnessSource, schemas.FitnessVital, schemas.FitnessToday, schemas.WorkoutOut, schemas.WorkoutCreate, schemas.FitnessWeekDay, schemas.FitnessWeek — the read/write response/request models the fitness router and its tests import. (ProviderStatus/FitnessStatus/ConnectUrl are NOT (re)defined here; they were defined in Task 19.)

- [ ] **Step 1: Write the failing test for the fitness schemas**

These are plain Pydantic models, so the test validates field names, types, defaults, and the `date` alias quirk (a field named `date` annotated with `Day`, matching MealOut/NutritionWeekDay). The oauth phase may already define `ProviderStatus`/`ConnectUrl`; this task owns `FitnessStatus`/`FitnessToday`/`WorkoutOut`/`WorkoutCreate`/`FitnessWeek` and the helper models they need.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_schemas.py`:

```python
"""Fitness Pydantic schemas (M4): field names, types, the `date` alias, defaults."""
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    FitnessStatus,
    FitnessToday,
    FitnessVital,
    FitnessWeek,
    FitnessWeekDay,
    ProviderStatus,
    WorkoutCreate,
    WorkoutOut,
)


def test_provider_status_shape():
    ps = ProviderStatus(
        provider="whoop",
        status="connected",
        connected_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        last_sync_at=None,
    )
    assert ps.provider == "whoop"
    assert ps.status == "connected"
    assert ps.provider_user_id is None
    with pytest.raises(ValidationError):
        ProviderStatus(provider="whoop", status="bogus",
                       connected_at=datetime.now(timezone.utc), last_sync_at=None)


def test_fitness_status_wraps_providers():
    fs = FitnessStatus(connected=True, providers=[
        ProviderStatus(provider="whoop", status="needs_reauth",
                       connected_at=datetime.now(timezone.utc), last_sync_at=None),
    ])
    assert fs.connected is True
    assert fs.providers[0].status == "needs_reauth"
    empty = FitnessStatus(connected=False, providers=[])
    assert empty.providers == []


def test_fitness_vital_and_today():
    vital = FitnessVital(key="hrv", label="HRV", value=58.0, unit="ms",
                         delta=6.0, icon="activity", tint="sky")
    today = FitnessToday(
        date=date(2026, 6, 30), source="whoop", recovery_pct=82,
        day_strain=8.1, sleep_quality_pct=74, vitals=[vital], has_data=True,
    )
    assert today.date == date(2026, 6, 30)
    assert today.source == "whoop"
    assert today.vitals[0].delta == 6.0
    # No data: every metric nullable, has_data False, source None.
    blank = FitnessToday(date=date(2026, 6, 30), source=None, recovery_pct=None,
                         day_strain=None, sleep_quality_pct=None, vitals=[],
                         has_data=False)
    assert blank.has_data is False and blank.source is None


def test_workout_out_shape_includes_derived_display():
    w = WorkoutOut(
        id=1, source="whoop", name="Run", sport="running",
        started_at=datetime(2026, 6, 30, 6, 10, tzinfo=timezone.utc),
        duration_min=42, strain=11.3, calories=520, avg_hr=148, max_hr=171,
        when="Today · 6:10am", icon="activity", tint="sky",
    )
    assert w.source == "whoop"
    assert w.when == "Today · 6:10am"
    with pytest.raises(ValidationError):
        WorkoutOut(id=1, source="strava", name="x", sport=None,
                   started_at=datetime.now(timezone.utc), duration_min=0,
                   strain=None, calories=None, avg_hr=None, max_hr=None,
                   when="", icon="activity", tint="sky")


def test_workout_create_validates_and_defaults():
    wc = WorkoutCreate(name="Lift", started_at=datetime.now(timezone.utc),
                       duration_min=30)
    assert wc.sport is None and wc.strain is None and wc.calories is None
    # name required, non-empty; negatives rejected.
    with pytest.raises(ValidationError):
        WorkoutCreate(name="", started_at=datetime.now(timezone.utc), duration_min=30)
    with pytest.raises(ValidationError):
        WorkoutCreate(name="Lift", started_at=datetime.now(timezone.utc),
                      duration_min=-1)
    with pytest.raises(ValidationError):
        WorkoutCreate(name="Lift", started_at=datetime.now(timezone.utc),
                      duration_min=30, avg_hr=-5)


def test_fitness_week_shape():
    days = [FitnessWeekDay(date=date(2026, 6, 29), dow="M", strain=8.0,
                           frac=round(8.0 / 21, 2))]
    week = FitnessWeek(days=days, avg_strain=8.0, peak_day=date(2026, 6, 29))
    assert week.days[0].dow == "M"
    assert week.days[0].frac == round(8.0 / 21, 2)
    assert week.peak_day == date(2026, 6, 29)
    assert FitnessWeek(days=[], avg_strain=0.0, peak_day=None).peak_day is None
```

- [ ] **Step 2: Run the test and watch it fail (ImportError)**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_schemas.py -q`

Expected: collection fails with `ImportError: cannot import name 'FitnessStatus' from 'app.schemas'` (the names don't exist yet).

- [ ] **Step 3: Append the fitness schemas to schemas.py**

Append after the `FoodHit` class (end of file, ~line 376) in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/schemas.py`. These mirror the existing conventions exactly: `Tint` literal for tints, `Day` alias for the `date` field (the deferred-annotation quirk documented at the top of the file), `Field` constraints like the nutrition models, derived display fields read-only.

**`ProviderStatus`, `FitnessStatus`, and `ConnectUrl` are already defined** — the OAuth phase added them at the head of Task 19 (so the OAuth router could import them). Do NOT redefine them here; appending a second class with the same name would shadow the first. This task adds only the read/write schemas (`FitnessSource`, `FitnessVital`, `FitnessToday`, `WorkoutOut`, `WorkoutCreate`, `FitnessWeekDay`, `FitnessWeek`). Before appending, confirm the three OAuth schemas exist:

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -c "from app.schemas import ConnectUrl, FitnessStatus, ProviderStatus; print('oauth schemas present')"`

Expected: prints `oauth schemas present` (they came from Task 19). If this fails, the OAuth phase was not completed — finish it first; do NOT define these three here.

```python


# ---- Fitness read/write schemas (M4) ----------------------------------------
# ProviderStatus / FitnessStatus / ConnectUrl already defined in Task 19.
FitnessSource = Literal["whoop", "oura", "apple_health", "manual"]


class FitnessVital(BaseModel):
    key: str  # 'hrv' | 'resting_hr' | 'respiratory_rate' | 'sleep_hours'
    label: str
    value: float | None
    unit: str
    delta: float | None  # vs prior day; None if no prior
    icon: str
    tint: Tint


class FitnessToday(BaseModel):
    date: Day
    source: str | None  # which provider produced today's snapshot; None if no data
    recovery_pct: int | None
    day_strain: float | None
    sleep_quality_pct: int | None
    vitals: List[FitnessVital]
    has_data: bool


class WorkoutOut(BaseModel):
    id: int
    source: FitnessSource
    name: str
    sport: str | None
    started_at: datetime
    duration_min: int
    strain: float | None
    calories: int | None
    avg_hr: int | None
    max_hr: int | None
    when: str  # derived display, e.g. "Today · 6:10am" (mirrors event_when style)
    icon: str  # derived from sport
    tint: Tint  # derived from sport


class WorkoutCreate(BaseModel):
    name: str = Field(min_length=1)
    sport: str | None = None
    started_at: datetime
    duration_min: int = Field(ge=0)
    strain: float | None = Field(default=None, ge=0)
    calories: int | None = Field(default=None, ge=0)
    avg_hr: int | None = Field(default=None, ge=0)
    max_hr: int | None = Field(default=None, ge=0)


class FitnessWeekDay(BaseModel):
    date: Day
    dow: str  # "M" / "T" / ... Mon-first
    strain: float | None
    frac: float  # day_strain / 21, capped at 1.0


class FitnessWeek(BaseModel):
    days: List[FitnessWeekDay]
    avg_strain: float
    peak_day: Day | None
```

Note: `ConnectUrl` (§F) is owned by the oauth phase, not added here.

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_schemas.py -q`

Expected: `6 passed` (test_provider_status_shape, test_fitness_status_wraps_providers, test_fitness_vital_and_today, test_workout_out_shape_includes_derived_display, test_workout_create_validates_and_defaults, test_fitness_week_shape).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass (new schemas are additive; the prior suite count plus 6). Report the pass count.

Then commit on the current branch (`m4-whoop-fitness`):

```
git add backend/app/schemas.py backend/tests/test_fitness_schemas.py
git commit -m "M4: fitness read/write Pydantic schemas (FitnessStatus/Today/Week, WorkoutOut/Create)"
```


### Task 24: Fitness read/write API routes (routers/fitness.py)

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_api.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py (append read/write routes after the oauth routes)`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_api.py`

**Interfaces:**
- Consumes: schemas.FitnessToday, schemas.WorkoutOut, schemas.WorkoutCreate, schemas.FitnessWeek (this phase, task 1); store.fitness_today(day), store.list_workouts(limit), store.create_workout(data), store.delete_workout(workout_id), store.fitness_week(end_day) (data phase); fitness_sync.tick() and providers.pull_providers() (sync phase); the `router = APIRouter(prefix="/api/fitness", ...)` object already created in routers/fitness.py (oauth phase).
- Produces: Six routes on the existing fitness `router`: GET /api/fitness/today, GET /api/fitness/workouts, POST /api/fitness/workouts, DELETE /api/fitness/workouts/{id}, GET /api/fitness/week, POST /api/fitness/sync — wired into the app via main.py's existing include_router(fitness.router) (oauth/lifespan phase).

- [ ] **Step 1: Write the failing API test for the read/write routes**

Reads (`/today`, `/workouts`, `/week`) hit the normalized tables only — no provider, no network. The manual POST/DELETE exercise `store.create_workout`/`store.delete_workout`. `/sync` calls `fitness_sync.tick()`; we install a fake sync via its `configure` seam (mirrors `reminders.configure`) so no provider runs. This test file lives alongside the oauth phase's route tests — if the oauth phase already created `test_fitness_api.py`, append these functions to it instead of creating a second file (search first; this body assumes it must be created and notes the merge case).

The `no_external_services` conftest fixture (per §N, done in the sync phase) resets `providers.configure(...)` and `fitness_sync.configure(...)` in teardown. This test installs its own fake `fitness_sync` for the `/sync` case only.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_api.py`:

```python
"""Fitness read/write API (M4): /today, /workouts, /week, manual POST/DELETE, /sync.

Reads never touch a provider — they read the normalized tables the data phase
fills. /sync delegates to fitness_sync.tick() through its configure() seam.
"""
from datetime import date, datetime, timezone

from app import fitness_sync
from app.providers.base import NormalizedSnapshot, NormalizedWorkout
from app.store import store

TODAY = date.today()


def _at(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    """A UTC datetime on `day`."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


class FakeSync:
    """Stands in for the fitness_sync tick via fitness_sync.configure().

    The sync phase's configure() accepts a fake whose .tick(now) returns an int;
    here we just record the call and return a fixed count.
    """

    def __init__(self, count: int = 3):
        self.count = count
        self.calls = 0

    def tick(self, now=None) -> int:
        self.calls += 1
        return self.count


# ---- reads (normalized tables only) ----------------------------------------

def test_today_empty_state(client):
    today = client.get("/api/fitness/today").json()
    assert today["date"] == TODAY.isoformat()
    assert today["has_data"] is False
    assert today["source"] is None
    assert today["recovery_pct"] is None
    assert today["vitals"] == [] or all(v["value"] is None for v in today["vitals"])


def test_today_reads_snapshot_with_derived_delta(client):
    yesterday = date.fromordinal(TODAY.toordinal() - 1)
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=yesterday,
                                             recovery_pct=70, hrv_ms=52.0))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY,
                                             recovery_pct=82, hrv_ms=58.0,
                                             day_strain=8.1, sleep_quality_pct=74))
    today = client.get("/api/fitness/today").json()
    assert today["has_data"] is True
    assert today["source"] == "whoop"
    assert today["recovery_pct"] == 82
    assert today["day_strain"] == 8.1
    hrv = next(v for v in today["vitals"] if v["key"] == "hrv")
    assert hrv["value"] == 58.0
    assert hrv["delta"] == 6.0  # 58 - 52, derived on read


def test_today_accepts_date_query(client):
    d = date.fromordinal(TODAY.toordinal() - 5)
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=d, recovery_pct=60))
    today = client.get("/api/fitness/today", params={"date": d.isoformat()}).json()
    assert today["date"] == d.isoformat()
    assert today["recovery_pct"] == 60


def test_workouts_returns_synced_and_manual_newest_first(client):
    store.upsert_workout(NormalizedWorkout(source="whoop", source_id="w-1",
                                           name="Morning Run", sport="running",
                                           started_at=_at(6, 10), duration_min=42,
                                           strain=11.3, calories=520))
    store.create_workout({"name": "Evening Lift", "sport": "strength",
                          "started_at": _at(18, 0), "duration_min": 30})
    rows = client.get("/api/fitness/workouts").json()
    assert [r["name"] for r in rows] == ["Evening Lift", "Morning Run"]  # newest first
    assert {r["source"] for r in rows} == {"manual", "whoop"}
    run = next(r for r in rows if r["name"] == "Morning Run")
    assert run["calories"] == 520
    assert isinstance(run["when"], str) and run["when"]
    assert isinstance(run["icon"], str) and isinstance(run["tint"], str)


def test_workouts_limit_query(client):
    for i in range(3):
        store.create_workout({"name": f"W{i}", "started_at": _at(7 + i),
                              "duration_min": 20})
    rows = client.get("/api/fitness/workouts", params={"limit": 2}).json()
    assert len(rows) == 2


def test_week_strain_trend_shape(client):
    week = client.get("/api/fitness/week").json()
    assert len(week["days"]) == 7
    assert [d["dow"] for d in week["days"]] == ["M", "T", "W", "T", "F", "S", "S"]
    assert "avg_strain" in week and "peak_day" in week


# ---- manual write ----------------------------------------------------------

def test_post_manual_workout_creates_source_manual_row(client):
    res = client.post("/api/fitness/workouts", json={
        "name": "Trail Run", "sport": "running",
        "started_at": _at(6, 30).isoformat(), "duration_min": 55,
        "strain": 12.0, "calories": 600,
    })
    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "manual"
    assert body["name"] == "Trail Run"
    assert body["calories"] == 600
    assert body["id"] in {w["id"] for w in client.get("/api/fitness/workouts").json()}


def test_post_manual_workout_rejects_blank_name(client):
    res = client.post("/api/fitness/workouts", json={
        "name": "", "started_at": _at(6).isoformat(), "duration_min": 30})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_delete_workout(client):
    created = client.post("/api/fitness/workouts", json={
        "name": "Doomed", "started_at": _at(9).isoformat(), "duration_min": 10}).json()
    assert client.delete(f"/api/fitness/workouts/{created['id']}").status_code == 204
    assert client.delete(f"/api/fitness/workouts/{created['id']}").status_code == 404
    assert created["id"] not in {w["id"] for w in client.get("/api/fitness/workouts").json()}


# ---- sync trigger ----------------------------------------------------------

def test_sync_triggers_tick_and_reports_count(client):
    fake = FakeSync(count=4)
    fitness_sync.configure(fake)
    res = client.post("/api/fitness/sync")
    assert res.status_code == 200
    body = res.json()
    assert body["synced"] == 4
    assert isinstance(body["providers"], list)
    assert fake.calls == 1
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_api.py -q`

Expected: failures — the read/write routes aren't on the router yet, so GET `/api/fitness/today` returns 404 (the assertion on `today["date"]` raises KeyError on the error envelope). The oauth phase already created the `router` object and `/status` etc., but not these six routes.

- [ ] **Step 3: Append the read/write routes to routers/fitness.py**

Append after the existing oauth routes in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/fitness.py`. Use the same router object the oauth phase created (`router = APIRouter(prefix="/api/fitness", tags=["fitness"])`). Match the nutrition router's style: `date_: date | None = Query(default=None, alias="date")` for date params, `Response(status_code=204)` for deletes, `HTTPException(404, ...)` for missing rows, `status_code=201` for the manual create, `response_model=...` on every route.

Ensure these imports are present at the top of the file (add any missing to the existing import block — the oauth phase already imports `APIRouter`, `HTTPException`, `store`, and some schemas):

```python
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
```

Then append the routes (the `router` object already exists from the oauth phase — do NOT redeclare it):

```python


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
    """Run one sync pass now (post-connect, manual test, assistant tool).

    Delegates to fitness_sync.tick(); reads never depend on it, so a failing
    tick just returns 0. `providers` lists the pull-providers that were polled.
    """
    count = fitness_sync.tick()
    return {"synced": count, "providers": [p.name for p in pull_providers()]}
```

Notes:
- `fitness_sync.tick()` is the frozen name (contract §G: POST /sync "triggers `fitness_sync.tick()`"; §H defines only `configure`/`tick`/`run_loop`). The `configure(fake)` seam lets tests swap in a `FakeSync` whose `.tick()` returns the count.
- `pull_providers()` (contract §C) returns the registered pull-providers; with no provider configured in a plain test it returns `[]`, so `providers` is `[]` — matching the test's `isinstance(..., list)` assertion.

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_api.py -q`

Expected: `10 passed` (test_today_empty_state, test_today_reads_snapshot_with_derived_delta, test_today_accepts_date_query, test_workouts_returns_synced_and_manual_newest_first, test_workouts_limit_query, test_week_strain_trend_shape, test_post_manual_workout_creates_source_manual_row, test_post_manual_workout_rejects_blank_name, test_delete_workout, test_sync_triggers_tick_and_reports_count).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass. Report the pass count.

Then commit on `m4-whoop-fitness`:

```
git add backend/app/routers/fitness.py backend/tests/test_fitness_api.py
git commit -m "M4: fitness read/write API routes (/today, /workouts, /week, /sync)"
```


### Task 25: Assistant fitness tools (tools.py) replace seed reader

**Files:**
- Create: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_tools.py`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`
- Test: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_tools.py`

**Interfaces:**
- Consumes: store.fitness_today(day), store.list_workouts(limit), store.fitness_week(end_day), store.list_provider_accounts(), store.create_workout(data) (data phase); fitness_sync.tick() (sync phase); existing tools.py helpers _parse_dt, _parse_date, _clamp, execute, the action-card convention.
- Produces: Six real tools in tools.TOOLS / tools.DEFINITIONS with frozen names: get_fitness_today, get_workouts, get_fitness_week, get_fitness_status, log_workout, sync_fitness; helper _fitness_action; removal of the FITNESS_TODAY seed reader.

- [ ] **Step 1: Write the failing test for the fitness tools**

Drive the executors through the chat loop (mirroring test_assistant_domains.py: FakeLLM + tool_turn/tool_block + the `chat` helper), and also call `tools.execute` directly for the read tools to assert their JSON shape. Write tools must return an action card with `screen == "fitness"`; tool errors must come back as `{"error": ...}`.

Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_fitness_tools.py`:

```python
"""Assistant fitness tools (M4): reads over normalized tables, manual log_workout,
sync_fitness — replacing the old seed get_fitness_today reader."""
import json
from datetime import date, datetime, timezone

from app import fitness_sync, llm, tools
from app.providers.base import NormalizedSnapshot, NormalizedWorkout
from app.store import store

from .fakes import FakeLLM, text_turn, tool_block, tool_turn

TODAY = date.today()


def chat(client, message: str) -> dict:
    res = client.post("/api/assistant/chat", json={"message": message})
    assert res.status_code == 200, res.text
    return res.json()


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute, tzinfo=timezone.utc)


class FakeSync:
    def __init__(self, count=2):
        self.count = count
        self.calls = 0

    def tick(self, now=None) -> int:
        self.calls += 1
        return self.count


def test_seed_fitness_reader_is_gone():
    # The old sample reader and its seed import must be removed.
    assert "FITNESS_TODAY" not in tools.__dict__
    names = {t["name"] for t in tools.TOOLS}
    assert {"get_fitness_today", "get_workouts", "get_fitness_week",
            "get_fitness_status", "log_workout", "sync_fitness"} <= names


def test_get_fitness_today_reads_real_snapshot(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY,
                                             recovery_pct=82, day_strain=8.1,
                                             hrv_ms=58.0))
    result_json, action = tools.execute("get_fitness_today", {})
    result = json.loads(result_json)
    assert action is None
    assert result["recovery_pct"] == 82
    assert result["has_data"] is True
    assert "SAMPLE" not in result_json


def test_get_workouts_lists_real_rows(client):
    store.upsert_workout(NormalizedWorkout(source="whoop", source_id="w-1",
                                           name="Run", sport="running",
                                           started_at=_at(6, 10), duration_min=42))
    result_json, action = tools.execute("get_workouts", {})
    result = json.loads(result_json)
    assert action is None
    assert [w["name"] for w in result["workouts"]] == ["Run"]


def test_get_fitness_week_and_status(client):
    week_json, _ = tools.execute("get_fitness_week", {})
    assert len(json.loads(week_json)["days"]) == 7
    status_json, _ = tools.execute("get_fitness_status", {})
    status = json.loads(status_json)
    assert "providers" in status


def test_log_workout_tool_creates_manual_row(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("log_workout", {
            "name": "Evening Lift", "sport": "strength",
            "started_at": _at(18, 0).isoformat(), "duration_min": 30,
        })),
        text_turn("Logged your lift."),
    ))
    body = chat(client, "I lifted this evening for half an hour")

    workouts = client.get("/api/fitness/workouts").json()
    assert [w["name"] for w in workouts] == ["Evening Lift"]
    assert workouts[0]["source"] == "manual"
    assert body["actions"][0]["screen"] == "fitness"
    assert body["actions"][0]["title"] == "Workout logged"


def test_sync_fitness_tool_triggers_tick(client):
    fake = FakeSync(count=2)
    fitness_sync.configure(fake)
    llm.configure(FakeLLM(
        tool_turn(tool_block("sync_fitness", {})),
        text_turn("Synced your WHOOP."),
    ))
    body = chat(client, "sync my whoop")
    assert fake.calls == 1
    assert body["actions"][0]["screen"] == "fitness"
    assert body["actions"][0]["title"] == "Fitness synced"
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_tools.py -q`

Expected: failures — `test_seed_fitness_reader_is_gone` fails because `get_workouts`/`get_fitness_week`/`get_fitness_status`/`log_workout`/`sync_fitness` aren't registered yet, and the new executors don't exist (`FITNESS_TODAY` is still imported).

- [ ] **Step 3: Replace the seed reader and add the six fitness tools in tools.py**

Three edits in `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/tools.py`.

**Edit 1 — imports.** Change the seeds import to drop `FITNESS_TODAY`, and add the `fitness_sync` import. Replace:

```python
from . import food_db, memory_engine, recurrence
from .seeds import FINANCE_SUMMARY, FITNESS_TODAY
from .store import store
```

with:

```python
from . import fitness_sync, food_db, memory_engine, recurrence
from .seeds import FINANCE_SUMMARY
from .store import store
```

**Edit 2 — action helper + executors.** Add the `_fitness_action` helper next to the other `_*_action` helpers (after `_nutrition_action`, ~line 88):

```python
def _fitness_action(title: str, meta: str) -> dict:
    return {"icon": "activity", "title": title, "meta": meta,
            "cta": "View fitness", "screen": "fitness"}
```

And add the executors. Place them after `_search_food` (end of the nutrition executors block, ~line 371), before the `_add_reminder` block:

```python
# ---- fitness (real from M4) -------------------------------------------------

def _get_fitness_today(args: dict):
    return store.fitness_today(_parse_date(args.get("date"))), None


def _get_workouts(args: dict):
    rows = store.list_workouts(args.get("limit", 10))
    return {"workouts": [{"id": w["id"], "name": w["name"], "source": w["source"],
                          "sport": w["sport"], "duration_min": w["duration_min"],
                          "strain": w["strain"], "calories": w["calories"],
                          "when": w["when"]} for w in rows]}, None


def _get_fitness_week(args: dict):
    return store.fitness_week(_parse_date(args.get("date"))), None


def _get_fitness_status(args: dict):
    accounts = store.list_provider_accounts()
    return {"connected": any(a["status"] == "connected" for a in accounts),
            "providers": accounts}, None


def _log_workout(args: dict):
    data = {
        "name": args["name"],
        "sport": args.get("sport"),
        "started_at": _parse_dt(args["started_at"]) if args.get("started_at")
        else datetime.now().astimezone(),
        "duration_min": max(0, int(args.get("duration_min") or 0)),
        "strain": args.get("strain"),
        "calories": args.get("calories"),
        "avg_hr": args.get("avg_hr"),
        "max_hr": args.get("max_hr"),
    }
    workout = store.create_workout({k: v for k, v in data.items() if v is not None})
    return {"logged": {"id": workout["id"], "name": workout["name"],
                       "source": workout["source"]}}, _fitness_action(
        "Workout logged", f"{workout['name']} · {workout['duration_min']} min"
    )


def _sync_fitness(args: dict):
    count = fitness_sync.tick()
    return {"synced": count}, _fitness_action(
        "Fitness synced", f"{count} record{'s' if count != 1 else ''} updated"
    )
```

**Edit 3 — the tool registry.** Replace the single seed `get_fitness_today` entry at the end of `TOOLS` (currently the last entry, ~lines 569-572):

```python
    {"name": "get_fitness_today",
     "description": "Read today's recovery/sleep/strain numbers.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(FITNESS_TODAY)},
```

with the six real tools:

```python
    {"name": "get_fitness_today",
     "description": "Read today's recovery/sleep/strain rings and vitals (HRV, resting HR, respiratory rate, sleep). Call for any recovery/readiness/sleep question.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."}},
         "additionalProperties": False},
     "run": _get_fitness_today},
    {"name": "get_workouts",
     "description": "List recent workouts (synced from WHOOP + manually logged), newest first. Call when the user asks about their training or recent sessions.",
     "input_schema": {"type": "object", "properties": {
         "limit": {"type": "integer", "description": "How many to return (default 10)."}},
         "additionalProperties": False},
     "run": _get_workouts},
    {"name": "get_fitness_week",
     "description": "Read the weekly strain trend (7-day, Mon-first). Call when the user asks how their training load looked this week.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD inside the week, default this week."}},
         "additionalProperties": False},
     "run": _get_fitness_week},
    {"name": "get_fitness_status",
     "description": "Check whether a wearable (WHOOP) is connected and when it last synced. Call before suggesting a sync or when the user asks if their device is linked.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_fitness_status},
    {"name": "log_workout",
     "description": "Log a manual workout (one WHOOP didn't capture). Call when the user says they did a session ('I lifted for 30 minutes'). A logged workout auto-completes a habit linked to workouts.",
     "input_schema": {"type": "object", "properties": {
         "name": _STRING,
         "sport": {"type": "string", "description": "e.g. running, cycling, strength."},
         "started_at": {"type": "string", "description": "ISO datetime; defaults to now (user's local time if no offset)."},
         "duration_min": {"type": "integer"},
         "strain": {"type": "number"},
         "calories": {"type": "integer"},
         "avg_hr": {"type": "integer"},
         "max_hr": {"type": "integer"}},
         "required": ["name"], "additionalProperties": False},
     "run": _log_workout},
    {"name": "sync_fitness",
     "description": "Trigger a WHOOP sync now to pull the latest recovery/sleep/strain/workouts. Call when the user asks to refresh or says their latest data is missing.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _sync_fitness},
```

Notes:
- `_parse_date` and `_parse_dt` already exist in tools.py; `datetime` is already imported.
- `get_workouts` compacts the WorkoutOut dicts the same way the calendar/habit tools compact their reads (a subset of keys for the model).
- `_get_fitness_status` returns `store.list_provider_accounts()` rows (safe dicts, no tokens) under `providers`, matching the data-phase contract.
- `_sync_fitness` calls `fitness_sync.tick()` (frozen name); the FakeSync seam intercepts it in tests.

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_fitness_tools.py -q`

Expected: `6 passed` (test_seed_fitness_reader_is_gone, test_get_fitness_today_reads_real_snapshot, test_get_workouts_lists_real_rows, test_get_fitness_week_and_status, test_log_workout_tool_creates_manual_row, test_sync_fitness_tool_triggers_tick).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q`

Expected: all tests pass — including the existing `test_assistant_domains.py` (it doesn't assert the fitness tool surface, so removing the seed reader doesn't break it) and `test_seed.py`. Report the pass count.

Before committing, grep for any stale reference: `grep -rn "FITNESS_TODAY" backend/tests/`. The seed payload `FITNESS_TODAY` stays defined in `seeds.py` (other code/tests may reference it); only its use as a tool reader is removed. If a test asserts the old seed `get_fitness_today` shape, update it to the new real-data shape.

Then commit on `m4-whoop-fitness`:

```
git add backend/app/tools.py backend/tests/test_fitness_tools.py
git commit -m "M4: assistant fitness tools (real reads + log_workout + sync_fitness) replace seed reader"
```


## Phase: Frontend rewrite (FitnessScreen)

### Task 26: Add fitness API methods to api.js

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`

**Interfaces:**
- Consumes: The backend `/api/fitness/*` routes from the API-routes phase (§G of the contract): GET /api/fitness/status, /today, /week, /workouts; POST /api/fitness/workouts, /disconnect/{provider}, /sync; DELETE /api/fitness/workouts/{id}; GET /api/fitness/connect/{provider}.
- Produces: Nine new methods on the exported `api` object, named VERBATIM per §M: `fitnessStatus`, `fitnessToday`, `fitnessWeek`, `fitnessWorkouts`, `fitnessConnect`, `fitnessDisconnect`, `logWorkout`, `deleteWorkout`, `fitnessSync`. The FitnessScreen rewrite (Task 2) calls these.

- [ ] **Step 1: Add the nine fitness methods to the `api` object**

Frontend has no unit-test harness, so this task has no failing-test step — verification is manual at the end of Task 2 (the screen is what exercises these). Add the methods right after the Nutrition block and before the Second-brain block.

In `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`, find this exact line (the last nutrition method, the closing of the nutrition group):

```js
  searchFoods: (q) => request(`/api/nutrition/foods?q=${encodeURIComponent(q)}`),

  // Second-brain memories.
```

Replace it with (inserts the fitness block between nutrition and second-brain — the method bodies are copied VERBATIM from contract §M):

```js
  searchFoods: (q) => request(`/api/nutrition/foods?q=${encodeURIComponent(q)}`),

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

  // Second-brain memories.
```

Note: `request()` already JSON-parses 2xx bodies (and returns `null` on 204, so `deleteWorkout` resolves to `null`), throws `ApiError` on non-2xx, and throws a `TypeError` when the backend is unreachable — the screen's `.catch()` handlers rely on exactly this. No changes to `request()` itself.

- [ ] **Step 2: Confirm the file parses (no separate run — verified by Vite in Task 2)**

There is no lint/test step for the frontend. Sanity-check the edit by eye: the nine new keys are valid object properties (trailing comma after `fitnessSync`), and the `// Second-brain memories.` comment with `listMemories` still follows. The methods become reachable as soon as Vite hot-reloads in Task 2's verification. Do not commit yet — commit happens at the end of Task 2 so the api change and its first consumer land together.


### Task 27: Rewrite FitnessScreen.jsx to live data with all connection states + manual log form

**Files:**
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/FitnessScreen.jsx`
- Modify: `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js`

**Interfaces:**
- Consumes: The nine `api.fitness*`/`api.logWorkout`/`api.deleteWorkout` methods from Task 1. The backend response shapes from the schemas phase (§F): `FitnessStatus {connected, providers:[{provider,status,connected_at,last_sync_at,provider_user_id}]}`; `FitnessToday {date, source, recovery_pct, day_strain, sleep_quality_pct, vitals:[{key,label,value,unit,delta,icon,tint}], has_data}`; `WorkoutOut {id, source, name, sport, started_at, duration_min, strain, calories, avg_hr, max_hr, when, icon, tint}`; `FitnessWeek {days:[{date,dow,strain,frac}], avg_strain, peak_day}`; `ConnectUrl {authorize_url}`. The screen takes NO props (App.jsx renders `<FitnessScreen />` with no args) — it owns its own state, mirroring MemoryScreen's in-component fetch convention.
- Produces: The three missing Lucide icons (`unplug`, `alert-triangle`, `waves`) registered in Icon.jsx so the disconnect button, needs-reauth banner, and swimming workout chip render. A fully live `FitnessScreen` exporting the same `export function FitnessScreen()` signature App.jsx already imports. Renders four connection states (not-connected, connected, needs_reauth, syncing) plus the manual Log-workout form. No new props required of App.jsx.

- [ ] **Step 1: Register the missing Lucide icons in Icon.jsx**

`Icon` returns `null` for an unknown name (only a DEV console warning, no crash) — so any referenced-but-unregistered icon renders blank. The fitness screen and the workout chips reference three names that are NOT yet in the `ICONS` map: `unplug` (the disconnect IconButton), `alert-triangle` (the needs-reauth banner), and `waves` (the swimming workout chip from the store's `_SPORT_CHIP`). All other referenced icons (`activity`, `refresh-cw`, `chart-line`, `trash-2`, `plus`, `sparkles`, `bike`, `dumbbell`, `flower-2`, `footprints`, `moon`, `wind`, `heart`) already exist. Add the three missing ones.

Edit `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/Icon.jsx`.

First, add the three components to the `lucide-react` import (keep it roughly alphabetized to match the file's style). Insert `AlertTriangle` after `AlarmClock` — change:

```js
  Activity,
  AlarmClock,
  AlignLeft,
```
to:
```js
  Activity,
  AlarmClock,
  AlertTriangle,
  AlignLeft,
```

Then insert `Unplug` and `Waves` in the U–W run — change:

```js
  Upload,
  Users,
  Utensils,
  Video,
  Wallet,
  Wifi,
  Wind,
```
to:
```js
  Unplug,
  Upload,
  Users,
  Utensils,
  Video,
  Wallet,
  Waves,
  Wifi,
  Wind,
```

Then add the three matching entries to the `ICONS` map (kebab-case keys). Insert `'alert-triangle'` after `'alarm-clock'` — change:

```js
  activity: Activity,
  'alarm-clock': AlarmClock,
  'align-left': AlignLeft,
```
to:
```js
  activity: Activity,
  'alarm-clock': AlarmClock,
  'alert-triangle': AlertTriangle,
  'align-left': AlignLeft,
```

And insert `unplug` and `waves` in the matching U–W run — change:

```js
  upload: Upload,
  users: Users,
  utensils: Utensils,
  video: Video,
  wallet: Wallet,
  wifi: Wifi,
  wind: Wind,
```
to:
```js
  unplug: Unplug,
  upload: Upload,
  users: Users,
  utensils: Utensils,
  video: Video,
  wallet: Wallet,
  waves: Waves,
  wifi: Wifi,
  wind: Wind,
```

These three names (`unplug`, `alert-triangle`, `waves`) are all valid `lucide-react` exports. After this edit, every icon the fitness surface and `_SPORT_CHIP` reference resolves to a real glyph.

- [ ] **Step 2: Replace the whole file with the live, state-driven screen**

Frontend has no test harness — write the real component, then verify manually in the next steps. Overwrite `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/FitnessScreen.jsx` entirely with the following. It keeps every existing UI component (`Card`, `Badge`, `ProgressRing`, `IconButton`, `Button`, `Icon`) and reuses the existing `kit-*` CSS classes the old screen used (`kit-rings`, `kit-ring-cell`, `kit-statgrid`, `kit-statline`, `kit-row`, `kit-workout__ico`, `kit-chart`, `kit-insight`), so no CSS changes are needed. The in-component fetch (api object + `React.useEffect` + `alive` guard) mirrors `MemoryScreen.jsx`; the form + `submit → write → refresh` mirrors `NutritionScreen.jsx` + `useNutrition`.

```jsx
/* Scuffed OS — Fitness & workout log (live, synced with WHOOP).
   Owns its own state (App.jsx renders <FitnessScreen /> with no props),
   mirroring MemoryScreen's in-component fetch convention. /status drives which
   connection state renders; /today, /workouts, /week feed the connected view.
   Reads come straight from the normalized tables server-side, so the screen
   works while a sync is mid-flight or WHOOP is down — it just shows what's
   landed so far. Tokens never reach the client. */
import React from 'react'
import { Card, Badge, ProgressRing, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const EMPTY_FORM = { name: '', sport: '', duration_min: '', strain: '', calories: '', avg_hr: '' }

const localIso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/* Green for a positive delta, clay for negative — matches the warm palette.
   Resting HR is the one vital where lower is better, so its sign flips. */
function deltaColor(key, delta) {
  if (delta == null || delta === 0) return 'var(--text-faint)'
  const better = key === 'resting_hr' ? delta < 0 : delta > 0
  return better ? 'var(--green-600)' : 'var(--clay-600)'
}
function fmtDelta(delta) {
  if (delta == null) return ''
  const r = Math.round(delta * 10) / 10
  return (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r)
}

export function FitnessScreen() {
  const [status, setStatus] = React.useState(null)   // null = /status not answered yet
  const [today, setToday] = React.useState(null)
  const [workouts, setWorkouts] = React.useState([])
  const [week, setWeek] = React.useState(null)
  const [logging, setLogging] = React.useState(false)
  const [form, setForm] = React.useState(EMPTY_FORM)
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const refresh = React.useCallback(() => {
    api.fitnessStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.fitnessToday().then((t) => { if (t) setToday(t) }).catch(() => {})
    api.fitnessWorkouts().then((w) => { if (Array.isArray(w)) setWorkouts(w) }).catch(() => {})
    api.fitnessWeek().then((w) => { if (w) setWeek(w) }).catch(() => {})
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const whoop = (status?.providers || []).find((p) => p.provider === 'whoop') || null
  const connected = !!status?.connected
  const needsReauth = whoop?.status === 'needs_reauth'
  // Connected + an account exists, but no day data has landed yet → first sync
  // is still running. has_data===false with a connected account = “Syncing…”.
  const syncing = connected && !needsReauth && today != null && today.has_data === false && !whoop?.last_sync_at

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
  const sync = () => { api.fitnessSync().then(() => refresh()).catch(() => {}) }

  const submitWorkout = () => {
    if (!form.name.trim()) return
    // duration_min/strain/calories/avg_hr are numeric server-side; an empty
    // string would 422 and the .catch would silently drop the workout.
    const payload = {
      name: form.name.trim(),
      started_at: new Date().toISOString(),
      duration_min: Math.round(+form.duration_min) || 0,
    }
    if (form.sport.trim()) payload.sport = form.sport.trim()
    if (form.strain !== '') payload.strain = +form.strain
    if (form.calories !== '') payload.calories = Math.round(+form.calories) || 0
    if (form.avg_hr !== '') payload.avg_hr = Math.round(+form.avg_hr) || 0
    api.logWorkout(payload).then(() => refresh()).catch(() => {})
    setForm(EMPTY_FORM)
    setLogging(false)
  }
  const onFormKey = (e) => {
    if (e.key === 'Enter') submitWorkout()
    else if (e.key === 'Escape') { setForm(EMPTY_FORM); setLogging(false) }
  }
  const removeWorkout = (id) => {
    setWorkouts((ws) => ws.filter((w) => w.id !== id))
    api.deleteWorkout(id).then(() => refresh()).catch(() => {})
  }

  const inputStyle = {
    padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
    border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
    color: 'var(--text-strong)',
  }

  // —— not connected: single CTA card ——
  if (status && !connected && !needsReauth) {
    return (
      <Card variant="flat" style={{ textAlign: 'center', padding: '56px 24px' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="activity" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect WHOOP</h3>
        <p className="kit-muted" style={{ maxWidth: 360, margin: '0 auto 18px' }}>Sync recovery, sleep, strain and workouts into Scuffed OS. Your tokens stay server-side and never reach this screen.</p>
        <Button variant="primary" iconLeft={<Icon name="activity" />} onClick={connect}>Connect WHOOP</Button>
      </Card>
    )
  }

  const recovered = (today?.recovery_pct ?? 0) >= 67
  const eyebrow = whoop?.last_sync_at
    ? `Synced with WHOOP · ${new Date(whoop.last_sync_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : 'Connected with WHOOP'
  const todayIso = localIso(new Date())
  const weekDays = week?.days || Array.from({ length: 7 }, () => ({ date: '', dow: '', strain: 0, frac: 0 }))

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {needsReauth && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">WHOOP needs to be reconnected</p>
            <p className="kit-muted">Your authorization expired or was revoked. Reconnect to resume syncing.</p>
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
          <p className="kit-muted" style={{ maxWidth: 360, margin: '0 auto 18px' }}>Pulling your recovery, sleep and workouts from WHOOP. This usually takes a moment — hang tight.</p>
          <Button variant="secondary" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Check again</Button>
        </Card>
      )}

      {!syncing && (
        <div className="kit-grid" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
          <Card eyebrow={eyebrow} title="Today"
            action={
              <div className="kit-inline" style={{ gap: 8 }}>
                {today?.has_data && <Badge color={recovered ? 'green' : 'honey'} dot>{recovered ? 'Recovered' : 'Take it easy'}</Badge>}
                <IconButton label="Sync now" size="sm" onClick={sync}><Icon name="refresh-cw" /></IconButton>
                <IconButton label="Disconnect WHOOP" size="sm" onClick={disconnect}><Icon name="unplug" /></IconButton>
              </div>
            }>
            {today?.has_data ? (
              <div className="kit-rings" style={{ justifyContent: 'space-around', marginTop: 6 }}>
                <div className="kit-ring-cell"><ProgressRing value={today.recovery_pct ?? 0} max={100} size={108} thickness={12} color="green" label={`${today.recovery_pct ?? 0}%`} sublabel="recovery" /><span className="kit-ring-cell__lab">Recovery</span></div>
                <div className="kit-ring-cell"><ProgressRing value={today.day_strain ?? 0} max={21} size={108} thickness={12} color="sky" label={`${today.day_strain ?? 0}`} sublabel="of 21" /><span className="kit-ring-cell__lab">Day strain</span></div>
                <div className="kit-ring-cell"><ProgressRing value={today.sleep_quality_pct ?? 0} max={100} size={108} thickness={12} color="plum" label={`${today.sleep_quality_pct ?? 0}%`} sublabel="quality" /><span className="kit-ring-cell__lab">Sleep</span></div>
              </div>
            ) : (
              <p className="kit-muted" style={{ marginTop: 6 }}>No data for today yet — it’ll appear after the next sync.</p>
            )}
          </Card>
          <Card title="Vitals" action={<IconButton label="History" size="sm"><Icon name="chart-line" /></IconButton>}>
            <div className="kit-statgrid" style={{ marginTop: 4 }}>
              {(today?.vitals || []).map((v) => (
                <div className="kit-statline" key={v.key}>
                  <span className="kit-statline__ico" style={{ background: `var(--${v.tint}-100)`, color: `var(--${v.tint}-600)` }}><Icon name={v.icon} /></span>
                  <div>
                    <div className="kit-statline__lab">{v.label}</div>
                    <div className="kit-statline__val">{v.value ?? '—'}<span style={{ fontSize: 11, color: 'var(--text-faint)' }}> {v.unit}</span>
                      {v.delta != null && <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, color: deltaColor(v.key, v.delta), marginLeft: 6 }}>{fmtDelta(v.delta)}</span>}
                    </div>
                  </div>
                </div>
              ))}
              {(!today?.vitals || today.vitals.length === 0) && <p className="kit-muted">No vitals yet.</p>}
            </div>
          </Card>
        </div>
      )}

      <div className="kit-grid" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <Card title="Workouts" action={<Button variant="soft" size="sm" iconLeft={<Icon name="plus" />} onClick={() => setLogging((v) => !v)}>Log workout</Button>}>
          {logging && (
            <div className="kit-stack" style={{ gap: 8, marginBottom: 12 }}>
              <div className="kit-addrow" style={{ marginTop: 0 }}>
                <Icon name="activity" />
                <input autoFocus placeholder="What did you do?" value={form.name} onChange={setField('name')} onKeyDown={onFormKey} />
              </div>
              <div className="kit-inline" style={{ gap: 8, flexWrap: 'wrap' }}>
                <input placeholder="sport" value={form.sport} onChange={setField('sport')} onKeyDown={onFormKey} style={inputStyle} />
                <input type="number" placeholder="min" value={form.duration_min} onChange={setField('duration_min')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 80 }} />
                <input type="number" placeholder="strain" value={form.strain} onChange={setField('strain')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 90 }} />
                <input type="number" placeholder="cal" value={form.calories} onChange={setField('calories')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 80 }} />
                <input type="number" placeholder="avg bpm" value={form.avg_hr} onChange={setField('avg_hr')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 90 }} />
                <Button variant="soft" size="sm" onClick={submitWorkout}>Add</Button>
              </div>
            </div>
          )}
          {workouts.map((w) => (
            <div className="kit-row" key={w.id}>
              <span className="kit-workout__ico" style={{ background: `var(--${w.tint}-100)`, color: `var(--${w.tint}-600)` }}><Icon name={w.icon} /></span>
              <div className="kit-row__main">
                <p className="kit-row__title">{w.name}{w.source === 'manual' && <span className="kit-muted" style={{ fontWeight: 400 }}> · manual</span>}</p>
                <p className="kit-row__sub">{[w.when, w.duration_min ? `${w.duration_min} min` : null, w.calories != null ? `${w.calories} cal` : null, w.avg_hr != null ? `${w.avg_hr} bpm` : null].filter(Boolean).join(' · ')}</p>
              </div>
              {w.strain != null && <Badge color="sky">{w.strain}</Badge>}
              <IconButton label="Delete" variant="ghost" size="sm" onClick={() => removeWorkout(w.id)}><Icon name="trash-2" /></IconButton>
            </div>
          ))}
          {workouts.length === 0 && !logging && <p className="kit-muted">No workouts logged yet.</p>}
        </Card>
        <Card title="Weekly strain" variant="sunken" action={<span className="kit-muted">avg {week?.avg_strain ?? 0}</span>}>
          <div className="kit-chart">
            {weekDays.map((c, i) => (
              <div className="kit-chart__col" key={i}>
                <div className={'kit-chart__bar' + (c.date && c.date === todayIso ? ' kit-chart__bar--hi' : '')} style={{ height: (Math.max(0, Math.min(1, c.frac || 0)) * 100) + '%' }} />
                <span className="kit-chart__lab">{c.dow}</span>
              </div>
            ))}
          </div>
          <div className="kit-insight" style={{ marginTop: 14 }}>
            <div className="kit-insight__icon"><Icon name="sparkles" /></div>
            <p>{recovered
              ? <>Recovery is high — a good day for a <strong>hard session</strong>. Want me to schedule one?</>
              : <>Recovery is on the lower side — consider an <strong>easy day</strong>.</>}</p>
          </div>
        </Card>
      </div>
    </div>
  )
}
```

Key design notes baked into the code, all matched to existing conventions:
- **No props** — App.jsx already renders `<FitnessScreen />` (App.jsx line 118), so the rewrite must not require props. It self-fetches like `MemoryScreen`.
- **`status === null`** (before `/status` answers) renders the connected layout skeleton with empty cards rather than flashing the not-connected CTA — the not-connected branch only fires once `status` is truthy AND `connected` is false. This avoids a CTA flash on every load, the same way `MemoryScreen` keeps sample data until the fetch lands.
- **Vitals icon/tint/label/unit come from the server** (`v.icon`, `v.tint`, `v.label`, `v.unit` per the `FitnessVital` schema) — no client-side sport→icon map, matching the contract's derive-on-read rule. Same for workouts (`w.icon`, `w.tint`, `w.when` from `WorkoutOut`).
- **All four `.catch(() => {})` handlers** keep the screen working when the backend is down (TypeError) or a sync is mid-flight — identical to `useNutrition`/`useHabits`.

- [ ] **Step 3: Start the backend and confirm /status is reachable**

Start the FastAPI backend (per README “Run it”). From a terminal:

Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate; alembic upgrade head; uvicorn app.main:app --port 8000
```
Expected: uvicorn logs `Uvicorn running on http://127.0.0.1:8000`. In a second terminal confirm the new route answers:

Run:
```bash
curl -s http://localhost:8000/api/fitness/status
```
Expected: a JSON object `{"connected": false, "providers": []}` (no WHOOP connected in a fresh DB). If you get a 404, the API-routes phase router isn't wired in `main.py` — stop and fix that phase first; this screen depends on it.

- [ ] **Step 4: Start Vite and verify the NOT-CONNECTED state**

Run (second terminal):
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm install && npm run dev
```
Expected: Vite prints `Local: http://localhost:5173/`.

Open http://localhost:5173, click **Fitness** in the sidebar. Observe:
- A single centered card: an activity icon, heading **“Connect WHOOP”**, the explanatory paragraph, and a primary **“Connect WHOOP”** button.
- No rings, no vitals, no workout rows (because `/status` returned `connected:false`).
- No console errors in the browser devtools Network tab beyond the expected 200s for `/api/fitness/status`, `/today`, `/workouts`, `/week`.

Click **Connect WHOOP**. Observe the Network tab fire `GET /api/fitness/connect/whoop`. With real WHOOP creds unset, the backend still returns a `ConnectUrl` (an authorize URL built from empty `client_id`); the browser will attempt `window.location = authorize_url`. That redirect leaving the SPA is the correct behavior to observe — you don't need to complete the WHOOP login. (To re-test other states without a real WHOOP app, use the seeding step below.)

- [ ] **Step 5: Seed a connected provider + data and verify the CONNECTED state**

To exercise the connected view without a live WHOOP OAuth round-trip, insert a fake connected account plus one snapshot and one workout directly via the store seam the backend exposes. From the backend venv:

Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate
python - <<'PY'
from datetime import datetime, timezone, date
from app.store import Store
from app.providers.base import Tokens, NormalizedSnapshot, NormalizedWorkout
s = Store()
s.upsert_provider_account('whoop', Tokens(access_token='x', refresh_token='y', expires_at=datetime(2030,1,1,tzinfo=timezone.utc), scopes='read:recovery', provider_user_id='u1'))
s.set_provider_synced('whoop', datetime.now(timezone.utc))
s.upsert_snapshot(NormalizedSnapshot(source='whoop', day=date.today(), recovery_pct=82, day_strain=14.2, sleep_quality_pct=91, hrv_ms=68.0, resting_hr=52, respiratory_rate=14.2, sleep_hours=7.6))
s.upsert_workout(NormalizedWorkout(source='whoop', source_id='w1', name='Morning run', sport='running', started_at=datetime.now(timezone.utc), duration_min=32, strain=9.4, calories=318, avg_hr=148, max_hr=171))
print('seeded')
PY
```
Expected: prints `seeded`.

Back in the browser, navigate away from Fitness and back (or refresh). Observe the **connected** state:
- Eyebrow on the Today card reads **“Synced with WHOOP · <time>”** (from `last_sync_at`).
- A green **“Recovered”** badge (recovery 82 ≥ 67), plus a **Sync now** (refresh) icon and a **Disconnect** (unplug) icon in the header action.
- Three rings: Recovery 82%, Day strain 14.2 / 21, Sleep 91%.
- Vitals card lists HRV / Resting HR / Respiratory / Sleep with their units and any delta colored green (or clay for a worse delta). With only one day seeded, deltas are absent (no prior day) — that's correct.
- Workouts card shows **“Morning run”** with `· 32 min · 318 cal · 148 bpm`, a sky strain Badge `9.4`, and a trash icon.
- Weekly strain chart renders bars; today's bar is highlighted.

Click **Sync now** — observe `POST /api/fitness/sync` in the Network tab and the four reads re-fire.

- [ ] **Step 6: Verify the manual LOG-WORKOUT form writes and refreshes**

On the connected Fitness screen, click **Log workout** in the Workouts card header. Observe an inline form appear with: a name input (autofocused), and a row of `sport`, `min`, `strain`, `cal`, `avg bpm` number inputs plus an **Add** button.

Type `Evening yoga`, sport `yoga`, min `25`, strain `4.8`, then press **Enter** (or click **Add**). Observe:
- Network tab fires `POST /api/fitness/workouts` (201) followed by the four refresh reads.
- A new row **“Evening yoga · manual”** appears in the Workouts list with `25 min` and a sky `4.8` Badge. The `· manual` suffix distinguishes it from synced rows (per the contract: manual + synced coexist).
- The form closes and clears.

Press **Escape** while the form is open in a fresh attempt — confirm it clears and closes without posting.

Delete the manual row via its trash icon — observe `DELETE /api/fitness/workouts/{id}` (204) and the row disappears immediately (optimistic), then the list reconciles on refresh.

- [ ] **Step 7: Verify the NEEDS_REAUTH and SYNCING states**

Flip the seeded account to `needs_reauth` to see the reconnect banner:

Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate
python -c "from app.store import Store; Store().set_provider_status('whoop','needs_reauth'); print('needs_reauth set')"
```
Expected: prints `needs_reauth set`. Refresh the Fitness screen. Observe a **clay reconnect banner** at the top: alert-triangle icon, “WHOOP needs to be reconnected”, and a **Reconnect** button (which calls the same connect flow). The rings/vitals/workouts below still render from local data (reads never depend on a live WHOOP call).

Now verify the **Syncing…** empty state. Reset to a freshly-connected account with NO data and NO last_sync_at:

Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate
python - <<'PY'
from datetime import datetime, timezone
from app.store import Store
from app.providers.base import Tokens
s = Store()
s.delete_provider_data('whoop')
s.upsert_provider_account('whoop', Tokens(access_token='x', refresh_token='y', expires_at=datetime(2030,1,1,tzinfo=timezone.utc), scopes='', provider_user_id='u1'))
print('connected, no sync yet')
PY
```
Expected: prints `connected, no sync yet`. Refresh the Fitness screen. Because the account is connected, `last_sync_at` is null, and `/today` returns `has_data:false`, observe the centered **“Syncing…”** card (refresh-cw icon, “Pulling your recovery, sleep and workouts…”, a **Check again** button) instead of the rings. Click **Check again** — observe `POST /api/fitness/sync` then the reads re-fire.

Finally, clean up the test rows so the dev DB isn't left with a fake account:
Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate
python -c "from app.store import Store; print('removed' if Store().delete_provider_data('whoop') else 'nothing to remove')"
```
Expected: prints `removed`. Refresh — the screen returns to the not-connected **Connect WHOOP** CTA, confirming the full state cycle works.

- [ ] **Step 8: Run the backend suite, then commit**

This is a frontend-only change, but the global rule requires the suite to be green before completing. Confirm the backend tests still pass (this phase touches no backend code, so the count should match the API-routes/tools phases' green run):

Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate; pytest -q
```
Expected: `N passed` with no failures (report the exact pass count). If anything fails, it's not from this phase — investigate the upstream phase before committing.

Then confirm the frontend still builds (CI runs this on every push):
Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build
```
Expected: `vite build` completes with `✓ built in …` and no errors.

Commit all three files on the current branch:
Run:
```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add frontend/src/lib/Icon.jsx frontend/src/lib/api.js frontend/src/screens/FitnessScreen.jsx && git commit -m "feat(fitness): wire FitnessScreen to live /api/fitness data

Replace the hardcoded Fitness sample with live data: status-driven
connection states (not-connected CTA, connected rings/vitals/workouts/week
with last-sync eyebrow + disconnect, needs_reauth banner, syncing empty
state) and a real manual Log-workout form. Adds the fitness* methods to the
api client and registers the unplug/alert-triangle/waves Lucide icons the
screen and workout chips reference. Reads come from the normalized tables,
so the screen works while sync is mid-flight or WHOOP is down.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: a commit is created on `m4-whoop-fitness` listing 3 files changed.


## Phase: Assistant actions, smoke test, privacy reword, live validation

### Task 28: Assistant fitness actions: persona + tool descriptions for read+act composition

**Files:**
- Create: `backend/tests/test_assistant_fitness.py`
- Modify: `backend/app/assistant.py:22-30`
- Modify: `backend/app/tools.py (the six fitness tool descriptions)`
- Test: `backend/tests/test_assistant_fitness.py`
- Verify (no edit expected): `backend/tests/test_assistant_domains.py`

**Interfaces:**
- Consumes: The six fitness tools added in an earlier phase to app/tools.py (names frozen: get_fitness_today, get_workouts, get_fitness_week, get_fitness_status, log_workout, sync_fitness), each pairing a Claude tool definition with an executor reading/writing the real store. tools.DEFINITIONS is the list of {name,description,input_schema}. assistant._PERSONA is the system-prompt persona string. The store.fitness_today/list_workouts/fitness_week/create_workout methods. The FakeLLM/tool_turn/tool_block/text_turn helpers in tests/fakes.py and the chat() helper pattern.
- Produces: Updated _PERSONA naming fitness as a live, writable-by-composition domain; the get_fitness_today and sync_fitness tool descriptions that steer the model to compose fitness reads with create_event/create_task; test_assistant_fitness.py proving the fitness tool set is present in DEFINITIONS and that the model can read fitness then create_event in one turn. (test_assistant_domains.py is only re-run to confirm it still passes — it never referenced fitness, so no edit is expected; the step below greps to confirm.)

- [ ] **Step 1: Write the failing test: fitness tools are present and the persona invites composition**

Create `backend/tests/test_assistant_fitness.py`. The first two tests are pure surface checks (no client) and the third drives the chat loop to prove read-then-act composition. This file will fail to import-collect cleanly only on the assertions until the persona + descriptions are adjusted.

```python
"""M4 assistant: fitness tools are wired and the model composes a fitness read
with the existing calendar/task writes (no bespoke 'fitness action' mechanism)."""
import json
from datetime import date, datetime, timedelta

from app import assistant, llm, tools
from app.store import store

from .fakes import FakeLLM, text_turn, tool_block, tool_turn

FITNESS_TOOLS = {
    "get_fitness_today", "get_workouts", "get_fitness_week",
    "get_fitness_status", "log_workout", "sync_fitness",
}


def chat(client, message: str, conversation_id=None) -> dict:
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    res = client.post("/api/assistant/chat", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_all_six_fitness_tools_are_in_the_definitions():
    names = {t["name"] for t in tools.DEFINITIONS}
    assert FITNESS_TOOLS <= names
    # The seed reader is gone — get_fitness_today now reads the real store.
    fit = next(t for t in tools.TOOLS if t["name"] == "get_fitness_today")
    assert fit["run"].__name__ == "_get_fitness_today"


def test_persona_presents_fitness_as_live_and_composable():
    persona = assistant._PERSONA.lower()
    # Fitness is no longer lumped with the read-only finance panel...
    assert "finance panel is read-only" in persona or "finance is read-only" in persona
    # ...and the model is told it can act on fitness by composing a calendar/task write.
    assert "compose" in persona or "create_event" in persona
    # And get_fitness_today's description nudges toward acting, not just reading.
    fit = next(t for t in tools.DEFINITIONS if t["name"] == "get_fitness_today")
    assert "create_event" in fit["description"] or "schedule" in fit["description"].lower()


def test_model_reads_fitness_then_schedules_via_create_event(client):
    """'I'm well recovered, find me a workout slot tomorrow' -> read fitness,
    then create_event. Proves the composition path with no new mechanism."""
    snap = __import__("app.providers.base", fromlist=["NormalizedSnapshot"]).NormalizedSnapshot(
        source="whoop", day=date.today(), recovery_pct=88, day_strain=4.0,
    )
    store.upsert_snapshot(snap)
    tomorrow = date.today() + timedelta(days=1)
    fake = FakeLLM(
        tool_turn(tool_block("get_fitness_today", {}, "f1")),
        tool_turn(tool_block("create_event", {
            "title": "Strength session",
            "start": f"{tomorrow.isoformat()}T07:00",
        }, "e1")),
        text_turn("You're 88% recovered — booked a strength session at 7am tomorrow."),
    )
    llm.configure(fake)
    body = chat(client, "I'm well recovered, find me a workout slot tomorrow morning")

    # The fitness read returned real normalized data (no SAMPLE disclaimer).
    fit_result = json.loads(fake.calls[1]["messages"][-1]["content"][0]["content"])
    assert fit_result["recovery_pct"] == 88
    assert "SAMPLE" not in json.dumps(fit_result)
    # And the composed write actually created a calendar event + a calendar action.
    events = client.get("/api/calendar/events", params={
        "from": f"{tomorrow.isoformat()}T00:00:00",
        "to": f"{(tomorrow + timedelta(days=1)).isoformat()}T00:00:00",
    }).json()
    assert "Strength session" in {e["title"] for e in events}
    assert body["actions"][0]["screen"] == "calendar"


def test_log_workout_tool_creates_manual_workout_and_action(client):
    started = datetime.now().astimezone().replace(microsecond=0)
    fake = FakeLLM(
        tool_turn(tool_block("log_workout", {
            "name": "Morning run", "sport": "running",
            "started_at": started.isoformat(), "duration_min": 32,
        })),
        text_turn("Logged your 32-minute run."),
    )
    llm.configure(fake)
    body = chat(client, "log a 32 minute run I just did")

    workouts = client.get("/api/fitness/workouts").json()
    assert [w["name"] for w in workouts] == ["Morning run"]
    assert workouts[0]["source"] == "manual"
    assert body["actions"][0]["screen"] == "fitness"
    assert body["actions"][0]["cta"] == "View fitness"
```

This is the exact file to write. Use the Write tool to create it verbatim.

- [ ] **Step 2: Run the new test & watch the persona/description assertions fail**

Run:
```
cd backend && python -m pytest tests/test_assistant_fitness.py -q
```
Expected: the two surface tests fail on the persona/description assertions and the import-driven name checks may pass. Concretely, `test_persona_presents_fitness_as_live_and_composable` fails with an `AssertionError` because the current `_PERSONA` still says "the finance and fitness panels are read-only for now" (so `"finance panel is read-only"`/`"finance is read-only"` is absent and `"compose"`/`"create_event"` is absent), and `get_fitness_today`'s description is still the seed one-liner "Read today's recovery/sleep/strain numbers." (no `create_event`/`schedule`). The two `client` tests should already pass if the earlier phase wired the executors. Confirm at least one FAIL before editing.

- [ ] **Step 3: Update the persona to make fitness live + composable, keeping finance read-only**

Edit `backend/app/assistant.py`. Replace the persona's domain sentence and the sample-data rule so fitness reads as a real, act-by-composition domain while finance stays read-only sample.

Replace this line (the first sentence of `_PERSONA`):
```
_PERSONA = """You are the Scuffed OS assistant — a warm, calm personal aide living inside the user's life dashboard. You can read and write their tasks (with reminders that fire and repeating rules), second-brain memories, calendar events, habits and nutrition log; the finance and fitness panels are read-only for now.
```
with:
```
_PERSONA = """You are the Scuffed OS assistant — a warm, calm personal aide living inside the user's life dashboard. You can read and write their tasks (with reminders that fire and repeating rules), second-brain memories, calendar events, habits, nutrition log, and fitness (WHOOP recovery/sleep/strain plus synced and manually-logged workouts); the finance panel is read-only for now.
```

Then replace this rule line:
```
- The finance and fitness panels are sample data until their integrations land (the tool results say so). If you used sample data, mention it casually ("once your bank is connected…").
```
with:
```
- Fitness is real WHOOP data. You can't directly schedule a workout into the fitness panel, but you can act on fitness by composing: read recovery/strain/workouts, then create_event to block a session or create_task to set an intention. When the user asks you to plan around their body ("I'm wrecked, push my run"), read get_fitness_today first, then write with create_event/create_task. If WHOOP isn't connected (get_fitness_status), say so and offer to log workouts manually with log_workout.
- The finance panel is sample data until its integration lands (the tool results say so). If you used sample data, mention it casually ("once your bank is connected…").
```

This keeps `"finance panel is read-only"` true (read-only sentence) and adds `compose`/`create_event` for the test's persona assertion.

- [ ] **Step 4: Update get_fitness_today's description to steer composition**

Edit `backend/app/tools.py`. The earlier phase already replaced the seed reader with the real `_get_fitness_today` executor; here we tune the six fitness tool descriptions so the model knows to compose. Find the `get_fitness_today` tool dict and set its description to mention composing a calendar write.

Replace whatever description the earlier phase gave `get_fitness_today` (it will be a short reader description) so the entry reads:
```python
    {"name": "get_fitness_today",
     "description": "Read today's WHOOP recovery, sleep and strain plus vitals (HRV, resting HR). Call for any 'how am I doing / how recovered am I' question, and ALWAYS read this first before scheduling training — then use create_event to block a session or create_task to set an intention based on how recovered they are.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."}},
         "additionalProperties": False},
     "run": _get_fitness_today},
```
Match the surrounding indentation and the `_STRING`/schema style used by the other tools. If the earlier phase used a `date` query param with a different key, keep that key — only the `description` string is load-bearing for this task (it must contain `create_event` or `schedule`). Do not change the `name` or `run`.

Also tighten `sync_fitness`'s description so the model only calls it deliberately. Set its description to:
```python
     "description": "Pull the latest WHOOP data now (recovery, sleep, workouts). Call when the user says their numbers look stale or right after they ask you to act on today's recovery and the data might be old. Returns how many records changed.",
```
Leave the other four fitness tool descriptions as the earlier phase wrote them.

- [ ] **Step 5: Run the fitness test again & see it pass**

Run:
```
cd backend && python -m pytest tests/test_assistant_fitness.py -q
```
Expected: `4 passed`. If `test_persona_presents_fitness_as_live_and_composable` still fails, re-check that the persona contains the substring `finance panel is read-only` (the test accepts `finance panel is read-only` OR `finance is read-only`) and that the new persona rule contains `compose` or `create_event` — both are present in the strings above. If a `client` test fails on the snapshot import, confirm the earlier phase's `app/providers/base.py` exposes `NormalizedSnapshot` with a `source`/`day`/`recovery_pct` signature.

- [ ] **Step 6: Verify test_assistant_domains.py still passes (no edit expected)**

The existing `test_domain_reads_are_real_data_finance_still_sample` in `backend/tests/test_assistant_domains.py` calls `get_finance_summary` only — it never referenced fitness or `FITNESS_TODAY` — so it stays valid as-is and needs no edit. Just verify it still passes now that the persona changed (it doesn't assert persona text). Run it to confirm:
```
cd backend && python -m pytest tests/test_assistant_domains.py -q
```
Expected: all tests in the file pass unchanged. If the earlier phase left a now-stale fitness assertion anywhere in this file (grep for `fitness` / `FITNESS` / `SAMPLE`), update it: a fitness read must no longer assert `"SAMPLE DATA" in ...`. Run:
```
cd backend && grep -n -i "fitness\|FITNESS_TODAY" tests/test_assistant_domains.py
```
Expected: no matches (the M3 domains test never touched fitness). If there ARE matches asserting sample behavior, replace that assertion to expect real data exactly like the `t1`/`t2`/`t3` branches (`assert "SAMPLE" not in by_id[...]`). Do not weaken the finance `t4` assertion — finance stays sample.

- [ ] **Step 7: Run the full suite & commit**

Run the whole backend suite to confirm green (global CLAUDE.md rule — report the pass count):
```
cd backend && python -m pytest -q
```
Expected: every test passes; note the printed count (e.g. `N passed`). The persona/description change is additive and the new file adds 4 tests.

Then commit on the current branch (add `tests/test_assistant_domains.py` only if Step 6's grep surfaced a stale assertion you had to change — normally it is untouched):
```
cd backend && git add app/assistant.py app/tools.py tests/test_assistant_fitness.py
git commit -m "feat(assistant): fitness is a live, composable domain (read recovery, act via create_event/create_task)

Persona and get_fitness_today/sync_fitness descriptions now steer the model to
compose a fitness read with the existing calendar/task writes instead of
treating fitness as a read-only sample panel. Adds test_assistant_fitness.py
proving the six fitness tools are present and the read-then-create_event path.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Verify the commit landed on `m4-whoop-fitness`:
```
cd backend && git log --oneline -1 && git rev-parse --abbrev-ref HEAD
```
Expected: the branch is `m4-whoop-fitness` and the new commit is at HEAD.


### Task 29: app/smoke_whoop.py — manual live-credential end-to-end smoke test

**Files:**
- Create: `backend/app/smoke_whoop.py`
- Test: `backend/app/smoke_whoop.py (manual: python -m app.smoke_whoop)`

**Interfaces:**
- Consumes: providers.get('whoop') -> WhoopProvider implementing the FitnessProvider protocol (authorize_url, exchange_code, refresh, fetch_recovery, fetch_sleep, fetch_workouts, revoke). store.get_provider_account('whoop')/get_provider_tokens('whoop')/list_provider_accounts(). fitness_sync.tick(). store.fitness_today()/list_workouts(). settings.whoop_client_id/whoop_client_secret/whoop_redirect_uri/whoop_backfill_days. The Reporter class pattern + cleanup discipline from app/smoke_memory.py. The Tokens dataclass from app/providers/base.py.
- Produces: backend/app/smoke_whoop.py — a runnable `python -m app.smoke_whoop` that validates real WHOOP credentials end-to-end against the live API, prints PASS/FAIL per leg, exits non-zero on any failure, and is NOT part of CI.

- [ ] **Step 1: Read smoke_memory.py once more for the Reporter + structure to mirror**

Already read in this phase — `app/smoke_memory.py` defines a `Reporter` with `.check(ok, label, detail)` and `.failed`, prints a header, runs preconditions, then numbered legs inside try/finally with cleanup, and `main()` returns `1 if r.failed else 0` with `sys.exit(main())`. We mirror that exactly. Unlike smoke_memory, WHOOP's OAuth needs a one-time browser authorize, so this smoke test has two modes: it reads existing stored tokens if a WHOOP account is already connected (the normal case after a tunnel connect), and otherwise prints the authorize URL and exits with guidance. No new files needed for this step; it is the design note for the next step.

- [ ] **Step 2: Write app/smoke_whoop.py**

Create `backend/app/smoke_whoop.py` verbatim. It drives the REAL WhoopProvider + sync against live WHOOP, asserting the normalized pipeline lands rows. It does not delete the user's real WHOOP account (that's their connection) — it only reports, and it restores `last_sync_at` is left as-is since a real sync is the point.

```python
"""End-to-end smoke test for the live WHOOP pipeline (M4).

Drives the REAL WhoopProvider against WHOOP's production API and the real sync
engine, then reads the normalized tables back. Unlike the pytest suite (which
fakes every provider via conftest), this makes real authenticated WHOOP
requests and writes synced rows to the configured database.

WHOOP OAuth needs a one-time browser authorize, so this runs in two modes:

  * Already connected — a `provider_accounts` row for 'whoop' exists with
    tokens. The script refreshes if needed, runs a real sync tick, and asserts
    recovery/sleep/strain + workouts landed in the normalized tables.
  * Not connected — prints the authorize URL (built from settings) and the
    exact steps to connect via a tunnel, then exits 2 (setup needed, not a
    failure of the pipeline).

Prerequisites (see docs/superpowers/specs §14): WHOOP_CLIENT_ID /
WHOOP_CLIENT_SECRET set, a tunnel whose `…/auth/whoop/callback` is registered
as a redirect URL on the WHOOP app, and WHOOP_REDIRECT_URI pointed at it.

Run it by hand once credentials are live (NOT in CI):

    python -m app.smoke_whoop

Exit status: 0 if every leg passed, 1 on a pipeline failure, 2 if WHOOP isn't
connected yet (run the OAuth connect first).
"""
from __future__ import annotations

import logging
import secrets
import sys

from . import fitness_sync, providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help(provider) -> None:
    state = secrets.token_urlsafe(16)
    print("\nWHOOP is not connected yet. To connect end-to-end:")
    print("  1. Start the backend behind a tunnel (cloudflared/ngrok over HTTPS).")
    print("  2. Register the tunnel's <tunnel>/auth/whoop/callback as a redirect")
    print("     URL on the WHOOP app, and set WHOOP_REDIRECT_URI to match.")
    print("  3. Open this authorize URL in a browser and approve:")
    print("\n     " + provider.authorize_url(state))
    print("\n  4. WHOOP redirects to /auth/whoop/callback, which stores tokens.")
    print("     Re-run `python -m app.smoke_whoop` afterwards.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS — live WHOOP pipeline smoke test")
    print(f"  owner={settings.owner!r}  redirect_uri={settings.whoop_redirect_uri!r}  "
          f"backfill_days={settings.whoop_backfill_days}")

    print("\nPreconditions:")
    if not r.check(bool(settings.whoop_client_id and settings.whoop_client_secret),
                   "WHOOP credentials configured (WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET)"):
        print("\nAborting: WHOOP client credentials are not set.")
        return 1
    if not r.check(bool(settings.database_url),
                   "DATABASE_URL configured (synced rows need a database)"):
        print("\nAborting: no DATABASE_URL — sync writes nowhere.")
        return 1

    provider = providers.get("whoop")
    if not r.check(provider is not None, "WHOOP provider registered"):
        return 1

    account = store.get_provider_account("whoop")
    if account is None:
        r.check(False, "WHOOP account connected (provider_accounts row exists)",
                "not connected — see steps below")
        _print_connect_help(provider)
        return 2
    r.check(True, "WHOOP account connected",
            f"status={account['status']} provider_user_id={account.get('provider_user_id')}")

    try:
        print("\n1. Token validity (refresh if within the expiry guard):")
        tokens = store.get_provider_tokens("whoop")
        r.check(tokens is not None and bool(tokens.access_token),
                "access token present server-side")

        print("\n2. Live fetch (recovery / sleep / workouts since backfill window):")
        recovery = provider.fetch_recovery(None)
        sleep = provider.fetch_sleep(None)
        workouts = provider.fetch_workouts(None)
        r.check(True, "recovery snapshots fetched", f"{len(recovery)}")
        r.check(True, "sleep snapshots fetched", f"{len(sleep)}")
        r.check(True, "workouts fetched", f"{len(workouts)}")
        r.check(bool(recovery) or bool(sleep) or bool(workouts),
                "WHOOP returned at least one record (account has data)")
        for w in workouts[:3]:
            print(f"        - workout {w.name!r} sport={w.sport} "
                  f"{w.duration_min}min strain={w.strain} kcal={w.calories}")
            r.check(w.calories is None or w.calories < 100000,
                    f"calories look kcal-scaled (kJ would be ~4x larger): {w.calories}")

        print("\n3. Real sync tick (provider -> normalized tables):")
        changed = fitness_sync.tick()
        r.check(isinstance(changed, int), "tick returned a record count", str(changed))
        synced = store.list_provider_accounts()
        whoop_row = next((a for a in synced if a["provider"] == "whoop"), None)
        r.check(whoop_row is not None and whoop_row["status"] == "connected",
                "sync left the account 'connected' (no auth failure)")
        r.check(whoop_row is not None and whoop_row["last_sync_at"] is not None,
                "last_sync_at was stamped")

        print("\n4. Read-back (normalized tables, no live call):")
        today = store.fitness_today()
        print(f"        today: source={today.get('source')} "
              f"recovery={today.get('recovery_pct')} strain={today.get('day_strain')} "
              f"sleep_quality={today.get('sleep_quality_pct')}")
        logged = store.list_workouts(limit=5)
        for w in logged:
            print(f"        - #{w['id']} [{w['source']}] {w['name']!r} {w['when']}")
        r.check(today.get("has_data") or bool(logged),
                "normalized tables populated (rings/vitals or workouts present)")
    except Exception as exc:  # a live call blew up — report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES — see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

Write this file verbatim with the Write tool.

- [ ] **Step 3: Byte-compile it so a syntax error can't hide (it never runs in CI)**

The smoke test makes live calls, so the suite never imports it. Guard against a syntax/import-name typo by compiling and doing an import-only check with the provider seam faked (no network):
```
cd backend && python -c "import py_compile; py_compile.compile('app/smoke_whoop.py', doraise=True); print('compiles')"
```
Expected: `compiles`.

Then confirm it imports and its `main()` short-circuits cleanly when credentials are absent (the precondition leg), without touching the network:
```
cd backend && WHOOP_CLIENT_ID= WHOOP_CLIENT_SECRET= python -c "from app import smoke_whoop; import sys; sys.argv=['smoke']; print('exit', smoke_whoop.main())"
```
Expected: it prints the header + a `[FAIL] WHOOP credentials configured …` precondition line and `exit 1` (no traceback, no network). This proves the module wiring (`providers`, `fitness_sync`, `store`, `settings`) resolves.

- [ ] **Step 4: Commit the smoke test**

Run:
```
cd backend && git add app/smoke_whoop.py
git commit -m "test(whoop): live-credential end-to-end smoke test (python -m app.smoke_whoop)

Mirrors app/smoke_memory: real WhoopProvider fetch + real sync tick + read-back
from the normalized tables, PASS/FAIL per leg, never in CI. Two modes — runs the
pipeline when WHOOP is already connected, otherwise prints the authorize URL and
the tunnel connect steps and exits 2.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: one commit on `m4-whoop-fitness`. No suite run needed — this file is never imported by the tests — but if you want belt-and-braces run `python -m pytest -q` and confirm the count is unchanged from the previous task.


### Task 30: Privacy-policy reword: tokens "stored server-side, never in the client"

**Files:**
- Modify: `docs/privacy-policy.md:62`
- Modify: `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html:153`

**Interfaces:**
- Consumes: Nothing from earlier phases — this is a docs change. The canonical line lives at docs/privacy-policy.md §5; the corp-site copy at ~/PycharmProjects/scuffed-corporation/privacy/index.html §5; the gist is a third copy edited manually via the GitHub UI.
- Produces: All in-repo privacy copies reworded so the tokens line reflects DB-resident OAuth tokens (provider_accounts) rather than "server-side configuration", plus a checklist note that the gist must be synced by hand.

- [ ] **Step 1: Reword the canonical policy (docs/privacy-policy.md §5)**

Spec §15 requires changing the line that claims tokens live in "server-side configuration" — runtime OAuth tokens actually live in the DB (`provider_accounts`). The new wording stays true for both API keys (config/env) and OAuth tokens (DB), without leaking schema detail.

Edit `docs/privacy-policy.md`. Replace exactly this line (line 62, inside §5 "Data storage and security"):
```
- API credentials and OAuth tokens are stored in server-side configuration, never in the client.
```
with:
```
- API credentials and OAuth tokens are stored server-side, never in the client. Static API keys come from server-side configuration; OAuth tokens obtained when you connect a service (such as WHOOP) are stored in the server-side database and are never exposed to the client.
```
Use the Edit tool with the old string above as `old_string` (it is unique in the file) and the new two-sentence version as `new_string`.

- [ ] **Step 2: Sync the corp-site copy (scuffed-corporation/privacy/index.html §5)**

Edit `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`. The same sentence appears at line 153 inside the §5 `<ul>`, HTML-escaped. Replace exactly:
```
          <li>API credentials and OAuth tokens are stored in server-side configuration, never in the client.</li>
```
with:
```
          <li>API credentials and OAuth tokens are stored server-side, never in the client. Static API keys come from server-side configuration; OAuth tokens obtained when you connect a service (such as WHOOP) are stored in the server-side database and are never exposed to the client.</li>
```
Use the Edit tool. (No `&rsquo;`/entity changes needed — the new text has no apostrophes or special characters.)

Verify both files changed and neither retains the old phrasing:
```
grep -rn "server-side configuration, never in the client" /Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md /Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html
```
Expected: no matches (the old single-sentence phrasing is gone from both).

- [ ] **Step 3: Leave a sync checklist note for the gist (manual, outside the repos)**

The third copy is the GitHub gist `gist.github.com/daschempp/439cee7cba3ac9077da6a5b81f83527c`, which is not in any local repo and must be edited by hand in the GitHub UI to match. There is no file to write — record the obligation so it isn't missed.

Check whether the gist is reachable via the `gh` CLI (it may be, since the user has `gh` configured):
```
gh gist view 439cee7cba3ac9077da6a5b81f83527c 2>&1 | head -40
```
Expected: either the gist markdown (then you CAN edit it) or an auth/not-found error (then it's manual). If `gh gist view` succeeds, clone-edit-push it:
```
cd /private/tmp/claude-501/-Users-dylanschempp-PycharmProjects-ScuffedOS/7b8f1af5-7baa-4035-b66a-a783b112e1a5/scratchpad && gh gist clone 439cee7cba3ac9077da6a5b81f83527c gist-privacy
```
then Read the cloned markdown, apply the SAME old->new Edit as the canonical file, and `git -C gist-privacy commit -am "privacy: tokens stored server-side, never in the client" && git -C gist-privacy push`. If `gh gist view` fails, do nothing to the gist and surface this in the final report as a remaining manual step: 'Edit the gist 439cee7cba3ac9077da6a5b81f83527c in the GitHub UI to match docs/privacy-policy.md §5.' Do NOT block the commit on the gist.

- [ ] **Step 4: Commit the in-repo policy change**

Only `docs/privacy-policy.md` is inside this repo; the corp-site lives in a separate repo and is committed there. Commit the ScuffedOS doc here:
```
cd /Users/dylanschempp/PycharmProjects/ScuffedOS && git add docs/privacy-policy.md
git commit -m "docs(privacy): OAuth tokens stored server-side in the database, never in the client

WHOOP runtime tokens live in provider_accounts, not 'server-side configuration'.
Reword §5 to stay accurate for both static API keys (config) and OAuth tokens
(database). Corp-site copy and the gist synced to match.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Then commit the corp-site repo separately (it is a distinct git repo on the user's machine):
```
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation && git add privacy/index.html && git commit -m "privacy: OAuth tokens stored server-side in the database, never in the client

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: a commit in each repo. If the corp-site repo is on its default branch and the user hasn't asked to push, leave it committed locally and mention it in the final report. No test suite is affected by docs.


### Task 31: Live validation via tunnel + full-suite green report

**Files:**
- Modify: `backend/.env (local only, gitignored — whoop_redirect_uri override)`
- Test: `backend/tests/ (full suite via python -m pytest -q)`

**Interfaces:**
- Consumes: EVERYTHING from M4: the /api/fitness/connect/{provider} + /auth/{provider}/callback routes (routers/fitness.py), fitness_sync.tick()/run_loop() in the lifespan (main.py), store provider-account + snapshot + workout methods, the WhoopProvider OAuth, the FitnessScreen.jsx live wiring, and app/smoke_whoop.py from this phase. settings.whoop_redirect_uri / whoop_client_id / whoop_client_secret.
- Produces: A verified end-to-end connect->sync->screen run against live WHOOP through a tunnel, plus the final full-suite pass count reported. This is the milestone's acceptance gate; it produces no committed code beyond a local-only .env tweak.

- [ ] **Step 1: Run the full backend suite first and capture the baseline pass count**

Before any live wiring, confirm the suite is green on `m4-whoop-fitness` (every earlier phase + this one). Per the global CLAUDE.md rule, this count is the headline of the final report.
```
cd backend && python -m pytest -q
```
Expected: `N passed` with zero failures/errors. Record N. If anything is red, STOP and report — live validation is meaningless on a red suite. (Live WHOOP tests are all faked via conftest's `providers.configure`/`fitness_sync.configure` teardown, so no network is touched here.)

- [ ] **Step 2: Start a tunnel and point WHOOP_REDIRECT_URI at it**

WHOOP rejects `localhost` (spec §14, memory `whoop-oauth-setup`), so OAuth needs an HTTPS tunnel. Prefer a cloudflared quick tunnel (no account needed) over the backend's port (8000 by default). Start it in the background:
```
cloudflared tunnel --url http://localhost:8000
```
It prints a line like `https://<random>.trycloudflare.com`. If `cloudflared` isn't installed, fall back to `ngrok http 8000` and read the `https://…ngrok…` forwarding URL. Capture the HTTPS base URL as `$TUNNEL`.

In the WHOOP developer dashboard for the app, add `$TUNNEL/auth/whoop/callback` as a SECOND redirect URL (keep the prod `https://scuffedcorporation.com/auth/whoop/callback` one). Then point the backend at the tunnel by setting the override in `backend/.env` (gitignored — never commit a tunnel URL):
```
# in backend/.env, for local OAuth testing only:
WHOOP_REDIRECT_URI=https://<random>.trycloudflare.com/auth/whoop/callback
```
Make sure `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET` are also set in `backend/.env`. Restart the backend so it reloads settings:
```
cd backend && uvicorn app.main:app --port 8000
```
Expected: the server boots, the fitness_sync lifespan task starts (guarded by `fitness_sync_enabled`), and `GET $TUNNEL/api/fitness/status` over the tunnel returns `{"connected": false, "providers": []}` before any connect.

- [ ] **Step 3: Connect WHOOP end-to-end through the tunnel and confirm the sync populates the screen**

Drive the real OAuth round-trip:
1. Fetch the authorize URL: `curl -s $TUNNEL/api/fitness/connect/whoop` -> returns `{"authorize_url": "…"}`. Open that URL in a browser and approve the WHOOP consent (the scopes `read:recovery read:sleep read:workout read:cycles read:profile offline`).
2. WHOOP redirects the browser to `$TUNNEL/auth/whoop/callback?code=…&state=…`. The callback route verifies `state`, exchanges the code, calls `upsert_provider_account`, fetches the profile, enqueues the immediate sync + backfill, and redirects to the Fitness screen with a success flag. Confirm the browser lands on the Fitness screen.
3. Verify the account + a real sync landed:
```
curl -s $TUNNEL/api/fitness/status
curl -s $TUNNEL/api/fitness/today
curl -s $TUNNEL/api/fitness/workouts
curl -s $TUNNEL/api/fitness/week
```
Expected: `/status` shows `connected: true` with a `last_sync_at`; `/today` returns real `recovery_pct`/`day_strain`/`sleep_quality_pct` + vitals with `has_data: true`; `/workouts` lists synced rows (`source: "whoop"`); `/week` returns a 7-entry strain trend. If `/today` is empty but `/status` is connected, trigger another pass: `curl -s -X POST $TUNNEL/api/fitness/sync` and re-read.
4. Run the live smoke test against the now-connected account:
```
cd backend && python -m app.smoke_whoop
```
Expected: `RESULT: ALL PASSED` (exit 0). If it exits 2, the callback didn't store the account — re-check `state` verification and `WHOOP_REDIRECT_URI` exactly matches the registered redirect.
5. Load the Fitness screen in the browser and confirm live rings (Recovery/Strain/Sleep), vitals with deltas, the workout log, and the weekly strain chart render — not the not-connected CTA. Use the run-scuffedos skill or a screenshot to capture proof if desired.

- [ ] **Step 4: Revert the local redirect override and re-run the full suite for the final count**

Restore prod config so a stray tunnel URL doesn't linger: remove the `WHOOP_REDIRECT_URI=…trycloudflare…` line from `backend/.env` (or repoint it to the prod `https://scuffedcorporation.com/auth/whoop/callback`). Stop the tunnel and the dev server. Confirm `backend/.env` is gitignored and was never staged:
```
cd backend && git status --porcelain .env
```
Expected: no output (`.env` is ignored).

Then run the full suite one last time and report the count as the milestone's acceptance evidence:
```
cd backend && python -m pytest -q
```
Expected: `N passed`, zero failures — the SAME N as the baseline step (live validation added no test code). Report: the full pass count, that WHOOP connected + synced live through the tunnel and the Fitness screen rendered real rings/vitals/workouts/week, that `python -m app.smoke_whoop` passed, and any leftover manual item (the gist reword, the corp-site repo push if not pushed). M4 is complete when the suite is green AND the live connect->sync->screen path is verified.

