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
