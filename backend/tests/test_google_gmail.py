"""GoogleProvider Gmail fetch (M5) — real provider, fake httpx transport."""
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
