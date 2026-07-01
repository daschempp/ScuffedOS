"""WHOOP v2 JSON → normalized dataclasses: recovery/cycle/sleep/workout mapping.

Fixtures use live v2 field names (confirm-against-live, M4 §13): records[] +
next_token; metrics nested under 'score'; score_state gates scored records;
workout sport field is 'sport_name'; energy is kilojoule (→kcal).
No network — WhoopProvider.configure(fake_http=...) replays the payloads.
"""
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import NormalizedSnapshot, NormalizedWorkout
from app.providers.whoop import (
    WHOOP_API_BASE,
    WhoopProvider,
)


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("x", request=None, response=None)


class FakeHttp:
    """Replays GET responses keyed by path; supports next_token paging.

    `pages` maps a path suffix (e.g. 'recovery') to a LIST of payloads;
    each successive GET to that path pops the next page.
    """

    def __init__(self, pages):
        self.pages = {k: list(v) for k, v in pages.items()}
        self.gets = []

    def _key(self, url):
        for k in self.pages:
            if url.endswith(k) or ("/" + k) in url:
                return k
        return None

    def get(self, url, headers=None, params=None):
        self.gets.append((url, params))
        key = self._key(url)
        queue = self.pages.get(key, [])
        payload = queue.pop(0) if queue else {"records": [], "next_token": None}
        return FakeResp(payload)

    def post(self, url, data=None, **kw):  # not used here
        return FakeResp({})


def _provider_with(pages):
    settings.whoop_client_id = "cid"
    settings.whoop_client_secret = "sec"
    p = WhoopProvider()
    p.configure(fake_http=FakeHttp(pages))
    # Tokens far from expiry so _ensure_fresh is a pass-through.
    p._tokens = _far_tokens()
    return p


def _far_tokens():
    from datetime import timedelta
    from app.providers.base import Tokens
    return Tokens("AT", "RT", datetime.now(timezone.utc) + timedelta(days=1), scopes="read:recovery")


# ---- recovery + cycle (strain) fixtures ----
RECOVERY_PAGE = {
    "records": [{
        "cycle_id": 93845,
        "sleep_id": "ecfc6a15-4661-442f-a9a4-f160dd7afae8",
        "user_id": 10129,
        "created_at": "2026-06-30T11:25:44.774Z",
        "updated_at": "2026-06-30T11:25:44.774Z",
        "score_state": "SCORED",
        "score": {  # confirm-against-live field names
            "recovery_score": 67,
            "resting_heart_rate": 52,
            "hrv_rmssd_milli": 88.4,
        },
    }],
    "next_token": None,
}
CYCLE_PAGE = {
    "records": [{
        "id": 93845,
        "user_id": 10129,
        "start": "2026-06-30T05:00:00.000Z",
        "end": "2026-07-01T05:00:00.000Z",
        "score_state": "SCORED",
        "score": {"strain": 14.2, "kilojoule": 8200.0,
                   "average_heart_rate": 71, "max_heart_rate": 165},
    }],
    "next_token": None,
}

# ---- sleep fixtures (ms durations) ----
SLEEP_PAGE = {
    "records": [{
        "id": "11111111-1111-1111-1111-111111111111",
        "cycle_id": 93845,
        "start": "2026-06-30T04:00:00.000Z",
        "end": "2026-06-30T11:00:00.000Z",
        "nap": False,
        "score_state": "SCORED",
        "score": {
            "sleep_performance_percentage": 82,
            "respiratory_rate": 15.1,
            "stage_summary": {
                "total_in_bed_time_milli": 27000000,        # 7.5 h in bed
                "total_awake_time_milli": 1800000,          # 0.5 h awake → 7.0 h asleep
            },
        },
    }],
    "next_token": None,
}

