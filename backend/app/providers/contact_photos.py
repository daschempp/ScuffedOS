"""Contact-photo storage (M10 s1).

Thumbnails extracted from the local AddressBook are written to the backend host's
App Support directory — NOT into PostgreSQL and NOT under ./data. The database
stores only an OPAQUE, RELATIVE photo key (sha256 of store_id:source_id + the
detected extension); the bytes live on disk keyed by that name in a flat layout.

Hardening:
- media type detected from MAGIC BYTES (JPEG/PNG/HEIC/GIF) -> correct extension +
  Content-Type; we never assume JFIF.
- writes are ATOMIC (temp file in the same dir + os.replace on the same fs).
- serving resolves the key against the photos root with a CONTAINMENT check
  (realpath must stay under the root), so a crafted / symlinked / '..' key cannot
  escape the directory.
- every failure (permission, disk-full, invalid filename, malformed image) is
  swallowed and returns a falsey result -> a photo problem NEVER aborts a
  contacts snapshot; the person is simply imported without a photo.
- cleanup removes superseded / orphaned files on re-sync, forget, and delete.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile

logger = logging.getLogger("scuffed_os.contact_photos")

_CONTENT_TYPE = {
    "jpg": "image/jpeg", "png": "image/png",
    "heic": "image/heic", "gif": "image/gif",
}
# ISO-BMFF 'ftyp' brands that mean HEIF/HEIC (Apple contact photos on modern macOS)
_HEIC_BRANDS = {b"heic", b"heix", b"heif", b"hevc", b"hevx", b"mif1", b"msf1"}


def detect_media_type(data: bytes) -> tuple[str, str] | None:
    """(ext, content_type) from magic bytes, or None if unrecognized."""
    if not data or len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return ("jpg", "image/jpeg")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ("png", "image/png")
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return ("heic", "image/heic")
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ("gif", "image/gif")
    return None


def content_type_for(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if key and "." in key else ""
    return _CONTENT_TYPE.get(ext, "application/octet-stream")


def resolve_root(settings) -> str:
    """The photos root. `contacts_photos_dir` may be absolute or (default)
    relative, in which case it resolves UNDER app_support_dir — never ./data."""
    configured = os.path.expanduser(getattr(settings, "contacts_photos_dir", "contact_photos"))
    if os.path.isabs(configured):
        return configured
    base = os.path.expanduser(getattr(settings, "app_support_dir",
                                      "~/Library/Application Support/ScuffedOS"))
    return os.path.join(base, configured)


def photo_key(store_id: str, source_id: str, ext: str) -> str:
    digest = hashlib.sha256(f"{store_id}:{source_id}".encode()).hexdigest()
    return f"{digest}.{ext}"


def key_for_path(photo_path: str) -> str:
    """The opaque relative key from the reader's transient absolute path. The
    layout is flat, so the key is just the basename (contract: photo_key is
    RELATIVE; the reader's absolute path is converted here, never persisted raw)."""
    return os.path.basename(photo_path)


def _within(root_real: str, candidate_real: str) -> bool:
    return candidate_real == root_real or candidate_real.startswith(root_real + os.sep)


def store_photo(data: bytes, *, store_id: str, source_id: str,
                photos_root: str) -> str | None:
    """Atomically write `data` under photos_root, keyed by sha256(store_id:source_id)
    + the detected extension. Returns the opaque relative key, or None on ANY
    failure (never raises)."""
    detected = detect_media_type(data)
    if detected is None:
        return None
    ext, _ct = detected
    root = os.path.expanduser(photos_root)
    key = photo_key(store_id, source_id, ext)
    try:
        os.makedirs(root, exist_ok=True)
        dst = os.path.join(root, key)
        # containment (the key is machine-generated, but never trust it)
        root_real = os.path.realpath(root)
        if not _within(root_real, os.path.realpath(dst)):
            return None
        fd, tmp = tempfile.mkstemp(prefix=".tmp_photo_", dir=root)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dst)                     # atomic within the same filesystem
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except (OSError, ValueError) as exc:
        logger.warning("contact photo write skipped (%s)", exc.__class__.__name__)
        return None
    return key


def resolve_photo(key: str, photos_root: str) -> str | None:
    """Absolute path for a stored key, or None. Rejects any key whose realpath
    escapes the root (symlink / '..' traversal) and any missing file."""
    if not key:
        return None
    root_real = os.path.realpath(os.path.expanduser(photos_root))
    candidate = os.path.realpath(os.path.join(root_real, key))
    if not _within(root_real, candidate):
        return None
    if not os.path.isfile(candidate):
        return None
    return candidate


def delete_photo(key: str | None, photos_root: str) -> None:
    """Remove one stored photo. Idempotent; never raises (a gone/absent file is
    a no-op). Used when a person is deleted or its photo is superseded."""
    path = resolve_photo(key, photos_root) if key else None
    if path is None:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def cleanup_orphans(keep_keys: set[str], photos_root: str) -> int:
    """Remove every file in photos_root not referenced by keep_keys. Called after
    a successful re-sync, on forget, and on delete. In-flight temp files are left
    alone. Returns the number of files removed."""
    root = os.path.expanduser(photos_root)
    if not os.path.isdir(root):
        return 0
    removed = 0
    for name in os.listdir(root):
        if name in keep_keys or name.startswith(".tmp_photo_"):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        try:
            os.unlink(full)
            removed += 1
        except OSError:
            pass
    return removed
