"""GoogleProvider Gmail fetch (M5) — real provider, fake httpx transport."""
import base64
from datetime import datetime, timezone

import pytest

from app.providers.base import NormalizedEmail
from app.providers.google import GoogleAuthError, GoogleProvider
from app.providers.base import Tokens

from .fakes import FakeGmailHTTP, gmail_message


def _provider(http) -> GoogleProvider:
    p = GoogleProvider()
    p.configure(fake_http=http)
    p.set_tokens(Tokens(access_token="tok", refresh_token="r", expires_at=None))
    return p


def test_fetch_messages_lists_inbox_then_maps_each_message():
    http = FakeGmailHTTP(messages={
        "m1": gmail_message(
            "m1", thread_id="th1",
            from_hdr="Priya Rao <priya@lighthouse.io>",
            subject="Re: moved deadline",
            date_hdr="Mon, 30 Jun 2026 08:24:00 -0700",
            snippet="Does the 30th still work?",
            label_ids=["INBOX", "UNREAD"],
            body_text="Hi — confirming the 30th. Loop in the design review please.",
        ),
    })
    emails = _provider(http).fetch_messages(since=None)

    assert len(emails) == 1
    e = emails[0]
    assert isinstance(e, NormalizedEmail)
    assert e.source == "google" and e.source_id == "m1" and e.thread_id == "th1"
    assert e.from_name == "Priya Rao" and e.from_email == "priya@lighthouse.io"
    assert e.subject == "Re: moved deadline"
    assert e.snippet == "Does the 30th still work?"
    assert e.unread is True
    # Date header -> aware UTC (08:24 -0700 == 15:24 UTC).
    assert e.received_at == datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc)
    assert "design review" in e.body_excerpt
    assert e.starred is False
    assert e.label_ids == ["INBOX", "UNREAD"]


def test_fetch_messages_sends_inbox_label_and_backfill_count():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000")})
    from app.config import settings

    _provider(http).fetch_messages(since=None)
    # First GET is the list call — assert its params.
    list_url, list_params = http.gets[0]
    assert list_url.endswith("/messages")
    assert list_params.get("labelIds") == "INBOX"
    assert list_params.get("maxResults") == settings.email_backfill_count


def test_bare_email_from_header_has_empty_from_name():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="noreply@service.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000")})
    e = _provider(http).fetch_messages(since=None)[0]
    assert e.from_email == "noreply@service.com"
    assert e.from_name == ""
    assert e.unread is False  # no UNREAD label


def test_fetch_messages_maps_starred_label():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000",
        label_ids=["INBOX", "STARRED"])})
    e = _provider(http).fetch_messages(since=None)[0]
    assert e.starred is True
    assert e.label_ids == ["INBOX", "STARRED"]


def test_body_excerpt_truncated_to_about_2kb():
    big = "x" * 5000
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000", body_text=big)})
    e = _provider(http).fetch_messages(since=None)[0]
    assert len(e.body_excerpt) <= 2048


def test_fetch_messages_auth_failure_raises_google_auth_error():
    http = FakeGmailHTTP(list_ids=["m1"], status={"/messages": 401})
    with pytest.raises(GoogleAuthError):
        _provider(http).fetch_messages(since=None)


def test_get_message_returns_decoded_full_body():
    http = FakeGmailHTTP(messages={"m1": gmail_message(
        "m1", from_hdr="a@x.com", subject="s",
        date_hdr="Mon, 30 Jun 2026 08:00:00 +0000",
        body_text="The complete message body, all of it.")})
    body = _provider(http).get_message("m1")
    assert body == "The complete message body, all of it."


def test_get_message_raises_on_transport_error():
    http = FakeGmailHTTP(messages={"m1": {}}, status={"/messages/m1": 500})
    with pytest.raises(GoogleAuthError):
        _provider(http).get_message("m1")


def _html_only_message(msg_id: str, *, html_body: str) -> dict:
    """A Gmail messages.get payload whose ONLY decodable body part is
    text/html (no text/plain part at all) — e.g. a newsletter sent as
    multipart/alternative with just an HTML part."""
    import base64

    b64 = base64.urlsafe_b64encode(html_body.encode("utf-8")).decode("ascii")
    return {
        "id": msg_id,
        "threadId": "th1",
        "snippet": "snippet",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "a@x.com"},
                {"name": "Subject", "value": "Newsletter"},
                {"name": "Date", "value": "Mon, 30 Jun 2026 08:00:00 +0000"},
            ],
            "parts": [
                {"mimeType": "text/html", "body": {"data": b64}},
            ],
        },
    }


def test_html_only_body_is_stripped_to_plain_text_for_triage():
    html_body = "<html><body><b>Hello</b> Ada &amp; team, please review.</body></html>"
    http = FakeGmailHTTP(messages={"m1": _html_only_message("m1", html_body=html_body)})

    e = _provider(http).fetch_messages(since=None)[0]

    assert "Hello" in e.body_excerpt
    assert "review" in e.body_excerpt
    assert "&" in e.body_excerpt  # &amp; unescaped
    assert "<" not in e.body_excerpt  # no raw tags leaked into the excerpt

    body = _provider(http).get_message("m1")
    assert "Hello" in body
    assert "review" in body
    assert "<" not in body


