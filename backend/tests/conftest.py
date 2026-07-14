"""Test plumbing: every test gets a fresh database.

Default is in-memory SQLite (fast, zero infra). Set TEST_DATABASE_URL to run
the identical suite against real Postgres — CI does this with a pgvector
service container, matching production.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import (
    contacts_sync, email_draft, email_sync, email_triage, finance_sync,
    fitness_sync, food_db, llm, memory_engine, moodle_sync, providers, reminders,
)
from app.config import settings
from app.db import Base, make_engine, make_session_factory
from app.main import app
from app.providers import macos_contacts
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
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
    moodle_sync.configure(None)
    finance_sync.configure(None)
    # Contacts: the REAL guarantee is the default fake_snapshot below, not the
    # platform override. read_snapshot() only ever consults _FAKE_SNAPSHOT (never
    # _PLATFORM_OVERRIDE/is_supported()) before touching disk, so seeding a
    # non-None default here is what keeps every test off the real AddressBook on
    # every platform (macOS dev + Ubuntu CI) -- platform="linux" alone would NOT
    # have stopped a test that enables contacts and calls tick()/read_snapshot()
    # without also configuring its own fake_snapshot from reading the real store.
    # A test that needs a REAL read (the reader/photo fixture tests) must reset
    # this seam first via macos_contacts.configure(fake_snapshot=None). Keep the
    # background loop disarmed either way.
    macos_contacts.configure(
        platform="linux",
        fake_snapshot=ContactsSnapshot(status=SnapshotStatus.ACCESS_DENIED, people=[]),
    )
    contacts_sync.configure(None)
    _prev_contacts_sync_enabled = settings.contacts_sync_enabled
    settings.contacts_sync_enabled = False
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
    moodle_sync.configure("unset")
    finance_sync.configure("unset")
    macos_contacts.configure()          # reset to real detection
    contacts_sync.configure("unset")
    settings.contacts_sync_enabled = _prev_contacts_sync_enabled


@pytest.fixture(autouse=True)
def attachments_tmpdir(tmp_path):
    """Uploads land in a per-test scratch directory, never ./data."""
    original = settings.attachments_dir
    settings.attachments_dir = str(tmp_path / "attachments")
    yield
    settings.attachments_dir = original


@pytest.fixture(autouse=True)
def contacts_photos_tmpdir(tmp_path):
    """Contact photos + the App Support root live in per-test scratch, never the
    real ~/Library/Application Support or ./data."""
    prev_support = settings.app_support_dir
    prev_photos = settings.contacts_photos_dir
    settings.app_support_dir = str(tmp_path / "AppSupport")
    settings.contacts_photos_dir = "contact_photos"     # relative -> resolved under App Support
    yield
    settings.app_support_dir = prev_support
    settings.contacts_photos_dir = prev_photos


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def seeded():
    """Demo data, for tests that want the prototype's sample rows."""
    assert store.seed_demo() is True
