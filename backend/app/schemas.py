"""Pydantic request/response models for the Scuffed OS API."""
from __future__ import annotations

from pydantic import BaseModel


# ---- Assistant ------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str


class ChatAction(BaseModel):
    icon: str
    title: str
    meta: str
    cta: str
    screen: str
    # Set when the assistant should create a real task with this label.
    makeTask: str | None = None


class ChatResponse(BaseModel):
    text: str
    action: ChatAction | None = None


# ---- Tasks ----------------------------------------------------------------
class Task(BaseModel):
    id: int
    label: str
    done: bool = False


class TaskCreate(BaseModel):
    label: str
    done: bool = False


class TaskUpdate(BaseModel):
    label: str | None = None
    done: bool | None = None


# ---- Memory (second brain) ------------------------------------------------
class Memory(BaseModel):
    id: int
    text: str
    src: str
    tags: list[str]
    color: str
    when: str


class MemoryCreate(BaseModel):
    text: str
    src: str = "note"
    tags: list[str] = []
    color: str = "green"
