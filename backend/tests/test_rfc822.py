"""_build_rfc822 (M5 slice-2 contract §B) — pure stdlib email.message builder,
no network. Real RFC-822 bytes assembled here are what Task 3's
send_message base64url-encodes into the Gmail 'raw' field."""
from email import policy
from email.parser import BytesParser

from app.providers.google import _build_rfc822


def test_sets_to_cc_subject_headers():
    raw = _build_rfc822(
        to="priya@lighthouse.io", cc="team@lighthouse.io",
        subject="Re: moved deadline", body="Works for me.",
    )
    msg = BytesParser().parsebytes(raw)
    assert msg["To"] == "priya@lighthouse.io"
    assert msg["Cc"] == "team@lighthouse.io"
    assert msg["Subject"] == "Re: moved deadline"


def test_cc_omitted_when_not_given():
    raw = _build_rfc822(to="a@x.com", subject="s", body="b")
    msg = BytesParser().parsebytes(raw)
    assert msg["Cc"] is None


def test_from_header_is_never_set():
    # Gmail sets the authenticated sender; a From header here would be
    # ignored or rejected by the API.
    raw = _build_rfc822(to="a@x.com", subject="s", body="b")
    msg = BytesParser().parsebytes(raw)
    assert msg["From"] is None


def test_body_is_utf8_plain_text_and_round_trips_emoji():
    raw = _build_rfc822(to="a@x.com", subject="s", body="Ship it \U0001F680 — thanks!")
    # policy=policy.default gives an EmailMessage-compatible parse tree with
    # .get_content(); the header-only tests above use the legacy default
    # policy since they only read headers.
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content_charset() == "utf-8"
    assert msg.get_content().strip() == "Ship it \U0001F680 — thanks!"


def test_in_reply_to_and_references_present_only_when_given():
    raw_plain = _build_rfc822(to="a@x.com", subject="s", body="b")
    msg_plain = BytesParser().parsebytes(raw_plain)
    assert msg_plain["In-Reply-To"] is None
    assert msg_plain["References"] is None

    raw_threaded = _build_rfc822(
        to="a@x.com", subject="Re: s", body="b",
        in_reply_to="<abc123@mail.gmail.com>",
        references="<abc123@mail.gmail.com>",
    )
    msg_threaded = BytesParser().parsebytes(raw_threaded)
    assert msg_threaded["In-Reply-To"] == "<abc123@mail.gmail.com>"
    assert msg_threaded["References"] == "<abc123@mail.gmail.com>"


def test_returns_bytes_parseable_by_email_parser():
    raw = _build_rfc822(to="a@x.com", subject="s", body="b")
    assert isinstance(raw, bytes)
    msg = BytesParser().parsebytes(raw)
    assert msg["To"] == "a@x.com"
