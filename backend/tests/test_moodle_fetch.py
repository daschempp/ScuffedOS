"""MoodleProvider fetch_* methods (M6 contract §E) — every test drives the
REAL MoodleProvider through FakeMoodleHTTP scripted with realistic Moodle
web-service JSON. No network. [confirm-against-live] on every wsfunction /
param / field name touched here — verified against the live WolfWare Moodle
in Task 21; the constant names and method signatures are frozen."""
from datetime import datetime, timezone

import pytest

from app.providers.base import Tokens
from app.providers.moodle import MoodleProvider

from .fakes import FakeMoodleHTTP, seq


def _provider(http) -> MoodleProvider:
    p = MoodleProvider()
    p.configure(http)
    p.set_tokens(
        Tokens(
            access_token="wstoken-abc", refresh_token=None, expires_at=None,
            scopes="", provider_user_id="7",
        )
    )
    return p


# ---- fetch_courses [confirm-against-live: core_enrol_get_users_courses;
#      fields id/shortname/fullname/progress/startdate/enddate/lastaccess/hidden] ----

def test_fetch_courses_maps_ws_json_to_normalized_courses():
    http = FakeMoodleHTTP(responses={
        "core_enrol_get_users_courses": [
            {
                "id": 72, "shortname": "CSC510", "fullname": "Software Engineering",
                "progress": 42.5, "startdate": 1725148800, "enddate": 1733011200,
                "lastaccess": 1725580800, "hidden": 0,
            },
            {
                "id": 69, "shortname": "MA305", "fullname": "Linear Algebra",
                "progress": None, "startdate": 0, "enddate": 0,
                "lastaccess": 0, "hidden": 1,
            },
        ],
    })
    courses = _provider(http).fetch_courses(userid=7)

    assert len(courses) == 2
    c0 = courses[0]
    assert c0.source == "moodle"
    assert c0.source_id == "72"                 # id coerced to str
    assert c0.shortname == "CSC510"
    assert c0.fullname == "Software Engineering"
    assert c0.progress == 42.5
    assert c0.start_at == datetime(2024, 9, 1, tzinfo=timezone.utc)   # 1725148800
    assert c0.end_at == datetime(2024, 12, 1, tzinfo=timezone.utc)    # 1733011200
    assert c0.last_access_at == datetime(2024, 9, 6, tzinfo=timezone.utc)  # 1725580800
    assert c0.hidden is False

    c1 = courses[1]
    assert c1.source_id == "69"
    assert c1.progress is None
    assert c1.start_at is None                   # epoch 0 -> None
    assert c1.end_at is None
    assert c1.last_access_at is None             # epoch 0 -> None
    assert c1.hidden is True                     # 1 -> True


def test_fetch_courses_sends_userid_param():
    http = FakeMoodleHTTP(responses={"core_enrol_get_users_courses": []})
    _provider(http).fetch_courses(userid=7)

    url, body = http.posts[0]
    assert url.endswith("/webservice/rest/server.php")
    assert body["wsfunction"] == "core_enrol_get_users_courses"
    assert body["userid"] == "7"                 # PHP form field, flattened to str
    assert body["moodlewsrestformat"] == "json"


def test_fetch_courses_empty_list_when_no_courses():
    http = FakeMoodleHTTP(responses={"core_enrol_get_users_courses": []})
    assert _provider(http).fetch_courses(userid=7) == []


# ---- fetch_deadlines [confirm-against-live: core_calendar_get_action_events_by_timesort;
#      params timesortfrom/timesortto/limitnum/aftereventid; response
#      {"events":[{id,name,modulename,eventtype,timesort,overdue,viewurl,course:{id}}]}] ----

def _event(eid, timesort, *, name="Assignment is due", modulename="assign",
           eventtype="due", overdue=False, courseid=72):
    return {
        "id": eid, "name": name, "modulename": modulename, "eventtype": eventtype,
        "timesort": timesort, "overdue": overdue,
        "viewurl": f"https://moodle.example/mod/assign/view.php?id={eid}",
        "course": {"id": courseid},
    }


def test_fetch_deadlines_maps_events_to_normalized_deadlines():
    http = FakeMoodleHTTP(responses={
        "core_calendar_get_action_events_by_timesort": {"events": [
            _event(9001, 1725580800, name="Summative assignment is due",
                   modulename="assign", eventtype="due", overdue=True, courseid=72),
        ]},
    })
    deadlines = _provider(http).fetch_deadlines(
        now=datetime(2024, 9, 1, tzinfo=timezone.utc)
    )

    assert len(deadlines) == 1
    d = deadlines[0]
    assert d.source == "moodle"
    assert d.source_id == "9001"
    assert d.course_id == "72"
    assert d.name == "Summative assignment is due"
    assert d.module_name == "assign"
    assert d.event_type == "due"
    assert d.due_at == datetime(2024, 9, 6, tzinfo=timezone.utc)   # 1725580800
    assert d.overdue is True
    assert d.url == "https://moodle.example/mod/assign/view.php?id=9001"


def test_fetch_deadlines_sends_timesort_window_and_limit():
    http = FakeMoodleHTTP(responses={
        "core_calendar_get_action_events_by_timesort": {"events": []},
    })
    now = datetime(2024, 9, 1, tzinfo=timezone.utc)       # epoch 1725148800
    _provider(http).fetch_deadlines(now=now)

    url, body = http.posts[0]
    assert body["wsfunction"] == "core_calendar_get_action_events_by_timesort"
    assert body["timesortfrom"] == "1725148800"           # now epoch
    # now + settings.moodle_backfill_days_ahead (default 60) days:
    assert body["timesortto"] == str(1725148800 + 60 * 86400)
    assert body["limitnum"] == "50"


def test_fetch_deadlines_paginates_via_aftereventid_while_page_is_full():
    # A full first page (exactly 50) triggers a second call keyed on the last
    # event id; the second, short page (< 50) stops pagination.
    page1 = [_event(3000 + i, 1725148800 + i) for i in range(50)]
    page2 = [_event(4000 + i, 1725238800 + i) for i in range(7)]
    http = FakeMoodleHTTP(responses={
        # seq(...) scripts successive per-call responses (this wsfunction is
        # called once per page); a bare list would be a literal array payload.
        "core_calendar_get_action_events_by_timesort": seq(
            {"events": page1},          # first call
            {"events": page2},          # second call (after aftereventid)
        ),
    })
    deadlines = _provider(http).fetch_deadlines(
        now=datetime(2024, 9, 1, tzinfo=timezone.utc)
    )

    assert len(deadlines) == 57                       # 50 + 7, both pages merged
    assert len(http.posts) == 2                       # exactly two WS calls
    # second call carried aftereventid = last id of page 1 (3049).
    _, body2 = http.posts[1]
    assert body2["aftereventid"] == "3049"


def test_fetch_deadlines_single_short_page_makes_one_call():
    http = FakeMoodleHTTP(responses={
        "core_calendar_get_action_events_by_timesort": {"events": [
            _event(9001, 1725580800),
        ]},
    })
    _provider(http).fetch_deadlines(now=datetime(2024, 9, 1, tzinfo=timezone.utc))
    assert len(http.posts) == 1
