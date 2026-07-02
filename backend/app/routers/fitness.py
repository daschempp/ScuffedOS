"""Fitness data endpoints (M4) — normalized reads/writes.

After the M5 OAuth refactor this module owns ONLY the fitness data surface:
/today, /week, /workouts (list/create/delete), and /sync. The OAuth dance
(connect/callback/disconnect/status + the CSRF state store + the auth_router
hosting /auth/{provider}/callback) moved to the shared routers/oauth.py. Reads
never touch a live WHOOP call — they come straight from the normalized tables.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Response

from .. import fitness_sync
from ..providers import pull_providers
from ..schemas import (
    FitnessToday,
    FitnessWeek,
    WorkoutCreate,
    WorkoutOut,
)
from ..store import store

router = APIRouter(prefix="/api/fitness", tags=["fitness"])


# ---- reads (normalized tables only; never a live provider call) ------------
@router.get("/today", response_model=FitnessToday)
def fitness_today(date_: date | None = Query(default=None, alias="date")) -> dict:
    return store.fitness_today(date_)


@router.get("/week", response_model=FitnessWeek)
def fitness_week(date_: date | None = Query(default=None, alias="date")) -> dict:
    return store.fitness_week(date_)


@router.get("/workouts", response_model=list[WorkoutOut])
def list_workouts(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    return store.list_workouts(limit)


# ---- manual workout write --------------------------------------------------
@router.post("/workouts", response_model=WorkoutOut, status_code=201)
def create_workout(body: WorkoutCreate) -> dict:
    return store.create_workout(body.model_dump())


@router.delete("/workouts/{workout_id}", status_code=204)
def delete_workout(workout_id: int) -> Response:
    if not store.delete_workout(workout_id):
        raise HTTPException(status_code=404, detail="Workout not found")
    return Response(status_code=204)


# ---- on-demand sync --------------------------------------------------------
@router.post("/sync")
def sync_now() -> dict:
    """Run one sync pass now. Delegates to fitness_sync.tick(); reads never
    depend on it, so a failing tick just returns 0. `providers` lists the
    pull-providers that were polled."""
    count = fitness_sync.tick()
    try:
        providers_list = [p.name for p in pull_providers()]
    except RuntimeError:
        providers_list = []
    return {"synced": count, "providers": providers_list}
