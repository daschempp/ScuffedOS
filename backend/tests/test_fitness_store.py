"""Store-layer fitness logic: provider accounts, snapshots, workouts (M4).

All against SQLite via the fresh_db fixture — no network, no providers.
"""
from datetime import date, datetime, timedelta, timezone

from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
from app.store import store

UTC = timezone.utc


def _tokens(**kw):
    base = dict(
        access_token="acc-1", refresh_token="ref-1",
        expires_at=datetime(2026, 7, 1, tzinfo=UTC),
        scopes="read:recovery read:workout", provider_user_id="whoop-user-9",
        meta={"foo": "bar"},
    )
    base.update(kw)
    return Tokens(**base)


def test_get_provider_account_absent_is_none():
    assert store.get_provider_account("whoop") is None
    assert store.get_provider_tokens("whoop") is None
    assert store.list_provider_accounts() == []


def test_upsert_provider_account_creates_safe_dict_without_tokens():
    safe = store.upsert_provider_account("whoop", _tokens())
    assert safe["provider"] == "whoop"
    assert safe["status"] == "connected"
    assert safe["provider_user_id"] == "whoop-user-9"
    assert safe["connected_at"] is not None
    assert safe["last_sync_at"] is None
    # Tokens must never appear in the client-safe dict.
    assert "access_token" not in safe
    assert "refresh_token" not in safe
    assert "scopes" not in safe
    assert "meta" not in safe


def test_get_provider_tokens_round_trips_secrets():
    store.upsert_provider_account("whoop", _tokens())
    tok = store.get_provider_tokens("whoop")
    assert tok.access_token == "acc-1"
    assert tok.refresh_token == "ref-1"
    assert tok.expires_at == datetime(2026, 7, 1, tzinfo=UTC)
    assert tok.scopes == "read:recovery read:workout"
    assert tok.provider_user_id == "whoop-user-9"
    assert tok.meta == {"foo": "bar"}


def test_upsert_is_get_or_create_by_owner_provider():
    first = store.upsert_provider_account("whoop", _tokens())
    second = store.upsert_provider_account("whoop", _tokens(access_token="acc-2"))
    assert first["connected_at"] == second["connected_at"]  # same row, not recreated
    assert len(store.list_provider_accounts()) == 1
    assert store.get_provider_tokens("whoop").access_token == "acc-2"  # rotated in place
    # Reconnecting flips a needs_reauth row back to connected.
    store.set_provider_status("whoop", "needs_reauth")
    again = store.upsert_provider_account("whoop", _tokens())
    assert again["status"] == "connected"


def test_set_provider_status_and_synced():
    store.upsert_provider_account("whoop", _tokens())
    store.set_provider_status("whoop", "needs_reauth")
    assert store.get_provider_account("whoop")["status"] == "needs_reauth"
    when = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store.set_provider_synced("whoop", when)
    assert store.get_provider_account("whoop")["last_sync_at"] == when


DAY = date(2026, 6, 30)


def test_upsert_snapshot_creates_row():
    out = store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, day_strain=14.2,
        hrv_ms=88.5, resting_hr=52,
    ))
    assert out["source"] == "whoop"
    assert out["day"] == DAY
    assert out["recovery_pct"] == 72
    assert out["day_strain"] == 14.2
    assert out["hrv_ms"] == 88.5
    assert out["resting_hr"] == 52


def test_upsert_snapshot_is_idempotent_by_owner_source_day():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=80))
    from sqlalchemy import select as _select

    from app.models import DailySnapshot
    with store._session() as s:
        rows = s.scalars(_select(DailySnapshot)).all()
    assert len(rows) == 1
    assert rows[0].recovery_pct == 80  # latest non-None wins


