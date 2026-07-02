"""The M5 email data layer: the NormalizedEmail seam + the emails table."""
from dataclasses import fields
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import Email
from app.providers.base import NormalizedEmail
from app.store import store

UTC = timezone.utc


def test_normalized_email_fields_and_defaults():
    field_names = {f.name for f in fields(NormalizedEmail)}
    assert field_names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
        "starred", "label_ids",
    }
    # unread / body_excerpt / starred / label_ids are the only optional fields.
    e = NormalizedEmail(
        source="google", source_id="g-1", thread_id="t-1",
        from_name="Priya", from_email="priya@example.com",
        subject="Lighthouse", snippet="About the deadline",
        received_at=datetime(2026, 6, 30, 15, 24, tzinfo=UTC),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
    assert e.starred is False
    assert e.label_ids == []
    # Provided values round-trip.
    e2 = NormalizedEmail(
        source="google", source_id="g-2", thread_id="t-2",
        from_name="Sam", from_email="sam@example.com",
        subject="Lunch", snippet="Thursday?",
        received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        unread=True, body_excerpt="Hey, are you free Thursday for lunch?",
        starred=True, label_ids=["INBOX", "STARRED"],
    )
    assert e2.unread is True
    assert e2.body_excerpt.startswith("Hey")
    assert e2.starred is True
    assert e2.label_ids == ["INBOX", "STARRED"]


def test_emails_table_and_columns_exist():
    with store._session() as s:
        insp = inspect(s.get_bind())
        assert "emails" in set(insp.get_table_names())
        cols = {c["name"] for c in insp.get_columns("emails")}
        assert {
            "owner", "source", "source_id", "thread_id", "from_name",
            "from_email", "subject", "snippet", "received_at", "unread",
            "category", "summary_json", "triaged_at", "created_at", "updated_at",
        } <= cols
        # Privacy rule: bodies are never persisted.
        assert "body" not in cols


def test_email_owner_source_source_id_is_unique():
    received = datetime(2026, 6, 30, 15, 24, tzinfo=UTC)
    with store._session() as s, s.begin():
        s.add(Email(owner="me", source="google", source_id="g-1",
                    subject="Hi", received_at=received))
    # Same (owner, source, source_id) collides — synced rows upsert idempotently.
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(Email(owner="me", source="google", source_id="g-1",
                        subject="Hi again", received_at=received))
    # A different source_id is allowed.
    with store._session() as s, s.begin():
        s.add(Email(owner="me", source="google", source_id="g-2",
                    subject="Second", received_at=received))
    with store._session() as s:
        rows = s.scalars(select(Email)).all()
        assert len(rows) == 2


def test_email_column_defaults():
    with store._session() as s, s.begin():
        row = Email(owner="me", source="google", source_id="g-3",
                    subject="Defaults",
                    received_at=datetime(2026, 6, 30, 9, 0, tzinfo=UTC))
        s.add(row)
        s.flush()
        assert row.thread_id == ""
        assert row.from_name == ""
        assert row.from_email == ""
        assert row.snippet == ""
        assert row.unread is False
        assert row.category is None
        assert row.summary_json is None
        assert row.triaged_at is None
        assert row.created_at is not None
        assert row.updated_at is not None


def test_email_starred_and_label_ids_columns_default():
    with store._session() as s:
        insp = inspect(s.get_bind())
        cols = {c["name"] for c in insp.get_columns("emails")}
        assert {"starred", "label_ids"} <= cols
    with store._session() as s, s.begin():
        row = Email(owner="me", source="google", source_id="g-4",
                    subject="Slice2 defaults",
                    received_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC))
        s.add(row)
        s.flush()
        assert row.starred is False
        assert row.label_ids == []
