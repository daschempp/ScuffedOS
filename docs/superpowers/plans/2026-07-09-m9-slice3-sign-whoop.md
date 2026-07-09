# M9 Slice 3 — Sign + WHOOP Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

Goal: Make WHOOP sign-in work from the packaged macOS app by (a) forwarding WHOOP's public https OAuth callback back into the app through a `scuffedos://` deep link, (b) publishing the static bounce page that performs that hop, (c) adding an opt-in Developer-ID sign + notarize stage to the build, and (d) removing the slice-2 "requires the signed build" WHOOP stub.

Architecture: WHOOP requires a public https redirect URI (its dashboard rejects loopback), so the OAuth code cannot land on the app's random loopback port directly. A static page at `https://scuffedcorporation.com/auth/whoop/callback` (WHOOP's registered redirect) JS-forwards its query to `scuffedos://oauth/callback?provider=whoop&<query>`; macOS routes that scheme to the installed app; a Rust `on_open_url` handler maps it to `http://127.0.0.1:{port}/auth/whoop/callback?<query>` and fires one blocking GET at the sidecar. The existing one-time CSRF `_STATES` check on the backend rejects any forged deep link, and the Connectors-tab poll picks up the flip. No backend logic changes.

Tech Stack: Rust / Tauri v2 (`src-tauri/`, verified by `cargo test` + `cargo check`); Python 3.14 / FastAPI (backend — **unchanged this slice**); React + Vite (frontend, verified by `npm run build` only); bash + Apple codesign/notarytool (`scripts/`, verified by `bash -n` + `plutil -lint` + a creds-absent dry run); a hand-written zero-build static site in the sibling `scuffed-corporation` repo (verified by a local static serve + a dependency-free `node -e` assertion).

Spec: `docs/superpowers/specs/2026-07-08-settings-connectors-design.md` (§5 slice map, §9 WHOOP-in-slice-2 stub, §10 the whole of this slice, §13 slice-3 testing, §16 slice-3 acceptance).

## Global Constraints

