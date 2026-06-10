"""Alembic environment — resolves the database URL the same way the app does."""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base, normalize_database_url
import app.models  # noqa: F401  — register tables on Base.metadata

config = context.config
target_metadata = Base.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")  # set programmatically by tests
    if not url:
        url = os.environ.get("DATABASE_URL", "")
    if not url:
        from app.config import settings

        url = settings.database_url
    if not url:
        raise SystemExit(
            "No database URL: set DATABASE_URL (or backend/.env) before running alembic."
        )
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
