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
