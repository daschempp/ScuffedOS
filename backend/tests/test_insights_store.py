"""Insights persistence: upsert-by-key, list, has_insight, and the snapshot
window the rules read. Reads are owner-scoped; upsert replaces by
(owner, domain, day, code)."""
from datetime import date, timedelta

from app.providers.base import NormalizedSnapshot
from app.store import store

TODAY = date.today()


def test_upsert_insert_then_list(client):
    store.upsert_insight(day=TODAY, domain="fitness", code="recovery_band",
                         tone="positive", headline="Recovery is green",
                         body="Recovery is 72% — you're primed.",
                         signals={"recovery_pct": 72}, source="rules")
    cards = store.list_insights(TODAY)
    assert len(cards) == 1
    c = cards[0]
    assert c["code"] == "recovery_band"
    assert c["tone"] == "positive"
    assert c["signals"] == {"recovery_pct": 72}
    assert c["source"] == "rules"


def test_upsert_replaces_by_key(client):
    store.upsert_insight(day=TODAY, domain="fitness", code="recovery_band",
                         tone="neutral", headline="h1", body="b1",
                         signals={"recovery_pct": 50}, source="rules")
    store.upsert_insight(day=TODAY, domain="fitness", code="recovery_band",
                         tone="positive", headline="h2", body="b2",
                         signals={"recovery_pct": 72}, source="llm")
    cards = store.list_insights(TODAY)
    assert len(cards) == 1                       # replaced, not duplicated
    assert cards[0]["body"] == "b2"
    assert cards[0]["source"] == "llm"


def test_has_insight(client):
    assert store.has_insight(TODAY) is False
    store.upsert_insight(day=TODAY, domain="fitness", code="recovery_band",
                         tone="neutral", headline="h", body="b",
                         signals={}, source="rules")
    assert store.has_insight(TODAY) is True


def test_list_snapshots_window_prefers_whoop(client):
    d2 = TODAY - timedelta(days=2)
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=d2, recovery_pct=60))
    store.upsert_snapshot(NormalizedSnapshot(source="oura", day=d2, recovery_pct=99))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=72))
    window = store.list_snapshots(TODAY, days_back=7)
    days = [s["day"] for s in window]
    assert days == sorted(days)                  # oldest -> newest
    d2_row = next(s for s in window if s["day"] == d2)
    assert d2_row["recovery_pct"] == 60          # whoop wins over oura
