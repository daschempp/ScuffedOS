from datetime import date, timedelta

TODAY = date.today()

RICH_SHAPE = {
    "id", "label", "done", "group", "deadline", "prio", "list", "description",
    "subtasks", "labels", "reminders", "files", "recurrence", "recurrence_label",
    "due", "late", "created_at", "updated_at", "completed_at",
    # Read-time origin markers (M6 School slice-1, contract §H) — additive,
    # default to local/editable for real rows created via this API.
    "source", "editable",
}


def test_create_task_applies_rich_defaults(client):
    res = client.post("/api/tasks", json={"label": "Water the plants"})
    assert res.status_code == 201
    task = res.json()
    assert set(task) == RICH_SHAPE
    assert task["label"] == "Water the plants"
    assert task["done"] is False
    assert task["group"] == "Today"
    assert task["prio"] == "med"
    assert task["list"] == "Personal"
    assert task["deadline"] is None
    assert task["subtasks"] == [] and task["labels"] == []
    assert task["reminders"] == [] and task["files"] == []
    assert task["due"] is None and task["late"] is False
    assert task["created_at"] and task["completed_at"] is None
    assert task["source"] == "local" and task["editable"] is True


def test_create_task_with_full_payload(client):
    deadline = (TODAY + timedelta(days=10)).isoformat()
    res = client.post("/api/tasks", json={
        "label": "Draft Q3 doc",
        "group": "Upcoming",
        "deadline": deadline,
        "prio": "high",
        "list": "Work",
        "description": "Outline goals.",
        "subtasks": [{"id": 1, "label": "Goals", "done": False}],
        "labels": ["planning"],
        "files": [{"id": 1.5, "name": "notes.txt", "size": 120}],
    })
    assert res.status_code == 201
    task = res.json()
    assert task["group"] == "Upcoming"
    assert task["deadline"] == deadline
    assert task["subtasks"] == [{"id": 1, "label": "Goals", "done": False}]
    assert task["files"][0]["name"] == "notes.txt"
    assert task["due"] == (TODAY + timedelta(days=10)).strftime("%b %-d")


def test_list_orders_newest_first(client):
    first = client.post("/api/tasks", json={"label": "First"}).json()
    second = client.post("/api/tasks", json={"label": "Second"}).json()
    tasks = client.get("/api/tasks").json()
    assert [t["id"] for t in tasks] == [second["id"], first["id"]]


def test_due_display_today_overdue_tomorrow(client):
    mk = lambda offset: client.post("/api/tasks", json={
        "label": "x", "deadline": (TODAY + timedelta(days=offset)).isoformat(),
    }).json()
    assert (mk(0)["due"], mk(0)["late"]) == ("Today", False)
    overdue = mk(-2)
    assert (overdue["due"], overdue["late"]) == ("Overdue", True)
    assert mk(1)["due"] == "Tomorrow"


def test_completing_sets_completed_at_and_done_display(client):
    task = client.post("/api/tasks", json={"label": "Pay rent"}).json()
    done = client.patch(f"/api/tasks/{task['id']}", json={"done": True}).json()
    assert done["done"] is True
    assert done["completed_at"] is not None
    assert done["due"].startswith("Done")
    # un-completing clears the completion timestamp
    undone = client.patch(f"/api/tasks/{task['id']}", json={"done": False}).json()
    assert undone["completed_at"] is None


def test_patch_only_touches_sent_fields(client):
    task = client.post("/api/tasks", json={
        "label": "Original", "description": "Keep me", "prio": "high",
    }).json()
    patched = client.patch(f"/api/tasks/{task['id']}", json={"label": "Renamed"}).json()
    assert patched["label"] == "Renamed"
    assert patched["description"] == "Keep me"
    assert patched["prio"] == "high"


def test_patch_null_on_non_nullable_fields_is_ignored(client):
    """R7: explicit null only clears nullable fields; elsewhere it's a no-op."""
    task = client.post("/api/tasks", json={"label": "Keep me", "description": "intact"}).json()
    res = client.patch(f"/api/tasks/{task['id']}", json={"label": None, "description": None})
    assert res.status_code == 200
    assert res.json()["label"] == "Keep me"
    assert res.json()["description"] == "intact"


def test_rows_are_owner_stamped(client):
    from sqlalchemy import select

    from app.config import settings
    from app.models import Task
    from app.store import store

    client.post("/api/tasks", json={"label": "Whose is this?"})
    with store._session() as s:
        owner = s.scalars(select(Task.owner)).one()
    assert owner == settings.owner


def test_patch_null_clears_deadline(client):
    task = client.post("/api/tasks", json={
        "label": "x", "deadline": TODAY.isoformat(),
    }).json()
    patched = client.patch(f"/api/tasks/{task['id']}", json={"deadline": None}).json()
    assert patched["deadline"] is None
    assert patched["due"] is None


def test_patch_replaces_subtasks_wholesale(client):
    task = client.post("/api/tasks", json={
        "label": "x", "subtasks": [{"id": 1, "label": "a", "done": False}],
    }).json()
    new_subs = [{"id": 1, "label": "a", "done": True}, {"id": 2, "label": "b", "done": False}]
    patched = client.patch(f"/api/tasks/{task['id']}", json={"subtasks": new_subs}).json()
    assert patched["subtasks"] == new_subs


def test_group_vocabulary_is_constrained(client):
    res = client.post("/api/tasks", json={"label": "x", "group": "Whenever"})
    assert res.status_code == 422
    res = client.post("/api/tasks", json={"label": "x", "prio": "urgent"})
    assert res.status_code == 422


def test_delete_task(client):
    task = client.post("/api/tasks", json={"label": "Doomed"}).json()
    res = client.delete(f"/api/tasks/{task['id']}")
    assert res.status_code == 204
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 404
    assert client.get("/api/tasks").json() == []


def test_patch_unknown_task_is_404(client):
    assert client.patch("/api/tasks/999", json={"done": True}).status_code == 404


def test_create_task_requires_label(client):
    assert client.post("/api/tasks", json={}).status_code == 422
    assert client.post("/api/tasks", json={"label": ""}).status_code == 422


def test_persistence_across_store_calls(client):
    """Rows live in the DB, not process memory — a second read sees the write."""
    created = client.post("/api/tasks", json={"label": "Durable"}).json()
    fetched = client.get("/api/tasks").json()
    assert fetched[0]["id"] == created["id"]
    assert fetched[0]["label"] == "Durable"
