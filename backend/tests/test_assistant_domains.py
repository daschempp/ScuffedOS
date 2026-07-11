"""M3 assistant tools: calendar, habits, nutrition, reminders, recurrence through the chat loop."""
import json
from datetime import date, timedelta

from app import food_db, llm
from app.store import store

from .fakes import FakeLLM, text_turn, tool_block, tool_turn


def chat(client, message: str, conversation_id=None) -> dict:
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    res = client.post("/api/assistant/chat", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _tool_result(fake: FakeLLM, call: int = 1, index: int = 0) -> dict:
    """The tool_result JSON fed back to the model on a follow-up call."""
    return json.loads(fake.calls[call]["messages"][-1]["content"][index]["content"])


def _next_friday() -> date:
    today = date.today()
    return today + timedelta(days=(4 - today.weekday()) % 7 or 7)


class FakeFood:
    def search(self, query, limit=5):
        return [{"fdc_id": 171534, "description": "Chicken Wrap", "brand": None,
                 "serving": "100 g", "kcal": 240, "protein_g": 18.0,
                 "carbs_g": 20.0, "fat_g": 9.0}]


def test_moodle_tool_through_chat_returns_school_action(client):
    """Regression: a Moodle tool emits an action card with screen='school'.
    The chat response model must accept it — otherwise /chat 500s and the
    stored card poisons every later /conversation reload."""
    llm.configure(FakeLLM(
        tool_turn(tool_block("get_courses", {})),
        text_turn("Here are your courses."),
    ))
    body = chat(client, "what courses am I in?")
    assert body["actions"][0]["screen"] == "school"


def test_create_event_tool_creates_real_event(client):
    friday = _next_friday()
    llm.configure(FakeLLM(
        tool_turn(tool_block("create_event", {"title": "Dentist",
                                              "start": f"{friday.isoformat()}T14:00"})),
        text_turn("Booked the dentist for Friday at 2pm."),
    ))
    body = chat(client, "dentist next friday 2pm")

    # The naive datetime was local time; query a window wide enough for any tz.
    events = client.get("/api/calendar/events", params={
        "from": f"{(friday - timedelta(days=1)).isoformat()}T00:00:00",
        "to": f"{(friday + timedelta(days=2)).isoformat()}T00:00:00",
    }).json()
    assert "Dentist" in {e["title"] for e in events}
    assert body["actions"][0]["screen"] == "calendar"
    assert body["actions"][0]["title"] == "Added to Calendar"


def test_log_water_tool_adds_cups(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("log_water", {"delta": 2})),
        text_turn("Two cups logged."),
    ))
    body = chat(client, "I drank two glasses of water")

    assert client.get("/api/nutrition/day").json()["water"]["cups"] == 2
    assert body["actions"][0]["screen"] == "nutrition"
    assert body["actions"][0]["title"] == "Water logged"


def test_log_meal_tool_files_a_real_meal(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("log_meal", {"name": "Chicken wrap", "slot": "Lunch",
                                          "kcal": 540, "protein_g": 38})),
        text_turn("Logged your lunch."),
    ))
    body = chat(client, "I had a chicken wrap for lunch")

    meals = client.get("/api/nutrition/day").json()["meals"]
    assert [m["name"] for m in meals] == ["Chicken wrap"]
    assert meals[0]["kcal"] == 540
    assert body["actions"][0]["title"] == "Lunch logged"
    assert body["actions"][0]["screen"] == "nutrition"


def test_toggle_habit_matches_by_name_and_dedupes(client):
    habit = store.create_habit({"name": "Meditate"})
    fake = FakeLLM(
        tool_turn(tool_block("toggle_habit", {"name": "meditate"})),
        text_turn("Nice — meditation done."),
        tool_turn(tool_block("toggle_habit", {"name": "meditate", "done": True})),
        text_turn("Already checked off."),
    )
    llm.configure(fake)

    body = chat(client, "I meditated this morning")
    week = client.get("/api/habits").json()
    meditate = next(h for h in week["habits"] if h["id"] == habit["id"])
    assert meditate["days"][week["today_index"]] is True
    assert week["done_today"] == 1
    assert body["actions"][0]["screen"] == "habits"
    assert body["actions"][0]["title"] == "Habit checked off"

    # Toggling an already-done habit reports it without flipping or acting.
    again = chat(client, "I meditated, did you log it?")
    assert again["actions"] == []
    assert _tool_result(fake, call=3)["already"] is True
    assert client.get("/api/habits").json()["done_today"] == 1


def test_search_food_returns_hits_from_the_db(client):
    food_db.configure(FakeFood())
    fake = FakeLLM(
        tool_turn(tool_block("search_food", {"query": "chicken wrap"})),
        text_turn("A chicken wrap is about 240 kcal per 100 g."),
    )
    llm.configure(fake)
    chat(client, "how many calories in a chicken wrap?")

    result = _tool_result(fake)
    assert result["foods"][0]["description"] == "Chicken Wrap"
    assert "per 100 g" in result["note"]


