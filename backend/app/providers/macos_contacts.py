"""macOS Contacts source-of-truth module (M10 s1).

This file lands ONLY the shared sync-contract value types below. Task 4 APPENDS
the local, read-only AddressBook reader (``read_snapshot``, ``probe_access``,
``DEFAULT_ROOT``, photo extraction) beneath them — it imports ``NormalizedPerson``
from ``.base`` and must NOT redefine these types.

Contacts are read locally and read-only from the machine running the backend;
the structured fields persist to the configured PostgreSQL database, which may
run locally (loopback) or on a remote/self-hosted server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SnapshotStatus(str, Enum):
    COMPLETE_NONEMPTY = "complete_nonempty"   # all discovered stores read OK; >=1 contact
    COMPLETE_EMPTY = "complete_empty"         # all discovered stores read OK; zero contacts
    ACCESS_DENIED = "access_denied"           # EPERM / Full Disk Access missing
    UNSUPPORTED_SCHEMA = "unsupported_schema" # missing ABCDContact entity or required table/column
    MISSING_STORE = "missing_store"           # no AddressBook store files present
    PARTIAL_READ = "partial_read"             # >=1 store read but >=1 failed -> reconciliation unsafe
    IO_ERROR = "io_error"                     # sqlite corruption / generic I/O failure


@dataclass
class ContactsSnapshot:
    status: SnapshotStatus
    people: list                              # list[NormalizedPerson]; populated only for COMPLETE_*
    stores_total: int = 0
    stores_read: int = 0
    store_ids: list = field(default_factory=list)   # stable ids of stores read OK
    error: str | None = None                  # redacted; never a DSN/credential


@dataclass
class SyncResult:
    status: str          # 'ok' | 'empty' | 'access_denied' | 'unsupported' | 'partial' | 'error' | 'disabled'
    access: str          # 'granted' | 'denied' | 'unknown'
    imported: int = 0
    updated: int = 0
    removed: int = 0
    last_sync_at: object | None = None   # datetime
    last_error: str | None = None


# ---- reader (Task 4 appends below Task 3's shared types at the top of this
# file; this comment supplements, and does NOT replace, Task 3's module
# docstring already at the top of macos_contacts.py) ----
#
# Reads the local macOS Contacts (AddressBook) store, one-way and read-only, by
# opening the Core Data SQLite files directly (there is no supported API). The
# schema is stable at AddressBook-v22 (macOS 13-26) but is treated DEFENSIVELY:
# the ABCDContact entity number is discovered at runtime via Z_PRIMARYKEY (never
# hardcoded), required tables/columns are probed via sqlite_master/PRAGMA, and
# any single-store failure is isolated and classified rather than raised.
#
# read_snapshot() NEVER raises for control flow — it returns a ContactsSnapshot
# whose `status` (SnapshotStatus, defined above) tells the caller exactly what
# happened; only COMPLETE_* may drive soft-delete reconciliation downstream. A
# `[]` people list is ONLY ever COMPLETE_EMPTY — a missing entity/table is
# UNSUPPORTED_SCHEMA, not empty.
#
# Live-read safety (why NOT immutable=1): the AddressBook store is a WAL-mode
# SQLite database that Contacts.app / cloudd write to concurrently. immutable=1
# would dodge locks but tells SQLite the file never changes, so it IGNORES the
# -wal frames — yielding a stale/inconsistent view and masking real corruption.
# Instead we take a private point-in-time SNAPSHOT: copy the store plus its
# -wal/-shm sidecars into a per-read temp dir and read the COPY with mode=ro +
# PRAGMA query_only=ON + a bounded busy_timeout inside a single read
# transaction — consistent, never disturbs the live store, still reflects
# committed WAL frames.
import errno
import glob
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import contact_photos
from .base import NormalizedPerson

logger = logging.getLogger("scuffed_os.macos_contacts")

DEFAULT_ROOT = "~/Library/Application Support/AddressBook"

_STORE_FILENAME = "AddressBook-v22.abcddb"
_REQUIRED_TABLES = ("Z_PRIMARYKEY", "ZABCDRECORD")
# Optional record columns probed per store; absent ones default to None so an
# older/newer schema variant degrades instead of raising.
_RECORD_OPTIONAL = (
    "ZUNIQUEID", "ZFIRSTNAME", "ZLASTNAME", "ZNICKNAME",
    "ZORGANIZATION", "ZJOBTITLE", "ZDISPLAYFLAGS", "ZTHUMBNAILIMAGEDATA",
)


# SnapshotStatus / ContactsSnapshot / SyncResult are defined above (Task 3) — do not redefine


# ---- per-store failure taxonomy (classified, never surfaced raw) -------------
class _StoreFailure(Exception):
    pass


class _AccessDenied(_StoreFailure):
    pass


class _UnsupportedSchema(_StoreFailure):
    pass


class _IOFailure(_StoreFailure):
    pass


# ---- test seam (contract: Testing/CI seam) ----------------------------------
# configure(fake_snapshot=..., platform=...) injects a canned snapshot and/or a
# platform so tests never touch the real AddressBook. The autouse suite fixture
# (Task 10) installs a non-darwin platform; individual tests install a fake
# snapshot (which read_snapshot returns verbatim and probe_access derives access
# from). configure() with no args resets to real detection.
_FAKE_SNAPSHOT: "ContactsSnapshot | None" = None
_PLATFORM_OVERRIDE: str | None = None


def configure(*, fake_snapshot: "ContactsSnapshot | None" = None,
              platform: str | None = None) -> None:
    """Install (or clear) the read/probe test seam."""
    global _FAKE_SNAPSHOT, _PLATFORM_OVERRIDE
    _FAKE_SNAPSHOT = fake_snapshot
    _PLATFORM_OVERRIDE = platform


def _is_darwin() -> bool:
    if _PLATFORM_OVERRIDE is not None:
        return _PLATFORM_OVERRIDE == "darwin"
    return sys.platform == "darwin"


def is_supported() -> bool:
    """Public platform seam (contract: Testing/CI seam): True on a macOS host with
    the AddressBook API. Returns ``_PLATFORM_OVERRIDE == "darwin"`` when a platform
    is injected, else ``sys.platform == "darwin"`` (this is exactly ``_is_darwin``).
    Connector/UI code MUST call this instead of reading raw ``sys.platform`` so
    ``configure(platform=…)`` drives platform detection deterministically on macOS
    dev + CI alike. Permission (FDA) is a SEPARATE concern — see ``probe_access``."""
    return _is_darwin()


def _redact(path: str) -> str:
    """Errors must never leak a home path / username -> basename only."""
    return os.path.basename(os.path.normpath(path)) or path


def _store_paths(root: str) -> list[str]:
    """The top-level store plus every Sources/<UUID> store, in a stable order."""
    base = Path(os.path.expanduser(root))
    paths: list[str] = []
    top = base / _STORE_FILENAME
    if top.exists():
        paths.append(str(top))
    paths.extend(sorted(glob.glob(str(base / "Sources" / "*" / _STORE_FILENAME))))
    return paths


def _store_id(root: str, db_path: str) -> str:
    """Stable per-store id: the Sources/<UUID> folder name, 'local' for the
    top-level store, else sha1(abspath). Namespaces source_id so the SAME
    ZUNIQUEID in two stores can never collide."""
    p = Path(db_path).resolve()
    parent = p.parent
    if parent.parent.name == "Sources" and parent.name:
        return parent.name
    base = Path(os.path.expanduser(root)).resolve()
    if parent == base:
        return "local"
    return hashlib.sha1(str(p).encode()).hexdigest()


def _source_id(store_id: str, zuniqueid: str | None, z_pk: int) -> str:
    """Contract: sha1(f"{store_id}:{zuniqueid or ('zpk:'+str(z_pk))}") -> hex(40),
    fits String(128), never an unqualified 'zpk:1'."""
    raw = zuniqueid or f"zpk:{z_pk}"
    return hashlib.sha1(f"{store_id}:{raw}".encode()).hexdigest()


def _private_snapshot(db_path: str) -> tuple[str, str]:
    """Copy the store + its -wal/-shm sidecars into a private temp dir so we read
    a consistent point-in-time image without touching the live store. Returns
    (copied_store_path, tmpdir). Raises PermissionError (EPERM) if FDA is denied —
    shutil.copy2 opens the source, which is where TCC surfaces the denial."""
    tmpdir = tempfile.mkdtemp(prefix="scuffedos_ab_")
    dst = os.path.join(tmpdir, os.path.basename(db_path))
    try:
        shutil.copy2(db_path, dst)                       # EPERM / ENOENT surface here
        for suffix in ("-wal", "-shm"):
            side = db_path + suffix
            if os.path.exists(side):
                try:
                    shutil.copy2(side, dst + suffix)     # sidecars are best-effort
                except OSError:
                    pass
    except Exception:
        # The first copy2 raising (FDA-denied EPERM is the common, long-lived
        # case) must not leak the tmpdir mkdtemp already created: the caller's
        # cleanup never runs because we exit via this exception before ever
        # returning tmpdir. Clean up here, then re-raise unchanged so the
        # caller's ACCESS_DENIED/IO_ERROR classification is unaffected.
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return dst, tmpdir


def _connect_ro(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    con.isolation_level = None                       # we drive the read txn explicitly
    con.execute("PRAGMA query_only=ON")              # belt-and-suspenders: no writes
    con.execute("PRAGMA busy_timeout=5000")          # bounded wait, never hang
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _unwrap_label(raw: str | None) -> str:
    """'_$!<Mobile>!$_' -> 'Mobile'; custom labels pass through unchanged."""
    if not raw:
        return ""
    if raw.startswith("_$!<") and raw.endswith(">!$_"):
        return raw[4:-4]
    return raw


def _thumbnail_bytes(blob, orig_db_path: str) -> bytes | None:
    """Resolve raw image bytes from a ZTHUMBNAILIMAGEDATA blob. Core Data stores
    either the image (optionally with a 1-byte tag prefix) inline, or a filename
    reference into the store's external-data directory. Best-effort: returns None
    on anything unexpected. External refs are read from the REAL store's _SUPPORT
    dir (read-only), not the private snapshot copy, and the filename is guarded
    against path traversal."""
    if not blob:
        return None
    if contact_photos.detect_media_type(blob) is not None:      # some stores keep raw bytes
        return blob
    tag = blob[0]
    if tag == 1:                                                # inline, 1-byte tag prefix
        body = blob[1:]
        return body if contact_photos.detect_media_type(body) is not None else None
    if tag == 2:                                                # external-data filename ref
        name = blob[1:].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        if not name or "/" in name or name.startswith("."):
            return None
        stem = Path(orig_db_path).stem
        support = Path(orig_db_path).parent / f".{stem}_SUPPORT" / "_EXTERNAL_DATA"
        try:
            data = (support / name).read_bytes()
        except OSError:
            return None
        return data if contact_photos.detect_media_type(data) is not None else None
    return None


def _contact_entity(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'ABCDContact'"
    ).fetchone()
    if row is None or row[0] is None:
        raise _UnsupportedSchema("no ABCDContact entity in Z_PRIMARYKEY")
    return int(row[0])


def _require_schema(con: sqlite3.Connection) -> None:
    """Probe the schema for real (this also forces the first read of the file, so
    a corrupt/non-sqlite store raises sqlite3.DatabaseError here -> IO_ERROR)."""
    present = _tables(con)
    missing = [t for t in _REQUIRED_TABLES if t not in present]
    if missing:
        raise _UnsupportedSchema(f"missing required table(s): {', '.join(missing)}")
    rec_cols = _columns(con, "ZABCDRECORD")
    if "Z_PK" not in rec_cols or "Z_ENT" not in rec_cols:
        raise _UnsupportedSchema("ZABCDRECORD lacks Z_PK/Z_ENT")


def _extract_people(con: sqlite3.Connection, db_path: str, store_id: str,
                    region: str, photos_dir: str | None) -> list[NormalizedPerson]:
    """Build NormalizedPerson rows from one already-validated store connection.
    `region`/`db_path`/`photos_dir` are threaded for the photo pass wired in
    Task 5; identity canonicalization stays in the store (contract). Task 4 leaves
    every person photoless."""
    ent = _contact_entity(con)
    rec_cols = _columns(con, "ZABCDRECORD")
    select_cols = ["Z_PK"] + [c for c in _RECORD_OPTIONAL if c in rec_cols]
    idx = {name: i for i, name in enumerate(select_cols)}

    tables = _tables(con)
    has_phone = "ZABCDPHONENUMBER" in tables
    has_email = "ZABCDEMAILADDRESS" in tables

    rows = con.execute(
        f"SELECT {', '.join(select_cols)} FROM ZABCDRECORD WHERE Z_ENT = ?",
        (ent,),
    ).fetchall()

    people: list[NormalizedPerson] = []
    for row in rows:
        def col(name):
            return row[idx[name]] if name in idx else None

        z_pk = row[0]
        uid = col("ZUNIQUEID")
        src_id = _source_id(store_id, uid, z_pk)
        first = col("ZFIRSTNAME") or ""
        last = col("ZLASTNAME") or ""
        nick = col("ZNICKNAME") or ""
        org = col("ZORGANIZATION") or ""
        job = col("ZJOBTITLE") or ""
        is_company = bool((col("ZDISPLAYFLAGS") or 0) & 1)

        phones = []
        if has_phone:
            for (num, label) in con.execute(
                "SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER "
                "WHERE ZOWNER = ? ORDER BY ZORDERINGINDEX", (z_pk,)
            ):
                if num:
                    phones.append({"value": num, "label": _unwrap_label(label)})
        emails = []
        if has_email:
            for (addr, label) in con.execute(
                "SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS "
                "WHERE ZOWNER = ? ORDER BY ZORDERINGINDEX", (z_pk,)
            ):
                if addr:
                    emails.append({"value": addr, "label": _unwrap_label(label)})

        display = (org.strip() if is_company
                   else " ".join(x for x in (first, last) if x).strip())
        display = display or nick or org or (uid or f"zpk:{z_pk}")

        photo_path, has_photo = None, False
        if photos_dir:
            try:
                img = _thumbnail_bytes(col("ZTHUMBNAILIMAGEDATA"), db_path)
                if img is not None:
                    key = contact_photos.store_photo(
                        img, store_id=store_id, source_id=src_id,
                        photos_root=photos_dir)
                    if key:                                     # transient ABSOLUTE path
                        photo_path = os.path.join(os.path.expanduser(photos_dir), key)
                        has_photo = True
            except Exception:                                   # a photo NEVER aborts the read
                logger.warning("contact photo skipped for a record")

        people.append(NormalizedPerson(
            source="macos_contacts",
            source_id=src_id,
            display_name=display,
            first_name=first, last_name=last, nickname=nick,
            organization=org, job_title=job,
            phones=phones, emails=emails,
            photo_path=photo_path, has_photo=has_photo,
            meta={"is_company": is_company, "store_id": store_id,
                  "zuniqueid": uid, "z_pk": z_pk},
        ))
    return people


def _read_store(db_path: str, store_id: str, region: str,
                photos_dir: str | None) -> list[NormalizedPerson]:
    """Read ONE store from a private snapshot. Classifies its failure mode by
    raising an _AccessDenied / _UnsupportedSchema / _IOFailure; never returns raw."""
    try:
        snap_path, tmpdir = _private_snapshot(db_path)
    except PermissionError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            raise _AccessDenied(f"Full Disk Access denied for {_redact(db_path)}") from exc
        raise _IOFailure(f"cannot copy {_redact(db_path)}: {exc.strerror}") from exc
    except OSError as exc:
        raise _IOFailure(f"cannot copy {_redact(db_path)}: {exc.strerror or exc}") from exc

    try:
        try:
            con = _connect_ro(snap_path)
        except sqlite3.DatabaseError as exc:
            raise _IOFailure(f"cannot open {_redact(db_path)}: {exc}") from exc
        try:
            con.execute("BEGIN")                     # one consistent read snapshot
            _require_schema(con)
            return _extract_people(con, db_path, store_id, region, photos_dir)
        except _UnsupportedSchema:
            raise
        except sqlite3.DatabaseError as exc:         # corrupt / not-a-db / image malformed
            raise _IOFailure(f"corrupt store {_redact(db_path)}: {exc}") from exc
        finally:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def read_snapshot(root: str = DEFAULT_ROOT, *, region: str,
                  photos_dir: str | None, enabled: bool = True) -> ContactsSnapshot:
    """Classify + read every AddressBook store under `root`. NEVER raises for
    control flow. See the module docstring for the status matrix."""
    if _FAKE_SNAPSHOT is not None:      # test seam: return the injected snapshot verbatim
        return _FAKE_SNAPSHOT
    if not enabled:
        # Consent gate. The sync engine already short-circuits to a 'disabled'
        # SyncResult before ever calling us; this is defense-in-depth so a direct
        # or mistaken call with consent off does ZERO filesystem/DB work and
        # cannot mutate rows (MISSING_STORE never soft-deletes or marks stale).
        return ContactsSnapshot(status=SnapshotStatus.MISSING_STORE, people=[],
                                error="contacts import disabled")

    paths = _store_paths(root)
    if not paths:
        return ContactsSnapshot(status=SnapshotStatus.MISSING_STORE, people=[],
                                error=f"no AddressBook store under {_redact(root)}")

    people: list[NormalizedPerson] = []
    store_ids: list[str] = []
    stores_total = len(paths)
    denied = unsupported = io_error = False
    first_error: str | None = None

    for path in paths:
        sid = _store_id(root, path)
        try:
            batch = _read_store(path, sid, region, photos_dir)
        except _AccessDenied as exc:
            denied = True
            first_error = first_error or str(exc)
            continue
        except _UnsupportedSchema as exc:
            unsupported = True
            first_error = first_error or str(exc)
            continue
        except _IOFailure as exc:
            io_error = True
            first_error = first_error or str(exc)
            continue
        except Exception as exc:                     # a surprise must never propagate
            io_error = True
            first_error = first_error or f"unexpected read error: {exc}"
            logger.exception("unexpected error reading a contacts store")
            continue
        people.extend(batch)
        store_ids.append(sid)

    stores_read = len(store_ids)

    if stores_read == 0:
        # Nothing read successfully: pick the most actionable failure.
        if denied:
            status = SnapshotStatus.ACCESS_DENIED
        elif unsupported:
            status = SnapshotStatus.UNSUPPORTED_SCHEMA
        elif io_error:
            status = SnapshotStatus.IO_ERROR
        else:
            status = SnapshotStatus.MISSING_STORE
        return ContactsSnapshot(status=status, people=[], stores_total=stores_total,
                                stores_read=0, store_ids=[], error=first_error)

    if stores_read < stores_total:
        # Some stores read, some failed -> reconciliation would soft-delete the
        # contacts that live in the unread store(s). Mark PARTIAL_READ.
        return ContactsSnapshot(status=SnapshotStatus.PARTIAL_READ, people=people,
                                stores_total=stores_total, stores_read=stores_read,
                                store_ids=store_ids, error=first_error)

    status = (SnapshotStatus.COMPLETE_NONEMPTY if people
              else SnapshotStatus.COMPLETE_EMPTY)
    return ContactsSnapshot(status=status, people=people, stores_total=stores_total,
                            stores_read=stores_read, store_ids=store_ids, error=None)


def probe_access(root: str = DEFAULT_ROOT) -> str:
    """'granted' | 'denied' | 'unknown' — a permission probe only, never raises.
    Attempts a REAL open (contract: never trust os.access()): an EPERM/EACCES from
    TCC means Full Disk Access is missing. Test seam: a configured fake_snapshot
    derives access from its status; a configured non-darwin platform -> 'denied'."""
    if _FAKE_SNAPSHOT is not None:
        st = _FAKE_SNAPSHOT.status
        if st in (SnapshotStatus.COMPLETE_NONEMPTY, SnapshotStatus.COMPLETE_EMPTY):
            return "granted"                         # a COMPLETE fake read means access
        if st == SnapshotStatus.ACCESS_DENIED:
            return "denied"
        return "unknown"
    if _PLATFORM_OVERRIDE is not None and _PLATFORM_OVERRIDE != "darwin":
        return "denied"                              # injected non-darwin -> deterministic
    if not _is_darwin():
        return "unknown"                             # can't determine off macOS
    paths = _store_paths(root)
    if not paths:
        return "denied"
    try:
        with open(paths[0], "rb") as fh:
            fh.read(16)
    except PermissionError as exc:
        return "denied" if exc.errno in (errno.EPERM, errno.EACCES) else "unknown"
    except OSError:
        return "unknown"
    return "granted"
