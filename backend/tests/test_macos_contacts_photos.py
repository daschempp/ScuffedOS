import os
import sqlite3

import pytest

from app.providers import contact_photos
from app.providers.macos_contacts import SnapshotStatus, read_snapshot

_ENT = 19
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _store(path, blob):
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);"
        "CREATE TABLE ZABCDRECORD (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUNIQUEID TEXT,"
        " ZFIRSTNAME TEXT, ZLASTNAME TEXT, ZNICKNAME TEXT, ZORGANIZATION TEXT, ZJOBTITLE TEXT,"
        " ZDISPLAYFLAGS INTEGER, ZTHUMBNAILIMAGEDATA BLOB);"
        "CREATE TABLE ZABCDPHONENUMBER (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,"
        " ZFULLNUMBER TEXT, ZLABEL TEXT, ZORDERINGINDEX INTEGER);"
        "CREATE TABLE ZABCDEMAILADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,"
        " ZADDRESS TEXT, ZLABEL TEXT, ZORDERINGINDEX INTEGER);"
    )
    con.execute("INSERT INTO Z_PRIMARYKEY VALUES (?, 'ABCDContact')", (_ENT,))
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS,"
        " ZTHUMBNAILIMAGEDATA) VALUES (1, ?, 'UID-P:ABPerson', 'Pic', 0, ?)", (_ENT, blob))
    con.commit()
    con.close()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "AddressBook"
    r.mkdir()
    return r


def test_inline_tagged_photo_extracted(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + _PNG)     # 1-byte inline tag
    photos = tmp_path / "photos"
    snap = read_snapshot(str(root), region="US", photos_dir=str(photos))
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    p = snap.people[0]
    assert p.has_photo is True
    assert p.photo_path and p.photo_path.endswith(".png")           # transient ABSOLUTE path
    assert os.path.isfile(p.photo_path)
    key = contact_photos.key_for_path(p.photo_path)
    assert contact_photos.resolve_photo(key, str(photos)) is not None


def test_raw_untagged_photo_extracted(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), _PNG)              # raw, no tag prefix
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    assert snap.people[0].has_photo is True


def test_person_without_thumbnail_has_no_photo(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), None)              # NULL blob
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people[0].has_photo is False
    assert snap.people[0].photo_path is None


def test_malformed_blob_imports_person_without_photo(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + b"not an image")
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    # the person is STILL imported and the snapshot stays COMPLETE — a bad photo
    # never aborts the read
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people[0].has_photo is False


def test_photos_dir_none_skips_extraction(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + _PNG)
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.people[0].has_photo is False
