# M8 Ship/Tauri — Slice 1 Implementation Plan

> For agentic workers: execute top to bottom. Each task is self-contained. TDD-able Python tasks (1–4) come first so `cd backend && python -m pytest` stays green throughout; infra/Rust/build tasks (5–11) use explicit run-commands with EXPECTED OUTPUT as their acceptance gate; the two spikes (12–13) come last with concrete pass/fail procedures. Do not skip the commit step at the end of each task. Do not implement anything from Slice 2 (secrets vault, Settings screen, `app/secrets.py`, `/api/settings/*`, Keychain wrapping) — it is out of scope here.

**Goal**
Produce a double-clickable, unsigned `ScuffedOS.app` (macOS arm64) that launches the full dashboard with no terminal: the Tauri shell picks a free port, spawns a Python sidecar that boots a bundled local Postgres (PG17 + pgvector), runs `alembic upgrade head`, and serves the existing FastAPI app; the shell keeps its window hidden until `GET /health` returns 200, then shows the built frontend pointed at `127.0.0.1:<port>`. Data persists under `~/Library/Application Support/ScuffedOS/`. On quit, the Python parent stops Postgres (`pg_ctl stop -m fast`) with a Rust process-tree kill as backstop. Dev and CI behavior is unchanged: everything new is gated behind `SCUFFEDOS_MANAGED_PG`.

**Architecture**
Tauri v2 (Rust + system WKWebView) owns exactly one child — a single-file launcher stub (`externalBin`) that `exec`s the vendored `Resources/py/bin/python3 -m uvicorn app.main:app` with `cwd=Resources/backend`. The Python process owns the local-Postgres lifecycle via a new `app/localdb.py` module (initdb/pg_ctl/wait-ready/alembic/stop) gated on the `SCUFFEDOS_MANAGED_PG` flag added to `app/config.py`. The existing DB seam (`app/db.py normalize_database_url`/`make_engine`) accepts the Unix-socket DSN `postgresql+psycopg://scuffedos@/scuffedos?host=<run-dir>` with **zero code change**. Postgres + pgvector and CPython 3.14 + true-installed deps are vendored as relocatable, ad-hoc-signed Tauri bundle resources produced by `scripts/vendor-postgres.sh` and `scripts/vendor-python.sh`, assembled by `scripts/build-app.sh`.

**Tech Stack**
Backend: Python 3.14, FastAPI, SQLAlchemy 2 + psycopg 3, Alembic, pydantic-settings v2, pytest. Shell: Tauri v2, `tauri-plugin-shell` v2, Rust (edition 2021), `reqwest` 0.12, `sysinfo` ~0.33. Vendoring: `uv` (managed CPython + `py-app-standalone`), `theseus-rs/postgresql-binaries` PG17, pgvector 0.8.4 (compiled), `codesign`/`install_name_tool`/`otool`/`iconutil`. Frontend: Vite 6 + React 18 (existing).

## Global Constraints

- **Platform:** macOS **arm64 only**, **unsigned** (ad-hoc `codesign -s -` only). No Developer ID, no notarization, no DMG/auto-update, no Windows/Linux, no PyInstaller freeze. First launch requires a one-time right-click▸Open (quarantine); do not attempt to work around it.
- **Pinned versions (use verbatim):** PostgreSQL **17.10.0** (theseus-rs/postgresql-binaries, `aarch64-apple-darwin`); pgvector **0.8.4** (compiled against that PG); CPython **3.14.5** via `uv` (`--managed-python 3.14`, cpython-3.14.5); **`py-app-standalone`** true-install (never a venv); **Tauri v2** + **`tauri-plugin-shell` v2**; **Rust ≥ 1.77.2**; **`sysinfo` ~0.33**; **`reqwest` 0.12**. Target triple **aarch64-apple-darwin**.
- **`SCUFFEDOS_MANAGED_PG` semantics:** unset/`false` (dev, CI, tests) → the backend uses external `DATABASE_URL` exactly as today, boots **no** Postgres, zero behavior change. `true`/`1` (packaged app only) → the backend copies/inits/starts the vendored Postgres, sets the socket DSN into `settings.database_url`, runs `alembic upgrade head`, and stops PG on shutdown. The flag defaults to `False`.
- **Suite stays green.** After every Python task (1–4) run `cd backend && python -m pytest` and report the pass count. Baseline before this slice is ~604 tests / 1 skipped (per project memory; confirm at Task 1). New tests must never hard-fail or hard-skip on the SQLite default and must never mutate the autouse `fresh_db`-bound engine.
- **Secrets & Settings are Slice 2 — out of scope.** Do not create `app/secrets.py`, `SettingsScreen.jsx`, `/api/settings/*`, the encrypted vault, or any Keychain wiring in this slice.
- **Branch:** all work lands on `m8-ship-tauri-design`. Per the spec prerequisite, that branch is cut from post-M7 `main`; if M7 Plaid is not yet on `main`, note it but proceed — nothing in Slice 1 references Plaid config fields.

---

### Task 1: Config seam — `SCUFFEDOS_MANAGED_PG` flag + app-support path settings (TDD)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/config.py` (append a new block after the last Moodle field at line 103, before the two blank lines at 104–105; do not touch the `Settings` header at lines 6–12 or the `settings = Settings()` singleton at line 106).
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/.env.example` (append a documented `# --- M8 Ship / managed Postgres ---` section after the Moodle block ending at line 64).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_config.py`.

**Interfaces:**
- Produces (on `settings` / `Settings`): `scuffedos_managed_pg: bool = False` (env `SCUFFEDOS_MANAGED_PG`), `app_support_dir: str = "~/Library/Application Support/ScuffedOS"` (env `APP_SUPPORT_DIR`), `managed_pg_superuser: str = "scuffedos"` (env `MANAGED_PG_SUPERUSER`), `managed_pg_dbname: str = "scuffedos"` (env `MANAGED_PG_DBNAME`).
- Consumes: pydantic-settings v2 `BaseSettings` (already imported). Field→env mapping is default UPPER_SNAKE; no aliases.

- [ ] **Step 1:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5` and record the baseline pass count (expect ~604 passed, 1 skipped). This is the number every later Python task must not regress.

- [ ] **Step 2:** Write the test file. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_config.py` with:

```python
"""M8 Ship/Tauri config seam: the SCUFFEDOS_MANAGED_PG flag defaults off
(dev/tests unchanged) and the app-support path settings expose safe,
import-time-instantiable defaults following the existing local-path idiom."""

from app.config import Settings


def test_managed_pg_defaults_off():
    field = Settings.model_fields["scuffedos_managed_pg"]
    assert field.default is False
    assert field.annotation is bool


def test_app_support_dir_default():
    field = Settings.model_fields["app_support_dir"]
    assert field.annotation is str
    assert "Application Support/ScuffedOS" in field.default


def test_managed_pg_role_and_dbname_defaults():
    assert Settings.model_fields["managed_pg_superuser"].default == "scuffedos"
    assert Settings.model_fields["managed_pg_dbname"].default == "scuffedos"


def test_managed_pg_reads_env(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_MANAGED_PG", "1")
    fresh = Settings()
    assert fresh.scuffedos_managed_pg is True


def test_flag_off_leaves_database_url_default_empty():
    # Fresh Settings with no env: default database_url stays empty so the
    # dev/external-DATABASE_URL path is entirely unaffected by the new flag.
    field = Settings.model_fields["database_url"]
    assert field.default == ""
```

