"""Habits endpoints (M3) — definitions + the per-day completion log.

The completion log is the source of truth; streaks, the week grid, and
percentages are derived on read. Toggling is the core write; "auto"
completions arrive from linked domains (water today, workouts in M4) and
never clobber a manual tap.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Response

from ..schemas import HabitCreate, HabitOut, HabitsWeek, HabitToggle, HabitUpdate
from ..store import store

router = APIRouter(prefix="/api/habits", tags=["habits"])


@router.get("", response_model=HabitsWeek)
def habits_week(week: date | None = Query(default=None)) -> dict:
    """Habits + completion grid for the week containing `week` (default: now)."""
    from .. import recurrence

    return store.habits_week(recurrence.week_start(week) if week else None)


@router.post("", response_model=HabitOut, status_code=201)
def create_habit(body: HabitCreate) -> dict:
    return store.create_habit(body.model_dump())


@router.post("/{habit_id}/toggle", response_model=HabitOut)
def toggle_habit(habit_id: int, body: HabitToggle | None = None) -> dict:
    day = body.date if body else None
    updated = store.toggle_habit(habit_id, day)
    if updated is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    return updated


@router.patch("/{habit_id}", response_model=HabitOut)
def update_habit(habit_id: int, body: HabitUpdate) -> dict:
    updated = store.update_habit(habit_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    return updated


@router.delete("/{habit_id}", status_code=204)
def delete_habit(habit_id: int) -> Response:
    if not store.delete_habit(habit_id):
        raise HTTPException(status_code=404, detail="Habit not found")
    return Response(status_code=204)
