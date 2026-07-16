import hashlib
import os
from types import SimpleNamespace

from app.providers import contact_photos as cp

# minimal but real magic-byte headers
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 16
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 16


def test_detect_media_types():
    assert cp.detect_media_type(_JPEG) == ("jpg", "image/jpeg")
    assert cp.detect_media_type(_PNG) == ("png", "image/png")
    assert cp.detect_media_type(_HEIC) == ("heic", "image/heic")     # NOT assumed JFIF
    assert cp.detect_media_type(_GIF) == ("gif", "image/gif")
    assert cp.detect_media_type(b"not an image at all") is None
    assert cp.detect_media_type(b"") is None


def test_store_and_resolve_roundtrip(tmp_path):
    key = cp.store_photo(_PNG, store_id="local", source_id="abc", photos_root=str(tmp_path))
    assert key == hashlib.sha256(b"local:abc").hexdigest() + ".png"   # opaque, relative
    path = cp.resolve_photo(key, str(tmp_path))
    assert path and os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == _PNG
    assert cp.content_type_for(key) == "image/png"
    assert cp.key_for_path(path) == key


def test_media_type_drives_extension(tmp_path):
    jpg = cp.store_photo(_JPEG, store_id="s", source_id="j", photos_root=str(tmp_path))
    heic = cp.store_photo(_HEIC, store_id="s", source_id="h", photos_root=str(tmp_path))
    assert jpg.endswith(".jpg") and cp.content_type_for(jpg) == "image/jpeg"
    assert heic.endswith(".heic") and cp.content_type_for(heic) == "image/heic"


def test_store_photo_rejects_malformed_image(tmp_path):
    assert cp.store_photo(b"garbage bytes here", store_id="s", source_id="i",
                          photos_root=str(tmp_path)) is None
    assert os.listdir(tmp_path) == []                     # nothing written


def test_resolve_missing_file_returns_none(tmp_path):
    key = hashlib.sha256(b"x:y").hexdigest() + ".jpg"
    assert cp.resolve_photo(key, str(tmp_path)) is None


def test_containment_rejects_parent_traversal(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("top secret")
    assert cp.resolve_photo("../secret.txt", str(root)) is None


def test_containment_rejects_symlink_escape(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, root / "escape.jpg")
    assert cp.resolve_photo("escape.jpg", str(root)) is None


def test_atomic_write_leaves_no_partial_on_replace_failure(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(cp.os, "replace", _boom)
    assert cp.store_photo(_PNG, store_id="s", source_id="i",
                          photos_root=str(tmp_path)) is None
    # the temp is cleaned up; no destination file survives
    assert [f for f in os.listdir(tmp_path) if not f.startswith(".tmp_photo_")] == []


def test_store_photo_swallows_permission_error(tmp_path, monkeypatch):
    def _denied(*a, **k):
        raise PermissionError("nope")
    monkeypatch.setattr(cp.os, "makedirs", _denied)
    assert cp.store_photo(_PNG, store_id="s", source_id="i",
                          photos_root=str(tmp_path / "sub")) is None   # never raises


def test_cleanup_orphans_removes_unreferenced(tmp_path):
    k1 = cp.store_photo(_PNG, store_id="s", source_id="one", photos_root=str(tmp_path))
    k2 = cp.store_photo(_PNG, store_id="s", source_id="two", photos_root=str(tmp_path))
    removed = cp.cleanup_orphans({k1}, str(tmp_path))
    assert removed == 1
    assert cp.resolve_photo(k1, str(tmp_path)) is not None
    assert cp.resolve_photo(k2, str(tmp_path)) is None


def test_delete_photo_removes_file(tmp_path):
    key = cp.store_photo(_PNG, store_id="s", source_id="i", photos_root=str(tmp_path))
    cp.delete_photo(key, str(tmp_path))
    assert cp.resolve_photo(key, str(tmp_path)) is None
    cp.delete_photo(key, str(tmp_path))               # idempotent; no raise on a gone file


def test_resolve_root_relative_goes_under_app_support(tmp_path):
    s = SimpleNamespace(app_support_dir=str(tmp_path / "AppSupport"),
                        contacts_photos_dir="contact_photos")
    assert cp.resolve_root(s) == os.path.join(str(tmp_path / "AppSupport"), "contact_photos")


def test_resolve_root_absolute_kept(tmp_path):
    s = SimpleNamespace(app_support_dir="~/whatever",
                        contacts_photos_dir=str(tmp_path / "abs_photos"))
    assert cp.resolve_root(s) == str(tmp_path / "abs_photos")
