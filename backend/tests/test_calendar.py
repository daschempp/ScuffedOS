"""HTTP tests for the calendar endpoints (events, recurrence expansion, up-next)."""
from datetime import datetime, timedelta, timezone

OCCURRENCE_SHAPE = {
    "id", "title", "start", "end", "tint", "location", "description",
    "recurring", "recurrence_label", "at",
    # Read-time origin markers (M6 School slice-1, contract §H) — additive,
    # default to local/editable for real rows created via this API.
    "source", "editable",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_z(dt: datetime) -> str:
    """Query-string/JSON-safe UTC stamp ('Z' suffix, no '+' to URL-encode)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_create_event_defaults_end_and_treats_naive_as_local(client):
    # Naive datetimes mean the user's local time — the same convention as
    # the assistant tools (local-first); the frontend always sends offsets.
    start_local = (_now() + timedelta(days=2)).astimezone()
    res = client.post("/api/calendar/events", json={
        "title": "Coffee chat",
        "start": start_local.replace(tzinfo=None).isoformat(),  # naive == local
    })
    assert res.status_code == 201
    ev = res.json()
    assert set(ev) == OCCURRENCE_SHAPE
    assert _parse(ev["start"]) == start_local
    assert _parse(ev["end"]) == start_local + timedelta(hours=1)
    assert ev["tint"] == "sky" and ev["location"] == ""
    assert ev["recurring"] is False and ev["recurrence_label"] is None
    assert isinstance(ev["at"], str) and ev["at"]
    assert ev["source"] == "local" and ev["editable"] is True


def test_create_event_rejects_end_at_or_before_start(client):
    start = _now() + timedelta(days=1)
    res = client.post("/api/calendar/events", json={
        "title": "Backwards", "start": _iso_z(start), "end": _iso_z(start),
    })
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "validation_error"
    assert "after" in body["error"]["message"]


def test_create_event_rejects_bad_rrule(client):
    res = client.post("/api/calendar/events", json={
        "title": "Broken repeat",
        "start": _iso_z(_now() + timedelta(days=1)),
        "recurrence": "FREQ=NEVER",
    })
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"].startswith("Invalid recurrence rule")


def test_events_window_expands_recurring_series_sorted(client):
    window_from = _now() + timedelta(days=14)
    window_to = window_from + timedelta(days=7)
    anchor = window_from + timedelta(hours=12)
    client.post("/api/calendar/events", json={
        "title": "Gym", "start": _iso_z(anchor),
        "recurrence": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
    })
    client.post("/api/calendar/events", json={
        "title": "Dentist", "start": _iso_z(window_from + timedelta(days=3, hours=2)),
    })
    occs = client.get("/api/calendar/events", params={
        "from": _iso_z(window_from), "to": _iso_z(window_to),
    }).json()
    # any 7-day window holds exactly 3 of a weekly MO,WE,FR series + the one-off
    assert len(occs) == 4
    assert sum(o["title"] == "Gym" for o in occs) == 3
    assert sum(o["title"] == "Dentist" for o in occs) == 1
    starts = [_parse(o["start"]) for o in occs]
    assert starts == sorted(starts)
    for o in occs:
        if o["title"] == "Gym":
            assert o["recurring"] is True
            assert o["recurrence_label"] == "Repeats (custom)"


def test_event_overlapping_window_start_is_returned(client):
    window_from = _now() + timedelta(days=5)
    window_to = window_from + timedelta(days=1)
    client.post("/api/calendar/events", json={
        "title": "Straddler",
        "start": _iso_z(window_from - timedelta(minutes=30)),
        "end": _iso_z(window_from + timedelta(minutes=30)),
    })
    client.post("/api/calendar/events", json={
        "title": "Earlier",  # ends exactly at the window edge: no overlap
        "start": _iso_z(window_from - timedelta(hours=2)),
        "end": _iso_z(window_from),
    })
    titles = [o["title"] for o in client.get("/api/calendar/events", params={
        "from": _iso_z(window_from), "to": _iso_z(window_to),
    }).json()]
    assert "Straddler" in titles
    assert "Earlier" not in titles


def test_delete_single_occurrence_records_exdate(client):
    start = _now() + timedelta(days=3)
    ev = client.post("/api/calendar/events", json={
        "title": "Standup", "start": _iso_z(start), "recurrence": "FREQ=WEEKLY",
    }).json()
    window = {"from": _iso_z(start - timedelta(hours=2)),
              "to": _iso_z(start + timedelta(days=8))}
    occs = client.get("/api/calendar/events", params=window).json()
    assert len(occs) == 2
    res = client.delete(f"/api/calendar/events/{ev['id']}",
                        params={"occurrence_start": occs[1]["start"]})
    assert res.status_code == 204
    left = client.get("/api/calendar/events", params=window).json()
    assert [o["start"] for o in left] == [occs[0]["start"]]


def test_delete_without_param_removes_series(client):
    start = _now() + timedelta(days=1)
    ev = client.post("/api/calendar/events", json={
        "title": "Doomed", "start": _iso_z(start), "recurrence": "FREQ=DAILY",
    }).json()
    assert client.delete(f"/api/calendar/events/{ev['id']}").status_code == 204
    occs = client.get("/api/calendar/events", params={
        "from": _iso_z(start - timedelta(hours=2)),
        "to": _iso_z(start + timedelta(days=3)),
    }).json()
    assert occs == []
    res = client.delete(f"/api/calendar/events/{ev['id']}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_patch_edits_apply_to_every_occurrence(client):
    start = _now() + timedelta(days=10)
    ev = client.post("/api/calendar/events", json={
        "title": "Daily sync", "start": _iso_z(start),
        "end": _iso_z(start + timedelta(hours=1)), "recurrence": "FREQ=DAILY",
    }).json()
    window = {"from": _iso_z(start - timedelta(hours=2)),
              "to": _iso_z(start + timedelta(days=3, hours=2))}
    assert len(client.get("/api/calendar/events", params=window).json()) == 4

    new_start = start + timedelta(minutes=30)
    res = client.patch(f"/api/calendar/events/{ev['id']}", json={
        "title": "Renamed sync", "start": _iso_z(new_start),
    })
    assert res.status_code == 200
    occs = client.get("/api/calendar/events", params=window).json()
    assert len(occs) == 4
    assert all(o["title"] == "Renamed sync" for o in occs)
    assert _parse(occs[0]["start"]) == new_start
    durations = {_parse(o["end"]) - _parse(o["start"]) for o in occs}
    assert durations == {timedelta(minutes=30)}


def test_patch_unknown_event_is_404(client):
    res = client.patch("/api/calendar/events/424242", json={"title": "Ghost"})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_up_next_orders_ongoing_first_and_respects_limit(client):
    now = _now()
    ongoing = client.post("/api/calendar/events", json={
        "title": "Ongoing now",
        "start": _iso_z(now - timedelta(minutes=30)),
        "end": _iso_z(now + timedelta(minutes=30)),
    }).json()
    client.post("/api/calendar/events", json={
        "title": "Design review",
        "start": _iso_z(now + timedelta(hours=2)),
        "end": _iso_z(now + timedelta(hours=3)),
        "location": "Boardroom 4",
    })
    client.post("/api/calendar/events", json={
        "title": "Later", "start": _iso_z(now + timedelta(hours=5)),
    })
    items = client.get("/api/calendar/up-next").json()
    assert [i["title"] for i in items] == ["Ongoing now", "Design review", "Later"]
    assert items[0]["id"] == ongoing["id"]
    assert items[0]["when"].startswith("Now · ")
    assert items[1]["when"].endswith("· Boardroom 4")
    limited = client.get("/api/calendar/up-next", params={"limit": 1}).json()
    assert [i["title"] for i in limited] == ["Ongoing now"]


def test_patch_rejects_end_at_or_before_start(client):
    start = _now() + timedelta(days=1)
    ev = client.post("/api/calendar/events", json={
        "title": "Sync", "start": start.isoformat(),
    }).json()
    res = client.patch(f"/api/calendar/events/{ev['id']}", json={
        "end": start.isoformat(),
    })
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_rescheduling_a_series_shifts_its_exdates(client):
    """A deleted single occurrence must stay deleted when the series moves."""
    start = (_now() + timedelta(days=1)).replace(microsecond=0)
    ev = client.post("/api/calendar/events", json={
        "title": "Standup", "start": start.isoformat(),
        "end": (start + timedelta(minutes=15)).isoformat(),
        "recurrence": "FREQ=DAILY",
    }).json()
    # Delete the third occurrence, then move the whole series an hour later.
    third = start + timedelta(days=2)
    res = client.delete(f"/api/calendar/events/{ev['id']}",
                        params={"occurrence_start": third.isoformat()})
    assert res.status_code == 204
    res = client.patch(f"/api/calendar/events/{ev['id']}", json={
        "start": (start + timedelta(hours=1)).isoformat(),
        "end": (start + timedelta(hours=1, minutes=15)).isoformat(),
    })
    assert res.status_code == 200

    occs = client.get("/api/calendar/events", params={
        "from": start.isoformat(),
        "to": (start + timedelta(days=4)).isoformat(),
    }).json()
    starts = [o["start"] for o in occs if o["title"] == "Standup"]
    shifted_third = third + timedelta(hours=1)
    assert _parse(shifted_third.isoformat()) not in [_parse(s) for s in starts]
    assert len(starts) == 3  # days 1, 2, 4 of the window — not 4


def test_finance_calendar_occurrence_not_mutable_via_http(client):
    # A 'finance:<id>' occurrence id is not an int, so the int-typed events routes reject it.
    res = client.patch("/api/calendar/events/finance:bill:cc1", json={"title": "x"})
    assert res.status_code in (404, 422)
    res2 = client.delete("/api/calendar/events/finance:bill:cc1")
    assert res2.status_code in (404, 422)