def test_upsert_snapshot_merges_recovery_and_sleep_same_day():
    # Recovery snapshot lands first (recovery + hrv), no sleep fields.
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, hrv_ms=88.5, resting_hr=52,
    ))
    # Sleep snapshot lands second (sleep fields), recovery fields all None.
    merged = store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, sleep_quality_pct=91,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    # Non-None from both lands on the one row; the earlier values survive.
    assert merged["recovery_pct"] == 72
    assert merged["hrv_ms"] == 88.5
    assert merged["resting_hr"] == 52
    assert merged["sleep_quality_pct"] == 91
    assert merged["respiratory_rate"] == 14.6
    assert merged["sleep_hours"] == 7.4


def test_upsert_snapshot_none_does_not_clobber():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    out = store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=None, day_strain=10.0))
    assert out["recovery_pct"] == 72  # None left the prior value intact
    assert out["day_strain"] == 10.0


def _nw(**kw):
    base = dict(
        source="whoop", source_id="w-1", name="Morning run", sport="running",
        started_at=datetime(2026, 6, 30, 6, 10, tzinfo=UTC), duration_min=42,
        strain=11.3, calories=430, avg_hr=148, max_hr=171,
    )
    base.update(kw)
    return NormalizedWorkout(**base)


def test_upsert_workout_is_idempotent_by_source_id():
    store.upsert_workout(_nw())
    again = store.upsert_workout(_nw(name="Morning run (v2)", duration_min=45))
    rows = store.list_workouts()
    assert len(rows) == 1                      # same (source, source_id) -> one row
    assert again["name"] == "Morning run (v2)"  # fields updated in place
    assert again["duration_min"] == 45
    assert again["source"] == "whoop"


def test_workout_dict_has_derived_display_fields():
    out = store.upsert_workout(_nw(sport="running"))
    assert out["icon"]                          # sport-derived, non-empty
    assert out["tint"] in {"green", "sky", "plum", "honey", "clay"}
    assert isinstance(out["when"], str) and out["when"]
    assert out["calories"] == 430


def test_create_manual_workout_has_null_source_id():
    out = store.create_workout({
        "name": "Lunch lift", "sport": "strength",
        "started_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "duration_min": 35, "strain": 8.0,
    })
    assert out["source"] == "manual"
    assert out["id"] > 0
    rows = store.list_workouts()
    assert any(r["name"] == "Lunch lift" and r["source"] == "manual" for r in rows)


def test_list_workouts_newest_started_first_and_limit():
    store.upsert_workout(_nw(source_id="a", started_at=datetime(2026, 6, 28, 6, tzinfo=UTC)))
    store.upsert_workout(_nw(source_id="b", started_at=datetime(2026, 6, 30, 6, tzinfo=UTC)))
    store.upsert_workout(_nw(source_id="c", started_at=datetime(2026, 6, 29, 6, tzinfo=UTC)))
    rows = store.list_workouts()
    starts = [r["started_at"] for r in rows]
    assert starts == sorted(starts, reverse=True)
    assert len(store.list_workouts(limit=2)) == 2


def test_delete_workout():
    out = store.create_workout({
        "name": "Doomed", "started_at": datetime(2026, 6, 30, 9, tzinfo=UTC),
        "duration_min": 10,
    })
    assert store.delete_workout(out["id"]) is True
    assert store.delete_workout(out["id"]) is False
    assert store.list_workouts() == []


def test_synced_workout_auto_completes_linked_habit():
    store.create_habit({"name": "Workout", "link": "workout"})
    local_day = datetime(2026, 6, 30, 6, 10, tzinfo=UTC).astimezone().date()
    store.upsert_workout(_nw(started_at=datetime(2026, 6, 30, 6, 10, tzinfo=UTC)))
    week = store.habits_week(local_day - timedelta(days=local_day.weekday()))
    habit = week["habits"][0]
    assert habit["days"][local_day.weekday()] is True


def test_fitness_today_empty_state():
    out = store.fitness_today(DAY)
    assert out["date"] == DAY
    assert out["has_data"] is False
    assert out["source"] is None
    assert out["recovery_pct"] is None
    assert out["day_strain"] is None
    assert out["sleep_quality_pct"] is None
    # vitals are always the same four keys, values None when no data.
    keys = [v["key"] for v in out["vitals"]]
    assert keys == ["hrv", "resting_hr", "respiratory_rate", "sleep_hours"]
    assert all(v["value"] is None and v["delta"] is None for v in out["vitals"])


