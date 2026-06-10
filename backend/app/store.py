"""In-memory data store for the Scuffed OS prototype backend.

State is process-local and resets on restart — this is a design-system prototype,
not a production datastore. Swap this module for a real DB (Postgres + SQLAlchemy,
etc.) without touching the routers. A lock guards mutations because FastAPI runs
sync endpoints in a threadpool.
"""
from __future__ import annotations

from threading import Lock


class Store:
    def __init__(self) -> None:
        self._lock = Lock()

        # Seeded to match the frontend's home task list (App.jsx SEED_TASKS).
        self.tasks: list[dict] = [
            {"id": 1, "label": "Pay rent", "done": True},
            {"id": 2, "label": "Reply to Priya about Lighthouse", "done": False},
            {"id": 3, "label": "Log lunch", "done": False},
            {"id": 4, "label": "Book dentist follow-up", "done": False},
            {"id": 5, "label": "Move $120 to savings", "done": False},
        ]
        self._next_task_id = 6

        # Seeded to match MemoryScreen.SAMPLE_MEMORIES (+ id and a relative time).
        self.memories: list[dict] = [
            {"id": 1, "text": "Mom's birthday is March 14 — she mentioned wanting that ceramics class.",
             "src": "voice note", "tags": ["family", "gifts"], "color": "plum", "when": "2 days ago"},
            {"id": 2, "text": "Prefer morning workouts; energy dips after 8pm. Schedule deep work before noon.",
             "src": "learned", "tags": ["health", "routine"], "color": "green", "when": "4 days ago"},
            {"id": 3, "text": "Project Lighthouse deadline moved to June 30. Loop in Priya before the 20th.",
             "src": "telegram", "tags": ["work"], "color": "sky", "when": "1 week ago"},
            {"id": 4, "text": "Trying to cut dining out to twice a week. Cook salmon more often.",
             "src": "voice note", "tags": ["finance", "nutrition"], "color": "clay", "when": "1 week ago"},
        ]
        self._next_memory_id = 5

    # ---- tasks ----
    def list_tasks(self) -> list[dict]:
        return list(self.tasks)

    def create_task(self, label: str, done: bool = False) -> dict:
        with self._lock:
            task = {"id": self._next_task_id, "label": label, "done": done}
            self._next_task_id += 1
            self.tasks.insert(0, task)  # newest first, like the prototype
            return task

    def update_task(self, task_id: int, patch: dict) -> dict | None:
        with self._lock:
            for task in self.tasks:
                if task["id"] == task_id:
                    for key, value in patch.items():
                        if value is not None:
                            task[key] = value
                    return task
        return None

    # ---- memory ----
    def list_memories(self) -> list[dict]:
        return list(self.memories)

    def create_memory(self, text: str, src: str = "note", tags: list[str] | None = None,
                      color: str = "green") -> dict:
        with self._lock:
            memory = {
                "id": self._next_memory_id,
                "text": text,
                "src": src,
                "tags": tags or [],
                "color": color,
                "when": "just now",
            }
            self._next_memory_id += 1
            self.memories.insert(0, memory)
            return memory


store = Store()
