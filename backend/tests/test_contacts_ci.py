"""CI hardening for the People/CRM + Contacts slice (M10 s1).

Every test in the suite runs with real Contacts probing forced OFF (so the same
suite is deterministic on a macOS dev box and on the Ubuntu CI runner) via the
autouse seam in conftest.py. These tests exercise the deployment-aware paths the
contract calls out: a remote PostgreSQL outage is a FAILED sync (never 'empty'),
apply is atomic, partial reads never reconcile, a per-record failure degrades to
'partial' without soft-deleting absent rows, and overlapping applies serialize
under the process + advisory lock. All run against whatever TEST_DATABASE_URL is
configured (Postgres on CI, SQLite locally), so the threaded test doubles as the
pg_advisory_xact_lock contention test on the Postgres leg.

Note: a remote-DSN-accepted test is intentionally NOT duplicated here — Task 6
already covers it in test_db_dsn.py (test_remote_dsn_with_tls_is_accepted +
test_normalize_keeps_remote_host_and_scheme).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app import contacts_sync
from app.providers import macos_contacts
from app.providers.base import NormalizedPerson
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from app.store import store

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _person(source_id: str, name: str, phone: str) -> NormalizedPerson:
    return NormalizedPerson(
        source="macos_contacts", source_id=source_id, display_name=name,
        phones=[{"value": phone, "label": "Mobile"}], emails=[],
    )


def _snap(status: SnapshotStatus, people: list[NormalizedPerson]) -> ContactsSnapshot:
    return ContactsSnapshot(
        status=status, people=people,
        stores_total=1, stores_read=1, store_ids=["local"],
    )


def test_real_contacts_probing_disabled_by_default():
    # The autouse conftest seam forces a non-darwin platform, so a probe never
    # opens the real AddressBook regardless of the host OS.
    assert macos_contacts.probe_access() == "denied"
    # ...and the background sync loop is not armed under test.
    from app.config import settings
    assert settings.contacts_sync_enabled is False


def test_default_autouse_seam_blocks_real_addressbook_read(monkeypatch):
    """M10 s1 review gap: enabling contacts and calling tick() with NO
    fake_snapshot configured beyond the global autouse default must NEVER reach
    the real AddressBook, regardless of host platform. read_snapshot() only ever
    consults `_FAKE_SNAPSHOT` (never the platform override) before touching
    disk, so the fix is a default fake_snapshot seeded by the autouse fixture --
    prove it short-circuits before `_store_paths` (the first real-disk touch)
    ever runs."""
    store.set_contacts_enabled(True, region="US", now=NOW)

    def _must_not_touch_disk(*a, **k):
        raise AssertionError(
            "_store_paths must not run: the autouse default fake_snapshot "
            "should short-circuit read_snapshot before any real disk access")
    monkeypatch.setattr(macos_contacts, "_store_paths", _must_not_touch_disk)

    result = contacts_sync.tick(NOW)
    assert result.status == "access_denied"
    assert result.access == "denied"
    assert len(store.list_people()["items"]) == 0


def test_remote_postgres_outage_is_error_never_empty(monkeypatch):
    """An unreachable/erroring PostgreSQL server is a FAILED sync (status='error'),
    NEVER 'empty' — and it must not soft-delete existing rows. Guards the money-
    manufacturing-style bug where an outage looks like 'every contact deleted'."""
    store.set_contacts_enabled(True, region="US", now=NOW)
    macos_contacts.configure(fake_snapshot=_snap(
        SnapshotStatus.COMPLETE_NONEMPTY,
        [_person("A", "Ada", "+15550001111"), _person("B", "Bo", "+15550002222")]))
    first = contacts_sync.tick(NOW)
    assert first.status == "ok"
    assert len(store.list_people()["items"]) == 2

    # Now the database link drops during apply, while the reader still returns a
    # snapshot that happens to omit B (as if B were removed).
    def _boom(snapshot, now):
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))
    monkeypatch.setattr(store, "apply_contacts_snapshot", _boom)
    macos_contacts.configure(fake_snapshot=_snap(
        SnapshotStatus.COMPLETE_NONEMPTY, [_person("A", "Ada", "+15550001111")]))
    res = contacts_sync.tick(NOW)
    assert res.status == "error"
    assert res.last_error
    assert res.removed == 0
    # B was NOT soft-deleted — the failed apply never reconciled.
    assert len(store.list_people()["items"]) == 2


def test_db_error_mid_apply_rolls_back_atomically(monkeypatch):
    """A DB-level failure part-way through apply rolls the whole transaction back:
    no half-written rows survive, and pre-existing rows are untouched. (Infra
    errors are fatal — they must NOT be swallowed as a per-record 'partial'.)"""
    store.set_contacts_enabled(True, region="US", now=NOW)
    seed = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [_person("A", "Ada", "+15550001111"),
                  _person("B", "Bo", "+15550002222")])
    assert store.apply_contacts_snapshot(seed, NOW).status == "ok"

    import app.identity as identity
    real = identity.canon_handle

    def _drop_on_c(raw, region):
        if raw == "+15550009999":            # C's handle -> the link "drops"
            raise OperationalError("INSERT", {}, Exception("connection reset"))
        return real(raw, region)
    monkeypatch.setattr(identity, "canon_handle", _drop_on_c)

    bad = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                [_person("A", "Ada", "+15550001111"),
                 _person("B", "Bo", "+15550002222"),
                 _person("C", "Cy", "+15550009999")])
    with pytest.raises(OperationalError):
        store.apply_contacts_snapshot(bad, NOW)

    # Rolled back: C never landed, A/B unchanged, count still 2.
    names = {p["display_name"] for p in store.list_people()["items"]}
    assert names == {"Ada", "Bo"}


def test_partial_read_snapshot_never_reconciles():
    """A PARTIAL_READ snapshot (>=1 store failed) writes state only — no row
    writes, no soft-deletes — because reconciliation on an incomplete read would
    delete real contacts."""
    store.set_contacts_enabled(True, region="US", now=NOW)
    store.apply_contacts_snapshot(_snap(
        SnapshotStatus.COMPLETE_NONEMPTY,
        [_person("A", "Ada", "+15550001111"),
         _person("B", "Bo", "+15550002222")]), NOW)
    assert len(store.list_people()["items"]) == 2

    partial = ContactsSnapshot(status=SnapshotStatus.PARTIAL_READ, people=[],
                               stores_total=2, stores_read=1, store_ids=["local"])
    res = store.apply_contacts_snapshot(partial, NOW)
    assert res.status == "partial"
    assert res.removed == 0
    assert len(store.list_people()["items"]) == 2      # nothing deleted


def test_partial_upsert_failure_marks_partial_and_preserves_absent(monkeypatch):
    """A per-record failure inside a COMPLETE_* apply commits the good rows,
    records status='partial', and SKIPS reconciliation — so a contact absent from
    this snapshot is NOT soft-deleted (an incomplete apply must never delete)."""
    store.set_contacts_enabled(True, region="US", now=NOW)
    seed = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [_person("A", "Ada", "+15550001111"),
                  _person("D", "Di", "+15550003333")])
    store.apply_contacts_snapshot(seed, NOW)

    import app.identity as identity
    real = identity.canon_handle

    def _fail_on_b(raw, region):
        if raw == "+15550008888":            # only B's reindex explodes
            raise ValueError("bad handle transform")
        return real(raw, region)
    monkeypatch.setattr(identity, "canon_handle", _fail_on_b)

    # New snapshot: A stays, B is new-but-broken, C is new-and-fine; D is ABSENT.
    snap = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [_person("A", "Ada", "+15550001111"),
                  _person("B", "Bo", "+15550008888"),
                  _person("C", "Cy", "+15550004444")])
    res = store.apply_contacts_snapshot(snap, NOW)
    assert res.status == "partial"
    assert res.removed == 0                    # reconcile skipped
    names = {p["display_name"] for p in store.list_people()["items"]}
    assert "Ada" in names and "Cy" in names    # good upserts committed
    assert "Di" in names                       # absent D preserved, not soft-deleted


def test_overlapping_applies_serialize_under_the_lock(monkeypatch):
    """Two applies never interleave: the module process lock (plus, on Postgres,
    pg_advisory_xact_lock) serializes them, so the single shared SQLite connection
    is used one-at-a-time and no rows are corrupted. On the Postgres CI leg this
    same test exercises advisory-lock contention."""
    people = [_person(f"P{i}", f"Person {i}", f"+1555000{i:04d}") for i in range(4)]
    snap = _snap(SnapshotStatus.COMPLETE_NONEMPTY, people)

    import app.identity as identity
    real = identity.canon_handle
    gate = threading.Lock()
    live = {"n": 0, "max": 0}

    def _tracked(raw, region):
        with gate:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        time.sleep(0.02)
        with gate:
            live["n"] -= 1
        return real(raw, region)
    monkeypatch.setattr(identity, "canon_handle", _tracked)

    errors: list[BaseException] = []

    def _worker():
        try:
            store.apply_contacts_snapshot(snap, NOW)
        except BaseException as exc:          # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []                        # no "database is locked" / cursor races
    assert live["max"] == 1                     # applies never overlapped
    assert len(store.list_people()["items"]) == 4        # every person landed, none dropped
