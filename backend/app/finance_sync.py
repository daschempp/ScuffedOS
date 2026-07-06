"""Finance sync engine (M7) — a background tick + on-demand trigger.

Clone of moodle_sync.py, but multi-Item: instead of looping providers, it loops
store.list_finance_items() and, per Item, injects that Item's access_token and
branches on its `products`: 'transactions' -> paged /transactions/sync (advance
the cursor); 'investments' -> holdings; accounts refresh always. A PlaidAuthError
(subclass of AuthError) on one Item flips only that Item to needs_reauth. Reads
never depend on a live Plaid call; only connect and this sync reach Plaid. The
tick NEVER crashes. Test seam: configure(fake) installs an object with .tick().
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from . import providers
from .config import settings
from .providers.base import AuthError
from .store import store

logger = logging.getLogger("scuffed_os.finance_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Test seam for mocking tick(); install a fake with .tick(). None/"unset"
    run the real tick. run_loop is gated separately by settings.finance_sync_enabled."""
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sync_item(provider, item: dict, now: datetime) -> int:
    """One Item's pass. Raises AuthError so the caller flips needs_reauth."""
    if item.get("status") != "active":
        return 0
    item_id = item["item_id"]
    access_token = store.get_finance_item_token(item_id)
    if not access_token:
        return 0
    products = item.get("products") or []
    count = 0
    for acc in provider.get_accounts(access_token):
        store.upsert_finance_account(acc)
        count += 1
    if "transactions" in products:
        cursor = store.get_finance_item_cursor(item_id)
        while True:
            delta = provider.sync_transactions(access_token, cursor)
            # Plaid /transactions/sync objects carry no item_id — stamp it so the
            # disconnect cascade (delete_finance_item deletes txns by item_id) works.
            for t in delta.added + delta.modified:
                t.item_id = item_id
            count += store.apply_transaction_delta(delta)
            cursor = delta.next_cursor
            store.set_finance_item_cursor(item_id, cursor)
            if not delta.has_more:
                break
    if "investments" in products:
        accts, secs, holds = provider.get_holdings(access_token)
        for a in accts:
            store.upsert_finance_account(a)
            count += 1
        for sec in secs:
            store.upsert_finance_security(sec)
            count += 1
        for h in holds:
            store.upsert_finance_holding(h)
            count += 1
    store.set_finance_item_synced(item_id, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every linked Item. Never crashes; auth failures flip
    that Item to needs_reauth. Returns rows upserted. Test seam via configure()."""
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]
    now = now or _utcnow()
    provider = providers.get("plaid")
    if provider is None:
        return 0
    try:
        items = store.list_finance_items()
    except RuntimeError:  # no DATABASE_URL — nothing to do
        return 0
    total = 0
    for item in items:
        try:
            total += _sync_item(provider, item, now)
        except AuthError:
            logger.warning("plaid item %s needs re-auth; flipping status", item["item_id"])
            try:
                store.set_finance_item_status(item["item_id"], "needs_reauth")
            except Exception:
                logger.exception("could not flip %s to needs_reauth", item["item_id"])
        except RuntimeError as exc:
            if "DATABASE_URL" in str(exc):
                return total
            logger.exception("finance sync failed for %s", item["item_id"])
        except Exception:
            logger.exception("finance sync failed for %s", item["item_id"])
    return total


async def trigger() -> int:
    """One sync pass off the event loop. Awaited by connect + POST /api/finance/sync."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    logger.info("finance sync loop started (every %ss)", settings.finance_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d finance record(s)", synced)
        except Exception:
            logger.exception("finance sync tick failed")
        await asyncio.sleep(settings.finance_sync_seconds)
