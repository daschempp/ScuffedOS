"""Task CRUD endpoints — the one rich task model (review D1).

TasksScreen, Home, and the assistant all read and write these same rows.
M3 adds the task's satellites: reminders that fire (rows, not strings),
real file attachments (bytes under settings.attachments_dir, metadata on
the task), and a recurrence rule validated on write.
"""
from __future__ import annotations

import mimetypes
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from .. import recurrence
from ..config import settings
from ..schemas import Task, TaskCreate, TaskReminderCreate, TaskReminderOut, TaskUpdate
from ..store import store

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _check_recurrence(rule: str | None) -> None:
    if rule is None:
        return
    try:
        recurrence.validate(rule)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _aware_local(dt: datetime) -> datetime:
    """Naive datetimes mean the user's local time — same convention as the
    calendar router and the assistant tools (local-first, spec §3)."""
    return dt.astimezone() if dt.tzinfo is None else dt


def _task_dir(task_id: int) -> Path:
    return Path(settings.attachments_dir) / str(task_id)


def _safe_file_path(task_id: int, file_id: str) -> Path | None:
    """Resolve a stored file path, refusing anything that escapes the
    attachments root. Uploads name files with server uuids, but `files`
    metadata is also client-patchable on the task row, so a crafted id like
    '../../.env' must never reach the filesystem."""
    root = Path(settings.attachments_dir).resolve()
    path = (root / str(task_id) / file_id).resolve()
    if path.parent != root / str(task_id) or not path.name == file_id:
        return None
    return path


@router.get("", response_model=list[Task])
def list_tasks() -> list[dict]:
    return store.list_tasks()


@router.post("", response_model=Task, status_code=201)
def create_task(body: TaskCreate) -> dict:
    _check_recurrence(body.recurrence)
    return store.create_task(body.model_dump())


@router.patch("/{task_id}", response_model=Task)
def update_task(task_id: int, body: TaskUpdate) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if patch.get("recurrence") is not None:
        _check_recurrence(patch["recurrence"])
    updated = store.update_task(task_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int) -> Response:
    if not store.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    shutil.rmtree(_task_dir(task_id), ignore_errors=True)
    return Response(status_code=204)


# ---- reminders (M3 — fired by app/reminders.py) ----------------------------
@router.get("/{task_id}/reminders", response_model=list[TaskReminderOut])
def list_reminders(task_id: int) -> list[dict]:
    rows = store.list_task_reminders(task_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return rows


@router.post("/{task_id}/reminders", response_model=TaskReminderOut, status_code=201)
def add_reminder(task_id: int, body: TaskReminderCreate) -> dict:
    row = store.add_task_reminder(task_id, _aware_local(body.remind_at), body.label)
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@router.delete("/{task_id}/reminders/{reminder_id}", status_code=204)
def delete_reminder(task_id: int, reminder_id: int) -> Response:
    if not store.delete_task_reminder(task_id, reminder_id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return Response(status_code=204)


# ---- file attachments (M3 — bytes on disk, metadata on the task row) -------
@router.post("/{task_id}/files", response_model=Task, status_code=201)
def upload_file(task_id: int, file: UploadFile) -> dict:
    if store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    file_id = uuid.uuid4().hex
    target_dir = _task_dir(task_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / file_id  # disk name is the id — never client input
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    meta = {
        "id": file_id,
        "name": file.filename or "untitled",
        "size": target.stat().st_size,
    }
    store.append_task_file(task_id, meta)
    return store.get_task(task_id)


@router.get("/{task_id}/files/{file_id}")
def download_file(task_id: int, file_id: str) -> FileResponse:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    meta = next((f for f in task["files"] if str(f.get("id")) == file_id), None)
    path = _safe_file_path(task_id, file_id)
    if meta is None or path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type = mimetypes.guess_type(meta["name"])[0] or "application/octet-stream"
    return FileResponse(path, filename=meta["name"], media_type=media_type)


@router.delete("/{task_id}/files/{file_id}", status_code=204)
def delete_file(task_id: int, file_id: str) -> Response:
    removed = store.remove_task_file(task_id, file_id)
    if removed is None and store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if removed is None:
        raise HTTPException(status_code=404, detail="File not found")
    path = _safe_file_path(task_id, file_id)
    if path is not None:
        path.unlink(missing_ok=True)
    return Response(status_code=204)
