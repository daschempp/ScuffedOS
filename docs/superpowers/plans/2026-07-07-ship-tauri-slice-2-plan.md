# M8 Ship/Tauri — Slice 2 Implementation Plan

> For agentic workers: execute top to bottom. Each task is self-contained. TDD-able Python tasks (1–5) come first so `cd backend && python -m pytest` stays green throughout; the frontend task (6) is build-verified; the Tauri polish task (7) is `cargo check`/run-verified; the docs tasks (8–9) are text edits; the final spike (10) is run-based with a concrete pass/fail procedure and closes the slice DoD. Do not skip the commit step at the end of each task. Everything new lives behind the vault seam / the `SCUFFEDOS_MANAGED_PG` flag, so the existing SQLite/Postgres test path and the slice-1 baseline are untouched. This slice depends on Slice 1, which is **already landed on this branch** (`m8-ship-tauri-design`, tip `08d2473`): `app/localdb.py`, `/health`, the lifespan wiring, the Tauri scaffold, and the vendor scripts all exist.

**Goal**
Add the in-app **Settings + secrets** surface and first-run polish. A new `app/secrets.py` `SecretsVault` stores API keys and OAuth credentials in a machine-bound **AES-256-GCM** vault at `~/Library/Application Support/ScuffedOS/secrets.enc` (dir `0700` / file `0600`), keyed by **HKDF-SHA256** over the Mac `IOPlatformUUID` plus a per-install random salt (`vault.salt`), zero prompts, surviving rebuilds. A config seam resolves every secret through the vault first, falling back to `.env`/process env so **dev and CI are byte-for-byte unchanged**. A new `GET/PUT /api/settings/secrets` router exposes presence/masked state (never raw values) and writes new values. A new `SettingsScreen.jsx` (sidebar entry + icon) lets the user paste/update keys, nudges first-run onboarding, and drives a re-authenticate recovery path when the vault fails to decrypt (e.g. the `IOPlatformUUID` changed after a hardware move). Polish: a Tauri diagnostic error window on health-gate timeout that surfaces `backend.log`/`pg.log`, plus branding/quit-relaunch UX. Docs: a new `docs/ship.md`, the stale M7→M8 Tauri-reference fixes, a README "Desktop app (M8)" section, and a one-line privacy-policy vault disclosure.

**Architecture**
`SecretsVault` (`app/secrets.py`) is the single read/write choke point. Key derivation has a **test/dev-safe fallback**: the machine id is resolved by an injectable seam (`machine_id()` reads `IOPlatformUUID` on macOS; a `SCUFFEDOS_VAULT_MACHINE_ID` env override or an explicit constructor argument short-circuits it so unit tests round-trip on ubuntu CI with no `ioreg`). The 32-byte derived key is optionally **wrapped in one `keyring` item** (OS-managed at-rest encryption of the master key) — but only in the packaged/managed path: when `keyring` is unavailable or its backend fails (ubuntu CI), the vault degrades to a **file-only key** and never crashes at import. The config seam (`app/config.py` → a small `_vault_read` helper reading a lazily-constructed process-wide vault) resolves `anthropic_api_key`, `openai_api_key`, `fdc_api_key`, `whoop_client_id/secret`, `google_client_id/secret`, `plaid_client_id/secret` from the vault **only when the field is otherwise empty**, so a value present in `.env`/env always wins and the test suite (which sets fields directly) is unaffected. The `SettingsScreen` follows the existing `FinanceScreen` template and the shared `Card`/`Button`/`Icon` kit; the API base already targets the Tauri port (slice 1) — do not touch that.

**Tech Stack**
Backend: Python 3.14, FastAPI, pydantic-settings v2, `cryptography` (`AESGCM` + `HKDF`), `keyring` (macOS-only, optional), pytest. Shell: Tauri v2, `tauri-plugin-shell` v2, Rust (edition 2021). Frontend: Vite 6 + React 18 (existing), the shared `ui.jsx`/`Icon.jsx` kit. Vendoring: `cryptography` is already forward-vendored in `scripts/vendor-python.sh` (`EXTRA_DEPS`); this slice adds `keyring` there and to `backend/requirements.txt`, and adds a `cryptography`/`keyring` smoke import.

## Global Constraints

- **Platform:** macOS **arm64 only**, **unsigned** (ad-hoc `codesign -s -`). The vault is machine-bound and prompt-free; the single-Keychain-item vault-key wrapping is the only place `keyring` is touched, and it is **gated** to the packaged path.
- **Pinned versions (use verbatim):** PostgreSQL **17.10.0** (theseus-rs, `aarch64-apple-darwin`); pgvector **0.8.4**; CPython **3.14.5** via `uv 0.11.19` (`--managed-python 3.14`); `py-app-standalone` true-install (never a venv); **Tauri v2** + `tauri-plugin-shell` v2; **Rust ≥ 1.77.2**; **`cryptography`** (latest cp314 arm64 wheel), **`keyring`** (latest). Target triple **aarch64-apple-darwin**.
- **`SCUFFEDOS_MANAGED_PG` semantics (unchanged from slice 1):** unset/`false` (dev, CI, tests) → external `DATABASE_URL`, no managed Postgres, zero behavior change. `true`/`1` (packaged app only) → managed Postgres under `app_support_dir`. This slice reuses `settings.app_support_dir` for the vault location and reuses this flag **only** to decide whether to engage the `keyring`-wrapped key (packaged) vs the file-only key (dev/CI).
- **Vault key derivation MUST have a test/dev-safe fallback.** Unit tests round-trip the vault on ubuntu CI with **no `ioreg` and no `keyring` backend**: the machine id is injectable (constructor arg or `SCUFFEDOS_VAULT_MACHINE_ID` env), and `keyring` wrapping is skipped/degraded when unavailable. **Nothing may crash at import** if `ioreg`/`keyring` are absent.
- **Config seam is empty-only override.** The vault fills a secret field **only when it is empty** after env/`.env` load. A value from `.env`/env or a direct test assignment always wins, so the suite's `monkeypatch.setattr(settings, ...)` and `.env` behavior are unchanged.
- **Suite stays green.** After every Python task (1–5) run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q` and report the pass count. The slice-1 baseline is expected to be **exactly 623 passed / 1 skipped** (project memory cites ~604/1 pre-slice-1); **confirm the actual number at Task 1, Step 1 and use it as the fixed anchor** for all later deltas (Task 2 +21, Task 3 +6, Task 4 +10, Task 5 +5 → 667/1 at slice end). New tests must never hard-fail or hard-skip on the SQLite default and must never touch the autouse `fresh_db` engine.
- **Branch:** all work lands on `m8-ship-tauri-design` (do NOT branch from `main`; slice 1 is not on `main`). The branch tip at the start of this slice is `08d2473`.

---

### Task 1: `keyring` dependency + vendor smoke-import (TDD the requirement, run-verify the vendor)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/requirements.txt` (append `keyring` after the httpx line at line 16; `cryptography` stays a vendor-only `EXTRA_DEPS` forward-vendor and is **not** added here — it is a Slice-2 import now, so add it too, see Step 3).
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-python.sh` (add `keyring` to `EXTRA_DEPS` at line 22; add `cryptography` + `keyring` to the smoke-import list at line ~127).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_secrets_deps.py`.

**Interfaces:**
- Produces: `cryptography` and `keyring` importable in the backend env (dev + packaged), and asserted present by a smoke test. No app code yet.
- Consumes: pip/uv for the dev install; `scripts/vendor-python.sh` `EXTRA_DEPS`/smoke for the packaged env.

- [ ] **Step 1:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5` and **record the exact baseline** — it should be **623 passed, 1 skipped** (the slice-1 tip). Write the actual number down here; if it is not 623/1, your branch/env diverges from this plan's expectation — report it before proceeding rather than eyeballing later deltas against a fuzzy number. This exact count is the fixed anchor every later Python task adds to (Task 2 +21, Task 3 +6, Task 4 +10, Task 5 +5).

- [ ] **Step 1a (verify slice-1 orphan-cleanup prerequisites):** This slice assumes slice-1's process-lifecycle safety nets are already on the branch. Confirm them before building on top:
```bash
grep -n 'atexit\|pg_ctl stop' /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/localdb.py
grep -n 'sysinfo' /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/src/lib.rs
grep -n 'postmaster.pid' /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/localdb.py
```
EXPECTED: the first grep shows the Python `atexit`/`pg_ctl stop` managed-Postgres shutdown; the second shows the Rust `sysinfo` orphan backstop; the third shows the stale-`postmaster.pid` recovery guarded before `pg_ctl start`. If any is absent, slice 1 is incomplete on this branch — STOP and land it first (the packaged app will orphan Postgres or fail to relaunch after a hard-kill without them). These are slice-1 code; this slice does not re-implement them, only depends on them.

- [ ] **Step 2:** Write the test. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_secrets_deps.py`:

```python
"""M8 Slice 2: the secrets vault depends on `cryptography` (AES-256-GCM + HKDF)
and, in the packaged app only, `keyring` (wrap the single vault key). Both must
be importable in the backend env so vault code never fails at import. keyring's
*backend* may be absent on ubuntu CI — that is handled in app/secrets.py, not
here; here we only assert the modules import."""

import importlib.util


def test_cryptography_importable():
    assert importlib.util.find_spec("cryptography") is not None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: F401


def test_keyring_importable():
    # The module must import even where no OS backend is configured (CI);
    # app/secrets.py degrades to a file-only key when keyring has no backend.
    assert importlib.util.find_spec("keyring") is not None
    import keyring  # noqa: F401
```

- [ ] **Step 3:** Run and confirm failure if the deps are missing from the dev env: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_secrets_deps.py -q`. If `cryptography`/`keyring` aren't installed in the dev venv, expect failures. Add both to `backend/requirements.txt` — after line 16 (`httpx>=0.27`) insert:

```
# Secrets vault (M8 Slice 2): AES-256-GCM + HKDF via cryptography; keyring
# wraps the single 32-byte vault key in one OS-keychain item in the packaged
# app (degrades to a file-only key where no backend exists, e.g. CI).
cryptography>=43
keyring>=25
```

Then install into the dev env: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pip install "cryptography>=43" "keyring>=25"`.

- [ ] **Step 4:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_secrets_deps.py -q` and confirm both pass.

- [ ] **Step 5:** Wire the packaged vendor path. Read `scripts/vendor-python.sh` line 22 to confirm the current `EXTRA_DEPS`, then change it from:
```bash
EXTRA_DEPS=("uvicorn[standard]" "cryptography")
```
to:
```bash
EXTRA_DEPS=("uvicorn[standard]" "cryptography" "keyring")
```

- [ ] **Step 6:** Add `cryptography` + `keyring` to the vendor smoke import. Read `scripts/vendor-python.sh` around line 127 to confirm the current tuple, then change the smoke-import line from:
```python
    importlib.util.find_spec(m) for m in ("psycopg", "pydantic_core", "fastapi", "uvicorn", "alembic")
```
to:
```python
    importlib.util.find_spec(m) for m in ("psycopg", "pydantic_core", "fastapi", "uvicorn", "alembic", "cryptography", "keyring")
```

- [ ] **Step 7:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Confirm baseline + 2 new tests. Report the pass count.

- [ ] **Step 8:** Commit.
```
git add backend/requirements.txt scripts/vendor-python.sh backend/tests/test_ship_secrets_deps.py
git commit -m "chore(ship): add keyring dep + cryptography/keyring vendor smoke

M8 Slice 2 secrets-vault deps. keyring wraps the single vault key in the
packaged app (degrades to file-only key on CI); cryptography was already
forward-vendored and is now a first-class runtime import.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `app/secrets.py` — `SecretsVault` AES-256-GCM + HKDF, machine-bound, injectable (TDD)

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/secrets.py`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_secrets_vault.py`.
- Reference only (no edit): `backend/app/localdb.py:290` (`resolve_paths` idiom for `~` expansion + `os.open` mode precedent), `backend/app/config.py` (`app_support_dir`, `scuffedos_managed_pg`).