- [ ] **Step 3:** Run the test and confirm it fails (fields don't exist yet): `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_config.py -q`. Expect `KeyError`/collection failures for the four new fields.

- [ ] **Step 4:** Read `backend/app/config.py` lines 100–106 to confirm the exact text at the Moodle-block tail, then insert the new block. After the line `    moodle_backfill_days_ahead: int = 60        # deadline-timeline horizon` (line 103) and before the two blank lines preceding `settings = Settings()`, add:

```python

    # ---- M8 Ship / Tauri — managed local Postgres (packaged app only) ----
    # OFF by default: dev, CI, and the test suite are unchanged and use the
    # external DATABASE_URL exactly as today. The packaged .app sets this to 1,
    # which makes app/localdb.py boot a vendored Postgres under app_support_dir
    # and inject the socket DSN into database_url before the first DB call.
    scuffedos_managed_pg: bool = False           # env SCUFFEDOS_MANAGED_PG
    # Per-user state root; ~ is expanded by app/localdb.py, never here.
    app_support_dir: str = "~/Library/Application Support/ScuffedOS"
    managed_pg_superuser: str = "scuffedos"      # initdb -U role + DSN user
    managed_pg_dbname: str = "scuffedos"         # created DB + DSN dbname
```

- [ ] **Step 5:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_config.py -q` and confirm all five pass.

- [ ] **Step 6:** Read `backend/.env.example` lines 55–64 to confirm the Moodle block tail, then append after line 64:

```
# --- M8 Ship / Tauri — managed local Postgres (packaged .app only) ---
# Leave these UNSET in dev: the app uses DATABASE_URL above exactly as today.
# The bundled ScuffedOS.app sets SCUFFEDOS_MANAGED_PG=1 at launch, which makes
# the backend copy/init/start a vendored Postgres under APP_SUPPORT_DIR and
# build its own socket DSN — you do not set DATABASE_URL in that mode.
# SCUFFEDOS_MANAGED_PG=0
# APP_SUPPORT_DIR=~/Library/Application Support/ScuffedOS
# MANAGED_PG_SUPERUSER=scuffedos
# MANAGED_PG_DBNAME=scuffedos
```

- [ ] **Step 7:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Confirm the baseline count + 5 new tests (e.g. ~609 passed, 1 skipped). Report the pass count.

- [ ] **Step 8:** Commit.
```
git add backend/app/config.py backend/.env.example backend/tests/test_ship_config.py
git commit -m "feat(ship): add SCUFFEDOS_MANAGED_PG flag + app-support path settings

M8 Slice 1 config seam. Flag defaults off so dev/CI/tests are unchanged
and keep using external DATABASE_URL. Packaged app will set it to 1.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `app/localdb.py` — managed-Postgres lifecycle helpers (TDD the pure logic)

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/localdb.py`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_localdb.py`.
- Reference only (no edit): `backend/app/db.py:19` (`normalize_database_url`), `backend/tests/test_migrations.py:18-27` (programmatic alembic `Config` idiom), `backend/app/config.py` (new fields from Task 1).

**Interfaces:**
- Produces:
  - `class Paths` (frozen dataclass) with `root, pgsql_dir, pgdata_dir, run_dir, logs_dir, data_dir: Path`.
  - `resolve_paths(app_support_dir: str) -> Paths` — expands `~`, does not create dirs.
  - `socket_dsn(paths: Paths, user: str, dbname: str) -> str` → `"postgresql+psycopg://<user>@/<dbname>?host=<run_dir>"`.
  - `is_stale_pidfile(pgdata_dir: Path) -> bool` — True iff `postmaster.pid` exists but its PID is not a live process.
  - `pg_bin(paths: Paths, name: str) -> Path` → `paths.pgsql_dir / "bin" / name`.
  - `ensure_dirs(paths: Paths) -> None`; `copy_pgsql_tree(src: Path, paths: Paths) -> None`; `initdb(paths, user) -> None`; `start(paths) -> None`; `wait_ready(paths, dbname, user, timeout_s=30.0) -> None`; `stop(paths) -> None`; `run_alembic_upgrade(dsn: str) -> None`; `boot(settings, resources_pgsql_dir: Path) -> str` (the orchestrator returning the DSN).
- Consumes: `subprocess`, `os`, `shutil`, `signal`, `pathlib.Path`, `time`, `alembic.config.Config`, `alembic.command`, `app.db.normalize_database_url`.

- [ ] **Step 1:** Write the test file. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_localdb.py`:

```python
"""M8 managed-Postgres lifecycle: pure-logic unit tests for DSN construction,
path resolution, and stale-postmaster.pid detection. Subprocess/binary paths
are mocked; real pg binary integration is deferred to Spike B. These tests
never touch the autouse fresh_db engine and pass on the SQLite default."""

import os
from pathlib import Path

import pytest

from app import localdb


def test_resolve_paths_expands_home_and_layout():
    paths = localdb.resolve_paths("~/Library/Application Support/ScuffedOS")
    assert paths.root == Path(os.path.expanduser("~/Library/Application Support/ScuffedOS"))
    assert paths.pgdata_dir == paths.root / "pgdata"
    assert paths.run_dir == paths.root / "run"
    assert paths.pgsql_dir == paths.root / "pgsql"
    assert paths.logs_dir == paths.root / "logs"
    assert paths.data_dir == paths.root / "data"


def test_socket_dsn_shape(tmp_path):
    paths = localdb.resolve_paths(str(tmp_path))
    dsn = localdb.socket_dsn(paths, "scuffedos", "scuffedos")
    assert dsn == f"postgresql+psycopg://scuffedos@/scuffedos?host={paths.run_dir}"
    # Survives the app.db normalizer unchanged (already +psycopg).
    from app.db import normalize_database_url
    assert normalize_database_url(dsn) == dsn


def test_pg_bin_path(tmp_path):
    paths = localdb.resolve_paths(str(tmp_path))
    assert localdb.pg_bin(paths, "pg_ctl") == paths.pgsql_dir / "bin" / "pg_ctl"


def test_stale_pidfile_absent_is_not_stale(tmp_path):
    (tmp_path / "pgdata").mkdir()
    assert localdb.is_stale_pidfile(tmp_path / "pgdata") is False


def test_stale_pidfile_dead_pid_is_stale(tmp_path):
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    # PID 2^31-1 is astronomically unlikely to be live.
    (pgdata / "postmaster.pid").write_text("2147483647\n/some/data\n")
    assert localdb.is_stale_pidfile(pgdata) is True


def test_stale_pidfile_live_pid_is_not_stale(tmp_path):
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "postmaster.pid").write_text(f"{os.getpid()}\n/some/data\n")
    assert localdb.is_stale_pidfile(pgdata) is False


def test_stale_pidfile_garbage_first_line_is_stale(tmp_path):
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "postmaster.pid").write_text("not-a-number\n")
    assert localdb.is_stale_pidfile(pgdata) is True


def test_start_clears_stale_pidfile_before_pg_ctl(tmp_path, monkeypatch):
    paths = localdb.resolve_paths(str(tmp_path))
    localdb.ensure_dirs(paths)
    (paths.pgdata_dir / "postmaster.pid").write_text("2147483647\n")
    calls = []
    monkeypatch.setattr(localdb.subprocess, "run",
                        lambda *a, **k: calls.append(a[0]) or _ok())
    localdb.start(paths)
    assert not (paths.pgdata_dir / "postmaster.pid").exists()
    assert any("pg_ctl" in " ".join(map(str, c)) for c in calls)


def test_initdb_invokes_binary_with_expected_args(tmp_path, monkeypatch):
    paths = localdb.resolve_paths(str(tmp_path))
    localdb.ensure_dirs(paths)
    seen = {}
    monkeypatch.setattr(localdb.subprocess, "run",
                        lambda argv, **k: seen.setdefault("argv", argv) or _ok())
    localdb.initdb(paths, "scuffedos")
    argv = seen["argv"]
    joined = " ".join(map(str, argv))
    assert "initdb" in joined
    assert "-U" in argv and "scuffedos" in argv
    assert "--auth-local=trust" in joined
    assert "--auth-host=scram-sha-256" in joined


def _ok():
    class _R:
        returncode = 0
        stdout = b""
        stderr = b""
    return _R()
```

- [ ] **Step 2:** Run the tests and confirm they fail (module missing): `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_localdb.py -q`. Expect `ModuleNotFoundError: app.localdb`.

- [ ] **Step 3:** Implement the module. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/localdb.py`:

```python
"""M8 Ship/Tauri — managed local Postgres lifecycle (packaged .app only).

This module is exercised ONLY when SCUFFEDOS_MANAGED_PG is truthy (set by the
bundled app). In dev/CI/tests the flag is off and none of this runs, so the
external DATABASE_URL path is completely unaffected.

The Python process owns the Postgres lifecycle: copy the vendored tree into
App Support on first run, initdb, pg_ctl start over a Unix socket, alembic
upgrade head, serve, and pg_ctl stop -m fast on shutdown. The socket DSN
`postgresql+psycopg://<user>@/<db>?host=<run-dir>` flows through app.db and
alembic with no code change (psycopg 3 reads host=<dir> as a socket dir).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config

# backend/ = this file's parent's parent (app/localdb.py -> app -> backend).
BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Paths:
    root: Path
    pgsql_dir: Path
    pgdata_dir: Path
    run_dir: Path
    logs_dir: Path
    data_dir: Path


def resolve_paths(app_support_dir: str) -> Paths:
    root = Path(os.path.expanduser(app_support_dir)).resolve()
    return Paths(
        root=root,
        pgsql_dir=root / "pgsql",
        pgdata_dir=root / "pgdata",
        run_dir=root / "run",
        logs_dir=root / "logs",
        data_dir=root / "data",
    )


def socket_dsn(paths: Paths, user: str, dbname: str) -> str:
    return f"postgresql+psycopg://{user}@/{dbname}?host={paths.run_dir}"


def pg_bin(paths: Paths, name: str) -> Path:
    return paths.pgsql_dir / "bin" / name


def ensure_dirs(paths: Paths) -> None:
    for d in (paths.root, paths.pgdata_dir, paths.run_dir, paths.logs_dir, paths.data_dir):
        d.mkdir(parents=True, exist_ok=True)


def is_stale_pidfile(pgdata_dir: Path) -> bool:
    """True iff a postmaster.pid exists but its PID is not a live process.

    A leftover pid file from a hard-killed app blocks pg_ctl start; we clear it
    only when the recorded PID is provably dead (or the file is unparseable).
    """
    pidfile = pgdata_dir / "postmaster.pid"
    if not pidfile.exists():
        return False
    try:
        first = pidfile.read_text().splitlines()[0].strip()
        pid = int(first)
    except (ValueError, IndexError):
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)  # signal 0 = liveness probe, does not touch the process
    except ProcessLookupError:
        return True
    except PermissionError:
        return False  # exists but owned by someone else -> treat as live
    return False


def copy_pgsql_tree(src: Path, paths: Paths) -> None:
    """Copy the vendored pgsql tree into App Support on first run only.

    Preserves executable bits and ad-hoc signatures (copy2 keeps mode/xattrs
    on macOS via shutil's metadata copy). Skips if already present.
    """
    if paths.pgsql_dir.exists():
        return
    shutil.copytree(src, paths.pgsql_dir, symlinks=True)


def _run(argv: list, **kwargs) -> subprocess.CompletedProcess:
    proc = subprocess.run(argv, capture_output=True, **kwargs)
    if proc.returncode != 0:
        out = (proc.stdout or b"").decode(errors="replace")
        err = (proc.stderr or b"").decode(errors="replace")
        raise RuntimeError(f"{argv[0]} failed ({proc.returncode}):\n{out}\n{err}")
    return proc


def initdb(paths: Paths, user: str) -> None:
    _run([
        str(pg_bin(paths, "initdb")),
        "-D", str(paths.pgdata_dir),
        "-U", user,
        "--auth-local=trust",
        "--auth-host=scram-sha-256",
        "-E", "UTF8",
    ])


def start(paths: Paths) -> None:
    if is_stale_pidfile(paths.pgdata_dir):
        (paths.pgdata_dir / "postmaster.pid").unlink(missing_ok=True)
    logfile = paths.logs_dir / "pg.log"
    _run([
        str(pg_bin(paths, "pg_ctl")),
        "-D", str(paths.pgdata_dir),
        "-l", str(logfile),
        "-o", f"-k {paths.run_dir} -c listen_addresses=127.0.0.1 -c jit=off",
        "-w", "start",
    ])


