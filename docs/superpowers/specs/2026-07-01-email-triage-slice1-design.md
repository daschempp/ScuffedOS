# M5 — Email domain, slice 1 (Google OAuth + Gmail sync + read-only triage) — Design

> Status: **approved design, pre-implementation** · Date: 2026-07-01 · Owner: Dylan Schempp
> Milestone: M5 (email), first slice. Builds on the M4 OAuth substrate.
> Supersedes the "planned" sketch in [email.md](../../email.md).

## 1. Goal & scope

Connect a Google account, sync the Gmail inbox, LLM-triage each message (category +
summary) **on sync**, and render the live **read-only** two-pane inbox. This is the first
of several email slices.

**In scope:** Google OAuth (via a shared, refactored OAuth layer), Gmail read-only sync,
LLM triage (category + summary bullets) computed on sync and cached, the read-only inbox +
reading pane, read-only assistant tools, and the privacy-policy update.

**Deferred to later slices (NOT this slice):** draft generation (tone variants), the send
path, archive, and cross-domain actions (email→task/calendar/people). No message *bodies*
are stored (fetched on demand).

## 2. The OAuth refactor (generalize M4's substrate)

M4's `FitnessProvider` protocol bundles OAuth methods with fitness-data methods. Split it so
a second OAuth *domain* (email) reuses the plumbing. **M4's OAuth tests are the guardrail —
they move with the endpoints and must stay green; the WHOOP live path must not regress.**

- `OAuthProvider` (base protocol, `app/providers/base.py`): `name`, `authorize_url(state)`,
  `exchange_code(code) -> Tokens`, `refresh(tokens) -> Tokens`, `revoke(tokens)`,
  `set_tokens(tokens)`, `success_redirect() -> str` (the provider-specific screen to land on
  after connect — WHOOP → `/?screen=fitness&connected=whoop`, Google →
  `/?screen=email&connected=google`), `on_connected() -> None` (post-connect hook: WHOOP
  triggers the fitness sync, Google triggers the email sync), and `on_disconnect() -> None`
  (delete this provider's domain data — WHOOP → fitness snapshots/workouts where
  `source='whoop'`, preserving manual; Google → `emails` where `source='google'`). The two
  hooks make connect/disconnect symmetric and domain-agnostic in the shared router.
- `FitnessProvider(OAuthProvider)`: adds `kind` + `fetch_recovery/sleep/workouts`
  (unchanged; `WhoopProvider` keeps working).
- `EmailProvider(OAuthProvider)`: adds `fetch_messages(since) -> list[NormalizedEmail]` and
  `get_message(source_id) -> str` (full body, on demand). `GoogleProvider` implements it.
