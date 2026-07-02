"""M5 email API: GET /inbox grouping, GET /{id} on-demand body + fallback, POST /sync."""
from datetime import datetime, timedelta, timezone

from app import email_sync, providers
from app.providers.base import NormalizedEmail, Tokens
from app.store import store

NOW = datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)


def _email(source_id: str, subject: str, minutes_ago: int = 0, unread: bool = False) -> NormalizedEmail:
    return NormalizedEmail(
        source="google",
        source_id=source_id,
        thread_id=f"t-{source_id}",
        from_name="Ada Lovelace",
        from_email="ada@example.com",
        subject=subject,
        snippet="preview text",
        received_at=NOW - timedelta(minutes=minutes_ago),
        unread=unread,
    )


class FakeEmailProvider:
    """Only the surface the email router calls: name, fetch_messages (marker), get_message."""

    name = "google"

    def __init__(self, *, body: str = "Full body text.", raise_on_get: bool = False):
        self._body = body
        self._raise = raise_on_get
        self.got: list[str] = []

    def fetch_messages(self, since):  # marks this as an EmailProvider for the sync
        return []

    def get_message(self, source_id: str) -> str:
        self.got.append(source_id)
        if self._raise:
            raise RuntimeError("gmail down")
        return self._body


class FakeEmailSync:
    def __init__(self, count: int = 4):
        self.count = count
        self.calls = 0

    def tick(self, now=None) -> int:
        self.calls += 1
        return self.count


def test_inbox_groups_needs_reply_fyi_untriaged_with_counts(client):
    store.upsert_email(_email("m1", "Reply please", minutes_ago=1, unread=True),
                       category="needs_reply", summary=["Wants a reply"])
    store.upsert_email(_email("m2", "Newsletter", minutes_ago=2, unread=True),
                       category="fyi", summary=["Weekly digest"])
    store.upsert_email(_email("m3", "Just arrived", minutes_ago=3, unread=False),
                       category=None, summary=None)

    body = client.get("/api/email/inbox").json()
    assert [e["subject"] for e in body["needs_reply"]] == ["Reply please"]
    assert [e["subject"] for e in body["fyi"]] == ["Newsletter"]
    assert [e["subject"] for e in body["untriaged"]] == ["Just arrived"]
    assert body["needs_reply_count"] == 1
    assert body["unread_count"] == 2
    # list items never carry a body
    assert all("body" not in e for group in ("needs_reply", "fyi", "untriaged") for e in body[group])


def test_get_email_returns_metadata_plus_on_demand_body(client):
    fake = FakeEmailProvider(body="Hey Ada here is the plan.")
    providers.configure([fake])
    row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])

    detail = client.get(f"/api/email/{row['id']}").json()
    assert detail["subject"] == "The plan"
    assert detail["thread_id"] == "t-m9"
    assert detail["summary"] == ["A plan"]
    assert detail["body"] == "Hey Ada here is the plan."
    assert fake.got == ["m9"]  # body fetched live by source_id


def test_get_email_falls_back_when_gmail_unreachable(client):
    providers.configure([FakeEmailProvider(raise_on_get=True)])
    row = store.upsert_email(_email("m5", "Offline"), category="fyi", summary=[])

    detail = client.get(f"/api/email/{row['id']}").json()
    assert detail["body"] == "Message body is unavailable right now."


def test_get_email_404_for_missing_id(client):
    assert client.get("/api/email/999999").status_code == 404


def test_sync_triggers_email_sync_and_lists_email_providers(client):
    fake_sync = FakeEmailSync(count=7)
    email_sync.configure(fake_sync)
    providers.configure([FakeEmailProvider()])

    body = client.post("/api/email/sync").json()
    assert body == {"synced": 7, "providers": ["google"]}
    assert fake_sync.calls == 1
