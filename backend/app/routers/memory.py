"""Second-brain memory endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas import Memory, MemoryCreate
from ..store import store

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[Memory])
def list_memories() -> list[dict]:
    return store.list_memories()


@router.post("", response_model=Memory, status_code=201)
def create_memory(body: MemoryCreate) -> dict:
    return store.create_memory(body.text, body.src, body.tags, body.color)
