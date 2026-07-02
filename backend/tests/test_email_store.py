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


def test_upsert_email_writes_through_starred_and_label_ids():
    out = store.upsert_email(
        _email(starred=True, label_ids=["INBOX", "STARRED"]),
        category="fyi", summary=["x"],
    )
    assert out["starred"] is True
    assert out["label_ids"] == ["INBOX", "STARRED"]
    # A later sync pass re-derives from Gmail's authoritative label list.
    again = store.upsert_email(
        _email(starred=False, label_ids=["INBOX"]),
        category="fyi", summary=["x"],
    )
    assert again["starred"] is False
    assert again["label_ids"] == ["INBOX"]


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


def test_get_email_is_owner_scoped():
    # get_email keys on id alone; without an owner predicate it would return a
    # row owned by a DIFFERENT owner (an IDOR the moment ids are URL-exposed or a
    # second owner exists). Lock the owner filter like _email_row/inbox/delete.
    from app.models import Email

    mine = store.upsert_email(_email(source_id="mine-1", subject="Mine"),
                              category="fyi", summary=["ok"])
    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="theirs-1",
            subject="Theirs",
            received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.get_email(mine["id"]) is not None   # my own row still returned
    assert store.get_email(foreign_id) is None        # other owner's row invisible


def test_delete_email_data_removes_only_that_source():
    store.upsert_email(_email(source_id="g-1"), category="fyi", summary=["a"])
    store.upsert_email(_email(source_id="g-2"), category="needs_reply", summary=["b"])
    assert store.delete_email_data("google") is True
    box = store.inbox()
    assert box["needs_reply"] == [] and box["fyi"] == [] and box["untriaged"] == []
    # A second delete with nothing left returns False.
    assert store.delete_email_data("google") is False


def test_delete_email_data_is_source_scoped():
    # A row from a DIFFERENT source must survive delete_email_data("google").
    # This locks the source filter: an owner-only delete would wrongly remove it.
    store.upsert_email(_email(source="google", source_id="g-1"),
                       category="fyi", summary=["a"])
    store.upsert_email(_email(source="outlook", source_id="o-1"),
                       category="fyi", summary=["b"])
    assert store.delete_email_data("google") is True
    assert store.email_exists("google", "g-1") is False
    assert store.email_exists("outlook", "o-1") is True   # untouched


def test_set_email_flags_updates_only_given_fields():
    created = store.upsert_email(_email(source_id="fl-1", unread=True), category="fyi", summary=["x"])
    out = store.set_email_flags(created["id"], starred=True)
    assert out["starred"] is True
    assert out["unread"] is True   # unread untouched (None = unchanged)
    out2 = store.set_email_flags(created["id"], unread=False)
    assert out2["unread"] is False
    assert out2["starred"] is True   # starred untouched by the second call
    out3 = store.set_email_flags(created["id"], unread=True, starred=False)
    assert out3["unread"] is True
    assert out3["starred"] is False


def test_set_email_flags_returns_none_for_absent_id():
    assert store.set_email_flags(999999, starred=True) is None


def test_set_email_flags_is_owner_scoped():
    from app.models import Email

    mine = store.upsert_email(_email(source_id="fl-mine"), category="fyi", summary=["x"])
    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="fl-theirs",
            subject="Theirs", received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.set_email_flags(foreign_id, starred=True) is None
    with store._session() as s:
        untouched = s.get(Email, foreign_id)
        assert untouched.starred is False


def test_set_email_labels_replaces_list_and_rederives_unread_starred():
    created = store.upsert_email(
        _email(source_id="lb-1", unread=True, starred=False, label_ids=["INBOX", "UNREAD"]),
        category="fyi", summary=["x"],
    )
    out = store.set_email_labels(created["id"], ["INBOX", "STARRED"])
    assert out["label_ids"] == ["INBOX", "STARRED"]
    assert out["starred"] is True     # re-derived from STARRED membership
    assert out["unread"] is False     # re-derived: UNREAD no longer present

    out2 = store.set_email_labels(created["id"], ["INBOX", "UNREAD", "STARRED"])
    assert out2["label_ids"] == ["INBOX", "UNREAD", "STARRED"]
    assert out2["unread"] is True
    assert out2["starred"] is True


def test_set_email_labels_returns_none_for_absent_id():
    assert store.set_email_labels(999999, ["INBOX"]) is None


def test_set_email_labels_is_owner_scoped():
    from app.models import Email

    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="lb-theirs",
            subject="Theirs", received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            label_ids=["INBOX"],
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.set_email_labels(foreign_id, ["INBOX", "STARRED"]) is None
    with store._session() as s:
        untouched = s.get(Email, foreign_id)
        assert untouched.label_ids == ["INBOX"]


def test_delete_email_removes_single_row():
    created = store.upsert_email(_email(source_id="del-1"), category="fyi", summary=["x"])
    other = store.upsert_email(_email(source_id="del-2"), category="fyi", summary=["y"])
    assert store.delete_email(created["id"]) is True
    assert store.get_email(created["id"]) is None
    assert store.get_email(other["id"]) is not None   # sibling row untouched


def test_delete_email_returns_false_for_absent_id():
    assert store.delete_email(999999) is False


def test_delete_email_is_owner_scoped():
    from app.models import Email

    with store._session() as s, s.begin():
        foreign = Email(
            owner="someone_else", source="google", source_id="del-theirs",
            subject="Theirs", received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id

    assert store.delete_email(foreign_id) is False
    with store._session() as s:
        assert s.get(Email, foreign_id) is not None   # a cross-owner delete must not succeed
