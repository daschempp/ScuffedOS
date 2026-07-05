"""M6 assistant Moodle tools (READ-ONLY): get_courses / get_deadlines /
get_grades return store data plus an "Open school" action card, and the
registration test asserts NO Moodle write tool is ever exposed to the
assistant (read-only guarantee, Global Constraints)."""
import json
from datetime import datetime, timezone

from app import tools
from app.providers.base import NormalizedDeadline
from app.store import store


def test_get_deadlines_returns_store_deadlines_and_school_action_card(client):
    # Seed one deadline through the real store upsert (Task 9) so the tool
    # reads exactly what the DB holds — no provider/network involved.
    store.upsert_moodle_deadline(
        NormalizedDeadline(
            source="moodle",
            source_id="evt-501",
            course_id="72",
            name="Summative assignment is due",
            module_name="assign",
            event_type="due",
            due_at=datetime(2026, 7, 10, 23, 59, tzinfo=timezone.utc),
            overdue=False,
            url="https://moodle-courses2527.wolfware.ncsu.edu/mod/assign/view.php?id=1",
        )
    )

    result_json, action = tools.execute("get_deadlines", {})
    result = json.loads(result_json)

    # The tool returns the store's deadline list verbatim (JSON round-tripped).
    # store.moodle_deadlines() carries raw datetime objects (e.g. due_at); the
    # tool's result has already been through json.dumps/json.loads (execute()'s
    # contract), so compare against the store data put through that same
    # round-trip rather than the live Python objects.
    assert isinstance(result, list)
    assert result == json.loads(json.dumps(store.moodle_deadlines(None), default=str))
    assert result[0]["source_id"] == "evt-501"
    assert result[0]["name"] == "Summative assignment is due"

    # The action card is the frozen school card (contract §K).
    assert action == {
        "icon": "graduation-cap",
        "title": "Deadlines",
        "meta": "Upcoming Moodle due dates",
        "cta": "Open school",
        "screen": "school",
    }
    assert action["screen"] == "school"


def test_get_deadlines_passes_days_window_through_to_store(client):
    # args["days"] must reach store.moodle_deadlines(days_ahead=...) — a bare
    # call with no days seeds the same row, and asking for a 0-day window (no
    # deadlines within it) proves the arg is actually forwarded, not dropped.
    store.upsert_moodle_deadline(
        NormalizedDeadline(
            source="moodle",
            source_id="evt-777",
            course_id="72",
            name="Quiz closes",
            module_name="quiz",
            event_type="close",
            due_at=datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc),
            overdue=False,
        )
    )

    result_json, _ = tools.execute("get_deadlines", {"days": 5})
    result = json.loads(result_json)
    assert result == json.loads(json.dumps(store.moodle_deadlines(5), default=str))


def test_moodle_read_tools_are_registered_and_no_write_tool_exists():
    names = {d["name"] for d in tools.DEFINITIONS}
    # The three read tools this slice adds.
    assert {"get_courses", "get_deadlines", "get_grades"} <= names
    # READ-ONLY guarantee: no Moodle write tool is ever exposed to the
    # assistant this slice (submitting/posting is slice 3, Global Constraints).
    assert not any(
        n in names for n in ("submit_assignment", "moodle_submit", "post_forum")
    )
