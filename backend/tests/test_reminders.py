"""Task reminders (M3): CRUD rows, embedded display, and the firing tick."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import reminders
from app.models import TaskReminder
from app.store import store


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _make_task(client, **overrides) -> dict:
    res = client.post("/api/tasks", json={"label": "Water the plants", **overrides})
    assert res.status_code == 201
    return res.json()


def _add_reminder(client, task_id: int, remind_at: datetime, label: str = "") -> dict:
    res = client.post(
        f"/api/tasks/{task_id}/reminders",
        json={"remind_at": remind_at.isoformat(), "label": label},
    )
    assert res.status_code == 201
    return res.json()


def test_create_reminder_label_wins_in_display(client):
    task = _make_task(client)
    when = _now() + timedelta(hours=2)
    row = _add_reminder(client, task["id"], when, "1 hour before")
    assert row["label"] == "1 hour before"
    assert row["display"] == "1 hour before"
    assert row["fired_at"] is None
    assert datetime.fromisoformat(row["remind_at"]) == when


def test_create_reminder_without_label_derives_display(client):
    task = _make_task(client)
    row = _add_reminder(client, task["id"], _now() + timedelta(days=1))
    assert row["label"] == ""
    assert isinstance(row["display"], str) and row["display"]


def test_list_reminders_returns_created_rows(client):
    task = _make_task(client)
    created = _add_reminder(client, task["id"], _now() + timedelta(hours=1), "soon")
    res = client.get(f"/api/tasks/{task['id']}/reminders")
    assert res.status_code == 200
    rows = res.json()
    assert [r["id"] for r in rows] == [created["id"]]
    assert rows[0]["display"] == "soon"


def test_reminder_endpoints_404_on_unknown_task(client):
    res = client.get("/api/tasks/999/reminders")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "not_found", "message": "Task not found"}}
    res = client.post(
        "/api/tasks/999/reminders", json={"remind_at": _now().isoformat()}
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_delete_reminder_204_then_404(client):
    task = _make_task(client)
    row = _add_reminder(client, task["id"], _now() + timedelta(hours=1))
    res = client.delete(f"/api/tasks/{task['id']}/reminders/{row['id']}")
    assert res.status_code == 204
    res = client.delete(f"/api/tasks/{task['id']}/reminders/{row['id']}")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "not_found", "message": "Reminder not found"}}


def test_delete_reminder_under_wrong_task_is_404(client):
    task = _make_task(client)
    other = _make_task(client, label="Other")
    row = _add_reminder(client, task["id"], _now() + timedelta(hours=1))
    assert client.delete(f"/api/tasks/{other['id']}/reminders/{row['id']}").status_code == 404
    # The mismatched delete didn't remove it.
    assert client.get(f"/api/tasks/{task['id']}/reminders").json()[0]["id"] == row["id"]


def test_task_embeds_reminders_sorted_by_remind_at(client):
    task = _make_task(client)
    later = _add_reminder(client, task["id"], _now() + timedelta(hours=2), "later")
    sooner = _add_reminder(client, task["id"], _now() + timedelta(hours=1), "sooner")
    listed = client.get("/api/tasks").json()
    row = next(t for t in listed if t["id"] == task["id"])
    assert [r["id"] for r in row["reminders"]] == [sooner["id"], later["id"]]


def test_tick_fires_only_past_due_with_task_label(client):
    fired: list[tuple[str, str]] = []
    reminders.configure(lambda title, body: fired.append((title, body)))
    task = _make_task(client, label="Call the dentist")
    _add_reminder(client, task["id"], _now() - timedelta(hours=1), "overdue ping")
    _add_reminder(client, task["id"], _now() + timedelta(hours=1), "future ping")

    assert reminders.tick() == 1
    assert fired == [("Call the dentist", "overdue ping")]
    # Marked fired: a second tick finds nothing new.
    assert reminders.tick() == 0
    assert fired == [("Call the dentist", "overdue ping")]


def test_tick_uses_fallback_body_when_label_empty(client):
    fired: list[tuple[str, str]] = []
    reminders.configure(lambda title, body: fired.append((title, body)))
    task = _make_task(client, label="Pay rent")
    _add_reminder(client, task["id"], _now() - timedelta(minutes=5))
    assert reminders.tick() == 1
    assert fired == [("Pay rent", "Task reminder")]


def test_reminders_on_done_tasks_do_not_fire(client):
    fired: list[tuple[str, str]] = []
    reminders.configure(lambda title, body: fired.append((title, body)))
    task = _make_task(client)
    _add_reminder(client, task["id"], _now() - timedelta(hours=1))
    client.patch(f"/api/tasks/{task['id']}", json={"done": True})
    assert reminders.tick() == 0
    assert fired == []


def test_tick_with_notifier_disabled_still_marks_fired(client):
    reminders.configure(None)  # notify becomes a no-op; firing bookkeeping stays
    task = _make_task(client)
    _add_reminder(client, task["id"], _now() - timedelta(hours=1))
    assert reminders.tick() == 1
    assert store.due_reminders() == []
    assert reminders.tick() == 0


def test_deleting_task_cascades_its_reminders(client):
    task = _make_task(client)
    _add_reminder(client, task["id"], _now() - timedelta(hours=1))
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert store.due_reminders() == []
    with store._session() as s:
        assert s.scalars(select(TaskReminder)).all() == []
