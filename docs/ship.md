# Shipping ScuffedOS — the macOS desktop app (M8)

ScuffedOS ships as a **double-clickable, Developer-ID-signed and notarized
`ScuffedOS.app`** for a single Apple-Silicon Mac. The app bundles its own Python
runtime, PostgreSQL 17 + pgvector, and the FastAPI backend, so it runs the full
dashboard offline with no terminal and no cloud database.

> **Scope:** personal daily-driver, macOS **arm64 only**, **signed + notarized**
> with a Developer ID (no DMG, no auto-update, no Windows/Linux). A build with
> `APPLE_SIGNING_IDENTITY` unset is unsigned and needs the quarantine bypass
> below. See `docs/superpowers/specs/2026-07-07-ship-tauri-design.md`.

## Build (on an Apple-Silicon Mac)

Prerequisites: Xcode Command Line Tools, `uv` (0.11.19+), Rust (≥ 1.77.2) with
`cargo-tauri` (`cargo install tauri-cli --version '^2'`), Node 18+.

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Dylan Schempp (TEAMID)"
export APPLE_NOTARY_KEYCHAIN_PROFILE=scuffedos-notary   # xcrun notarytool store-credentials
bash scripts/build-app.sh
```

This vendors PostgreSQL 17.10.0 + pgvector 0.8.4 (`scripts/vendor-postgres.sh`),
true-installs CPython 3.14.5 + backend deps incl. `cryptography` and `keyring`
(`scripts/vendor-python.sh`), builds the launcher stub, renders the icon, builds
the frontend, runs `cargo tauri build`, and — with both variables above exported
— signs, notarizes and staples via `scripts/sign-notarize.sh`. With
`APPLE_SIGNING_IDENTITY` unset that last stage is skipped and the output is
unsigned. Output:

```
src-tauri/target/release/bundle/macos/ScuffedOS.app   (~250–350 MB)
```

## Incremental rebuild

`scripts/build-app.sh` always re-vendors both runtimes, so running it end to end
is the safe path. When re-running `cargo tauri build` by hand, the vendored trees
may be reused **only** under these rules — Tauri bundles them verbatim, so a
stale tree ships:

- **`build/py`** — reuse only if `backend/requirements.txt` **and**
  `scripts/vendor-python.sh` are both older than `build/py.stamp`. Otherwise
  `rm -rf build/py && bash scripts/vendor-python.sh`.
- **`build/pgsql`** — reuse only if `scripts/vendor-postgres.sh` is unchanged
  since that tree was built. Otherwise `rm -rf build/pgsql && bash
  scripts/vendor-postgres.sh`.

`build-app.sh` enforces the Python half: step `[5b/7]` refuses to build against a
`build/py` older than either input ("vendored Python is stale") and runs
`scripts/check_vendored_deps.py` against it, and step `[6b/7]` runs the same
check against the interpreter *inside the bundle* before signing, so an .app
missing a dependency never reaches notarization. That guard was absent when the
shipped app was rebuilt against a `build/py` vendored before `phonenumberslite`
was added: contacts sync raised ImportError in the .app while every test passed.

## First launch (Gatekeeper / quarantine)

A signed + notarized build opens with a normal double-click — Gatekeeper
validates the stapled ticket offline, with no prompt and no bypass. Verify with:

```bash
spctl -a -vvv /Applications/ScuffedOS.app   # → accepted / Notarized Developer ID
```

An **unsigned** build (`APPLE_SIGNING_IDENTITY` unset) still needs a one-time
bypass on first launch:

- **Right-click the app → Open → Open** (do this once; subsequent launches are
  a normal double-click), or
- `xattr -dr com.apple.quarantine /path/to/ScuffedOS.app`

Ad-hoc signing does **not** remove quarantine — only Developer ID + notarization
does.

## Per-user data layout

All state lives under `~/Library/Application Support/ScuffedOS/`:

```
ScuffedOS/
├─ pgsql/         extracted Postgres tree (copied from the bundle on first run)
├─ pgdata/        the initdb data directory (your database)
├─ run/           Unix-domain socket dir for Postgres
├─ logs/          pg.log, backend.log
├─ data/          task attachments + the Mem0 history file
├─ secrets.enc    AES-256-GCM encrypted secrets vault (API keys + OAuth tokens)
├─ vault.salt     per-install random salt for key derivation (non-secret)
└─ config.json    non-secret app config
```

## Secrets & Settings

API keys and OAuth credentials are entered **in-app under Settings** — never in
a file. They are stored in a **machine-bound AES-256-GCM vault** (`secrets.enc`),
keyed by HKDF-SHA256 over this Mac's hardware UUID plus a per-install salt. The
32-byte vault key is additionally wrapped in one macOS Keychain item, so the OS
encrypts the master key at rest (at most one "Always Allow" prompt per app
update). Nothing is uploaded.

If you move the app to different hardware, the vault can no longer decrypt
(the hardware UUID changed). Settings detects this and shows a
**re-authenticate** flow — re-paste your keys to repair the vault.

### Publishing privacy-policy changes
`docs/privacy-policy.md` is the **canonical** copy. When it changes (e.g. the M8
vault disclosure), its two public mirrors — the GitHub gist and the
scuffed-corporation website `/privacy/` — go stale until you run the
`publish-privacy-policy` skill. After merging any privacy-policy change, run that
skill to sync both mirrors and bump the live effective date.

## Acceptance smoke (a fresh app on a clean machine)

1. `rm -rf ~/Library/Application\ Support/ScuffedOS` (fresh first-run state).
2. Turn networking **off**. Right-click▸Open the app.
3. Within ~5–15s the window shows the dashboard; every live screen
   (Home/Calendar/Tasks/Habits/Nutrition/Second Brain, plus Finance/Email/School/
   Fitness) and the Claude assistant render — offline.
4. Open **Settings**, paste an Anthropic key, Save; confirm the assistant works.
5. Quit and relaunch: your data persists, keys survive (no re-prompt storm).
6. Confirm no orphaned `postgres` after quit:
   `pgrep -fl "postgres.*ScuffedOS/pgdata" || echo clean`.

## Troubleshooting

On a startup failure the shell opens a **diagnostic window** with the tails of
`backend.log` and `pg.log`. The same files under `logs/` are the first place to
look. A leftover `postmaster.pid` from a hard-kill is cleared automatically on
the next launch (stale-pid recovery).