def stop(paths: Paths) -> None:
    _run([
        str(pg_bin(paths, "pg_ctl")),
        "-D", str(paths.pgdata_dir),
        "stop", "-m", "fast", "-w",
    ])


def wait_ready(paths: Paths, dbname: str, user: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    isready = str(pg_bin(paths, "pg_isready"))
    while time.monotonic() < deadline:
        proc = subprocess.run(
            [isready, "-h", str(paths.run_dir), "-d", dbname, "-U", user],
            capture_output=True,
        )
        if proc.returncode == 0:
            return
        time.sleep(0.2)
    raise RuntimeError(f"Postgres not ready after {timeout_s}s (see {paths.logs_dir/'pg.log'})")


def _db_exists(paths: Paths, dbname: str, user: str) -> bool:
    """True if `dbname` exists — a locale-independent pg_database query
    (createdb's error wording is not contractual across PG builds/locales)."""
    psql = str(pg_bin(paths, "psql"))
    q = subprocess.run(
        [psql, "-h", str(paths.run_dir), "-U", user, "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'"],
        capture_output=True,
    )
    return q.returncode == 0 and (q.stdout or b"").strip() == b"1"


def ensure_database(paths: Paths, dbname: str, user: str) -> None:
    """Create the application database if initdb only made the bootstrap DBs.

    Idempotent by *checking existence* rather than parsing createdb's stderr.
    """
    if _db_exists(paths, dbname, user):
        return
    createdb = str(pg_bin(paths, "createdb"))
    proc = subprocess.run(
        [createdb, "-h", str(paths.run_dir), "-U", user, dbname],
        capture_output=True,
    )
    # Tolerate a create race: re-check existence before treating it as fatal.
    if proc.returncode != 0 and not _db_exists(paths, dbname, user):
        raise RuntimeError((proc.stderr or b"").decode(errors="replace"))


def run_alembic_upgrade(dsn: str) -> None:
    """Programmatic 'alembic upgrade head' with absolute paths (cwd-agnostic).

    Mirrors tests/test_migrations.py:_make_cfg so a bundled app whose cwd is
    Resources/backend still finds alembic.ini + the versions dir.
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(cfg, "head")


def boot(settings, resources_pgsql_dir: Path) -> str:
    """Full managed-PG boot; returns the socket DSN. Idempotent across runs."""
    paths = resolve_paths(settings.app_support_dir)
    ensure_dirs(paths)
    copy_pgsql_tree(resources_pgsql_dir, paths)
    if not (paths.pgdata_dir / "PG_VERSION").exists():
        initdb(paths, settings.managed_pg_superuser)
    start(paths)
    wait_ready(paths, settings.managed_pg_dbname, settings.managed_pg_superuser)
    ensure_database(paths, settings.managed_pg_dbname, settings.managed_pg_superuser)
    dsn = socket_dsn(paths, settings.managed_pg_superuser, settings.managed_pg_dbname)
    run_alembic_upgrade(dsn)
    return dsn


def shutdown(settings) -> None:
    """Stop the managed Postgres if it's the one we started. Safe to call twice."""
    paths = resolve_paths(settings.app_support_dir)
    if not (paths.pgdata_dir / "postmaster.pid").exists():
        return
    try:
        stop(paths)
    except RuntimeError:
        pass  # best-effort; the Rust tree-kill backstop covers a wedged stop
```

- [ ] **Step 4:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_localdb.py -q` and confirm all pass.

- [ ] **Step 5:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Confirm no regression (baseline + Task 1's 5 + this task's 9 ≈ 618 passed, 1 skipped). Report the pass count.

- [ ] **Step 6:** Commit.
```
git add backend/app/localdb.py backend/tests/test_localdb.py
git commit -m "feat(ship): app/localdb.py managed-Postgres lifecycle helpers

Pure logic (DSN, path resolution, stale-pid detection) is unit-tested with
mocked subprocess; real binary integration is deferred to Spike B. Socket DSN
passes through app.db.normalize_database_url unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `GET /health` endpoint (TDD)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py` (add a new bare route immediately after the existing `/api/health` handler at lines 84–86; leave `/api/health` untouched).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_health.py`.

**Interfaces:**
- Produces: `GET /health` → `{"status": "ok"}`, HTTP 200. This is the endpoint the Rust health-gate polls; it must be dependency-free (no DB access) so it returns 200 the instant uvicorn is up, independent of managed-PG readiness.
- Consumes: existing `app = FastAPI(...)` at `main.py:60`.

- [ ] **Step 1:** Write the test. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_health.py`:

```python
"""M8 Ship/Tauri: a bare-root GET /health for the Tauri health-gate. Distinct
from the existing /api/health (which the frontend Vite proxy reaches). This
one is DB-free so it flips to 200 the moment uvicorn is up."""


def test_ship_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_existing_api_health_unchanged(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "scuffed-os-api"}
```

- [ ] **Step 2:** Run and confirm the new test fails: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_health.py -q`. Expect `test_ship_health_ok` to 404.

- [ ] **Step 3:** Read `backend/app/main.py` lines 84–86, then insert immediately after the existing `health()` function (after line 86):

```python


@app.get("/health", tags=["meta"])
def ship_health() -> dict:
    """Bare-root health probe for the Tauri sidecar gate.

    Intentionally DB-free: returns 200 as soon as uvicorn is serving, so the
    Rust shell can show the window without waiting on managed-Postgres. The
    /api/health route above is the frontend-facing one behind the Vite proxy.
    """
    return {"status": "ok"}
```

- [ ] **Step 4:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_health.py -q` and confirm both pass.

- [ ] **Step 5:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Report the pass count (≈ 620 passed, 1 skipped).

- [ ] **Step 6:** Commit.
```
git add backend/app/main.py backend/tests/test_ship_health.py
git commit -m "feat(ship): add DB-free GET /health for the Tauri health-gate

Bare-root /health returns {status: ok} the instant uvicorn is up, distinct
from /api/health. Existing /api/health is unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Lifespan wiring — boot/stop managed PG behind the flag + atexit/SIGTERM (TDD flag-off no-op)

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/app/main.py` (imports at lines 16–33; lifespan at lines 36–57; module scope after `app = FastAPI(...)` at line 60).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_lifespan.py`.

**Interfaces:**
- Consumes: `app.localdb.boot(settings, resources_pgsql_dir) -> str`, `app.localdb.shutdown(settings)`, `settings.scuffedos_managed_pg`, `settings.database_url`.
- Produces: managed-PG boot at the top of the lifespan body (gated on `SCUFFEDOS_MANAGED_PG`, before any sync loop starts); teardown after the existing task-cancel loop; an idempotent `atexit`/`SIGTERM` backstop registered at module scope. Flag-off ⇒ zero new behavior (asserted by test + full suite staying green). The Rust shell sets `SCUFFEDOS_MANAGED_PG=1` and points the backend at the bundled tree via env; the resources dir is resolved from `RESOURCES_PGSQL_DIR` env (set by the launcher stub) with a fallback next to the app-support copy.

- [ ] **Step 1:** Write the test. Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/tests/test_ship_lifespan.py`:

```python
"""M8 lifespan wiring: managed-PG boot/stop is gated on SCUFFEDOS_MANAGED_PG.
Flag OFF (the dev/test default) => localdb.boot is never called and startup is
byte-for-byte the old behavior. Flag ON => boot runs before the sync loops and
its returned DSN lands in settings.database_url."""

from app import main as appmain
from app.config import settings


def test_flag_off_does_not_boot_localdb(monkeypatch):
    called = {"boot": 0}
    monkeypatch.setattr(appmain.localdb, "boot",
                        lambda *a, **k: called.__setitem__("boot", called["boot"] + 1) or "x")
    monkeypatch.setattr(settings, "scuffedos_managed_pg", False)
    # Drive only the managed-PG boot branch (not the whole lifespan/loops).
    appmain._maybe_boot_managed_pg()
    assert called["boot"] == 0


def test_flag_on_boots_and_sets_dsn(monkeypatch):
    monkeypatch.setattr(appmain.localdb, "boot",
                        lambda *a, **k: "postgresql+psycopg://scuffedos@/scuffedos?host=/x/run")
    monkeypatch.setattr(settings, "scuffedos_managed_pg", True)
    monkeypatch.setattr(settings, "database_url", "")
    appmain._maybe_boot_managed_pg()
    assert settings.database_url == "postgresql+psycopg://scuffedos@/scuffedos?host=/x/run"


def test_flag_off_shutdown_is_noop(monkeypatch):
    called = {"shutdown": 0}
    monkeypatch.setattr(appmain.localdb, "shutdown",
                        lambda *a, **k: called.__setitem__("shutdown", called["shutdown"] + 1))
    monkeypatch.setattr(settings, "scuffedos_managed_pg", False)
    appmain._maybe_stop_managed_pg()
    assert called["shutdown"] == 0
```

- [ ] **Step 2:** Run and confirm failure (helpers don't exist): `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_lifespan.py -q`. Expect `AttributeError: _maybe_boot_managed_pg`.

- [ ] **Step 3:** Read `backend/app/main.py` lines 1–20 and 36–60 to confirm current text. Add `import atexit`, `import os`, `import signal`, and `from . import localdb` to the import block. In the existing import section, after the line `from . import email_sync, fitness_sync, moodle_sync, reminders` (line 19), add:

```python
from . import localdb
```
and near the stdlib imports at the top of the file (lines 13–14 already have `import asyncio`, `import contextlib`), add:
```python
import atexit
import os
import signal
```

- [ ] **Step 4:** Add the boot/stop helpers and a shutdown guard at module scope. Insert immediately before the `@contextlib.asynccontextmanager` decorator at line 36:

```python
_pg_stopped = False


def _resources_pgsql_dir() -> "os.PathLike | str":
    """Where the vendored pgsql tree lives before it's copied to App Support.

    The launcher stub exports RESOURCES_PGSQL_DIR pointing at
    Contents/Resources/pgsql. If unset (e.g. a manual managed-PG dev run),
    fall back to a sibling 'pgsql' of the app-support root.
    """
    env = os.environ.get("RESOURCES_PGSQL_DIR")
    if env:
        return env
    paths = localdb.resolve_paths(settings.app_support_dir)
    return paths.pgsql_dir


def _maybe_boot_managed_pg() -> None:
    if not settings.scuffedos_managed_pg:
        return
    dsn = localdb.boot(settings, _resources_pgsql_dir())
    settings.database_url = dsn


def _maybe_stop_managed_pg() -> None:
    global _pg_stopped
    if _pg_stopped or not settings.scuffedos_managed_pg:
        return
    _pg_stopped = True
    localdb.shutdown(settings)
```

- [ ] **Step 5:** Wire the helpers into the lifespan. Change the lifespan body so `_maybe_boot_managed_pg()` runs first (before the `reminder_task` declaration) and `_maybe_stop_managed_pg()` runs after the existing task-cancel loop. The edited function becomes:

```python
@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the reminder tick and the fitness/email/moodle-sync loops alongside
    the server; stop them on shutdown. In the packaged app (SCUFFEDOS_MANAGED_PG)
    also boot a local Postgres before any DB-touching loop and stop it last."""
    _maybe_boot_managed_pg()
    reminder_task: asyncio.Task | None = None
    fitness_task: asyncio.Task | None = None
    email_task: asyncio.Task | None = None
    moodle_task: asyncio.Task | None = None
    if settings.reminders_enabled:
        reminder_task = asyncio.create_task(reminders.run_loop())
    if settings.fitness_sync_enabled:
        fitness_task = asyncio.create_task(fitness_sync.run_loop())
    if settings.email_sync_enabled:
        email_task = asyncio.create_task(email_sync.run_loop())
    if settings.moodle_sync_enabled:
        moodle_task = asyncio.create_task(moodle_sync.run_loop())
    yield
    for task in (reminder_task, fitness_task, email_task, moodle_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    _maybe_stop_managed_pg()
```

- [ ] **Step 6:** Register the hard-exit backstop at module scope. Immediately after `app = FastAPI(title="Scuffed OS API", version="0.1.0", lifespan=lifespan)` (line 60), add:

```python

# Hard-exit safety net: the lifespan post-yield block does not run on SIGTERM/
# hard exit, so also stop the managed Postgres from atexit + a SIGTERM handler.
# Both call the idempotent _maybe_stop_managed_pg (guarded by _pg_stopped), so a
# clean shutdown never double-stops. On the flag-off dev path these are no-ops.
atexit.register(_maybe_stop_managed_pg)


def _sigterm_stop(_signum, _frame):
    _maybe_stop_managed_pg()
    raise SystemExit(0)


try:
    signal.signal(signal.SIGTERM, _sigterm_stop)
except ValueError:
    # signal.signal only works on the main thread; TestClient/threaded runs skip it.
    pass
```

- [ ] **Step 7:** Run `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest tests/test_ship_lifespan.py -q` and confirm all three pass.

- [ ] **Step 8:** Run the full suite: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/backend && python -m pytest -q 2>&1 | tail -5`. Confirm no regression and that flag-off startup is unchanged (all prior tests green). Report the pass count (≈ 623 passed, 1 skipped).

- [ ] **Step 9:** Commit.
```
git add backend/app/main.py backend/tests/test_ship_lifespan.py
git commit -m "feat(ship): boot/stop managed Postgres in lifespan behind the flag

Managed-PG boots before the sync loops and stops after them, plus an
idempotent atexit/SIGTERM backstop. Flag-off is a strict no-op; suite green.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

> **Verification boundary:** these unit tests assert the flag-off no-op (dev/CI/tests never boot managed PG) and that `boot`/`shutdown` are called vs skipped per the flag. The *runtime ordering guarantee* — managed Postgres boots BEFORE the sync loops start and stops AFTER they cancel — is exercised end-to-end in **Task 13 (Spike B, offline boot)**, not unit-tested, because the suite always runs flag-off.

---

### Task 5: `scripts/vendor-postgres.sh` — vendor PG17 + build pgvector + re-sign (run-based acceptance)

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-postgres.sh`.

**Interfaces:**
- Produces: `build/pgsql/` — a relocatable PostgreSQL 17.10.0 tree with pgvector 0.8.4 installed and `vector.dylib` ad-hoc signed. Also `build/pgsql.stamp` recording the versions.
- Consumes: network (download of theseus PG binaries + pgvector source at build time only), `curl`, `tar`, `make`, `codesign`, `otool`, Xcode command-line tools.

- [ ] **Step 1:** Create the script. Write `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-postgres.sh`:

```bash
#!/usr/bin/env bash
# Vendor a relocatable PostgreSQL 17.10.0 (arm64) with pgvector 0.8.4 for the
# ScuffedOS .app bundle. Run on an Apple-Silicon Mac with Xcode CLT installed.
set -euo pipefail

PG_VERSION="17.10.0"
PGVECTOR_VERSION="0.8.4"
ARCH="aarch64-apple-darwin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
WORK="$BUILD/_pgwork"
OUT="$BUILD/pgsql"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$OUT"

echo "==> Downloading PostgreSQL $PG_VERSION ($ARCH) from theseus-rs"
PG_URL="https://github.com/theseus-rs/postgresql-binaries/releases/download/${PG_VERSION}/postgresql-${PG_VERSION}-${ARCH}.tar.gz"
curl -fL "$PG_URL" -o "$WORK/pg.tar.gz"
tar -xzf "$WORK/pg.tar.gz" -C "$WORK"
# theseus tarball extracts to a single top dir; move its contents into OUT.
PGSRC="$(find "$WORK" -maxdepth 1 -type d -name 'postgresql-*' | head -1)"
cp -R "$PGSRC"/. "$OUT"/
PGROOT="$OUT"
PG_CONFIG="$PGROOT/bin/pg_config"
test -x "$PG_CONFIG" || { echo "pg_config missing at $PG_CONFIG"; exit 1; }

echo "==> Building pgvector $PGVECTOR_VERSION against vendored PG"
curl -fL "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" \
  -o "$WORK/pgvector.tar.gz"
tar -xzf "$WORK/pgvector.tar.gz" -C "$WORK"
PVSRC="$WORK/pgvector-${PGVECTOR_VERSION}"
make -C "$PVSRC" clean || true
make -C "$PVSRC" PG_CONFIG="$PG_CONFIG"
make -C "$PVSRC" PG_CONFIG="$PG_CONFIG" install

echo "==> Ad-hoc re-signing pgvector"
VECTOR_DYLIB="$($PG_CONFIG --pkglibdir)/vector.dylib"
test -f "$VECTOR_DYLIB" || { echo "vector.dylib not installed at $VECTOR_DYLIB"; exit 1; }
codesign --force --sign - "$VECTOR_DYLIB"

echo "==> Relocation check (no /opt/homebrew or absolute build paths)"
BAD=0
while IFS= read -r macho; do
  if otool -L "$macho" 2>/dev/null | grep -E '/opt/homebrew|/usr/local/Cellar' >/dev/null; then
    echo "NON-RELOCATABLE: $macho"
    otool -L "$macho" | grep -E '/opt/homebrew|/usr/local/Cellar'
    BAD=1
  fi
done < <(find "$PGROOT" \( -name '*.dylib' -o -name '*.so' \) -o -path '*/bin/*' -type f)
if [ "$BAD" -ne 0 ]; then
  echo "FAIL: non-relocatable references found"; exit 1
fi

echo "==> Verifying vector.dylib links only relocatable paths"
otool -L "$VECTOR_DYLIB"

echo "PG_VERSION=$PG_VERSION PGVECTOR_VERSION=$PGVECTOR_VERSION ARCH=$ARCH" > "$BUILD/pgsql.stamp"
echo "==> Done: $OUT"
```

- [ ] **Step 2:** `chmod +x /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-postgres.sh`.

- [ ] **Step 3 (acceptance):** Run `bash /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-postgres.sh`. EXPECTED: it prints `==> Done: .../build/pgsql`, exits 0, and the relocation check prints no `NON-RELOCATABLE` lines. If any `/opt/homebrew` reference appears the script exits 1 — that is a real failure to fix (the theseus tarball should be clean; a homebrew leak means pgvector picked up a system lib).

- [ ] **Step 4 (acceptance):** Verify the tree runs standalone (no PATH deps): `/Users/dylanschempp/PycharmProjects/ScuffedOS/build/pgsql/bin/postgres --version` prints `postgres (PostgreSQL) 17.10.0`, and `test -f build/pgsql/lib/vector.dylib || test -f "$(build/pgsql/bin/pg_config --pkglibdir)/vector.dylib"` succeeds. Also run `otool -L build/pgsql/bin/postgres` and confirm every non-system path is `@loader_path`/`@rpath`-relative.

- [ ] **Step 5:** Commit (script only; `build/` is a gitignored artifact). First ensure `build/` is ignored: `grep -qx 'build/' /Users/dylanschempp/PycharmProjects/ScuffedOS/.gitignore || echo 'build/' >> /Users/dylanschempp/PycharmProjects/ScuffedOS/.gitignore`.
```
git add scripts/vendor-postgres.sh .gitignore
git commit -m "chore(ship): vendor-postgres.sh — PG17.10.0 + pgvector 0.8.4, re-signed

Downloads relocatable theseus PG17, builds pgvector against it, ad-hoc signs
vector.dylib, and fails on any /opt/homebrew or absolute-build-path reference.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `scripts/vendor-python.sh` — true-install CPython 3.14 + deps + re-sign (run-based acceptance)

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-python.sh`.
- Reference: `/Users/dylanschempp/PycharmProjects/ScuffedOS/backend/requirements.txt` (the dep list).

**Interfaces:**
- Produces: `build/py/` — a relocatable CPython 3.14.5 with backend deps true-installed (not a venv), pruned, and every touched Mach-O ad-hoc signed. `build/py.stamp` records versions.
- Consumes: `uv` (installs managed CPython + runs `py-app-standalone`), network at build time only, `install_name_tool`, `codesign`, `otool`.

- [ ] **Step 1:** Confirm `uv` is available: `uv --version` (install with `curl -LsSf https://astral.sh/uv/install.sh | sh` if absent). Confirm the dep list: `cat /Users/dylanschempp/PycharmProjects/ScuffedOS/backend/requirements.txt`. **Then lock the `py-app-standalone` CLI interface before the script relies on it:** run `uvx py-app-standalone --help` and confirm the flag names used in Step 2 (`--python`, `--requirements`, `-o`, plus positional extra deps). If the real interface differs (e.g. deps are passed differently, or the output flag is `--output`), adjust the invocation in Step 2 to match before running it — do not guess.

- [ ] **Step 2:** Create the script. Write `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-python.sh`:

```bash
#!/usr/bin/env bash
# Vendor a relocatable CPython 3.14.5 with backend deps TRUE-INSTALLED (not a
# venv) for the ScuffedOS .app. Fails loudly if any dep compiles from sdist
# (that would break offline first-run). Apple-Silicon only.
set -euo pipefail

PY_SERIES="3.14"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
OUT="$BUILD/py"
REQ="$ROOT/backend/requirements.txt"

rm -rf "$OUT"
mkdir -p "$BUILD"

echo "==> Installing managed CPython $PY_SERIES via uv"
uv python install --managed-python "$PY_SERIES"

echo "==> True-installing deps into a copy of the interpreter (py-app-standalone)"
# --check-build-dependencies-style guard: force wheels only, so a missing cp314
# wheel FAILS instead of silently sdist-compiling.
export PIP_ONLY_BINARY=":all:"
# NOTE: `cryptography` is a DELIBERATE forward-vendor. It is Slice 2's secrets-
# vault dependency (spec §4.5), not a Slice-1 runtime need — bundling it now
# means Slice 2 does not have to re-vendor the whole (~195 MB) interpreter tree
# just to add one wheel. It is inert at runtime until Slice 2 imports it.
# (If flag names differ, Step 1's `--help` probe told you; fix them here.)
uvx py-app-standalone \
  --python "$PY_SERIES" \
  --requirements "$REQ" \
  uvicorn[standard] cryptography \
  -o "$OUT"

echo "==> Relocation fix: libpython install-name + re-sign"
LIBPY="$(find "$OUT/lib" -maxdepth 1 -name 'libpython3.14*.dylib' | head -1)"
if [ -n "${LIBPY:-}" ]; then
  install_name_tool -id "@executable_path/../lib/$(basename "$LIBPY")" "$LIBPY"
  codesign --force -s - "$LIBPY"
fi

echo "==> Pruning caches/tests/static-libs"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.a' -delete 2>/dev/null || true
find "$OUT/lib" -type d -name 'test' -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$OUT"/lib/python3.14/{idlelib,turtledemo,tkinter} 2>/dev/null || true

echo "==> Re-signing every Mach-O we may have touched"
find "$OUT" -type f \( -name '*.dylib' -o -name '*.so' \) -exec codesign --force -s - {} + 2>/dev/null || true
codesign --force -s - "$OUT/bin/python3" 2>/dev/null || true

echo "==> Fail-on-sdist audit: verify all C-extension deps have cp314 arm64 .so"
# psycopg (binary), pydantic_core, and any compiled dep must exist as loadable
# .so under the tree. A build that sdist-compiled would have left cpython-3.14
# .so's too, but PIP_ONLY_BINARY above already aborts the install on a missing
# wheel; this is the belt-and-suspenders smoke import.
"$OUT/bin/python3" - <<'PY'
import importlib, sys
sys.exit(0 if all(
    importlib.util.find_spec(m) for m in ("psycopg", "pydantic_core", "fastapi", "uvicorn", "alembic")
) else 1)
PY

echo "==> otool relocation check (no /opt/homebrew, no absolute build paths)"
BAD=0
while IFS= read -r macho; do
  if otool -L "$macho" 2>/dev/null | grep -E '/opt/homebrew|/usr/local/Cellar|/private/var/folders' >/dev/null; then
    echo "NON-RELOCATABLE: $macho"; BAD=1
  fi
done < <(find "$OUT" \( -name '*.dylib' -o -name '*.so' \))
[ "$BAD" -eq 0 ] || { echo "FAIL: non-relocatable references"; exit 1; }

echo "PY_SERIES=$PY_SERIES" > "$BUILD/py.stamp"
echo "==> Done: $OUT"
```

- [ ] **Step 3:** `chmod +x /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-python.sh`.

- [ ] **Step 4 (acceptance):** Run `bash /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/vendor-python.sh`. EXPECTED: prints `==> Done: .../build/py`, exits 0. If it exits during the true-install with a "no binary wheel" / sdist error, that is the intended fail-loud path — a dep lacks a cp314 arm64 wheel and must be pinned/substituted before shipping (see spec §4.3: verify `psycopg[binary]`, `pydantic-core`, `uvloop`, mem0's `grpc`/`numpy`).

- [ ] **Step 5 (acceptance):** Verify the tree runs uvicorn offline from an arbitrary cwd: `cd / && /Users/dylanschempp/PycharmProjects/ScuffedOS/build/py/bin/python3 -c "import uvicorn, fastapi, psycopg, alembic; print('imports-ok')"` prints `imports-ok`. Confirm no absolute *interpreter* pin leaked into `bin/` shebangs — the real risk is a pin at the uv managed-CPython cache, not the project dir: `grep -rIl "$HOME/.local/share/uv" /Users/dylanschempp/PycharmProjects/ScuffedOS/build/py/bin/ && { echo "FAIL: abs uv-cache pin in bin/"; false; } || echo "no-abs-path-pins"` prints `no-abs-path-pins`. (The stronger relocation gate is the `otool` `/opt/homebrew`/`/private/var/folders` scan already inside the script.)

- [ ] **Step 6:** Commit.
```
git add scripts/vendor-python.sh
git commit -m "chore(ship): vendor-python.sh — true-install CPython 3.14 + deps

py-app-standalone true-install (never a venv), relocation fixes, ad-hoc
re-sign, and a fail-loud audit if any dep sdist-compiles instead of using a
cp314 arm64 wheel.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `src-tauri` scaffold — conf, Cargo, capabilities, launcher stub source

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/tauri.conf.json`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/Cargo.toml`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/build.rs`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/capabilities/default.json`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/binaries/.gitkeep` (the target-triple-suffixed stub binary is produced by the build script, Task 9; keep the dir tracked).

**Interfaces:**
- Produces the Tauri v2 project skeleton: `bundle.resources` for `py`/`pgsql`/`backend`/`dist`; `bundle.externalBin` = `binaries/scuffedos-backend`; hidden main window; `shell:allow-spawn` capability with an exact `--port <digits>` args validator. `src/lib.rs` is written in Task 8.
- Consumes: Rust ≥ 1.77.2, `tauri` v2, `tauri-plugin-shell` v2.

- [ ] **Step 1:** Confirm Rust: `rustc --version` (must be ≥ 1.77.2; install via `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh` if absent). Confirm the Tauri CLI: `cargo tauri --version` (install with `cargo install tauri-cli --version '^2'` if absent).

- [ ] **Step 2:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "ScuffedOS",
  "version": "0.1.0",
  "identifier": "com.scuffedos.app",
  "build": {
    "frontendDist": "../frontend/dist"
  },
  "app": {
    "windows": [
      {
        "title": "ScuffedOS",
        "width": 1280,
        "height": 832,
        "visible": false
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": true,
    "targets": ["app"],
    "icon": ["icons/icon.icns"],
    "externalBin": ["binaries/scuffedos-backend"],
    "resources": {
      "../build/py": "py",
      "../build/pgsql": "pgsql",
      "../backend": "backend",
      "../frontend/dist": "dist"
    }
  },
  "plugins": {}
}
```

- [ ] **Step 3:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/Cargo.toml`:

```toml
[package]
name = "scuffedos"
version = "0.1.0"
edition = "2021"
rust-version = "1.77.2"

[lib]
name = "scuffedos_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-shell = "2"
reqwest = { version = "0.12", features = ["blocking"] }
sysinfo = "0.33"
serde = { version = "1", features = ["derive"] }
serde_json = "1"

[profile.release]
opt-level = "s"
lto = true
strip = true
```

- [ ] **Step 4:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

- [ ] **Step 5:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/capabilities/default.json`. The `args` validator must match exactly what Rust passes (`--port <digits>`):

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "ScuffedOS shell: spawn the backend sidecar only.",
  "windows": ["main"],
  "permissions": [
    "core:default",
    {
      "identifier": "shell:allow-spawn",
      "allow": [
        {
          "name": "binaries/scuffedos-backend",
          "sidecar": true,
          "args": ["--port", { "validator": "\\d+" }]
        }
      ]
    }
  ]
}
```

- [ ] **Step 6:** `mkdir -p /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/binaries && touch /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/binaries/.gitkeep` and `mkdir -p /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/icons` (the `.icns` is generated in Task 11).

- [ ] **Step 7 (acceptance):** `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri && cargo tauri --version` succeeds and `cat tauri.conf.json | python3 -c "import json,sys; json.load(sys.stdin); print('conf-valid')"` prints `conf-valid`. (A full `cargo build` waits for `src/lib.rs` in Task 8.)

- [ ] **Step 8:** Add `src-tauri/target/` and `src-tauri/gen/` to gitignore, then commit.
```
grep -qx 'src-tauri/target/' /Users/dylanschempp/PycharmProjects/ScuffedOS/.gitignore || printf 'src-tauri/target/\nsrc-tauri/gen/\n' >> /Users/dylanschempp/PycharmProjects/ScuffedOS/.gitignore
git add src-tauri/tauri.conf.json src-tauri/Cargo.toml src-tauri/build.rs src-tauri/capabilities/default.json src-tauri/binaries/.gitkeep .gitignore
git commit -m "chore(ship): Tauri v2 scaffold (conf, Cargo, capabilities, dirs)

Hidden main window, externalBin sidecar, resources for py/pgsql/backend/dist,
and a shell:allow-spawn capability with an exact --port <digits> validator.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `src-tauri/src/lib.rs` + `main.rs` — free-port, spawn, health-gate, show, teardown, tree-kill, port command

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/src/lib.rs`.
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/src/main.rs`.

**Interfaces:**
- Produces: `run()` (the app entrypoint) doing: bind `127.0.0.1:0` → free port; `app.shell().sidecar("scuffedos-backend").args(["--port", port]).spawn()`; store `Arc<Mutex<Option<CommandChild>>>` via `app.manage`; async-drain `CommandEvent`; poll `http://127.0.0.1:<port>/health` every 200ms until 200 (bounded, ~150 tries ≈ 30s) then `get_webview_window("main").show()`; `#[tauri::command] fn api_port() -> u16`; teardown on `RunEvent::ExitRequested` (child `.kill()` + sysinfo tree-kill, SIGTERM→KILL) and `WindowEvent::CloseRequested → app.exit(0)`.
- Consumes: the launcher stub (Task 9) as sidecar `scuffedos-backend`; the backend `/health` (Task 3).

- [ ] **Step 1:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/src/main.rs`:

```rust
// Prevents an extra console window on Windows (no-op on macOS); standard Tauri stub.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    scuffedos_lib::run()
}
```

- [ ] **Step 2:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/src/lib.rs`:

```rust
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, State, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Shared handle to the spawned backend child + the chosen port.
struct Backend {
    child: Arc<Mutex<Option<CommandChild>>>,
    port: u16,
}

/// Pick a free loopback port by binding to :0 and immediately dropping the listener.
fn free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind 127.0.0.1:0");
    let port = listener.local_addr().expect("local_addr").port();
    drop(listener);
    port
}

/// Kill the sidecar's whole process tree (backstop for the Python-owned pg_ctl
/// stop). SIGTERM first, escalate to KILL after a grace period.
fn kill_process_tree(root_pid: u32) {
    use sysinfo::{Pid, ProcessesToUpdate, Signal, System};
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All, true);

    // Collect root + all transitive descendants.
    let mut targets = vec![Pid::from_u32(root_pid)];
    let mut i = 0;
    while i < targets.len() {
        let parent = targets[i];
        for (pid, proc_) in sys.processes() {
            if proc_.parent() == Some(parent) && !targets.contains(pid) {
                targets.push(*pid);
            }
        }
        i += 1;
    }
    // SIGTERM, then a short wait, then SIGKILL survivors.
    for pid in &targets {
        if let Some(p) = sys.process(*pid) {
            let _ = p.kill_with(Signal::Term);
        }
    }
    std::thread::sleep(Duration::from_millis(1500));
    sys.refresh_processes(ProcessesToUpdate::All, true);
    for pid in &targets {
        if let Some(p) = sys.process(*pid) {
            let _ = p.kill_with(Signal::Kill);
        }
    }
}

#[tauri::command]
fn api_port(state: State<Backend>) -> u16 {
    state.port
}

/// Poll GET /health until 200 (bounded). Returns true on success.
fn wait_for_health(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/health");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(500))
        .build()
        .expect("reqwest client");
    for _ in 0..150 {
        // ~150 * 200ms = 30s ceiling (first run does initdb + alembic).
        if let Ok(resp) = client.get(&url).send() {
            if resp.status().is_success() {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![api_port])
        .setup(|app| {
            let port = free_port();

            // Spawn the sidecar with the managed-PG env so the Python side owns
            // Postgres and injects the socket DSN itself.
            let resource_dir = app.path().resource_dir()?;
            let pgsql_res = resource_dir.join("pgsql");
            let (mut rx, child) = app
                .shell()
                .sidecar("scuffedos-backend")?
                .env("SCUFFEDOS_MANAGED_PG", "1")
                .env("RESOURCES_PGSQL_DIR", pgsql_res.to_string_lossy().to_string())
                .args(["--port", &port.to_string()])
                .spawn()?;

            let child = Arc::new(Mutex::new(Some(child)));
            app.manage(Backend { child: child.clone(), port });

            // Drain the sidecar's stdout/stderr to the console (app log).
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Stderr(bytes) => {
                            eprintln!("[backend:err] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] terminated: {:?}", payload);
                        }
                        _ => {}
                    }
                }
                let _ = &app_handle;
            });

            // Health-gate on a worker thread, then show (or surface an error).
            let show_handle = app.handle().clone();
            std::thread::spawn(move || {
                if wait_for_health(port) {
                    if let Some(win) = show_handle.get_webview_window("main") {
                        let _ = win.show();
                        let _ = show_handle.emit("api-port", port);
                    }
                } else {
                    eprintln!("[shell] health-gate timed out on :{port}; backend did not become ready");
                    // Minimal diagnostic: still show the window so the user isn't
                    // stuck on a blank hidden app; frontend shows its own error UI.
                    if let Some(win) = show_handle.get_webview_window("main") {
                        let _ = win.show();
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // On macOS, closing the window does not quit the app by default.
            if let WindowEvent::CloseRequested { .. } = event {
                window.app_handle().exit(0);
            }
        })
        .build(tauri::generate_context!())
        .expect("error building ScuffedOS")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                let state: State<Backend> = app_handle.state();
                let maybe_child = state.child.lock().unwrap().take();
                if let Some(child) = maybe_child {
                    let pid = child.pid();
                    let _ = child.kill(); // polite: lets the Python atexit run pg_ctl stop
                    kill_process_tree(pid); // backstop: reap any orphaned postgres
                }
            }
        });
}
```

- [ ] **Step 3 (acceptance):** `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri && cargo check 2>&1 | tail -20`. EXPECTED: `Finished` with no errors. (Warnings about unused `app_handle` capture are acceptable.) If `child.pid()` type mismatches (Tauri returns `u32`), keep the signature as written; adjust only if the compiler flags an exact type error.

> **Verification boundary (read this):** `cargo check` only proves the Rust *compiles* — it does NOT exercise the sidecar spawn, the `/health` gate, the port hand-off, or teardown, all of which need a real bundle. The load-bearing verification of this task's logic lives entirely in **Task 12 (Spike A — teardown)** and **Task 13 (Spike B — offline boot)**. Do not treat a green `cargo check` as evidence the runtime behavior is correct.
>
> **Scope note:** on a health-gate timeout this task shows the window with an `eprintln` diagnostic so the app never hangs on a blank hidden window. The full **diagnostic error window** that surfaces `backend.log`/`pg.log` is **Slice 2** (spec §10) — out of scope here.

- [ ] **Step 4:** Commit.
```
git add src-tauri/src/lib.rs src-tauri/src/main.rs
git commit -m "feat(ship): Rust shell — free-port, spawn, health-gate, teardown

setup() picks a free loopback port, spawns the sidecar with SCUFFEDOS_MANAGED_PG,
drains its output, health-gates GET /health before showing the window, exposes
the port via #[tauri::command] api_port, and on exit kills the child + sysinfo
process tree as a backstop to the Python-owned pg_ctl stop.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Backend launcher stub — resolve bundled interpreter + exec uvicorn

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/launcher/launcher.rs` (source of the single-file `externalBin`).
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/launcher/Cargo.toml`.

**Interfaces:**
- Produces the `scuffedos-backend` externalBin: a single self-contained executable that resolves `Contents/Resources/py/bin/python3` relative to its own location and `exec`s `python3 -m uvicorn app.main:app --host 127.0.0.1 --port <p>` with `cwd = Contents/Resources/backend`, passing through `--port` and the env (`SCUFFEDOS_MANAGED_PG`, `RESOURCES_PGSQL_DIR`) set by the Rust shell. The build script (Task 11) compiles this to `src-tauri/binaries/scuffedos-backend-aarch64-apple-darwin`.
- Consumes: its own executable path (`std::env::current_exe`), the bundle layout.

- [ ] **Step 1:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/launcher/Cargo.toml`:

```toml
[package]
name = "scuffedos-backend"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "scuffedos-backend"
path = "launcher.rs"

[profile.release]
opt-level = "s"
strip = true
```

- [ ] **Step 2:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/launcher/launcher.rs`. The stub lives at `Contents/MacOS/scuffedos-backend`; the interpreter is at `Contents/Resources/py/bin/python3` and backend source at `Contents/Resources/backend`:

```rust
// scuffedos-backend: the Tauri externalBin. A single-file stub whose only job
// is to exec the vendored CPython running uvicorn, with cwd at the bundled
// backend source. It rides next to a multi-file Python tree that cannot itself
// be the sidecar.
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    // current_exe() = .../Contents/MacOS/scuffedos-backend
    let exe = std::env::current_exe().expect("current_exe");
    // .../Contents/MacOS -> .../Contents
    let contents = exe
        .parent()
        .and_then(|p| p.parent())
        .expect("Contents dir")
        .to_path_buf();
    let resources: PathBuf = contents.join("Resources");
    let python = resources.join("py").join("bin").join("python3");
    let backend = resources.join("backend");

    // Pass our args straight through (Rust sends: --port <digits>).
    let args: Vec<String> = std::env::args().skip(1).collect();

    let err = Command::new(python)
        .current_dir(&backend)
        .arg("-m")
        .arg("uvicorn")
        .arg("app.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .args(&args) // forwards --port <p>
        // SCUFFEDOS_MANAGED_PG / RESOURCES_PGSQL_DIR are inherited from the
        // parent (the Rust shell set them on spawn); no need to re-set here.
        .exec(); // replaces this process on success; only returns on error

    eprintln!("scuffedos-backend: failed to exec python: {err}");
    std::process::exit(1);
}
```

- [ ] **Step 3 (acceptance):** Compile it standalone: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/src-tauri/launcher && cargo build --release 2>&1 | tail -5`. EXPECTED: `Finished`. Confirm the binary exists: `test -x target/release/scuffedos-backend && echo stub-built`.

- [ ] **Step 4 (acceptance, wiring smoke):** From the repo root with the vendored trees present (Tasks 5–6), simulate the bundle layout is not required here — just confirm the stub's path math: `./target/release/scuffedos-backend --port 0 2>&1 | head -3` should print a `failed to exec python` line (because the `Contents/Resources/py` layout doesn't exist next to the dev build path) — proving it computed a path and attempted exec. Real end-to-end exec is validated in Task 12/13 inside the actual `.app`.

- [ ] **Step 5:** Commit.
```
git add src-tauri/launcher/Cargo.toml src-tauri/launcher/launcher.rs
git commit -m "feat(ship): backend launcher stub (externalBin)

Single-file scuffedos-backend that resolves the bundled CPython under
Contents/Resources/py and execs uvicorn with cwd at Resources/backend,
forwarding --port and inheriting the managed-PG env from the Rust shell.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Frontend API-base switch — Tauri port with Vite-proxy dev fallback

**Files:**
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/lib/api.js` (the single `BASE` definition at line 6; leave every consumer at lines 39–53, 59, 123 untouched — they all read `BASE`).
- Modify `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/src/main.jsx` (add a pre-render port bootstrap).
- Do **not** touch `/Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/vite.config.js` (the `/api` proxy must stay for `npm run dev`).

**Interfaces:**
- Produces: `BASE` initializes (in precedence order) from an explicit `VITE_API_URL` build override, else a `window.__TAURI_API_BASE__` global (a defensive initializer read once at module load — no task populates it; kept as a fallback), else `''` (dev → relative `/api` → Vite proxy). The **actual** packaged-app path is the exported `setApiBase(base)` setter: `main.jsx` calls it with `http://127.0.0.1:<port>` fetched via the `api_port` Tauri command before first render.
- Consumes: `window.__TAURI__` / the `api_port` command from Task 8; existing `import.meta.env.VITE_API_URL`.

- [ ] **Step 1:** Read `frontend/src/lib/api.js` lines 1–10 to confirm the `const BASE` line, then replace it. Change line 6 from `const BASE = import.meta.env.VITE_API_URL || ''` to a mutable base with a setter:

```javascript
/* Base URL for backend calls. Precedence:
   1. VITE_API_URL — explicit build/deploy override.
   2. window.__TAURI_API_BASE__ — set by main.jsx from the Tauri api_port
      command before first render, in the packaged .app.
   3. '' — dev: relative '/api' paths hit the Vite proxy (vite.config.js). */
let BASE =
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' && window.__TAURI_API_BASE__) ||
  ''

/* Allow the Tauri bootstrap (main.jsx) to inject the resolved 127.0.0.1:<port>
   base before the first fetch. No trailing slash — paths already begin '/api'. */
export function setApiBase(base) {
  BASE = base ? base.replace(/\/$/, '') : ''
}
```

- [ ] **Step 2:** Read `frontend/src/main.jsx` (it currently does a synchronous `createRoot(...).render(<App/>)`). Gate rendering on the Tauri port when running inside Tauri, falling straight through in dev. Replace the render call with:

```javascript
import { setApiBase } from './lib/api.js'

async function resolveApiBase() {
  // Only inside the Tauri webview: ask Rust for the backend port.
  if (typeof window !== 'undefined' && '__TAURI__' in window) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const port = await invoke('api_port')
      setApiBase(`http://127.0.0.1:${port}`)
    } catch (err) {
      console.error('Failed to resolve Tauri api port; falling back to relative /api', err)
    }
  }
  // In dev (no __TAURI__) BASE stays '' and the Vite proxy handles /api.
}

