import errno
import glob
import hashlib
import os
import sqlite3
import tempfile

import pytest

from app.providers import macos_contacts
from app.providers.macos_contacts import (
    ContactsSnapshot, SnapshotStatus, probe_access, read_snapshot,
)

# The ABCDContact entity number is DISCOVERED at runtime via Z_PRIMARYKEY. We
# deliberately pick 19 (never 1) so a hardcoded entity number would fail loudly.
_ENT_CONTACT = 19
_ENT_GROUP = 20

_SCHEMA = """
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);
CREATE TABLE ZABCDRECORD (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUNIQUEID TEXT,
    ZFIRSTNAME TEXT, ZLASTNAME TEXT, ZNICKNAME TEXT,
    ZORGANIZATION TEXT, ZJOBTITLE TEXT, ZDISPLAYFLAGS INTEGER,
    ZTHUMBNAILIMAGEDATA BLOB
);
CREATE TABLE ZABCDPHONENUMBER (
    Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZFULLNUMBER TEXT,
    ZLABEL TEXT, ZORDERINGINDEX INTEGER
);
CREATE TABLE ZABCDEMAILADDRESS (
    Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZADDRESS TEXT,
    ZLABEL TEXT, ZORDERINGINDEX INTEGER
);
"""


def _new_store(path, *, contact_entity_name="ABCDContact", schema=_SCHEMA):
    con = sqlite3.connect(path)
    con.executescript(schema)
    if contact_entity_name is not None:
        con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
                    (_ENT_CONTACT, contact_entity_name))
    con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, 'ABCDGroup')",
                (_ENT_GROUP,))
    return con


def _seed_local(con):
    # a normal person, with a wrapped-label phone + email
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZDISPLAYFLAGS)"
        " VALUES (1, ?, 'UID-1:ABPerson', 'Jane', 'Doe', 0)", (_ENT_CONTACT,))
    con.execute("INSERT INTO ZABCDPHONENUMBER (Z_PK, ZOWNER, ZFULLNUMBER, ZLABEL, ZORDERINGINDEX)"
                " VALUES (1, 1, '(555) 123-4567', '_$!<Mobile>!$_', 0)")
    con.execute("INSERT INTO ZABCDEMAILADDRESS (Z_PK, ZOWNER, ZADDRESS, ZLABEL, ZORDERINGINDEX)"
                " VALUES (1, 1, 'Jane@iCloud.com', '_$!<Home>!$_', 0)")
    # a company row (ZDISPLAYFLAGS bit0 set)
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZORGANIZATION, ZDISPLAYFLAGS)"
                " VALUES (2, ?, 'UID-2:ABPerson', 'Acme Inc', 1)", (_ENT_CONTACT,))
    # a NULL-displayflags row (must read as not-company, never crash)
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS)"
                " VALUES (3, ?, 'UID-3:ABPerson', 'Solo', NULL)", (_ENT_CONTACT,))
    # a GROUP row (different Z_ENT) that MUST be excluded
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZNICKNAME)"
                " VALUES (4, ?, 'UID-G:ABGroup', 'My Group')", (_ENT_GROUP,))


@pytest.fixture
def ab_root(tmp_path):
    """A top-level 'local' store plus a SECOND store under Sources/<UUID> that
    holds a UNIQUE contact — proving multi-store union and per-store namespacing."""
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = _new_store(str(root / "AddressBook-v22.abcddb"))
    _seed_local(con)
    con.commit()
    con.close()

    src = root / "Sources" / "ABCDEF-1234"
    src.mkdir(parents=True)
    con2 = _new_store(str(src / "AddressBook-v22.abcddb"))
    con2.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZDISPLAYFLAGS)"
        " VALUES (7, ?, 'UID-Z:ABPerson', 'Zed', 'Unique', 0)", (_ENT_CONTACT,))
    con2.commit()
    con2.close()
    return str(root)


