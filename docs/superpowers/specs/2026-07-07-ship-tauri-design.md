# M8 — Ship / Tauri (design)

> Milestone: **M8** · Roadmap: Fitness M4 · Email M5 · School M6 · Finance/Plaid M7 · **Ship/Tauri M8**
> (renumber user-approved 2026-07-03). Effective 2026-07-07.
>
> **Scope (user-approved):** package ScuffedOS as a **personal daily-driver macOS app** — a
> double-clickable `ScuffedOS.app` for the single local user. **No** Apple code-signing,
> notarization, DMG/auto-update, cross-platform, or PyInstaller freeze.
>
> **Prerequisite:** the **M7 Plaid finance stack merges to `main`** (and passes its live PROD
> gate) *before* M8 implementation begins. This spec + the plan proceed now; the
> `m8-ship-tauri` branch is cut from post-M7 `main` so the first shipped `.app` includes finance.
>
> **Supersedes:** the stale "Tauri bundle lands in **M7**" notes in `docs/backend-overview.md`
> (§"How it should function") and `backend/app/reminders.py` (module docstring) — both predate
> the 2026-07-03 renumber and must be corrected to **M8** as part of this milestone.

This design is grounded in a de-risking research pass (2026-07-07) that validated the four
load-bearing technical assumptions against current tooling; the concrete tool/version picks
below come from it. **All four are feasible for an unsigned app; none is a hard blocker.**

---

## 1. Goals & non-goals

**Goals**

- One **double-clickable `ScuffedOS.app`** that launches the full dashboard with **no terminal**:
  frontend + the FastAPI backend + a local database, all managed by the app.
- **Self-contained & offline-capable** first run: the Python runtime, the app's dependencies,
  and a local Postgres (with pgvector for Mem0) all ship *inside* the bundle — nothing is
  downloaded at runtime.
- **Data persists** across restarts under `~/Library/Application Support/ScuffedOS/`.
- **In-app Settings** to enter/manage API keys and OAuth credentials (no editing files).
- **Zero data-layer migration**: the existing Postgres + Mem0/pgvector code is reused unchanged;
  the app just *provides* the Postgres it already expects.

**Non-goals (explicit)**

- No Apple Developer ID signing, notarization, Gatekeeper-clean install, DMG, or auto-update.
- No Windows/Linux builds.
- No PyInstaller/Nuitka single-binary freeze of the backend.
- No new product features. M8 is **packaging + a Settings surface only.**
- No rewrite of the store to SQLite / no swap of Mem0's vector backend.
- **Apple-Silicon (arm64) only.** The vendored Postgres + Python binaries are arm64; the `.app`
  will not run on an Intel Mac. (Accepted 2026-07-07 — the target machine is Apple Silicon.)
- **No macOS CI build job in M8.** The `.app` is built by a **local** script; a CI build job is a
  deferred later add (§8).

---

## 2. Ratified decisions (the five forks)

| # | Fork | Decision |
| --- | --- | --- |
| 1 | Ship scope | **Personal daily-driver, macOS (arm64), unsigned.** |
| 2 | Backend runtime | **Tauri sidecar, managed Python env** (vendored relocatable CPython, no freeze). |
| 3 | Data layer | **App-managed local Postgres** (vendored PG17 + pgvector; the **Python sidecar owns its lifecycle**). |
| 4 | Secrets/config | **In-app Settings screen** (UX as chosen) backed by a **machine-bound AES-256-GCM encrypted vault** — *not* raw Keychain (see §7); slice 2 also wraps the single vault key in one Keychain item (OS-managed at-rest). |
| 5 | Sequencing | **Merge M7 first, then branch** `m8-ship-tauri` from the complete `main`. |

---

## 3. Runtime topology

Tauri owns exactly one child — the Python sidecar — and the sidecar owns its own datastore.
The Rust shell stays thin.

