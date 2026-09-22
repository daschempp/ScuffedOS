import os
import sqlite3

import pytest

from app.providers import contact_photos, macos_contacts
from app.providers.macos_contacts import SnapshotStatus, read_snapshot

_ENT = 19
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _real_reads(no_external_services):
    """This file reads REAL (fixture) .abcddb files via read_snapshot() to
    exercise the photo-extraction logic. The global autouse seam (conftest.py)
    now seeds a default fake_snapshot so read_snapshot() never touches a real
    AddressBook by default -- opt back out of that default here so these tests
    still read the on-disk fixtures they build. Depending on
    `no_external_services` (by name, not just autouse) guarantees this fixture's
    reset runs AFTER that seam is installed, not before."""
    macos_contacts.configure(platform="linux", fake_snapshot=None)
    yield


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


# ---- 4d: the tag 0x02 external-data branch of _thumbnail_bytes --------------
# Core Data keeps a large thumbnail OUTSIDE the store, as a filename reference
# into <parent>/.<stem>_SUPPORT/_EXTERNAL_DATA/. The ref blob is b"\x02" + the
# NUL-terminated ascii filename.

def _ext_ref(name: str) -> bytes:
    return b"\x02" + name.encode() + b"\x00"


def _external_data_dir(root):
    d = root / ".AddressBook-v22_SUPPORT" / "_EXTERNAL_DATA"
    d.mkdir(parents=True)
    return d


def test_4d_external_data_photo_is_extracted(root, tmp_path):
    """A valid ref resolves to the referenced file's bytes (read from the REAL
    store's _SUPPORT dir, not the private snapshot copy)."""
    _external_data_dir(root).joinpath("thumb-1").write_bytes(_PNG)
    _store(str(root / "AddressBook-v22.abcddb"), _ext_ref("thumb-1"))
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    person = snap.people[0]
    assert person.has_photo is True
    with open(person.photo_path, "rb") as fh:
        assert fh.read() == _PNG


def test_4d_external_data_missing_file_is_no_photo(root):
    _external_data_dir(root)
    db = str(root / "AddressBook-v22.abcddb")
    assert macos_contacts._thumbnail_bytes(_ext_ref("gone"), db) is None


def test_4d_external_data_name_escaping_the_support_dir_is_rejected(root):
    """Path-traversal guard: a name with '/' is refused even when it resolves to
    a real image just outside _EXTERNAL_DATA."""
    ext = _external_data_dir(root)
    ext.parent.joinpath("escaped.png").write_bytes(_PNG)      # one level up
    db = str(root / "AddressBook-v22.abcddb")
    assert macos_contacts._thumbnail_bytes(_ext_ref("../escaped.png"), db) is None
    assert (ext.parent / "escaped.png").read_bytes() == _PNG  # it WAS readable


@pytest.mark.parametrize("name", ["sub/thumb", ".hidden", ""])
def test_4d_external_data_unsafe_names_are_rejected(root, name):
    _external_data_dir(root)
    db = str(root / "AddressBook-v22.abcddb")
    assert macos_contacts._thumbnail_bytes(_ext_ref(name), db) is None


def test_4d_external_data_non_image_bytes_are_rejected(root):
    _external_data_dir(root).joinpath("thumb-2").write_bytes(b"not an image at all")
    db = str(root / "AddressBook-v22.abcddb")
    assert macos_contacts._thumbnail_bytes(_ext_ref("thumb-2"), db) is None
