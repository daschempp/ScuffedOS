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


# ---- fetch_assignments [confirm-against-live: mod_assign_get_assignments ->
#      {"courses":[{id, assignments:[{id,cmid,name,duedate,cutoffdate,grade}]}]};
#      then mod_assign_get_submission_status(assignid,userid) ->
#      lastattempt.submission.status / gradingstatus / graded] ----

def _sub_status(status="submitted", gradingstatus="graded", graded=True):
    return {
        "lastattempt": {"submission": {"status": status}},
        "gradingstatus": gradingstatus,
        "graded": graded,
    }


def test_fetch_assignments_maps_and_merges_submission_status_per_assignment():
    http = FakeMoodleHTTP(responses={
        "mod_assign_get_assignments": {"courses": [
            {"id": 72, "assignments": [
                {"id": 501, "cmid": 8801, "name": "Design doc",
                 "duedate": 1725580800, "cutoffdate": 1725667200, "grade": 100},
                {"id": 502, "cmid": 8802, "name": "Reflection",
                 "duedate": 0, "cutoffdate": 0, "grade": 20},
            ]},
        ]},
        # scripted per-call sequence: first call -> assign 501, second -> 502
        "mod_assign_get_submission_status": seq(
            _sub_status(status="submitted", gradingstatus="graded", graded=True),
            _sub_status(status="draft", gradingstatus="notgraded", graded=False),
        ),
    })
    assignments = _provider(http).fetch_assignments(userid=7)

    assert len(assignments) == 2
    a0, a1 = assignments
    assert a0.source == "moodle"
    assert a0.source_id == "501"
    assert a0.course_id == "72"
    assert a0.cmid == "8801"
    assert a0.name == "Design doc"
    assert a0.due_at == datetime(2024, 9, 6, tzinfo=timezone.utc)      # 1725580800
    assert a0.cutoff_at == datetime(2024, 9, 7, tzinfo=timezone.utc)   # 1725667200
    assert a0.grade_max == 100
    assert a0.submission_status == "submitted"     # merged onto 501
    assert a0.grading_status == "graded"
    assert a0.graded is True

    assert a1.source_id == "502"
    assert a1.due_at is None                        # duedate 0 -> None
    assert a1.cutoff_at is None
    assert a1.submission_status == "draft"          # merged onto 502, not 501
    assert a1.grading_status == "notgraded"
    assert a1.graded is False


def test_fetch_assignments_passes_assignid_and_userid_to_status_call():
    http = FakeMoodleHTTP(responses={
        "mod_assign_get_assignments": {"courses": [
            {"id": 72, "assignments": [
                {"id": 501, "cmid": 8801, "name": "Design doc",
                 "duedate": 1725580800, "cutoffdate": 0, "grade": 100},
            ]},
        ]},
        "mod_assign_get_submission_status": _sub_status(),
    })
    _provider(http).fetch_assignments(userid=7)

    # posts[0] = mod_assign_get_assignments; posts[1] = the status call.
    _, status_body = http.posts[1]
    assert status_body["wsfunction"] == "mod_assign_get_submission_status"
    assert status_body["assignid"] == "501"
    assert status_body["userid"] == "7"


def test_fetch_assignments_status_defaults_when_lastattempt_missing():
    http = FakeMoodleHTTP(responses={
        "mod_assign_get_assignments": {"courses": [
            {"id": 72, "assignments": [
                {"id": 501, "cmid": 8801, "name": "Design doc",
                 "duedate": 0, "cutoffdate": 0, "grade": 100},
            ]},
        ]},
        "mod_assign_get_submission_status": {"gradingstatus": "", "graded": False},
    })
    a = _provider(http).fetch_assignments(userid=7)[0]
    assert a.submission_status == "none"     # no lastattempt.submission -> "none"
    assert a.grading_status == ""
    assert a.graded is False


def test_fetch_assignments_empty_when_no_courses():
    http = FakeMoodleHTTP(responses={"mod_assign_get_assignments": {"courses": []}})
    assert _provider(http).fetch_assignments(userid=7) == []


# ---- fetch_grades [confirm-against-live: gradereport_user_get_grade_items
#      (courseid,userid) -> usergrades[].gradeitems[]: id,itemname,itemtype,
#      graderaw,gradeformatted,grademin,grademax,gradedategraded] ----

def test_fetch_grades_maps_rows_per_course():
    http = FakeMoodleHTTP(responses={
        "gradereport_user_get_grade_items": {"usergrades": [
            {"gradeitems": [
                {"id": 9001, "itemname": "Design doc", "itemtype": "mod",
                 "graderaw": 88.0, "gradeformatted": "88.00",
                 "grademin": 0.0, "grademax": 100.0,
                 "gradedategraded": 1725580800},
                {"id": 9002, "itemname": "Course total", "itemtype": "course",
                 "graderaw": None, "gradeformatted": "-",
                 "grademin": 0.0, "grademax": 100.0,
                 "gradedategraded": 0},
            ]},
        ]},
    })
    grades = _provider(http).fetch_grades(userid=7, course_ids=["72"])

    assert len(grades) == 2
    g0, g1 = grades
    assert g0.source == "moodle"
    assert g0.source_id == "9001"
    assert g0.course_id == "72"                  # from the course_ids arg, not the row
    assert g0.item_name == "Design doc"
    assert g0.item_type == "mod"
    assert g0.grade_formatted == "88.00"
    assert g0.grade_raw == 88.0
    assert g0.grade_min == 0.0
    assert g0.grade_max == 100.0
    assert g0.graded_at == datetime(2024, 9, 6, tzinfo=timezone.utc)  # 1725580800

    # "-" / None raw -> grade_raw None; formatted string preserved as-is.
    assert g1.item_name == "Course total"
    assert g1.grade_formatted == "-"
    assert g1.grade_raw is None
    assert g1.graded_at is None                  # gradedategraded 0 -> None


def test_fetch_grades_iterates_every_course_id():
    http = FakeMoodleHTTP(responses={
        # one call per course_id -> seq() scripts the two successive responses.
        "gradereport_user_get_grade_items": seq(
            {"usergrades": [{"gradeitems": [
                {"id": 1, "itemname": "A", "itemtype": "mod",
                 "graderaw": 1.0, "gradeformatted": "1", "grademin": 0.0,
                 "grademax": 1.0, "gradedategraded": 0}]}]},
            {"usergrades": [{"gradeitems": [
                {"id": 2, "itemname": "B", "itemtype": "mod",
                 "graderaw": 2.0, "gradeformatted": "2", "grademin": 0.0,
                 "grademax": 2.0, "gradedategraded": 0}]}]},
        ),
    })
    grades = _provider(http).fetch_grades(userid=7, course_ids=["72", "69"])

    assert [g.course_id for g in grades] == ["72", "69"]   # tagged per course
    assert len(http.posts) == 2                            # one call per course
    _, body0 = http.posts[0]
    _, body1 = http.posts[1]
    assert body0["courseid"] == "72"
    assert body0["userid"] == "7"
    assert body1["courseid"] == "69"


def test_fetch_grades_empty_when_no_course_ids():
    http = FakeMoodleHTTP(responses={"gradereport_user_get_grade_items": {}})
    assert _provider(http).fetch_grades(userid=7, course_ids=[]) == []
    assert http.posts == []          # no course ids -> no WS calls at all
