"""Insights read surface (fitness slice 1). GET is a pure cache read over the
insights table — it never runs the rules or the LLM. POST /refresh force-
regenerates today (the manual refresh affordance)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from ..insights import engine
from ..schemas import InsightsDay
from ..store import _local_today, store

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _day_payload(day: date) -> dict:
    cards = store.list_insights(day)
    return {"date": day, "has_data": bool(cards), "cards": cards}


@router.get("", response_model=InsightsDay)
def get_insights(date_: date | None = Query(default=None, alias="date")) -> dict:
    """Cached cards for the day (default today). Never generates."""
    return _day_payload(date_ or _local_today())


@router.post("/refresh", response_model=InsightsDay)
def refresh_insights() -> dict:
    """Force-regenerate today's insights, then return them."""
    day = _local_today()
    engine.generate_for_day(day)
    return _day_payload(day)
