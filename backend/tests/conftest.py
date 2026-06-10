"""Test plumbing: every test gets a fresh database.

Default is in-memory SQLite (fast, zero infra). Set TEST_DATABASE_URL to run
the identical suite against real Postgres — CI does this with a pgvector
service container, matching production.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import llm, memory_engine
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
    """Tests never reach the Claude API, Ollama, or Mem0 — install a fake
    explicitly (llm.configure / memory_engine.configure) when one is needed."""
    llm.configure(None)
    memory_engine.configure(None)
    yield
    llm.configure()
    memory_engine.configure("unset")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def seeded():
    """Demo data, for tests that want the prototype's sample rows."""
    assert store.seed_demo() is True
