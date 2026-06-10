from app.assistant import clean_event, clean_title


def chat(client, message: str) -> dict:
    res = client.post("/api/assistant/chat", json={"message": message})
    assert res.status_code == 200
    return res.json()


def test_explicit_task_phrasing_makes_task(client):
    body = chat(client, "add a task to call the dentist")
    assert body["action"]["screen"] == "tasks"
    assert body["action"]["makeTask"] == "Call the dentist"


def test_remind_me_makes_task(client):
    body = chat(client, "remind me to pay rent")
    assert body["action"]["makeTask"] == "Pay rent"


def test_plan_my_day_targets_home(client):
    body = chat(client, "plan my day")
    assert body["action"]["screen"] == "home"
    assert body["action"].get("makeTask") is None


def test_transfer_targets_finance(client):
    body = chat(client, "move $120 to savings")
    assert body["action"]["screen"] == "finance"


def test_spending_targets_finance(client):
    body = chat(client, "how much did I spend on dining?")
    assert body["action"]["screen"] == "finance"


def test_schedule_targets_calendar_with_cleaned_event(client):
    body = chat(client, "schedule design review")
    assert body["action"]["screen"] == "calendar"
    assert "Design review" in body["text"]


def test_log_meal_targets_nutrition(client):
    body = chat(client, "log lunch")
    assert body["action"]["screen"] == "nutrition"


def test_remember_targets_memory(client):
    body = chat(client, "remember mom's birthday is March 14")
    assert body["action"]["screen"] == "memory"


def test_fallback_has_no_action(client):
    body = chat(client, "xyzzy plugh")
    assert body["action"] is None
    assert body["text"]


def test_chat_never_writes_to_the_store(client):
    # The endpoint is stateless: even a makeTask reply must not create the task
    # server-side — the client owns the follow-up POST.
    chat(client, "add a task to water the plants")
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 5
    assert all(t["label"] != "Water the plants" for t in tasks)


def test_chat_is_deterministic(client):
    first = chat(client, "add a task to water the plants")
    second = chat(client, "add a task to water the plants")
    assert first == second


def test_clean_title_strips_prefixes_and_punctuation():
    assert clean_title("remind me to call mom.") == "Call mom"
    assert clean_title("please add a task to book flights!") == "Book flights"


def test_clean_event_strips_scheduling_prefix():
    assert clean_event("schedule a meeting for design review") == "Design review"
    assert clean_event("schedule") == "New event"
