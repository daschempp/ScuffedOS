"""Task CRUD endpoints — the one rich task model (review D1).

TasksScreen, Home, and the assistant all read and write these same rows.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from ..schemas import Task, TaskCreate, TaskUpdate
from ..store import store

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
def list_tasks() -> list[dict]:
    return store.list_tasks()


@router.post("", response_model=Task, status_code=201)
def create_task(body: TaskCreate) -> dict:
    return store.create_task(body.model_dump())


@router.patch("/{task_id}", response_model=Task)
def update_task(task_id: int, body: TaskUpdate) -> dict:
    updated = store.update_task(task_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int) -> Response:
    if not store.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return Response(status_code=204)
