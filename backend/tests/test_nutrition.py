"""Nutrition API: day totals, meal CRUD + slot chips, water counter, week trend, targets, food search."""
import re
from datetime import date, timedelta

from app import food_db

TODAY = date.today()
MONDAY = TODAY - timedelta(days=TODAY.weekday())

CLOCK = re.compile(r"^(1[0-2]|[1-9]):[0-5][0-9](am|pm)$")  # e.g. 8:10am

DEFAULT_TARGETS = {
    "calories": 2100, "protein_g": 160, "carbs_g": 210, "fat_g": 70, "water_cups": 8,
}

FOOD_HIT = {
    "fdc_id": 12345,
    "description": "Chicken Wrap",
    "brand": None,
    "serving": "100 g",
    "kcal": 215,
    "protein_g": 14.2,
    "carbs_g": 20.1,
    "fat_g": 8.3,
}


class FakeFood:
    """Stands in for USDA FoodData Central via food_db.configure()."""

    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, query, limit):
        self.calls.append((query, limit))
        return self.hits


def test_day_empty_state(client):
    day = client.get("/api/nutrition/day").json()
    assert day["date"] == TODAY.isoformat()
    assert day["meals"] == []
    assert day["totals"] == {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
    assert day["water"] == {"date": TODAY.isoformat(), "cups": 0, "goal": 8}
    assert day["targets"] == DEFAULT_TARGETS


def test_log_meal_defaults_to_snack_chip(client):
    res = client.post("/api/nutrition/meals", json={"name": "Apple"})
    assert res.status_code == 201
    meal = res.json()
    assert meal["slot"] == "Snack"
    assert (meal["icon"], meal["tint"]) == ("apple", "green")
    assert meal["date"] == TODAY.isoformat()
    assert meal["kcal"] == 0 and meal["protein_g"] == 0
    slot, sep, clock_part = meal["time"].partition(" · ")
    assert (slot, sep) == ("Snack", " · ")
    assert CLOCK.match(clock_part)


def test_meal_chip_is_derived_per_slot(client):
    chips = {
        "Breakfast": ("egg", "honey"),
        "Lunch": ("sandwich", "clay"),
        "Snack": ("apple", "green"),
        "Dinner": ("utensils", "plum"),
    }
    for slot, (icon, tint) in chips.items():
        meal = client.post("/api/nutrition/meals", json={"name": "x", "slot": slot}).json()
        assert (meal["icon"], meal["tint"]) == (icon, tint)
        assert meal["time"].startswith(f"{slot} · ")


def test_negative_kcal_is_rejected(client):
    res = client.post("/api/nutrition/meals", json={"name": "x", "kcal": -5})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_day_totals_sum_across_meals(client):
    client.post("/api/nutrition/meals", json={
        "name": "Eggs", "slot": "Breakfast",
        "kcal": 320, "protein_g": 18.5, "carbs_g": 2.0, "fat_g": 24.0,
    })
    client.post("/api/nutrition/meals", json={
        "name": "Wrap", "slot": "Lunch",
        "kcal": 540, "protein_g": 32.2, "carbs_g": 45.0, "fat_g": 21.5,
    })
    day = client.get("/api/nutrition/day").json()
    assert len(day["meals"]) == 2
    assert day["totals"] == {"kcal": 860, "protein_g": 50.7, "carbs_g": 47.0, "fat_g": 45.5}


def test_patch_meal_updates_kcal(client):
    meal = client.post("/api/nutrition/meals", json={"name": "Wrap", "kcal": 500}).json()
    res = client.patch(f"/api/nutrition/meals/{meal['id']}", json={"kcal": 350})
    assert res.status_code == 200
    assert res.json()["kcal"] == 350
    assert res.json()["name"] == "Wrap"  # untouched
    assert client.patch("/api/nutrition/meals/999", json={"kcal": 1}).status_code == 404


def test_delete_meal(client):
    meal = client.post("/api/nutrition/meals", json={"name": "Doomed"}).json()
    assert client.delete(f"/api/nutrition/meals/{meal['id']}").status_code == 204
    assert client.delete(f"/api/nutrition/meals/{meal['id']}").status_code == 404
    assert client.get("/api/nutrition/day").json()["meals"] == []


def test_water_delta_set_and_floor(client):
    assert client.post("/api/nutrition/water", json={}).json()["cups"] == 1  # default +1
    assert client.post("/api/nutrition/water", json={"delta": 2}).json()["cups"] == 3
    out = client.post("/api/nutrition/water", json={"cups": 5}).json()
    assert out == {"date": TODAY.isoformat(), "cups": 5, "goal": 8}
    assert client.post("/api/nutrition/water", json={"delta": -10}).json()["cups"] == 0


def test_week_trend(client):
    day2 = MONDAY + timedelta(days=1)
    client.post("/api/nutrition/meals", json={"name": "a", "kcal": 500, "date": MONDAY.isoformat()})
    client.post("/api/nutrition/meals", json={"name": "b", "kcal": 600, "date": MONDAY.isoformat()})
    client.post("/api/nutrition/meals", json={"name": "c", "kcal": 3000, "date": day2.isoformat()})
    week = client.get("/api/nutrition/week").json()
    assert len(week["days"]) == 7
    assert [d["dow"] for d in week["days"]] == ["M", "T", "W", "T", "F", "S", "S"]
    assert week["days"][0]["date"] == MONDAY.isoformat()
    assert week["days"][0]["kcal"] == 1100
    assert week["days"][0]["frac"] == round(1100 / 2100, 2)
    assert week["days"][1]["kcal"] == 3000
    assert week["days"][1]["frac"] == 1.0  # capped for the bar chart
    assert all(d["kcal"] == 0 and d["frac"] == 0.0 for d in week["days"][2:])
    assert week["avg_kcal"] == round((1100 + 3000) / 2)  # logged days only
    assert week["days_met"] == 1  # 1100 within goal, 3000 over
    assert week["goal"] == 2100


def test_targets_partial_update_and_validation(client):
    res = client.put("/api/nutrition/targets", json={"calories": 1800, "water_cups": 10})
    assert res.status_code == 200
    assert res.json() == {**DEFAULT_TARGETS, "calories": 1800, "water_cups": 10}
    assert client.get("/api/nutrition/targets").json()["calories"] == 1800
    assert client.put("/api/nutrition/targets", json={"protein_g": 0}).status_code == 422


def test_food_search_offline_is_503_envelope(client):
    res = client.get("/api/nutrition/foods", params={"q": "apple"})
    assert res.status_code == 503
    body = res.json()
    assert body["error"]["code"] == "service_unavailable"
    assert body["error"]["message"]


def test_food_search_with_fake_db(client):
    fake = FakeFood([FOOD_HIT])
    food_db.configure(fake)
    res = client.get("/api/nutrition/foods", params={"q": "chicken wrap", "limit": 3})
    assert res.status_code == 200
    assert res.json() == [FOOD_HIT]
    assert fake.calls == [("chicken wrap", 3)]