- The **CSRF state store + connect/callback/disconnect/status endpoints** move out of
  `routers/fitness.py` into a shared, provider-registry-driven `routers/oauth.py`:
  `GET /api/oauth/connect/{provider}` → authorize URL; `GET /auth/{provider}/callback`
  (verify state → `exchange_code` → persist to `provider_accounts` → `provider.on_connected()`
  → redirect); `POST /api/oauth/disconnect/{provider}` (revoke best-effort → delete that
  provider's data); `GET /api/oauth/status`. `routers/fitness.py` keeps only its data
  endpoints (`/today`, `/workouts`, `/week`, `/sync`, manual workouts).
- The providers registry (`app/providers/__init__.py`) holds all OAuth providers; the fitness
  `pull_providers()` filter stays for the fitness sync. `provider_accounts` is unchanged
  (already provider-agnostic — Google tokens land there). The shared status
  (`GET /api/oauth/status`) returns generic per-provider connection state (not the
  fitness-specific `FitnessStatus`).
- **Frontend + M4 tests repoint** their connect/status/disconnect calls from `/api/fitness/*`
  to the shared `/api/oauth/*` (the fitness *data* calls — today/workouts/week/sync — are
  unchanged). This is part of the refactor and small; the moved M4 OAuth tests assert the
  shared endpoints, and the fitness `api.js` connect/status helpers point at `/api/oauth/*`.

## 3. Google OAuth specifics

- Scopes: `openid email profile https://www.googleapis.com/auth/gmail.readonly`.
- Authorization request includes `access_type=offline` + `prompt=consent` to guarantee a
  **refresh token**. Endpoints **[confirm-against-live]**: auth
  `https://accounts.google.com/o/oauth2/v2/auth`, token `https://oauth2.googleapis.com/token`,
  revoke `https://oauth2.googleapis.com/revoke`, Gmail base
  `https://gmail.googleapis.com/gmail/v1/users/me`.
- **User prereq:** a Google Cloud OAuth 2.0 **Web application** client (client_id + secret)
  with the redirect URI registered. Unlike WHOOP, **Google permits `http://localhost`
  redirect URIs**, so local validation likely needs no tunnel — register e.g.
  `http://localhost:8000/auth/google/callback`.
- `provider_user_id` = the Google `sub` (from the id_token or the userinfo/profile endpoint).

## 4. Gmail sync (`app/email_sync.py`)

Mirrors the M4 `fitness_sync` tick (background loop registered in the lifespan, gated by
`email_sync_enabled`; immediate run after connect via `on_connected`).

Each run, per connected Google account:
1. Load + refresh tokens via the shared OAuth layer (persist rotated tokens), inject into the
   provider.
2. `messages.list` over `INBOX` (`maxResults = email_backfill_count`, default 50); for each
   message id not already stored, `messages.get` (headers + `snippet` + a bounded plain-text
   **body excerpt ~2 KB** for triage).
3. Triage (§5) → category + summary.
4. Idempotent upsert into `emails` by `(owner, source, source_id)`; advance the sync cursor.
- Per-account errors are isolated and logged; the tick never crashes; `AuthError` flips the
  account to `needs_reauth`.
- Reads never depend on a live Gmail call for the inbox list (served from `emails`); only the
  message **body** is fetched live (`get_message`) for the reading pane, with a graceful
  fallback message if Gmail is unreachable.

## 5. Triage (`app/email_triage.py`)

- Uses the shared `app/llm.py` Claude client (Haiku tier), with a `configure(fake)` seam so
  tests run with no LLM/network.
- Input per message: subject + sender + snippet + the ~2 KB body excerpt.
- Output (structured / validated): `category ∈ {'needs_reply','fyi'}` + `summary` = a list of
  ≤3 short bullet strings. Stored on the row; a triage failure leaves `category`/`summary`
  null (message still shows as untriaged) and retries next sync.
- **Bodies transit (Gmail → server → Anthropic) but are never persisted.** Cost ≈ 1 Haiku
  call per synced message, cached on the row (re-triaged only if the message changes).

## 6. Data model — `emails` table (migration `0005_email`)

Provider-agnostic `source`/`source_id`, `owner` default `"me"`, matching M4 conventions.

| Field | Type | Notes |
| --- | --- | --- |
| `source` / `source_id` | str/str | `'google'` / Gmail message id; unique `(owner, source, source_id)` |
| `thread_id` | str | Gmail thread id |
| `from_name` / `from_email` | str/str | parsed sender |
| `subject` | str | |
| `snippet` | str | Gmail preview |
| `received_at` | datetime | sort key |
| `unread` | bool | |
| `category` | str, nullable | `'needs_reply'` \| `'fyi'` (triage) |
| `summary_json` | JSON, nullable | list of bullet strings (triage) |
| `triaged_at` | datetime, nullable | |
| `created_at` / `updated_at` | datetime | |

No `body` column (privacy — fetched on demand).

## 7. API surface (`app/routers/email.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/email/inbox` | Triaged messages grouped by category (+ `needs_reply` count) |
| `GET` | `/api/email/{id}` | Metadata + summary + **on-demand body** (live Gmail fetch) |
| `POST` | `/api/email/sync` | Trigger a sync run |

Connect/disconnect/status via the shared `/api/oauth/*`. Pydantic schemas: `EmailOut`
(list item, no body), `EmailDetail` (with body + summary), `Inbox` (grouped lists + counts).
Draft/send/archive endpoints are deferred.

## 8. Assistant tools (`app/tools.py`) — read-only this slice

`get_inbox` (triaged summary of what needs a reply), `get_email` (one message + summary +
body). No write/send tools this slice. Tool errors return `{"error": …}` (existing convention).

## 9. Frontend (`frontend/src/screens/EmailScreen.jsx`)

Rewrite from the hardcoded sample to live data, following the M3/M4 screens' data-loading
convention. Two-pane: inbox grouped **Needs reply / FYI** (with the "N need you" count) +
reading pane (from / subject / body / AI summary bullets). Connection states like the Fitness
screen (not-connected → "Connect Google" CTA via `/api/oauth/connect/google`; connected;
needs_reauth; syncing). The draft-tone tabs + send button from the sample are **omitted**
(a later slice) — no dead UI.

## 10. Config additions (`config.py`)

| Setting | Default |
| --- | --- |
| `google_client_id` / `google_client_secret` | `""` |
| `google_redirect_uri` | `http://localhost:8000/auth/google/callback` |
| `email_sync_enabled` | `True` |
| `email_sync_seconds` | `900` (15 min) |
| `email_backfill_count` | `50` |

Triage reuses the existing assistant model config (Haiku tier).

## 11. Testing

Suite must stay green (incl. the **entire M4 fitness suite** — the refactor's guardrail).
`configure(fake)` seams on `GoogleProvider` (fake Gmail JSON) and `email_triage` (fake LLM):
- OAuth refactor: the moved shared oauth endpoints behave as before for WHOOP; Google connect
  stores an account; fitness data endpoints still work.
- Gmail mapping (message JSON → `NormalizedEmail`), triage parse (category/summary), upsert
  idempotency, inbox grouping + count, on-demand body fetch, `needs_reauth` on auth failure.
- Optional manual `python -m app.smoke_google` (mirrors `smoke_whoop`), not in CI.

## 12. Privacy-policy update

Add the email domain to the policy (all three copies — canonical `docs/privacy-policy.md`,
corp-site `/privacy/`, the gist): Gmail accessed **read-only** via Google OAuth; message
content (subject + a bounded body excerpt) is sent to **Anthropic** for triage; message
**bodies are not stored** (fetched on demand); Google tokens are stored server-side and
deleted on disconnect. Add Google to the Section 3 provider table.

## 13. Confirm against live API during implementation

- Google auth/token/revoke endpoints + params (`access_type`, `prompt`), the id_token/`sub`
  for `provider_user_id`, the userinfo endpoint.
- Gmail `messages.list` (label/`q` filter, pagination) + `messages.get` (format for headers +
  snippet + body; base64url body decoding, plain-text part extraction).
- Exact scope strings.

## 14. Suggested implementation phasing

1. OAuth refactor: split the seam (`OAuthProvider`/`FitnessProvider`), extract the shared
   `routers/oauth.py` + move the M4 OAuth tests, wire `on_connected`. Fitness stays green.
2. Config + `GoogleProvider` OAuth (authorize/exchange/refresh/revoke + profile `sub`) against
   fixtures.
3. `emails` model + migration `0005` + store (upsert, inbox grouping, get-by-id).
4. `GoogleProvider` Gmail fetch (list/get + mapping) + `email_triage` + `email_sync` tick +
   lifespan wiring.
5. Read/write API (`routers/email.py`) + schemas + read-only assistant tools.
6. Frontend `EmailScreen` rewrite + connection states.
7. Privacy-policy update + optional `smoke_google` + live validation (Google localhost OAuth).
