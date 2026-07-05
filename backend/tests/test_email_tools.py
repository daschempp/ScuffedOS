"""M5 assistant email tools: get_inbox compact shape, get_email body + errors,
draft_email (slice-2, the only write-adjacent tool this slice)."""
import json
from datetime import datetime, timedelta, timezone

from app import email_draft, providers, tools
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


def test_email_tools_are_registered():
    names = {t["name"] for t in tools.TOOLS}
    assert {"get_inbox", "get_email", "draft_email"} <= names
    # draft_email is the ONLY write-adjacent email tool this slice — it never
    # sends/trashes/labels; those remain assistant-inaccessible.
    assert not any(n in names for n in ("send_email", "trash_email", "label_email"))


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


class _FakeDraft:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def draft(self, instructions, notes, mode, original):
        self.calls.append((instructions, notes, mode, original))
        return self.text


def test_draft_email_happy_path_with_reply_to(client):
    fake = FakeEmailProvider(body="Full live body text, not the snippet.")
    providers.configure([fake])
    row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])
    fake_draft = _FakeDraft("Sounds good, confirming.")
    email_draft.configure(fake_draft)

    result_json, action = tools.execute(
        "draft_email", {"instructions": "confirm it works", "email_id": row["id"]}
    )
    result = json.loads(result_json)
    assert result["draft"] == "Sounds good, confirming."
    assert result["reply_to"]["id"] == row["id"]
    assert result["reply_to"]["subject"] == "The plan"
    assert "body" not in result["reply_to"]
    assert action == {"icon": "mail", "title": "Draft ready",
                      "meta": "Open compose to review & send", "cta": "Open email", "screen": "email"}
    # contract §G: body_excerpt is fetched live via provider.get_message,
    # never the DB-cached snippet (row["snippet"] == "preview" per _email()).
    assert fake.got == ["m9"]
    _, _, _, original = fake_draft.calls[0]
    assert original["body_excerpt"] == "Full live body text, not the snippet."


def test_draft_email_without_email_id_has_no_reply_to():
    email_draft.configure(_FakeDraft("A fresh note."))

    result_json, action = tools.execute("draft_email", {"instructions": "write a note"})
    result = json.loads(result_json)
    assert result["draft"] == "A fresh note."
    assert result["reply_to"] is None
    assert action is not None


def test_draft_email_errors_when_draft_unavailable():
    email_draft.configure(None)

    result_json, action = tools.execute("draft_email", {"instructions": "write it"})
    result = json.loads(result_json)
    assert "error" in result
    assert action is None


def test_draft_email_errors_for_missing_email_id():
    email_draft.configure(_FakeDraft("text"))

    result_json, action = tools.execute(
        "draft_email", {"instructions": "reply", "email_id": 987654}
    )
    result = json.loads(result_json)
    assert "error" in result
    assert action is None