**Interfaces:**
- Produces (in `app/secrets.py`):
  - `class VaultDecryptError(Exception)` — raised on GCM auth failure / unreadable ciphertext (drives the Settings re-auth path; never a bare crash upstream).
  - `class SaltCorruptedError(VaultDecryptError)` — raised when `vault.salt` exists but is not exactly 16 bytes (truncated/empty). Subclasses `VaultDecryptError` so the existing swallow/recover paths treat it as a decrypt failure (re-auth) instead of silently regenerating a salt and orphaning `secrets.enc`.
  - `machine_id(override: str | None = None) -> str` — returns `override` if given, else `os.environ["SCUFFEDOS_VAULT_MACHINE_ID"]` if set, else the parsed macOS `IOPlatformUUID`, else the string `"dev-fallback-machine-id"` (so no `ioreg` ⇒ still deterministic, never raises).
  - `class SecretsVault` with:
    - `__init__(self, root: str | os.PathLike, *, machine_id_override: str | None = None, use_keyring: bool = False)` — stores paths; does NOT touch disk or keyring at construction.
    - `derive_key(self) -> bytes` — 32-byte HKDF-SHA256 over `machine_id(...)` bytes + the per-install salt (read/created at `vault.salt`), `info=b"scuffedos-secrets-vault-v1"`. When `use_keyring` is true and a keyring backend is available, the derived key is wrapped/stored in one keyring item (`service="scuffedos-vault"`, `username="master-key"`); a keyring failure degrades silently to the file-derived key.
    - `read_all(self) -> dict[str, str]` — decrypt `secrets.enc`, return `{}` if absent; raise `VaultDecryptError` on a bad tag.
    - `write_all(self, values: dict[str, str]) -> None` — encrypt + atomically write `secrets.enc` at `0600`, dir at `0700`.
    - `get(self, key: str) -> str | None`; `set(self, key: str, value: str) -> None`; `present(self) -> dict[str, bool]`.
- Consumes: `cryptography.hazmat.primitives.ciphers.aead.AESGCM`, `cryptography.hazmat.primitives.kdf.hkdf.HKDF`, `cryptography.hazmat.primitives.hashes`, `os`, `json`, `secrets` (stdlib, for salt + nonce), `subprocess` (ioreg), `pathlib`, optional `keyring`.

- [ ] **Step 1:** Write the test file. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_secrets_vault.py`:

```python
"""M8 Slice 2 secrets vault: AES-256-GCM round-trip, wrong-key GCM failure,
0600 perms, empty-vault default, and the CI-safe machine-id fallback. Every
test injects an explicit machine id so it round-trips on ubuntu CI with no
ioreg and no keyring backend. Nothing here touches the DB or the fresh_db
engine."""

import os
import stat

import pytest

from app import secrets as vaultmod
from app.secrets import SecretsVault, VaultDecryptError


def _vault(tmp_path, mid="unit-test-machine"):
    return SecretsVault(tmp_path, machine_id_override=mid, use_keyring=False)


