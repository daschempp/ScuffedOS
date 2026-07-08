# Settings › Connectors — unified sign-in surface + packaged-app OAuth (M9)

**Date:** 2026-07-08 · **Status:** approved design (brainstormed with user)
**Branch:** `m9-connectors-design` off `m8-ship-tauri-slice2` (53cea3b — requires M8 slice-2's
Settings screen + secrets vault). **Execution prerequisite:** merge M8 to main first (one
combined M8 PR), then rebase/cut the real M9 branches from main — do not stack three deep
(the M7 stacked-PR lesson).

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
| Token storage | `provider_accounts` (single row, owner+provider; store.py:1411) | same | same (`access_token`, `expires_at` always None) | `finance_items`, **multi-row** per institution (models.py:555) |
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
`/?screen=email` lands on the backend root, not Vite — users navigate back by hand. §9 fixes this
for both modes.)

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
| **1 — Connectors tab** | All four sign-ins managed in Settings › Connectors; dev mechanics unchanged | M8 slice-2 merged |
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
  kind:        "oauth" | "token" | "link"
  configured:  bool                     # app creds present (vault→env seam); Moodle: always true
  status:      "not_connected" | "connected" | "needs_reauth"
  connected_at: datetime | None
  provider_user_id: str | None
  can_write_email: bool | None          # google only (existing derivation)
  items:       list[ConnectorItem]      # plaid only, else []

ConnectorItem:                          # one per linked institution
  item_id, institution_name, status ("connected" | "needs_reauth"), last_synced_at
```

Vocabulary mapping: `provider_accounts.status` passes through; `finance_items.status`
`'active'` → `'connected'`. Plaid's connector-level status derives from its items:
any `needs_reauth` → `needs_reauth`; else ≥1 item → `connected`; else `not_connected`.
`configured` reads the already-vault-resolved settings fields (`google_client_id != ""` etc.).
Tokens/secrets are **never** serialized (same rule as `_provider_account_dict`, store.py:423).

**No new action endpoints.** Connect/disconnect/reauth reuse the five existing flows verbatim.

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
    the same field with "paste a fresh key" copy. (Token acquisition help-text links the
    WolfWare Security-keys page, as SchoolScreen does today.)
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

Email/Fitness/School/Finance **delete** their connect CTAs, paste forms, link launchers, and
reauth re-connect forms (EmailScreen:208-219/:280-300, FitnessScreen:101-132/:152 disconnect
IconButton, SchoolScreen:73-146, FinanceScreen:103-145 + startLink/finishLink/reauth/disconnect
handlers). In their place:

- **Not connected** → one empty-state card: icon, "Not connected", one line of copy, and a
  "Set up in Settings › Connectors" button (`onOpenConnectors`).
- **needs_reauth** → one-line banner "Connection needs re-authorizing — fix in Settings ›
  Connectors" (deep-link). No inline re-auth UI.
- Connected behavior (data panels, Sync buttons) is untouched.

## 9. Slice 2 — packaged sign-in (Google + Plaid; signed-agnostic)

**Google — Desktop client + runtime loopback + PKCE:**

- User switches the GCP client type to **"Desktop app"** (new client id/secret pasted into the
  API keys tab). *Consequence:* refresh tokens minted under the old Web client die with the
  client_id change — a **one-time Google reconnect** after the switch; the Connectors tab makes
  this a visible, ordinary needs_reauth → Reconnect.
- The Tauri shell already passes `--port {n}` to the sidecar; it additionally exports
  `SCUFFEDOS_PORT={n}` when spawning. `config.py` gains `backend_port: int = 8000` (env-fed).
  `GoogleProvider.authorize_url`/`exchange_code` compute
  `redirect_uri = http://127.0.0.1:{settings.backend_port}/auth/google/callback` at request
  time — dev (uvicorn :8000) and packaged (random port) both just work, no registration.
  An explicitly set `google_redirect_uri` env still wins (back-compat escape hatch).
- **PKCE** (S256), recommended for native apps: the verifier is stored alongside the provider in
  the CSRF `_STATES` entry (oauth.py:30) — `_STATES[state] = (provider, verifier)` — and passed
  to `exchange_code`. Google-only; the other providers ignore it. `[confirm-against-live]`
  Desktop-client + PKCE token exchange shape.
- **System browser:** in packaged mode (`isTauri()`), Connect opens `authorize_url` via the
  official **opener plugin** (new capability) instead of navigating the webview; dev keeps
  `window.location`. Consent then happens in the user's real browser with their Google session.
