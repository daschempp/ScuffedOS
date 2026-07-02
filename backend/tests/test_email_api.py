"""M5 email API: GET /inbox grouping, GET /{id} on-demand body + fallback, POST /sync."""
from datetime import datetime, timedelta, timezone

from app import email_draft, email_sync, providers
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
    """Only the surface the email router calls: name, fetch_messages (marker),
    get_message, plus the M5 slice-2 write methods (trash/modify/labels/send/meta)."""

    name = "google"

    def __init__(self, *, body: str = "Full body text.", raise_on_get: bool = False,
                 raise_on_write: bool = False, labels: list[dict] | None = None,
                 meta: dict | None = None, send_result: dict | None = None):
        self._body = body
        self._raise = raise_on_get
        self._raise_write = raise_on_write
        self._labels = labels if labels is not None else []
        self._meta = meta or {"message_id": "", "references": "", "subject": "", "from_email": ""}
        self._send_result = send_result or {"id": "sent-1"}
        self.got: list[str] = []
        self.trashed: list[str] = []
        self.modified: list[tuple[str, list[str], list[str]]] = []
        self.sent: list[tuple[bytes, str | None]] = []
        self.meta_fetched: list[str] = []

    def fetch_messages(self, since):  # marks this as an EmailProvider for the sync
        return []

    def get_message(self, source_id: str) -> str:
        self.got.append(source_id)
        if self._raise:
            raise RuntimeError("gmail down")
        return self._body

    def _maybe_raise(self):
        if self._raise_write:
            from app.providers.google import GoogleAuthError
            raise GoogleAuthError("gmail rejected the action")

    def trash_message(self, source_id: str) -> None:
        self._maybe_raise()
        self.trashed.append(source_id)

    def modify_labels(self, source_id: str, add=(), remove=()) -> None:
        self._maybe_raise()
        self.modified.append((source_id, list(add), list(remove)))

    def list_labels(self) -> list[dict]:
        self._maybe_raise()
        return list(self._labels)

    def get_message_meta(self, source_id: str) -> dict:
        self._maybe_raise()
        self.meta_fetched.append(source_id)
        return dict(self._meta)

    def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str:
        self._maybe_raise()
        self.sent.append((raw_rfc822, thread_id))
        return self._send_result["id"]


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


def test_trash_email_calls_gmail_then_deletes_local_row(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m20", "Junk"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/trash")

    assert res.status_code == 204
    assert fake.trashed == ["m20"]
    assert store.get_email(row["id"]) is None


def test_trash_email_404_before_any_provider_call(client):
    fake = FakeEmailProvider()
    providers.configure([fake])

    res = client.post("/api/email/999999/trash")

    assert res.status_code == 404
    assert fake.trashed == []


