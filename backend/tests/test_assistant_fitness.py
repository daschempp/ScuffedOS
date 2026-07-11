"""M4 assistant: fitness tools are wired and the model composes a fitness read
with the existing calendar/task writes (no bespoke 'fitness action' mechanism)."""
import json
from datetime import date, datetime, timedelta

from app import assistant, llm, tools
from app.store import store

from .fakes import FakeLLM, text_turn, tool_block, tool_turn

FITNESS_TOOLS = {
    "get_fitness_today", "get_workouts", "get_fitness_week",
    "get_fitness_status", "log_workout", "sync_fitness",
}


def chat(client, message: str, conversation_id=None) -> dict:
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    res = client.post("/api/assistant/chat", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_all_six_fitness_tools_are_in_the_definitions():
    names = {t["name"] for t in tools.DEFINITIONS}
    assert FITNESS_TOOLS <= names
    # The seed reader is gone — get_fitness_today now reads the real store.
    fit = next(t for t in tools.TOOLS if t["name"] == "get_fitness_today")
    assert fit["run"].__name__ == "_get_fitness_today"


def test_persona_presents_fitness_as_live_and_composable():
    persona = assistant._PERSONA.lower()
    # Finance is live from M7 — the persona must NOT still call it read-only or sample.
    assert "read-only" not in persona and "sample data" not in persona
    # Finance writes exist but are local budgets only (they never move real money).
    assert "never move real money" in persona
    # ...and the model is told it can act on fitness by composing a calendar/task write.
    assert "compose" in persona or "create_event" in persona
    # And get_fitness_today's description nudges toward acting, not just reading.
    fit = next(t for t in tools.DEFINITIONS if t["name"] == "get_fitness_today")
    assert "create_event" in fit["description"] or "schedule" in fit["description"].lower()


def test_model_reads_fitness_then_schedules_via_create_event(client):
    """'I'm well recovered, find me a workout slot tomorrow' -> read fitness,
    then create_event. Proves the composition path with no new mechanism."""
    snap = __import__("app.providers.base", fromlist=["NormalizedSnapshot"]).NormalizedSnapshot(
        source="whoop", day=date.today(), recovery_pct=88, day_strain=4.0,
    )
    store.upsert_snapshot(snap)
    tomorrow = date.today() + timedelta(days=1)
    fake = FakeLLM(
        tool_turn(tool_block("get_fitness_today", {}, "f1")),
        tool_turn(tool_block("create_event", {
            "title": "Strength session",
            "start": f"{tomorrow.isoformat()}T07:00",
        }, "e1")),
        text_turn("You're 88% recovered — booked a strength session at 7am tomorrow."),
    )
    llm.configure(fake)
    body = chat(client, "I'm well recovered, find me a workout slot tomorrow morning")

    # The fitness read returned real normalized data (no SAMPLE disclaimer).
    # messages[-3] is the fitness tool_result (the list is mutated in-place by later rounds;
    # at final state: [user, assistant(fit_use), user(fit_result), assistant(ce_use), user(ce_result)]).
    fit_result = json.loads(fake.calls[1]["messages"][-3]["content"][0]["content"])
    assert fit_result["recovery_pct"] == 88
    assert "SAMPLE" not in json.dumps(fit_result)
    # And the composed write actually created a calendar event + a calendar action.
    events = client.get("/api/calendar/events", params={
        "from": f"{tomorrow.isoformat()}T00:00:00",
        "to": f"{(tomorrow + timedelta(days=1)).isoformat()}T00:00:00",
    }).json()
    assert "Strength session" in {e["title"] for e in events}
    assert body["actions"][0]["screen"] == "calendar"


def test_log_workout_tool_creates_manual_workout_and_action(client):
    started = datetime.now().astimezone().replace(microsecond=0)
    fake = FakeLLM(
        tool_turn(tool_block("log_workout", {
            "name": "Morning run", "sport": "running",
            "started_at": started.isoformat(), "duration_min": 32,
        })),
        text_turn("Logged your 32-minute run."),
    )
    llm.configure(fake)
    body = chat(client, "log a 32 minute run I just did")

    workouts = client.get("/api/fitness/workouts").json()
    assert [w["name"] for w in workouts] == ["Morning run"]
    assert workouts[0]["source"] == "manual"
    assert body["actions"][0]["screen"] == "fitness"
    assert body["actions"][0]["cta"] == "View fitness"