def test_send_message_posts_base64url_raw_and_returns_new_id():
    http = FakeGmailHTTP()
    raw = b"To: a@x.com\r\nSubject: s\r\n\r\nbody text\r\n"
    new_id = _provider(http).send_message(raw)
    assert new_id == "sent-1"
    url, payload = http.posts[0]
    assert url.endswith("/messages/send")
    decoded = base64.urlsafe_b64decode(payload["raw"] + "=" * (-len(payload["raw"]) % 4))
    assert decoded == raw
    assert "threadId" not in payload


def test_send_message_passes_thread_id_when_given():
    http = FakeGmailHTTP()
    new_id = _provider(http).send_message(b"To: a@x.com\r\n\r\nb\r\n", thread_id="th1")
    assert new_id == "sent-1"
    url, payload = http.posts[0]
    assert payload["threadId"] == "th1"


def test_send_message_auth_failure_raises_google_auth_error():
    http = FakeGmailHTTP(status={"/messages/send": 401})
    with pytest.raises(GoogleAuthError):
        _provider(http).send_message(b"To: a@x.com\r\n\r\nb\r\n")


def test_trash_message_posts_to_trash_endpoint():
    http = FakeGmailHTTP()
    _provider(http).trash_message("m1")
    url, payload = http.posts[0]
    assert url.endswith("/messages/m1/trash")
    assert payload == {}


def test_trash_message_auth_failure_raises():
    http = FakeGmailHTTP(status={"/trash": 401})
    with pytest.raises(GoogleAuthError):
        _provider(http).trash_message("m1")


def test_modify_labels_posts_add_and_remove_label_ids():
    http = FakeGmailHTTP()
    _provider(http).modify_labels("m1", add=["STARRED"], remove=["UNREAD"])
    url, payload = http.posts[0]
    assert url.endswith("/messages/m1/modify")
    assert payload == {"addLabelIds": ["STARRED"], "removeLabelIds": ["UNREAD"]}


def test_modify_labels_defaults_to_empty_lists():
    http = FakeGmailHTTP()
    _provider(http).modify_labels("m1")
    url, payload = http.posts[0]
    assert payload == {"addLabelIds": [], "removeLabelIds": []}


def test_modify_labels_auth_failure_raises():
    http = FakeGmailHTTP(status={"/modify": 500})
    with pytest.raises(GoogleAuthError):
        _provider(http).modify_labels("m1", add=["STARRED"])


def test_list_labels_gets_and_returns_label_dicts():
    http = FakeGmailHTTP(labels=[
        {"id": "STARRED", "name": "STARRED", "type": "system"},
        {"id": "Label_1", "name": "Family", "type": "user"},
    ])
    labels = _provider(http).list_labels()
    assert labels == [
        {"id": "STARRED", "name": "STARRED", "type": "system"},
        {"id": "Label_1", "name": "Family", "type": "user"},
    ]
    url, _ = http.gets[0]
    assert url.endswith("/labels")


def test_list_labels_auth_failure_raises():
    http = FakeGmailHTTP(status={"/labels": 401})
    with pytest.raises(GoogleAuthError):
        _provider(http).list_labels()


def test_get_message_meta_returns_headers_and_metadata_params():
    http = FakeGmailHTTP(messages={"m1": {
        "id": "m1",
        "payload": {"headers": [
            {"name": "Message-ID", "value": "<abc123@mail.gmail.com>"},
            {"name": "References", "value": "<xyz@mail.gmail.com>"},
            {"name": "Subject", "value": "Original subject"},
            {"name": "From", "value": "Priya Rao <priya@lighthouse.io>"},
        ]},
    }})
    meta = _provider(http).get_message_meta("m1")
    assert meta == {
        "message_id": "<abc123@mail.gmail.com>",
        "references": "<xyz@mail.gmail.com>",
        "subject": "Original subject",
        "from_email": "priya@lighthouse.io",
    }
    url, params = http.gets[0]
    assert url.endswith("/messages/m1")
    assert params["format"] == "metadata"
    assert params["metadataHeaders"] == ["Message-ID", "References", "Subject", "From"]


def test_get_message_meta_missing_headers_are_empty_strings():
    http = FakeGmailHTTP(messages={"m1": {"id": "m1", "payload": {"headers": []}}})
    meta = _provider(http).get_message_meta("m1")
    assert meta == {"message_id": "", "references": "", "subject": "", "from_email": ""}


def test_get_message_meta_auth_failure_raises():
    http = FakeGmailHTTP(messages={"m1": {}}, status={"/messages/m1": 500})
    with pytest.raises(GoogleAuthError):
        _provider(http).get_message_meta("m1")