# ---- workout fixtures (paginated, kJ→kcal, sport_name) ----
WORKOUT_PAGE_1 = {
    "records": [{
        "id": "22222222-2222-2222-2222-222222222222",
        "start": "2026-06-30T06:10:00.000Z",
        "end": "2026-06-30T06:52:00.000Z",
        "sport_name": "running",          # confirm-against-live: v2 uses sport_name
        "score_state": "SCORED",
        "score": {"strain": 9.4, "kilojoule": 2510.0,
                   "average_heart_rate": 148, "max_heart_rate": 171},
    }],
    "next_token": "PAGE2",
}
WORKOUT_PAGE_2 = {
    "records": [{
        "id": "33333333-3333-3333-3333-333333333333",
        "start": "2026-06-29T18:00:00.000Z",
        "end": "2026-06-29T18:30:00.000Z",
        "sport_name": "weightlifting",
        "score_state": "SCORED",
        "score": {"strain": 6.1, "kilojoule": 900.0,
                   "average_heart_rate": 110, "max_heart_rate": 140},
    }],
    "next_token": None,
}
# An unscored record must be skipped.
UNSCORED_WORKOUT = {
    "records": [{
        "id": "44444444-4444-4444-4444-444444444444",
        "start": "2026-06-28T07:00:00.000Z",
        "end": "2026-06-28T07:20:00.000Z",
        "sport_name": "walking",
        "score_state": "PENDING_SCORE",
        "score": None,
    }],
    "next_token": None,
}


def test_fetch_recovery_maps_recovery_and_cycle_strain_by_day():
    p = _provider_with({"recovery": [RECOVERY_PAGE], "cycle": [CYCLE_PAGE]})
    snaps = p.fetch_recovery(since=None)
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, NormalizedSnapshot)
    assert s.source == "whoop"
    assert s.recovery_pct == 67
    assert s.resting_hr == 52
    assert s.hrv_ms == 88.4
    # cycle strain folded onto the same physiological day (cycle start, local date)
    assert s.day_strain == 14.2
    # day comes from the cycle start in local tz
    expected_day = datetime(2026, 6, 30, 5, 0, tzinfo=timezone.utc).astimezone().date()
    assert s.day == expected_day


def test_fetch_sleep_maps_quality_rr_and_hours_from_ms():
    p = _provider_with({"sleep": [SLEEP_PAGE]})
    snaps = p.fetch_sleep(since=None)
    assert len(snaps) == 1
    s = snaps[0]
    assert s.sleep_quality_pct == 82
    assert s.respiratory_rate == 15.1
    # 7.5h in bed - 0.5h awake = 7.0h asleep
    assert s.sleep_hours == 7.0
    expected_day = datetime(2026, 6, 30, 4, 0, tzinfo=timezone.utc).astimezone().date()
    assert s.day == expected_day


def test_fetch_workouts_paginates_and_converts_kj_to_kcal():
    p = _provider_with({"workout": [WORKOUT_PAGE_1, WORKOUT_PAGE_2]})
    outs = p.fetch_workouts(since=None)
    assert [w.source_id for w in outs] == [
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    run = outs[0]
    assert isinstance(run, NormalizedWorkout)
    assert run.source == "whoop"
    assert run.sport == "running"
    assert run.name == "Running"            # titled from sport_name
    assert run.duration_min == 42
    assert run.strain == 9.4
    assert run.avg_hr == 148 and run.max_hr == 171
    assert run.calories == round(2510.0 * 0.239006)  # kJ→kcal
    # page 2 followed the next_token
    assert any(params and params.get("nextToken") == "PAGE2" for _u, params in p._http.gets)


def test_unscored_records_are_skipped():
    p = _provider_with({"workout": [UNSCORED_WORKOUT]})
    assert p.fetch_workouts(since=None) == []


def test_since_is_passed_as_start_param():
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    p = _provider_with({"workout": [{"records": [], "next_token": None}]})
    p.fetch_workouts(since=since)
    _url, params = p._http.gets[0]
    assert params["start"] == "2026-06-01T00:00:00+00:00"
