"""Nutrition endpoints (M3) — food/water log, targets, day totals, week trend.

Totals are computed on read; macros are stored as filed (food-DB lookup,
LLM estimate, or manual entry — manual always possible). Hitting the water
goal auto-completes a linked habit; dropping back under retracts it.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Response

from .. import food_db
from ..schemas import (
    FoodHit,
    MealCreate,
    MealOut,
    MealUpdate,
    NutritionDay,
    NutritionTargetsOut,
    NutritionTargetsUpdate,
    NutritionWeek,
    WaterOut,
    WaterUpdate,
)
from ..store import store

router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


@router.get("/day", response_model=NutritionDay)
def nutrition_day(date_: date | None = Query(default=None, alias="date")) -> dict:
    return store.nutrition_day(date_)


@router.post("/meals", response_model=MealOut, status_code=201)
def log_meal(body: MealCreate) -> dict:
    return store.create_meal(body.model_dump())


@router.patch("/meals/{meal_id}", response_model=MealOut)
def update_meal(meal_id: int, body: MealUpdate) -> dict:
    updated = store.update_meal(meal_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Meal not found")
    return updated


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int) -> Response:
    if not store.delete_meal(meal_id):
        raise HTTPException(status_code=404, detail="Meal not found")
    return Response(status_code=204)


@router.post("/water", response_model=WaterOut)
def set_water(body: WaterUpdate) -> dict:
    return store.set_water(day=body.date, cups=body.cups, delta=body.delta)


@router.get("/week", response_model=NutritionWeek)
def nutrition_week(date_: date | None = Query(default=None, alias="date")) -> dict:
    return store.nutrition_week(date_)


@router.get("/targets", response_model=NutritionTargetsOut)
def get_targets() -> dict:
    return store.get_targets()


@router.put("/targets", response_model=NutritionTargetsOut)
def put_targets(body: NutritionTargetsUpdate) -> dict:
    return store.update_targets(body.model_dump(exclude_unset=True))


@router.get("/foods", response_model=list[FoodHit])
def search_foods(q: str = Query(min_length=1), limit: int = Query(default=5, ge=1, le=10)) -> list[dict]:
    hits = food_db.search(q, limit)
    if hits is None:
        raise HTTPException(
            status_code=503,
            detail="Food database is unreachable — log the meal with manual macros.",
        )
    return hits
