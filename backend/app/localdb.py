"""M8 Ship/Tauri — managed local Postgres lifecycle (packaged .app only).

This module is exercised ONLY when SCUFFEDOS_MANAGED_PG is truthy (set by the
bundled app). In dev/CI/tests the flag is off and none of this runs, so the
external DATABASE_URL path is completely unaffected.

The Python process owns the Postgres lifecycle: copy the vendored tree into
App Support on first run, initdb, pg_ctl start over a Unix socket, alembic
upgrade head, serve, and pg_ctl stop -m fast on shutdown. The socket DSN
`postgresql+psycopg://<user>@/<db>?host=<run-dir>` has THREE consumers:
  1. app.db's SQLAlchemy store engine — parsed via SQLAlchemy's `make_url`,
     which percent-decodes the query string, so `host=` may be percent-encoded.
  2. alembic — also goes through SQLAlchemy's URL machinery (same as above).
  3. app.memory_engine's mem0/pgvector vector store — this one hands the DSN
     to psycopg as a RAW connection string (no SQLAlchemy involved), so it
     needs a libpq-legal string as-is.
The default App Support dir (`~/Library/Application Support/ScuffedOS/run`)
contains a space, which raw libpq/psycopg rejects unencoded. `socket_dsn()`
therefore percent-encodes the host path; SQLAlchemy's `make_url` decodes
`%20` back to a literal space for consumers 1-2, and psycopg's own DSN parser
(consumer 3) accepts the percent-encoded form directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

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
    # Percent-encode the host path: the default App Support dir contains a
    # space, which SQLAlchemy's make_url tolerates (and decodes back) but
    # raw psycopg/libpq (the mem0/memory_engine consumer) rejects unencoded.
    host = quote(str(paths.run_dir), safe="/")
    return f"postgresql+psycopg://{user}@/{dbname}?host={host}"


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
