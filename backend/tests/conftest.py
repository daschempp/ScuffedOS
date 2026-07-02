"""Test plumbing: every test gets a fresh database.

Default is in-memory SQLite (fast, zero infra). Set TEST_DATABASE_URL to run
the identical suite against real Postgres — CI does this with a pgvector
service container, matching production.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import email_draft, email_sync, email_triage, fitness_sync, food_db, llm, memory_engine, providers, reminders
from app.config import settings
from app.db import Base, make_engine, make_session_factory
from app.main import app
from app.store import store

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or "sqlite+pysqlite:///:memory:"


@pytest.fixture(autouse=True)
def fresh_db():
    """Bind the store singleton to a clean schema for each test."""
    engine = make_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    store.configure(make_session_factory(engine))
    yield
    store.configure(None)
    engine.dispose()


@pytest.fixture(autouse=True)
def no_external_services():
    """Tests never reach the Claude API, OpenAI, Mem0, USDA, osascript, or
    WHOOP — install a fake explicitly (each module's configure seam) when needed."""
    llm.configure(None)
    memory_engine.configure(None)
    food_db.configure(None)
    reminders.configure(None)
    providers.configure([])
    fitness_sync.configure(None)
    email_triage.configure(None)
    email_sync.configure(None)
    email_draft.configure(None)
    yield
    llm.configure()
    memory_engine.configure("unset")
    food_db.configure("unset")
    reminders.configure("unset")
    providers.configure("unset")
    fitness_sync.configure("unset")
    email_triage.configure("unset")
    email_sync.configure("unset")
    email_draft.configure("unset")


@pytest.fixture(autouse=True)
def attachments_tmpdir(tmp_path):
    """Uploads land in a per-test scratch directory, never ./data."""
    original = settings.attachments_dir
    settings.attachments_dir = str(tmp_path / "attachments")
    yield
    settings.attachments_dir = original


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def seeded():
    """Demo data, for tests that want the prototype's sample rows."""
    assert store.seed_demo() is True
