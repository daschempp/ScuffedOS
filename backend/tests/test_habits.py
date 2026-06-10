"""Habits API: defaults, schedule validation, toggle/streak walk, week grid, water auto-complete."""
from datetime import date, timedelta

TODAY = date.today()
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def test_create_habit_applies_defaults(client):
    res = client.post("/api/habits", json={"name": "Read"})
    assert res.status_code == 201
    habit = res.json()
    assert habit["name"] == "Read"
    assert habit["icon"] == "check"
    assert habit["tint"] == "green"
    assert habit["schedule"] == [0, 1, 2, 3, 4, 5, 6]
    assert habit["link"] is None
    assert habit["streak"] == 0 and habit["best_streak"] == 0
    assert habit["days"] == [False] * 7


def test_schedule_weekdays_are_validated(client):
    res = client.post("/api/habits", json={"name": "x", "schedule": [0, 8]})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_toggle_marks_today_and_starts_streak(client):
    habit = client.post("/api/habits", json={"name": "Stretch"}).json()
    res = client.post(f"/api/habits/{habit['id']}/toggle")
    assert res.status_code == 200
    body = res.json()
    assert body["days"][TODAY.weekday()] is True
    assert body["streak"] == 1


def test_toggle_twice_removes_completion(client):
    habit = client.post("/api/habits", json={"name": "Stretch"}).json()
    client.post(f"/api/habits/{habit['id']}/toggle")
    body = client.post(f"/api/habits/{habit['id']}/toggle").json()
    assert body["days"][TODAY.weekday()] is False
    assert body["streak"] == 0


def test_yesterday_plus_today_is_streak_two(client):
    habit = client.post("/api/habits", json={"name": "Run"}).json()
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    client.post(f"/api/habits/{habit['id']}/toggle", json={"date": yesterday})
    body = client.post(f"/api/habits/{habit['id']}/toggle").json()
    assert body["streak"] == 2


def test_weekend_gap_does_not_break_weekday_streak(client):
    habit = client.post(
        "/api/habits", json={"name": "Gym", "schedule": [0, 1, 2, 3, 4]}
    ).json()
    last_monday = MONDAY - timedelta(days=7)
    done = [last_monday + timedelta(days=i) for i in range(5)]  # last week Mon-Fri
    # This week's weekdays strictly before today; today stays unfinished —
    # the streak walk doesn't count an open today against the streak.
    done += [MONDAY + timedelta(days=i) for i in range(min(TODAY.weekday(), 5))]
    for d in done:
        res = client.post(
            f"/api/habits/{habit['id']}/toggle", json={"date": d.isoformat()}
        )
        assert res.status_code == 200
    got = client.get("/api/habits").json()["habits"][0]
    # Walk rules: Sat/Sun aren't scheduled so the weekend gap is skipped —
    # all 5 of last week's weekdays plus this week's elapsed weekdays count.
    assert got["streak"] == 5 + min(TODAY.weekday(), 5)
    assert got["best_streak"] == got["streak"]


def test_habits_week_grid_and_percentages(client):
    habit = client.post("/api/habits", json={"name": "Floss"}).json()
    client.post(f"/api/habits/{habit['id']}/toggle")
    week = client.get("/api/habits").json()
    assert week["week_start"] == MONDAY.isoformat()
    assert week["today_index"] == TODAY.weekday()
    assert week["done_today"] == 1
    assert week["habits"][0]["days"][TODAY.weekday()] is True
    # one completion over the scheduled slots elapsed so far this week
    assert week["week_pct"] == round(100 * 1 / (TODAY.weekday() + 1))
    assert week["prev_week_pct"] == 0


def test_week_query_returns_past_week_grid(client):
    habit = client.post("/api/habits", json={"name": "Journal"}).json()
    prev_monday = MONDAY - timedelta(days=7)
    client.post(
        f"/api/habits/{habit['id']}/toggle", json={"date": prev_monday.isoformat()}
    )
    # any day inside the previous week snaps to its Monday
    prev_wednesday = prev_monday + timedelta(days=2)
    res = client.get("/api/habits", params={"week": prev_wednesday.isoformat()})
    assert res.status_code == 200
    body = res.json()
    assert body["week_start"] == prev_monday.isoformat()
    assert body["today_index"] is None
    assert body["habits"][0]["days"] == [True] + [False] * 6


def test_patch_renames_and_retints(client):
    habit = client.post("/api/habits", json={"name": "Old", "tint": "sky"}).json()
    res = client.patch(f"/api/habits/{habit['id']}", json={"name": "New", "tint": "plum"})
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "New"
    assert body["tint"] == "plum"
    assert body["icon"] == "check"  # untouched
    assert client.patch("/api/habits/999", json={"name": "x"}).status_code == 404


def test_delete_habit_removes_completions(client):
    from sqlalchemy import select

    from app.models import HabitCompletion
    from app.store import store

    habit = client.post("/api/habits", json={"name": "Doomed"}).json()
    client.post(f"/api/habits/{habit['id']}/toggle")
    assert client.delete(f"/api/habits/{habit['id']}").status_code == 204
    assert client.delete(f"/api/habits/{habit['id']}").status_code == 404
    assert client.post(f"/api/habits/{habit['id']}/toggle").status_code == 404
    with store._session() as s:
        assert s.scalars(select(HabitCompletion)).all() == []


def test_water_goal_auto_completes_linked_habit(client):
    client.post("/api/habits", json={"name": "Hydrate", "link": "water"})
    client.post("/api/nutrition/water", json={"cups": 8})  # default goal is 8
    week = client.get("/api/habits").json()
    assert week["habits"][0]["days"][TODAY.weekday()] is True
    assert week["done_today"] == 1
    # dropping back under the goal retracts the auto completion
    client.post("/api/nutrition/water", json={"cups": 5})
    week = client.get("/api/habits").json()
    assert week["habits"][0]["days"][TODAY.weekday()] is False
    assert week["done_today"] == 0


def test_manual_toggle_survives_water_dropping(client):
    habit = client.post("/api/habits", json={"name": "Hydrate", "link": "water"}).json()
    client.post(f"/api/habits/{habit['id']}/toggle")  # manual tap
    client.post("/api/nutrition/water", json={"cups": 8})
    client.post("/api/nutrition/water", json={"cups": 2})  # back under the goal
    week = client.get("/api/habits").json()
    assert week["habits"][0]["days"][TODAY.weekday()] is True
