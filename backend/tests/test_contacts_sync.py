import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import contacts_sync
from app.db import Base
from app.providers import macos_contacts
from app.providers.base import NormalizedPerson
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from app.store import SyncResult, store

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    store.configure(sessionmaker(eng))
    yield
    store.configure(None)
    contacts_sync.configure("unset")


def _snap(status, people=()):
    return ContactsSnapshot(status=status, people=list(people),
                            stores_total=1, stores_read=1, store_ids=["local"])


def test_default_state_is_disabled_noop(monkeypatch):
    # Consent defaults OFF: tick must NOT touch the AddressBook at all.
    def must_not_read(*a, **k):
        raise AssertionError("read_snapshot must not run while consent is off")

    monkeypatch.setattr(macos_contacts, "read_snapshot", must_not_read)
    result = contacts_sync.tick()
    assert result.status == "disabled"


def test_complete_snapshot_delegates_to_apply(monkeypatch):
    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    snap = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [NormalizedPerson(source="macos_contacts", source_id="A", display_name="A")])
    monkeypatch.setattr(macos_contacts, "read_snapshot", lambda *a, **k: snap)
    seen = {}

    def fake_apply(snapshot, now):
        seen["snapshot"] = snapshot
        seen["now"] = now
        return SyncResult(status="ok", access="granted", imported=1,
                          updated=0, removed=0, last_sync_at=now)

    monkeypatch.setattr(store, "apply_contacts_snapshot", fake_apply)
    result = contacts_sync.tick()
    assert result.status == "ok"
    assert result.imported == 1
    assert seen["snapshot"] is snap             # the reader's snapshot, applied verbatim


def test_unreachable_database_is_error_never_empty(monkeypatch):
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    monkeypatch.setattr(macos_contacts, "read_snapshot",
                        lambda *a, **k: _snap(SnapshotStatus.COMPLETE_EMPTY))

    def db_down(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("could not connect to server"))

    monkeypatch.setattr(store, "apply_contacts_snapshot", db_down)
    result = contacts_sync.tick()
    assert result.status == "error"             # a failed remote DB is a FAILED sync
    assert result.status != "empty"             # never mistaken for an empty source


def test_state_read_failure_is_error_and_never_crashes(monkeypatch):
    def db_down():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(store, "get_contacts_state", db_down)
    result = contacts_sync.tick()               # must not raise
    assert result.status == "error"


def test_access_denied_snapshot_flows_through_apply(monkeypatch):
    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    monkeypatch.setattr(macos_contacts, "read_snapshot",
                        lambda *a, **k: _snap(SnapshotStatus.ACCESS_DENIED))

    def fake_apply(snapshot, now):
        assert snapshot.status == SnapshotStatus.ACCESS_DENIED
        return SyncResult(status="access_denied", access="denied")

    monkeypatch.setattr(store, "apply_contacts_snapshot", fake_apply)
    result = contacts_sync.tick()
    assert result.status == "access_denied"
    assert result.access == "denied"


def test_configure_override():
    class Fake:
        def tick(self, now=None):
            return SyncResult(status="ok", access="granted", imported=99)

    contacts_sync.configure(Fake())
    assert contacts_sync.tick().imported == 99


# ---- 4e: a crashing reader is classified, never propagated ------------------

def test_4e_tick_survives_a_crashing_reader(monkeypatch):
    """read_snapshot() classifies rather than raising, but a reader BUG must not
    crash the loop either: tick substitutes an IO_ERROR snapshot, which the store
    maps to status 'error' and records as 'reader failed' — writing no rows."""
    store.set_contacts_enabled(True, region="US", now=NOW)

    def boom(*a, **k):
        raise RuntimeError("reader exploded")

    monkeypatch.setattr(macos_contacts, "read_snapshot", boom)

    result = contacts_sync.tick(NOW)                    # must not raise
    assert result.status == "error"                     # _FAILED_MAP[IO_ERROR]
    assert store.list_people()["items"] == []           # no row writes
    state = store.get_contacts_state()
    assert state["last_error"] == "reader failed"
    assert state["status"] == "error"


# ---- 4g: the AddressBook root is a real setting -----------------------------

def test_4g_tick_reads_the_configured_addressbook_root(monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "addressbook_root", "/tmp/addressbook-under-test")
    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    seen = {}

    def _read(root, **kwargs):
        seen["root"] = root
        return _snap(SnapshotStatus.COMPLETE_EMPTY)

    monkeypatch.setattr(macos_contacts, "read_snapshot", _read)
    monkeypatch.setattr(store, "apply_contacts_snapshot",
                        lambda snapshot, now: SyncResult(status="empty", access="granted"))

    assert contacts_sync.tick(NOW).status == "empty"
    assert seen["root"] == "/tmp/addressbook-under-test"


# ---- 4i: the loop always runs; consent gates every tick ---------------------

class _RecordingTick:
    """Seam object for contacts_sync.configure(...): records every tick and
    (optionally) raises the first time, to prove the loop survives it."""

    def __init__(self, raise_first: bool = False):
        self.calls: list = []
        self._raise_first = raise_first

    def tick(self, now=None):
        self.calls.append(now)
        if self._raise_first and len(self.calls) == 1:
            raise RuntimeError("tick exploded")
        return SyncResult(status="ok", access="granted")


def test_4i_run_loop_sleeps_before_the_first_tick(monkeypatch):
    """The enable endpoint already kicks the first sync, so the loop must WAIT one
    interval before ticking — that keeps every TestClient lifespan and app startup
    free of AddressBook reads now that the loop is always started."""
    from app.config import settings as app_settings

    fake = _RecordingTick()
    contacts_sync.configure(fake)
    monkeypatch.setattr(app_settings, "contacts_sync_seconds", 3600)

    async def drive():
        task = asyncio.create_task(contacts_sync.run_loop())
        await asyncio.sleep(0.05)               # plenty of time to tick, if it would
        assert fake.calls == []                 # ...it must not have
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task                          # stops cleanly on cancel

    asyncio.run(drive())


def test_4i_run_loop_ticks_each_interval_and_survives_a_raising_tick(monkeypatch):
    from app.config import settings as app_settings

    fake = _RecordingTick(raise_first=True)
    contacts_sync.configure(fake)
    monkeypatch.setattr(app_settings, "contacts_sync_seconds", 0.01)

    async def drive():
        task = asyncio.create_task(contacts_sync.run_loop())
        for _ in range(200):                    # bounded wait, not a fixed sleep
            if len(fake.calls) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert len(fake.calls) >= 2                 # ticked after the first sleep, and
                                                # kept ticking after one raised


def test_4i_lifespan_always_starts_the_contacts_loop(monkeypatch):
    """There is no env kill-switch any more: the loop is always started, and every
    tick is gated by contacts_sync_state.enabled."""
    from fastapi.testclient import TestClient

    from app.config import settings as app_settings
    from app.main import app

    started = {"contacts": False}

    async def fake_run_loop():
        started["contacts"] = True
        await asyncio.sleep(3600)               # alive until lifespan cancels it

    for flag in ("reminders_enabled", "fitness_sync_enabled", "email_sync_enabled",
                 "moodle_sync_enabled", "finance_sync_enabled"):
        monkeypatch.setattr(app_settings, flag, False)              # isolate this loop
    monkeypatch.setattr(contacts_sync, "run_loop", fake_run_loop)

    with TestClient(app):
        pass

    assert started["contacts"] is True
