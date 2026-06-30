# M4 — Fitness domain (WHOOP sync) — Design

> Status: **approved design, pre-implementation** · Date: 2026-06-30 · Owner: Dylan Schempp
> Milestone: M4 · Supersedes the "planned" sketch in [fitness.md](../../fitness.md)

## 1. Goal

Replace the sample Fitness stub with a real, **full vertical slice**: connect a WHOOP
account over OAuth, sync recovery / sleep / strain / workouts on a schedule into normalized
local tables, serve them through `/api/fitness/*`, wire the existing Fitness screen to live
data, and let the assistant read (and act on) real fitness data. Built so a second wearable
(Oura, Apple Health) is a later *adapter*, not a schema rewrite.

## 2. Scope

**In scope (core):**
- WHOOP OAuth connect / token refresh / disconnect.
- Scheduled pull sync (recovery, sleep, strain/cycle, workouts) into normalized tables.
- `/api/fitness/*` read + write endpoints.
- Fitness screen rewritten to live data, with connection states.
- Assistant reads real fitness data.
- Disconnect-with-deletion (privacy-policy obligation).

**In scope (the three approved extras):**
1. **Manual workout logging** — the "Log workout" button becomes real; manual + synced coexist.
2. **Workout → habit auto-complete** — a workout (synced or manual) auto-completes a habit
   linked `link='workout'` (the M3 hook).
3. **Assistant fitness actions** — the assistant acts on fitness data by *composition*
   (read fitness + existing calendar/task writes), no bespoke mechanism.