- **Callback UX:** `/auth/{provider}/callback` stops 302-ing to a SPA path the backend can't
  serve; it returns a minimal inline-HTML **"✓ Connected — you can close this tab and return to
  ScuffedOS"** page (error variant shows the failure reason). Strict improvement in both modes
  (dev currently lands on a backend 404). The Connectors tab **polls** `GET /api/connectors`
  (~2s, bounded ~2min) from the moment Connect is clicked until status flips — the same UX
  pattern Plaid's finish-poll already set.

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
  (oauth.py:41-43) rejects anything the backend didn't just issue.
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

None. Slice 1 adds a response schema only. Slice 2 adds `backend_port` (a Settings field, not
a table) and extends the in-memory `_STATES` value. Slice 3 touches no backend data at all.

## 12. Error handling & security

- **Destructive disconnect** — inline confirm naming exactly what synced data is wiped (§7).
- **Vault locked** (`vault_ok:false`) — Connectors tab reachable with a warning strip; OAuth
  connect buttons disabled (creds unreadable); Moodle paste still works (DB, not vault).
- **CSRF `_STATES` is in-process** (oauth.py:30) — a sidecar restart mid-consent invalidates
  the flow; the callback error page says "start again from Settings › Connectors". Accepted
  (single-user local app); not persisted.
- **Callback failures** (denied consent, expired state, exchange error) — error variant of the
  callback page in both modes; the tab's poll times out back to an actionable "Connect failed —
  try again" state on the card.
- **Poll bounds** — status polling stops after ~2min or on tab/screen exit; no infinite loops.
- **Secrets never leave the backend** — `GET /api/connectors` carries no tokens; masked
  presence stays the API-keys-tab contract (`GET /api/settings/secrets`).
- Single-user posture unchanged: loopback bind, no sessions (documented, not "fixed" here).

## 13. Testing

Through the existing seams — registry `providers.configure([fakes])`, `no_external_services`
autouse fixture, TestClient; zero network.

- **Slice 1 (backend):** GET /api/connectors returns all four with `not_connected` on an empty
  DB; connected/needs_reauth projection per provider; Plaid items nested + connector-level
  derivation (active→connected mapping); `configured` flips with fake vault/env creds; Moodle
  always configured; no token material in any response. Frontend: `npm run build` green;
  SettingsScreen tab behavior (vault-locked keeps Connectors reachable) unit-tested if a
  component-test seam exists, else covered by the screens' empty-state render paths.
- **Slice 2:** unit tests assert the runtime redirect_uri embeds `settings.backend_port`;
  PKCE verifier round-trip through `_STATES` and into the (fake-transport) exchange body;
  callback returns the success/error HTML page (no more 302-to-SPA); explicit
  `google_redirect_uri` override still wins.
- **Slice 3:** bounce page is static (visual check + a tiny query-forwarding JS unit if the
  corp repo has any harness); deep-link handler logic unit-tested at the Rust seam where
  practical; the end-to-end is a **manual GUI gate** on the signed bundle (deep links cannot
  fire in dev — verified).
- **Suite baseline:** 670 passed / 1 skipped / 1 failed at 53cea3b — the failure is the
  pre-existing `test_moodle_deadlines_days_ahead_horizon_filter` time-bomb (hardcodes
  now=2026-07-03; also fails on main; fix belongs on main, not this branch). Each slice must
  not regress the passing set; report counts per house rule.

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

## 15. Risks

| Risk | Mitigation |
|---|---|
| Notarizing a bundle embedding Python + Postgres (hundreds of Mach-Os) | Known-shipped shape (Postgres.app); sign everything + hardened-runtime entitlements; `[confirm-against-live]` gate |
| Google Desktop-client switch invalidates stored tokens | Surfaced as ordinary needs_reauth → one-click Reconnect in the tab |
| Deep link hijack (another app claims `scuffedos://`) | One-time CSRF state check rejects forged callbacks; scheme collision is theoretical on a personal machine |
| SettingsScreen restructure regresses M8 slice-2 UX (first-run nudge, vault re-auth) | Both early-return states become API-keys-tab states with tests; Connectors tab explicitly tested under vault_ok:false |
| Plaid hosted-link tab in packaged app | opener plugin (system browser) — same fix as Google consent |

## 16. Acceptance criteria

- **Slice 1:** From a fresh DB in dev, all four connectors appear in Settings › Connectors as
  Not connected; each can be connected, re-authed, and disconnected (with the destructive
  confirm) entirely from the tab; the four data screens show empty states that deep-link;
  no data-screen connect UI remains; suite green (minus the pre-existing moodle time-bomb);
  build green.
- **Slice 2:** In the packaged .app — Google connects end-to-end via system browser +
  loopback callback + poll; Plaid links via system browser + finish-poll; Moodle pastes;
  callback page renders in both modes.
- **Slice 3:** The signed, notarized .app launches with no Gatekeeper bypass; WHOOP connects
  end-to-end via bounce page → deep link → callback; live round-trip confirmed.
