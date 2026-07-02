"""Email sync engine (M5) — a background tick + on-demand trigger.

A near-clone of app/fitness_sync.py: a plain asyncio loop (started from the app
lifespan, guarded by settings.email_sync_enabled) wakes every
settings.email_sync_seconds, and for each connected email provider fetches the
Gmail INBOX since its cursor, triages each NEW message, upserts it into the
`emails` table, and advances the cursor.

Email providers are the registry entries that implement fetch_messages (i.e.
GoogleProvider). The fitness pull_providers() filter is deliberately NOT reused
— a fitness pull provider has no fetch_messages and is skipped here, exactly as
GoogleProvider (no `kind`) is skipped by the fitness tick.

Reads never depend on a live Gmail call for the inbox list (served from the
`emails` table); only the message body is fetched live for the reading pane.
A failed sync just logs and retries next tick; the tick never crashes. Auth
failures flip the account to needs_reauth. Test seam: configure(fake) installs
an object with a .tick() that tick() delegates to; configure(None)/"unset" run
the real pass (matching fitness_sync). Providers are swapped via
providers.configure(...).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import email_triage, providers
from .config import settings
from .providers.base import AuthError
from .store import store

logger = logging.getLogger("scuffed_os.email_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Test seam for mocking tick(); install a fake with .tick() to delegate to
    it. None or "unset" run the real tick. Does NOT gate run_loop (the lifespan,
    gated by settings.email_sync_enabled, controls that). The provider registry
    is swapped separately via providers.configure(...)."""
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _email_providers() -> list:
    """Registry entries that implement fetch_messages (email domain)."""
    return [p for p in providers.all_providers() if hasattr(p, "fetch_messages")]


def _load_and_inject_tokens(provider, now: datetime) -> bool:
    """Load stored tokens, refresh if within the skew of expiry (persist the
    rotation), and inject them so the authed Gmail calls carry a Bearer token.
    Returns False if no tokens are stored. Raises AuthError on a refresh failure
    so the caller flips needs_reauth. Mirrors fitness_sync._load_and_inject_tokens."""
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
    """One email provider's pass. Returns messages upserted. Raises AuthError on
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

    since = acct["last_sync_at"]  # None on a fresh account -> full backfill via list
    count = 0
    for email in provider.fetch_messages(since):
        if store.email_triaged(email.source, email.source_id):
            continue
        category, summary = email_triage.triage(
            email.subject, email.from_name, email.from_email,
            email.snippet, email.body_excerpt,
        )
        store.upsert_email(email, category, summary)
        count += 1
    store.set_provider_synced(provider.name, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every connected email provider. Returns messages
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
        provider_list = _email_providers()
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
            logger.exception("email sync failed for %s", provider.name)
        except Exception:
            logger.exception("email sync failed for %s", provider.name)
    return total


async def trigger() -> int:
    """Run one sync pass off the event loop and return its count. Awaited by the
    OAuth callback (via on_connected) and by POST /api/email/sync. Errors are
    already swallowed inside tick, so this never raises for provider problems."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """The lifespan background task; ticks forever until cancelled."""
    logger.info("email sync loop started (every %ss)", settings.email_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d email(s)", synced)
        except Exception:
            logger.exception("email sync tick failed")
        await asyncio.sleep(settings.email_sync_seconds)