```
ScuffedOS.app   (double-click; unsigned → one-time right-click▸Open on first launch)
│
├─ Contents/MacOS/ScuffedOS         Tauri shell (Rust + system WKWebView)
│    ├─ loads the built frontend (Contents/Resources/dist/) — no Vite dev server
│    ├─ picks a free 127.0.0.1 port, spawns the sidecar launcher, streams its stdout
│    ├─ keeps the main window HIDDEN until GET /health is 200 (with a timeout → error window)
│    └─ on exit: SIGTERM the sidecar; backstop process-tree kill (sysinfo)
│
├─ Contents/Resources/py/           vendored CPython 3.14 + true-installed deps (offline)
├─ Contents/Resources/pgsql/        vendored PostgreSQL 17 + pgvector (relocatable, ad-hoc signed)
├─ Contents/Resources/backend/      the FastAPI app source (app/, alembic/, migrations)
└─ Contents/MacOS/scuffedos-backend-aarch64-apple-darwin   tiny launcher stub (the externalBin)
        └─ exec Resources/py/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port <p>
              └─ boots local Postgres: (first run) initdb → (every run) pg_ctl start → alembic upgrade head
                    … serves FastAPI …
              └─ on SIGTERM/atexit: pg_ctl stop -m fast   ← load-bearing: reaps the grandchild
```

**Per-user state** lives under `~/Library/Application Support/ScuffedOS/`:

```
ScuffedOS/
├─ pgsql/            extracted Postgres tree (copied from Resources on first run)
├─ pgdata/           the initdb data directory (the actual database)
├─ run/              Unix domain socket dir for Postgres (avoids the macOS firewall prompt)
├─ logs/             pg.log, backend.log
├─ data/             existing backend/data/ artifacts: task attachments + Mem0 history file
├─ secrets.enc       AES-256-GCM encrypted secrets vault (API keys + OAuth tokens)
├─ vault.salt        per-install random salt for key derivation (non-secret)
└─ config.json       non-secret app config (chosen port persistence, prefs)
```

---

## 4. Components

### 4.1 Tauri shell (`src-tauri/`) — new

- Tauri **v2** project (Rust ≥ 1.77.2) with `tauri-plugin-shell` v2. New toolchain dependency:
  **Rust must be installed** on the build machine (not currently present) and added to CI.
- `tauri.conf.json`:
  - `bundle.resources`: `py/**/*`, `pgsql/**/*`, `backend/**/*`, and the built `dist/**/*`.
  - `bundle.externalBin`: `binaries/scuffedos-backend` (the launcher stub). The shipped file
    **must** carry the `-aarch64-apple-darwin` target-triple suffix (Tauri strips it at bundle time).
  - main window declared `"visible": false` (shown only after the health gate passes).
- `capabilities/default.json`: grant `shell:allow-spawn` for the sidecar with an **args validator**
  matching exactly what Rust passes (`--port <digits>`). (`allow-execute` is wrong — it buffers
  until process exit; we need a long-running spawn.)
- **Rust responsibilities** (`src-tauri/src/lib.rs`), all in `.setup()` + the top-level run closure:
  1. Pick a free port: bind `TcpListener` to `127.0.0.1:0`, read the port, drop the listener.
  2. `app.shell().sidecar("scuffedos-backend").args(["--port", &port]).spawn()`; store the
     `CommandChild` in `Arc<Mutex<Option<CommandChild>>>` state; drain `CommandEvent::{Stdout,
     Stderr,Terminated}` to the app log.
  3. Health-gate: async-poll `http://127.0.0.1:<port>/health` (reqwest) every 200 ms until 200,
     **with a max-retry timeout**; on success `window.show()`, on timeout show a diagnostic error window.
  4. Expose the chosen port to the webview via a `#[tauri::command]` getter (or `app.emit`).
  5. Teardown on `RunEvent::ExitRequested`: `.take()` the child and `kill()` it, then a **sysinfo
     process-tree kill** (SIGTERM first, escalate to KILL after a timeout) as a *backstop*. On
     macOS also wire `on_window_event(CloseRequested → app_handle.exit(0))` since closing the
     window does not quit the app by default.

### 4.2 Backend launcher stub (`scuffedos-backend`) — new

A tiny single-file executable (the externalBin) whose only job is to resolve the bundled
interpreter and `exec Resources/py/bin/python3 -m uvicorn app.main:app --host 127.0.0.1
--port <p>` with `cwd` at `Resources/backend/`. It exists because Tauri's `externalBin` must be a
**single file** — the multi-file Python tree can't itself be the sidecar, so it rides along as
`resources` and this stub launches it.

