"""Insights read/refresh API. GET is a pure cache read (never generates);
refresh regenerates today from the current snapshot."""
from datetime import date

from app.providers.base import NormalizedSnapshot
from app.store import store

TODAY = date.today()


def _seed_card():
    store.upsert_insight(day=TODAY, domain="fitness", code="recovery_band",
                         tone="positive", headline="Recovery is green",
                         body="Recovery is 80% — primed.", signals={"recovery_pct": 80},
                         source="rules")


def test_get_empty(client):
    body = client.get("/api/insights").json()
    assert body["date"] == TODAY.isoformat()
    assert body["has_data"] is False
    assert body["cards"] == []


def test_get_returns_cached_and_does_not_generate(client):
    # a snapshot exists but NO insight row -> GET must not create one
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=80))
    body = client.get("/api/insights").json()
    assert body["cards"] == []
    assert store.list_insights(TODAY) == []        # GET generated nothing


def test_get_lists_seeded_card(client):
    _seed_card()
    body = client.get("/api/insights").json()
    assert body["has_data"] is True
    assert body["cards"][0]["code"] == "recovery_band"
    assert body["cards"][0]["source"] == "rules"


def test_refresh_generates_today(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY, recovery_pct=80))
    body = client.post("/api/insights/refresh").json()   # llm disabled by fixture -> templates
    assert body["has_data"] is True
    assert any(c["code"] == "recovery_band" for c in body["cards"])