def test_machine_id_env_override(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_VAULT_MACHINE_ID", "from-env")
    assert vaultmod.machine_id() == "from-env"


def test_machine_id_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_VAULT_MACHINE_ID", "from-env")
    assert vaultmod.machine_id("explicit") == "explicit"


def test_machine_id_never_raises_without_ioreg(monkeypatch):
    # No env, and force the ioreg path to fail -> deterministic fallback string.
    monkeypatch.delenv("SCUFFEDOS_VAULT_MACHINE_ID", raising=False)
    monkeypatch.setattr(vaultmod, "_ioreg_platform_uuid", lambda: None)
    assert vaultmod.machine_id() == "dev-fallback-machine-id"


def test_empty_vault_reads_empty(tmp_path):
    assert _vault(tmp_path).read_all() == {}
    assert _vault(tmp_path).get("ANTHROPIC_API_KEY") is None


def test_roundtrip_set_get(tmp_path):
    v = _vault(tmp_path)
    v.set("ANTHROPIC_API_KEY", "sk-ant-123")
    v.set("OPENAI_API_KEY", "sk-oai-456")
    # A fresh instance on the same dir + machine id decrypts the same values.
    v2 = _vault(tmp_path)
    assert v2.get("ANTHROPIC_API_KEY") == "sk-ant-123"
    assert v2.get("OPENAI_API_KEY") == "sk-oai-456"
    assert v2.read_all() == {"ANTHROPIC_API_KEY": "sk-ant-123", "OPENAI_API_KEY": "sk-oai-456"}


def test_wrong_machine_id_fails_to_decrypt(tmp_path):
    _vault(tmp_path, mid="machine-A").set("K", "v")
    wrong = _vault(tmp_path, mid="machine-B")  # same salt file, different id
    with pytest.raises(VaultDecryptError):
        wrong.read_all()


def test_secrets_file_is_0600_and_dir_0700(tmp_path):
    v = _vault(tmp_path)
    v.set("K", "v")
    enc = tmp_path / "secrets.enc"
    assert enc.exists()
    assert stat.S_IMODE(enc.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_on_disk_format_is_nonce_ct_tag(tmp_path):
    v = _vault(tmp_path)
    v.set("K", "v")
    raw = (tmp_path / "secrets.enc").read_bytes()
    # 12-byte nonce prefix + AESGCM ciphertext(>=1) + 16-byte tag suffix.
    assert len(raw) >= 12 + 16 + 1


def test_present_masks_and_lists(tmp_path):
    v = _vault(tmp_path)
    v.set("ANTHROPIC_API_KEY", "sk-ant")
    v.set("OPENAI_API_KEY", "")  # explicitly-empty -> not present
    p = v.present()
    assert p["ANTHROPIC_API_KEY"] is True
    assert p["OPENAI_API_KEY"] is False


def test_set_overwrites_and_persists(tmp_path):
    v = _vault(tmp_path)
    v.set("K", "first")
    v.set("K", "second")
    assert _vault(tmp_path).get("K") == "second"


def test_salt_is_stable_across_instances(tmp_path):
    _vault(tmp_path).set("K", "v")
    salt1 = (tmp_path / "vault.salt").read_bytes()
    _vault(tmp_path).get("K")  # must not regenerate the salt
    salt2 = (tmp_path / "vault.salt").read_bytes()
    assert salt1 == salt2


def test_sequential_writes_use_fresh_nonces(tmp_path):
    # GCM nonce reuse under one key is catastrophic; every write_all must draw a
    # fresh 12-byte nonce. Two writes of the same plaintext must differ in the
    # nonce prefix (raw[:12]).
    v = _vault(tmp_path)
    v.set("K", "same-value")
    nonce1 = (tmp_path / "secrets.enc").read_bytes()[:12]
    v.set("K", "same-value")
    nonce2 = (tmp_path / "secrets.enc").read_bytes()[:12]
    assert nonce1 != nonce2


def test_derive_key_without_keyring_uses_file_key(tmp_path):
    # use_keyring=False must never touch keyring and returns a deterministic
    # file-derived key for a given (dir, machine id).
    v = SecretsVault(tmp_path, machine_id_override="k-off", use_keyring=False)
    k1 = v.derive_key()
    k2 = SecretsVault(tmp_path, machine_id_override="k-off", use_keyring=False).derive_key()
    assert k1 == k2
    assert len(k1) == 32


def test_derive_key_with_keyring_unavailable_degrades(tmp_path, monkeypatch):
    # use_keyring=True but the keyring backend raises -> silently degrade to the
    # file-derived key (this is the ubuntu-CI / locked-keychain path).
    import types

    fake = types.SimpleNamespace(
        get_password=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no backend")),
        set_password=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no backend")),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    v = SecretsVault(tmp_path, machine_id_override="k-degrade", use_keyring=True)
    file_key = SecretsVault(tmp_path, machine_id_override="k-degrade", use_keyring=False).derive_key()
    assert v.derive_key() == file_key


def test_vault_roundtrip_with_keyring_simulated(tmp_path, monkeypatch):
    # A fake in-memory keyring backend proves the keyring-wrapped path stores and
    # reuses one 32-byte hex item and round-trips a secret.
    import types

    store: dict[tuple[str, str], str] = {}
    fake = types.SimpleNamespace(
        get_password=lambda s, u: store.get((s, u)),
        set_password=lambda s, u, v: store.__setitem__((s, u), v),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    v = SecretsVault(tmp_path, machine_id_override="k-sim", use_keyring=True)
    v.set("K", "wrapped")
    assert len(store) == 1  # exactly one keyring item was written
    v2 = SecretsVault(tmp_path, machine_id_override="k-sim", use_keyring=True)
    assert v2.get("K") == "wrapped"


def test_keyring_malformed_entry_falls_back(tmp_path, monkeypatch, caplog):
    # A malformed keyring item (non-hex / wrong length) must not raise: degrade
    # to the file key and log a warning.
    import logging
    import types

    fake = types.SimpleNamespace(
        get_password=lambda *a, **k: "not-hex-zzzz",
        set_password=lambda *a, **k: None,
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    v = SecretsVault(tmp_path, machine_id_override="k-bad", use_keyring=True)
    file_key = SecretsVault(tmp_path, machine_id_override="k-bad", use_keyring=False).derive_key()
    with caplog.at_level(logging.WARNING, logger="scuffed_os.secrets"):
        assert v.derive_key() == file_key
    assert any("not valid hex" in r.message for r in caplog.records)


def test_ioreg_timeout_falls_back(monkeypatch):
    # A hung ioreg (TimeoutExpired) must degrade to the fallback id, not raise.
    import subprocess as _sp

    monkeypatch.delenv("SCUFFEDOS_VAULT_MACHINE_ID", raising=False)

    def _boom(*a, **k):
        raise _sp.TimeoutExpired(cmd="ioreg", timeout=5.0)

    monkeypatch.setattr(vaultmod.subprocess, "run", _boom)
    assert vaultmod._ioreg_platform_uuid() is None
    assert vaultmod.machine_id() == "dev-fallback-machine-id"


def test_truncated_salt_raises_error(tmp_path):
    from app.secrets import SaltCorruptedError

    v = _vault(tmp_path)
    v.set("K", "v")  # creates a valid 16-byte salt + secrets.enc
    # Corrupt the salt to a truncated length; the next derive must refuse to
    # silently regenerate (which would orphan secrets.enc).
    (tmp_path / "vault.salt").write_bytes(b"\x00\x01\x02")
    with pytest.raises(SaltCorruptedError):
        _vault(tmp_path).read_all()


def test_salt_file_corruption_detected(tmp_path):
    from app.secrets import SaltCorruptedError

    # An empty salt file is corruption, not "unset" — must raise, not regenerate.
    v = _vault(tmp_path)
    v.set("K", "v")
    (tmp_path / "vault.salt").write_bytes(b"")
    with pytest.raises(SaltCorruptedError):
        _vault(tmp_path).read_all()
```

- [ ] **Step 2:** Run and confirm failure (module missing): `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_secrets_vault.py -q`. Expect `ModuleNotFoundError: app.secrets`.

- [ ] **Step 3:** Implement the module. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/secrets.py`:

```python
"""M8 Ship/Tauri — machine-bound AES-256-GCM secrets vault (spec §4.5, §7).

Store of record: <app_support>/secrets.enc, dir 0700 / file 0600, on-disk
format nonce(12) || ciphertext || tag (AESGCM appends the 16-byte tag to the
ciphertext). The 32-byte key is HKDF-SHA256 over the Mac IOPlatformUUID plus a
per-install random salt (vault.salt). Machine-bound, prompt-free, survives
rebuilds. A decrypt failure (GCM auth fail / machine id changed) raises
VaultDecryptError, which the Settings screen turns into a re-authenticate flow
instead of crashing.

CI/dev safety: the machine id is injectable (constructor arg or the
SCUFFEDOS_VAULT_MACHINE_ID env var) so unit tests round-trip on ubuntu with no
ioreg; keyring wrapping is engaged only when use_keyring is set AND a backend
exists, otherwise it degrades to the file-derived key. Nothing here touches the
DB or imports app.config, so it is safe to construct from the config seam.

On-disk format (secrets.enc): 12-byte random nonce || AES-256-GCM ciphertext ||
16-byte auth tag. The nonce is fresh per encryption (secrets.token_bytes); the
tag is appended by AESGCM.encrypt(). read_all() slices raw[:12] as the nonce and
raw[12:] as the blob (ciphertext + tag). A fresh nonce every write is REQUIRED —
GCM nonce reuse under the same key is catastrophic; if a nonce pool is ever
added, it must never be shared with this vault.
"""

from __future__ import annotations

import json
import logging
import os
import secrets as _secrets
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_log = logging.getLogger("scuffed_os.secrets")

# The canonical set of secret field names the vault stores. Mirrors the
# secret-bearing config fields; the config seam (Task 3) maps settings fields to
# these keys. Kept here so the vault, the API, and the seam agree on one list.
SECRET_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "FDC_API_KEY",
    "WHOOP_CLIENT_ID",
    "WHOOP_CLIENT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "PLAID_CLIENT_ID",
    "PLAID_SECRET",
)

_HKDF_INFO = b"scuffedos-secrets-vault-v1"
_KEYRING_SERVICE = "scuffedos-vault"
_KEYRING_USER = "master-key"
_NONCE_LEN = 12


class VaultDecryptError(Exception):
    """The vault could not be decrypted (bad GCM tag / machine id changed)."""


class SaltCorruptedError(VaultDecryptError):
    """The per-install salt file exists but is not the expected 16 bytes.

    Subclasses VaultDecryptError so existing swallow/recover paths (the config
    seam, the Settings vault_ok banner) treat it as a decrypt failure and route
    to the re-authenticate flow, rather than silently regenerating a salt (which
    would derive a different key and orphan the existing ciphertext)."""


def _ioreg_platform_uuid() -> str | None:
    """Parse IOPlatformUUID from `ioreg -rd1 -c IOPlatformExpertDevice`.

    Returns None on any non-macOS / missing-binary / parse failure / timeout so
    callers fall back to a deterministic dev id. A slow boot (ioreg hanging) is
    explicitly caught as subprocess.TimeoutExpired and logged, so a wedged ioreg
    degrades to the fallback id instead of blocking startup forever.
    """
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5.0,
        )
    except subprocess.TimeoutExpired:
        _log.warning("ioreg timed out; using fallback machine id")
        return None
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if "IOPlatformUUID" in line:
            # line looks like: "IOPlatformUUID" = "XXXXXXXX-....-...."
            parts = line.split('"')
            for i, tok in enumerate(parts):
                if tok == "IOPlatformUUID" and i + 2 < len(parts):
                    val = parts[i + 2].strip()
                    return val or None
    return None


def machine_id(override: str | None = None) -> str:
    """Stable per-machine id, with a CI/dev-safe fallback chain.

    Precedence: explicit override > SCUFFEDOS_VAULT_MACHINE_ID env > macOS
    IOPlatformUUID > a fixed dev string (so ubuntu CI is deterministic and this
    NEVER raises).
    """
    if override:
        return override
    env = os.environ.get("SCUFFEDOS_VAULT_MACHINE_ID")
    if env:
        return env
    uuid = _ioreg_platform_uuid()
    if uuid:
        return uuid
    return "dev-fallback-machine-id"


class SecretsVault:
    def __init__(
        self,
        root: str | os.PathLike,
        *,
        machine_id_override: str | None = None,
        use_keyring: bool = False,
    ) -> None:
        self.root = Path(os.path.expanduser(str(root)))
        self._mid_override = machine_id_override
        self._use_keyring = use_keyring

    # ---- paths ----
    @property
    def enc_path(self) -> Path:
        return self.root / "secrets.enc"

    @property
    def salt_path(self) -> Path:
        return self.root / "vault.salt"

    # ---- directory / salt ----
    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass  # best-effort on exotic filesystems

    def _salt(self) -> bytes:
        self._ensure_root()
        if self.salt_path.exists():
            existing = self.salt_path.read_bytes()
            # A truncated/corrupt salt must NOT be silently regenerated: a new
            # salt derives a different key and orphans secrets.enc forever. Raise
            # so the Settings re-auth path recovers instead of losing the vault.
            if len(existing) != 16:
                raise SaltCorruptedError(
                    f"vault.salt is {len(existing)} bytes, expected 16"
                )
            return existing
        salt = _secrets.token_bytes(16)
        self._atomic_write(self.salt_path, salt, mode=0o600)
        # _atomic_write does os.replace (atomic on POSIX) so a crash leaves
        # either the old or the new file, never a partial one; re-read and
        # verify the persisted bytes match before deriving a key over them.
        persisted = self.salt_path.read_bytes()
        if persisted != salt:
            raise SaltCorruptedError("vault.salt failed to persist correctly")
        return salt

    # ---- key derivation ----
    def _derive_file_key(self) -> bytes:
        salt = self._salt()
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_HKDF_INFO)
        return hkdf.derive(machine_id(self._mid_override).encode("utf-8"))

    def derive_key(self) -> bytes:
        """32-byte AES key. In the packaged app (use_keyring), the file-derived
        key is stored in one keyring item so the OS encrypts it at rest; a
        keyring failure degrades silently to the file-derived key."""
        file_key = self._derive_file_key()
        if not self._use_keyring:
            return file_key
        try:
            import keyring

            stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if stored:
                # Validate the stored item is well-formed 32-byte hex before we
                # trust it; a malformed entry (partial write, tampering) must
                # degrade to the file-derived key, not raise or return garbage.
                try:
                    key = bytes.fromhex(stored)
                except ValueError:
                    _log.warning(
                        "keyring vault-key item is not valid hex; "
                        "falling back to file-derived key"
                    )
                    return file_key
                if len(key) != 32:
                    _log.warning(
                        "keyring vault-key item is %d bytes, expected 32; "
                        "falling back to file-derived key", len(key)
                    )
                    return file_key
                return key
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, file_key.hex())
            return file_key
        except Exception:
            # No backend (CI) / locked keychain / any keyring error -> file key.
            return file_key

    # ---- atomic write helper (explicit mode via os.open) ----
    @staticmethod
    def _atomic_write(path: Path, data: bytes, *, mode: int) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.chmod(tmp, mode)  # umask can mask create mode; force it
        os.replace(tmp, path)
        os.chmod(path, mode)

    # ---- encrypt / decrypt ----
    def read_all(self) -> dict[str, str]:
        if not self.enc_path.exists():
            return {}
        raw = self.enc_path.read_bytes()
        if len(raw) < _NONCE_LEN + 16:
            raise VaultDecryptError("secrets.enc is truncated")
        nonce, blob = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
        # derive_key() may raise SaltCorruptedError (a VaultDecryptError subclass)
        # via _salt(); let that propagate UNCHANGED so callers can distinguish a
        # corrupt salt from a bad GCM tag. Only wrap genuine crypto/decrypt
        # errors below.
        key = self.derive_key()
        try:
            plaintext = AESGCM(key).decrypt(nonce, blob, None)
        except VaultDecryptError:
            raise  # already the right type (e.g. bubbled up); don't re-wrap
        except Exception as exc:  # InvalidTag and friends
            raise VaultDecryptError(str(exc)) from exc
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise VaultDecryptError("vault plaintext is not valid JSON") from exc
        return {str(k): str(v) for k, v in data.items()}

    def write_all(self, values: dict[str, str]) -> None:
        self._ensure_root()
        nonce = _secrets.token_bytes(_NONCE_LEN)
        plaintext = json.dumps(values, separators=(",", ":")).encode("utf-8")
        blob = AESGCM(self.derive_key()).encrypt(nonce, plaintext, None)
        self._atomic_write(self.enc_path, nonce + blob, mode=0o600)

    # ---- convenience ----
    def get(self, key: str) -> str | None:
        return self.read_all().get(key) or None

    def set(self, key: str, value: str) -> None:
        values = self.read_all()
        values[key] = value
        self.write_all(values)

    def update(self, patch: dict[str, str]) -> None:
        values = self.read_all()
        values.update({k: v for k, v in patch.items()})
        self.write_all(values)

    def present(self) -> dict[str, bool]:
        """Presence map over the canonical SECRET_KEYS — True iff a non-empty
        value is stored. Never returns raw secret values."""
        stored = {}
        try:
            stored = self.read_all()
        except VaultDecryptError:
            stored = {}
        return {k: bool(stored.get(k)) for k in SECRET_KEYS}
```

- [ ] **Step 4:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_secrets_vault.py -q` and confirm all pass.

- [ ] **Step 5:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Confirm no regression (baseline + Task 1's 2 + this task's 21). Report the pass count.

- [ ] **Step 6:** Commit.
```
git add backend/app/secrets.py backend/tests/test_secrets_vault.py
git commit -m "feat(ship): app/secrets.py machine-bound AES-256-GCM SecretsVault

HKDF-SHA256 key over IOPlatformUUID + per-install salt, nonce||ct||tag on
disk at 0600 (dir 0700). Machine id is injectable so unit tests round-trip on
ubuntu CI; keyring wrapping degrades to a file-only key when no backend exists.
Bad-tag decrypt raises VaultDecryptError for the Settings re-auth path.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Config seam — resolve secrets from the vault, env-first (TDD empty-only override)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py` (append a vault-resolver block + call after the `settings = Settings()` singleton at line 133; do not change any field default).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_config_vault_seam.py`.
- Reference only: `backend/app/secrets.py` (Task 2), `backend/app/config.py:22-119` (the secret fields).

**Interfaces:**
- Produces (in `app/config.py`):
  - `get_vault() -> SecretsVault` — process-wide, lazily constructed against `settings.app_support_dir`, with `use_keyring = settings.scuffedos_managed_pg` (packaged path wraps the key; dev/CI uses file-only). Cached in a module global.
  - `resolve_secrets_from_vault(target=settings) -> None` — for each `(field_name, VAULT_KEY)` in the field→key map, if `getattr(target, field_name)` is falsy AND the vault has a non-empty value, set the field. **Never overrides a non-empty field** (env/.env/test assignment wins). Swallows `VaultDecryptError` (logs a warning) so a corrupt/foreign vault never crashes startup — the Settings re-auth path handles recovery.
  - `SECRET_FIELD_MAP: dict[str, str]` — `{"anthropic_api_key": "ANTHROPIC_API_KEY", ...}` for all nine secret fields.
- Consumes: `app.secrets.SecretsVault`, `SECRET_KEYS`, `VaultDecryptError`.

- [ ] **Step 1:** Write the test. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_config_vault_seam.py`:

```python
"""M8 Slice 2 config seam: the vault fills a secret field ONLY when it is empty,
so env/.env/test values always win and the suite is unaffected. A decrypt
failure is swallowed (logged), never raised, so a foreign/corrupt vault can't
crash startup. Uses a tmp vault via an injected machine id — no ioreg, CI-safe."""

import pytest

from app import config as cfg
from app.config import Settings
from app.secrets import SecretsVault


def _seed_vault(tmp_path, values, mid="seam-test"):
    v = SecretsVault(tmp_path, machine_id_override=mid, use_keyring=False)
    v.write_all(values)
    return SecretsVault(tmp_path, machine_id_override=mid, use_keyring=False)


def test_empty_field_is_filled_from_vault(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path, {"ANTHROPIC_API_KEY": "sk-from-vault"})
    monkeypatch.setattr(cfg, "get_vault", lambda: vault)
    s = Settings(anthropic_api_key="")
    cfg.resolve_secrets_from_vault(s)
    assert s.anthropic_api_key == "sk-from-vault"


def test_nonempty_field_is_not_overridden(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path, {"ANTHROPIC_API_KEY": "sk-from-vault"})
    monkeypatch.setattr(cfg, "get_vault", lambda: vault)
    s = Settings(anthropic_api_key="sk-from-env")
    cfg.resolve_secrets_from_vault(s)
    assert s.anthropic_api_key == "sk-from-env"  # env wins


def test_fdc_demo_key_default_is_overridden(tmp_path, monkeypatch):
    # fdc_api_key ships as "DEMO_KEY"; the seam treats the DEMO_KEY sentinel as
    # "unset" so a real vault key replaces it.
    vault = _seed_vault(tmp_path, {"FDC_API_KEY": "real-fdc-key"})
    monkeypatch.setattr(cfg, "get_vault", lambda: vault)
    s = Settings()  # fdc_api_key == "DEMO_KEY"
    cfg.resolve_secrets_from_vault(s)
    assert s.fdc_api_key == "real-fdc-key"


def test_decrypt_failure_is_swallowed(tmp_path, monkeypatch):
    from app.secrets import VaultDecryptError

    class _Boom:
        def read_all(self):
            raise VaultDecryptError("bad tag")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    s = Settings(anthropic_api_key="")
    # Must not raise; field stays empty.
    cfg.resolve_secrets_from_vault(s)
    assert s.anthropic_api_key == ""


def test_map_covers_all_nine_secret_fields():
    assert set(cfg.SECRET_FIELD_MAP.values()) == {
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FDC_API_KEY",
        "WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "PLAID_CLIENT_ID", "PLAID_SECRET",
    }


def test_vault_isolation_per_test(tmp_path, monkeypatch):
    # The process-wide vault global (cfg._vault) must not leak a tmp vault from
    # one test into the next. Redirect via get_vault (a function patch, not the
    # global), reset the cached global, and assert a second, differently-seeded
    # vault does not see the first test's data.
    monkeypatch.setattr(cfg, "_vault", None, raising=False)
    vault_a = _seed_vault(tmp_path / "a", {"ANTHROPIC_API_KEY": "sk-a"}, mid="iso-a")
    monkeypatch.setattr(cfg, "get_vault", lambda: vault_a)
    assert cfg.get_vault().read_all() == {"ANTHROPIC_API_KEY": "sk-a"}
    vault_b = _seed_vault(tmp_path / "b", {"OPENAI_API_KEY": "sk-b"}, mid="iso-b")
    monkeypatch.setattr(cfg, "get_vault", lambda: vault_b)
    assert "ANTHROPIC_API_KEY" not in cfg.get_vault().read_all()
```

> **Test isolation contract (Tasks 3–5):** every test that touches the vault
> redirects it by monkeypatching the **function** `cfg.get_vault` (auto-restored
> by pytest), and any test that mutates the module-global `app.config.settings`
> singleton does so via `monkeypatch.setattr(settings, field, …)` (also
> auto-restored). Do NOT assign to `settings.<field> = …` directly in a test
> without monkeypatch, and do NOT mutate the cached `cfg._vault` global except
> via a `monkeypatch.setattr(cfg, "_vault", None)` inside the test — otherwise a
> tmp vault or a stray secret can leak across tests. The `tmp_vault`/`seeded`
> fixtures are function-scoped for exactly this reason.

- [ ] **Step 2:** Run and confirm failure (helpers don't exist): `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_config_vault_seam.py -q`. Expect `AttributeError: SECRET_FIELD_MAP` / `resolve_secrets_from_vault`.

- [ ] **Step 3:** Read `backend/app/config.py` lines 130–133 to confirm the `settings = Settings()` tail, then append after line 133:

```python


# ---- M8 Ship / Tauri — secrets vault seam (Slice 2) ----
# Secrets resolve from the machine-bound vault ONLY when the field is empty
# after env/.env load, so a value in the environment (or a test's direct
# assignment) always wins and dev/CI are unchanged. A foreign/corrupt vault
# (machine id changed) is swallowed here and recovered via the Settings
# re-authenticate flow — startup never crashes on a bad vault.
import logging as _logging

from .secrets import SecretsVault, VaultDecryptError

_log = _logging.getLogger("scuffed_os.config")

# settings field name -> canonical vault key.
SECRET_FIELD_MAP: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "fdc_api_key": "FDC_API_KEY",
    "whoop_client_id": "WHOOP_CLIENT_ID",
    "whoop_client_secret": "WHOOP_CLIENT_SECRET",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "plaid_client_id": "PLAID_CLIENT_ID",
    "plaid_secret": "PLAID_SECRET",
}

# Field values that mean "not really set" and may be replaced by a vault value.
_UNSET_SENTINELS = {"", "DEMO_KEY"}

_vault: SecretsVault | None = None


def get_vault() -> SecretsVault:
    """Process-wide vault against app_support_dir. use_keyring only in the
    packaged app (SCUFFEDOS_MANAGED_PG); dev/CI use a file-only key."""
    global _vault
    if _vault is None:
        _vault = SecretsVault(
            settings.app_support_dir,
            use_keyring=settings.scuffedos_managed_pg,
        )
    return _vault


def resolve_secrets_from_vault(target: "Settings" = settings) -> None:
    """Fill empty/sentinel secret fields from the vault. Env/.env values win.
    A decrypt failure is logged and swallowed (recovered via Settings re-auth)."""
    try:
        stored = get_vault().read_all()
    except VaultDecryptError:
        _log.warning("secrets vault failed to decrypt; using env-only secrets "
                     "(re-authenticate in Settings to repair)")
        return
    except Exception as exc:  # defensive: never crash config import/startup
        _log.warning("secrets vault unavailable (%s); using env-only secrets", exc)
        return
    for field_name, vault_key in SECRET_FIELD_MAP.items():
        current = getattr(target, field_name, "")
        if current in _UNSET_SENTINELS:
            val = stored.get(vault_key)
            if val:
                setattr(target, field_name, val)


# Resolve once at import so lazy consumers (llm/food_db/providers) see vault
# values. Empty-only override keeps dev/CI/tests byte-for-byte unchanged.
resolve_secrets_from_vault(settings)
```

- [ ] **Step 4:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_config_vault_seam.py -q` and confirm all six pass.

- [ ] **Step 5:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. This is the **critical regression gate** — the import-time `resolve_secrets_from_vault(settings)` must not change any existing test (in CI there is no vault file → `read_all()` returns `{}` → no field changes). Expected exact count: **baseline 623 + Task 1 (+2) + Task 2 (+21) + this task (+6) = 652 passed, 1 skipped**, with **zero prior-test regressions**. Report the pass count. If the total is short of 652 a new test is missing/failing; if any *prior* test flipped from pass→fail, the seam is overriding a non-empty field or crashing at import — fix the seam (Task 3), not the consumers, before proceeding.

- [ ] **Step 6:** Commit.
```
git add backend/app/config.py backend/tests/test_config_vault_seam.py
git commit -m "feat(ship): config seam resolves secrets from the vault, env-first

Empty-only override: the machine-bound vault fills a secret field only when it
is empty (or the DEMO_KEY sentinel), so env/.env and test assignments always
win and dev/CI are unchanged. A decrypt failure is logged and swallowed so a
foreign vault never crashes startup.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `GET/PUT /api/settings/secrets` router — masked presence + write-through (TDD)

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/settings.py`.
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py` (add `settings` to the `from .routers import (...)` block at lines 25–37; add `app.include_router(settings.router)` after the finance router at line 142). NOTE: the module is named `settings` and there is already a `from .config import settings` singleton imported at line 23 — import the router module under an alias to avoid the name clash (see Step 4).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_settings_secrets.py`.
- Reference only: `backend/app/schemas.py` (Pydantic `*Out` convention), `backend/app/config.py:get_vault` (Task 3), `backend/app/errors.py` (error envelope).

**Interfaces:**
- Produces:
  - `GET /api/settings/secrets` → `SecretsStateOut`: `{"integrations": {"anthropic": {"label": "Anthropic", "keys": [{"key": "ANTHROPIC_API_KEY", "present": bool}]}, ...}, "vault_ok": bool}`. **Never returns raw secret values** — only presence booleans. `vault_ok` is False when the vault fails to decrypt (drives the frontend re-auth banner).
  - `PUT /api/settings/secrets` (body `SecretsUpdateIn`: `{"values": {"ANTHROPIC_API_KEY": "sk-..."}}`) → validates keys, then under a process-wide write lock writes the given keys into the vault, **re-reads to verify persistence**, forces the running settings, and re-runs `resolve_secrets_from_vault(settings)` so the running process picks them up; returns the same masked `SecretsStateOut`. Empty-string values delete/blank a key. Error domains: unknown key → **422**; `VaultDecryptError` (foreign/corrupt vault, machine changed) → **422** (re-authenticate); `IOError`/`OSError` (disk) or an unverifiable write → **503**; any other vault error → **500**.
- Consumes: `app.config.get_vault`, `app.config.resolve_secrets_from_vault`, `app.secrets.SECRET_KEYS`, `app.secrets.VaultDecryptError`.

- [ ] **Step 1:** Write the test. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_settings_secrets.py`:

```python
"""M8 Slice 2 Settings API: GET returns masked presence only (never raw
values); PUT writes into the machine-bound vault and never echoes secrets. The
vault is redirected to a tmp dir via the config get_vault seam so no real
~/Library path is touched and it round-trips on CI."""

import pytest

from app import config as cfg
from app.secrets import SecretsVault


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    v = SecretsVault(tmp_path, machine_id_override="settings-api-test", use_keyring=False)
    monkeypatch.setattr(cfg, "get_vault", lambda: v)
    return v


def test_get_secrets_empty_presence(client, tmp_vault):
    res = client.get("/api/settings/secrets")
    assert res.status_code == 200
    body = res.json()
    assert body["vault_ok"] is True
    anth = body["integrations"]["anthropic"]
    keys = {k["key"]: k["present"] for k in anth["keys"]}
    assert keys["ANTHROPIC_API_KEY"] is False


def test_put_secret_then_present_true(client, tmp_vault):
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk-ant-xyz"}})
    assert res.status_code == 200
    body = res.json()
    keys = {k["key"]: k["present"] for k in body["integrations"]["anthropic"]["keys"]}
    assert keys["ANTHROPIC_API_KEY"] is True
    # And it persisted to the vault (still never echoed as a raw value).
    assert tmp_vault.get("ANTHROPIC_API_KEY") == "sk-ant-xyz"


def test_get_never_returns_raw_values(client, tmp_vault):
    tmp_vault.set("PLAID_SECRET", "super-secret-value")
    res = client.get("/api/settings/secrets")
    assert "super-secret-value" not in res.text


def test_put_rejects_unknown_key(client, tmp_vault):
    res = client.put("/api/settings/secrets",
                     json={"values": {"NOT_A_REAL_KEY": "x"}})
    # Assert only the HTTP status; the error-envelope shape is version/
    # middleware-dependent and would make this test brittle.
    assert res.status_code == 422


def test_put_empty_value_blanks_presence(client, tmp_vault):
    tmp_vault.set("OPENAI_API_KEY", "sk-oai")
    res = client.put("/api/settings/secrets",
                     json={"values": {"OPENAI_API_KEY": ""}})
    assert res.status_code == 200
    keys = {k["key"]: k["present"] for k in res.json()["integrations"]["openai"]["keys"]}
    assert keys["OPENAI_API_KEY"] is False


def test_put_updates_running_settings(client, tmp_vault):
    from app.config import settings
    settings.anthropic_api_key = ""
    client.put("/api/settings/secrets", json={"values": {"ANTHROPIC_API_KEY": "sk-live"}})
    assert settings.anthropic_api_key == "sk-live"


def test_get_reports_vault_not_ok_on_decrypt_failure(client, tmp_path, monkeypatch):
    from app.secrets import VaultDecryptError

    class _Boom:
        def present(self):
            raise VaultDecryptError("bad tag")
        def read_all(self):
            raise VaultDecryptError("bad tag")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    res = client.get("/api/settings/secrets")
    assert res.status_code == 200
    assert res.json()["vault_ok"] is False


def test_put_decrypt_failure_is_422(client, tmp_path, monkeypatch):
    # A foreign/corrupt vault (machine changed) is a client-recoverable state,
    # surfaced as 422 (re-authenticate), not a blanket 503.
    from app.secrets import VaultDecryptError

    class _Boom:
        def update(self, patch):
            raise VaultDecryptError("bad tag")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk"}})
    assert res.status_code == 422


def test_put_revalidates_vault_write(client, tmp_path, monkeypatch):
    # update() reports success but the value never persisted (read_all returns
    # stale data) -> the endpoint must re-read, detect the mismatch, and 503
    # rather than falsely reporting success.
    class _Stale:
        def update(self, patch):
            return None  # pretend the write succeeded

        def read_all(self):
            return {}  # but nothing actually persisted

    monkeypatch.setattr(cfg, "get_vault", lambda: _Stale())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk-live"}})
    assert res.status_code == 503


def test_concurrent_puts_dont_lose_updates(client, tmp_vault):
    # Two simultaneous PUTs of different keys against a real tmp vault must both
    # persist; the write lock serializes the read-modify-write so neither
    # clobbers the other.
    import threading

    barrier = threading.Barrier(2)

    def _put(key, val):
        barrier.wait()
        client.put("/api/settings/secrets", json={"values": {key: val}})

    t1 = threading.Thread(target=_put, args=("ANTHROPIC_API_KEY", "sk-a"))
    t2 = threading.Thread(target=_put, args=("OPENAI_API_KEY", "sk-o"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert tmp_vault.get("ANTHROPIC_API_KEY") == "sk-a"
    assert tmp_vault.get("OPENAI_API_KEY") == "sk-o"
```

- [ ] **Step 2:** Run and confirm failure (route missing): `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_settings_secrets.py -q`. Expect 404s and collection to still succeed.

- [ ] **Step 3:** Create the router. Write `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/routers/settings.py`:

```python
"""M8 Slice 2 — Settings/secrets API.

GET returns which integrations are configured, as PRESENCE booleans only —
never raw secret values (spec §4.5). PUT writes new values into the
machine-bound vault, then re-resolves the running settings so the live process
picks them up without a restart. Grouped by integration for the Settings UI.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_vault, resolve_secrets_from_vault, settings
from ..secrets import SECRET_KEYS, VaultDecryptError

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Serialize the read-modify-write in put_secrets so concurrent PUTs can't lose
# updates. The vault's update() is read_all -> merge -> write_all, which is not
# atomic across requests; this lock makes the whole sequence critical-section.
_vault_write_lock = threading.Lock()

# Presentation grouping: integration id -> (label, [vault keys]).
_INTEGRATIONS: dict[str, tuple[str, list[str]]] = {
    "anthropic": ("Anthropic", ["ANTHROPIC_API_KEY"]),
    "openai": ("OpenAI (embeddings)", ["OPENAI_API_KEY"]),
    "usda": ("USDA FoodData Central", ["FDC_API_KEY"]),
    "whoop": ("WHOOP", ["WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET"]),
    "google": ("Google / Gmail / Calendar", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]),
    "plaid": ("Plaid", ["PLAID_CLIENT_ID", "PLAID_SECRET"]),
}


class SecretKeyState(BaseModel):
    key: str
    present: bool


class IntegrationState(BaseModel):
    label: str
    keys: list[SecretKeyState]


class SecretsStateOut(BaseModel):
    integrations: dict[str, IntegrationState]
    vault_ok: bool


class SecretsUpdateIn(BaseModel):
    values: dict[str, str]


def _state() -> SecretsStateOut:
    # Probe with read_all(), NOT present(): present() intentionally swallows a
    # decrypt failure and returns an all-absent map, which would report
    # vault_ok=True on a genuinely corrupt/foreign vault (incl. a SaltCorrupted
    # salt) and never surface the re-auth banner. read_all() raises, so a decrypt
    # failure here correctly flips vault_ok=False.
    vault_ok = True
    try:
        stored = get_vault().read_all()
        presence = {k: bool(stored.get(k)) for k in SECRET_KEYS}
    except VaultDecryptError:  # includes SaltCorruptedError
        vault_ok = False
        presence = {k: False for k in SECRET_KEYS}
    except Exception:
        vault_ok = False
        presence = {k: False for k in SECRET_KEYS}
    integrations = {
        iid: IntegrationState(
            label=label,
            keys=[SecretKeyState(key=k, present=bool(presence.get(k))) for k in keys],
        )
        for iid, (label, keys) in _INTEGRATIONS.items()
    }
    return SecretsStateOut(integrations=integrations, vault_ok=vault_ok)


@router.get("/secrets", response_model=SecretsStateOut)
def get_secrets() -> SecretsStateOut:
    """Masked presence of every integration secret. Never returns raw values."""
    return _state()


@router.put("/secrets", response_model=SecretsStateOut)
def put_secrets(body: SecretsUpdateIn) -> SecretsStateOut:
    """Write new secret values into the vault, then re-resolve running settings.

    A process-wide lock serializes read-modify-write so concurrent PUTs cannot
    lose each other's updates (SecretsVault.update() does read_all -> merge ->
    write_all, which is not atomic across requests). After the write, the vault
    is re-read and the written keys are verified present so a silent persistence
    failure surfaces as a 503 instead of a false success.
    """
    unknown = [k for k in body.values if k not in SECRET_KEYS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown secret key(s): {', '.join(unknown)}")
    patch = dict(body.values)
    with _vault_write_lock:
        try:
            get_vault().update(patch)
        except VaultDecryptError as exc:
            # Bad credentials / machine changed: this is a client-recoverable
            # state (re-authenticate), not a server fault -> 422.
            raise HTTPException(
                status_code=422,
                detail=f"vault decrypt failed; re-authenticate: {exc}",
            )
        except (IOError, OSError) as exc:
            raise HTTPException(status_code=503, detail=f"vault write failed: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"unexpected vault error: {exc}")
        # Re-read and verify the write actually persisted. A non-empty value we
        # just wrote must read back as present; if not, the write silently
        # failed and we must not report success.
        try:
            reread = get_vault().read_all()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"vault write unverifiable: {exc}")
        for k, v in patch.items():
            if v and reread.get(k) != v:
                raise HTTPException(
                    status_code=503,
                    detail=f"vault write did not persist key {k}",
                )
        # A PUT can also repair a previously non-empty field; force those keys so
        # the running process reflects the new value even if it was already set.
        for k, v in patch.items():
            field = next((f for f, vk in _field_map().items() if vk == k), None)
            if field is not None:
                setattr(settings, field, v)
        resolve_secrets_from_vault(settings)
    return _state()


def _field_map() -> dict[str, str]:
    from ..config import SECRET_FIELD_MAP
    return SECRET_FIELD_MAP
```

- [ ] **Step 4:** Register the router in `main.py`. Read `backend/app/main.py` lines 25–37 and 142 to confirm the current router block, then in the `from .routers import (...)` tuple add `settings as settings_router` (aliased to avoid clashing with the `from .config import settings` singleton). Change the import block to include the new line (keep alphabetical-ish order; place it after `oauth,`):

```python
from .routers import (
    assistant,
    calendar,
    email,
    finance,
    fitness,
    habits,
    memory,
    moodle,
    nutrition,
    oauth,
    settings as settings_router,
    tasks,
)
```

Then after `app.include_router(finance.router)` (line 142) add:
```python
app.include_router(settings_router.router)
```

- [ ] **Step 5:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_settings_secrets.py -q` and confirm all ten pass.

- [ ] **Step 6:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Report the pass count. Confirm no regression (the new router is additive and the vault is redirected to tmp in its tests).

- [ ] **Step 7:** Commit.
```
git add backend/app/routers/settings.py backend/app/main.py backend/tests/test_settings_secrets.py
git commit -m "feat(ship): GET/PUT /api/settings/secrets — masked presence + write-through

GET returns per-integration presence booleans only (never raw values); PUT
writes into the machine-bound vault and re-resolves running settings so keys
take effect without a restart. Unknown keys 422; vault decrypt failure surfaces
vault_ok=false for the frontend re-auth path.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `.env.example` doc + integration-read audit note (docs-in-code, TDD the audit)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example` (append a `# --- M8 Secrets vault ---` note after the managed-PG block).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_vault_integration_reads.py`.
- Reference only (no edit): `backend/app/llm.py:33,54`, `backend/app/food_db.py:67`, `backend/app/memory_engine.py:56-57`, `backend/app/providers/plaid.py:133`, `backend/app/providers/google.py:202,236-237` — all read `settings.<field>` lazily at request time, so the Task 3 seam (which fills those fields at import) transparently feeds them. This task adds a regression test proving the seam reaches those consumers.

**Interfaces:**
- Produces: a test that seeds the vault, re-resolves settings, and asserts `settings.anthropic_api_key` / `settings.fdc_api_key` / `settings.plaid_client_id` etc. now read the vault value — i.e. every lazy integration consumer transparently gets vault secrets with **no change to llm.py/food_db.py/providers**.
- Consumes: `app.config.resolve_secrets_from_vault`, `app.secrets.SecretsVault`.

- [ ] **Step 1:** Write the test. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_vault_integration_reads.py`:

```python
"""M8 Slice 2: prove the config seam transparently feeds every lazy integration
consumer. llm.py, food_db.py, memory_engine.py, providers/plaid.py and
providers/google.py all read settings.<field> at request time, so filling those
fields from the vault (Task 3) reaches them with ZERO change to those modules.
This test asserts the settings values the consumers read now come from the
vault when the field was empty."""

import pytest

from app import config as cfg
from app.config import resolve_secrets_from_vault
from app.secrets import SecretsVault


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    v = SecretsVault(tmp_path, machine_id_override="integ-read-test", use_keyring=False)
    v.write_all({
        "ANTHROPIC_API_KEY": "sk-ant-vault",
        "FDC_API_KEY": "fdc-vault",
        "PLAID_CLIENT_ID": "plaid-id-vault",
        "PLAID_SECRET": "plaid-secret-vault",
        "GOOGLE_CLIENT_ID": "google-id-vault",
    })
    monkeypatch.setattr(cfg, "get_vault", lambda: v)
    return v


def test_llm_consumer_reads_vault_anthropic_key(seeded, monkeypatch):
    # END-TO-END: resolve the vault into the GLOBAL settings the consumer reads,
    # then call the real consumer (llm.available()) so a typo in the field name
    # inside llm.py — e.g. settings.anthropic_api_ky — would fail this test.
    import app.llm as llm
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "anthropic_api_key", "")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.anthropic_api_key == "sk-ant-vault"
    # available() returns True iff it read a non-empty settings.anthropic_api_key.
    llm.configure("unset")  # force the real settings-backed code path
    assert llm.available() is True


def test_food_db_consumer_reads_vault_fdc_key(seeded, monkeypatch):
    # END-TO-END through the real food_db module: seed the vault, resolve into
    # global settings, and assert food_db reads the same field the seam filled.
    import app.food_db as food_db
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "fdc_api_key", "DEMO_KEY")
    resolve_secrets_from_vault(global_settings)
    # food_db.search() reads settings.fdc_api_key at request time; assert the
    # module sees the vault value via its own settings import.
    assert food_db.settings.fdc_api_key == "fdc-vault"


def test_plaid_consumer_reads_vault_credentials(seeded, monkeypatch):
    import app.providers.plaid as plaid_mod
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "plaid_client_id", "")
    monkeypatch.setattr(global_settings, "plaid_secret", "")
    resolve_secrets_from_vault(global_settings)
    assert plaid_mod.settings.plaid_client_id == "plaid-id-vault"
    assert plaid_mod.settings.plaid_secret == "plaid-secret-vault"


def test_google_consumer_reads_vault_client_id(seeded, monkeypatch):
    import app.providers.google as google_mod
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "google_client_id", "")
    resolve_secrets_from_vault(global_settings)
    assert google_mod.settings.google_client_id == "google-id-vault"


def test_env_value_still_beats_vault_for_consumers(seeded, monkeypatch):
    import app.llm as llm
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "anthropic_api_key", "sk-from-env")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.anthropic_api_key == "sk-from-env"  # env wins
    llm.configure("unset")
    assert llm.available() is True  # still reads the env value, not the vault
```

> **Note on module-global `settings`:** every consumer (`llm`, `food_db`,
> `providers/plaid`, `providers/google`) imports the *same* `app.config.settings`
> singleton and reads `settings.<field>` lazily at request time. The tests above
> mutate that global via `monkeypatch.setattr`, so `monkeypatch` automatically
> restores it after each test and cannot leak into the rest of the suite. That is
> what makes calling the real consumers safe here. Asserting on a fresh
> `Settings()` instance (the earlier draft) would only prove the seam mutates
> *an* object, not the one the consumers actually read — the whole point of this
> regression guard.

- [ ] **Step 2:** Run: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_vault_integration_reads.py -q`. These are end-to-end guards that seed the vault, resolve into the **global** `app.config.settings`, and call the **real** consumers (`llm.available()`) or read the consumer module's own `settings` import (`food_db.settings.fdc_api_key`, etc.), so a field-name typo in a consumer would fail here — not just the seam. If a test fails, first check whether it is the seam (Task 3's empty-only/sentinel logic) or the consumer's own `settings.<field>` read; fix whichever is wrong, but do NOT weaken the assertion to only check a throwaway `Settings()` instance — that would defeat the guard.

- [ ] **Step 3:** Document the vault in `.env.example`. Read `backend/.env.example` tail (the M8 managed-PG block added in slice 1), then append after it:

```
# --- M8 Ship / Tauri — secrets vault (packaged .app) ---
# In the packaged app, API keys and OAuth credentials are stored in a
# machine-bound AES-256-GCM vault at
#   ~/Library/Application Support/ScuffedOS/secrets.enc
# and entered via in-app Settings — you do NOT put them here. In dev, the
# values above (or your shell env) win: the vault only fills a key that is
# otherwise empty. SCUFFEDOS_VAULT_MACHINE_ID overrides the machine id (tests/CI).
# SCUFFEDOS_VAULT_MACHINE_ID=
```

- [ ] **Step 4:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Report the pass count.

- [ ] **Step 5:** Commit.
```
git add backend/.env.example backend/tests/test_vault_integration_reads.py
git commit -m "test(ship): prove the vault seam feeds every lazy integration consumer

Regression guard: llm/food_db/memory_engine/plaid/google read settings.<field>
lazily, so the empty-only vault fill reaches them with no change to those
modules. Documents the vault in .env.example.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `SettingsScreen.jsx` — masked keys, edit/save, first-run nudge, re-auth recovery (build-verified)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js` (add two methods to the `api` export object before the closing `}` at the end of the file, after the `deleteMemory` line).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SettingsScreen.jsx`.
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/App.jsx` (add the import after line 17; add the routing branch before the final `else body = <Placeholder ...>` at line 125).
- Reference only (no edit): `frontend/src/screens/FinanceScreen.jsx` (template), `frontend/src/components/ui.jsx` (`Card`/`Button` signatures), `frontend/src/lib/Icon.jsx` (the component uses exactly these 8 icon names, all confirmed present in the `Icon.jsx` name→component map: `settings`, `sliders-horizontal`, `alert-triangle`, `check`, `plus`, `pen-line`, `x`, `refresh-cw`), `frontend/src/shell/Sidebar.jsx:53-54` (Settings nav button already wired — no change).

**Interfaces:**
- Produces:
  - `api.settingsGetSecrets()` → `GET /api/settings/secrets`; `api.settingsPutSecrets(values)` → `PUT /api/settings/secrets` with `{ values }`.
  - `SettingsScreen` component: fetches masked state on mount; renders one card per integration with a present/absent chip and a masked field + Edit → password input; a Save button PUTs edited values; a first-run onboarding nudge when nothing is configured; a re-authenticate recovery banner when `vault_ok === false`.
- Consumes: the Task 4 endpoints; the shared `Card`/`Button`/`Icon` kit; `App.jsx` routing (the `settings` screen id and sidebar button already exist).

- [ ] **Step 1:** Add the API methods. Read the last ~10 lines of `frontend/src/lib/api.js` to confirm the `deleteMemory` line and the closing `}`, then insert before the final `}`:

```javascript

  // Settings — integration secrets. GET returns masked presence only; PUT
  // writes new values into the machine-bound vault (never echoes secrets).
  settingsGetSecrets: () => request('/api/settings/secrets'),
  settingsPutSecrets: (values) => request('/api/settings/secrets', {
    method: 'PUT',
    body: JSON.stringify({ values }),
  }),
```

- [ ] **Step 2:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/screens/SettingsScreen.jsx`:

```jsx
/* Scuffed OS — Settings: integration secrets (M8 Slice 2).
   Shows which integrations are configured (masked presence only — the backend
   never returns raw values), lets the user paste/update keys, nudges first-run
   onboarding, and surfaces a re-authenticate recovery path when the vault fails
   to decrypt (e.g. IOPlatformUUID changed after a hardware move). Mirrors the
   FinanceScreen template + the shared ui/Icon kit. */
import React from 'react'
import { Card, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

export function SettingsScreen() {
  const [state, setState] = React.useState(null) // { integrations, vault_ok }
  const [error, setError] = React.useState('')
  const [edits, setEdits] = React.useState({})   // { KEY: 'new value' }
  const [saving, setSaving] = React.useState(false)
  const [saved, setSaved] = React.useState(false)

  const refresh = React.useCallback(() => {
    api.settingsGetSecrets()
      .then((s) => { setState(s); setError('') })
      .catch((e) => setError(e?.message || 'Failed to load settings'))
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const startEdit = (key) => setEdits((p) => ({ ...p, [key]: '' }))
  const cancelEdit = (key) => setEdits((p) => { const n = { ...p }; delete n[key]; return n })
  const setEdit = (key, val) => setEdits((p) => ({ ...p, [key]: val }))

  const save = () => {
    const values = { ...edits }
    if (Object.keys(values).length === 0) return
    setSaving(true)
    api.settingsPutSecrets(values)
      .then((s) => {
        setState(s)
        setEdits({})
        setSaved(true)
        setTimeout(() => setSaved(false), 2500)
      })
      .catch((e) => setError(e?.message || 'Failed to save settings'))
      .finally(() => setSaving(false))
  }

  const integrations = state ? Object.entries(state.integrations) : []
  const anyConfigured = integrations.some(([, ig]) => ig.keys.some((k) => k.present))
  const dirty = Object.keys(edits).length > 0

  // Re-authenticate recovery: the vault could not be decrypted.
  if (state && state.vault_ok === false) {
    return (
      <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}>
          <Icon name="alert-triangle" />
        </span>
        <div style={{ flex: 1 }}>
          <p className="kit-row__title">Re-authenticate your integrations</p>
          <p className="kit-muted">
            The local secrets vault could not be unlocked on this machine (this
            happens if the hardware changed). Your keys are safe but must be
            re-entered. Paste them again below to repair the vault.
          </p>
        </div>
        <Button variant="primary" size="sm" iconLeft={<Icon name="refresh-cw" />}
          onClick={() => setState({ ...state, vault_ok: true })}>
          Re-enter keys
        </Button>
      </Card>
    )
  }

  // First-run onboarding nudge: nothing configured yet.
  if (state && !anyConfigured && !dirty) {
    return (
      <Card variant="flat" style={{ maxWidth: 560, margin: '0 auto', padding: '40px 28px', textAlign: 'center' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="sliders-horizontal" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>
          Connect your integrations
        </h3>
        <p className="kit-muted" style={{ maxWidth: 420, margin: '0 auto 18px' }}>
          Add API keys and OAuth credentials for the assistant, nutrition, and
          your connected services. They are encrypted in a machine-bound vault on
          this Mac — never uploaded, never shown again.
        </p>
        <Button variant="primary" iconLeft={<Icon name="plus" />}
          onClick={() => setState({ ...state, __expandAll: true })}>
          Add keys
        </Button>
      </Card>
    )
  }

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {error && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}>
            <Icon name="alert-triangle" />
          </span>
          <p className="kit-row__title">{error}</p>
        </Card>
      )}
      {saved && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="check" /><p>Settings saved.</p>
        </Card>
      )}

      {integrations.map(([id, ig]) => (
        <Card
          key={id}
          title={ig.label}
          action={
            <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
              {ig.keys.every((k) => k.present)
                ? 'Configured'
                : ig.keys.some((k) => k.present) ? 'Partial' : 'Not set'}
            </span>
          }
        >
          <div className="kit-stack" style={{ marginTop: 4, gap: 12 }}>
            {ig.keys.map((k) => (
              <div key={k.key}>
                <label style={{ display: 'block', marginBottom: 6, fontFamily: 'var(--font-display)', fontSize: 'var(--text-sm)', color: 'var(--text-strong)' }}>
                  {k.key}
                </label>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <div style={{ flex: 1, padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', background: 'var(--paper-100)' }}>
                    {k.present ? '••••••••••••' : '(not set)'}
                  </div>
                  {edits[k.key] === undefined ? (
                    <Button variant="secondary" size="sm" iconLeft={<Icon name="pen-line" />}
                      onClick={() => startEdit(k.key)}>
                      {k.present ? 'Replace' : 'Add'}
                    </Button>
                  ) : (
                    <Button variant="secondary" size="sm" iconLeft={<Icon name="x" />}
                      onClick={() => cancelEdit(k.key)}>
                      Cancel
                    </Button>
                  )}
                </div>
                {edits[k.key] !== undefined && (
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder={`Paste ${k.key}`}
                    value={edits[k.key]}
                    onChange={(e) => setEdit(k.key, e.target.value)}
                    style={{ marginTop: 8, width: '100%', padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }}
                  />
                )}
              </div>
            ))}
          </div>
        </Card>
      ))}

      {dirty && (
        <div className="kit-inline" style={{ justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="secondary" size="sm" onClick={() => setEdits({})} disabled={saving}>Discard</Button>
          <Button variant="primary" size="sm" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3:** Register in `App.jsx`. Read `frontend/src/App.jsx` lines 13–18 and 122–126 to confirm the import block and routing tail. Add the import after line 17 (`import { MemoryScreen } ...`):

```javascript
import { SettingsScreen } from './screens/SettingsScreen.jsx'
```

Then in the routing chain, add a branch before the final `else body = <Placeholder ...>` (line 125):

```javascript
  else if (screen === 'settings') body = <SettingsScreen />
```

- [ ] **Step 3a (validate every Icon name resolves):** A bad `Icon name="…"` renders nothing at runtime and the build will NOT catch it. Confirm all 8 names the component uses are defined in the `Icon.jsx` name→component map (which uses both quoted `'kebab-case':` and bare `identifier:` keys):

```bash
cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend
have=$(grep -oE "^[[:space:]]+'?[a-z0-9-]+'?:" src/lib/Icon.jsx | tr -d " ':")
for n in settings sliders-horizontal alert-triangle check plus pen-line x refresh-cw; do
  echo "$have" | grep -qx "$n" || echo "MISSING ICON: $n — add it to src/lib/Icon.jsx"
done
echo "icon-check done"
```

EXPECTED: only `icon-check done` prints (no `MISSING ICON` line). If any icon is missing, add it to `Icon.jsx` (import the lucide component + add the map entry) before proceeding — do not ship a Settings screen with a blank icon.

- [ ] **Step 4 (acceptance — build):** `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build 2>&1 | tail -8`. EXPECTED: `✓ built` with no unresolved-import or syntax errors for `SettingsScreen`, `settingsGetSecrets`, or the kit imports.

- [ ] **Step 5 (acceptance — dev smoke, REQUIRED):** `npm run build` only checks syntax/imports — it does NOT prove the component mounts or that the `vault_ok===false` / first-run branches render without a runtime error (e.g. a bad `Icon` name or a null-deref on `state.integrations`). You MUST mount it. Start the backend (`cd backend && python -m uvicorn app.main:app --port 8000`) and `cd frontend && npm run dev`, open `http://localhost:5173`, click the sidebar **Settings** button, and confirm ALL of:
  - (a) with no vault, the first-run "Connect your integrations" nudge renders and the browser console shows **no React errors**;
  - (b) pasting a key into Anthropic → Save flips its chip to "Configured";
  - (c) reloading shows the masked `••••` and never the raw value in the DOM;
  - (d) exercise the re-auth branch: with the backend forced to report `vault_ok:false` (start it with `SCUFFEDOS_VAULT_MACHINE_ID=x` after seeding a vault under a different id, per Task 10 Step 5), reload Settings and confirm the **"Re-authenticate your integrations"** banner renders without a console error.
  Stop both servers. Halt and fix if any branch throws in the console — this is the runtime gate the build cannot provide.

  > If a headless component test harness (Vitest + `@testing-library/react`) is already configured in `frontend/`, add `frontend/src/screens/__tests__/SettingsScreen.test.jsx` asserting the re-auth banner text appears when `settingsGetSecrets` resolves `{vault_ok:false, integrations:{}}`, and the nudge appears when everything is absent. If no such harness exists, do NOT introduce one in this slice — the manual dev-smoke above is the gate.

- [ ] **Step 6:** Commit.
```
git add frontend/src/lib/api.js frontend/src/screens/SettingsScreen.jsx frontend/src/App.jsx
git commit -m "feat(ship): SettingsScreen — masked integration keys, first-run + re-auth

New Settings surface (sidebar entry already wired) showing per-integration
presence (masked, never raw), paste/replace + save, a first-run onboarding
nudge, and a re-authenticate recovery banner when the vault won't decrypt.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Tauri diagnostic error window on health-gate timeout + quit/relaunch polish (cargo-check verified)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/src/lib.rs` (the health-gate `else` branch inside the worker thread, currently at lines ~130–139 — the `eprintln!("[shell] health-gate timed out …")` block that just shows the main window).

**Interfaces:**
- Produces: on health-gate timeout, instead of silently showing a blank main window, the shell (a) reads the tail of `~/Library/Application Support/ScuffedOS/logs/backend.log` and `pg.log`, (b) opens a second diagnostic `WebviewWindow` (label `"diagnostic"`) rendering an inline HTML page with the log tails and a Quit button, and (c) does NOT show the main window (the diagnostic replaces it). A helper `tail_file(path, max_bytes) -> String` and `show_diagnostic_window(app, backend_tail, pg_tail)` are added. Quit/relaunch: the existing `CloseRequested → exit(0)` already covers quit; the diagnostic window's Quit button calls the existing exit path.
- Consumes: `tauri::WebviewWindowBuilder`, `tauri::WebviewUrl`, `std::fs`, the App-Support logs written by `app/localdb.py` (`pg.log`) and the sidecar (`backend.log`).

- [ ] **Step 1:** Read `src-tauri/src/lib.rs` to confirm the current worker-thread health-gate block (the `if wait_for_health(port) { … } else { eprintln!(…); show main window }` section) and the import list at the top.

- [ ] **Step 2:** Add the helper functions. Immediately after the `wait_for_health` function (before `pub fn run()`), insert:

```rust
/// Resolve ~/Library/Application Support/ScuffedOS/logs/<name>.
fn app_log_path(name: &str) -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    std::path::PathBuf::from(home)
        .join("Library")
        .join("Application Support")
        .join("ScuffedOS")
        .join("logs")
        .join(name)
}

/// Return the last `max_bytes` of a UTF-8 log file (or a placeholder if absent).
fn tail_file(path: &std::path::Path, max_bytes: usize) -> String {
    match std::fs::read(path) {
        Ok(bytes) => {
            let start = bytes.len().saturating_sub(max_bytes);
            String::from_utf8_lossy(&bytes[start..]).into_owned()
        }
        Err(_) => format!("(no log at {})", path.display()),
    }
}

/// HTML-escape for safe interpolation into the inline diagnostic page.
fn html_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// Open a diagnostic window surfacing the backend + pg log tails on a
/// health-gate timeout, instead of a blank hidden main window (spec §6).
///
/// The health-gate timeout is one-shot, but guard against a double-open anyway:
/// if a "diagnostic" window already exists (e.g. a future retry path), focus it
/// instead of stacking a second identical window.
fn show_diagnostic_window(app: &tauri::AppHandle, backend_tail: &str, pg_tail: &str) {
    use tauri::Manager;
    if let Some(existing) = app.get_webview_window("diagnostic") {
        let _ = existing.set_focus();
        return;
    }
    let html = format!(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>ScuffedOS — startup problem</title>\
         <style>body{{font:13px -apple-system,system-ui,sans-serif;margin:0;padding:20px;background:#1c1b19;color:#e8e4dd}}\
         h1{{font-size:18px;margin:0 0 4px}}p{{color:#b8b2a7;margin:0 0 16px}}\
         h2{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#8a8578;margin:18px 0 6px}}\
         pre{{background:#111;border:1px solid #333;border-radius:6px;padding:12px;overflow:auto;max-height:32vh;white-space:pre-wrap;word-break:break-word}}\
         button{{margin-top:18px;padding:8px 16px;border:0;border-radius:6px;background:#c4552e;color:#fff;font-size:13px;cursor:pointer}}</style></head>\
         <body><h1>ScuffedOS didn't finish starting</h1>\
         <p>The backend did not become ready in time. The logs below may explain why.</p>\
         <h2>backend.log</h2><pre>{}</pre>\
         <h2>pg.log</h2><pre>{}</pre>\
         <button onclick=\"window.__TAURI_INTERNALS__.invoke('quit_app')\">Quit</button>\
         </body></html>",
        html_escape(backend_tail),
        html_escape(pg_tail),
    );
    let url = tauri::WebviewUrl::App(format!("data:text/html,{}", urlencoding_encode(&html)).into());
    let _ = tauri::WebviewWindowBuilder::new(app, "diagnostic", url)
        .title("ScuffedOS — startup problem")
        .inner_size(720.0, 560.0)
        .build();
}

/// Minimal percent-encoding for the data: URL (avoids a new crate dependency).
fn urlencoding_encode(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 2);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}
```

- [ ] **Step 3:** Register the new command. In `pub fn run()`, change the existing `invoke_handler` from:
```rust
        .invoke_handler(tauri::generate_handler![api_port])
```
to:
```rust
        .invoke_handler(tauri::generate_handler![api_port, quit_app])
```

- [ ] **Step 4:** Replace the health-gate `else` branch. Change the worker-thread block from the current form (that `eprintln!`s and shows the main window) to:

```rust
                } else {
                    eprintln!("[shell] health-gate timed out on :{port}; showing diagnostic window");
                    let backend_tail = tail_file(&app_log_path("backend.log"), 8192);
                    let pg_tail = tail_file(&app_log_path("pg.log"), 8192);
                    show_diagnostic_window(&show_handle, &backend_tail, &pg_tail);
                    // Do NOT show the blank main window; the diagnostic replaces it.
                }
```

- [ ] **Step 5 (acceptance — compile):** `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri && cargo check 2>&1 | tail -20`. EXPECTED: `Finished` with no errors. If `WebviewUrl::App` rejects a `data:` URL on the installed Tauri version, fall back to `WebviewUrl::External(url)` with the same data URL, or write the HTML to a temp file and use `WebviewUrl::External` with a `file://` URL — adjust and re-run `cargo check` until green. Warnings about unused helpers are acceptable.

> **Verification boundary:** `cargo check` proves the diagnostic path and the `quit_app` command *compile and are registered*; it does NOT prove the window renders or that the diagnostic HTML's `invoke('quit_app')` button actually reaches the command at runtime (a data-URL webview, the `__TAURI_INTERNALS__.invoke` bridge, and the handler registration all have to line up). The actual window render + the Quit button are smoke-tested in **Task 10 (Spike C) Step 6** by forcing a boot failure and clicking Quit. Do not treat green `cargo check` as proof the window renders or that Quit exits.

- [ ] **Step 6:** Commit.
```
git add src-tauri/src/lib.rs
git commit -m "feat(ship): diagnostic error window on health-gate timeout

On timeout the shell now opens a diagnostic window surfacing the tails of
backend.log + pg.log with a Quit button, instead of a blank hidden main
window (spec §6). Adds a quit_app command wired to the existing exit path.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Docs — fix stale M7→M8 refs + new `docs/ship.md`

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/backend-overview.md` (line 195: `bundle (M7).` → `bundle (M8).`).
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/reminders.py` (line 10: `the Tauri bundle lands in M7` → `the Tauri bundle lands in M8`).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/ship.md`.

**Interfaces:**
- Produces: corrected milestone references and a new shipping doc covering build, App-Support layout, the one-time quarantine right-click▸Open, the secrets vault, and the acceptance smoke.
- Consumes: nothing at runtime; these are docs.

- [ ] **Step 1:** Fix `docs/backend-overview.md`. Read line 195 to confirm the exact text (`… then the Tauri bundle (M7).`), then replace `bundle (M7).` with `bundle (M8).` using an exact-match edit.

- [ ] **Step 2:** Fix `backend/app/reminders.py`. Read line 10 to confirm (`process, no app bundle needed (the Tauri bundle lands in M7). Same test`), then replace `lands in M7)` with `lands in M8)`.

- [ ] **Step 3:** Confirm no other stale refs remain. First the two exact phrases this task fixes:
```bash
grep -rn "Tauri bundle lands in M7\|bundle (M7)" \
  /Users/dylanschempp/PycharmProjects/ScuffedOS/docs \
  /Users/dylanschempp/PycharmProjects/ScuffedOS/backend
```
must print nothing. Then a broader sweep for any *other* M7↔Tauri wording (e.g. "Tauri M7", "shipped in M7", "M7 bundle") across docs and source, including `frontend/` and `src-tauri/`:
```bash
grep -rniI 'M7' \
  --include='*.md' --include='*.py' --include='*.rs' --include='*.jsx' \
  /Users/dylanschempp/PycharmProjects/ScuffedOS 2>/dev/null | grep -i tauri
```
Review each hit: Tauri belongs to **M8**, so any line that ties Tauri/the desktop bundle to M7 is stale — fix it in the same commit. (Lines that mention M7 for the *finance/Plaid* milestone are correct and must be left alone.) If the sweep is noisy, it is fine to leave genuinely-correct M7 references; only the Tauri-milestone ones are the target.

- [ ] **Step 4:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/ship.md`:

```markdown
# Shipping ScuffedOS — the macOS desktop app (M8)

ScuffedOS ships as a **double-clickable, unsigned `ScuffedOS.app`** for a single
Apple-Silicon Mac. The app bundles its own Python runtime, PostgreSQL 17 +
pgvector, and the FastAPI backend, so it runs the full dashboard offline with no
terminal and no cloud database.

> **Scope:** personal daily-driver, macOS **arm64 only**, **unsigned** (no
> Developer ID, no notarization, no DMG/auto-update, no Windows/Linux). See
> `docs/superpowers/specs/2026-07-07-ship-tauri-design.md`.

## Build (on an Apple-Silicon Mac)

Prerequisites: Xcode Command Line Tools, `uv` (0.11.19+), Rust (≥ 1.77.2) with
`cargo-tauri` (`cargo install tauri-cli --version '^2'`), Node 18+.

```bash
bash scripts/build-app.sh
```

This vendors PostgreSQL 17.10.0 + pgvector 0.8.4 (`scripts/vendor-postgres.sh`),
true-installs CPython 3.14.5 + backend deps incl. `cryptography` and `keyring`
(`scripts/vendor-python.sh`), builds the launcher stub, renders the icon, builds
the frontend, and runs `cargo tauri build`. Output:

```
src-tauri/target/release/bundle/macos/ScuffedOS.app   (~250–350 MB)
```

## First launch (Gatekeeper / quarantine)

The app is unsigned, so the first launch needs a one-time bypass:

- **Right-click the app → Open → Open** (do this once; subsequent launches are
  a normal double-click), or
- `xattr -dr com.apple.quarantine /path/to/ScuffedOS.app`

Ad-hoc signing does **not** remove quarantine — this step is expected.

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
```

- [ ] **Step 5:** Commit.
```
git add docs/backend-overview.md backend/app/reminders.py docs/ship.md
git commit -m "docs(ship): new docs/ship.md + fix stale M7->M8 Tauri references

Adds the build/run/App-Support/quarantine/secrets/acceptance shipping doc and
corrects the two stale 'Tauri bundle lands in M7' notes to M8.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Docs — README "Desktop app (M8)" section + privacy-policy vault disclosure

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/README.md` (after the "Desktop surfaces" paragraph ending `… reads and writes all of it.` around line 26).
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/privacy-policy.md` (§5 "Data storage and security", after the OAuth-tokens bullet ~line 119; bump the effective date at line 3).
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/docs/ship.md` (created in Task 8; append the "Publishing privacy-policy changes" note in Step 4).

**Interfaces:**
- Produces: a README desktop-app note and a one-line privacy disclosure that keys/tokens live in a local machine-bound encrypted vault. Flags a privacy "wave" for the user to publish (the two public copies are published by the separate `publish-privacy-policy` skill — this task only updates the canonical doc).
- Consumes: nothing at runtime.

- [ ] **Step 1:** Add the README section. Read `README.md` lines 20–27 to confirm the "Desktop surfaces" paragraph tail, then insert a new subsection immediately after the paragraph ending `… reads and writes all of it.`:

```markdown

### Desktop app (M8)
ScuffedOS also ships as a **double-clickable, unsigned macOS app** (Apple-Silicon
only) built with Tauri: it bundles its own Python runtime, PostgreSQL 17 +
pgvector, and the backend, so the full dashboard runs **offline with no
terminal**. API keys and OAuth credentials are entered in-app under **Settings**
and stored in a machine-bound encrypted vault. Build it with `bash
scripts/build-app.sh`; see [`docs/ship.md`](docs/ship.md) for the build, the
one-time right-click▸Open (quarantine) step, and the acceptance smoke.
```

- [ ] **Step 2:** Bump the privacy-policy effective date. Read `docs/privacy-policy.md` line 3 (`**Effective date:** July 6, 2026`), then change it to `**Effective date:** July 7, 2026`.

- [ ] **Step 3:** Add the vault disclosure. Read `docs/privacy-policy.md` §5 lines 117–120 to confirm the OAuth-tokens bullet (`… stored in the server-side database and are never exposed to the client.`), then insert a new bullet immediately after it:

```markdown
- In the packaged desktop app, API keys and OAuth tokens are stored on your Mac in a machine-bound, AES-256-GCM encrypted vault (`secrets.enc`) rather than in a database; the encryption key is derived from your machine's hardware identifier and wrapped in the macOS Keychain. These secrets never leave your machine.
```

- [ ] **Step 4:** Flag the privacy wave. This task updates only the **canonical** `docs/privacy-policy.md`. The two public copies (the GitHub gist + the scuffed-corporation website `/privacy/`) are published by the separate `publish-privacy-policy` skill as a **user-run step** — note in the commit body that a privacy wave is pending. Do NOT run the publish skill here. To keep this from being silently forgotten after merge, also record it as a durable, discoverable reminder in `docs/ship.md` (not just the commit message): add a short "Publishing privacy-policy changes" note under the Secrets & Settings section pointing at the `publish-privacy-policy` skill, so the sync step is documented in-repo even if the commit body scrolls out of view. (This is a doc-only chore, not a code-blocking gate — the canonical doc is the source of truth; the public mirrors just lag until the skill runs.)

```markdown

### Publishing privacy-policy changes
`docs/privacy-policy.md` is the **canonical** copy. When it changes (e.g. the M8
vault disclosure), its two public mirrors — the GitHub gist and the
scuffed-corporation website `/privacy/` — go stale until you run the
`publish-privacy-policy` skill. After merging any privacy-policy change, run that
skill to sync both mirrors and bump the live effective date.
```

Append this block to `docs/ship.md` (created in Task 8) in the same Task 9 commit, immediately after the "Secrets & Settings" section.

- [ ] **Step 5:** Commit.
```
git add README.md docs/privacy-policy.md docs/ship.md
git commit -m "docs(ship): README desktop-app section + privacy vault disclosure

Adds a Desktop app (M8) README subsection and a one-line privacy-policy bullet
that packaged-app keys/tokens live in a local machine-bound AES-256-GCM vault;
bumps the effective date. PENDING USER: publish the privacy wave (gist + corp
site) via the publish-privacy-policy skill.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Spike C — first-run Settings, key survival across update, vault re-auth, diagnostic window (run-based; closes the slice DoD)

**Files:** none created; run-based verification spike. Record results in the commit message, not a tracked report file.

**Interfaces:** validates the slice-2 DoD (spec §10): a first-run user with an empty vault can enter keys in Settings and use every integration; keys survive an app update (no re-prompt storm); the vault re-auth path recovers a decrypt failure; the diagnostic window renders on a forced boot failure. Requires a built `.app` (rebuild via `bash scripts/build-app.sh` if slice-2 backend/Rust changes are not yet in the bundle).

**Procedure (each step is a discrete pass/fail):**

- [ ] **Step 1 (rebuild with slice-2 code):** `bash /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/build-app.sh`. EXPECTED: completes and prints `==> Done. App at: .../ScuffedOS.app`. The bundle now includes `app/secrets.py`, the settings router, the SettingsScreen, and the diagnostic-window Rust. Set `APP="/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/target/release/bundle/macos/ScuffedOS.app"`.

- [ ] **Step 2 (first-run empty vault):** `rm -rf ~/Library/Application\ Support/ScuffedOS`; `xattr -dr com.apple.quarantine "$APP"; open "$APP"`. Wait for the window. Open **Settings**. EXPECTED: the first-run "Connect your integrations" nudge shows (nothing configured). PASS iff the nudge renders and no secret values are visible anywhere.

- [ ] **Step 3 (enter a key + use it):** In Settings, paste a real `ANTHROPIC_API_KEY`, Save. EXPECTED: the Anthropic chip flips to "Configured". Open the Assistant and send a message. PASS iff the assistant responds live (proving the vault→config seam fed `llm.py` with no restart). Confirm the vault file exists and is `0600`: `stat -f "%Sp" ~/Library/Application\ Support/ScuffedOS/secrets.enc` shows `-rw-------`.

- [ ] **Step 4 (key survives an "update"):** Quit the app. Simulate an app update by rebuilding the bundle (`bash scripts/build-app.sh`) — the machine UUID is unchanged, so the vault must still decrypt. Relaunch, open Settings. EXPECTED: the Anthropic key still shows "Configured" (no re-prompt storm; at most one Keychain "Always Allow" prompt for the wrapped key). PASS iff the key survives and the assistant still works.

- [ ] **Step 5 (vault re-auth recovery):** Force a decrypt failure by rotating the machine id the vault sees. **Important:** `open "$APP"` does NOT pass shell env vars into the bundled app on macOS (there is no reliable `open --env`), so `SCUFFEDOS_VAULT_MACHINE_ID=… open "$APP"` will silently NOT take effect — do not use it. Use one of these two working methods instead:

  **Method A (preferred — launch the bundled binary directly so it inherits the shell env):**
  ```bash
  SCUFFEDOS_VAULT_MACHINE_ID=some-other-id "$APP/Contents/MacOS/scuffedos"
  ```
  (The Tauri binary name matches the bundle; if it differs, `ls "$APP/Contents/MacOS/"` to find it.) The app boots with a different derived key, the vault fails to decrypt, and the UI shows the "Re-authenticate your integrations" banner.

  **Method B (backend-only proxy — run the vendored uvicorn directly and check the API):**
  ```bash
  cd "$APP/Contents/Resources/backend"
  SCUFFEDOS_MANAGED_PG=1 RESOURCES_PGSQL_DIR="$APP/Contents/Resources/pgsql" \
    SCUFFEDOS_VAULT_MACHINE_ID=some-other-id \
    "$APP/Contents/Resources/py/bin/python3" -m uvicorn app.main:app --port 8123
  # in another shell:
  curl -s localhost:8123/api/settings/secrets
  ```
  EXPECTED (either method): the API reports `vault_ok:false` (Method B: in the curl JSON; Method A: the banner renders). PASS iff `vault_ok:false` is observed AND re-entering a key (PUT `/api/settings/secrets`) repairs it (a subsequent GET reports `vault_ok:true`). Kill the manual process afterward.

  > **Fidelity note:** both methods are a best-effort proxy for a genuine hardware move (the definitive test is copying the built `.app` to a physically different Mac, whose real `IOPlatformUUID` differs — out of scope for Slice 2). Method A exercises the full packaged launch path and is the closer proxy; Method B isolates the backend when the GUI is inconvenient.

- [ ] **Step 6 (diagnostic window on boot failure):** Force a health-gate timeout: temporarily break the managed-PG boot (e.g. rename the vendored `initdb` inside a *copy* of the app, or set `RESOURCES_PGSQL_DIR` to a bogus path via a manual launch) so `/health` never comes up, then launch. EXPECTED: instead of a blank window, the **diagnostic window** opens showing the `backend.log`/`pg.log` tails and a Quit button. PASS iff the diagnostic window renders with log content and Quit exits the app. Restore the app afterward.

- [ ] **Step 7 (regression — suite green):** `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. EXPECTED: the full suite is green (baseline **623** + all slice-2 tests: Task 1 +2, Task 2 +21, Task 3 +6, Task 4 +10, Task 5 +5 = **+44** → **667 passed, 1 skipped**). Report the final count.

- [ ] **Step 8:** Commit the spike record + mark the slice DoD.
```
git commit --allow-empty -m "test(ship): Spike C — Settings/secrets first-run + survival verified

First-run empty vault shows the onboarding nudge; entering an Anthropic key in
Settings makes the live assistant work with no restart; the key survives an app
rebuild (no re-prompt storm) since the machine UUID is stable; a forced machine-
id change surfaces vault_ok=false and the re-auth path repairs it; a forced boot
failure renders the diagnostic window with backend/pg log tails. secrets.enc is
0600. Backend suite green (+44 slice-2 tests, 667 passed / 1 skipped).

Slice-2 DoD met: first-run user with an empty vault can enter keys in Settings
and use every integration; keys survive an update; acceptance smoke recorded
(docs/ship.md); suite green.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of Done (spec §10 — Slice 2)

- [ ] **Vault:** `app/secrets.py` `SecretsVault` stores `secrets.enc` (dir `0700`/file `0600`, `nonce||ct||tag`, AES-256-GCM, a **fresh 12-byte nonce every write**, HKDF over `IOPlatformUUID` + `vault.salt`); machine id injectable so unit tests round-trip on ubuntu CI; a hung `ioreg` (TimeoutExpired) degrades to the fallback id; keyring wraps the single key in the packaged path and degrades to a file-only key when the backend is absent or the stored item is malformed (non-hex / not 32 bytes); a truncated/empty `vault.salt` raises `SaltCorruptedError` (never silently regenerated); a bad-tag decrypt raises `VaultDecryptError` (Tasks 1–2).
- [ ] **Config seam:** secrets resolve from the vault first, empty-only override so env/`.env`/tests always win; a decrypt failure is swallowed and never crashes startup; every lazy integration consumer (llm/food_db/memory_engine/plaid/google) transparently reads vault values (Tasks 3, 5).
- [ ] **API:** `GET /api/settings/secrets` returns masked presence + `vault_ok` (never raw values); `PUT` serializes its read-modify-write under a process lock (no lost updates), re-reads to verify the write persisted (silent-write-failure → 503), and re-resolves running settings; unknown keys → 422, a decrypt failure → 422 (re-auth), I/O failure → 503 (Task 4).
- [ ] **Frontend:** `SettingsScreen.jsx` (sidebar entry already wired) shows masked per-integration presence, paste/replace + save, first-run onboarding nudge, and a re-auth recovery banner on `vault_ok:false`; `npm run build` is green (Task 6).
- [ ] **Polish:** the Tauri health-gate timeout opens a diagnostic window surfacing `backend.log`/`pg.log` with a Quit button; `cargo check` green; quit/relaunch wired (Task 7).
- [ ] **Docs:** new `docs/ship.md`; stale M7→M8 Tauri refs fixed in `docs/backend-overview.md` + `backend/app/reminders.py`; README "Desktop app (M8)" section; privacy-policy vault disclosure + bumped effective date; privacy wave flagged for the user to publish (Tasks 8–9).
- [ ] **Spike C:** first-run empty-vault → enter keys → every integration works; keys survive an app rebuild (no re-prompt storm); vault re-auth repairs a forced decrypt failure; diagnostic window renders on a forced boot failure (Task 10).
- [ ] **Suite green** on the SQLite default and unchanged in CI (no `ioreg`/`keyring` backend): the slice-1 baseline (623/1) + 44 new tests → 667 passed / 1 skipped, zero prior-test regressions, reported after each Python task.
