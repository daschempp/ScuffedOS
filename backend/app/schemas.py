"""Pydantic request/response models for the Scuffed OS API.

Vocabulary fields (group, prio) are Literal-constrained (review R8) so clients
and the assistant's tools can't invent values. Display strings (`due`, `late`,
`when`) are derived server-side from stored facts and are read-only.
"""
from __future__ import annotations

from datetime import date, datetime
# The task models have a field literally named `list` (the prototype's API
# contract). Under Python 3.14's deferred annotations, that field shadows the
# `list` builtin when sibling `list[...]` annotations are evaluated — so task
# models use typing.List instead.
from typing import List, Literal

from pydantic import BaseModel, Field

TaskGroup = Literal["Today", "Upcoming", "Someday"]
TaskPriority = Literal["low", "med", "high"]


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
class Subtask(BaseModel):
    id: int | float  # client-generated (Date.now())
    label: str
    done: bool = False


class TaskFile(BaseModel):
    """File *metadata* only until real uploads land in M3."""

    id: int | float
    name: str
    size: int | None = None


class Task(BaseModel):
    id: int
    label: str
    done: bool
    group: TaskGroup
    deadline: date | None
    prio: TaskPriority
    list: str
    description: str
    subtasks: List[Subtask]
    labels: List[str]
    reminders: List[str]
    files: List[TaskFile]
    # Derived display facts (review R6) — computed from deadline/done on read.
    due: str | None
    late: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskCreate(BaseModel):
    label: str = Field(min_length=1)
    done: bool = False
    group: TaskGroup = "Today"
    deadline: date | None = None
    prio: TaskPriority = "med"
    list: str = "Personal"
    description: str = ""
    subtasks: List[Subtask] = []
    labels: List[str] = []
    reminders: List[str] = []
    files: List[TaskFile] = []


class TaskUpdate(BaseModel):
    """Partial update. Only keys the client sends are applied; an explicit
    null clears `deadline` and is ignored for non-nullable fields (R7)."""

    label: str | None = Field(default=None, min_length=1)
    done: bool | None = None
    group: TaskGroup | None = None
    deadline: date | None = None
    prio: TaskPriority | None = None
    list: str | None = None
    description: str | None = None
    subtasks: List[Subtask] | None = None
    labels: List[str] | None = None
    reminders: List[str] | None = None
    files: List[TaskFile] | None = None


# ---- Memory (second brain) ------------------------------------------------
class Memory(BaseModel):
    id: int
    text: str
    src: str
    tags: list[str]
    color: str
    when: str  # derived relative time ("2 days ago")
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    text: str = Field(min_length=1)
    src: str = "note"
    tags: list[str] = []
    color: str = "green"


class MemoryUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    src: str | None = None
    tags: list[str] | None = None
    color: str | None = None
