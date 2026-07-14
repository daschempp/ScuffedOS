"""Database plumbing: engine construction, session factory, declarative base.

The app talks to plain Postgres (Supabase-hosted in production) through
SQLAlchemy. Tests run the same code against SQLite, so engine options branch
on dialect and models stick to portable types (JSON with a JSONB variant).
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def _last_query_value(query, key: str) -> str:
    """SQLAlchemy's URL.query maps to a str normally, but to a tuple of str
    when a key is repeated. Normalize to a single string (last occurrence)
    so callers can safely .startswith/.lower without an AttributeError."""
    value = query.get(key) or ""
    if isinstance(value, tuple):
        value = value[-1] if value else ""
    return value


def _assert_secure_dsn(url: str) -> None:
    """Reject a non-loopback PostgreSQL DSN that lacks TLS. Loopback needs no TLS;
    a remote host requires sslmode=require|verify-ca|verify-full. Remote DSNs are
    SUPPORTED — only insecure ones are refused. The error text carries a redacted
    host only, NEVER the DSN or password.

    psycopg (like libpq) also honors a `host` QUERY PARAM when the authority
    host is empty — `postgresql://user:pw@/db?host=evil.example.com` connects
    to evil.example.com despite an empty authority host. A bare `/`-prefixed
    query host is a Unix-socket path (loopback; see app.localdb.socket_dsn),
    but anything else is a real remote hostname and must go through the same
    loopback/TLS check as an authority host would.
    """
    from sqlalchemy.engine import make_url

    u = make_url(url)
    host = (u.host or "").lower()
    if not host:
        query_host = _last_query_value(u.query, "host")
        if query_host and not query_host.startswith("/"):
            host = query_host.lower()
    is_loopback = host in ("", "localhost", "127.0.0.1", "::1")
    if u.drivername.startswith("postgresql") and not is_loopback:
        sslmode = _last_query_value(u.query, "sslmode").lower()
        if sslmode not in ("require", "verify-ca", "verify-full"):
            raise RuntimeError(
                f"Refusing a non-loopback PostgreSQL DSN without TLS (host={host!r}); "
                "set sslmode=require or stronger."
            )


def normalize_database_url(url: str) -> str:
    """Accept the connection string exactly as Supabase hands it out.

    Supabase (and most providers) give `postgres://` or `postgresql://`;
    SQLAlchemy needs an explicit driver to pick psycopg 3.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    _assert_secure_dsn(url)
    if url.startswith("sqlite"):
        # In-memory databases need a single shared connection or every
        # checkout would see a fresh empty schema.
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        # SQLite ships with foreign keys OFF; turn them on so tests enforce
        # the same FK/CASCADE behavior Postgres does.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    # Supabase free tier runs behind a session pooler — keep our side small
    # and ping before use so idle-dropped connections recycle quietly.
    return create_engine(url, pool_size=5, max_overflow=2, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
