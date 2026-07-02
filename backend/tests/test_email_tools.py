"""M5 assistant email tools (read-only): get_inbox compact shape, get_email body + errors."""
import json
from datetime import datetime, timedelta, timezone

from app import providers, tools
from app.providers.base import NormalizedEmail
from app.store import store

NOW = datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)


def _email(source_id: str, subject: str, minutes_ago: int = 0) -> NormalizedEmail:
    return NormalizedEmail(
        source="google",
        source_id=source_id,
        thread_id=f"t-{source_id}",
        from_name="Ada Lovelace",
        from_email="ada@example.com",
        subject=subject,
        snippet="preview",
        received_at=NOW - timedelta(minutes=minutes_ago),
        unread=True,
    )


class FakeEmailProvider:
    name = "google"

    def __init__(self, *, body: str = "Full body.", raise_on_get: bool = False):
        self._body = body
        self._raise = raise_on_get
        self.got: list[str] = []

    def fetch_messages(self, since):
        return []

    def get_message(self, source_id: str) -> str:
        self.got.append(source_id)
        if self._raise:
            raise RuntimeError("gmail down")
        return self._body


def test_email_tools_are_registered_read_only():
    names = {t["name"] for t in tools.TOOLS}
    assert {"get_inbox", "get_email"} <= names
    # No write/send/draft/archive tools this slice.
    assert not any(n in names for n in ("send_email", "draft_email", "archive_email"))


def test_get_inbox_returns_compact_groups_and_count(client):
    store.upsert_email(_email("m1", "Reply please", minutes_ago=1),
                       category="needs_reply", summary=["Wants a reply"])
    store.upsert_email(_email("m2", "Newsletter", minutes_ago=2),
                       category="fyi", summary=["Digest"])

    result_json, action = tools.execute("get_inbox", {})
    result = json.loads(result_json)
    assert action is None  # reader — no action card
    assert result["needs_reply_count"] == 1
    assert [e["subject"] for e in result["needs_reply"]] == ["Reply please"]
    assert [e["subject"] for e in result["fyi"]] == ["Newsletter"]
    # compact: no body ever, and summary carried through
    assert result["needs_reply"][0]["summary"] == ["Wants a reply"]
    assert "body" not in result["needs_reply"][0]


def test_get_email_reads_metadata_summary_and_live_body(client):
    fake = FakeEmailProvider(body="Here is the full text.")
    providers.configure([fake])
    row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])

    result_json, action = tools.execute("get_email", {"email_id": row["id"]})
    result = json.loads(result_json)
    assert action is None
    assert result["subject"] == "The plan"
    assert result["summary"] == ["A plan"]
    assert result["body"] == "Here is the full text."
    assert fake.got == ["m9"]


def test_get_email_body_falls_back_when_gmail_unreachable(client):
    providers.configure([FakeEmailProvider(raise_on_get=True)])
    row = store.upsert_email(_email("m5", "Offline"), category="fyi", summary=[])

    result = json.loads(tools.execute("get_email", {"email_id": row["id"]})[0])
    assert result["body"] == "Message body is unavailable right now."


def test_get_email_errors_for_missing_id(client):
    result = json.loads(tools.execute("get_email", {"email_id": 987654})[0])
    assert "error" in result
