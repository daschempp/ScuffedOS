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


def test_socket_dsn_with_spaced_run_dir_is_valid_for_raw_psycopg_consumers(tmp_path, monkeypatch):
    """The default App Support run-dir contains a space
    (~/Library/Application Support/ScuffedOS/run). SQLAlchemy's make_url
    tolerates an unencoded space in the query string, but mem0's
    memory_engine hands the DSN to psycopg as a RAW connection string (see
    memory_engine._connection_string, which just strips the +psycopg
    dialect suffix via str.replace — no SQLAlchemy URL parsing at all). An
    unencoded space in that raw string is rejected by libpq/psycopg. This
    test mirrors that exact raw-string derivation and asserts psycopg can
    parse the result."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    spaced_root = tmp_path / "Library" / "Application Support" / "ScuffedOS"
    spaced_root.mkdir(parents=True)
    paths = localdb.resolve_paths(str(spaced_root))

    dsn = localdb.socket_dsn(paths, "scuffedos", "scuffedos")

    # Mirror memory_engine._connection_string(): strip the SQLAlchemy driver
    # suffix via plain string replace, nothing more.
    raw_conninfo = dsn.replace("postgresql+psycopg://", "postgresql://")

    # Must not blow up on an unencoded space in the host path.
    parsed = conninfo_to_dict(raw_conninfo)
    assert parsed["host"] == str(paths.run_dir)

    # And SQLAlchemy's make_url must still decode it back to the literal
    # (unencoded) host path, so the store engine + alembic keep working.
    from app.db import normalize_database_url
    from sqlalchemy.engine import make_url
    normalized = normalize_database_url(dsn)
    assert make_url(normalized).query["host"] == str(paths.run_dir)


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


def test_write_runtime_conf_single_quotes_spaced_run_dir(tmp_path):
    """The default App Support run-dir contains a space
    (~/Library/Application Support/ScuffedOS/run). Postgres conf files accept
    single-quoted string values containing spaces, so scuffedos.conf must
    single-quote unix_socket_directories rather than relying on shell/argv
    word-splitting (which is exactly what broke the old `-o "-k <path> ..."`
    approach)."""
    spaced_root = tmp_path / "Library" / "Application Support" / "ScuffedOS"
    paths = localdb.resolve_paths(str(spaced_root))
    localdb.ensure_dirs(paths)

    conf_path = localdb.write_runtime_conf(paths)

    assert conf_path == paths.pgdata_dir / "scuffedos.conf"
    lines = conf_path.read_text().splitlines()
    assert f"unix_socket_directories = '{paths.run_dir}'" in lines
    assert "listen_addresses = '127.0.0.1'" in lines
    assert "jit = off" in lines


def test_start_pg_ctl_argv_has_no_o_flag_with_raw_spaced_path(tmp_path, monkeypatch):
    """Regression guard for the MF6 ship-blocker: pg_ctl's argv must never
    carry a `-o` string embedding paths.run_dir unquoted, since Postgres
    splits the `-o` string on whitespace and truncates a spaced path at the
    first space (e.g. `.../Application Support/ScuffedOS/run` -> the
    `-k`-value silently becomes `.../Application`). The settings now live in
    scuffedos.conf (a conf file, where single-quoted values may contain
    spaces) instead of the space-splitting `-o` argument."""
    spaced_root = tmp_path / "Library" / "Application Support" / "ScuffedOS"
    paths = localdb.resolve_paths(str(spaced_root))
    localdb.ensure_dirs(paths)
    calls = []
    monkeypatch.setattr(localdb.subprocess, "run",
                        lambda *a, **k: calls.append(a[0]) or _ok())

    localdb.start(paths)

    assert len(calls) == 1
    argv = [str(a) for a in calls[0]]
    assert "-o" not in argv
    assert not any(str(paths.run_dir) in a for a in argv)
    assert "pg_ctl" in argv[0]
    assert "-w" in argv and "start" in argv

    # And the settings must actually be reachable via scuffedos.conf, wired
    # in through postgresql.conf's include_if_exists.
    conf_text = (paths.pgdata_dir / "scuffedos.conf").read_text()
    assert f"unix_socket_directories = '{paths.run_dir}'" in conf_text
    main_conf_text = (paths.pgdata_dir / "postgresql.conf").read_text()
    assert "include_if_exists 'scuffedos.conf'" in main_conf_text


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
