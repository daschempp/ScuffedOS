"""The M5 provider-protocol split: OAuthProvider base + Fitness/Email domains.

Guards that the refactor keeps WhoopProvider structurally a FitnessProvider,
and introduces the EmailProvider protocol + NormalizedEmail dataclass with the
frozen field set. No network — pure type/shape assertions.
"""
from dataclasses import fields
from datetime import datetime, timezone

from app.providers import base
from app.providers.whoop import WhoopProvider


def test_oauth_provider_is_runtime_checkable():
    assert hasattr(base, "OAuthProvider")
    assert getattr(base.OAuthProvider, "_is_runtime_protocol", False) is True


def test_email_provider_exists():
    assert hasattr(base, "EmailProvider")


def test_whoop_still_satisfies_fitness_provider():
    # runtime_checkable structural check — WhoopProvider must keep passing after
    # it gains the three OAuthProvider hooks (added in a later task; this only
    # asserts the protocol still admits it structurally today).
    assert isinstance(WhoopProvider(), base.FitnessProvider)


def test_normalized_email_fields_and_defaults():
    names = {f.name for f in fields(base.NormalizedEmail)}
    assert names == {
        "source", "source_id", "thread_id", "from_name", "from_email",
        "subject", "snippet", "received_at", "unread", "body_excerpt",
    }
    e = base.NormalizedEmail(
        source="google", source_id="m1", thread_id="t1",
        from_name="Ada", from_email="ada@example.com", subject="Hi",
        snippet="preview", received_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert e.unread is False
    assert e.body_excerpt == ""
