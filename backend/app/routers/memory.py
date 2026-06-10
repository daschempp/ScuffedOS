"""Second-brain memory endpoints (list / file / edit / forget).

Rows live in the canonical `memories` table; each write also propagates to
the Mem0 vector store (best-effort) so the assistant can recall it
semantically. See app/memory_engine.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from .. import memory_engine
from ..schemas import Memory, MemoryCreate, MemoryUpdate
from ..store import store

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[Memory])
def list_memories() -> list[dict]:
    return store.list_memories()


@router.post("", response_model=Memory, status_code=201)
def create_memory(body: MemoryCreate) -> dict:
    memory = store.create_memory(body.model_dump())
    memory_engine.index_row(memory)
    return memory


@router.patch("/{memory_id}", response_model=Memory)
def update_memory(memory_id: int, body: MemoryUpdate) -> dict:
    patch = body.model_dump(exclude_unset=True)
    updated = store.update_memory(memory_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if "text" in patch:
        memory_engine.sync_update(updated.get("mem0_id"), updated["text"])
    return updated


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: int) -> Response:
    deleted = store.delete_memory(memory_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    memory_engine.sync_delete(deleted.get("mem0_id"))
    return Response(status_code=204)