**Explicitly NOT in scope (YAGNI boundary):**
- No Oura or Apple Health adapters (extension points only, documented below).
- No generic multi-provider plugin framework, no provider settings UI.
- No fuzzy manual↔synced workout dedupe (see §6).
- No webhooks (pull only — chosen because the backend isn't reliably public; see §8).

## 3. Architecture & module layout

Follows the established per-domain pattern (model → migration → store → router → schemas →
tools), plus the seam pattern used by `llm.py` / `memory_engine.py` for testability.

| Module | Responsibility |
| --- | --- |
| `app/providers/base.py` | `FitnessProvider` protocol (the vendor-neutral seam) + normalized dataclasses |
| `app/providers/whoop.py` | `WhoopProvider`: OAuth token exchange/refresh, authenticated v2 REST calls, WHOOP→normalized mapping. Lazy client; `configure(fake)` seam for tests |
| `app/fitness_sync.py` | Background tick loop (near-clone of `reminders.py`), registered in the FastAPI lifespan |
| `app/routers/fitness.py` | `/api/fitness/*` + the `/auth/{provider}/callback` route |
| `app/models.py` | +3 tables (§6) |
| `app/store.py` | Fitness reads (derive-on-read) + writes (idempotent upsert) + provider-account CRUD |
| `app/schemas.py` | `FitnessStatus`, `FitnessToday`, `WorkoutOut`, `WorkoutCreate`, `FitnessWeek` |
| `app/tools.py` | Real fitness tools replace the seed reader |
| `app/config.py` | New settings (§11) |
| `alembic/versions/0004_fitness.py` | The migration |
| `frontend/src/screens/FitnessScreen.jsx` | Rewritten to fetch live data |
| `app/smoke_whoop.py` | Optional manual live-credential smoke test (mirrors `smoke_memory`) |

**Decision: OAuth is hand-rolled with `httpx`** (already a dependency), not Authlib — the
authorization-code flow is ~40 lines and one provider doesn't justify a new dependency.

## 4. Provider seam (vendor-neutral core)

`FitnessProvider` protocol — the only thing the sync engine and routers know about:

```
class FitnessProvider(Protocol):
    name: str                       # 'whoop'
    kind: Literal['pull', 'push']   # whoop/oura = pull; apple_health = push
    def authorize_url(state) -> str
    def exchange_code(code) -> Tokens
    def refresh(tokens) -> Tokens
    def fetch_recovery(since) -> list[NormalizedSnapshot]
    def fetch_sleep(since)    -> list[NormalizedSnapshot]   # merged into snapshot by day
    def fetch_workouts(since) -> list[NormalizedWorkout]
    def revoke(tokens) -> None
```

- The sync engine iterates **connected pull-providers** generically.
- **Apple Health caveat:** no cloud REST API — data lives on-device in HealthKit. It would be
  a **push** provider (a companion app / export POSTing to an ingest endpoint), feeding the
  *same* normalized tables but *not* via the sync tick. The `kind` field encodes this so push
  providers are never polled. Unbuilt; the seam just leaves the door open.

## 5. Provider-agnostic principle

No WHOOP field names in tables or schemas. Every persisted row carries `source`
(`'whoop' | 'oura' | 'apple_health' | 'manual'`). Rows that map **1:1 to a provider record**
(workouts) also carry `source_id` for idempotent upsert. **Daily snapshots are different**:
one day aggregates several WHOOP records (recovery + cycle + sleep), so a snapshot has no
single source record — it's keyed by `(owner, source, day)` and upserted by day. The same
logical day can later merge fields from two providers.

## 6. Data model (migration `0004_fitness.py`)

All tables carry `owner` (default `"me"`), consistent with every existing table.

### `provider_account` — OAuth credentials + sync cursor
One row per `(owner, provider)` (unique).

| Field | Type | Notes |
| --- | --- | --- |
| `provider` | str | `'whoop'` today |
| `access_token` / `refresh_token` | str, nullable | nullable for push providers |
| `expires_at` | datetime, nullable | access-token expiry |
| `scopes` | str | space-delimited, as granted |
| `provider_user_id` | str, nullable | provider's user id |
| `status` | str | `'connected'` \| `'needs_reauth'` |
| `meta` | JSON | provider-specific extras |
| `connected_at` | datetime | |
| `last_sync_at` | datetime, nullable | incremental-pull cursor |

Tokens live **server-side only**, never sent to the client.

### `daily_snapshot` — per-day physiological summary
One row per `(owner, source, day)` (unique — the upsert key; no `source_id`, since a day folds
together several WHOOP records). **Consolidates** the prototype's separate "Daily snapshot" +
"Vital" entities — every UI vital is a daily scalar from the same records.

| Field | Type | Source | UI |
| --- | --- | --- | --- |
| `source`, `day` | str/date | | upsert key + ring date |
| `recovery_pct` | int? | recovery | Recovery ring |
| `day_strain` | float? | cycle (0–21) | Strain ring |
| `sleep_quality_pct` | int? | sleep performance | Sleep ring |
| `hrv_ms` | float? | recovery | Vitals |
| `resting_hr` | int? | recovery | Vitals |
| `respiratory_rate` | float? | sleep | Vitals |
| `sleep_hours` | float? | sleep | Vitals |
| `metrics_json` | JSON? | | escape hatch for provider-specific extras |
| `created_at`, `updated_at` | datetime | | |

Deltas (e.g. HRV "+6") and the **weekly strain trend** are derived on read (this-day vs
prior-day; week of `day_strain`) — not stored. Mirrors how habits/nutrition derive display.

### `workout` — synced + manual sessions

| Field | Type | Notes |
| --- | --- | --- |
| `source` | str | `'whoop'` (synced) or `'manual'` |
| `source_id` | str, nullable | provider id; **null for manual** |
| `name` | str | |
| `sport` | str, nullable | maps to UI icon/tint |
| `started_at` | datetime | |
| `duration_min` | int | |
| `strain` | float, nullable | |
| `calories` | int, nullable | **kJ→kcal** converted (WHOOP reports kilojoules) |
| `avg_hr` / `max_hr` | int, nullable | |
| `created_at`, `updated_at` | datetime | |

Unique on `(source, source_id)` **where `source_id` is not null** → synced workouts upsert
idempotently; manual rows (null `source_id`) never collide.

**No fuzzy manual↔synced dedupe.** A manually-logged run + a later WHOOP sync of the same
session = two rows (one `manual`, one `whoop`); the user can delete the manual one. We only
guarantee idempotent upsert of *synced* workouts.

**Day mapping:** WHOOP recovery/cycle are per physiological cycle; map each to a calendar
`day` using the cycle's start date in the user's local timezone (confirm cycle→day rule in §13).

## 7. OAuth flows

**Connect** (`GET /api/fitness/connect/{provider}` → authorize URL):
1. Build WHOOP authorize URL: `client_id`, `redirect_uri`, `response_type=code`, scopes, random `state` (stored server-side, one-time CSRF check).
2. User authorizes → WHOOP redirects to **`/auth/whoop/callback`** (the registered path; route generalized as `/auth/{provider}/callback`, mounted *outside* `/api`).
3. Callback: verify `state` → exchange `code` for tokens → store in `provider_account` → fetch profile for `provider_user_id` → enqueue immediate sync + `whoop_backfill_days` backfill → redirect browser to the Fitness screen with a success flag.

**Refresh** (inside `WhoopProvider`, transparent): before any authed call, if within ~60s of
`expires_at`, POST `grant_type=refresh_token`; store rotated tokens. On failure (revoked) →
set `status='needs_reauth'` and surface it.

**Disconnect** (`POST /api/fitness/disconnect/{provider}`):
1. Best-effort `revoke` at WHOOP.
2. Delete the `provider_account` row.
3. Delete that provider's `daily_snapshot` + `workout` rows (`source = provider`). **Manual
   workouts preserved.**

Deletion is immediate — well inside the policy's 30-day promise — and happens even if the
remote revoke call fails (deletion is the user-facing guarantee).

## 8. Sync engine (`fitness_sync.py`)

A near-clone of `reminders.py`, registered in the same lifespan, guarded by
`fitness_sync_enabled`. Each tick (`fitness_sync_seconds`, default 1800 = 30 min):
1. Load connected **pull**-providers with valid (or refreshable) tokens.
2. `since = last_sync_at` (or `now − whoop_backfill_days` on first run).
3. Fetch recovery / sleep / cycle / workouts changed since `since` (paginated).
4. Map → upsert `daily_snapshot` by `(owner, source, day)`, `workout` by `(source, source_id)`.
5. On each new/updated workout, run the **habit auto-complete** (§10.2).
6. Update `last_sync_at`.

Per-provider errors (rate-limit, network, auth) are caught and logged; the tick never crashes;
auth failures flip `needs_reauth`. `POST /api/fitness/sync` triggers a run on demand (used by
the post-connect immediate sync, manual testing, and the assistant's `sync_fitness` tool).

## 9. API surface (`app/routers/fitness.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/fitness/status` | Per-provider state (connected / `needs_reauth` / `last_sync_at`) |
| `GET` | `/api/fitness/connect/{provider}` | Returns OAuth authorize URL |
| `GET` | `/auth/{provider}/callback` | OAuth callback (outside `/api`) |
| `POST` | `/api/fitness/disconnect/{provider}` | Revoke + delete provider data |
| `GET` | `/api/fitness/today` | Rings + vitals (derived deltas) |
| `GET` | `/api/fitness/workouts` | Workout log (synced + manual) |
| `POST` | `/api/fitness/workouts` | Log a manual workout |
| `DELETE` | `/api/fitness/workouts/{id}` | Delete a workout |
| `GET` | `/api/fitness/week` | Weekly strain trend |
| `POST` | `/api/fitness/sync` | Trigger a sync run |

## 10. Frontend + extras

**Fitness screen** (`FitnessScreen.jsx`) — keeps existing visual components (Card,
ProgressRing, Badge…), follows the M3 screens' data-loading convention, swaps hardcoded arrays
for fetches to `/today`, `/workouts`, `/week`, `/status`. States:
- **Not connected** → "Connect WHOOP" CTA → `GET /connect/whoop` → redirect to authorize.
- **Connected** → live rings/vitals/workouts/week; eyebrow shows last-sync time; disconnect control.
- **`needs_reauth`** → reconnect banner. **Just-connected / syncing** → "Syncing…" empty state.
- **Log workout** button → small form → `POST /workouts`.

**Extras:**
1. **Manual workout logging** — `WorkoutCreate` + `store.create_workout` (`source='manual'`) + form + `log_workout` tool.
2. **Workout → habit auto-complete** — on any workout landing (synced or manual), the store
   auto-completes a habit with `link='workout'` for that day, reusing the existing water
   auto-complete path (never clobbers a manual tap; see `habits.py` docstring).
3. **Assistant fitness actions** — composition only: assistant reads fitness, writes with its
   existing `create_event` / task tools. The screen's teaser insight becomes a real capability.

**Assistant tools** (`tools.py`) — seed `get_fitness_today` replaced by:
`get_fitness_today`, `get_workouts`, `get_fitness_week`, `get_fitness_status`, `log_workout`,
`sync_fitness`.

## 11. Config additions (`config.py`)

| Setting | Default | Notes |
| --- | --- | --- |
| `whoop_client_id` | `""` | from env |
| `whoop_client_secret` | `""` | from env |
| `whoop_redirect_uri` | `https://scuffedcorporation.com/auth/whoop/callback` | switch to tunnel URL in dev |
| `fitness_sync_enabled` | `True` | |
| `fitness_sync_seconds` | `1800` | 30 min |
| `whoop_backfill_days` | `30` | first-connect backfill window |

## 12. Error handling

**Reads never depend on a live WHOOP call** — `/today`, `/workouts`, `/week` read the
normalized tables, so the screen works when WHOOP is down or sync is mid-flight. Sync failures
log and retry next tick. Auth failures flip `needs_reauth`. Disconnect deletes local
data/tokens even if remote revoke fails. Tool errors return `{"error": …}` to the model
(existing convention).

## 13. Confirm against live API during implementation

My field knowledge may be stale; the plan must include a step to verify against live v2 docs:
- Auth URL `…/oauth/oauth2/auth`, token URL `…/oauth/oauth2/token`, revoke endpoint.
- API base `https://api.prod.whoop.com/developer/v2/`; collection paths for recovery / sleep /
  cycle / workout / profile; pagination (`start`/`end`/`nextToken`/`limit`); v2 ids are UUIDs.
- Exact score field names (recovery_score, hrv_rmssd_milli, resting_heart_rate, strain,
  sleep_performance_percentage, respiratory_rate, kilojoule, average/max_heart_rate, sport).
- Cycle→calendar-day rule and timezone handling.
- Scope strings: `read:recovery read:sleep read:workout read:cycles read:profile offline`.

## 14. Local development

WHOOP rejects `localhost`. For OAuth testing, run a tunnel (cloudflared named tunnel preferred
for a stable URL; ngrok works but rotates) and register its HTTPS `…/auth/whoop/callback` as a
**second** redirect URL on the WHOOP app. `whoop_redirect_uri` switches prod ↔ tunnel.

## 15. Privacy-policy reconciliation

The policy says tokens are "stored in server-side **configuration**." Runtime OAuth tokens must
live in the DB (`provider_account`) instead. Reword that line to "stored server-side, never in
the client" (stays true) across all three copies — `docs/privacy-policy.md` (canonical), the
gist, and the corp-site `/privacy/` page. Optional future hardening: encrypt the token columns
at rest. (Tracked in memory: `whoop-oauth-setup`, `scuffed-os-implementation`.)

## 16. Testing strategy

Suite must stay green. A `providers.configure(fake)` seam (mirroring `llm`/`memory_engine`)
swaps the registered provider so every test runs against fixture payloads, no network:
- **Mapping:** WHOOP JSON → normalized; kJ→kcal; delta + weekly derivation.
- **OAuth:** state verification; token refresh; refresh-failure → `needs_reauth`.
- **Store:** upsert idempotency (same `source_id` twice = one row); disconnect deletes synced,
  keeps manual; manual workout → habit auto-complete.
- **Router:** connect returns authorize URL; callback (fake exchange) stores account + triggers
  sync; disconnect; `/today` `/workouts` `/week` shapes; manual POST; `/sync`.
- **Optional manual:** `python -m app.smoke_whoop` validates real credentials end-to-end (not CI).

## 17. Suggested implementation phasing

1. Migration + models + store CRUD (no network) + tests.
2. Provider seam + `WhoopProvider` mapping against fixtures + tests.
3. OAuth connect/refresh/disconnect endpoints + `/auth/whoop/callback` + tests.
4. Sync engine + lifespan registration + tests.
5. Read/write API + schemas + assistant tools (replace seed reader) + tests.
6. Frontend rewrite + connection states.
7. Extras: manual logging, habit auto-complete wiring, assistant-action enablement.
8. Live validation via tunnel + `smoke_whoop`; privacy-policy reword.
