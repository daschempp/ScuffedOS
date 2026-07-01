"""The M5 email data layer: the NormalizedEmail seam + the emails table."""
from dataclasses import fields
from datetime import datetime, timezone

from app.providers.base import NormalizedEmail

UTC = timezone.utc


def test_normalized_email_fields_and_defaults():
    field_names = {f.name for f in fields(NormalizedEmail)}
    assert field_names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
    }
    # unread / body_excerpt are the only optional fields.
    e = NormalizedEmail(
        source="google", source_id="g-1", thread_id="t-1",
        from_name="Priya", from_email="priya@example.com",
        subject="Lighthouse", snippet="About the deadline",
        received_at=datetime(2026, 6, 30, 15, 24, tzinfo=UTC),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
    # Provided values round-trip.
    e2 = NormalizedEmail(
        source="google", source_id="g-2", thread_id="t-2",
        from_name="Sam", from_email="sam@example.com",
        subject="Lunch", snippet="Thursday?",
        received_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        unread=True, body_excerpt="Hey, are you free Thursday for lunch?",
    )
    assert e2.unread is True
    assert e2.body_excerpt.startswith("Hey")
