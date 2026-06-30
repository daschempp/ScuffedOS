"""Fitness read/write API (M4): /today, /workouts, /week, manual POST/DELETE, /sync.

Reads never touch a provider — they read the normalized tables the data phase
fills. /sync delegates to fitness_sync.tick() through its configure() seam.
"""
from datetime import date, datetime, timezone

from app import fitness_sync
from app.providers.base import NormalizedSnapshot, NormalizedWorkout
from app.store import store

TODAY = date.today()


def _at(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    """A UTC datetime on `day`."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


class FakeSync:
    """Stands in for the fitness_sync tick via fitness_sync.configure().

    The sync phase's configure() accepts a fake whose .tick(now) returns an int;
    here we just record the call and return a fixed count.
    """

    def __init__(self, count: int = 3):
        self.count = count
        self.calls = 0

    def tick(self, now=None) -> int:
        self.calls += 1
        return self.count


# ---- reads (normalized tables only) ----------------------------------------

def test_today_empty_state(client):
    today = client.get("/api/fitness/today").json()
    assert today["date"] == TODAY.isoformat()
    assert today["has_data"] is False
    assert today["source"] is None
    assert today["recovery_pct"] is None
    assert today["vitals"] == [] or all(v["value"] is None for v in today["vitals"])


def test_today_reads_snapshot_with_derived_delta(client):
    yesterday = date.fromordinal(TODAY.toordinal() - 1)
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=yesterday,
                                             recovery_pct=70, hrv_ms=52.0))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY,
                                             recovery_pct=82, hrv_ms=58.0,
                                             day_strain=8.1, sleep_quality_pct=74))
    today = client.get("/api/fitness/today").json()
    assert today["has_data"] is True
    assert today["source"] == "whoop"
    assert today["recovery_pct"] == 82
    assert today["day_strain"] == 8.1
    hrv = next(v for v in today["vitals"] if v["key"] == "hrv")
    assert hrv["value"] == 58.0
    assert hrv["delta"] == 6.0  # 58 - 52, derived on read


def test_today_accepts_date_query(client):
    d = date.fromordinal(TODAY.toordinal() - 5)
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=d, recovery_pct=60))
    today = client.get("/api/fitness/today", params={"date": d.isoformat()}).json()
    assert today["date"] == d.isoformat()
    assert today["recovery_pct"] == 60


def test_workouts_returns_synced_and_manual_newest_first(client):
    store.upsert_workout(NormalizedWorkout(source="whoop", source_id="w-1",
                                           name="Morning Run", sport="running",
                                           started_at=_at(6, 10), duration_min=42,
                                           strain=11.3, calories=520))
    store.create_workout({"name": "Evening Lift", "sport": "strength",
                          "started_at": _at(18, 0), "duration_min": 30})
    rows = client.get("/api/fitness/workouts").json()
    assert [r["name"] for r in rows] == ["Evening Lift", "Morning Run"]  # newest first
    assert {r["source"] for r in rows} == {"manual", "whoop"}
    run = next(r for r in rows if r["name"] == "Morning Run")
    assert run["calories"] == 520
    assert isinstance(run["when"], str) and run["when"]
    assert isinstance(run["icon"], str) and isinstance(run["tint"], str)


def test_workouts_limit_query(client):
    for i in range(3):
        store.create_workout({"name": f"W{i}", "started_at": _at(7 + i),
                              "duration_min": 20})
    rows = client.get("/api/fitness/workouts", params={"limit": 2}).json()
    assert len(rows) == 2


def test_week_strain_trend_shape(client):
    week = client.get("/api/fitness/week").json()
    assert len(week["days"]) == 7
    assert [d["dow"] for d in week["days"]] == ["M", "T", "W", "T", "F", "S", "S"]
    assert "avg_strain" in week and "peak_day" in week


# ---- manual write ----------------------------------------------------------

def test_post_manual_workout_creates_source_manual_row(client):
    res = client.post("/api/fitness/workouts", json={
        "name": "Trail Run", "sport": "running",
        "started_at": _at(6, 30).isoformat(), "duration_min": 55,
        "strain": 12.0, "calories": 600,
    })
    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "manual"
    assert body["name"] == "Trail Run"
    assert body["calories"] == 600
    assert body["id"] in {w["id"] for w in client.get("/api/fitness/workouts").json()}


def test_post_manual_workout_rejects_blank_name(client):
    res = client.post("/api/fitness/workouts", json={
        "name": "", "started_at": _at(6).isoformat(), "duration_min": 30})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_delete_workout(client):
    created = client.post("/api/fitness/workouts", json={
        "name": "Doomed", "started_at": _at(9).isoformat(), "duration_min": 10}).json()
    assert client.delete(f"/api/fitness/workouts/{created['id']}").status_code == 204
    assert client.delete(f"/api/fitness/workouts/{created['id']}").status_code == 404
    assert created["id"] not in {w["id"] for w in client.get("/api/fitness/workouts").json()}


# ---- sync trigger ----------------------------------------------------------

def test_sync_triggers_tick_and_reports_count(client):
    fake = FakeSync(count=4)
    fitness_sync.configure(fake)
    res = client.post("/api/fitness/sync")
    assert res.status_code == 200
    body = res.json()
    assert body["synced"] == 4
    assert isinstance(body["providers"], list)
    assert fake.calls == 1