def test_trash_email_502_on_gmail_failure_leaves_row_untouched(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])
    row = store.upsert_email(_email("m21", "Keep me"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/trash")

    assert res.status_code == 502
    # App-wide error envelope (app/errors.py): {"error": {"code", "message"}}.
    assert res.json()["error"]["message"] == "Gmail rejected the action"
    assert store.get_email(row["id"]) is not None


def test_flags_mark_read_removes_unread_label_and_updates_row(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m30", "Ping", unread=True), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/flags", json={"unread": False})

    assert res.status_code == 200
    body = res.json()
    assert body["unread"] is False
    assert fake.modified == [("m30", [], ["UNREAD"])]


def test_flags_mark_unread_adds_unread_label(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m31", "Ping", unread=False), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/flags", json={"unread": True})

    assert res.status_code == 200
    assert res.json()["unread"] is True
    assert fake.modified == [("m31", ["UNREAD"], [])]


def test_flags_star_adds_starred_label(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m32", "Ping"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/flags", json={"starred": True})

    assert res.status_code == 200
    assert res.json()["starred"] is True
    assert fake.modified == [("m32", ["STARRED"], [])]


def test_flags_unstar_removes_starred_label(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m33", "Ping"), category="fyi", summary=[])
    store.set_email_flags(row["id"], starred=True)

    res = client.post(f"/api/email/{row['id']}/flags", json={"starred": False})

    assert res.status_code == 200
    assert res.json()["starred"] is False
    assert fake.modified == [("m33", [], ["STARRED"])]


def test_flags_both_fields_combine_add_and_remove(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m34", "Ping", unread=True), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/flags",
                      json={"unread": False, "starred": True})

    assert res.status_code == 200
    assert fake.modified == [("m34", ["STARRED"], ["UNREAD"])]


def test_flags_empty_patch_is_a_no_op_and_skips_the_provider_call(client):
    # PINNED behavior: {} (both fields None/untouched) returns the current
    # row unchanged and never calls modify_labels — there is nothing to
    # confirm with Gmail, so no network round-trip is made.
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m35", "Ping", unread=True), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/flags", json={})

    assert res.status_code == 200
    assert res.json()["unread"] is True
    assert fake.modified == []


def test_flags_404_before_any_provider_call(client):
    fake = FakeEmailProvider()
    providers.configure([fake])

    res = client.post("/api/email/999999/flags", json={"unread": True})

    assert res.status_code == 404
    assert fake.modified == []


def test_flags_502_on_gmail_failure_leaves_row_unchanged(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])
    row = store.upsert_email(_email("m36", "Ping", unread=True), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/flags", json={"unread": False})

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"
    assert store.get_email(row["id"])["unread"] is True


def test_labels_add_and_remove_computes_union_minus_removed(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m40", "Ping"), category="fyi", summary=[])
    store.set_email_labels(row["id"], ["INBOX", "IMPORTANT"])

    res = client.post(f"/api/email/{row['id']}/labels",
                      json={"add": ["STARRED"], "remove": ["IMPORTANT"]})

    assert res.status_code == 200
    body = res.json()
    assert sorted(body["label_ids"]) == sorted(["INBOX", "STARRED"])
    assert fake.modified == [("m40", ["STARRED"], ["IMPORTANT"])]


def test_labels_add_only(client):
    fake = FakeEmailProvider()
    providers.configure([fake])
    row = store.upsert_email(_email("m41", "Ping"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/labels", json={"add": ["Label_1"]})

    assert res.status_code == 200
    assert res.json()["label_ids"] == ["Label_1"]
    assert fake.modified == [("m41", ["Label_1"], [])]


def test_labels_404_before_any_provider_call(client):
    fake = FakeEmailProvider()
    providers.configure([fake])

    res = client.post("/api/email/999999/labels", json={"add": ["Label_1"]})

    assert res.status_code == 404
    assert fake.modified == []


def test_labels_502_on_gmail_failure_leaves_row_unchanged(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])
    row = store.upsert_email(_email("m42", "Ping"), category="fyi", summary=[])
    store.set_email_labels(row["id"], ["INBOX"])

    res = client.post(f"/api/email/{row['id']}/labels", json={"add": ["Label_2"]})

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"
    assert store.get_email(row["id"])["label_ids"] == ["INBOX"]


def test_labels_unknown_provider_returns_502(client):
    # No providers configured at all -> providers.get('google') is None.
    providers.configure([])
    row = store.upsert_email(_email("m43", "Ping"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/labels", json={"add": ["Label_1"]})

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"


def test_get_labels_lists_from_provider(client):
    fake = FakeEmailProvider(labels=[
        {"id": "INBOX", "name": "INBOX", "type": "system"},
        {"id": "Label_1", "name": "Work", "type": "user"},
    ])
    providers.configure([fake])

    res = client.get("/api/email/labels")

    assert res.status_code == 200
    body = res.json()
    assert body == [
        {"id": "INBOX", "name": "INBOX", "type": "system"},
        {"id": "Label_1", "name": "Work", "type": "user"},
    ]


def test_get_labels_502_on_gmail_failure(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])

    res = client.get("/api/email/labels")

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"


# policy.default gives EmailMessage-compatible parses (get_content works);
# the legacy compat32 default would lack .get_content().
from email import message_from_bytes, policy


def _parse_raw(raw: bytes):
    return message_from_bytes(raw, policy=policy.default)


def test_send_builds_rfc822_and_posts_via_provider(client):
    fake = FakeEmailProvider(send_result={"id": "sent-42"})
    providers.configure([fake])

    res = client.post("/api/email/send", json={
        "to": "priya@lighthouse.io", "cc": "team@lighthouse.io",
        "subject": "Kickoff", "body": "See you Monday.",
    })

    assert res.status_code == 200
    assert res.json() == {"id": "sent-42"}
    assert len(fake.sent) == 1
    raw, thread_id = fake.sent[0]
    assert thread_id is None
    msg = _parse_raw(raw)
    assert msg["To"] == "priya@lighthouse.io"
    assert msg["Cc"] == "team@lighthouse.io"
    assert msg["Subject"] == "Kickoff"
    assert msg.get_content().strip() == "See you Monday."


def test_send_502_on_gmail_failure(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])

    res = client.post("/api/email/send", json={
        "to": "a@x.com", "subject": "S", "body": "B",
    })

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"


def test_reply_threads_and_prefixes_subject_with_re(client):
    fake = FakeEmailProvider(
        send_result={"id": "reply-1"},
        meta={"message_id": "<orig@gmail.com>", "references": "<older@gmail.com>",
              "subject": "Kickoff", "from_email": "priya@lighthouse.io"},
    )
    providers.configure([fake])
    row = store.upsert_email(_email("m50", "Kickoff"), category="needs_reply", summary=[])

    res = client.post(f"/api/email/{row['id']}/reply", json={"body": "Sounds good."})

    assert res.status_code == 200
    assert res.json() == {"id": "reply-1"}
    assert fake.meta_fetched == ["m50"]
    raw, thread_id = fake.sent[0]
    assert thread_id == "t-m50"  # original row's thread_id, per _email() helper
    msg = _parse_raw(raw)
    assert msg["To"] == "priya@lighthouse.io"
    assert msg["Subject"] == "Re: Kickoff"
    assert msg["In-Reply-To"] == "<orig@gmail.com>"
    assert msg["References"] == "<older@gmail.com> <orig@gmail.com>"
    assert msg.get_content().strip() == "Sounds good."


def test_reply_does_not_double_prefix_an_existing_re_subject(client):
    fake = FakeEmailProvider(
        meta={"message_id": "<orig@gmail.com>", "references": "",
              "subject": "Re: Kickoff", "from_email": "priya@lighthouse.io"},
    )
    providers.configure([fake])
    row = store.upsert_email(_email("m51", "Re: Kickoff"), category="needs_reply", summary=[])

    client.post(f"/api/email/{row['id']}/reply", json={"body": "Ack."})

    raw, _ = fake.sent[0]
    msg = _parse_raw(raw)
    assert msg["Subject"] == "Re: Kickoff"


def test_reply_case_insensitive_re_prefix_check(client):
    fake = FakeEmailProvider(
        meta={"message_id": "<orig@gmail.com>", "references": "",
              "subject": "RE: kickoff", "from_email": "priya@lighthouse.io"},
    )
    providers.configure([fake])
    row = store.upsert_email(_email("m52", "RE: kickoff"), category="needs_reply", summary=[])

    client.post(f"/api/email/{row['id']}/reply", json={"body": "Ack."})

    raw, _ = fake.sent[0]
    msg = _parse_raw(raw)
    assert msg["Subject"] == "RE: kickoff"


def test_reply_404_before_any_provider_call(client):
    fake = FakeEmailProvider()
    providers.configure([fake])

    res = client.post("/api/email/999999/reply", json={"body": "Ack."})

    assert res.status_code == 404
    assert fake.sent == []
    assert fake.meta_fetched == []


def test_reply_502_on_gmail_failure(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])
    row = store.upsert_email(_email("m53", "Kickoff"), category="needs_reply", summary=[])

    res = client.post(f"/api/email/{row['id']}/reply", json={"body": "Ack."})

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"


def test_forward_prefixes_subject_with_fwd_and_carries_no_threading_headers(client):
    fake = FakeEmailProvider(
        send_result={"id": "fwd-1"},
        meta={"message_id": "<orig@gmail.com>", "references": "<older@gmail.com>",
              "subject": "Kickoff", "from_email": "priya@lighthouse.io"},
    )
    providers.configure([fake])
    row = store.upsert_email(_email("m54", "Kickoff"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/forward",
                      json={"to": "other@x.com", "body": "FYI, see below."})

    assert res.status_code == 200
    assert res.json() == {"id": "fwd-1"}
    raw, thread_id = fake.sent[0]
    assert thread_id is None  # forward does not thread
    msg = _parse_raw(raw)
    assert msg["To"] == "other@x.com"
    assert msg["Subject"] == "Fwd: Kickoff"
    assert msg["In-Reply-To"] is None
    assert msg["References"] is None
    assert msg.get_content().strip() == "FYI, see below."


def test_forward_does_not_double_prefix_an_existing_fwd_subject(client):
    fake = FakeEmailProvider(
        meta={"message_id": "<orig@gmail.com>", "references": "",
              "subject": "Fwd: Kickoff", "from_email": "priya@lighthouse.io"},
    )
    providers.configure([fake])
    row = store.upsert_email(_email("m55", "Fwd: Kickoff"), category="fyi", summary=[])

    client.post(f"/api/email/{row['id']}/forward", json={"to": "other@x.com", "body": "FYI."})

    raw, _ = fake.sent[0]
    msg = _parse_raw(raw)
    assert msg["Subject"] == "Fwd: Kickoff"


def test_forward_404_before_any_provider_call(client):
    fake = FakeEmailProvider()
    providers.configure([fake])

    res = client.post("/api/email/999999/forward", json={"to": "a@x.com", "body": "FYI."})

    assert res.status_code == 404
    assert fake.sent == []


def test_forward_502_on_gmail_failure(client):
    fake = FakeEmailProvider(raise_on_write=True)
    providers.configure([fake])
    row = store.upsert_email(_email("m56", "Kickoff"), category="fyi", summary=[])

    res = client.post(f"/api/email/{row['id']}/forward",
                      json={"to": "other@x.com", "body": "FYI."})

    assert res.status_code == 502
    assert res.json()["error"]["message"] == "Gmail rejected the action"


class _FakeDraft:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def draft(self, instructions, notes, mode, original):
        self.calls.append((instructions, notes, mode, original))
        return self.text


def test_draft_new_mode_ignores_email_id(client):
    email_draft.configure(_FakeDraft("Hey team, launch update inside."))

    resp = client.post("/api/email/draft", json={
        "instructions": "write a launch update", "notes": "on track",
        "mode": "new", "email_id": 999999,
    })
    assert resp.status_code == 200
    assert resp.json() == {"draft": "Hey team, launch update inside."}


def test_draft_reply_mode_builds_original_from_store_and_live_excerpt(client):
    fake_provider = FakeEmailProvider(body="Full original body, quite long, " * 100)
    providers.configure([fake_provider])
    row = store.upsert_email(_email("m9", "The plan"), category="fyi", summary=["A plan"])
    fake_draft = _FakeDraft("Sounds good, confirming.")
    email_draft.configure(fake_draft)

    resp = client.post("/api/email/draft", json={
        "instructions": "confirm it works", "mode": "reply", "email_id": row["id"],
    })
    assert resp.status_code == 200
    assert resp.json() == {"draft": "Sounds good, confirming."}
    assert len(fake_draft.calls) == 1
    _, _, mode, original = fake_draft.calls[0]
    assert mode == "reply"
    assert original["from_name"] == "Ada Lovelace"
    assert original["from_email"] == "ada@example.com"
    assert original["subject"] == "The plan"
    assert len(original["body_excerpt"]) <= 2048


def test_draft_reply_mode_404_when_email_id_absent(client):
    email_draft.configure(_FakeDraft("text"))
    resp = client.post("/api/email/draft", json={
        "instructions": "confirm it works", "mode": "reply", "email_id": 999999,
    })
    assert resp.status_code == 404


def test_draft_reply_mode_excerpt_falls_back_to_empty_on_fetch_failure(client):
    providers.configure([FakeEmailProvider(raise_on_get=True)])
    row = store.upsert_email(_email("m5", "Offline"), category="fyi", summary=[])
    fake_draft = _FakeDraft("Drafted anyway.")
    email_draft.configure(fake_draft)

    resp = client.post("/api/email/draft", json={
        "instructions": "reply anyway", "mode": "reply", "email_id": row["id"],
    })
    assert resp.status_code == 200
    assert resp.json() == {"draft": "Drafted anyway."}
    _, _, _, original = fake_draft.calls[0]
    assert original["body_excerpt"] == ""


def test_draft_returns_503_when_draft_unavailable(client):
    email_draft.configure(None)
    resp = client.post("/api/email/draft", json={"instructions": "write it", "mode": "new"})
    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "Couldn't draft — try again."


def test_draft_never_persists_anything(client):
    email_draft.configure(_FakeDraft("Some draft text."))
    before = store.inbox()
    client.post("/api/email/draft", json={"instructions": "write it", "mode": "new"})
    after = store.inbox()
    assert before == after
