"""M6 School slice-1 contract §H — additive widening of the Calendar/Tasks
response models so read-time Moodle projections (id='moodle:<n>',
source='moodle', editable=False) validate alongside real local rows, which
must keep validating unchanged and defaulting to source='local'/editable=True.
Pure pydantic validation — no DB, no network."""
from datetime import datetime, timezone

from app.schemas import EventOccurrence, Task, TaskGroup, Tint


def _local_event_dict() -> dict:
    # The exact shape store._occurrence_dict emits for a real Event row —
    # note it carries NO source/editable keys (those are additive here).
    return {
        "id": 7,
        "title": "Standup",
        "start": datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
        "tint": "sky",
        "location": "",
        "description": "",
        "recurring": False,
        "recurrence_label": None,
        "at": "9:00am",
    }


def _local_task_dict() -> dict:
    # The exact shape store._task_dict emits for a real Task row — no
    # source/editable keys.
    return {
        "id": 3,
        "label": "Buy milk",
        "done": False,
        "group": "Today",
        "deadline": None,
        "prio": "med",
        "list": "Personal",
        "description": "",
        "subtasks": [],
        "labels": [],
        "reminders": [],
        "files": [],
        "recurrence": None,
        "recurrence_label": None,
        "due": None,
        "late": False,
        "created_at": datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        "completed_at": None,
    }


def test_existing_event_dict_without_source_editable_still_validates_and_defaults():
    occ = EventOccurrence.model_validate(_local_event_dict())
    assert occ.id == 7
    assert occ.source == "local"
    assert occ.editable is True


def test_existing_task_dict_without_source_editable_still_validates_and_defaults():
    task = Task.model_validate(_local_task_dict())
    assert task.id == 3
    assert task.source == "local"
    assert task.editable is True


def test_moodle_projected_event_with_string_id_validates():
    d = _local_event_dict()
    d.update(id="moodle:1", source="moodle", editable=False, tint="grape")
    occ = EventOccurrence.model_validate(d)
    assert occ.id == "moodle:1"
    assert occ.source == "moodle"
    assert occ.editable is False
    assert occ.tint == "grape"


def test_moodle_projected_task_with_string_id_validates():
    d = _local_task_dict()
    d.update(id="moodle:1", source="moodle", editable=False,
             group="School", list="School")
    task = Task.model_validate(d)
    assert task.id == "moodle:1"
    assert task.source == "moodle"
    assert task.editable is False
    assert task.group == "School"
    assert task.list == "School"


def test_grape_is_a_valid_tint_and_school_a_valid_taskgroup():
    # The two new Literal members the projection relies on.
    assert "grape" in Tint.__args__
    assert "School" in TaskGroup.__args__