def test_fitness_today_rings_and_vitals():
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, day_strain=14.2,
        sleep_quality_pct=88, hrv_ms=82.0, resting_hr=52,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    out = store.fitness_today(DAY)
    assert out["has_data"] is True
    assert out["source"] == "whoop"
    assert out["recovery_pct"] == 72
    assert out["day_strain"] == 14.2
    assert out["sleep_quality_pct"] == 88
    by_key = {v["key"]: v for v in out["vitals"]}
    assert by_key["hrv"]["value"] == 82.0
    assert by_key["hrv"]["unit"] == "ms"
    assert by_key["resting_hr"]["value"] == 52
    assert by_key["respiratory_rate"]["value"] == 14.6
    assert by_key["sleep_hours"]["value"] == 7.4
    # no prior day -> no deltas
    assert all(v["delta"] is None for v in out["vitals"])


def test_fitness_today_deltas_vs_prior_day():
    prior = DAY - timedelta(days=1)
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=prior, hrv_ms=76.0, resting_hr=55,
        respiratory_rate=15.0, sleep_hours=7.0,
    ))
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, hrv_ms=82.0, resting_hr=52,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    by_key = {v["key"]: v for v in store.fitness_today(DAY)["vitals"]}
    assert by_key["hrv"]["delta"] == 6.0           # 82 - 76
    assert by_key["resting_hr"]["delta"] == -3      # 52 - 55
    assert by_key["respiratory_rate"]["delta"] == round(14.6 - 15.0, 1)
    assert by_key["sleep_hours"]["delta"] == round(7.4 - 7.0, 1)


def test_manual_workout_auto_completes_and_does_not_clobber_manual_tap():
    h = store.create_habit({"name": "Workout", "link": "workout"})
    local_day = datetime(2026, 6, 30, 12, 0, tzinfo=UTC).astimezone().date()
    # User manually taps the habit first.
    store.toggle_habit(h["id"], local_day)
    # A manual workout lands -> auto-complete is a no-op on an already-complete day.
    store.create_workout({
        "name": "Lift", "started_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "duration_min": 30,
    })
    from sqlalchemy import select as _select

    from app.models import HabitCompletion
    with store._session() as s:
        comp = s.scalars(
            _select(HabitCompletion).where(HabitCompletion.date == local_day)
        ).all()
    assert len(comp) == 1
    assert comp[0].source == "manual"  # the manual tap was never clobbered


def test_fitness_today_whoop_source_wins_over_manual():
    """When both 'manual' and 'whoop' rows exist for the same day,
    fitness_today must surface the whoop values (recovery_pct / day_strain /
    hrv_ms), not the manual ones. This exercises _snapshot_row's precedence
    ORDER BY: case(source=='whoop', 0, else_=1) ASC, id DESC."""
    # Insert manual row first (lower id) with distinct values.
    store.upsert_snapshot(NormalizedSnapshot(
        source="manual", day=DAY,
        recovery_pct=55, day_strain=8.0, hrv_ms=60.0,
        resting_hr=62, sleep_quality_pct=70,
    ))
    # Insert whoop row second (higher id) with distinct, different values.
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY,
        recovery_pct=81, day_strain=17.5, hrv_ms=91.0,
        resting_hr=49, sleep_quality_pct=88,
    ))
    out = store.fitness_today(DAY)
    assert out["has_data"] is True
    assert out["source"] == "whoop"
    assert out["recovery_pct"] == 81,   "whoop recovery_pct must win"
    assert out["day_strain"] == 17.5,   "whoop day_strain must win"
    assert out["sleep_quality_pct"] == 88, "whoop sleep_quality_pct must win"
    by_key = {v["key"]: v for v in out["vitals"]}
    assert by_key["hrv"]["value"] == 91.0, "whoop hrv_ms must win"
    assert by_key["resting_hr"]["value"] == 49, "whoop resting_hr must win"


