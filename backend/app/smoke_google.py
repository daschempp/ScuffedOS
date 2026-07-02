"""End-to-end smoke test for the live Gmail pipeline (M5).

Drives the REAL GoogleProvider against Google's production OAuth + the Gmail
API and the real email_sync engine, then reads the emails table back. Unlike
the pytest suite (which fakes every provider and the triage LLM via conftest),
this makes real authenticated Gmail requests, sends real triage input to
Anthropic, and writes synced rows to the configured database.

Google OAuth needs a one-time browser authorize, so this runs in two modes:

  * Already connected -- a `provider_accounts` row for 'google' exists with
    tokens. The script refreshes if needed, runs a real email_sync tick, and
    asserts messages landed in the emails table with triage populated.
  * Not connected -- prints the authorize URL (built from settings) and the
    exact steps to connect, then exits 2 (setup needed, not a pipeline
    failure).

Google ALLOWS localhost redirect URIs, so no tunnel is needed: register
http://localhost:8000/auth/google/callback on the OAuth client and point
GOOGLE_REDIRECT_URI at it.

Prerequisites (see the M5 design spec): GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
set, ANTHROPIC_API_KEY set (triage runs live), and the redirect URI above
registered on the Google Cloud OAuth Web client.

Run it by hand once credentials are live (NOT in CI):

    python -m app.smoke_google

Exit status: 0 if every leg passed, 1 on a pipeline failure, 2 if Google isn't
connected yet (run the OAuth connect first).
"""
from __future__ import annotations

import logging
import secrets
import sys
import time
from datetime import datetime, timezone

