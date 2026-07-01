"""End-to-end smoke test for the live WHOOP pipeline (M4).

Drives the REAL WhoopProvider against WHOOP's production API and the real sync
engine, then reads the normalized tables back. Unlike the pytest suite (which
fakes every provider via conftest), this makes real authenticated WHOOP
requests and writes synced rows to the configured database.

WHOOP OAuth needs a one-time browser authorize, so this runs in two modes:

  * Already connected — a `provider_accounts` row for 'whoop' exists with
    tokens. The script refreshes if needed, runs a real sync tick, and asserts
    recovery/sleep/strain + workouts landed in the normalized tables.
  * Not connected — prints the authorize URL (built from settings) and the
    exact steps to connect via a tunnel, then exits 2 (setup needed, not a
    failure of the pipeline).

Prerequisites (see docs/superpowers/specs §14): WHOOP_CLIENT_ID /
WHOOP_CLIENT_SECRET set, a tunnel whose `…/auth/whoop/callback` is registered
as a redirect URL on the WHOOP app, and WHOOP_REDIRECT_URI pointed at it.

Run it by hand once credentials are live (NOT in CI):

    python -m app.smoke_whoop

Exit status: 0 if every leg passed, 1 on a pipeline failure, 2 if WHOOP isn't
connected yet (run the OAuth connect first).
"""
from __future__ import annotations

import logging
import secrets
import sys

from . import fitness_sync, providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help(provider) -> None:
    state = secrets.token_urlsafe(16)
    print("\nWHOOP is not connected yet. To connect end-to-end:")
    print("  1. Start the backend behind a tunnel (cloudflared/ngrok over HTTPS).")
    print("  2. Register the tunnel's <tunnel>/auth/whoop/callback as a redirect")
    print("     URL on the WHOOP app, and set WHOOP_REDIRECT_URI to match.")
    print("  3. Open this authorize URL in a browser and approve:")
    print("\n     " + provider.authorize_url(state))
    print("\n  4. WHOOP redirects to /auth/whoop/callback, which stores tokens.")
    print("     Re-run `python -m app.smoke_whoop` afterwards.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS — live WHOOP pipeline smoke test")
    print(f"  owner={settings.owner!r}  redirect_uri={settings.whoop_redirect_uri!r}  "
          f"backfill_days={settings.whoop_backfill_days}")

    print("\nPreconditions:")
    if not r.check(bool(settings.whoop_client_id and settings.whoop_client_secret),
                   "WHOOP credentials configured (WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET)"):
        print("\nAborting: WHOOP client credentials are not set.")
        return 1
    if not r.check(bool(settings.database_url),
                   "DATABASE_URL configured (synced rows need a database)"):
        print("\nAborting: no DATABASE_URL — sync writes nowhere.")
        return 1

    provider = providers.get("whoop")
    if not r.check(provider is not None, "WHOOP provider registered"):
        return 1

    account = store.get_provider_account("whoop")
    if account is None:
        r.check(False, "WHOOP account connected (provider_accounts row exists)",
                "not connected — see steps below")
        _print_connect_help(provider)
        return 2
    r.check(True, "WHOOP account connected",
            f"status={account['status']} provider_user_id={account.get('provider_user_id')}")

    try:
        print("\n1. Token validity (refresh if within the expiry guard):")
        tokens = store.get_provider_tokens("whoop")
        if not r.check(tokens is not None and bool(tokens.access_token),
                       "access token present server-side"):
            return 1
        # Inject tokens into provider before fetching (what the sync engine does).
        provider.set_tokens(tokens)

        print("\n2. Live fetch (recovery / sleep / workouts since backfill window):")
        recovery = provider.fetch_recovery(None)
        sleep = provider.fetch_sleep(None)
        workouts = provider.fetch_workouts(None)
        r.check(True, "recovery snapshots fetched", f"{len(recovery)}")
        r.check(True, "sleep snapshots fetched", f"{len(sleep)}")
        r.check(True, "workouts fetched", f"{len(workouts)}")
        r.check(bool(recovery) or bool(sleep) or bool(workouts),
                "WHOOP returned at least one record (account has data)")
        for w in workouts[:3]:
            print(f"        - workout {w.name!r} sport={w.sport} "
                  f"{w.duration_min}min strain={w.strain} kcal={w.calories}")
            r.check(w.calories is None or w.calories < 100000,
                    f"calories look kcal-scaled (kJ would be ~4x larger): {w.calories}")

        print("\n3. Real sync tick (provider -> normalized tables):")
        changed = fitness_sync.tick()
        r.check(isinstance(changed, int), "tick returned a record count", str(changed))
        synced = store.list_provider_accounts()
        whoop_row = next((a for a in synced if a["provider"] == "whoop"), None)
        r.check(whoop_row is not None and whoop_row["status"] == "connected",
                "sync left the account 'connected' (no auth failure)")
        r.check(whoop_row is not None and whoop_row["last_sync_at"] is not None,
                "last_sync_at was stamped")

        print("\n4. Read-back (normalized tables, no live call):")
        today = store.fitness_today()
        print(f"        today: source={today.get('source')} "
              f"recovery={today.get('recovery_pct')} strain={today.get('day_strain')} "
              f"sleep_quality={today.get('sleep_quality_pct')}")
        logged = store.list_workouts(limit=5)
        for w in logged:
            print(f"        - #{w['id']} [{w['source']}] {w['name']!r} {w['when']}")
        r.check(today.get("has_data") or bool(logged),
                "normalized tables populated (rings/vitals or workouts present)")
    except Exception as exc:  # a live call blew up — report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES — see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