### 4.3 Vendored Python env (`Resources/py/`) — build artifact

- **CPython 3.14.5** from `python-build-standalone` via `uv python install --managed-python 3.14`.
- Deps installed with the **`py-app-standalone` "true install" pattern** (install into a *copy* of
  the interpreter, **not a venv** — a venv pins its base interpreter by absolute path and breaks
  once moved). `uvx py-app-standalone --python 3.14 <deps from backend/requirements.txt> -o build/py`.
- Relocation fixes (done by the tool): relocatable shebangs, `_sysconfigdata` build-path patch,
  `install_name_tool -id @executable_path/../lib/libpython3.14.dylib`. **Ad-hoc re-sign** every
  Mach-O whose install-name we rewrite (`codesign --force -s -`) — arm64's loader rejects
  broken/absent signatures even for an unsigned app.
- Prune `__pycache__`, tests, static libs, unused stdlib (tkinter/idle/turtle) to trim size.
- **Build must fail loudly** if any C-extension dep falls back to an sdist compile (would break
  offline first-run). Python 3.14 is new — verify cp314 arm64 wheels for `psycopg[binary]`,
  `pydantic-core`, `uvloop`, and `mem0ai`'s `grpc`/`numpy` at build time.
- `psycopg[binary]` verified self-contained (bundles `libpq` under `@loader_path`), so the client
  needs no external Postgres libs.

### 4.4 Vendored Postgres + pgvector (`Resources/pgsql/`) — build artifact

- **PostgreSQL 17.10.0** from `theseus-rs/postgresql-binaries` (`aarch64-apple-darwin`) — genuinely
  relocatable on arm64 (`@loader_path` install-names, already ad-hoc signed). ~45–55 MB extracted.
- **pgvector 0.8.4** compiled **in CI against that exact PG** (`make PG_CONFIG=<pgroot>/bin/pg_config
  && make install`), then **`codesign --force --sign -`** the added `vector.dylib`.
- Ship the combined tree (PG17 + pgvector, one version-stamped tarball) as a Tauri resource.
- **Lifecycle owned by the Python backend** (a new `app/localdb.py` module), gated by env flag:
  - `SCUFFEDOS_MANAGED_PG=1` (packaged app) → boot/own a local Postgres.
  - unset (dev/tests) → use external `DATABASE_URL` exactly as today. **No behavior change in dev/CI.**
  - First run: copy tree Resources→App Support (preserving exec bits + signatures), `initdb -D pgdata`
    (SCRAM host auth, local trust), then start.
  - Every run: `pg_ctl -D pgdata -o "-k <run> -c listen_addresses=127.0.0.1 -c jit=off" -w start`
    over a **Unix socket** (avoids the macOS "accept incoming connections" firewall prompt and port
    collisions), a **stale-`postmaster.pid` recovery check**, then `alembic upgrade head` (an early
    migration runs `CREATE EXTENSION IF NOT EXISTS vector`), then serve.
  - Shutdown: an `atexit` + `SIGTERM` handler runs `pg_ctl -D pgdata stop -m fast -w`.
- **Do not** ship `pg0`/`pg0-embedded` (dev/test-only, pins PG18, fixed `~/.pg0` layout) — reference only.

### 4.5 Secrets vault + Settings — new (see §7 for rationale)

- **Store of record:** `~/Library/Application Support/ScuffedOS/secrets.enc`, dir `0700` / file `0600`
  (explicit `os.open` mode), format `nonce(12)||ciphertext||tag`, **AES-256-GCM** via the
  `cryptography` package. Key = **HKDF-SHA256** over the Mac's `IOPlatformUUID`
  (`ioreg -rd1 -c IOPlatformExpertDevice`) + a per-install random salt (`vault.salt`). Machine-bound,
  **zero prompts**, survives every rebuild/update.
- Holds **all** API keys (Anthropic, OpenAI, USDA) *and* OAuth credentials + refresh tokens
  (Whoop, Gmail, Google Calendar, Moodle, Plaid), write-through on every token rotation.
- **Backend config seam** (`app/config.py`): read secrets from the vault first, falling back to the
  App-Support `.env` / process env (keeps dev unchanged). A new `app/secrets.py` (`SecretsVault`)
  centralizes read/write; routers/integrations resolve keys through it.
