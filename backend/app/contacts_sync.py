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

# Upper bound on run_loop's delay before its FIRST tick (the delay is
# min(this, contacts_sync_seconds)). A desktop app that is open for minutes a
# day would never reach a first pass gated on the full 6h interval, while a
# minute still keeps app startup and every TestClient lifespan free of
# AddressBook reads.
FIRST_TICK_DELAY_SECONDS = 60

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
    - non-macOS host         -> status='unsupported', zero reads, no state write
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

    # 2) Platform gate. There is no AddressBook on a non-macOS backend host, so
    #    read_snapshot() would classify MISSING_STORE and the store would record
    #    status='error' on every interval — an alarm about an absent feature.
    #    Report it as what it is, and touch no state.
    if not macos_contacts.is_supported():
        return SyncResult(status="unsupported", access="unknown")

    # 3) Read the local AddressBook. read_snapshot() classifies rather than
    #    raising; guard anyway so a reader bug can never crash the loop.
    region = state.get("normalization_region") or settings.contacts_default_region
    try:
        snapshot = macos_contacts.read_snapshot(
            settings.addressbook_root,
            region=region,
            photos_dir=settings.contacts_photos_root(),
            enabled=True,
        )
    except Exception:
        logger.exception("contacts sync: read_snapshot crashed")
        snapshot = ContactsSnapshot(status=SnapshotStatus.IO_ERROR, people=[],
                                    error="reader failed")

    # 4) Apply. The store serializes this under its process + advisory lock, so
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
    """Background loop. ALWAYS started (there is no env kill-switch — the packaged
    app has no way to set one); the ONLY gate is per-tick consent, since tick()
    no-ops without ever touching the AddressBook while contacts_sync_state.enabled
    is False. Sleeps BEFORE the first tick — the enable endpoint already kicks the
    first sync, and this keeps app startup (and every TestClient lifespan) free of
    AddressBook reads — but that first delay is capped at FIRST_TICK_DELAY_SECONDS
    so a session shorter than one interval still gets a pass. Every later tick is
    a full contacts_sync_seconds apart."""
    logger.info("contacts sync loop started (every %ss)", settings.contacts_sync_seconds)
    delay = min(FIRST_TICK_DELAY_SECONDS, settings.contacts_sync_seconds)
    while True:
        await asyncio.sleep(delay)
        delay = settings.contacts_sync_seconds
        try:
            result = await asyncio.to_thread(tick)
            if result.status == "ok" and (result.imported or result.updated or result.removed):
                logger.info("contacts sync: +%d ~%d -%d",
                            result.imported, result.updated, result.removed)
        except Exception:
            logger.exception("contacts sync tick failed")
