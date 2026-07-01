"""Store-layer email logic (M5): upsert idempotency, inbox grouping, detail, delete.

All against SQLite via the fresh_db fixture — no network, no providers, no LLM.
"""
from datetime import datetime, timezone

from app.providers.base import NormalizedEmail
from app.store import store

UTC = timezone.utc


def _email(**kw):
    base = dict(
        source="google", source_id="g-1", thread_id="t-1",
        from_name="Priya Rao", from_email="priya@example.com",
        subject="Lighthouse deadline", snippet="About the moved date",
        received_at=datetime(2026, 6, 30, 15, 24, tzinfo=UTC),
        unread=True, body_excerpt="Can you confirm the 30th works?",
    )
    base.update(kw)
    return NormalizedEmail(**base)


def test_upsert_email_creates_row_with_triage():
    out = store.upsert_email(_email(), category="needs_reply",
                             summary=["Confirm the 30th", "Loop in design"])
    assert out["source"] == "google"
    assert out["source_id"] == "g-1"
    assert out["thread_id"] == "t-1"
    assert out["from_name"] == "Priya Rao"
    assert out["from_email"] == "priya@example.com"
    assert out["subject"] == "Lighthouse deadline"
    assert out["snippet"] == "About the moved date"
    assert out["unread"] is True
    assert out["category"] == "needs_reply"
    assert out["summary"] == ["Confirm the 30th", "Loop in design"]
    assert out["triaged_at"] is not None
    assert out["received_at"] == datetime(2026, 6, 30, 15, 24, tzinfo=UTC)
    # No body ever leaves the store.
    assert "body" not in out
    assert "body_excerpt" not in out
    # Derived display field present.
    assert isinstance(out["when"], str) and out["when"]


def test_upsert_email_is_idempotent_by_source_id():
    store.upsert_email(_email(), category="fyi", summary=["first"])
    again = store.upsert_email(
        _email(subject="Lighthouse deadline (edited)", unread=False),
        category="needs_reply", summary=["second"],
    )
    # Same (owner, source, source_id) -> one row, metadata + triage updated.
    assert store.email_exists("google", "g-1") is True
    assert again["subject"] == "Lighthouse deadline (edited)"
    assert again["unread"] is False
    assert again["category"] == "needs_reply"
    assert again["summary"] == ["second"]
    from sqlalchemy import select
    from app.models import Email
    with store._session() as s:
        assert len(s.scalars(select(Email)).all()) == 1


def test_upsert_email_untriaged_when_category_none():
    # A triage failure passes category=None -> row stored, left untriaged.
    out = store.upsert_email(_email(), category=None, summary=None)
    assert out["category"] is None
    assert out["summary"] == []           # [] not None in the dict
    assert out["triaged_at"] is None
    assert store.email_exists("google", "g-1") is True


def test_upsert_email_none_category_preserves_prior_triage():
    # First pass triages the row.
    store.upsert_email(_email(), category="needs_reply", summary=["reply soon"])
    # A later pass with category=None (triage offline) must NOT clobber the
    # already-good triage — metadata refreshes, triage fields stay.
    out = store.upsert_email(_email(unread=False), category=None, summary=None)
    assert out["unread"] is False              # metadata refreshed
    assert out["category"] == "needs_reply"     # prior triage preserved
    assert out["summary"] == ["reply soon"]
    assert out["triaged_at"] is not None


def test_email_exists_false_when_absent():
    assert store.email_exists("google", "nope") is False
