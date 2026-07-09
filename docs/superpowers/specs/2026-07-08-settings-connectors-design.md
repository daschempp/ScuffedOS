# Settings › Connectors — unified sign-in surface + packaged-app OAuth (M9)

**Date:** 2026-07-08 · **Status:** approved design (brainstormed with user; 4-lens adversarial
spec review applied — 21 confirmed findings folded in)
**Branch:** `m9-connectors-design` off `m8-ship-tauri-slice2` (requires M8 slice-2's Settings
screen + secrets vault). **Execution prerequisite:** M8 merged to main first (PR #11), then
rebase this branch onto main — do not stack three deep (the M7 stacked-PR lesson).

---

## 1. Goal

Every account sign-in — **Gmail/Google, WHOOP, Moodle, Plaid** — is authorized, re-authorized,
and disconnected from **one surface: Settings › Connectors**. The four data screens
(Email/Fitness/School/Finance) stop owning connect UI. And, because the user chose the full
scope: sign-in must work **from the packaged .app**, not just dev — including WHOOP — under a
**signed + notarized** app assumption (user will enroll in the Apple Developer Program).

## 2. User-approved forks

1. **Full scope** — consolidation *plus* packaged-app OAuth for all four connectors (not UI-only).
2. **Signed assumption** — design against a Developer ID-signed, notarized .app. This turns the
   WHOOP fix from hosted relay infrastructure into a **static bounce page + `scuffedos://` deep
   link**, and removes the Gatekeeper right-click-Open dance. (Supersedes M8's "unsigned
   daily-driver" premise; the M8 machine-bound vault stays — see §14 out-of-scope.)
3. **Three slices**, each independently shippable (§5).
4. **Full move, not mirror** — data screens lose their connect CTAs/forms entirely; they render
   a calm "Not connected — set up in Settings › Connectors" empty state that deep-links. One
   source of truth; deletes four duplicated connection state machines.

## 3. Current state (verified against the tree at 53cea3b)

| | Gmail/Google | WHOOP | Moodle | Plaid |
|---|---|---|---|---|
| Auth kind | OAuth redirect | OAuth redirect | wstoken paste | Hosted Link + poll |
| Connect | `GET /api/oauth/connect/google` (oauth.py:54) → same-window redirect → `GET /auth/google/callback` (oauth.py:70) | same shared plumbing; WHOOP owns zero endpoints | `POST /api/moodle/connect` (moodle.py:32), validates live, 502 on bad token | `POST /api/finance/link/start` (finance.py:29) → new tab → `POST /api/finance/link/complete` polls, 409 until done (finance.py:45) |
| Status | `GET /api/oauth/status` (oauth.py:64) | same | same (`_status_dict`, oauth.py:46) | own `GET /api/finance/status` (finance.py:72) |
| Disconnect | `POST /api/oauth/disconnect/google` (oauth.py:99) — **no UI today** | same, buried IconButton (FitnessScreen.jsx:152) | same — **no UI today** | per-item `POST /api/finance/items/{id}/disconnect` (finance.py:131) |
| Reauth | re-run connect | re-run connect | re-paste token | update-mode `…/reauth/start` + `…/reauth/complete` (finance.py:147/167) |
| Token storage | `provider_accounts` (single row, owner+provider; store.py:1411) | same | same (`access_token`, `expires_at` always None) | `finance_items`, **multi-row** per institution |
| App creds | GOOGLE_CLIENT_ID/SECRET in vault (SECRET_FIELD_MAP, config.py:149) | WHOOP_CLIENT_ID/SECRET in vault | **none** — the pasted token IS the credential | PLAID_CLIENT_ID/SECRET in vault |
| Connect UI today | EmailScreen.jsx:93/:208/:280 | FitnessScreen.jsx:56/:101/:123 | SchoolScreen.jsx:58/:73/:120 | FinanceScreen.jsx:49-79/:103/:126/:136 |

Shared seams a Connectors surface builds on:

- **Provider registry** `backend/app/providers/__init__.py` — `_build_real()` (:27-51) constructs
  exactly the four; `all_providers()` (:55) / `get(name)` (:62) are the only enumeration seams.
  The catalog comes from the registry, never the store (which only holds *connected* rows).
- **Shared OAuth router** already unifies Google/WHOOP/Moodle at the status/disconnect layer.
- **Settings secrets backend** — `_INTEGRATIONS` (routers/settings.py:27, ids anthropic/openai/
  usda/whoop/google/plaid) + `SECRET_FIELD_MAP` (config.py:149, 9 fields) + `GET/PUT
  /api/settings/secrets`. The natural join between "creds that make OAuth possible" and "the
  connect action that consumes them".
- **Frontend transport** `frontend/src/lib/api.js` — `oauthStatus/oauthConnect/oauthDisconnect`
  (:176-178), `moodleConnect` (:223), `finance*` (:229-252), `settingsGetSecrets/PutSecrets`
  (:265+). Helpers stay; only callers relocate.

## 4. Why packaged-app OAuth is broken today

1. The Tauri shell binds a **random loopback port each launch** (src-tauri/src/lib.rs:16-20
   `free_port()`), but `google_redirect_uri` is hardcoded `http://localhost:8000/auth/google/callback`
   (config.py:88) and `whoop_redirect_uri` is the public corp URL (config.py:75). OAuth requires
   the redirect URI to exactly match a pre-registered value — nothing listens where they point.
2. Connect navigates the **webview itself** (`window.location = authorize_url`, EmailScreen.jsx:95);
   after consent the redirect lands on a port with nothing listening (backend serves no SPA —
   no StaticFiles in main.py).

Dev works only because uvicorn happens to run on :8000. (Even in dev, the post-consent bounce to
`/?screen=email` lands on the backend root, not Vite — users navigate back by hand. §6a fixes
this for both modes, in slice 1.)

**Externally verified facts the design rests on** (2026-07-08):

- Google **"Desktop app"** OAuth clients support loopback redirects `http://127.0.0.1:{port}/…`
  with **any ephemeral port chosen at request time — no port registration** (Google native-app
  OAuth docs; RFC 8252 §7.3). The random-port design needs no change for Google.
- The official **Tauri v2 deep-link plugin** registers custom schemes via Info.plist **at build
  time**; on macOS deep links fire **only from a bundled .app installed in /Applications** (no
  dev-mode). Fine: it is only needed for packaged WHOOP.
- WHOOP's dashboard **rejects localhost** redirect URIs (project memory, M4 live gate) — it
  requires a public https URL. `https://scuffedcorporation.com/auth/whoop/callback` is already
  the registered URI and the config default.

## 5. Slice map

| Slice | Delivers | Depends on |
|---|---|---|
| **1 — Connectors tab** | All four sign-ins managed in Settings › Connectors; callback success/error page (§6a); dev mechanics otherwise unchanged | M8 merged (PR #11) |
| **2 — Packaged sign-in** | Google + Plaid connect from the shipped .app (Moodle already does); works unsigned too | slice 1 |
| **3 — Sign + WHOOP** | Developer ID signing + notarization; `scuffedos://` deep link; static bounce page; WHOOP connects packaged | slice 2 + user's Apple enrollment |

## 6. Slice 1 — backend: `GET /api/connectors` (pure read-time projection)

New router `backend/app/routers/connectors.py`, mounted in main.py. **No new tables, no
migration — alembic head stays 0009.** The endpoint is a left-join over existing state:

- Iterate `providers.all_providers()` (always four, even with nothing connected).
- Attach the `provider_accounts` row (Google/WHOOP/Moodle) via `store.list_provider_accounts()`
  and the `finance_items` rows (Plaid) via the store's finance item reads.
- No row → `not_connected`. Existing `ProviderStatus` (schemas.py:390) **cannot** express this
  (non-optional `connected_at` would 500) — hence a new schema, not a reuse.

Response shape (new Pydantic schemas in schemas.py):

```
ConnectorInfo:
  name:        "google" | "whoop" | "moodle" | "plaid"
  label:       str                      # human name, e.g. "Google / Gmail"
  auth_kind:   "oauth" | "token" | "link"
  configured:  bool                     # app creds present (vault→env seam); Moodle: always true
  status:      "not_connected" | "connected" | "needs_reauth"
  connected_at: datetime | None
  provider_user_id: str | None
  can_write_email: bool | None          # google only (existing derivation)
  items:       list[ConnectorItem]      # plaid only, else []

ConnectorItem:                          # one per linked institution
  item_id, institution_name, status ("connected" | "needs_reauth"), last_sync_at
```

- `label` and `auth_kind` come from a **static name-keyed dict inside routers/connectors.py**
  (mirroring `_INTEGRATIONS` in routers/settings.py:27) — *not* from provider attributes
  (`WhoopProvider.kind` already exists and means something else; hence `auth_kind`, not `kind`).
- `last_sync_at` matches the codebase-wide naming. Connector-level last-sync is deliberately
  omitted from the card model (per-item only, where Plaid already tracks it).
- Vocabulary mapping: `provider_accounts.status` passes through; `finance_items.status`
  `'active'` → `'connected'`. Plaid's connector-level status derives from its items:
  any `needs_reauth` → `needs_reauth`; else ≥1 item → `connected`; else `not_connected`.
- `configured` reads the already-vault-resolved settings fields (`google_client_id != ""` etc.).
- Tokens/secrets are **never** serialized (same rule as `_provider_account_dict`, store.py:423).

**No new action endpoints.** Connect/disconnect/reauth reuse the five existing flows verbatim.

### 6a. Slice 1 — callback page (replaces the dead 302)

`GET /auth/{provider}/callback` (oauth.py:70) stops 302-ing to a SPA path the backend cannot
serve. Signature becomes `code: str | None = None, error: str | None = None, state: str = …`;
it returns minimal inline HTML:

- **Success** — "✓ Connected — you can close this tab and return to ScuffedOS."
- **Error** — rendered when `error` is present (e.g. Google's `access_denied` redirect carries
  `error` and **no `code`** — today's required `code` param would 422 before our code runs) or
  `code` is missing or the state/exchange fails; shows the reason and "start again from
  Settings › Connectors". The one-time state is still consumed/validated on every path.

Consequence: `success_redirect()` is **deleted** from the `OAuthProvider` protocol and all
implementations (google.py:302, whoop.py:170, the moodle provider) and fakes, along with its
string-assert tests. Nothing else consumes it (verified: no frontend `?connected=` handling
survives §8). This is a strict improvement in dev too (today's bounce lands on a backend 404).

## 7. Slice 1 — frontend: Settings becomes tabbed **Connectors | API keys**

**SettingsScreen restructure.** Today it is flat with two full-component early returns —
vault-locked banner (:56-76) and first-run nudge (:79-105) — before the main render (:107).
The tab bar hoists **above** both; the early returns demote into the **API keys** tab body.
Otherwise the Connectors tab would be unreachable whenever the vault is locked or empty.
When `vault_ok === false`, the Connectors tab still renders (connections live in the DB, not
the vault) with a warning strip: OAuth connects need creds the vault can't currently serve.

- **API keys tab** = the existing secrets UI, content unchanged (all six `_INTEGRATIONS`
  including the non-connector Anthropic/OpenAI/USDA keys).
- **Connectors tab** = one card per connector from `GET /api/connectors`, ordered
  google/whoop/moodle/plaid. Each card: label, status chip
  (Connected · Needs re-auth · Not connected), `connected_at`/account hint when present, and
  modality-specific actions:
  - **Google / WHOOP** — Connect (or Reconnect on needs_reauth) → `api.oauthConnect(name)` →
    navigate to `authorize_url` (dev mechanics in slice 1; slice 2 swaps the transport).
    Google's card keeps the "Enable email actions" scope-upgrade affordance (can_write_email).
  - **Moodle** — inline paste-token field + Connect → `api.moodleConnect`; needs_reauth shows
    the same field with "paste a fresh key" copy. The card reproduces SchoolScreen's existing
    step-by-step help copy for obtaining the wstoken (no external link — none exists today).
  - **Plaid** — "Link bank account" / "Link investment account" buttons (`link/start` →
    open tab → "Finish linking" poll, the existing 409 loop) + one sub-row per institution
    with its own status chip, Reconnect (update-mode reauth pair) and Disconnect.
- **Disconnect is destructive and must say so.** `on_disconnect` hooks wipe synced domain data
  (emails / moodle_* / fitness / that item's finance rows). Clicking Disconnect flips the card
  into an inline confirm — "This deletes all synced <emails|grades…|workouts|transactions for
  this account> from ScuffedOS. Disconnect / Cancel" — no new modal system.
- **Not configured gating** — if `configured === false`, Connect is disabled with
  "Add API keys first →" switching to the API keys tab. (Moodle is exempt: always configured.)

**Navigation.** App.jsx lifts a `settingsTab` state (`'connectors' | 'keys'`, default
`'connectors'`) passed to `<SettingsScreen/>` (App.jsx:126); Sidebar's Settings button
(shell/Sidebar.jsx:53) keeps navigating to `settings`. The four data screens receive an
`onOpenConnectors()` callback that sets `screen='settings'` + `settingsTab='connectors'`.

## 8. Slice 1 — the four data screens slim down

Each screen keys its empty/needs_reauth state on **its own provider's entry** (its connector in
`GET /api/connectors`, or its `provider === '<name>'` row in the oauth status) — **never** the
aggregate `connected` flag. FitnessScreen.jsx:50 keys on the aggregate today and must change.

What is deleted vs preserved, per screen (ranges are the connect-UI blocks only; connected-mode
data panels, Sync buttons, and derivation code between the cited blocks stay):

- **EmailScreen** — delete the not-connected CTA card (:208-219) and the needs_reauth +
  enable-write banners (:280-300) plus `connect()` (:93). Add: (a) the empty-state card,
  (b) the one-line needs_reauth deep-link banner, (c) a third state — when connected and
  `can_write_email === false`, a one-line "Email actions are read-only — enable in Settings ›
  Connectors" banner (`onOpenConnectors`), replacing today's in-context upgrade pointer.
- **FitnessScreen** — delete the not-connected CTA (:101-112), the needs_reauth banner
  (:123-132), and the disconnect IconButton (:152) + `connect()/disconnect()` handlers
  (:56-64). Preserve the vitals/rings derivation between those blocks (:114-119).
- **SchoolScreen** — delete the paste-key form (:73-105) and the double reauth cards
  (:120-146) + `connect()` (:58).
- **FinanceScreen** — delete the not-connected connect card (:103-116), the per-item
  Reconnect/Disconnect chips (:126-127), the pendingLink/finish card + needs_reauth
  inline-reauth (:135-145), and the `startLink/reauth/finishLink/disconnect` handlers
  (:49-79 minus `sync()`). **Preserve** `sync()` and the Sync button (:130-133) — the
  connected view keeps its refresh affordance; per-institution management moves to the tab.

In place of each deleted block:

- **Not connected** → one empty-state card: icon, "Not connected", one line of copy, and a
  "Set up in Settings › Connectors" button (`onOpenConnectors`).
- **needs_reauth** → one-line banner "Connection needs re-authorizing — fix in Settings ›
  Connectors" (deep-link). No inline re-auth UI.

## 9. Slice 2 — packaged sign-in (Google + Plaid; signed-agnostic)

**Google — Desktop client + runtime loopback + PKCE:**

- User switches the GCP client type to **"Desktop app"** (new client id/secret pasted into the
  API keys tab). *Consequence:* refresh tokens minted under the old Web client die with the
  client_id change — a **one-time Google reconnect** after the switch; the Connectors tab makes
  this a visible, ordinary needs_reauth → Reconnect.
- **Port plumbing (exact pairing — a name mismatch here ships a dead flow):** the Tauri shell
  already passes `--port {n}` and sets sidecar env via `.env()` (lib.rs:207-209); it
  additionally exports **`SCUFFEDOS_PORT={n}`**. `config.py` gains
  **`scuffedos_port: int = 8000`** — the field name matches the env var under pydantic's
  default name↔env binding (`SettingsConfigDict` has no `env_prefix`/aliases, config.py:12;
  the `scuffedos_managed_pg` ↔ `SCUFFEDOS_MANAGED_PG` precedent). Do **not** name it
  `backend_port` — that would silently bind to `BACKEND_PORT` and never see the value.
  §13 tests construct `Settings` from an env dict containing `SCUFFEDOS_PORT`.
- **Redirect URI:** `google_redirect_uri` default changes to `""`; when empty, GoogleProvider
  computes `http://127.0.0.1:{settings.scuffedos_port}/auth/google/callback` at request time —
  dev (uvicorn :8000) and packaged (random port) both just work, no registration. A non-empty
  env value wins verbatim (defined override semantics; update the default-assert in
  test_email_config.py:12).
- **PKCE (S256), both legs specified:** the oauth router owns the flow — at connect time it
  generates the verifier, derives the S256 challenge, stores
  `_STATES[state] = (provider, verifier)` (value type changes str → tuple; update the
  `_STATES.get(state) == "whoop"` assertion, test_oauth.py:41), and calls
  `authorize_url(state, code_challenge=None)` — a **new optional protocol param**
  (base.py:174): Google appends `code_challenge` + `code_challenge_method=S256`; the others
  ignore it. At callback time the verifier rides into
  `exchange_code(code, verifier: str | None = None)` — a **coordinated protocol-signature
  change** (base.py:175) across google.py:231, whoop.py:116, moodle.py:402, the three
  fakes.py providers (:129/:373/:462) and the four inline test fakes
  (test_provider_registry.py:13/:26, test_providers_base.py:69, test_moodle_provider.py:88,
  test_fitness_sync.py:33). Only Google *uses* the verifier; every signature must accept it.
  `[confirm-against-live]` Desktop-client + PKCE token exchange shape.
- **System browser:** in packaged mode (`isTauri()`), Connect opens `authorize_url` via the
  official **opener plugin** (new capability) instead of navigating the webview; dev keeps
  `window.location`. Consent then happens in the user's real browser with their Google session.
- **Polling:** from the moment Connect is clicked the Connectors tab polls
  `GET /api/connectors` (~2s, bounded ~2min), stopping when the connector's
  **(status, can_write_email, connected_at) tuple changes from its pre-click snapshot** — not
  "until status flips", which never fires for the scope-upgrade reconnect (status stays
  `connected`; only `can_write_email` moves).

**Plaid:** the hosted-link tab opens via the opener plugin under `isTauri()` (webview
`window.open` is unreliable in packaged Tauri); the `link/complete` 409-poll is unchanged.

**Moodle:** already works packaged (paste-token, no redirect).

**WHOOP in slice 2:** card renders, but Connect shows "requires the signed build (slice 3)" in
packaged mode; dev connect (tunnel redirect URI) still works as today.

## 10. Slice 3 — signing, deep link, WHOOP bounce page

**Prerequisite (user):** Apple Developer Program enrollment ($99/yr) + a Developer ID
Application certificate in the login keychain.

- **build-app.sh signing stage:** codesign every nested Mach-O — the vendored Python tree
  (bin/python3 + all .so/.dylib), Postgres binaries, launcher, sidecar — then the bundle, with
  `--options runtime` (hardened) + entitlements Python needs (`allow-jit`,
  `allow-unsigned-executable-memory`, `disable-library-validation`); then
  `notarytool submit --wait` + `stapler staple`. Precedent: Postgres.app ships exactly this
  shape. `[confirm-against-live]` exact entitlement set (trim to what the bundle actually
  needs once notarization output is in hand).
- **Deep link:** official Tauri v2 deep-link plugin, scheme `scuffedos` (Info.plist at build
  time). The Rust handler parses `scuffedos://oauth/callback?provider=whoop&code=…&state=…`
  and forwards the query to `http://127.0.0.1:{port}/auth/{provider}/callback` via the existing
  reqwest dependency; the Connectors tab's poll picks up the flip. Deep links are
  attacker-invokable by any local page — safe here because the one-time CSRF state check
  (consume oauth.py:41-43, reject oauth.py:80-82) rejects anything the backend didn't just
  issue.
- **Bounce page:** a **static** HTML page published at
  `https://scuffedcorporation.com/auth/whoop/callback` (already the registered WHOOP redirect
  URI and the config default) that JS-forwards its query string to
  `scuffedos://oauth/callback?provider=whoop&…` plus a manual "Open ScuffedOS" link as
  fallback. No server logic, no secrets, nothing to maintain. Lives in the
  `scuffed-corporation` repo; published like the privacy page (its own wave/commit).
  `[confirm-against-live]` WHOOP → bounce → deep-link round trip on the signed build.
- **Dev caveat:** macOS fires deep links only for the bundled installed app, so dev WHOOP
  testing keeps the tunnel-redirect approach (override `whoop_redirect_uri` in .env, as in M4).

## 11. Data model & migrations

None. Slice 1 adds a response schema and the callback-page rework only. Slice 2 adds
`scuffedos_port` (a Settings field, not a table), the two protocol-signature extensions
(§9 PKCE), and the `_STATES` tuple value. Slice 3 touches no backend data at all.

## 12. Error handling & security

- **Destructive disconnect** — inline confirm naming exactly what synced data is wiped (§7).
- **Vault locked** (`vault_ok:false`) — Connectors tab reachable with a warning strip; OAuth
  connect buttons disabled (creds unreadable); Moodle paste still works (DB, not vault).
- **CSRF `_STATES` is in-process** (oauth.py:30; consume :41-43, reject :80-82) — a sidecar
  restart mid-consent invalidates the flow; the callback error page says "start again from
  Settings › Connectors". Accepted (single-user local app); not persisted.
- **Callback failures** (denied consent → `error` param with no `code`; expired state;
  exchange error) — the §6a error page in both modes; the tab's poll times out back to an
  actionable "Connect failed — try again" state on the card.
- **Poll bounds** — stops on the §9 tuple-change condition, after ~2min, or on tab/screen
  exit; no infinite loops.
- **Secrets never leave the backend** — `GET /api/connectors` carries no tokens; masked
  presence stays the API-keys-tab contract (`GET /api/settings/secrets`).
- Single-user posture unchanged: loopback bind, no sessions (documented, not "fixed" here).

## 13. Testing

Through the existing seams — registry `providers.configure([fakes])`, `no_external_services`
autouse fixture, TestClient; zero network.

- **Slice 1 (backend):** GET /api/connectors returns all four with `not_connected` on an empty
  DB; connected/needs_reauth projection per provider; Plaid items nested + connector-level
  derivation (active→connected mapping); `configured` flips with fake vault/env creds; Moodle
  always configured; no token material in any response. Callback page: success HTML on a valid
  code+state; error HTML on `error=access_denied` with no `code` (must not 422), on a missing
  code, and on an invalid state; `success_redirect` removal (protocol + impls + fakes + its
  string tests deleted).
- **Slice 1 (frontend):** `npm run build` green. There is **no frontend test harness** — the
  SettingsScreen restructure is verified by a **manual checklist** instead: vault-locked →
  Connectors tab still reachable with the warning strip; first-run nudge renders inside the
  API-keys tab; the M8 "Add keys" expand (53cea3b) still works; each data screen shows its
  empty state off its own provider entry.
- **Slice 2:** `Settings` constructed from an env dict containing `SCUFFEDOS_PORT` binds
  `scuffedos_port`; empty `google_redirect_uri` computes the loopback URI embedding
  `scuffedos_port`, a non-empty value wins verbatim; `authorize_url(state, code_challenge=…)`
  carries the challenge derived from the stored verifier; the verifier round-trips through
  `_STATES` into the (fake-transport) exchange body; all provider/fake `exchange_code`
  signatures accept the optional verifier; test_oauth.py:41 updated for the tuple.
- **Slice 3:** bounce page is static (visual check + a tiny query-forwarding JS unit if the
  corp repo has any harness); deep-link handler logic unit-tested at the Rust seam where
  practical; the end-to-end is a **manual GUI gate** on the signed bundle (deep links cannot
  fire in dev — verified).
- **Suite baseline:** 671 passed / 1 skipped on `m8-ship-tauri-slice2` after the time-bomb fix
  (f35733e). Each slice must keep the suite green; report counts per house rule.

## 14. Out of scope

- **Keychain migration of the vault key** — signing makes it viable; the machine-bound vault
  works as-is. Revisit later if desired.
- **Universal links** (https URLs opening the app) — possible once signed, but unreliable for
  OAuth redirect chains; the bounce page is the dependable pattern.
- **Making `moodle_base_url` / `plaid_env` / `plaid_country_codes` user-configurable** — they
  stay env-only; no persistence surface for non-secret config in this milestone (YAGNI).
- **Multi-user auth / sessions** — single-user loopback posture unchanged.
- **New sync behavior** — connect/disconnect semantics (immediate backfill, data wipe) are
  reused, not redesigned.
- **A frontend test harness** — deliberately not introduced for this milestone (§13 manual
  checklist instead).

## 15. Risks

| Risk | Mitigation |
|---|---|
| Notarizing a bundle embedding Python + Postgres (hundreds of Mach-Os) | Known-shipped shape (Postgres.app); sign everything + hardened-runtime entitlements; `[confirm-against-live]` gate |
| Google Desktop-client switch invalidates stored tokens | Surfaced as ordinary needs_reauth → one-click Reconnect in the tab |
| Deep link hijack (another app claims `scuffedos://`) | One-time CSRF state check rejects forged callbacks; scheme collision is theoretical on a personal machine |
| SettingsScreen restructure regresses M8 slice-2 UX (first-run nudge, vault re-auth) | Both early-return states become API-keys-tab states; §13 manual checklist covers vault-locked reachability, nudge placement, and the M8 Add-keys expand |
| PKCE protocol change misses a fake → suite breaks late | §9 enumerates every impl + fake + assertion that must change; §13 tests the signatures |
| Plaid hosted-link tab in packaged app | opener plugin (system browser) — same fix as Google consent |

## 16. Acceptance criteria

- **Slice 1:** From a fresh DB in dev, all four connectors appear in Settings › Connectors as
  Not connected; each can be connected (post-consent landing = the §6a page, then return to
  the app), re-authed, and disconnected (with the destructive confirm) entirely from the tab;
  the four data screens show empty states keyed on their own provider; no data-screen connect
  UI remains; suite green; build green.
- **Slice 2:** In the packaged .app — Google connects end-to-end via system browser +
  loopback callback + poll; Plaid links via system browser + finish-poll; Moodle pastes;
  `scuffedos_port` provably reaches the redirect URI (test + live).
- **Slice 3:** The signed, notarized .app launches with no Gatekeeper bypass; WHOOP connects
  end-to-end via bounce page → deep link → callback; live round-trip confirmed.
