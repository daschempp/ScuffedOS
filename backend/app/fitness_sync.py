"""Fitness sync engine (M4) — a background tick + on-demand trigger.

A near-clone of `reminders.py`: a plain asyncio loop (started from the app
lifespan, guarded by `fitness_sync_enabled`) wakes every
`fitness_sync_seconds`, pulls each connected pull-provider since its cursor,
maps the results into the normalized tables, and advances the cursor. The
catch-up is implicit — anything that arrived while the laptop slept lands on
the next tick.

Reads never depend on a live WHOOP call (the screen reads the normalized
tables), so a failed sync just logs and retries next tick; the tick never
crashes. Auth failures flip the provider to `needs_reauth`. The background
`run_loop()` is gated ONLY by the lifespan (which starts it when
`settings.fitness_sync_enabled` is true); `configure()` is a vestigial test
seam that does not gate the loop. Providers are swapped via
`providers.configure(...)`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import providers
from .config import settings
from .providers.base import AuthError, NormalizedSnapshot
from .store import store

logger = logging.getLogger("scuffed_os.fitness_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Vestigial test seam consumed by conftest's no_external_services fixture.

    Does NOT gate run_loop; the lifespan (gated by settings.fitness_sync_enabled)
    is the sole controller. The provider *registry* is swapped separately via
    providers.configure(...).
    """
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _merge_snapshot(into: NormalizedSnapshot, other: NormalizedSnapshot) -> None:
    """Fold `other`'s set fields onto `into` (non-None wins, existing kept).

    recovery and sleep arrive as separate NormalizedSnapshot lists keyed by
    day; the same calendar day must become one row before upsert.
    """
    for f in ("recovery_pct", "day_strain", "sleep_quality_pct", "hrv_ms",
              "resting_hr", "respiratory_rate", "sleep_hours"):
        val = getattr(other, f)
        if val is not None and getattr(into, f) is None:
            setattr(into, f, val)
    merged_metrics = {**other.metrics_json, **into.metrics_json}
    into.metrics_json = merged_metrics


def _merge_by_day(*lists: list[NormalizedSnapshot]) -> list[NormalizedSnapshot]:
    by_day: dict = {}
    for snaps in lists:
        for snap in snaps:
            key = snap.day
            if key in by_day:
                _merge_snapshot(by_day[key], snap)
            else:
                by_day[key] = snap
    return list(by_day.values())


def _load_and_inject_tokens(provider, now: datetime) -> bool:
    """Load the provider's stored tokens, refresh if expired (persisting the
    rotated tokens back), and inject them into the provider so its authed
    fetch_* calls carry a Bearer token. Returns False if no tokens are stored
    (nothing to sync). Raises AuthError on a refresh failure so the caller
    flips needs_reauth. Without this every fetch_* runs with an empty Bearer
    token and 401s — the bug FakeProvider hides because it ignores tokens."""
    tokens = store.get_provider_tokens(provider.name)
    if tokens is None:
        return False
    # Refresh proactively when within ~the skew of expiry. The provider's
    # refresh raises AuthError on failure (propagated to tick).
    refresh = getattr(provider, "refresh", None)
    if (
        tokens.expires_at is not None
        and refresh is not None
        and now >= tokens.expires_at - timedelta(seconds=60)
    ):
        tokens = refresh(tokens)                      # may raise AuthError
        store.upsert_provider_account(provider.name, tokens)  # persist rotation
    set_tokens = getattr(provider, "set_tokens", None)
    if set_tokens is not None:
        set_tokens(tokens)                            # inject for the authed fetch
    return True


def _sync_provider(provider, now: datetime) -> int:
    """One provider's pass. Returns records upserted. Raises AuthError on an
    auth/refresh failure so the caller flips needs_reauth; raises other errors
    so the caller can log-and-continue."""
    acct = next(
        (a for a in store.list_provider_accounts() if a["provider"] == provider.name),
        None,
    )
    if acct is None or acct["status"] != "connected":
        return 0

    # Load + refresh + inject tokens before any authed fetch. No stored tokens
    # (shouldn't happen for a connected account) → nothing to sync.
    if not _load_and_inject_tokens(provider, now):
        return 0

    since = acct["last_sync_at"]
    if since is None:
        since = now - timedelta(days=settings.whoop_backfill_days)

    recovery = provider.fetch_recovery(since)
    sleep = provider.fetch_sleep(since)
    workouts = provider.fetch_workouts(since)

    count = 0
    for snap in _merge_by_day(recovery, sleep):
        store.upsert_snapshot(snap)
        count += 1
    for w in workouts:
        store.upsert_workout(w)  # runs the workout->habit auto-complete
        count += 1

    store.set_provider_synced(provider.name, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every connected pull-provider. Returns how many
    snapshot/workout records were upserted. Safe to call any time — per-provider
    errors are caught and logged so the tick never crashes; auth failures flip
    the provider to needs_reauth. Returns 0 when no database is configured
    (RuntimeError caught, like reminders.tick)."""
    now = now or _utcnow()
    try:
        provider_list = providers.pull_providers()
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
            # No DATABASE_URL surfaced mid-pass (e.g. list_provider_accounts) —
            # treat the whole pass as a no-op, like reminders.tick.
            if "DATABASE_URL" in str(exc):
                return total
            logger.exception("sync failed for %s", provider.name)
        except Exception:
            logger.exception("sync failed for %s", provider.name)
    return total


async def trigger() -> int:
    """Run one sync pass off the event loop and return its count.

    Awaited by the OAuth callback (immediate post-connect sync + backfill)
    and by POST /api/fitness/sync. Errors are already swallowed inside tick,
    so this never raises for provider problems.
    """
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """The lifespan background task; ticks forever until cancelled."""
    logger.info("fitness sync loop started (every %ss)", settings.fitness_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d fitness record(s)", synced)
        except Exception:
            logger.exception("fitness sync tick failed")
        await asyncio.sleep(settings.fitness_sync_seconds)
