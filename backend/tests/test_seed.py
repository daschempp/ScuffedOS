"""Demo seed: prototype rows across every M3 domain, idempotent per domain."""
from app.store import store


def test_seed_demo_populates_prototype_rows(client, seeded):
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 10
    today = [t for t in tasks if t["group"] == "Today"]
    assert len(today) == 5  # the Home dashboard's five
    labels = {t["label"] for t in today}
    assert "Pay rent" in labels and "Book dentist follow-up" in labels

    dentist = next(t for t in tasks if t["label"] == "Book dentist follow-up")
    assert dentist["due"] == "Overdue" and dentist["late"] is True
    rent = next(t for t in tasks if t["label"] == "Pay rent")
    assert rent["done"] is True and rent["due"].startswith("Done")

    memories = client.get("/api/memory").json()
    assert len(memories) == 4
    assert memories[0]["when"] == "2 days ago"


def test_seed_demo_is_idempotent(seeded):
    assert store.seed_demo() is False
    assert len(store.list_tasks()) == 10


def test_seed_creates_weeks_events_with_recurrence(client, seeded):
    occurrences = client.get("/api/calendar/events").json()  # current Mon-start week
    assert len({o["id"] for o in occurrences}) == 7
    recurring_ids = {o["id"] for o in occurrences if o["recurring"]}
    assert len(recurring_ids) == 2
    standups = [o for o in occurrences if o["title"] == "Team standup"]
    assert len(standups) == 3  # FREQ=WEEKLY;BYDAY=MO,WE,FR expands in-week


def test_seed_habits_streaks_and_done_today(client, seeded):
    week = client.get("/api/habits").json()
    assert week["done_today"] == 2  # Meditate + Read 20 min
    by_name = {h["name"]: h for h in week["habits"]}
    assert set(by_name) == {"Meditate", "Read 20 min", "Workout",
                            "Sleep by 11", "Drink 8 cups water"}
    assert [by_name[n]["streak"] for n in
            ("Meditate", "Read 20 min", "Workout", "Sleep by 11",
             "Drink 8 cups water")] == [12, 5, 3, 8, 2]
    idx = week["today_index"]
    assert by_name["Meditate"]["days"][idx] is True
    assert by_name["Workout"]["days"][idx] is False


def test_seed_nutrition_day_and_targets(client, seeded):
    day = client.get("/api/nutrition/day").json()
    assert len(day["meals"]) == 4
    assert day["totals"]["kcal"] == 1690
    assert day["water"]["cups"] == 5
    assert day["targets"] == {"calories": 2100, "protein_g": 160,
                              "carbs_g": 210, "fat_g": 70, "water_cups": 8}


def test_seed_task_reminders_are_rows(client, seeded):
    tasks = client.get("/api/tasks").json()
    assert sum(len(t["reminders"]) for t in tasks) == 3
    priya = next(t for t in tasks if t["label"] == "Reply to Priya about Lighthouse")
    assert priya["reminders"][0]["display"] == "1 hour before"


def test_seed_up_next_is_non_empty(client, seeded):
    up_next = client.get("/api/calendar/up-next").json()
    assert len(up_next) > 0


def test_seed_is_idempotent_per_domain(client, seeded):
    """Wiping one domain and re-seeding refills only that domain."""
    for event_id in {o["id"] for o in client.get("/api/calendar/events").json()}:
        assert client.delete(f"/api/calendar/events/{event_id}").status_code == 204
    assert client.get("/api/calendar/events").json() == []

    assert store.seed_demo() is True  # events re-seed…
    assert len({o["id"] for o in client.get("/api/calendar/events").json()}) == 7
    assert len(store.list_tasks()) == 10  # …other domains untouched
    assert len(store.list_memories()) == 4
    assert len(client.get("/api/habits").json()["habits"]) == 5
    assert store.seed_demo() is False  # and everything is full again