def test_complete_nonempty_unions_both_stores(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert isinstance(snap, ContactsSnapshot)
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.stores_total == 2 and snap.stores_read == 2
    assert set(snap.store_ids) == {"local", "ABCDEF-1234"}
    names = {p.display_name for p in snap.people}
    assert "Jane Doe" in names
    assert "Zed Unique" in names          # the UNIQUE contact from the 2nd store was imported


def test_second_store_contact_is_namespaced_to_its_store(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    zed = next(p for p in snap.people if p.display_name == "Zed Unique")
    assert zed.meta["store_id"] == "ABCDEF-1234"
    assert zed.meta["zuniqueid"] == "UID-Z:ABPerson"
    assert zed.meta["z_pk"] == 7


def test_source_id_is_hashed_namespaced_never_raw(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    jane = next(p for p in snap.people if p.display_name == "Jane Doe")
    # sha1 hex, 40 chars, fits String(128); NEVER an unqualified 'zpk:1'
    assert len(jane.source_id) == 40
    assert all(c in "0123456789abcdef" for c in jane.source_id)
    assert "zpk:" not in jane.source_id
    assert jane.source_id == hashlib.sha1(b"local:UID-1:ABPerson").hexdigest()
    # raw ids are preserved in meta for debugging
    assert jane.meta["zuniqueid"] == "UID-1:ABPerson"
    assert jane.meta["store_id"] == "local"


def test_labels_unwrapped(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    jane = next(p for p in snap.people if p.display_name == "Jane Doe")
    assert jane.phones[0]["value"] == "(555) 123-4567"     # reader keeps the RAW value
    assert jane.phones[0]["label"] == "Mobile"             # _$!<Mobile>!$_ unwrapped
    assert jane.emails[0]["label"] == "Home"


def test_groups_excluded(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert all("ABGroup" not in (p.meta.get("zuniqueid") or "") for p in snap.people)
    assert all(p.display_name != "My Group" for p in snap.people)


def test_company_and_null_displayflags(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    acme = next(p for p in snap.people if p.organization == "Acme Inc")
    assert acme.meta["is_company"] is True
    assert acme.display_name == "Acme Inc"
    solo = next(p for p in snap.people if p.first_name == "Solo")
    assert solo.meta["is_company"] is False


def test_complete_empty_when_store_present_but_no_contacts(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = _new_store(str(root / "AddressBook-v22.abcddb"))   # entity present, zero contact rows
    con.commit()
    con.close()
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.COMPLETE_EMPTY
    assert snap.people == []                                 # [] people is ONLY ever COMPLETE_EMPTY


def test_missing_store(tmp_path):
    snap = read_snapshot(str(tmp_path / "nope"), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.MISSING_STORE
    assert snap.people == []


def test_unsupported_when_abcdcontact_entity_absent(tmp_path):
    # tables all present, but Z_PRIMARYKEY has no ABCDContact row -> UNSUPPORTED, not EMPTY
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = _new_store(str(root / "AddressBook-v22.abcddb"), contact_entity_name=None)
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS)"
                " VALUES (1, 19, 'UID-1:ABPerson', 'Jane', 0)")
    con.commit()
    con.close()
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.UNSUPPORTED_SCHEMA
    assert snap.people == []


def test_unsupported_when_required_table_missing(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = sqlite3.connect(str(root / "AddressBook-v22.abcddb"))
    con.executescript("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);")  # no ZABCDRECORD
    con.execute("INSERT INTO Z_PRIMARYKEY VALUES (19, 'ABCDContact')")
    con.commit()
    con.close()
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.UNSUPPORTED_SCHEMA


def test_io_error_on_corrupt_store(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    (root / "AddressBook-v22.abcddb").write_bytes(b"this is definitely not a sqlite database")
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.IO_ERROR
    assert snap.people == []


def test_partial_read_when_one_store_fails(ab_root):
    # corrupt the SECOND store; the first still reads fine -> PARTIAL_READ (reconcile unsafe)
    bad = os.path.join(ab_root, "Sources", "ABCDEF-1234", "AddressBook-v22.abcddb")
    with open(bad, "wb") as fh:
        fh.write(b"corrupted")
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.PARTIAL_READ
    assert snap.stores_total == 2 and snap.stores_read == 1
    assert snap.store_ids == ["local"]
    assert any(p.display_name == "Jane Doe" for p in snap.people)   # good store still imported


def test_access_denied_via_eperm(ab_root, monkeypatch):
    # simulate Full Disk Access denied: the private-snapshot copy hits EPERM
    def _eperm(_path):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(macos_contacts, "_private_snapshot", _eperm)
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.ACCESS_DENIED
    assert snap.people == []                        # a denied read NEVER yields rows


def test_private_snapshot_cleans_up_tempdir_on_copy_failure(ab_root, monkeypatch):
    """Real _private_snapshot (NOT mocked): when the underlying shutil.copy2 raises
    -- exactly how an FDA-denied EPERM surfaces -- the tmpdir already created by
    tempfile.mkdtemp(prefix="scuffedos_ab_") must be cleaned up, not leaked.
    Regression for a bug where _private_snapshot exited via the exception before
    ever returning tmpdir, so the caller's `shutil.rmtree` cleanup never ran --
    one leaked empty temp dir per store per read_snapshot call while FDA is
    ungranted (the common, long-lived state)."""
    def _boom(*_a, **_kw):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(macos_contacts.shutil, "copy2", _boom)

    pattern = os.path.join(tempfile.gettempdir(), "scuffedos_ab_*")
    before = set(glob.glob(pattern))
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    after = set(glob.glob(pattern))

    assert snap.status is SnapshotStatus.ACCESS_DENIED
    assert snap.people == []
    assert after - before == set(), "a scuffedos_ab_* tempdir was leaked on copy failure"


def test_disabled_reads_nothing(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None, enabled=False)
    assert snap.people == []
    assert snap.status is not SnapshotStatus.COMPLETE_NONEMPTY   # no writes/reconcile possible


def test_error_string_is_redacted(tmp_path):
    snap = read_snapshot(str(tmp_path / "SecretUser" / "nope"), region="US", photos_dir=None)
    assert snap.error and "SecretUser" not in snap.error         # no home path / username leak


def test_probe_access_granted_on_readable_fixture(ab_root, monkeypatch):
    macos_contacts.configure()   # clear the autouse platform seam; drive via _is_darwin
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: True)
    assert probe_access(ab_root) == "granted"


def test_probe_access_denied_on_missing(tmp_path, monkeypatch):
    macos_contacts.configure()
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: True)
    assert probe_access(str(tmp_path / "none")) == "denied"


def test_probe_access_unknown_off_darwin(ab_root, monkeypatch):
    macos_contacts.configure()
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: False)
    assert probe_access(ab_root) == "unknown"
