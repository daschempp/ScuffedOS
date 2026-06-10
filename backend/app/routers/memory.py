"""Second-brain memory endpoints (list / file / edit / forget)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from ..schemas import Memory, MemoryCreate, MemoryUpdate
from ..store import store

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[Memory])
def list_memories() -> list[dict]:
    return store.list_memories()


@router.post("", response_model=Memory, status_code=201)
def create_memory(body: MemoryCreate) -> dict:
    return store.create_memory(body.model_dump())


@router.patch("/{memory_id}", response_model=Memory)
def update_memory(memory_id: int, body: MemoryUpdate) -> dict:
    updated = store.update_memory(memory_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return updated


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: int) -> Response:
    if not store.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return Response(status_code=204)
