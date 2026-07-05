"""Moodle sync engine (M6) — a background tick + on-demand trigger.

A near-clone of app/email_sync.py: a plain asyncio loop (started from the app
lifespan, guarded by settings.moodle_sync_enabled) wakes every
settings.moodle_sync_seconds, and for each connected Moodle provider fetches a
MoodleSnapshot since its cursor and upserts every course / deadline /
assignment / grade / announcement / notification into the moodle_* tables,
then advances the cursor.

Moodle providers are the registry entries that implement fetch_school_snapshot
(i.e. MoodleProvider). The email_sync hasattr(p, 'fetch_messages') filter is
the model — a fitness pull provider and GoogleProvider both lack
fetch_school_snapshot, so they are skipped here, exactly as MoodleProvider (no
fetch_messages) is skipped by email_sync.

Reads never depend on a live Moodle call — every /api/moodle/* GET is served
from the DB; only connect (token validate) and this sync reach Moodle. A
failed sync just logs and retries next tick; the tick NEVER crashes. Auth
failures (MoodleAuthError, a subclass of AuthError) flip the account to
needs_reauth. Test seam: configure(fake) installs an object with a .tick()
that tick() delegates to; configure(None)/"unset" run the real pass (matching
email_sync). Providers are swapped via providers.configure(...).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import providers
from .config import settings
from .providers.base import AuthError
from .store import store

logger = logging.getLogger("scuffed_os.moodle_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Test seam for mocking tick(); install a fake with .tick() to delegate to
    it. None or "unset" run the real tick. Does NOT gate run_loop (the lifespan,
    gated by settings.moodle_sync_enabled, controls that). The provider registry
    is swapped separately via providers.configure(...)."""
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _moodle_providers() -> list:
    """Registry entries that implement fetch_school_snapshot (Moodle domain)."""
    return [p for p in providers.all_providers() if hasattr(p, "fetch_school_snapshot")]


def _load_and_inject_tokens(provider, now: datetime) -> bool:
    """Load stored tokens, refresh if within the skew of expiry (persist the
    rotation), and inject them so the authed Moodle calls carry the wstoken.
    Returns False if no tokens are stored. Raises AuthError on a refresh failure
    so the caller flips needs_reauth. Byte-identical to
    email_sync._load_and_inject_tokens — for Moodle the refresh is a passthrough
    (no refresh endpoint; tokens.expires_at is always None), so the refresh
    branch never fires and no rotation is actually persisted."""
    tokens = store.get_provider_tokens(provider.name)
    if tokens is None:
        return False
    refresh = getattr(provider, "refresh", None)
    if (
        tokens.expires_at is not None
        and refresh is not None
        and now >= tokens.expires_at - timedelta(seconds=60)
    ):
        tokens = refresh(tokens)                              # may raise AuthError
        store.upsert_provider_account(provider.name, tokens)  # persist rotation
    set_tokens = getattr(provider, "set_tokens", None)
    if set_tokens is not None:
        set_tokens(tokens)
    return True


def _sync_provider(provider, now: datetime) -> int:
    """One Moodle provider's pass. Returns records upserted. Raises AuthError on
    an auth/refresh failure so the caller flips needs_reauth; other errors
    propagate so the caller can log-and-continue."""
    acct = next(
        (a for a in store.list_provider_accounts() if a["provider"] == provider.name),
        None,
    )
    if acct is None or acct["status"] != "connected":
        return 0
    if not _load_and_inject_tokens(provider, now):
        return 0

    since = acct["last_sync_at"]  # None on a fresh account -> full backfill
    snap = provider.fetch_school_snapshot(since)
    count = 0
    for course in snap.courses:
        store.upsert_moodle_course(course)
        count += 1
    for deadline in snap.deadlines:
        store.upsert_moodle_deadline(deadline)
        count += 1
    for assignment in snap.assignments:
        store.upsert_moodle_assignment(assignment)
        count += 1
    for grade in snap.grades:
        store.upsert_moodle_grade(grade)
        count += 1
    for announcement in snap.announcements:
        store.upsert_moodle_announcement(announcement)
        count += 1
    for notification in snap.notifications:
        store.upsert_moodle_notification(notification)
        count += 1
    store.set_provider_synced(provider.name, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every connected Moodle provider. Returns records
    upserted. Safe to call any time — per-account errors are caught and logged
    so the tick never crashes; auth failures flip the account to needs_reauth.
    Returns 0 when no database is configured (RuntimeError caught).

    Test seam: if configure() installed an object with a .tick(), that is called
    instead of the real pass.
    """
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]
    now = now or _utcnow()
    try:
        provider_list = _moodle_providers()
    except RuntimeError:  # no DATABASE_URL behind the registry — nothing to do
        return 0
    total = 0
    for provider in provider_list:
        try:
            total += _sync_provider(provider, now)
        except AuthError:
            logger.warning("%s needs re-auth; flipping status", provider.name)
            try:
                store.set_provider_status(provider.name, "needs_reauth")
            except Exception:
                logger.exception("could not flip %s to needs_reauth", provider.name)
        except RuntimeError as exc:
            if "DATABASE_URL" in str(exc):
                return total
            logger.exception("moodle sync failed for %s", provider.name)
        except Exception:
            logger.exception("moodle sync failed for %s", provider.name)
    return total


async def trigger() -> int:
    """Run one sync pass off the event loop and return its count. Awaited by the
    OAuth/connect flow (via on_connected) and by POST /api/moodle/sync. Errors are
    already swallowed inside tick, so this never raises for provider problems."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """The lifespan background task; ticks forever until cancelled."""
    logger.info("moodle sync loop started (every %ss)", settings.moodle_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d moodle record(s)", synced)
        except Exception:
            logger.exception("moodle sync tick failed")
        await asyncio.sleep(settings.moodle_sync_seconds)