from . import email_sync, providers
from .config import settings
from .providers.google import GMAIL_API_BASE, _build_rfc822
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help(provider) -> None:
    state = secrets.token_urlsafe(16)
    print("\nGoogle is not connected yet. To connect end-to-end:")
    print("  1. Start the backend on http://localhost:8000 (Google allows localhost).")
    print("  2. Register http://localhost:8000/auth/google/callback as an authorized")
    print("     redirect URI on the Google Cloud OAuth Web client, and set")
    print("     GOOGLE_REDIRECT_URI to match.")
    print("  3. Open this authorize URL in a browser and approve:")
    print("\n     " + provider.authorize_url(state))
    print("\n  4. Google redirects to /auth/google/callback, which stores tokens.")
    print("     Re-run `python -m app.smoke_google` afterwards.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS -- live Gmail pipeline smoke test")
    print(f"  owner={settings.owner!r}  redirect_uri={settings.google_redirect_uri!r}  "
          f"backfill_count={settings.email_backfill_count}")

    print("\nPreconditions:")
    if not r.check(bool(settings.google_client_id and settings.google_client_secret),
                   "Google credentials configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)"):
        print("\nAborting: Google client credentials are not set.")
        return 1
    if not r.check(bool(settings.database_url),
                   "DATABASE_URL configured (synced rows need a database)"):
        print("\nAborting: no DATABASE_URL -- sync writes nowhere.")
        return 1
    r.check(bool(settings.anthropic_api_key),
            "ANTHROPIC_API_KEY configured (triage runs live; without it rows stay untriaged)")

    provider = providers.get("google")
    if not r.check(provider is not None, "Google provider registered"):
        return 1

    account = store.get_provider_account("google")
    if account is None:
        r.check(False, "Google account connected (provider_accounts row exists)",
                "not connected -- see steps below")
        _print_connect_help(provider)
        return 2
    r.check(True, "Google account connected",
            f"status={account['status']} provider_user_id={account.get('provider_user_id')}")

    try:
        print("\n1. Token validity (refresh if within the expiry guard):")
        tokens = store.get_provider_tokens("google")
        if not r.check(tokens is not None and bool(tokens.access_token),
                       "access token present server-side"):
            return 1
        provider.set_tokens(tokens)

        print("\n2. Live fetch (Gmail INBOX messages):")
        messages = provider.fetch_messages(None)
        r.check(True, "messages fetched", f"{len(messages)}")
        r.check(bool(messages), "Gmail returned at least one INBOX message")
        for m in messages[:3]:
            print(f"        - {m.subject!r} from {m.from_name!r} <{m.from_email}> "
                  f"unread={m.unread} at {m.received_at}")
            r.check(bool(m.source_id), "message has a source_id")
            r.check(m.source == "google", f"source is 'google' (got {m.source!r})")
            r.check(len(m.body_excerpt) <= 4096,
                    f"body_excerpt is bounded (~2 KB): {len(m.body_excerpt)} chars")

        print("\n3. On-demand body fetch (first message):")
        if messages:
            body = provider.get_message(messages[0].source_id)
            r.check(isinstance(body, str) and bool(body.strip()),
                    "get_message returned a non-empty body", f"{len(body)} chars")

        print("\n4. Real email_sync tick (provider -> triage -> emails table):")
        upserted = email_sync.tick()
        r.check(isinstance(upserted, int), "tick returned a count of upserted rows", str(upserted))
        synced = store.list_provider_accounts()
        g_row = next((a for a in synced if a["provider"] == "google"), None)
        r.check(g_row is not None and g_row["status"] == "connected",
                "sync left the account 'connected' (no auth failure)")
        r.check(g_row is not None and g_row["last_sync_at"] is not None,
                "last_sync_at was stamped")

        print("\n5. Read-back (emails table, no live call):")
        inbox = store.inbox()
        total = len(inbox["needs_reply"]) + len(inbox["fyi"]) + len(inbox["untriaged"])
        print(f"        inbox: needs_reply={len(inbox['needs_reply'])} "
              f"fyi={len(inbox['fyi'])} untriaged={len(inbox['untriaged'])} "
              f"needs_reply_count={inbox['needs_reply_count']} "
              f"unread_count={inbox['unread_count']}")
        r.check(total > 0, "emails table populated (inbox has messages)")
        triaged = inbox["needs_reply"] + inbox["fyi"]
        if settings.anthropic_api_key:
            r.check(bool(triaged),
                    "at least one message was triaged (category + summary present)")
            for e in triaged[:3]:
                print(f"        - [{e['category']}] {e['subject']!r} :: "
                      + " | ".join(e["summary"][:3]))

        print("\n6. Write path (send-to-self -> verify -> trash):")
        account = store.get_provider_account("google")
        if not account or not account.get("can_write_email"):
            r.check(True, "SKIPPED -- account lacks gmail.modify/gmail.send scopes",
                    "re-consent to grant email actions: connect Google again and tick "
                    "BOTH the Gmail modify and send checkboxes on the consent screen")
        else:
            # [confirm-against-live]: GET {GMAIL_API_BASE}/profile -> {"emailAddress": ...}
            profile = provider._get(f"{GMAIL_API_BASE}/profile")
            self_addr = profile.get("emailAddress", "")
            r.check(bool(self_addr), "resolved the connected account's own address",
                    self_addr or "<empty>")

            subject = f"ScuffedOS smoke {datetime.now(timezone.utc).isoformat()}"
            raw = _build_rfc822(to=self_addr, subject=subject,
                                 body="Automated write-leg smoke test -- safe to ignore.")
            sent_id = provider.send_message(raw)
            r.check(bool(sent_id), "send_message returned a new message id", sent_id)

            print("        polling for arrival (up to ~30s)...")
            found_id = None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not found_id:
                hits = provider._get(
                    f"{GMAIL_API_BASE}/messages",
                    # Gmail search phrases use double quotes, not Python repr()'s
                    # single quotes -- [confirm-against-live] the exact query
                    # syntax against the real Gmail search API in Task 19/20.
                    params={"q": f'subject:"{subject}"'},
                )
                ids = [m["id"] for m in hits.get("messages", [])]
                if sent_id in ids:
                    found_id = sent_id
                else:
                    time.sleep(3)
            r.check(found_id is not None,
                    "sent message appeared in messages.list by subject", subject)

            provider.trash_message(sent_id)
            r.check(True, "trash_message call completed", sent_id)

            time.sleep(2)
            after = provider._get(
                f"{GMAIL_API_BASE}/messages", params={"q": f'subject:"{subject}"'}
            )
            after_ids = [m["id"] for m in after.get("messages", [])]
            r.check(sent_id not in after_ids,
                    "trashed message no longer returned by messages.list", subject)
    except Exception as exc:  # a live call blew up -- report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES -- see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
