"""Recurring tasks (M3): RRULE validation and complete-spawns-next semantics."""
from datetime import date, datetime, timedelta, timezone

TODAY = date.today()


def _make(client, **overrides) -> dict:
    res = client.post("/api/tasks", json={"label": "Meal prep", **overrides})
    assert res.status_code == 201
    return res.json()


def _complete(client, task_id: int) -> dict:
    res = client.patch(f"/api/tasks/{task_id}", json={"done": True})
    assert res.status_code == 200
    return res.json()


def _spawn_of(client, old_id: int) -> dict:
    rows = [t for t in client.get("/api/tasks").json() if t["id"] != old_id]
    assert len(rows) == 1, f"expected exactly one spawned task, got {len(rows)}"
    return rows[0]


def test_create_with_weekly_recurrence_gets_label(client):
    task = _make(
        client,
        recurrence="FREQ=WEEKLY",
        deadline=(TODAY + timedelta(days=7)).isoformat(),
    )
    assert task["recurrence"] == "FREQ=WEEKLY"
    assert task["recurrence_label"] == "Repeats weekly"


def test_invalid_rrule_rejected_on_create_and_patch(client):
    res = client.post("/api/tasks", json={"label": "x", "recurrence": "FREQ=BOGUS"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"

    task = _make(client)
    res = client.patch(f"/api/tasks/{task['id']}", json={"recurrence": "FREQ=BOGUS"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_completing_recurring_task_spawns_next_occurrence(client):
    old_deadline = TODAY + timedelta(days=7)
    task = _make(
        client,
        recurrence="FREQ=WEEKLY",
        deadline=old_deadline.isoformat(),
        prio="high",
        list="Health",
        labels=["food"],
        subtasks=[
            {"id": 1, "label": "Buy groceries", "done": True},
            {"id": 2, "label": "Cook", "done": False},
        ],
    )
    done = _complete(client, task["id"])
    assert done["done"] is True
    assert done["recurrence"] is None
    assert done["recurrence_label"] is None

    spawn = _spawn_of(client, task["id"])
    assert spawn["done"] is False
    next_deadline = date.fromisoformat(spawn["deadline"])
    assert next_deadline > max(old_deadline, TODAY)
    assert next_deadline == old_deadline + timedelta(days=7)
    assert spawn["label"] == task["label"]
    assert spawn["prio"] == "high"
    assert spawn["list"] == "Health"
    assert spawn["labels"] == ["food"]
    assert [s["label"] for s in spawn["subtasks"]] == ["Buy groceries", "Cook"]
    assert all(s["done"] is False for s in spawn["subtasks"])
    assert spawn["recurrence"] == "FREQ=WEEKLY"
    assert spawn["group"] == "Upcoming"


def test_spawn_lands_in_today_group_when_next_is_today(client):
    # Hourly rule anchored yesterday: the next occurrence after today-noon is
    # still today, so the spawn belongs in the Today group.
    task = _make(
        client,
        recurrence="FREQ=HOURLY",
        deadline=(TODAY - timedelta(days=1)).isoformat(),
    )
    _complete(client, task["id"])
    spawn = _spawn_of(client, task["id"])
    assert spawn["deadline"] == TODAY.isoformat()
    assert spawn["group"] == "Today"


def test_reminders_copied_to_spawn_shifted_by_deadline_delta(client):
    old_deadline = TODAY + timedelta(days=7)
    task = _make(
        client, recurrence="FREQ=WEEKLY", deadline=old_deadline.isoformat()
    )
    remind_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7)
    res = client.post(
        f"/api/tasks/{task['id']}/reminders",
        json={"remind_at": remind_at.isoformat(), "label": "prep tonight"},
    )
    assert res.status_code == 201

    done = _complete(client, task["id"])
    # The completed row keeps its own reminder, unshifted.
    assert len(done["reminders"]) == 1
    assert datetime.fromisoformat(done["reminders"][0]["remind_at"]) == remind_at

    spawn = _spawn_of(client, task["id"])
    assert len(spawn["reminders"]) == 1
    copied = spawn["reminders"][0]
    assert copied["label"] == "prep tonight"
    # Next deadline is a week out, so the reminder shifts by exactly 7 days.
    assert datetime.fromisoformat(copied["remind_at"]) == remind_at + timedelta(days=7)


def test_recompleting_after_uncomplete_does_not_spawn_again(client):
    task = _make(
        client,
        recurrence="FREQ=WEEKLY",
        deadline=(TODAY + timedelta(days=7)).isoformat(),
    )
    _complete(client, task["id"])
    assert len(client.get("/api/tasks").json()) == 2
    # Un-complete the (now rule-less) old row, then complete it again.
    client.patch(f"/api/tasks/{task['id']}", json={"done": False})
    redone = _complete(client, task["id"])
    assert redone["recurrence"] is None
    assert len(client.get("/api/tasks").json()) == 2


def test_count_exhausted_strips_rule_and_spawns_nothing(client):
    # COUNT=1 anchored at its own deadline: the only occurrence is the deadline
    # itself, so there is no "next" — the rule comes off and nothing spawns.
    task = _make(
        client, recurrence="FREQ=DAILY;COUNT=1", deadline=TODAY.isoformat()
    )
    done = _complete(client, task["id"])
    assert done["done"] is True
    assert done["recurrence"] is None
    assert len(client.get("/api/tasks").json()) == 1


def test_patch_null_recurrence_clears_rule(client):
    task = _make(
        client,
        recurrence="FREQ=WEEKLY",
        deadline=(TODAY + timedelta(days=7)).isoformat(),
    )
    res = client.patch(f"/api/tasks/{task['id']}", json={"recurrence": None})
    assert res.status_code == 200
    assert res.json()["recurrence"] is None
    assert res.json()["recurrence_label"] is None
    # The rule is really gone: completing no longer spawns.
    _complete(client, task["id"])
    assert len(client.get("/api/tasks").json()) == 1


def test_count_budget_terminates_after_exactly_n_occurrences(client):
    """COUNT=3 means three occurrences total — the rule must not restart its
    count when it re-anchors on each spawned task."""
    task = _make(client, recurrence="FREQ=DAILY;COUNT=3", deadline=TODAY.isoformat())
    done = _complete(client, task["id"])
    assert done["recurrence"] is None
    second = _spawn_of(client, task["id"])
    assert second["recurrence"] == "FREQ=DAILY;COUNT=2"

    done2 = _complete(client, second["id"])
    assert done2["recurrence"] is None
    third = [t for t in client.get("/api/tasks").json() if not t["done"]]
    assert len(third) == 1
    assert third[0]["recurrence"] == "FREQ=DAILY;COUNT=1"

    # Third (final) occurrence: completing it must spawn nothing.
    _complete(client, third[0]["id"])
    rows = client.get("/api/tasks").json()
    assert len(rows) == 3
    assert all(t["done"] for t in rows)


def test_dtstart_smuggled_into_rule_is_rejected(client):
    res = client.post("/api/tasks", json={
        "label": "x",
        "recurrence": "DTSTART:20260601T090000\nRRULE:FREQ=WEEKLY",
        "deadline": TODAY.isoformat(),
    })
    assert res.status_code == 422
