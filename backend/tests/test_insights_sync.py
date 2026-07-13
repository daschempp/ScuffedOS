"""The sync tick generates today's insight once (gated), and never crashes the
tick. The autouse fixture leaves llm disabled + providers empty, so tick's
provider loop no-ops and generation falls back to templates."""
from datetime import date

from app import fitness_sync
from app.providers.base import NormalizedSnapshot
from app.store import store

TODAY = date.today()


def test_tick_generates_todays_insight_from_snapshot(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=72,
                                             day_strain=8.0, sleep_quality_pct=80))
    fitness_sync.tick()
    cards = store.list_insights(TODAY)
    assert any(c["code"] == "recovery_band" for c in cards)


def test_tick_without_recovery_generates_nothing(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, day_strain=8.0))
    fitness_sync.tick()
    assert store.list_insights(TODAY) == []
