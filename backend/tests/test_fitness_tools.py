"""Assistant fitness tools (M4): reads over normalized tables, manual log_workout,
sync_fitness — replacing the old seed get_fitness_today reader."""
import json
from datetime import date, datetime, timezone

from app import fitness_sync, llm, tools
from app.providers.base import NormalizedSnapshot, NormalizedWorkout
from app.store import store

from .fakes import FakeLLM, text_turn, tool_block, tool_turn

TODAY = date.today()


def chat(client, message: str) -> dict:
    res = client.post("/api/assistant/chat", json={"message": message})
    assert res.status_code == 200, res.text
    return res.json()


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute, tzinfo=timezone.utc)


class FakeSync:
    def __init__(self, count=2):
        self.count = count
        self.calls = 0

    def tick(self, now=None) -> int:
        self.calls += 1
        return self.count


def test_seed_fitness_reader_is_gone():
    # The old sample reader and its seed import must be removed.
    assert "FITNESS_TODAY" not in tools.__dict__
    names = {t["name"] for t in tools.TOOLS}
    assert {"get_fitness_today", "get_workouts", "get_fitness_week",
            "get_fitness_status", "log_workout", "sync_fitness"} <= names


def test_get_fitness_today_reads_real_snapshot(client):
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=TODAY,
                                             recovery_pct=82, day_strain=8.1,
                                             hrv_ms=58.0))
    result_json, action = tools.execute("get_fitness_today", {})
    result = json.loads(result_json)
    assert action is None
    assert result["recovery_pct"] == 82
    assert result["has_data"] is True
    assert "SAMPLE" not in result_json


def test_get_workouts_lists_real_rows(client):
    store.upsert_workout(NormalizedWorkout(source="whoop", source_id="w-1",
                                           name="Run", sport="running",
                                           started_at=_at(6, 10), duration_min=42))
    result_json, action = tools.execute("get_workouts", {})
    result = json.loads(result_json)
    assert action is None
    assert [w["name"] for w in result["workouts"]] == ["Run"]


def test_get_fitness_week_and_status(client):
    week_json, _ = tools.execute("get_fitness_week", {})
    assert len(json.loads(week_json)["days"]) == 7
    status_json, _ = tools.execute("get_fitness_status", {})
    status = json.loads(status_json)
    assert "providers" in status


def test_log_workout_tool_creates_manual_row(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("log_workout", {
            "name": "Evening Lift", "sport": "strength",
            "started_at": _at(18, 0).isoformat(), "duration_min": 30,
        })),
        text_turn("Logged your lift."),
    ))
    body = chat(client, "I lifted this evening for half an hour")

    workouts = client.get("/api/fitness/workouts").json()
    assert [w["name"] for w in workouts] == ["Evening Lift"]
    assert workouts[0]["source"] == "manual"
    assert body["actions"][0]["screen"] == "fitness"
    assert body["actions"][0]["title"] == "Workout logged"


def test_sync_fitness_tool_triggers_tick(client):
    fake = FakeSync(count=2)
    fitness_sync.configure(fake)
    llm.configure(FakeLLM(
        tool_turn(tool_block("sync_fitness", {})),
        text_turn("Synced your WHOOP."),
    ))
    body = chat(client, "sync my whoop")
    assert fake.calls == 1
    assert body["actions"][0]["screen"] == "fitness"
    assert body["actions"][0]["title"] == "Fitness synced"
