"""M5 email schemas: EmailOut (no body), EmailDetail (adds body), Inbox, OAuthStatus."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import EmailDetail, EmailOut, Inbox, OAuthStatus


def _row(**over) -> dict:
    base = {
        "id": 1,
        "source": "google",
        "from_name": "Ada Lovelace",
        "from_email": "ada@example.com",
        "subject": "Re: dinner",
        "snippet": "Are we still on for",
        "received_at": datetime(2026, 6, 30, 15, 24, tzinfo=timezone.utc),
        "unread": True,
        "category": "needs_reply",
        "summary": ["Wants to confirm dinner", "Asks about time"],
        "when": "8:24am",
    }
    base.update(over)
    return base


def test_email_out_validates_list_row_and_has_no_body():
    out = EmailOut.model_validate(_row())
    assert out.category == "needs_reply"
    assert out.summary == ["Wants to confirm dinner", "Asks about time"]
    assert out.when == "8:24am"
    assert "body" not in EmailOut.model_fields  # privacy: list item never carries a body


def test_email_out_allows_untriaged_null_category_and_empty_summary():
    out = EmailOut.model_validate(_row(category=None, summary=[]))
    assert out.category is None
    assert out.summary == []


def test_email_out_rejects_out_of_vocab_category():
    with pytest.raises(ValidationError):
        EmailOut.model_validate(_row(category="spam"))


def test_email_out_defaults_starred_false_and_label_ids_empty():
    out = EmailOut.model_validate(_row())
    assert out.starred is False
    assert out.label_ids == []


def test_email_out_accepts_starred_and_label_ids():
    out = EmailOut.model_validate(_row(starred=True, label_ids=["INBOX", "STARRED"]))
    assert out.starred is True
    assert out.label_ids == ["INBOX", "STARRED"]


def test_email_detail_adds_thread_id_and_body():
    detail = EmailDetail.model_validate(_row(thread_id="t-1", body="Full plain text body."))
    assert detail.thread_id == "t-1"
    assert detail.body == "Full plain text body."
    assert detail.subject == "Re: dinner"  # inherits EmailOut fields


def test_inbox_groups_and_counts():
    inbox = Inbox.model_validate({
        "needs_reply": [_row(id=1)],
        "fyi": [_row(id=2, category="fyi")],
        "untriaged": [_row(id=3, category=None, summary=[])],
        "needs_reply_count": 1,
        "unread_count": 3,
    })
    assert [e.id for e in inbox.needs_reply] == [1]
    assert [e.id for e in inbox.fyi] == [2]
    assert [e.id for e in inbox.untriaged] == [3]
    assert inbox.needs_reply_count == 1
    assert inbox.unread_count == 3


def test_oauth_status_is_generic_provider_status_list():
    status = OAuthStatus.model_validate({
        "connected": True,
        "providers": [{
            "provider": "google",
            "status": "connected",
            "connected_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "last_sync_at": None,
        }],
    })
    assert status.connected is True
    assert status.providers[0].provider == "google"
