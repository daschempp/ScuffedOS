"""email_sync (M5): tick over connected Google accounts — real tick, fakes only."""
from datetime import datetime, timezone

from app import email_sync, email_triage, providers
from app.providers.base import NormalizedEmail, Tokens
from app.store import store

from .fakes import FakeEmailProvider, FakeProvider


class _FakeTriage:
    def __init__(self, result=("fyi", ["noted"])):
        self.result = result
        self.calls = []

    def triage(self, subject, from_name, from_email, snippet, body_excerpt):
        self.calls.append(source := (subject, body_excerpt))
        return self.result


def _email(source_id: str, *, subject: str = "Hi", unread: bool = True) -> NormalizedEmail:
    return NormalizedEmail(
        source="google", source_id=source_id, thread_id="th",
        from_name="Priya", from_email="p@x.io", subject=subject,
        snippet="snip", received_at=datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc),
        unread=unread, body_excerpt="body excerpt text",
    )


def _connect_google():
    store.upsert_provider_account("google", Tokens(
        access_token="g", refresh_token="r", expires_at=None,
        scopes="gmail.readonly", provider_user_id="sub1"))


def test_tick_fetches_triages_and_upserts_new_messages():
    prov = FakeEmailProvider(messages=[_email("m1"), _email("m2", subject="FYI note")])
    providers.configure([prov])
    triage = _FakeTriage(("needs_reply", ["Reply about the 30th"]))
    email_triage.configure(triage)
    _connect_google()

    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 2
    # Tokens were injected before the authed fetch.
    assert prov.injected and prov.injected[-1].access_token == "g"
    # Both messages triaged + stored.
    assert len(triage.calls) == 2
    inbox = store.inbox()
    stored_ids = {e["source_id"] for e in inbox["needs_reply"] + inbox["fyi"] + inbox["untriaged"]}
    assert stored_ids == {"m1", "m2"}
    # Cursor advanced.
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "google")
    assert acct["last_sync_at"] is not None


def test_tick_skips_already_stored_ids():
    prov = FakeEmailProvider(messages=[_email("m1")])
    providers.configure([prov])
    triage = _FakeTriage()
    email_triage.configure(triage)
    _connect_google()
    # Pre-store m1 so email_exists short-circuits it.
    store.upsert_email(_email("m1"), "fyi", ["already"])

    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 0
    assert triage.calls == []  # never re-triaged


def test_tick_stores_untriaged_message_when_triage_returns_none():
    prov = FakeEmailProvider(messages=[_email("m1")])
    providers.configure([prov])
    email_triage.configure(_FakeTriage((None, None)))
    _connect_google()

    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 1
    inbox = store.inbox()
    ids = {e["source_id"] for e in inbox["untriaged"]}
    assert "m1" in ids  # shows as untriaged, retried next pass


def test_tick_ignores_fitness_pull_providers():
    # A WHOOP FakeProvider has no fetch_messages -> email_sync must skip it.
    providers.configure([FakeProvider()])
    email_triage.configure(_FakeTriage())
    store.upsert_provider_account("whoop", Tokens(
        access_token="w", refresh_token="r", expires_at=None, scopes="", provider_user_id=None))
    count = email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    assert count == 0  # nothing email-shaped connected


def test_tick_flips_account_to_needs_reauth_on_auth_error():
    providers.configure([FakeEmailProvider(raise_auth=True)])
    email_triage.configure(_FakeTriage())
    _connect_google()
    email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc))
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "google")
    assert acct["status"] == "needs_reauth"


def test_tick_skips_disconnected_account():
    providers.configure([FakeEmailProvider(messages=[_email("m1")])])
    email_triage.configure(_FakeTriage())
    # No account row at all -> nothing to sync.
    assert email_sync.tick(now=datetime(2026, 6, 30, 18, tzinfo=timezone.utc)) == 0
