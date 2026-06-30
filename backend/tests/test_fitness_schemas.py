"""Fitness Pydantic schemas (M4): field names, types, the `date` alias, defaults."""
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    FitnessStatus,
    FitnessToday,
    FitnessVital,
    FitnessWeek,
    FitnessWeekDay,
    ProviderStatus,
    WorkoutCreate,
    WorkoutOut,
)


def test_provider_status_shape():
    ps = ProviderStatus(
        provider="whoop",
        status="connected",
        connected_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        last_sync_at=None,
    )
    assert ps.provider == "whoop"
    assert ps.status == "connected"
    assert ps.provider_user_id is None
    with pytest.raises(ValidationError):
        ProviderStatus(provider="whoop", status="bogus",
                       connected_at=datetime.now(timezone.utc), last_sync_at=None)


def test_fitness_status_wraps_providers():
    fs = FitnessStatus(connected=True, providers=[
        ProviderStatus(provider="whoop", status="needs_reauth",
                       connected_at=datetime.now(timezone.utc), last_sync_at=None),
    ])
    assert fs.connected is True
    assert fs.providers[0].status == "needs_reauth"
    empty = FitnessStatus(connected=False, providers=[])
    assert empty.providers == []


def test_fitness_vital_and_today():
    vital = FitnessVital(key="hrv", label="HRV", value=58.0, unit="ms",
                         delta=6.0, icon="activity", tint="sky")
    today = FitnessToday(
        date=date(2026, 6, 30), source="whoop", recovery_pct=82,
        day_strain=8.1, sleep_quality_pct=74, vitals=[vital], has_data=True,
    )
    assert today.date == date(2026, 6, 30)
    assert today.source == "whoop"
    assert today.vitals[0].delta == 6.0
    # No data: every metric nullable, has_data False, source None.
    blank = FitnessToday(date=date(2026, 6, 30), source=None, recovery_pct=None,
                         day_strain=None, sleep_quality_pct=None, vitals=[],
                         has_data=False)
    assert blank.has_data is False and blank.source is None


def test_workout_out_shape_includes_derived_display():
    w = WorkoutOut(
        id=1, source="whoop", name="Run", sport="running",
        started_at=datetime(2026, 6, 30, 6, 10, tzinfo=timezone.utc),
        duration_min=42, strain=11.3, calories=520, avg_hr=148, max_hr=171,
        when="Today · 6:10am", icon="activity", tint="sky",
    )
    assert w.source == "whoop"
    assert w.when == "Today · 6:10am"
    with pytest.raises(ValidationError):
        WorkoutOut(id=1, source="strava", name="x", sport=None,
                   started_at=datetime.now(timezone.utc), duration_min=0,
                   strain=None, calories=None, avg_hr=None, max_hr=None,
                   when="", icon="activity", tint="sky")


def test_workout_create_validates_and_defaults():
    wc = WorkoutCreate(name="Lift", started_at=datetime.now(timezone.utc),
                       duration_min=30)
    assert wc.sport is None and wc.strain is None and wc.calories is None
    # name required, non-empty; negatives rejected.
    with pytest.raises(ValidationError):
        WorkoutCreate(name="", started_at=datetime.now(timezone.utc), duration_min=30)
    with pytest.raises(ValidationError):
        WorkoutCreate(name="Lift", started_at=datetime.now(timezone.utc),
                      duration_min=-1)
    with pytest.raises(ValidationError):
        WorkoutCreate(name="Lift", started_at=datetime.now(timezone.utc),
                      duration_min=30, avg_hr=-5)


def test_fitness_week_shape():
    days = [FitnessWeekDay(date=date(2026, 6, 29), dow="M", strain=8.0,
                           frac=round(8.0 / 21, 2))]
    week = FitnessWeek(days=days, avg_strain=8.0, peak_day=date(2026, 6, 29))
    assert week.days[0].dow == "M"
    assert week.days[0].frac == round(8.0 / 21, 2)
    assert week.peak_day == date(2026, 6, 29)
    assert FitnessWeek(days=[], avg_strain=0.0, peak_day=None).peak_day is None
