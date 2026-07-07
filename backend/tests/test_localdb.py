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

    def _fake_run(argv, **k):
        seen["argv"] = argv
        return _ok()

    monkeypatch.setattr(localdb.subprocess, "run", _fake_run)
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
