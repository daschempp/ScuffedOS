"""Engine: rules+phraser+cache, and the once-a-day generation gate."""
from datetime import date, timedelta

from app import llm
from app.insights import engine
from app.providers.base import NormalizedSnapshot
from app.store import store

TODAY = date.today()


def test_generate_for_day_writes_cached_cards(client):
    # baseline history + a strong today
    for i in range(1, 4):
        store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY - timedelta(days=i),
                                                 recovery_pct=60, hrv_ms=50.0, resting_hr=54))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=82,
                                             day_strain=9.0, sleep_quality_pct=88, hrv_ms=58.0))
    llm.configure(None)                            # force template wording
    n = engine.generate_for_day(TODAY)
    assert n >= 1
    cards = store.list_insights(TODAY)
    assert any(c["code"] == "recovery_band" for c in cards)
    assert cards[0]["source"] == "rules"           # llm off -> templated


def test_generate_is_idempotent_by_code(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=82))
    llm.configure(None)
    engine.generate_for_day(TODAY)
    first = len(store.list_insights(TODAY))
    engine.generate_for_day(TODAY)                 # re-run
    assert len(store.list_insights(TODAY)) == first  # upsert, no duplicates


def test_maybe_generate_skips_without_recovery(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, day_strain=10.0))
    assert engine.maybe_generate_today() == 0
    assert store.list_insights(TODAY) == []


def test_maybe_generate_runs_once_then_skips(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=75))
    llm.configure(None)
    assert engine.maybe_generate_today() >= 1
    assert engine.maybe_generate_today() == 0      # already has today's insight


def test_regenerate_prunes_cards_that_stopped_firing(client):
    llm.configure(None)
    # Morning: green recovery + low strain -> strain_recovery_balance (positive) fires.
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=75, day_strain=5.0))
    engine.generate_for_day(TODAY)
    codes1 = {c["code"] for c in store.list_insights(TODAY)}
    assert "strain_recovery_balance" in codes1
    # Later: strain has climbed past the "primed & underused" threshold -> that signal no longer fires.
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, day_strain=15.0))
    engine.generate_for_day(TODAY)
    codes2 = {c["code"] for c in store.list_insights(TODAY)}
    assert "strain_recovery_balance" not in codes2   # pruned, not left stale
    assert "recovery_band" in codes2                 # anchor still present
