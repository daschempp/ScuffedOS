"""Durable data store — SQLAlchemy over Postgres behind the same `Store` facade.

Routers keep calling plain methods that take and return API-shaped dicts; all
ORM/session detail stays in here. The engine is built lazily from settings on
first use so importing the app never requires a database; tests call
`store.configure(...)` to point the same singleton at a throwaway engine.

Patch semantics (review R7): updates receive only the keys the client sent
(`exclude_unset`). An explicit null clears nullable fields (deadline); nulls on
non-nullable fields are ignored rather than erroring.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .db import make_engine, make_session_factory
from .display import aware_utc, relative_when, task_due_display
from .models import Conversation, ConversationMessage, Memory, Task, utcnow

_TASK_FIELDS = {
    "label", "done", "group", "deadline", "prio", "list", "description",
    "subtasks", "labels", "reminders", "files",
}
_TASK_NULLABLE = {"deadline"}
_MEMORY_FIELDS = {"text", "src", "tags", "color"}


def _task_dict(t: Task) -> dict:
    due, late = task_due_display(t.deadline, t.done, t.completed_at)
    return {
        "id": t.id,
        "label": t.label,
        "done": t.done,
        "group": t.group,
        "deadline": t.deadline,
        "prio": t.prio,
        "list": t.list_name,
        "description": t.description,
        "subtasks": t.subtasks or [],
        "labels": t.labels or [],
        "reminders": t.reminders or [],
        "files": t.files or [],
        "due": due,
        "late": late,
        "created_at": aware_utc(t.created_at),
        "updated_at": aware_utc(t.updated_at),
        "completed_at": aware_utc(t.completed_at),
    }


def _memory_dict(m: Memory) -> dict:
    return {
        "id": m.id,
        "text": m.text,
        "src": m.src,
        "tags": m.tags or [],
        "color": m.color,
        "when": relative_when(m.created_at),
        "created_at": aware_utc(m.created_at),
        "updated_at": aware_utc(m.updated_at),
    }


def _message_dict(m: ConversationMessage) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "role": m.role,
        "content": m.content,
        "actions": m.actions,
        "created_at": aware_utc(m.created_at),
    }


def _apply_task_patch(task: Task, patch: dict) -> None:
    for key, value in patch.items():
        if key not in _TASK_FIELDS:
            continue
        if value is None and key not in _TASK_NULLABLE:
            continue
        if key == "list":
            task.list_name = value
        elif key == "done":
            if value and not task.done:
                task.completed_at = utcnow()
            elif not value:
                task.completed_at = None
            task.done = value
        else:
            setattr(task, key, value)


class Store:
    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory

    def configure(self, session_factory: sessionmaker | None) -> None:
        """Point the store at a different database (tests) or back to lazy (None)."""
        self._session_factory = session_factory

    def _session(self) -> Session:
        if self._session_factory is None:
            from .config import settings

            if not settings.database_url:
                raise RuntimeError(
                    "DATABASE_URL is not set. Put your Postgres connection string "
                    "(Supabase: the session-pooler URL) in backend/.env."
                )
            self._session_factory = make_session_factory(make_engine(settings.database_url))
        return self._session_factory()

    # ---- tasks ----
    def list_tasks(self) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(Task).order_by(Task.id.desc())).all()
            return [_task_dict(t) for t in rows]

    def get_task(self, task_id: int) -> dict | None:
        with self._session() as s:
            task = s.get(Task, task_id)
            return _task_dict(task) if task else None

    def create_task(self, data: dict) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            fields = {k: v for k, v in data.items() if k in _TASK_FIELDS and k != "list"}
            task = Task(owner=settings.owner, **fields)
            if "list" in data:
                task.list_name = data["list"]
            if task.done:
                task.completed_at = utcnow()
            s.add(task)
            s.flush()
            return _task_dict(task)

    def update_task(self, task_id: int, patch: dict) -> dict | None:
        with self._session() as s, s.begin():
            task = s.get(Task, task_id)
            if task is None:
                return None
            _apply_task_patch(task, patch)
            s.flush()
            return _task_dict(task)

    def delete_task(self, task_id: int) -> bool:
        with self._session() as s, s.begin():
            task = s.get(Task, task_id)
            if task is None:
                return False
            s.delete(task)
            return True

    # ---- memory ----
    def list_memories(self) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(Memory).order_by(Memory.id.desc())).all()
            return [_memory_dict(m) for m in rows]

    def create_memory(self, data: dict) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            memory = Memory(
                owner=settings.owner,
                **{k: v for k, v in data.items() if k in _MEMORY_FIELDS and v is not None},
            )
            s.add(memory)
            s.flush()
            return _memory_dict(memory)

    def update_memory(self, memory_id: int, patch: dict) -> dict | None:
        with self._session() as s, s.begin():
            memory = s.get(Memory, memory_id)
            if memory is None:
                return None
            for key, value in patch.items():
                if key in _MEMORY_FIELDS and value is not None:
                    setattr(memory, key, value)
            s.flush()
            return _memory_dict(memory)

    def delete_memory(self, memory_id: int) -> bool:
        with self._session() as s, s.begin():
            memory = s.get(Memory, memory_id)
            if memory is None:
                return False
            s.delete(memory)
            return True

    # ---- conversations (used by the real assistant from M2 on) ----
    def create_conversation(self, title: str | None = None) -> dict:
        from .config import settings

        with self._session() as s, s.begin():
            conv = Conversation(owner=settings.owner, title=title)
            s.add(conv)
            s.flush()
            return {"id": conv.id, "title": conv.title,
                    "created_at": aware_utc(conv.created_at),
                    "updated_at": aware_utc(conv.updated_at)}

    def get_conversation(self, conversation_id: int) -> dict | None:
        with self._session() as s:
            conv = s.get(Conversation, conversation_id)
            if conv is None:
                return None
            return {"id": conv.id, "title": conv.title,
                    "created_at": aware_utc(conv.created_at),
                    "updated_at": aware_utc(conv.updated_at)}

    def latest_conversation(self) -> dict | None:
        with self._session() as s:
            conv = s.scalars(
                select(Conversation).order_by(Conversation.updated_at.desc()).limit(1)
            ).first()
            if conv is None:
                return None
            return {"id": conv.id, "title": conv.title,
                    "created_at": aware_utc(conv.created_at),
                    "updated_at": aware_utc(conv.updated_at)}

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        actions: list | None = None,
    ) -> dict | None:
        with self._session() as s, s.begin():
            conv = s.get(Conversation, conversation_id)
            if conv is None:
                return None
            msg = ConversationMessage(
                conversation_id=conversation_id, role=role, content=content, actions=actions
            )
            conv.updated_at = utcnow()
            if conv.title is None and role == "user":
                conv.title = content[:80]
            s.add(msg)
            s.flush()
            return _message_dict(msg)

    def list_messages(self, conversation_id: int) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.id)
            ).all()
            return [_message_dict(m) for m in rows]

    # ---- demo data ----
    def seed_demo(self) -> bool:
        """Insert the design-prototype sample rows (idempotent: skips if data exists).

        Dates are relative to today so the Today/Upcoming/Someday groups look
        the way the prototype intended no matter when you run it.
        """
        from .config import settings

        today = datetime.now().astimezone().date()
        with self._session() as s, s.begin():
            if s.scalars(select(Task).limit(1)).first() is not None:
                return False

            def day(offset: int) -> date:
                return today + timedelta(days=offset)

            tasks = [
                Task(label="Reply to Priya about Lighthouse", group="Today", deadline=day(0),
                     prio="high", list_name="Work",
                     description="She asked about the moved deadline — confirm the 30th works and loop in the design review.",
                     subtasks=[{"id": 11, "label": "Check calendar for the 30th", "done": True},
                               {"id": 12, "label": "Draft reply", "done": False}],
                     reminders=["1 hour before"],
                     files=[{"id": 101, "name": "lighthouse-brief.pdf", "size": 248000}]),
                Task(label="Log lunch", group="Today", deadline=day(0), prio="low",
                     list_name="Health", labels=["nutrition"], reminders=["1:00pm"]),
                Task(label="Book dentist follow-up", group="Today", deadline=day(-2), prio="med",
                     list_name="Health",
                     description="Call Oak Street Dental — ask for an early-morning slot."),
                Task(label="Move $120 to savings", group="Today", deadline=day(0), prio="med",
                     list_name="Finance", description="Roll over the dining-budget surplus.",
                     labels=["savings"]),
                Task(label="Pay rent", group="Today", deadline=day(0), prio="high",
                     list_name="Finance", done=True, completed_at=utcnow()),
                Task(label="Draft Q3 planning doc", group="Upcoming", deadline=day(1),
                     prio="high", list_name="Work",
                     description="Outline goals, headcount, and the roadmap themes.",
                     subtasks=[{"id": 61, "label": "Goals", "done": False},
                               {"id": 62, "label": "Roadmap themes", "done": False}],
                     labels=["planning"]),
                Task(label="Order mom's birthday gift", group="Upcoming", deadline=day(4),
                     prio="med", list_name="Personal",
                     description="The ceramics class she mentioned in a voice note.",
                     reminders=["Jun 11, 9:00am"],
                     files=[{"id": 701, "name": "ceramics-studio.png", "size": 1340000},
                            {"id": 702, "name": "gift-ideas.txt", "size": 1200}]),
                Task(label="Meal prep for the week", group="Upcoming", deadline=day(6),
                     prio="low", list_name="Health"),
                Task(label="Renew gym membership", group="Someday", prio="low", list_name="Health"),
                Task(label="Read 'Deep Work'", group="Someday", prio="low", list_name="Personal",
                     labels=["reading"]),
            ]
            for t in reversed(tasks):  # insert so list order (id desc) matches the prototype
                t.owner = settings.owner
                s.add(t)

            now = utcnow()
            memories = [
                Memory(text="Mom's birthday is March 14 — she mentioned wanting that ceramics class.",
                       src="voice note", tags=["family", "gifts"], color="plum",
                       created_at=now - timedelta(days=2)),
                Memory(text="Prefer morning workouts; energy dips after 8pm. Schedule deep work before noon.",
                       src="learned", tags=["health", "routine"], color="green",
                       created_at=now - timedelta(days=4)),
                Memory(text="Project Lighthouse deadline moved to June 30. Loop in Priya before the 20th.",
                       src="telegram", tags=["work"], color="sky",
                       created_at=now - timedelta(days=7)),
                Memory(text="Trying to cut dining out to twice a week. Cook salmon more often.",
                       src="voice note", tags=["finance", "nutrition"], color="clay",
                       created_at=now - timedelta(days=8)),
            ]
            for m in reversed(memories):
                m.owner = settings.owner
                s.add(m)
            return True


store = Store()
