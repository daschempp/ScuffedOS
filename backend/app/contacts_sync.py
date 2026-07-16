"""Contacts sync engine (M10 s1) — a token-less, consent-gated pass.

Reads the local macOS AddressBook via providers.macos_contacts.read_snapshot()
(no network, no OAuth, no cursor) and hands the resulting ContactsSnapshot to
store.apply_contacts_snapshot(), which does the whole transactional write
(upsert + handle re-index + reconcile) under its process + advisory lock. This
module only orchestrates; the store owns locking and reconciliation safety.

Invariants:
  * Consent-gated: while contacts_sync_state.enabled is False, tick() is a pure
    no-op — it reads NOTHING from the AddressBook and returns status='disabled'.
  * Never crashes: every failure is caught and turned into a SyncResult.
  * An unreachable / erroring PostgreSQL server (structured contact data is
    persisted to the configured database, which may be remote/self-hosted) is a
    FAILED sync (status='error') — NEVER an 'empty' one. A DB blip must not look
    like "every contact vanished".

Test seam: configure(fake) installs an object whose .tick() this delegates to;
configure(None)/"unset" runs the real pass.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .providers import macos_contacts
from .providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from .store import SyncResult, store

logger = logging.getLogger("scuffed_os.contacts_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _access_for(snapshot: ContactsSnapshot) -> str:
    if snapshot.status in (SnapshotStatus.COMPLETE_NONEMPTY, SnapshotStatus.COMPLETE_EMPTY):
        return "granted"
    if snapshot.status == SnapshotStatus.ACCESS_DENIED:
        return "denied"
    return "unknown"


def tick(now: datetime | None = None) -> SyncResult:
    """One contacts pass. Returns a SyncResult; never raises.

    - consent off            -> status='disabled', zero reads
    - snapshot not COMPLETE_* -> the store records the status; no row writes
    - DB unreachable          -> status='error' (never 'empty')
    """
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]

    now = now or _utcnow()

    # 1) Consent gate. A DB failure reading the flag is itself a failed sync.
    try:
        state = store.get_contacts_state()
    except Exception:
        logger.exception("contacts sync: could not read consent state (database unavailable?)")
        return SyncResult(status="error", access="unknown",
                          last_error="database unavailable")
    if not state.get("enabled"):
        return SyncResult(status="disabled", access=state.get("access", "unknown"),
                          last_sync_at=state.get("last_sync_at"))

    # 2) Read the local AddressBook. read_snapshot() classifies rather than
    #    raising; guard anyway so a reader bug can never crash the loop.
    region = state.get("normalization_region") or settings.contacts_default_region
    try:
        snapshot = macos_contacts.read_snapshot(
            getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT),
            region=region,
            photos_dir=settings.contacts_photos_root(),
            enabled=True,
        )
    except Exception:
        logger.exception("contacts sync: read_snapshot crashed")
        snapshot = ContactsSnapshot(status=SnapshotStatus.IO_ERROR, people=[],
                                    error="reader failed")

    # 3) Apply. The store serializes this under its process + advisory lock, so
    #    manual /sync and the background loop can never interleave a write.
    try:
        return store.apply_contacts_snapshot(snapshot, now)
    except Exception:
        logger.exception("contacts sync: apply_contacts_snapshot failed (database unavailable?)")
        return SyncResult(status="error", access=_access_for(snapshot),
                          last_error="database unavailable during sync")


async def trigger() -> SyncResult:
    """Run one pass off the event loop. Awaited by POST /api/people/sync and by
    the enable endpoint's first-sync kick."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """Background loop. Gated by settings.contacts_sync_enabled (started only when
    true) AND, per tick, by contacts_sync_state.enabled (tick() no-ops when off)."""
    logger.info("contacts sync loop started (every %ss)", settings.contacts_sync_seconds)
    while True:
        try:
            if settings.contacts_sync_enabled:
                result = await asyncio.to_thread(tick)
                if result.status == "ok" and (result.imported or result.updated or result.removed):
                    logger.info("contacts sync: +%d ~%d -%d",
                                result.imported, result.updated, result.removed)
        except Exception:
            logger.exception("contacts sync tick failed")
        await asyncio.sleep(settings.contacts_sync_seconds)
