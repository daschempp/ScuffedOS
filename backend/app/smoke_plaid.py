"""End-to-end smoke test for the live Plaid read pipeline (M7). Drives the REAL
PlaidProvider against real Plaid using the access_tokens stored in finance_items,
then exercises accounts / transactions / holdings. Makes NO writes — Plaid slice-1
is read-only. Run by hand (NOT in CI): python -m app.smoke_plaid

Exit: 0 all legs passed · 1 pipeline failure · 2 no Item linked yet (link a bank
via the Finance screen's Hosted Link first)."""
from __future__ import annotations

import logging
import sys

from . import providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help() -> None:
    print("\nNo Plaid Item linked yet. To connect end-to-end:")
    print("  1. Set PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV in backend/.env.")
    print("  2. Start the backend + frontend, open the Finance screen.")
    print("  3. Click 'Connect a bank' (or Coinbase), finish in the Plaid tab, then 'Finish linking'.")
    print("  4. Re-run `python -m app.smoke_plaid`.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS -- live Plaid read pipeline smoke test")
    print(f"  owner={settings.owner!r}  plaid_env={settings.plaid_env!r}")

    if not r.check(bool(settings.database_url), "DATABASE_URL configured"):
        return 1
    if not r.check(bool(settings.plaid_client_id and settings.plaid_secret),
                   "PLAID_CLIENT_ID / PLAID_SECRET configured"):
        return 1
    provider = providers.get("plaid")
    if not r.check(provider is not None, "Plaid provider registered"):
        return 1

    items = store.list_finance_items()
    if not items:
        r.check(False, "at least one Item linked", "not connected -- see below")
        _print_connect_help()
        return 2
    r.check(True, "Items linked", f"{len(items)}")

    for it in items:
        item_id = it["item_id"]
        print(f"\nItem {item_id} ({it['institution_name']}) products={it['products']}:")
        token = store.get_finance_item_token(item_id)
        if not r.check(bool(token), "access_token present server-side"):
            continue
        try:
            accounts = provider.get_accounts(token)
            r.check(True, "accounts fetched", f"{len(accounts)}")
            for a in accounts[:6]:
                print(f"        - {a.name!r} ({a.type}/{a.subtype}) bal={a.current_balance}")
            if "transactions" in (it["products"] or []):
                delta = provider.sync_transactions(token, store.get_finance_item_cursor(item_id))
                r.check(True, "transactions/sync page", f"+{len(delta.added)} ~{len(delta.modified)} -{len(delta.removed)}")
            if "investments" in (it["products"] or []):
                accts, secs, holds = provider.get_holdings(token)
                r.check(True, "holdings fetched", f"{len(holds)} across {len(secs)} securities")
                for h, s in [(h, next((x for x in secs if x.source_id == h.security_id), None)) for h in holds[:6]]:
                    print(f"        - {(s.ticker_symbol if s else h.security_id)!r} qty={h.quantity} value={h.institution_value}")
        except Exception as exc:  # a live call blew up -- report, don't traceback-dump
            r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES -- see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