*(Every task's requirements implicitly include this section. Slices 1 and 2 are already MERGED to main (slice 2 via PR #13, merge `dd14aed`); this branch `m9-connectors-slice3` is a clean single-slice branch off main tip `dd14aed` — not stacked. Values verified against that tree.)*

- **Test baseline:** `698 passed, 1 skipped` (measured with `cd backend && ../.venv/bin/python -m pytest -q` at the branch point). This slice touches **no backend/pytest files**, so the count MUST stay `698 passed, 1 skipped`. Run the full backend suite once at the end (Task 5's close-out) to prove no backend file was edited by accident; report the count (house rule).
- **No backend change, no migration.** alembic head stays `0009`. The callback the deep link forwards to (`GET /auth/whoop/callback?code=..&state=..`) already exists and is already covered by `test_callback_success_renders_html_and_persists_and_syncs` (backend/tests/test_oauth.py:106). WHOOP already `authorize_url`/`exchange_code` cleanly ignore the PKCE params (whoop.py:89, :116). Do not add backend code or a redundant guard test.
- **Do NOT change `whoop_redirect_uri`.** It stays the public `https://scuffedcorporation.com/auth/whoop/callback` (config.py:75) — it is what WHOOP redirects to and what the token exchange sends. The loopback URL is the deep-link *forward target*, never the registered redirect.
- **Signed builds are opt-in.** The sign+notarize stage runs only when `APPLE_SIGNING_IDENTITY` is set. `bash scripts/build-app.sh` with no signing env MUST still emit the unsigned `.app` exactly as today (the dev daily-driver path).
- **No new test harness.** The frontend has none (§14) and the corp site is deliberately zero-build/zero-dependency; do not introduce jest/vitest/npm into either. The corp forward logic is checked with a dependency-free `node -e` one-liner.
- **Deep-link scheme is `scuffedos`.** Baked into Info.plist at build time via `tauri.conf.json > plugins > deep-link > desktop > schemes`. macOS fires deep links only for the bundled, installed `.app` — dev (`tauri dev`) cannot exercise them (§10 dev caveat).
- **Style (match slice 2, the immediate predecessor):** `### Task N` headings; plain (unbolded) `Files:`/`Interfaces:` labels; bare `- [ ]` step bullets; `cd backend && ../.venv/bin/python -m pytest -q`; `cd frontend && npm run build`; `cd src-tauri && cargo test`/`cargo check`; commit with `git commit -am`, subject suffixed `(M9 s3)` (optionally `(M9 s3 §10)`). `[confirm-against-live]` tags anything resolvable only against a real cert / installed bundle / external service. `> EXECUTION RISK` blockquotes flag network/registry or credential gates as SOFT (hand to user, not a plan defect).

**Prerequisite (user, [confirm-against-live]):** Apple Developer Program enrollment ($99/yr) + a "Developer ID Application" certificate in the login keychain + a stored notarytool keychain profile. This gates **execution** of Task 3's signing and **all** live gates in the Manual verification section. Every code artifact in this plan lands and is statically verified regardless; only the actual signed/notarized run and the end-to-end WHOOP round-trip wait on enrollment.

---

## File Structure

Rust / Tauri (`src-tauri/`) — modified:
- `src/lib.rs` — add the pure `forward_target_url()` mapper + its `#[cfg(test)]` tests (Task 1); add the deep-link plugin registration + `on_open_url` forwarding handler (Task 2).
- `Cargo.toml` — add `tauri-plugin-deep-link = "2"` (Task 2).
- `capabilities/default.json` — add `"deep-link:default"` (Task 2).
- `tauri.conf.json` — add `plugins.deep-link.desktop.schemes` (Task 2).

Build (`scripts/`) — created + modified:
- `scripts/sign-notarize.sh` — created: deepest-first Developer-ID codesign + notarytool + stapler (Task 3).
- `src-tauri/entitlements.plist` — created: hardened-runtime entitlements the vendored Python/Postgres need (Task 3).
- `scripts/build-app.sh` — modified: renumber to 7 stages, add the gated `[7/7]` sign step (Task 3).

Frontend (`frontend/src/`) — modified:
- `screens/ConnectorsPanel.jsx` — remove the packaged-WHOOP stub, unwrap the button fragment, drop the now-dead `packaged` local (Task 4).

Corp site (sibling repo `/Users/dylanschempp/PycharmProjects/scuffed-corporation`) — created + modified:
- `auth/whoop/callback.html` — created: the static JS bounce page (Task 5).
- `Dockerfile` — modified: add `auth/` to the Caddy COPY list (Task 5).
- `README.md` — modified: reconcile the post-deploy checklist + the two internal no-JS developer rules (Task 5).

---

### Task 1: Rust — pure `scuffedos://` → loopback URL mapper (TDD)

Files:
- Modify: `src-tauri/src/lib.rs` (add a free function `forward_target_url` near `wait_for_health` ~line 79, and a `#[cfg(test)] mod tests` at the end of the file).
- Test: same file, `#[cfg(test)] mod tests` (Rust's built-in harness — no new dependency).

Interfaces:
- Produces: `fn forward_target_url(deep_link: &str, port: u16) -> Option<String>` — maps `scuffedos://oauth/callback?provider=<p>&<oauth query>` to `http://127.0.0.1:{port}/auth/{p}/callback?<oauth query minus provider>`; returns `None` for any URL that is not our scheme/host/path or lacks a safe non-empty `provider`. Task 2's handler consumes it.
- Consumes: `reqwest::Url` (already vendored — `reqwest` is a dep at Cargo.toml:18; reqwest 0.12 re-exports `pub use url::Url`). No new crate, so `cargo test` runs offline.

Why a pure helper: the URL mapping is the only branchy logic in the whole deep-link path and it is the one part unit-testable without an installed bundle or a live browser (§13: "deep-link handler logic unit-tested at the Rust seam where practical"). Task 2 is then thin glue that `cargo check` covers.

- [ ] Add the failing tests. Append to `src-tauri/src/lib.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::forward_target_url;

    #[test]
    fn maps_whoop_callback_to_loopback_preserving_code_and_state() {
        let got = forward_target_url(
            "scuffedos://oauth/callback?provider=whoop&code=abc123&state=xyz789",
            54321,
        );
        assert_eq!(
            got.as_deref(),
            Some("http://127.0.0.1:54321/auth/whoop/callback?code=abc123&state=xyz789"),
        );
    }

    #[test]
    fn preserves_error_param_and_reencodes_values() {
        // WHOOP denial: error present, no code. query_pairs decodes `a+b` to
        // "a b"; append_pair re-encodes the space back to `+`.
        let got = forward_target_url(
            "scuffedos://oauth/callback?provider=whoop&error=access_denied&state=a+b",
            8000,
        );
        assert_eq!(
            got.as_deref(),
            Some("http://127.0.0.1:8000/auth/whoop/callback?error=access_denied&state=a+b"),
        );
    }

    #[test]
    fn rejects_foreign_scheme() {
        assert_eq!(
            forward_target_url("https://evil.example/oauth/callback?provider=whoop&code=x", 8000),
            None,
        );
    }

    #[test]
    fn rejects_wrong_host_or_path() {
        assert_eq!(
            forward_target_url("scuffedos://evil/callback?provider=whoop&code=x", 8000),
            None,
        );
        assert_eq!(
            forward_target_url("scuffedos://oauth/other?provider=whoop&code=x", 8000),
            None,
        );
    }

    #[test]
    fn rejects_missing_empty_or_unsafe_provider() {
        assert_eq!(
            forward_target_url("scuffedos://oauth/callback?code=x&state=y", 8000),
            None,
        );
        assert_eq!(
            forward_target_url("scuffedos://oauth/callback?provider=&code=x", 8000),
            None,
        );
        // Path-injection defense: provider must be lowercase ascii only.
        assert_eq!(
            forward_target_url("scuffedos://oauth/callback?provider=..%2Fetc&code=x", 8000),
            None,
        );
    }
}
```

- [ ] Run them, confirm FAIL. `cd src-tauri && cargo test --offline forward_target_url` → expected FAIL: `cannot find function `forward_target_url` in this scope` (or `E0425`). If `--offline` errors because the test-build metadata isn't cached yet, drop `--offline` for this one run.

- [ ] Minimal implementation. Insert into `src-tauri/src/lib.rs` just after `wait_for_health` (after line 79):

```rust
/// Map an incoming `scuffedos://oauth/callback?provider=<p>&<oauth query>` deep
/// link to the loopback OAuth callback the backend serves:
/// `http://127.0.0.1:{port}/auth/{p}/callback?<oauth query minus provider>`.
///
/// Returns `None` for anything that is not our exact scheme/host/path, or whose
/// `provider` is missing/empty/not lowercase-ascii (a path-injection guard — the
/// segment is interpolated into the URL path). The backend's one-time CSRF state
/// check is the real authorization gate; this is defense in depth.
fn forward_target_url(deep_link: &str, port: u16) -> Option<String> {
    let url = reqwest::Url::parse(deep_link).ok()?;
    if url.scheme() != "scuffedos" {
        return None;
    }
    // `scuffedos://oauth/callback` parses to host "oauth", path "/callback".
    if url.host_str() != Some("oauth") || url.path() != "/callback" {
        return None;
    }

    let pairs: Vec<(String, String)> = url.query_pairs().into_owned().collect();
    let provider = pairs
        .iter()
        .find(|(k, _)| k == "provider")
        .map(|(_, v)| v.clone())
        .filter(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_lowercase()))?;

    let mut target =
        reqwest::Url::parse(&format!("http://127.0.0.1:{port}/auth/{provider}/callback")).ok()?;
    {
        let mut qp = target.query_pairs_mut();
        for (k, v) in pairs.iter().filter(|(k, _)| k != "provider") {
            qp.append_pair(k, v);
        }
    }
    // Drop the trailing "?" url writes when there are no pairs.
    Some(match target.query() {
        Some("") | None => {
            target.set_query(None);
            target.to_string()
        }
        Some(_) => target.to_string(),
    })
}
```

> Note ([confirm-against-live]): this relies on `reqwest::Url` (reqwest 0.12 re-exports the `url` crate). If `cargo test` reports `unresolved import reqwest::Url`, add `url = "2"` to `[dependencies]` in `src-tauri/Cargo.toml` and swap `reqwest::Url` → `url::Url` (one more crate to fetch — fold it into Task 2's network gate). Confirmed present in the current lock is preferred.

- [ ] Run tests, confirm PASS. `cd src-tauri && cargo test --offline forward_target_url` → expected: `test result: ok. 5 passed`. (First compile may need network for the test profile; if `--offline` fails to build, run `cargo test forward_target_url` once.)

- [ ] Commit. `git commit -am "feat(ship): pure scuffedos:// -> loopback OAuth callback URL mapper + tests (M9 s3 §10)"`

---

### Task 2: Rust — register the deep-link plugin + forward WHOOP callbacks

Files:
- Modify: `src-tauri/Cargo.toml` (add `tauri-plugin-deep-link = "2"` under `[dependencies]`, after `tauri-plugin-opener = "2"` at line 17).
- Modify: `src-tauri/capabilities/default.json` (add `"deep-link:default"` to `permissions`, after `"opener:default"` at line 7).
- Modify: `src-tauri/tauri.conf.json` (replace `"plugins": {}` at line 34 with the deep-link scheme config).
- Modify: `src-tauri/src/lib.rs` (add the `DeepLinkExt` import + register the plugin in the Builder + the `on_open_url` handler inside `.setup()`).

Interfaces:
- Consumes: `forward_target_url()` (Task 1), `Backend { port }` managed state (lib.rs:10-13, :215), `wait_for_health()` (lib.rs:63), the existing blocking-`reqwest` + `std::thread::spawn` pattern (lib.rs:65, :239).
- Produces: at runtime, every `scuffedos://oauth/callback?...` (including the cold-start launch URL the plugin buffers) is forwarded once to the loopback callback. No new Rust API surface other code consumes.

> EXECUTION RISK — network/registry required, no offline path. This task's `cargo check` must fetch `tauri-plugin-deep-link` from crates.io (and, if the Task-1 note fired, `url`). This is a SOFT gate: if the crate cannot be fetched (no network/registry), record the blocker and hand the packaged build to the user — do NOT report task failure. It mirrors slice 2's opener-plugin task exactly (cc59603).

- [ ] Add the dependency. In `src-tauri/Cargo.toml`, after line 17 (`tauri-plugin-opener = "2"`), add:

```toml
tauri-plugin-deep-link = "2"
```

- [ ] Add the capability permission. In `src-tauri/capabilities/default.json`, change the `permissions` array so line 7-8 read:

```json
    "core:default",
    "opener:default",
    "deep-link:default",
```

> The `deep-link:default` permission gates the `get_current` IPC command (per the plugin's permission table). The pure-Rust `on_open_url` handler below does not strictly need it, but adding it mirrors `opener:default` and future-proofs a JS `getCurrent()` fallback. Harmless if unused.

- [ ] Declare the scheme. In `src-tauri/tauri.conf.json`, replace line 34 (`"plugins": {}`) with:

```json
  "plugins": {
    "deep-link": {
      "desktop": {
        "schemes": ["scuffedos"]
      }
    }
  }
```

- [ ] Register the plugin + handler in `src-tauri/src/lib.rs`.

First, add the trait import next to the other `use` lines at the top (after line 7, `use tauri_plugin_shell::ShellExt;`):

```rust
use tauri_plugin_deep_link::DeepLinkExt;
```

Register the plugin in the Builder — after line 196 (`.plugin(tauri_plugin_opener::init())`), add:

```rust
        .plugin(tauri_plugin_deep_link::init())
```

Then wire the handler inside `.setup()`, immediately after `app.manage(Backend { child: child.clone(), port });` (line 215), so the managed state exists when a buffered launch URL is replayed:

```rust
            // Forward WHOOP's scuffedos:// OAuth callback into the loopback
            // callback the backend serves. The deep-link plugin delivers these
            // here, including the cold-start launch URL (macOS buffers it and
            // replays it to on_open_url). WHOOP needs a public https redirect
            // (its dashboard rejects loopback), so the public bounce page hops
            // the code back in via this scheme. The backend's one-time CSRF
            // state check rejects any forged deep link, so firing for any
            // incoming scuffedos:// URL is safe.
            let dl_handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                let port = dl_handle.state::<Backend>().port;
                for url in event.urls() {
                    match forward_target_url(url.as_str(), port) {
                        Some(target) => {
                            let h = dl_handle.clone();
                            std::thread::spawn(move || {
                                // Gate on backend health BEFORE the single
                                // forward: on a cold start the sidecar may not be
                                // listening yet. The state token is one-time, so
                                // we must NOT retry the GET itself — wait for
                                // health, then fire exactly once. reqwest::blocking
                                // must run off the UI/tokio thread (mirrors the
                                // health-gate worker at lib.rs:239).
                                if !wait_for_health(h.state::<Backend>().port) {
                                    eprintln!("[deep-link] backend not healthy; dropping OAuth callback forward");
                                    return;
                                }
                                let client = reqwest::blocking::Client::builder()
                                    .timeout(Duration::from_secs(30))
                                    .build()
                                    .expect("reqwest client");
                                match client.get(&target).send() {
                                    Ok(resp) => eprintln!("[deep-link] forwarded OAuth callback ({})", resp.status()),
                                    Err(e) => eprintln!("[deep-link] OAuth callback forward failed: {e}"),
                                }
                            });
                        }
                        None => eprintln!("[deep-link] ignoring unrecognized deep link: {}", url.as_str()),
                    }
                }
            });
```

> [confirm-against-live] the exact `app.deep_link().on_open_url(|event| …)` / `event.urls()` surface — this is the documented Tauri v2 `DeepLinkExt` API, but the crate could not be built offline to compile-check the signature while authoring. If `on_open_url`/`urls()` do not resolve, check the installed `tauri-plugin-deep-link` version's docs and adjust (the handler body — health-gate, `forward_target_url`, blocking GET on a worker thread — stays the same).

- [ ] Verify it compiles. `cd src-tauri && cargo check` → expected: downloads `tauri-plugin-deep-link` (and `url` if the Task-1 note fired), then `Finished` with zero errors. If the registry is unreachable, STOP and hand off per the EXECUTION RISK note above.

- [ ] Commit. `git commit -am "feat(ship): deep-link plugin (scuffedos scheme) forwards WHOOP OAuth callback to the loopback backend (M9 s3 §10)"`

---

### Task 3: Build — opt-in Developer-ID sign + notarize stage

Files:
- Create: `src-tauri/entitlements.plist` (hardened-runtime entitlements).
- Create: `scripts/sign-notarize.sh` (deepest-first codesign + notarytool + stapler).
- Modify: `scripts/build-app.sh` (renumber the 6 stages to 7; add the gated `[7/7]` call after `$APP` is defined at line 99; update the header comment).

Interfaces:
- Consumes: the `.app` at `$APP` (build-app.sh:99), the vendored trees at `Contents/Resources/py` + `Contents/Resources/pgsql` and the two `Contents/MacOS/*` binaries (verified in the built bundle), env `APPLE_SIGNING_IDENTITY` + `APPLE_NOTARY_KEYCHAIN_PROFILE`.
- Produces: a signed, hardened, notarized, stapled `.app` when creds are present; the unchanged unsigned `.app` when they are absent.

Design notes (from spec §10 + the verified bundle):
- **Manual shell stage, not Tauri-native signing.** The bundle embeds hundreds of nested Mach-Os (~61 under `py`, ~120 under `pgsql`, plus the sidecar) whose ad-hoc vendor-time signatures must be *overwritten* with Developer-ID + hardened runtime + entitlements. A deepest-first manual pass (the Postgres.app-shipped shape) is the reliable way; Tauri's `bundle.macOS` signing does not re-sign copied `resources/` trees. So we bolt a stage onto `build-app.sh`.
- **Order matters:** sign leaf `*.dylib`/`*.so` → Mach-O executables under `Resources` → the two `Contents/MacOS/*` → the `.app` last. Re-signing a parent invalidates unsigned children, so children first.
- **notarytool takes an archive, not a bare `.app`** — zip with `ditto`, submit the zip, staple the `.app`.

- [ ] Create `src-tauri/entitlements.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <!-- The vendored CPython + Postgres need these under the hardened runtime.
       Trim to the minimum once a real notarization run confirms what the
       bundle actually requires (spec §10 [confirm-against-live]). -->
  <key>com.apple.security.cs.allow-jit</key>
  <true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
  <true/>
  <key>com.apple.security.cs.disable-library-validation</key>
  <true/>
</dict>
</plist>
```

- [ ] Lint the plist. `plutil -lint src-tauri/entitlements.plist` → expected: `src-tauri/entitlements.plist: OK`.

- [ ] Create `scripts/sign-notarize.sh`:

```bash
#!/usr/bin/env bash
# Developer-ID codesign + notarize + staple a built ScuffedOS.app. Invoked by
# build-app.sh's [7/7] stage ONLY when APPLE_SIGNING_IDENTITY is set. Signs
# every nested Mach-O deepest-first with the hardened runtime + entitlements,
# then submits to Apple's notary service and staples the ticket.
#
# Required env:
#   APPLE_SIGNING_IDENTITY         e.g. "Developer ID Application: Dylan Schempp (TEAMID)"
#   APPLE_NOTARY_KEYCHAIN_PROFILE  a profile stored via `xcrun notarytool store-credentials`
set -euo pipefail

APP="${1:?usage: sign-notarize.sh /path/to/ScuffedOS.app}"
IDENT="${APPLE_SIGNING_IDENTITY:?APPLE_SIGNING_IDENTITY not set}"
PROFILE="${APPLE_NOTARY_KEYCHAIN_PROFILE:?APPLE_NOTARY_KEYCHAIN_PROFILE not set}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTITLEMENTS="$ROOT/src-tauri/entitlements.plist"

sign() { codesign --force --timestamp --options runtime \
                  --entitlements "$ENTITLEMENTS" -s "$IDENT" "$1"; }

echo "==> Signing nested Mach-Os (deepest first)"
# 1. Leaf shared libraries under Resources (py + pgsql trees).
find "$APP/Contents/Resources" \( -name '*.dylib' -o -name '*.so' \) -type f -print0 \
  | while IFS= read -r -d '' f; do sign "$f"; done
# 2. Mach-O executables under Resources (python3, postgres, initdb, psql, ...).
find "$APP/Contents/Resources" -type f -perm -111 ! -name '*.dylib' ! -name '*.so' -print0 \
  | while IFS= read -r -d '' f; do
      if file "$f" | grep -q 'Mach-O'; then sign "$f"; fi
    done
# 3. The sidecar launcher + the main app binary.
sign "$APP/Contents/MacOS/scuffedos-backend"
sign "$APP/Contents/MacOS/scuffedos"
# 4. The bundle itself, last.
sign "$APP"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> Notarizing (zip -> submit --wait -> staple)"
ZIP="${APP%.app}.zip"
rm -f "$ZIP"
/usr/bin/ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP"
rm -f "$ZIP"

echo "==> Signed + notarized: $APP"
```

- [ ] Syntax-check it. `bash -n scripts/sign-notarize.sh` → expected: no output, exit 0. (If `shellcheck` is installed, `shellcheck scripts/sign-notarize.sh` and address any error-level findings; warnings about the `sign` helper are fine.)

- [ ] Wire it into `scripts/build-app.sh`. Update the header comment (lines 2-5) to note the optional signing stage, renumber the stage echoes `[N/6]` → `[N/7]` (lines 19, 22, 25, 32, 93, 96), and after `$APP` is defined (line 99) insert the gated stage. The tail of the file becomes:

```bash
echo "==> [6/7] cargo tauri build (.app only)"
( cd "$ROOT/src-tauri" && cargo tauri build --bundles app )

APP="$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app"

if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  echo "==> [7/7] Sign + notarize (APPLE_SIGNING_IDENTITY set)"
  bash "$ROOT/scripts/sign-notarize.sh" "$APP"
else
  echo "==> [7/7] Skipping sign + notarize (APPLE_SIGNING_IDENTITY unset) — unsigned build"
fi

echo "==> Done. App at: $APP"
du -sh "$APP" || true
```

- [ ] Prove the unsigned path still no-ops cleanly. `bash -n scripts/build-app.sh` → exit 0. Then dry-run just the new branch without a real build: `APPLE_SIGNING_IDENTITY="" bash -c 'if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then echo SIGN; else echo "skip — unsigned"; fi'` → expected: `skip — unsigned`. (A full `bash scripts/build-app.sh` is a long vendored build; run it only if you want the end-to-end unsigned artifact — it must still finish at "Done. App at: …".)

> EXECUTION RISK — the *signed* run needs the Apple prerequisite (enrollment + Developer ID cert + notarytool profile). Executing `APPLE_SIGNING_IDENTITY=… APPLE_NOTARY_KEYCHAIN_PROFILE=… bash scripts/build-app.sh` is a **user live gate** (Manual verification below), NOT an SDD step. Landing the scripts + entitlements is this task's deliverable.

- [ ] Commit. `git commit -am "feat(ship): opt-in Developer-ID sign + notarize stage (hardened runtime + entitlements); unsigned build unchanged (M9 s3 §10)"`

---

### Task 4: Frontend — un-gate WHOOP packaged connect

Files:
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (delete the slice-2 stub ternary at lines 203-207 + its closing `)` at line 222, unwrap the `<>…</>` button fragment, and delete the now-dead `const packaged = isTauri()` at line 161).

Interfaces:
- Consumes: nothing new. WHOOP already flows through the provider-agnostic `connectOAuth(name)` → `openExternal(authorize_url)` → `startConnectPoll(name)` path (ConnectorsPanel.jsx:89-99), and `openExternal` already routes packaged connects through the opener plugin (:32-39). Removing the stub lets WHOOP take that identical Google path.
- Produces: nothing consumed elsewhere. Pure UI change.

Read + confirm the block before editing (verified against the current tree). The OAuth branch at lines 201-228 currently wraps the real buttons in a stub ternary. Replace lines 201-228 with the un-gated form:

```jsx
            {/* OAuth connectors: Google / WHOOP */}
            {c.auth_kind === 'oauth' && (
              <div className="kit-inline" style={{ gap: 8 }}>
                {c.status === 'not_connected' && (
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Connect</Button>
                )}
                {c.status === 'needs_reauth' && (
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Reconnect</Button>
                )}
                {c.status === 'connected' && c.name === 'google' && c.can_write_email === false && (
                  <Button variant="secondary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Enable email actions</Button>
                )}
                {c.status !== 'not_connected' && confirming !== c.name && (
                  <Button variant="secondary" size="sm" disabled={busy === c.name}
                    onClick={() => setConfirming(c.name)}>Disconnect</Button>
                )}
              </div>
            )}
```

Then delete the now-unused local at line 161 (`const packaged = isTauri()`) — it was referenced only by the deleted stub. **Keep** the `isTauri` import at line 10; `openExternal` (line 33) still uses it.

- [ ] Confirm `packaged` is dead before deleting. `cd frontend && grep -n "packaged" src/screens/ConnectorsPanel.jsx` → expected: no matches after you remove the stub (if any remain, they are unexpected — reconcile before deleting the local).

- [ ] Verify the build. `cd frontend && npm run build` → expected: `vite build` completes with `✓ built in …` and exit code 0, no unused-var error for `packaged`/`isTauri`.

- [ ] Manual checklist (dev — the packaged path is a live gate below):
  - [ ] In dev (`run-scuffedos` skill), Settings › Connectors: the WHOOP card shows a real **Connect** button (not the "requires the signed build" text). Dev WHOOP connect already worked pre-slice-3; this only removes the packaged-mode stub.
  - [ ] Google/Moodle/Plaid cards are visually unchanged.

- [ ] Commit. `git commit -am "feat(connectors): un-gate WHOOP packaged connect now that the signed build + deep link land (M9 s3 §10)"`

> Sequencing note: this un-gate is safe to land in the branch, but packaged WHOOP Connect only actually completes once Task 2's deep link, Task 3's signed build, and Task 5's bounce page are all live. The whole slice ships as one unit behind the live gate — do not cut a packaged release from a partial slice.

---

### Task 5: Corp site — static WHOOP bounce page + deploy wiring + README reconciliation

This task lands in the **sibling repo** `/Users/dylanschempp/PycharmProjects/scuffed-corporation` (remote `github.com/daschempp/scuffed-corporation`, branch `main`), not the ScuffedOS branch. It is the public hop WHOOP's https redirect needs (§10). Follow the corp site's convention: hand-authored static file, direct commit to `main`, **push only after explicit user go-ahead** (outward-facing).

Files (all paths under the corp repo):
- Create: `auth/whoop/callback.html` — served at `/auth/whoop/callback` (extensionless — see the trailing-slash note).
- Modify: `Dockerfile` — add `COPY auth/ /srv/auth/` to the Caddy image (the GitHub-Pages/Cloudflare path picks the file up automatically on push; the Caddy container does not unless copied).
- Modify: `README.md` — reconcile the post-deploy checklist item (lines 69-74) and the two internal no-JS developer rules (lines 34, 87).

Why extensionless `callback.html`, not a `callback/` directory ([confirm-against-live]): WHOOP's registered redirect is `https://scuffedcorporation.com/auth/whoop/callback` with **no trailing slash**. The site's `<dir>/index.html` convention serves at a *trailing-slash* path and 301-redirects the no-slash form — a redirect that can drop the query or break strict `redirect_uri` matching. GitHub Pages / Cloudflare serve `foo.html` at the extensionless `/foo`, so `auth/whoop/callback.html` answers `/auth/whoop/callback` directly. Verify the live host serves it with no 301 (Manual verification below).

Reconciliation note (not a public walk-back): the on-site colophon was reworked in the June 2026 redesign to drop the "no javascript" meta-brag — the current public colophon (index.html:156 and every page) says only *"No trackers, no cookies, nothing here is watching you read it,"* which stays **true** for a scheme-redirect page (no trackers, no cookies, no external requests). Only two **internal README developer rules** still assert "no JavaScript"; this task narrows them to carve out the single OAuth utility page.

- [ ] Create `auth/whoop/callback.html` (mirrors the shared head boilerplate + `/styles.css`; the only page on the site with a `<script>`):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Returning to Scuffed OS…</title>
<meta name="robots" content="noindex">
<meta name="theme-color" content="#f4f3ee" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0e0e0e" media="(prefers-color-scheme: dark)">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css">
</head>
<body>
<div class="frame">
  <main id="main">
    <section class="sec" aria-labelledby="bounce-title">
      <p class="sec-label"><span>whoop sign-in</span><span>returning to the app</span></p>
      <div class="sec-main">
        <h1 class="page-title" id="bounce-title">Finishing WHOOP sign-in…</h1>
        <p>You should be returned to Scuffed OS automatically. If nothing happens,
           <a id="return" href="#">open Scuffed OS</a>.</p>
        <p class="kit-muted">This is the one utility page on the site that runs a few lines of
           script — it hands WHOOP's sign-in result back to the desktop app. No trackers,
           no cookies, no external requests.</p>
      </div>
    </section>
  </main>
</div>
<script>
  // Forward WHOOP's OAuth query (code + state, or error) into the desktop app
  // via its custom scheme. WHOOP requires a public https redirect, so this page
  // is the bridge back to the local app's deep-link handler.
  (function () {
    function bounceTarget(search) {
      var q = (search || '').replace(/^\?/, '');
      return 'scuffedos://oauth/callback?provider=whoop' + (q ? '&' + q : '');
    }
    var target = bounceTarget(window.location.search);
    var link = document.getElementById('return');
    if (link) link.setAttribute('href', target);
    window.location.href = target;
  })();
</script>
</body>
</html>
```

- [ ] Assert the forward logic with a dependency-free node check (no harness added):

```bash
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation
node -e '
  function bounceTarget(search){var q=(search||"").replace(/^\?/,"");return "scuffedos://oauth/callback?provider=whoop"+(q?"&"+q:"");}
  const a = bounceTarget("?code=abc&state=xyz");
  const b = bounceTarget("?error=access_denied&state=xyz");
  const c = bounceTarget("");
  if (a!=="scuffedos://oauth/callback?provider=whoop&code=abc&state=xyz") throw new Error("a: "+a);
  if (b!=="scuffedos://oauth/callback?provider=whoop&error=access_denied&state=xyz") throw new Error("b: "+b);
  if (c!=="scuffedos://oauth/callback?provider=whoop") throw new Error("c: "+c);
  console.log("bounceTarget OK");
'
```

Expected: `bounceTarget OK`. (This mirrors Task 1's Rust mapper on the JS side: `?code&state` → the scheme URL that the Rust `forward_target_url` then maps to the loopback.)

- [ ] Confirm the bounce page is the only script on the site. `grep -rl "<script" . --include=*.html` → expected: only `./auth/whoop/callback.html`.

- [ ] Update the Caddy `Dockerfile`. After the `COPY privacy/ /srv/privacy/` line, add:

```dockerfile
COPY auth/ /srv/auth/
```

- [ ] Update `README.md`:
  - Line 69-74 post-deploy checklist item — replace the "leave that as-is (the site does not need to serve that path…)" clause with: the site now serves `/auth/whoop/callback` as a static bounce page that forwards the OAuth result into the desktop app via the `scuffedos://` scheme; confirm it loads and that the no-slash URL is served without a 301.
  - Line 34 — narrow "no JavaScript" to: no analytics, no trackers, no cookies, and no JavaScript on content pages; the single `/auth/whoop/callback` bounce page runs a few lines of inline script to hand the OAuth result to the desktop app (no trackers/cookies/external requests). The public colophon claim ("no trackers, no cookies") stays literally true.
  - Line 87 editing rule — change to: No JavaScript on content pages. The sole exception is the `/auth/whoop/callback` OAuth bounce page, which must forward the code into the desktop app via the `scuffedos://` scheme. Any other page that seems to need JS is wrong for this site.

- [ ] Local visual + serving check. `cd /Users/dylanschempp/PycharmProjects/scuffed-corporation && python3 -m http.server 8000` in one shell, then load `http://localhost:8000/auth/whoop/callback?code=demo&state=demo` — the styled interstitial renders, the "open Scuffed OS" link's href is `scuffedos://oauth/callback?provider=whoop&code=demo&state=demo` (the auto-redirect will fail in a plain browser since the scheme isn't registered there — that's expected; check the link href / console). Stop the server.

- [ ] Commit (in the corp repo). `git add auth/whoop/callback.html Dockerfile README.md && git commit -m "auth: WHOOP OAuth bounce page -> scuffedos:// deep link (sync with Scuffed OS M9 s3)"`

> Do NOT `git push` until the user approves the diff (outward-facing public site — same rule as the privacy waves). Publishing is a user step in the Manual verification section.

- [ ] Close-out (back in the ScuffedOS repo): prove no backend file was touched this slice. `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && ../.venv/bin/python -m pytest -q` → expected: **`698 passed, 1 skipped`** (unchanged). Report the count.

---

## Manual verification / live gate (user) [confirm-against-live]

The signed-bundle end-to-end is NOT an SDD task — no automated harness can drive Gatekeeper, Apple notarization, a real system browser, or a macOS custom-scheme hop. Once the user has completed the Apple prerequisite, the user performs the §16 Slice-3 acceptance:

- [ ] [confirm-against-live] Store a notarytool profile: `xcrun notarytool store-credentials` (Apple ID + app-specific password + team id), note the profile name.
- [ ] [confirm-against-live] Build signed: `APPLE_SIGNING_IDENTITY="Developer ID Application: … (TEAMID)" APPLE_NOTARY_KEYCHAIN_PROFILE="<profile>" bash scripts/build-app.sh` → the `[7/7]` stage runs, `codesign --verify --deep --strict` passes, `notarytool submit --wait` returns `Accepted`, `stapler staple` succeeds.
- [ ] [confirm-against-live] Gatekeeper: move `ScuffedOS.app` to `/Applications` and launch by double-click on a machine where it was never opened before — it opens with **no** right-click-Open bypass. `spctl -a -vvv /Applications/ScuffedOS.app` → `accepted / source=Notarized Developer ID`.
- [ ] [confirm-against-live] Publish the corp bounce page: review the corp-repo diff, then `git push origin main`; confirm `https://scuffedcorporation.com/auth/whoop/callback` loads over HTTPS **without a trailing-slash 301** (`curl -sSI 'https://scuffedcorporation.com/auth/whoop/callback?code=x&state=y'` → `200`, not `301`). If the live host 301s to `/auth/whoop/callback/`, fall back to a `callback/index.html` and re-verify WHOOP accepts the redirect.
- [ ] [confirm-against-live] WHOOP end-to-end from the installed signed `.app`: Settings › Connectors → WHOOP **Connect** → consent in the system browser → WHOOP redirects to the bounce page → it deep-links `scuffedos://…` → the app forwards to the loopback callback → the card flips to **Connected** (the tab poll picks it up). Confirm a workout/recovery sync landed.
- [ ] [confirm-against-live] Dev caveat sanity: macOS fires deep links only for the installed bundle; if you need to test WHOOP in `tauri dev`, keep the M4 tunnel-redirect override (`whoop_redirect_uri` in `.env`) — the scheme hop is packaged-only.

---

## Open questions resolved / flagged

- **[prereq] Apple enrollment** — REQUIRED for Task 3 execution + every live gate; does not block landing any code. Flag to the user before the live-gate phase. Until enrolled, the app ships unsigned (right-click-Open) and packaged WHOOP stays unusable even with the un-gate, because the deep link only fires from a bundled installed app.
- **[signing] native vs manual** — RESOLVED: manual deepest-first codesign stage in `build-app.sh` (Postgres.app-shipped shape), not Tauri's `bundle.macOS`, because the copied `resources/` Python+Postgres trees carry ad-hoc vendor-time signatures that Tauri-native signing won't overwrite (spec §10).
- **[entitlements] exact set** — assumed `allow-jit` + `allow-unsigned-executable-memory` + `disable-library-validation` (spec §10); [confirm-against-live] trim to the minimum once a real notarization run reports what the vendored CPython/Postgres actually need.
- **[corp] no-JS claim** — RESOLVED: the public on-site colophon already dropped "no javascript" in the June redesign; the bounce page keeps every *public* promise true and only narrows two internal README developer rules. Not a public walk-back. Alternative if the user prefers a spotless apex site: host the bounce on a dedicated subdomain — rejected here because WHOOP's redirect is already registered at `scuffedcorporation.com/auth/whoop/callback` and re-registering is friction.
- **[corp] trailing slash** — RESOLVED to extensionless `callback.html` to answer the no-slash `redirect_uri` without a 301; [confirm-against-live] against the live host, with a `callback/index.html` fallback documented in the live gate.
- **[deep-link] Rust API surface** — [confirm-against-live] `app.deep_link().on_open_url` / `event.urls()` (standard Tauri v2 `DeepLinkExt`), not compile-checkable offline while authoring; adjust to the installed crate version if needed.
- **[branch/merge] not stacked** — RESOLVED: slices 1 and 2 are already on main (slice 2 merged via PR #13, `dd14aed`), so `m9-connectors-slice3` is a clean single-slice branch off main. It ships as an ordinary single PR onto main — no stacking, no combined-M9-PR concern. (The M7/spec §1 stacked-PR worry does not apply.)

---

Plan complete.