def test_search_food_unavailable_tells_model_to_estimate(client):
    # conftest leaves food_db configured to None — the network-down case.
    fake = FakeLLM(
        tool_turn(tool_block("search_food", {"query": "chicken wrap"})),
        text_turn("Roughly 450 kcal — that's an estimate."),
    )
    llm.configure(fake)
    body = chat(client, "log a chicken wrap")

    result = _tool_result(fake)
    assert "estimate the macros yourself" in result["error"]
    assert body["actions"] == []


def test_domain_reads_are_real_data_no_sample_disclaimers(client, seeded):
    monday = date.today() - timedelta(days=date.today().weekday())
    fake = FakeLLM(
        tool_turn(
            tool_block("get_calendar", {"date": monday.isoformat(), "days": 7}, "t1"),
            tool_block("get_habits_today", {}, "t2"),
            tool_block("get_nutrition_today", {}, "t3"),
            tool_block("get_finance_summary", {}, "t4"),
        ),
        text_turn("Here's your day."),
    )
    llm.configure(fake)
    chat(client, "how's everything looking?")

    results = fake.calls[1]["messages"][-1]["content"]
    by_id = {r["tool_use_id"]: r["content"] for r in results}
    for built in ("t1", "t2", "t3", "t4"):  # M3 + M7 finance: real rows, no disclaimer
        assert "SAMPLE" not in by_id[built]
    assert len(json.loads(by_id["t1"])["events"]) > 0
    assert json.loads(by_id["t2"])["done_today"] == 2
    assert json.loads(by_id["t3"])["totals"]["kcal"] == 1690
    assert "balance" in json.loads(by_id["t4"])  # finance is real from M7


def test_add_task_reminder_tool_creates_firing_row(client):
    task = store.create_task({"label": "Call mom"})
    tomorrow = date.today() + timedelta(days=1)
    llm.configure(FakeLLM(
        tool_turn(tool_block("add_task_reminder", {
            "task_id": task["id"],
            "remind_at": f"{tomorrow.isoformat()}T09:00",
            "label": "9am tomorrow",
        })),
        text_turn("I'll remind you at 9am tomorrow."),
    ))
    body = chat(client, "remind me to call mom tomorrow at 9")

    rows = store.list_task_reminders(task["id"])
    assert len(rows) == 1 and rows[0]["display"] == "9am tomorrow"
    assert body["actions"][0]["title"] == "Reminder set"
    assert body["actions"][0]["screen"] == "tasks"


def test_create_task_with_recurrence_keeps_the_rule(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("create_task", {"label": "Meal prep",
                                             "recurrence": "FREQ=WEEKLY"})),
        text_turn("Weekly meal prep is on your list."),
    ))
    body = chat(client, "add a weekly meal prep task")

    task = client.get("/api/tasks").json()[0]
    assert task["recurrence"] == "FREQ=WEEKLY"
    assert task["recurrence_label"] == "Repeats weekly"
    assert body["actions"][0]["title"] == "Added to Tasks"


def test_create_task_invalid_recurrence_is_error_not_exception(client):
    fake = FakeLLM(
        tool_turn(tool_block("create_task", {"label": "x", "recurrence": "FREQ=BOGUS"})),
        text_turn("That repeat rule didn't parse — try 'weekly'."),
    )
    llm.configure(fake)
    body = chat(client, "repeat it bogusly")

    assert "Invalid recurrence rule" in _tool_result(fake)["error"]
    assert body["actions"] == []
    assert client.get("/api/tasks").json() == []  # nothing was created


def test_toggle_habit_honors_done_state_for_past_weeks(client):
    """'Actually I didn't work out last Friday' on an already-unmarked day
    must NOT create a completion — the dedupe guard has to read the target
    week's grid, not the current week's."""
    habit = store.create_habit({"name": "Workout"})
    last_friday = date.today() - timedelta(days=date.today().weekday() + 3)

    llm.configure(FakeLLM(
        tool_turn(tool_block("toggle_habit", {
            "name": "workout", "date": last_friday.isoformat(), "done": False,
        })),
        text_turn("Noted."),
    ))
    fake = llm._override
    chat(client, "actually I didn't work out last Friday")
    result = _tool_result(fake)
    assert result.get("already") is False

    from app import recurrence
    week = store.habits_week(recurrence.week_start(last_friday))
    row = next(h for h in week["habits"] if h["id"] == habit["id"])
    assert row["days"][last_friday.weekday()] is False

    # And marking it done for that past day works, exactly once.
    llm.configure(FakeLLM(
        tool_turn(tool_block("toggle_habit", {
            "name": "workout", "date": last_friday.isoformat(), "done": True,
        })),
        text_turn("Marked."),
    ))
    chat(client, "I did work out last Friday after all")
    week = store.habits_week(recurrence.week_start(last_friday))
    row = next(h for h in week["habits"] if h["id"] == habit["id"])
    assert row["days"][last_friday.weekday()] is True