- **Backend endpoints:** `GET/PUT /api/settings/secrets` (never returns raw secret values — returns
  presence/masked state), driving the Settings UI.
- **Settings screen (frontend):** a new surface (icon + sidebar entry + `SettingsScreen.jsx`) to
  view which integrations are configured and paste/update keys; first-run onboarding nudges the
  user to add keys. A "re-authenticate integrations" recovery path handles vault decrypt failure
  (e.g. `IOPlatformUUID` changed after a hardware move) instead of crashing.
- **Slice-2 hardening (in scope, decided 2026-07-07):** wrap only the 32-byte vault key in a
  single `keyring` item so the OS encrypts the master key at rest. This costs at most **one**
  "Always Allow" prompt per app update (not the N-item re-prompt storm of raw per-secret Keychain
  use, §7); the vault file remains the store of record, Keychain guards only the wrapping key.

### 4.6 Frontend changes — minimal

- The one substantive change: the API base becomes the **Tauri-provided `127.0.0.1:<port>`** instead
  of the Vite dev proxy. A small bootstrap reads the port (Tauri command/event) before first
  `/api` call; in `npm run dev` it still falls back to the Vite proxy so **dev is unchanged**.
- Add the Settings screen (4.5). App icon/branding assets for the bundle.
- Production build (`vite build`) output is bundled as a resource; the shell loads it directly.

---

## 5. First-run & steady-state sequence

```
First launch:                                   Subsequent launches:
1. Gatekeeper: right-click▸Open once             1. Tauri picks free port, spawns sidecar
2. Tauri picks free port, spawns sidecar         2. sidecar: pg_ctl start (stale-pid check)
3. sidecar copies Resources/pgsql → AppSupport   3. alembic upgrade head (usually no-op)
4. initdb pgdata; pg_ctl start (socket)          4. uvicorn serves; /health 200
5. alembic upgrade head (+ CREATE EXTENSION      5. Tauri shows the window
   vector); first-run vault + salt created       6. Settings-provided keys already in the vault
6. uvicorn serves; /health 200 (~5–15s one-time)
7. Tauri shows the window; Settings prompts keys
On quit (any launch): sidecar SIGTERM → pg_ctl stop -m fast; Rust tree-kill backstop.
```

---

## 6. Error handling

- **Health-gate timeout:** bounded `/health` retries; on failure the shell shows a diagnostic window
  (surfacing `backend.log`/`pg.log`) rather than hanging on a blank hidden window forever.
- **Stale Postgres (`postmaster.pid`):** boot-time check clears/recovers a leftover data dir before
  `pg_ctl start` (covers a prior hard-kill of the app).
- **Orphan prevention:** primary = self-cleaning Python parent (`atexit`/SIGTERM → `pg_ctl stop`);
  backstop = Rust `sysinfo` tree-kill. `RunEvent` hooks don't fire on a hard-killed app, so the
  Python-side handler is the load-bearing guarantee.
- **Vault decrypt failure** (UUID change): detect GCM auth failure → Settings "re-authenticate"
  flow, no crash.
- **Quarantine:** the unsigned `.app` needs a one-time right-click▸Open (or
  `xattr -dr com.apple.quarantine ScuffedOS.app`) — documented in `docs/ship.md`, not worked around
  (ad-hoc signing does **not** remove it).
- Existing backend error envelope (`{ "error": { code, message, details? } }`) is unchanged.

---

## 7. Why the secrets store changed from Keychain (decision record)

The chosen UX — an in-app Settings screen — is kept. Only the **backing store** changed, because the
de-risk pass found raw `keyring`/Keychain is unreliable for an **unsigned** app:

- `keyring`'s macOS backend calls `SecItemAdd(query, None)` with **no `SecAccess`**, so each item's
  ACL binds to the **creating binary's cdhash** (the Python sidecar).
- For an unsigned/ad-hoc binary there is no stable Designated Requirement, so the cdhash changes on
  **every app update / env rebuild**. "Always Allow" then stops matching and the user is re-prompted
  **~6–10 Keychain dialogs after every update, indefinitely.**
- Ad-hoc signing does **not** fix this (no stable identity); only an out-of-scope Developer ID cert would.

