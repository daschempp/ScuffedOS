# People / Contacts (M10) hardening — implementation plan

**Date:** 2026-09-21 · **Branch:** `m10-people-hardening` (off `origin/main` `7a25c0f`) ·
**Spec:** `docs/superpowers/specs/2026-07-13-people-crm-contacts-slice1-design.md`
(the slice-1 design is the binding authority for contacts-sync semantics) ·
**Source of the items:** the 2026-09-13 program audit, section M10
(https://claude.ai/code/artifact/af4d43bc-7f2a-4d87-8e30-3e6b3e9cf8cc).

## Context

Slice 1 of People/CRM + Apple Contacts is on main (PR #18). The audit found
that the *packaged* app cannot import contacts (a stale vendored Python without
`phonenumbers`), that its "Grant Full Disk Access" button is dead (the
`x-apple.systempreferences:` scheme is not in the Tauri opener allowlist),
that the manual FDA acceptance tests fail even on a working machine, and a
cluster of deferred review minors in the sync engine. This plan closes every
agent-doable M10 item that does not depend on PR #22 (`fix/people-gaps`).

Out of scope here (tracked in the audit, need PR #22 or a user decision):
the `list_people` cursor, the `update_person` wording, `docs/assistant.md`
People tools, the CRM search index, the app-wide focus ring, ZLINKID de-dup,
iMessage slice 2, the actual rebuild + FDA gate on hardware.

## Global Constraints

- **Base:** `origin/main` `7a25c0f`. PR #22's People tools and CRM search are
  NOT on this branch. Do not touch `backend/app/tools.py`; do not add an
  Alembic migration (head stays `0011`, single head).
- **Git:** implementers never run a writing git command (`add`, `commit`,
  `stash`, `checkout`, `switch`, `reset`, `rebase`, `clean`, `worktree`).
  Read-only git (`status`, `diff`, `log`, `show`) is fine. The controller
  commits.
- **Parallel work:** other implementers are editing other files in this same
  worktree at the same time. Touch only the files in your task's **Owns**
  list. If a test outside your files fails, re-run it once; if it still fails
  and the file is not yours, record it in your report and move on.
- **Backend tests:** from `backend/`:
  `/Users/dylanschempp/PycharmProjects/ScuffedOS/.venv/bin/python -m pytest -q -p no:cacheprovider <files>`
  while iterating; the full suite once before reporting. The suite must stay
  green with no new skips (the only skips are the 4 `manual` acceptance tests
  and the PG-only test). Test output must be pristine — no new warnings.
- **Frontend tests:** from `frontend/`: `npx vitest run` (baseline 9/9) and
  `npm run build` whenever a `.jsx`/`.js`/`.css` file changes.
- **TDD** for every behavior change: failing test first; RED/GREEN evidence
  in the report.
- **Never:** launch `/Applications/ScuffedOS.app` or any bundle; read the real
  `~/Library/Application Support/AddressBook`; set `RUN_MACOS_ACCEPTANCE`;
  run `open`; run `cargo tauri build`, `scripts/build-app.sh`,
  `scripts/vendor-python.sh` or `scripts/vendor-postgres.sh` end-to-end (they
  download toolchains). Shell scripts are verified with `bash -n` and by
  unit-testing the Python they call.
- **Docs are dated snapshots:** the 2026-07-13 plan/spec are edited only for
  the fence fix in Task 1. Living docs (`docs/people.md`, `docs/ship.md`) get
  their "updated" date set to 2026-09-21 where such a header exists.
- **Environment names:** `Settings` has no `env_prefix`; a field
  `app_support_dir` binds the env var `APP_SUPPORT_DIR`, `addressbook_root`
  binds `ADDRESSBOOK_ROOT`, etc.

## Task 1: Small isolated fixes (batch)

**Owns:** `src-tauri/capabilities/default.json`,
`frontend/src/screens/ConnectorsPanel.jsx`,
`frontend/src/screens/__tests__/ConnectorsPanel.test.jsx`,
`docs/superpowers/plans/2026-07-13-people-crm-contacts-slice1.md`.

Three independent edits. Each must appear in the diff.

### 1a — Allow the Full Disk Access deep link in the Tauri opener capability

`frontend/src/screens/ConnectorsPanel.jsx:34-35` opens
`FDA_DEEP_LINK = 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'`
through `@tauri-apps/plugin-opener`'s `openUrl`. The capability
`src-tauri/capabilities/default.json` grants only `opener:default`, whose
URL scope is `mailto:`/`tel:`/`http(s)`, so in the packaged app the button
silently does nothing.

Add, keeping `opener:default` (OAuth relies on its https/mailto scope), a
scoped allow entry in the `permissions` array:

```json
{
  "identifier": "opener:allow-open-url",
  "allow": [{ "url": "x-apple.systempreferences:*" }]
}
```

Update the capability's `description` to mention the FDA deep link.
Verify: the file parses (`python3 -m json.tool`), and the permission shape
matches tauri-plugin-opener 2.x — check the crate's permission files if they
are cached locally under `~/.cargo/registry/src/*/tauri-plugin-opener-2*/`
(look for `allow-open-url` and its `allow: [{url}]` scope), or
`src-tauri/gen/schemas/desktop-schema.json` if present. Do not run a cargo
build. If neither source is available, say so in the report.

### 1b — Drop the dead `sync_status === 'unsupported'` projection

`ConnectorsPanel.jsx:58`:
`if (c.configured === false || c.sync_status === 'unsupported') return 'unsupported'`.
The backend never emits a `sync_status` of `'unsupported'` — verify against
the values `apply_contacts_snapshot` writes (`backend/app/store.py`, the
`_FAILED_MAP` table near line 542 and the branch above it: `ready`, `error`,
`stale`, `access_denied`, `disabled`). Keep the `configured === false`
projection and the `unsupported` title/icon/tint. Fix the comment at
`:54-55` so it no longer claims an UNSUPPORTED_SCHEMA snapshot yields that
status.

Test (vitest, in the existing `ConnectorsPanel.test.jsx`, following its
current mocking pattern): a `macos_contacts` connector with
`configured: true`, `access: 'denied'` and `sync_status: 'unsupported'`
renders the access ("Full Disk Access is off.") state, not the
"isn't available on this device" copy; and `configured: false` still renders
the unavailable copy. Write the first assertion before changing the code and
confirm it fails.

Run `npx vitest run` and `npm run build`.

### 1c — Balance the unterminated code fence in the slice-1 plan

`docs/superpowers/plans/2026-07-13-people-crm-contacts-slice1.md` has an odd
number of ``` lines (187), which breaks the awk task-brief extractor for
every task after Task 8. The unterminated block ends just above the
`> **Note:** store.count_people(...)` paragraph (around line 4202: the block
whose last code line is `getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT)`
followed by `)`). Insert the missing closing fence there. Verify by
(1) the fence count becoming even, and (2) running the extractor for a task
after Task 8, e.g.
`bash /Users/dylanschempp/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/subagent-driven-development/scripts/task-brief <plan> 9 /tmp/t9.md`
and checking the output contains only Task 9's text. Change nothing else in
that file.

## Task 2: Vendored-runtime guard — a stale `build/py` can never be bundled again

**Owns:** `scripts/check_vendored_deps.py` (new), `scripts/vendor-python.sh`,
`scripts/build-app.sh`, `backend/tests/test_vendored_deps_guard.py` (new),
`docs/ship.md`.

**Why:** `scripts/vendor-python.sh` installs `backend/requirements.txt` into
`build/py`; Tauri bundles `build/py` verbatim (`src-tauri/tauri.conf.json`
`bundle.resources`). The installed app was built by re-running
`cargo tauri build` against a `build/py` vendored before `phonenumberslite`
was added, so every contacts sync in the .app raises ImportError. The smoke
import at `scripts/vendor-python.sh:122-130` is a hard-coded tuple that never
learned about the new dependency.

### 2a — `scripts/check_vendored_deps.py`

Python 3.11+ stdlib only. Two public functions plus a CLI:

- `parse_requirement_names(text: str) -> list[str]` — from requirements-file
  text, return the PEP 503-normalized project names (lowercase; runs of
  `-`, `_`, `.` collapsed to `-`), stripping extras (`psycopg[binary]` →
  `psycopg`), version specifiers, environment markers (`; sys_platform ==
  "darwin"`), inline comments, blank lines. Raise `ValueError` on
  `-r`/`-e`/`--` option lines and on URLs — this repo's file has none and the
  checker must not silently ignore something it cannot verify.
- `missing_distributions(names: list[str], site_packages: str) -> list[str]`
  — the names with no installed distribution under that directory, using
  `importlib.metadata.distributions(path=[site_packages])` (distribution
  lookup, NOT module import: the dist name and the module name differ —
  `phonenumberslite` provides `phonenumbers`).
- CLI: `check_vendored_deps.py --requirements PATH (--site-packages DIR |
  --python EXE) [--extra SPEC]...`. `--python` resolves the site-packages
  directory by asking that interpreter (`sysconfig.get_paths()["purelib"]`)
  and also runs, inside that interpreter, an import smoke of
  `MODULES = ("psycopg", "pydantic_core", "fastapi", "uvicorn", "alembic",
  "cryptography", "keyring", "phonenumbers")` (the old tuple plus the one
  that bit). `--extra` adds specs that are not in the requirements file
  (vendor-python.sh's `EXTRA_DEPS`). Exit 0 and print nothing on success;
  exit 1 listing every missing distribution / failed import on one line each.

Tests (`backend/tests/test_vendored_deps_guard.py`, import the script via
`importlib.util.spec_from_file_location` from
`Path(__file__).resolve().parents[2] / "scripts" / "check_vendored_deps.py"`):
name parsing (extras, specifiers, markers, comments, normalization of
`Pydantic_Settings` → `pydantic-settings`); `ValueError` on `-r other.txt`;
`missing_distributions` against a `tmp_path` site-packages holding fake
`Foo_Bar-1.0.dist-info/METADATA` (`Name: Foo_Bar`) → `foo-bar` present,
`missing` missing; the CLI via `subprocess.run([sys.executable, script,
"--requirements", req, "--site-packages", dir])` returning 1 and naming the
missing one, and 0 when all present. Also assert the real
`backend/requirements.txt` parses without error and includes
`phonenumberslite`.

### 2b — Wire it into the build

- `scripts/vendor-python.sh`: replace the hard-coded `find_spec` tuple block
  with one call:
  `python3 "$ROOT/scripts/check_vendored_deps.py" --requirements "$ROOT/backend/requirements.txt" --python "$OUT/bin/python3" --extra "uvicorn[standard]" --extra cryptography --extra keyring`
  (derive the `--extra` list from the existing `EXTRA_DEPS` array rather than
  repeating the literals). Keep writing `build/py.stamp` only after the
  check passes.
- `scripts/build-app.sh`: add a preflight immediately before the
  `[6/7] cargo tauri build` step that (1) fails with
  `"vendored Python is stale — rm -rf build/py && bash scripts/vendor-python.sh"`
  if `backend/requirements.txt` or `scripts/vendor-python.sh` is newer than
  `build/py.stamp` (mtime; `[ file -nt stamp ]`), and (2) runs the checker
  against `build/py/bin/python3` with the same `--extra` list. After
  `cargo tauri build` and before the sign step, run the checker once more
  against the bundle's interpreter
  (`src-tauri/target/release/bundle/macos/ScuffedOS.app/Contents/Resources/py/bin/python3`)
  so a bundle missing a dependency never reaches signing. Keep the existing
  step numbering readable (renumber or add `[5b/7]`-style labels — your call,
  say which).
- Verify both scripts with `bash -n`. Do not execute them.

### 2c — `docs/ship.md`

Add an `## Incremental rebuild` section stating the rule: reuse `build/py`
only if `backend/requirements.txt` and `scripts/vendor-python.sh` are both
older than `build/py.stamp`; reuse `build/pgsql` only if
`scripts/vendor-postgres.sh` is unchanged since it was built; otherwise
`rm -rf build/py && bash scripts/vendor-python.sh` (the full
`scripts/build-app.sh` always re-vendors). Mention that `build-app.sh` now
refuses a stale `build/py` and re-checks the bundle. Correct the "unsigned"
claims (`docs/ship.md:3`, `:8`, the `## First launch (Gatekeeper /
quarantine)` section) to describe the signed + notarized path
(`scripts/sign-notarize.sh` with `APPLE_SIGNING_IDENTITY` and
`APPLE_NOTARY_KEYCHAIN_PROFILE` exported; the unsigned bypass remains the
fallback when the identity is unset). Do not rewrite the rest of the document.

## Task 3: Make the manual FDA acceptance tests pass on a correctly working machine

**Owns:** `backend/tests/test_macos_contacts_acceptance.py`,
`backend/tests/test_acceptance_helpers.py` (new).
Read `backend/tests/conftest.py:98-108` (the autouse
`contacts_photos_tmpdir` fixture) but do not modify conftest.

**Why:** the four `manual`-marked tests are the only acceptance record for
the signed-bundle FDA gate, and as written they fail even when everything
works: test 3 writes photos to a cwd-relative `backend/contact_photos`; test
4 reads the App Support root that the autouse fixture has just redirected to
a per-test tmp dir; test 1 passes when Full Disk Access was granted to
Terminal rather than the app; test 2 shells out to `open`, which bypasses the
app's own button (the thing that was actually broken).

### 3a — A real-App-Support fixture that runs after the autouse override

In the acceptance module add a function-scoped fixture `real_app_support`
that **requests `contacts_photos_tmpdir`** (so pytest sets it up after the
autouse override) and then sets `settings.app_support_dir` and
`settings.contacts_photos_dir` to the real configured values, restoring both
on teardown. Real values come from a helper
`real_settings_values() -> tuple[str, str]` in
`backend/tests/test_acceptance_helpers.py` that instantiates a fresh
`app.config.Settings()` (this honours `APP_SUPPORT_DIR` / a `.env` and the
class default `~/Library/Application Support/ScuffedOS`) and returns
`(app_support_dir, contacts_photos_dir)`. Note `Settings` has no
`env_prefix` — the env var is `APP_SUPPORT_DIR`, not the `SCUFFEDOS_…`
name the audit guessed.

Ordinary (non-manual) tests in `test_acceptance_helpers.py`: with
`monkeypatch.setenv("APP_SUPPORT_DIR", "/tmp/x")` the helper returns
`/tmp/x`; with it unset (and `monkeypatch.delenv`) it returns the class
default (`Settings.model_fields["app_support_dir"].default`); and a test
that uses the `real_app_support` fixture (import it into the module so pytest
sees it) and asserts `settings.app_support_dir` equals the helper's value
while the fixture is active — i.e. the override really wins over the autouse
tmp dir. Keep `.env` out of it: pass `_env_file=None` when constructing
`Settings` in the tests if the helper takes that argument, or document why
not.

### 3b — Test 3 and test 4

Test 3 (`test_live_wal_read_returns_current_contacts`): use the fixture; call
`read_snapshot(region=settings.contacts_default_region, photos_dir=settings.contacts_photos_root())`.
Test 4 (`test_photos_land_under_app_support_not_repo`): use the fixture; read
`settings.contacts_photos_root()`; make it independent of test 3 by
performing its own `read_snapshot(..., photos_dir=settings.contacts_photos_root())`
first, then assert the directory exists under the real App Support root and
holds at least one file with a detected image extension. Both keep
`macos_contacts.configure()` (real detection).

### 3c — Test 1 and test 2

Test 1 (`test_fda_responsible_process_is_the_signed_bundle`): `probe_access()`
from pytest proves only that the pytest process has FDA. Make it skip unless
`os.environ.get("RUN_INSIDE_BUNDLE") == "1"`, with a reason that gives the
real check: `pgrep -f scuffedos-backend`, then
`sudo launchctl procinfo <pid> | grep -i responsible` must name
`/Applications/ScuffedOS.app`. Keep the `probe_access() == "granted"`
assertion for the in-bundle case.

Test 2 (`test_system_settings_deep_link_opens_full_disk_access`): remove the
`subprocess.run(["open", url])`. Replace the body with an unconditional
`pytest.skip(...)` whose reason is the manual checklist: in the packaged
app with FDA off, click "Grant Full Disk Access" on the Apple Contacts card
in Settings › Connectors; the Privacy & Security › Full Disk Access pane
must open; the scheme is allowed by `src-tauri/capabilities/default.json`
(`opener:allow-open-url`, `x-apple.systempreferences:*`, Task 1). Update the
module docstring to match.

Verify: `pytest tests/test_macos_contacts_acceptance.py tests/test_acceptance_helpers.py -rs -p no:cacheprovider`
collects 4 skipped manual tests with no errors plus the new passing helper
tests; then the full suite.

## Task 4: Contacts sync hardening (backend)

**Owns:** `backend/app/store.py` (contacts/people region only),
`backend/app/contacts_sync.py`, `backend/app/providers/macos_contacts.py`,
`backend/app/config.py`, `backend/app/main.py`,
`backend/app/routers/connectors.py`, `backend/app/routers/people.py`,
`backend/.env.example`, `docs/people.md`, and these tests:
`backend/tests/conftest.py`, `test_contacts_ci.py`, `test_contacts_sync.py`,
`test_people_store.py`, `test_people_api.py`, `test_connectors_contacts.py`,
`test_macos_contacts_reader.py`, `test_macos_contacts_photos.py`.

Nine deferred review minors from the slice-1 final review plus one config
decision. Each behavior change starts with a failing test in the test file
that already covers that code (follow its existing fixtures/seams — the
`macos_contacts.configure(fake_snapshot=…, platform=…)` seam, the
`contacts_sync.configure(...)` seam, the SQLite store fixtures).

### 4a — Persist `normalization_region` once, everywhere

`Store.enable_contacts` (store.py ~2247) guards `if not row.normalization_region`;
`Store.set_contacts_enabled(True, region=...)` (~2210-2225) does not — it
patches the region unconditionally through `set_contacts_state`. Make the
toggle path honour persist-once too: an existing region is never overwritten
by enabling. Test: state with region `"GB"`, `set_contacts_enabled(True,
region="US")` → still `"GB"`; with no region → `"US"`.

### 4b — `resolve_handle` returns each person once

`Store.resolve_handle` (store.py ~2160) joins `PersonHandle`; a person carrying
the same normalized value under two handle rows (e.g. the same number
labelled mobile and iPhone) comes back twice. De-duplicate preserving the
existing order (a `seen` set over `Person.id` after the query, or DISTINCT
on the Person columns — say which and why). Test: one person, two handle
rows with the same normalized value → one result.

### 4c — `probe_access` probes every discovered store

`macos_contacts.probe_access` (~494) opens only `paths[0]`. Probe every path
from `_store_paths(root)`: `"denied"` if any store raises
`PermissionError` with `EPERM`/`EACCES`; else `"unknown"` if any other
`OSError` (or a non-EPERM PermissionError) occurred; `"granted"` only when
every store opened. Tests: monkeypatch `_store_paths` to return two
`tmp_path` files; make the second raise (monkeypatch `builtins.open` or
`chmod 000` — pick the one that is deterministic on both macOS and Linux CI,
and remember CI may run as root where `chmod 000` still reads) and drive the
darwin branch through the seam (`configure(platform="darwin")` if the seam
supports it — read `configure`'s signature at ~133).

### 4d — Tests for the `_thumbnail_bytes` tag `0x02` branch

`macos_contacts._thumbnail_bytes` (~247) resolves external-data refs from
`<parent>/.<stem>_SUPPORT/_EXTERNAL_DATA/<name>`. No test exercises it. Add,
in `test_macos_contacts_photos.py`: a valid ref resolves to the file's bytes
when they are a detected image; a ref to a missing file → `None`; names with
`/`, leading `.`, or empty → `None` (path-traversal guard); a ref whose
bytes are not an image → `None`. Build the layout under `tmp_path`.

### 4e — `tick()` survives a crashing reader

`contacts_sync.tick` (~77-90) wraps `read_snapshot` and substitutes an
`IO_ERROR` snapshot with `error="reader failed"`. Test it: consent on, real
tick path (`contacts_sync.configure(None)` per its docstring), monkeypatch
`macos_contacts.read_snapshot` to raise `RuntimeError`; assert the result
status is what `_FAILED_MAP[IO_ERROR]` dictates (`"error"`), no person rows
were written, `get_contacts_state()["last_error"] == "reader failed"`, and
nothing raised.

### 4f — Partial applies: wider per-record net, no `last_sync_at` advance

`Store.apply_contacts_snapshot` (~1919-1951): (1) the per-record except
becomes `(ValueError, TypeError, AttributeError, KeyError)` — still never
SQLAlchemy errors, which must roll the whole batch back; (2) on a partial
apply `state.last_sync_at` is left at its previous value (it means "last
successful sync") and the returned `SyncResult.last_sync_at` reflects that;
`state.access` stays `"granted"` (the read did succeed — ruling recorded in
the ledger). Tests: extend the existing partial-apply test (find it in
`test_people_store.py` / `test_contacts_sync.py`) so one record raises
`AttributeError` from `_apply_person` → status `"partial"`, the good records
are committed, `last_sync_at` unchanged from a prior successful sync,
`access == "granted"`.

### 4g — `addressbook_root` becomes a real setting

`contacts_sync.py:82` and `routers/connectors.py:96` read
`getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT)`, but
`config.py` never defines it. Add
`addressbook_root: str = "~/Library/Application Support/AddressBook"` to
`Settings` next to the other contacts fields (config must not import the
provider; add a comment that it mirrors `macos_contacts.DEFAULT_ROOT` and a
test asserting the two literals are equal), replace both `getattr` fallbacks
with `settings.addressbook_root`, document it in `docs/people.md` `## Config`,
and add a commented `# ADDRESSBOOK_ROOT=` line in a small `# Contacts` block in
`backend/.env.example` (the file has no contacts block yet).

### 4h — Delete the dead `_configured("macos_contacts")` branch

`routers/connectors.py:48-49`. Confirm no caller passes `"macos_contacts"`
(the connectors list loop at ~140-147 and every `_configured(` call);
`_contacts_connector` uses `_contacts_configured()` directly. If a caller
exists it is not dead — keep it and say so in the report.

### 4i — The background loop always runs; consent gates every tick

Ruling (audit item "periodic 6h re-sync cannot be turned on from the
packaged app", option a): remove the `contacts_sync_enabled` env flag
entirely. `main.py:98-99` creates the task unconditionally (same shape as the
other loops, but without a flag); `contacts_sync.run_loop` drops the flag
check and **sleeps `settings.contacts_sync_seconds` before the first tick**
(the enable endpoint already kicks the first sync, and this keeps every
TestClient lifespan and app startup free of AddressBook reads). Remove the
field from `config.py`, the save/restore in `conftest.py:70-86`, and the
assertion at `test_contacts_ci.py:55` (replace it with one that still
proves CI safety — e.g. that `tick()` with consent off performs no
`read_snapshot` call, using a monkeypatched reader that would raise). Grep
`docs/` (excluding `docs/superpowers/`), `README.md`, `backend/.env.example`
for `contacts_sync_enabled` / `CONTACTS_SYNC_ENABLED` and fix each mention;
replace the `docs/people.md:126` bullet with a sentence saying the loop is
always started and consent-gated per tick by `contacts_sync_state.enabled`,
with no env kill-switch.

Test (`test_contacts_sync.py`): with `contacts_sync_seconds` patched to a few
milliseconds and a fake `tick` installed through `contacts_sync.configure(fake)`,
`run_loop` does not call tick before the first sleep, calls it afterwards,
survives a tick that raises, and stops cleanly on `task.cancel()`.

### 4j — Verify

Full backend suite green and pristine; `alembic heads` from `backend/` still
prints exactly one head (`0011`).
