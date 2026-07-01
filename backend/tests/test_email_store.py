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


def test_inbox_groups_by_category_and_counts():
    # Two needs_reply (one unread), one fyi (unread), one untriaged (unread).
    store.upsert_email(
        _email(source_id="nr-1", subject="Reply A", unread=True,
               received_at=datetime(2026, 6, 30, 9, 0, tzinfo=UTC)),
        category="needs_reply", summary=["a"],
    )
    store.upsert_email(
        _email(source_id="nr-2", subject="Reply B", unread=False,
               received_at=datetime(2026, 6, 30, 11, 0, tzinfo=UTC)),
        category="needs_reply", summary=["b"],
    )
    store.upsert_email(
        _email(source_id="fyi-1", subject="FYI", unread=True,
               received_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC)),
        category="fyi", summary=["c"],
    )
    store.upsert_email(
        _email(source_id="un-1", subject="Untriaged", unread=True,
               received_at=datetime(2026, 6, 30, 7, 0, tzinfo=UTC)),
        category=None, summary=None,
    )
    box = store.inbox()
    assert [e["subject"] for e in box["needs_reply"]] == ["Reply B", "Reply A"]  # desc
    assert [e["subject"] for e in box["fyi"]] == ["FYI"]
    assert [e["subject"] for e in box["untriaged"]] == ["Untriaged"]
    assert box["needs_reply_count"] == 2
    assert box["unread_count"] == 3   # nr-1, fyi-1, un-1 unread


def test_inbox_empty_state():
    box = store.inbox()
    assert box == {
        "needs_reply": [], "fyi": [], "untriaged": [],
        "needs_reply_count": 0, "unread_count": 0,
    }


def test_get_email_returns_dict_or_none():
    created = store.upsert_email(_email(source_id="det-1", subject="Detail"),
                                 category="fyi", summary=["x"])
    fetched = store.get_email(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["subject"] == "Detail"
    assert fetched["source_id"] == "det-1"
    assert "body" not in fetched          # store never yields a body
    assert store.get_email(999999) is None


def test_delete_email_data_removes_only_that_source():
    store.upsert_email(_email(source_id="g-1"), category="fyi", summary=["a"])
    store.upsert_email(_email(source_id="g-2"), category="needs_reply", summary=["b"])
    assert store.delete_email_data("google") is True
    box = store.inbox()
    assert box["needs_reply"] == [] and box["fyi"] == [] and box["untriaged"] == []
    # A second delete with nothing left returns False.
    assert store.delete_email_data("google") is False