def test_fitness_week_whoop_source_wins_over_manual():
    """When both 'manual' and 'whoop' rows exist for the same day inside the
    current week, fitness_week must surface the whoop day_strain, not the
    manual one. This exercises the inverted ORDER BY in fitness_week:
    precedence.desc() + id.desc() means whoop is iterated last and
    overwrites the manual entry in strain_by_day."""
    # Use Tuesday of the test week so it's clearly within MONDAY's week.
    tuesday = MONDAY + timedelta(days=1)
    # Manual row first with a clearly different strain.
    store.upsert_snapshot(NormalizedSnapshot(
        source="manual", day=tuesday, day_strain=6.0,
    ))
    # Whoop row second with a distinct higher strain.
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=tuesday, day_strain=19.3,
    ))
    out = store.fitness_week(tuesday)
    tuesday_day = next(d for d in out["days"] if d["date"] == tuesday)
    assert tuesday_day["strain"] == 19.3, "whoop day_strain must win in fitness_week"
    assert tuesday_day["strain"] != 6.0,  "manual day_strain must NOT surface"


MONDAY = date(2026, 6, 29)  # 2026-06-29 is a Monday


def test_fitness_week_empty_state():
    out = store.fitness_week(MONDAY + timedelta(days=3))
    assert len(out["days"]) == 7
    assert [d["dow"] for d in out["days"]] == ["M", "T", "W", "T", "F", "S", "S"]
    assert out["days"][0]["date"] == MONDAY
    assert all(d["strain"] is None and d["frac"] == 0.0 for d in out["days"])
    assert out["avg_strain"] == 0
    assert out["peak_day"] is None


def test_fitness_week_strain_trend_and_frac_cap():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=MONDAY, day_strain=10.5))
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=MONDAY + timedelta(days=1), day_strain=21.0,
    ))
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=MONDAY + timedelta(days=2), day_strain=5.0,
    ))
    out = store.fitness_week(MONDAY + timedelta(days=2))
    days = out["days"]
    assert days[0]["strain"] == 10.5
    assert days[0]["frac"] == round(10.5 / 21, 2)
    assert days[1]["strain"] == 21.0
    assert days[1]["frac"] == 1.0                # capped
    assert days[2]["strain"] == 5.0
    assert all(d["strain"] is None and d["frac"] == 0.0 for d in days[3:])
    # avg over days with a strain reading only.
    assert out["avg_strain"] == round((10.5 + 21.0 + 5.0) / 3, 1)
    assert out["peak_day"] == MONDAY + timedelta(days=1)  # day_strain 21 is the peak


def test_delete_provider_data_removes_synced_keeps_manual():
    store.upsert_provider_account("whoop", _tokens())
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    store.upsert_workout(_nw(source_id="synced-1"))
    store.create_workout({
        "name": "Manual lift",
        "started_at": datetime(2026, 6, 30, 12, tzinfo=UTC),
        "duration_min": 30,
    })

    assert store.delete_provider_data("whoop") is True

    # Account + tokens gone.
    assert store.get_provider_account("whoop") is None
    assert store.get_provider_tokens("whoop") is None
    assert store.list_provider_accounts() == []
    # Synced snapshot + workout gone; manual workout preserved.
    assert store.fitness_today(DAY)["has_data"] is False
    remaining = store.list_workouts()
    assert [w["name"] for w in remaining] == ["Manual lift"]
    assert remaining[0]["source"] == "manual"


def test_delete_provider_data_absent_returns_false():
    # No account, but a manual workout exists and must be untouched.
    store.create_workout({
        "name": "Solo", "started_at": datetime(2026, 6, 30, 8, tzinfo=UTC),
        "duration_min": 20,
    })
    assert store.delete_provider_data("whoop") is False
    assert [w["name"] for w in store.list_workouts()] == ["Solo"]