The **machine-bound AES-256-GCM encrypted vault** (§4.5) sidesteps this entirely: prompt-free,
survives rebuilds, fully offline, single-user-appropriate. This is the one place the original
"keychain" framing was corrected by the research.

---

## 8. Build / packaging pipeline

A new **local build script** (`scripts/build-app.sh`, run on an Apple-Silicon Mac) produces the
`.app`. **CI stays ubuntu** (backend tests + frontend build) unchanged — no macOS runner in M8.

1. **Vendor Postgres+pgvector:** download pinned theseus PG17.10.0, build pgvector 0.8.4 against it,
   ad-hoc re-sign `vector.dylib`, stamp + cache the combined tarball. Verify with `otool -L`
   (no `/opt/homebrew` or absolute build paths remain).
2. **Vendor Python env:** `uv python install` + `py-app-standalone` true-install of
   `backend/requirements.txt` (+ `uvicorn[standard]`, `cryptography`), prune, ad-hoc re-sign touched
   Mach-O, `otool -L` check. Fail the build if any dep compiled from sdist.
3. **Frontend:** `npm ci && npm run build`.
4. **Icon:** render `frontend/public/assets/logo-mark.svg` → 1024px PNG → `iconutil` `.icns`; wire
   as the Tauri bundle icon (reuse the existing brand mark — decided 2026-07-07).
5. **Tauri bundle:** `cargo tauri build` (no signing identity) → `ScuffedOS.app`.
6. **Clean-machine verification (spike, see §10):** on a second Mac / fresh user account with
   networking **disabled**, right-click▸Open, confirm uvicorn boots, `alembic upgrade` runs, and a
   pgvector/Mem0 query works — **zero network calls.**

*Deferred:* a macOS-arm64 **CI build job** that runs this script and uploads the `.app` artifact —
added later only if downloadable/reproducible builds are wanted; M8 builds locally.

Pinned tools/versions (as of 2026-07): PostgreSQL **17.10.0** (theseus), pgvector **0.8.4**,
CPython **3.14.5** (python-build-standalone via **uv 0.11.19**), `py-app-standalone`, Tauri **v2** +
`tauri-plugin-shell` **v2** (Rust ≥ **1.77.2**), `reqwest` 0.12, `sysinfo` ~0.33, `cryptography`.
Target triple **aarch64-apple-darwin**.

---

## 9. Testing strategy

- **Keep the suite green in dev/CI unchanged.** All new backend code (`app/localdb.py`,
  `app/secrets.py`, `/api/settings`) is behind the `SCUFFEDOS_MANAGED_PG` flag / vault seam, so the
  existing Postgres-or-SQLite test path is untouched. Report the pass count after each slice.
- **New unit tests:** secrets vault round-trip (encrypt/decrypt, wrong-key GCM failure, 0600 perms);
  `/api/settings/secrets` never leaks raw values; config precedence (vault → env fallback);
  `localdb` DSN/flag selection logic (mock the binaries).
- **Slice-1 spikes (must pass before the slice is "done"):**
  - **Spike A — orphan teardown:** across normal quit, window-close, app SIGKILL, and back-to-back
    relaunch, assert **no orphaned `postgres`** and the next launch is clean.
  - **Spike B — clean-machine offline relocation:** §8.5 — the single test that de-risks the PG and
    Python vendoring at once.
- **Acceptance smoke (`docs/ship.md` "acceptance"):** a fresh `.app` on a clean App-Support dir →
  double-click → every **live** screen (Home/Calendar/Tasks/Habits/Nutrition/Second Brain, + Finance
  once M7 is in, + Email/School/Fitness) and the Claude assistant work end-to-end; data persists
  across a restart. Recorded like prior milestones' live-gate notes.

---

## 10. Slicing

Big milestone → two slices, matching the project's pattern. The two spikes are **inside slice 1**
because they de-risk the core value prop (a reliable double-click) before any polish.

**Slice 1 — "It launches and works."**
- Tauri v2 scaffold (`src-tauri/`), Rust toolchain (local), launcher stub, capabilities.
- Vendored Python env + vendored PG17/pgvector build scripts.
- `scripts/build-app.sh` (local, Apple-Silicon): vendor PG+Python, generate `.icns` from
  `logo-mark.svg`, `cargo tauri build` → `ScuffedOS.app` (§8).
