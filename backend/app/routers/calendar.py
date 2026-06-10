"""Calendar endpoints (M3) — events with recurrence, expanded on read.

GET /events returns concrete *occurrences* in a window; a recurring series
is one stored row (see app/recurrence.py). PATCH edits the whole series;
DELETE with ?occurrence_start= removes a single occurrence (an exdate).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Response

from .. import recurrence
from ..schemas import EventCreate, EventOccurrence, EventUpdate, UpNextItem
from ..store import store

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _aware(dt: datetime) -> datetime:
    """Naive datetimes mean the user's local time — one convention across the
    HTTP surface and the assistant tools (the frontend always sends explicit
    offsets, so this only decides what hand-written/naive input means)."""
    return dt if dt.tzinfo else dt.astimezone()


def _check_recurrence(rule: str | None) -> None:
    if rule is None:
        return
    try:
        recurrence.validate(rule)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/events", response_model=list[EventOccurrence])
def list_events(
    window_from: datetime | None = Query(default=None, alias="from"),
    window_to: datetime | None = Query(default=None, alias="to"),
) -> list[dict]:
    """Occurrences in [from, to); defaults to the current Mon-start week."""
    if window_from is None or window_to is None:
        monday = recurrence.week_start(datetime.now().astimezone().date())
        local_start = datetime.combine(monday, datetime.min.time()).astimezone()
        window_from = window_from or local_start.astimezone(timezone.utc)
        window_to = window_to or window_from + timedelta(days=7)
    window_from, window_to = _aware(window_from), _aware(window_to)
    if window_to <= window_from:
        raise HTTPException(status_code=422, detail="'to' must be after 'from'")
    return store.events_between(window_from, window_to)


@router.post("/events", response_model=EventOccurrence, status_code=201)
def create_event(body: EventCreate) -> dict:
    _check_recurrence(body.recurrence)
    data = body.model_dump()
    data["start"] = _aware(data["start"])
    if data["end"] is not None:
        data["end"] = _aware(data["end"])
        if data["end"] <= data["start"]:
            raise HTTPException(status_code=422, detail="'end' must be after 'start'")
    return store.create_event(data)


@router.patch("/events/{event_id}", response_model=EventOccurrence)
def update_event(event_id: int, body: EventUpdate) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if patch.get("recurrence") is not None:
        _check_recurrence(patch["recurrence"])
    for key in ("start", "end"):
        if patch.get(key) is not None:
            patch[key] = _aware(patch[key])
    try:
        updated = store.update_event(event_id, patch)
    except ValueError as exc:  # end <= start after the patch
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return updated


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    occurrence_start: datetime | None = Query(default=None),
) -> Response:
    when = _aware(occurrence_start) if occurrence_start else None
    if not store.delete_event(event_id, occurrence_start=when):
        raise HTTPException(status_code=404, detail="Event not found")
    return Response(status_code=204)


@router.get("/up-next", response_model=list[UpNextItem])
def up_next(limit: int = Query(default=3, ge=1, le=10)) -> list[dict]:
    return store.up_next(limit=limit)