resolveApiBase().finally(() => {
  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
```

The existing `frontend/src/main.jsx` wraps `<App />` in `<React.StrictMode>` — keep that wrapper exactly (shown above). The ONLY changes are: add the `setApiBase` import + `resolveApiBase` function, and move the existing `createRoot(...).render(<React.StrictMode><App/></React.StrictMode>)` call inside `resolveApiBase().finally(...)`. Do not drop `StrictMode` or any existing import.

- [ ] **Step 3:** Add the Tauri API package as a frontend dependency so `import('@tauri-apps/api/core')` resolves in the built bundle: `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm install @tauri-apps/api@^2`.

- [ ] **Step 4 (acceptance — dev unchanged):** `cd /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend && npm run build 2>&1 | tail -5`. EXPECTED: build succeeds (`✓ built`). Then start dev and confirm relative calls still proxy: `npm run dev` in the background, and `curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/api/health` prints `200` (proxied to :8000 — the backend must be running for this; if not, at minimum confirm the dev server serves index.html at `http://localhost:5173` with `200`). Stop the dev server afterward.

- [ ] **Step 5 (acceptance — Tauri path):** The real packaged-app wiring — `main.jsx`'s `resolveApiBase()` calling `setApiBase(\`http://127.0.0.1:${port}\`)` with the port from `invoke('api_port')` — only runs inside the built bundle and is validated end-to-end in **Task 13 (Spike B, offline boot)**. Unit-level checks here: (a) `npm run build` emits no unresolved-reference errors for `setApiBase` or `@tauri-apps/api/core`; (b) by inspection, `api.js` initializes `BASE` from `import.meta.env.VITE_API_URL || window.__TAURI_API_BASE__ || ''` and exports `setApiBase`, and `resolveApiBase()` calls `setApiBase(...)` only under `'__TAURI__' in window`, leaving `BASE=''` (Vite proxy) in dev. Note: `window.__TAURI_API_BASE__` is a defensive module-load initializer that no task populates — the port reaches the app solely through `invoke('api_port')` → `setApiBase`, which is the path that matters.

- [ ] **Step 6:** Commit.
```
git add frontend/src/lib/api.js frontend/src/main.jsx frontend/package.json frontend/package-lock.json
git commit -m "feat(ship): frontend API base reads Tauri port, dev proxy fallback

BASE precedence: VITE_API_URL > Tauri-injected 127.0.0.1:<port> > '' (dev
Vite proxy). main.jsx resolves the port via the api_port command before first
render inside the .app; npm run dev is unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: `scripts/build-app.sh` — orchestrate vendoring + icon + npm build + tauri build

**Files:**
- Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/build-app.sh`.

**Interfaces:**
- Produces: `ScuffedOS.app` at `src-tauri/target/release/bundle/macos/ScuffedOS.app`. Orchestrates Task 5 + Task 6 (vendoring), compiles the launcher stub into `src-tauri/binaries/scuffedos-backend-aarch64-apple-darwin`, renders the icon `.icns`, `npm ci && npm run build`, then `cargo tauri build`.
- Consumes: `scripts/vendor-postgres.sh`, `scripts/vendor-python.sh`, `frontend/public/assets/logo-mark.svg`, `iconutil`, `sips` (or `rsvg-convert`), `cargo tauri`.

- [ ] **Step 1:** Confirm the logo asset exists: `test -f /Users/dylanschempp/PycharmProjects/ScuffedOS/frontend/public/assets/logo-mark.svg && echo logo-present`. If absent, note it and use any existing PNG under `frontend/public/assets/` as the icon source in step 2's script (adjust the `SRC_SVG` path).

- [ ] **Step 2:** Create `/Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/build-app.sh`:

```bash
#!/usr/bin/env bash
# Build the unsigned ScuffedOS.app on an Apple-Silicon Mac. Orchestrates:
# vendor Postgres+pgvector, vendor Python, build the launcher stub, render the
# icon, build the frontend, and cargo tauri build. Unsigned; first launch
# requires a one-time right-click > Open (quarantine).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
TRIPLE="aarch64-apple-darwin"

echo "==> [1/6] Vendor Postgres + pgvector"
bash "$ROOT/scripts/vendor-postgres.sh"

echo "==> [2/6] Vendor Python env"
bash "$ROOT/scripts/vendor-python.sh"

echo "==> [3/6] Build the launcher stub (target-triple-suffixed externalBin)"
( cd "$ROOT/src-tauri/launcher" && cargo build --release )
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/src-tauri/launcher/target/release/scuffedos-backend" \
   "$ROOT/src-tauri/binaries/scuffedos-backend-${TRIPLE}"
codesign --force -s - "$ROOT/src-tauri/binaries/scuffedos-backend-${TRIPLE}"

echo "==> [4/6] Render icon (logo-mark.svg -> 1024 PNG -> .icns)"
SRC_SVG="$ROOT/frontend/public/assets/logo-mark.svg"
ICONSET="$BUILD/ScuffedOS.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET" "$ROOT/src-tauri/icons"
# Rasterize to 1024 (prefer rsvg-convert; fall back to sips on an existing PNG).
if command -v rsvg-convert >/dev/null 2>&1 && [ -f "$SRC_SVG" ]; then
  rsvg-convert -w 1024 -h 1024 "$SRC_SVG" -o "$BUILD/icon-1024.png"
elif command -v qlmanage >/dev/null 2>&1 && [ -f "$SRC_SVG" ]; then
  qlmanage -t -s 1024 -o "$BUILD" "$SRC_SVG" >/dev/null
  mv "$BUILD/$(basename "$SRC_SVG").png" "$BUILD/icon-1024.png"
else
  echo "WARN: no SVG rasterizer; expecting a prebuilt $BUILD/icon-1024.png"
fi
for s in 16 32 64 128 256 512 1024; do
  sips -z "$s" "$s" "$BUILD/icon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  h=$((s*2))
  sips -z "$h" "$h" "$BUILD/icon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ROOT/src-tauri/icons/icon.icns"

echo "==> [5/6] Build frontend"
( cd "$ROOT/frontend" && npm ci && npm run build )

echo "==> [6/6] cargo tauri build (unsigned)"
( cd "$ROOT/src-tauri" && cargo tauri build )

APP="$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app"
echo "==> Done. App at: $APP"
du -sh "$APP" || true
```

- [ ] **Step 3:** `chmod +x /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/build-app.sh`.

- [ ] **Step 4 (acceptance):** Run `bash /Users/dylanschempp/PycharmProjects/ScuffedOS/scripts/build-app.sh`. EXPECTED: it completes all 6 stages and prints `==> Done. App at: .../ScuffedOS.app` with a size in the ~250–350 MB range. Verify the bundle exists and has the sidecar with the target-triple stripped inside the bundle: `test -d "$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app" && ls "$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app/Contents/MacOS/"` shows `ScuffedOS` and `scuffedos-backend`.

- [ ] **Step 5 (acceptance — first double-click smoke):** `xattr -dr com.apple.quarantine "$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app"` then `open "$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app"`. **The acceptance gate is: within ~5–15s the window appears showing the dashboard (Home) rendering live data.** That is dispositive on its own — the Rust health-gate only reveals the window *after* `GET /health` returned 200, so a visible live dashboard proves the backend + managed Postgres came up. (Slice-1 does not persist the chosen port to `config.json`, so do not try to read a port from disk.) Optional secondary probe from the sidecar log: `PORT=$(grep -oE '127\.0\.0\.1:[0-9]+' ~/Library/Application\ Support/ScuffedOS/logs/backend.log 2>/dev/null | tail -1 | cut -d: -f2); [ -n "$PORT" ] && curl -s "http://127.0.0.1:$PORT/health"` prints `{"ok":true}`. Quit the app.

- [ ] **Step 6:** Commit.
```
git add scripts/build-app.sh
git commit -m "chore(ship): build-app.sh — vendor + icon + frontend + tauri build

Orchestrates PG/Python vendoring, compiles the target-triple-suffixed launcher
stub, renders logo-mark.svg -> .icns, builds the frontend, and cargo tauri
build -> unsigned ScuffedOS.app.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Spike A — orphan teardown

**Files:** none created; this is a run-based verification spike. Record the results in the commit message / a scratch note, not a tracked report file.

**Interfaces:** validates the load-bearing guarantee that no `postgres` process is orphaned across normal quit, window-close, app SIGKILL, and back-to-back relaunch — the biggest risk (spec §11).

**Procedure (each step is a discrete pass/fail):**

- [ ] **Step 1:** Establish a clean baseline. `pgrep -fl postgres | grep -i scuffedos || echo "no-scuffedos-postgres"` prints `no-scuffedos-postgres`. Remove any prior state for a true first-run test if desired: `rm -rf ~/Library/Application\ Support/ScuffedOS` (optional; a persistent-data test in Step 6 needs it kept).

- [ ] **Step 2 (normal quit):** `open .../ScuffedOS.app`, wait for the window, confirm a running managed postgres: `pgrep -fl "postgres.*ScuffedOS/pgdata"` returns a PID. Quit via the app menu (Cmd-Q). After ~3s: `pgrep -fl "postgres.*ScuffedOS/pgdata" || echo "clean-after-quit"` must print `clean-after-quit`. PASS iff no postgres remains.

- [ ] **Step 3 (window-close):** Relaunch, wait for the window, close the window with the red button (not Cmd-Q). After ~3s confirm both the app and postgres are gone: `pgrep -fl ScuffedOS || echo "app-gone"` and `pgrep -fl "postgres.*ScuffedOS/pgdata" || echo "pg-gone"` print `app-gone` / `pg-gone`. PASS iff both gone (validates the `CloseRequested → exit(0)` wiring + teardown).

- [ ] **Step 4 (hard SIGKILL of the app):** Relaunch, wait for the window. `SHELLPID=$(pgrep -f 'ScuffedOS.app/Contents/MacOS/ScuffedOS' | head -1); kill -9 "$SHELLPID"`. This skips the Rust `RunEvent` teardown, so the Python-side `atexit`/SIGTERM handler is the load-bearing reaper. After ~3s: `pgrep -fl "postgres.*ScuffedOS/pgdata" || echo "pg-reaped"`. If postgres survives (expected on a hard `kill -9` of the whole tree, since Python also dies), the recovery is the stale-pid check on next launch — proceed to Step 5 to prove clean relaunch. Record whether an orphan remained.

- [ ] **Step 5 (stale-pid recovery / back-to-back relaunch):** Immediately relaunch the app. EXPECTED: it starts cleanly within the health-gate window despite any leftover `postmaster.pid` (localdb `is_stale_pidfile` clears a dead-PID file before `pg_ctl start`). Confirm the window shows and `pgrep -fl "postgres.*ScuffedOS/pgdata"` returns exactly one fresh PID. PASS iff the relaunch is clean with no "another server might be running" error in `~/Library/Application Support/ScuffedOS/logs/pg.log`.

- [ ] **Step 6 (data persistence across restart):** With the app running, create a piece of data through the UI (e.g. add a Task). Quit, relaunch, confirm the Task is still present. PASS iff data survives (validates pgdata persistence under App Support).

- [ ] **Step 7:** If any step leaves an orphan that the next launch does NOT recover from, that is a Spike-A failure — debug `localdb.start`/`is_stale_pidfile` and the Rust `kill_process_tree` before declaring the slice done. Record the final result: all of quit/close/SIGKILL-then-relaunch leave a clean, working next launch.

- [ ] **Step 8:** Commit the spike record.
```
git commit --allow-empty -m "test(ship): Spike A — orphan teardown verified

Normal quit and window-close leave zero orphaned postgres; hard SIGKILL is
recovered by the stale-postmaster.pid check on the next launch; back-to-back
relaunch is clean and data persists across restart.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: Spike B — clean-machine offline relocation

**Files:** none created; run-based verification spike.

**Interfaces:** de-risks the PG + Python vendoring simultaneously — proves the bundle is relocatable and boots with **zero network**, on a fresh App-Support dir (ideally a second Mac / fresh user account, per spec §8.6).

**Procedure:**

- [ ] **Step 1 (relocation audit — Postgres):** On the built `.app`, run `otool -L "$APP/Contents/Resources/pgsql/bin/postgres"` and `otool -L "$APP/Contents/Resources/pgsql/lib/vector.dylib"` (or the pkglibdir path). EXPECTED: no `/opt/homebrew`, no `/usr/local/Cellar`, no `/private/var/folders` build paths — only `@loader_path`/`@rpath`/`/usr/lib`/`/System`. PASS iff clean.

- [ ] **Step 2 (relocation audit — Python):** `find "$APP/Contents/Resources/py" \( -name '*.dylib' -o -name '*.so' \) -exec otool -L {} \; | grep -E '/opt/homebrew|/usr/local/Cellar|/private/var/folders' || echo "py-relocatable"`. EXPECTED: prints `py-relocatable`. Also confirm libpython's install-name: `otool -D "$APP/Contents/Resources/py/lib/libpython3.14.dylib"` shows `@executable_path/../lib/libpython3.14.dylib`.

- [ ] **Step 3 (fresh state):** `rm -rf ~/Library/Application\ Support/ScuffedOS` so first-run copy + initdb + `CREATE EXTENSION vector` all execute from scratch.

- [ ] **Step 4 (offline boot):** Disable networking (Wi-Fi off / `networksetup -setairportpower en0 off`, and unplug ethernet). Then `xattr -dr com.apple.quarantine "$APP"; open "$APP"`. EXPECTED: the window appears within the health-gate timeout — the first run does `initdb`, `pg_ctl start`, `alembic upgrade head` (including `CREATE EXTENSION IF NOT EXISTS vector`), and uvicorn serves — **with no network**. PASS iff the dashboard loads offline.

- [ ] **Step 5 (pgvector / Mem0 query offline):** With networking still off, exercise a code path that touches pgvector: open the Second Brain / memory surface and confirm it loads without error, or run against the socket directly — `"$APP/Contents/Resources/pgsql/bin/psql" -h ~/Library/Application\ Support/ScuffedOS/run -U scuffedos -d scuffedos -c "SELECT extname FROM pg_extension WHERE extname='vector';"` prints `vector`. PASS iff the extension is present and a memory query returns without a network call.

- [ ] **Step 6 (no-network assertion):** While the app runs offline, confirm nothing is trying to reach the internet for core boot: tail `~/Library/Application Support/ScuffedOS/logs/backend.log` for connection-refused/DNS errors that would indicate a runtime download. Core boot (PG + alembic + serve) must complete with zero external calls. (Integration syncs like Gmail/Whoop will fail offline — that's expected and not part of this spike; the spike is about the app *launching and serving* offline.)

- [ ] **Step 7:** Re-enable networking. Record the result: bundle is fully relocatable and boots+serves offline on a fresh App-Support dir. If Step 1/2 flag any absolute path, fix the corresponding vendor script (Task 5/6) and rebuild before declaring the slice done.

- [ ] **Step 8:** Commit the spike record and mark the slice DoD.
```
git commit --allow-empty -m "test(ship): Spike B — clean-machine offline relocation verified

otool audits show no /opt/homebrew or absolute build paths in postgres,
vector.dylib, or the Python tree; a fresh App-Support dir boots fully offline
(initdb + alembic upgrade + CREATE EXTENSION vector + uvicorn) and a pgvector
query succeeds with networking disabled.

Slice-1 DoD met: built .app double-clicks to a working dashboard, all live
screens + assistant function, data persists across restarts, no orphaned
processes; backend suite green.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
