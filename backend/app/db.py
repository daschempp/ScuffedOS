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
