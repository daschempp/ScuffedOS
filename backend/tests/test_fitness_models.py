"""The three M4 fitness tables: columns + unique-constraint behavior."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import DailySnapshot, ProviderAccount, Workout
from app.store import store


def test_tables_and_columns_exist():
    with store._session() as s:
        insp = inspect(s.get_bind())
        names = set(insp.get_table_names())
        assert {"provider_accounts", "daily_snapshots", "workouts"} <= names
        snap_cols = {c["name"] for c in insp.get_columns("daily_snapshots")}
        assert {"owner", "source", "day", "recovery_pct", "day_strain",
                "sleep_quality_pct", "hrv_ms", "resting_hr", "respiratory_rate",
                "sleep_hours", "metrics_json", "created_at", "updated_at"} <= snap_cols
        wk_cols = {c["name"] for c in insp.get_columns("workouts")}
        assert {"owner", "source", "source_id", "name", "sport", "started_at",
                "duration_min", "strain", "calories", "avg_hr", "max_hr"} <= wk_cols
        pa_cols = {c["name"] for c in insp.get_columns("provider_accounts")}
        assert {"owner", "provider", "access_token", "refresh_token",
                "expires_at", "scopes", "provider_user_id", "status", "meta",
                "connected_at", "last_sync_at"} <= pa_cols


def test_provider_account_owner_provider_is_unique():
    with store._session() as s, s.begin():
        s.add(ProviderAccount(owner="me", provider="whoop"))
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(ProviderAccount(owner="me", provider="whoop"))


def test_snapshot_owner_source_day_is_unique():
    day = date(2026, 6, 30)
    with store._session() as s, s.begin():
        s.add(DailySnapshot(owner="me", source="whoop", day=day))
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(DailySnapshot(owner="me", source="whoop", day=day))
    # A different source on the same day is allowed (two providers fold in).
    with store._session() as s, s.begin():
        s.add(DailySnapshot(owner="me", source="oura", day=day))


def test_workout_source_id_partial_unique():
    started = datetime(2026, 6, 30, 6, 0, tzinfo=timezone.utc)
    with store._session() as s, s.begin():
        s.add(Workout(owner="me", source="whoop", source_id="abc",
                      name="Run", started_at=started, duration_min=30))
    # Same (source, source_id) collides — synced rows upsert idempotently.
    with pytest.raises(IntegrityError):
        with store._session() as s, s.begin():
            s.add(Workout(owner="me", source="whoop", source_id="abc",
                          name="Run again", started_at=started, duration_min=31))
    # Null source_id (manual rows) never collide, even many of them.
    with store._session() as s, s.begin():
        s.add(Workout(owner="me", source="manual", source_id=None,
                      name="M1", started_at=started, duration_min=10))
        s.add(Workout(owner="me", source="manual", source_id=None,
                      name="M2", started_at=started, duration_min=20))
    with store._session() as s:
        manual = s.scalars(
            select(Workout).where(Workout.source == "manual")
        ).all()
        assert len(manual) == 2