- `app/localdb.py` (managed-Postgres lifecycle) behind `SCUFFEDOS_MANAGED_PG`; `/health` endpoint.
- Health-gated hidden window, dynamic port handoff, teardown (Python-owned + Rust backstop).
- Frontend API-base switch to the Tauri port (Vite-proxy fallback in dev).
- **Spike A (orphan teardown)** and **Spike B (clean-machine offline relocation)**.
- **DoD:** a built `.app` double-clicks to a working dashboard, all live screens + assistant function,
  data persists across restarts, no orphaned processes; suite green.

**Slice 2 — "Settings, secrets & first-run polish."**
- `app/secrets.py` encrypted vault + config seam (vault → env fallback), migrate integration key
  reads onto it.
- **Keychain-wrapped vault key:** wrap the single vault master key in one `keyring` item so the OS
  encrypts the master key at rest (≤1 prompt per app update; §4.5).
- `GET/PUT /api/settings/secrets` + `SettingsScreen.jsx` (sidebar entry, first-run onboarding,
  re-auth recovery path).
- Branding polish, quit/relaunch UX, diagnostic error window, `docs/ship.md` + doc-fix of the
  stale "M7 Tauri" references.
- **DoD:** first-run user with an empty vault can enter keys in Settings and use every integration;
  keys survive an app update (no re-prompt storm); acceptance smoke recorded; suite green.

*(A privacy "wave" for M8 is a doc chore, not a slice — see §12.)*

---

## 11. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| **Orphaned grandchild Postgres** (biggest risk — fails the 2nd launch, not the 1st) | Python-owned shutdown (`pg_ctl stop -m fast`) + stale-pid recovery + Rust tree-kill backstop; **Spike A** proves it. |
| Stripped ad-hoc signatures / absolute build paths break exec on arm64 | Preserve xattrs on copy; `otool -L` gate in CI; **Spike B** on a clean machine. |
| Bare-venv trap (works in dev, breaks moved) | Use `py-app-standalone` true-install, never a venv. |
| cp314 wheels missing for a dep → non-offline first run | Build fails loudly on any sdist compile; verify at build time. |
| Bundle size ~250–350 MB (mem0ai grpc/numpy dominate) | Acceptable for a personal app; optional grpc/qdrant trim later — not a slice-1 dependency. |
| Quarantine blocks first launch | Documented one-time right-click▸Open; do not rely on ad-hoc signing to avoid it. |

---

## 12. Doc & housekeeping updates (part of M8)

- **Fix stale references:** `docs/backend-overview.md` §"How it should function" and
  `backend/app/reminders.py` docstring say the Tauri bundle is **M7** — correct to **M8**.
- **New `docs/ship.md`:** how the packaged app is built + run, the App-Support layout, the
  quarantine step, and the acceptance smoke.
- **README:** add a "Desktop app (M8)" section; note the `.app` build alongside the two-terminal dev flow.
- **Privacy policy:** no new external data recipient is introduced by M8 (packaging only), but the
  local encrypted-vault storage of tokens is worth a line — a small privacy "wave" via the
  `publish-privacy-policy` skill if the effective date is bumped.

## 13. Resolved (2026-07-07 review)

The three open questions from the first draft are settled:

- **Build/CI:** `.app` is built by a **local** `scripts/build-app.sh` on the Apple-Silicon Mac; CI
  stays ubuntu (tests + frontend build). A macOS-arm64 CI build job is **deferred** (§8) — not needed
  for a personal daily-driver, easy to add later for downloadable artifacts.
- **Icon:** reuse the existing brand **`logo-mark.svg` → `.icns`** at build time (§8 step 4). No new art.
- **Keychain-wrapped vault key:** **in scope for slice 2** (§4.5, §10) — OS-managed at-rest encryption
  of the single vault key, ≤1 prompt per update.

Accepted assumptions (§1 non-goals): **Apple-Silicon-only** (won't run on Intel); **~250–350 MB**
bundle (§11). Remaining build-time verification (not a design question): confirm cp314 arm64 wheels
exist for every C-extension dep so first-run stays fully offline (§4.3).
