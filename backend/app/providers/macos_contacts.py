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
