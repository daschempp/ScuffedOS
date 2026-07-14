import pytest

from app.db import make_engine, normalize_database_url


def test_loopback_and_sqlite_need_no_tls():
    for dsn in ("postgresql://u:p@127.0.0.1:5432/app",
                "postgresql://u:p@localhost/app",
                "sqlite://"):
        eng = make_engine(dsn)
        eng.dispose()


def test_remote_dsn_with_tls_is_accepted():
    eng = make_engine("postgresql://u:secret@db.example.com:5432/app?sslmode=require")
    try:
        assert eng.dialect.name == "postgresql"
    finally:
        eng.dispose()


def test_remote_dsn_without_tls_is_rejected():
    with pytest.raises(RuntimeError) as exc:
        make_engine("postgresql://u:secret@db.example.com:5432/app")
    # names the problem but never leaks the password
    assert "secret" not in str(exc.value)
    assert "TLS" in str(exc.value) or "sslmode" in str(exc.value)


def test_normalize_keeps_remote_host_and_scheme():
    assert normalize_database_url(
        "postgres://u:p@10.0.0.9:5432/app?sslmode=require"
    ).startswith("postgresql+psycopg://")


def test_query_host_bypass_is_rejected():
    # psycopg honors a `host` QUERY PARAM when the authority host is empty.
    # A remote hostname smuggled in via ?host= must be treated as the real
    # host and rejected when TLS isn't required.
    with pytest.raises(RuntimeError) as exc:
        make_engine("postgresql://user:pw@/dbname?host=evil.example.com&sslmode=disable")
    assert "pw" not in str(exc.value)


def test_query_host_remote_with_tls_is_accepted():
    eng = make_engine(
        "postgresql://user:pw@/dbname?host=evil.example.com&sslmode=require"
    )
    try:
        assert eng.dialect.name == "postgresql"
    finally:
        eng.dispose()


def test_query_host_unix_socket_is_loopback():
    # Mirrors app.localdb.socket_dsn's own DSN shape for the packaged app's
    # managed local Postgres: no authority host, a `host=` query param
    # pointing at a Unix-socket directory. Must NOT regress this.
    eng = make_engine(
        "postgresql+psycopg://user@/dbname?host=/var/run/postgresql"
    )
    try:
        assert eng.dialect.name == "postgresql"
    finally:
        eng.dispose()


def test_repeated_query_keys_do_not_crash_the_guard():
    # SQLAlchemy's URL.query returns a tuple when a key repeats. The guard
    # must normalize before .startswith/.lower, not raise AttributeError.
    with pytest.raises(RuntimeError) as exc:
        make_engine(
            "postgresql://user:pw@/dbname?host=evil.example.com&host=evil.example.com&sslmode=disable&sslmode=disable"
        )
    assert "pw" not in str(exc.value)
