"""The assistant's tool surface (review D2): read + write over every built
domain, read-only over seeded ones.

Each tool pairs a Claude tool definition with an executor. Write executors
also return an "action card" — the UI's receipt of what actually executed,
with a deep link to the right screen. Descriptions state *when* to call the
tool, not just what it does.
"""
from __future__ import annotations

import json

from . import memory_engine
from .seeds import CALENDAR_TODAY, FINANCE_SUMMARY, FITNESS_TODAY, HABITS_TODAY, NUTRITION_TODAY
from .store import store

_GROUPS = ["Today", "Upcoming", "Someday"]
_PRIOS = ["low", "med", "high"]


def _compact_task(t: dict) -> dict:
    out = {k: t[k] for k in ("id", "label", "done", "group", "prio", "list", "due", "late")}
    out["deadline"] = t["deadline"].isoformat() if t["deadline"] else None
    if t["description"]:
        out["description"] = t["description"][:200]
    if t["labels"]:
        out["labels"] = t["labels"]
    if t["subtasks"]:
        out["subtasks"] = [{"label": s["label"], "done": s["done"]} for s in t["subtasks"]]
    return out


def _task_action(title: str, meta: str) -> dict:
    return {"icon": "circle-check-big", "title": title, "meta": meta,
            "cta": "View tasks", "screen": "tasks"}


def _memory_action(title: str, meta: str) -> dict:
    return {"icon": "brain", "title": title, "meta": meta,
            "cta": "Open brain", "screen": "memory"}


# ---- executors (each returns (result, action | None)) ----------------------

def _list_tasks(args: dict):
    tasks = [_compact_task(t) for t in store.list_tasks()]
    if args.get("open_only"):
        tasks = [t for t in tasks if not t["done"]]
    return {"tasks": tasks}, None


def _create_task(args: dict):
    task = store.create_task({k: v for k, v in args.items() if v is not None})
    return {"created": _compact_task(task)}, _task_action(
        "Added to Tasks", f"{task['label']}" + (f" · {task['due']}" if task["due"] else "")
    )


def _update_task(args: dict):
    task_id = args.pop("task_id")
    patch = {k: v for k, v in args.items() if v is not None}
    task = store.update_task(task_id, patch)
    if task is None:
        return {"error": f"No task with id {task_id}."}, None
    title = "Task completed" if patch.get("done") else "Task updated"
    return {"updated": _compact_task(task)}, _task_action(title, task["label"])


def _delete_task(args: dict):
    task = store.get_task(args["task_id"])
    if task is None or not store.delete_task(args["task_id"]):
        return {"error": f"No task with id {args['task_id']}."}, None
    return {"deleted": args["task_id"]}, _task_action("Task deleted", task["label"])


def _search_memory(args: dict):
    hits = memory_engine.search(args["query"], limit=args.get("limit", 5))
    if hits is None:
        # Engine offline — fall back to the canonical notes so recall degrades
        # gracefully instead of failing.
        recent = [{"text": m["text"], "tags": m["tags"], "when": m["when"]}
                  for m in store.list_memories()[:10]]
        return {"results": recent, "note": "semantic search unavailable — showing recent notes"}, None
    return {"results": hits}, None


def _remember(args: dict):
    memory = memory_engine.remember_verbatim(args["text"], tags=args.get("tags") or [])
    return {"stored": {"id": memory["id"], "text": memory["text"]}}, _memory_action(
        "Stored in memory", memory["text"][:60]
    )


def _list_memories(args: dict):
    rows = store.list_memories()[: args.get("limit", 10)]
    return {"memories": [{"id": m["id"], "text": m["text"], "tags": m["tags"], "when": m["when"]}
                         for m in rows]}, None


def _update_memory(args: dict):
    memory_id = args.pop("memory_id")
    patch = {k: v for k, v in args.items() if v is not None}
    updated = store.update_memory(memory_id, patch)
    if updated is None:
        return {"error": f"No memory with id {memory_id}."}, None
    if "text" in patch:
        memory_engine.sync_update(updated.get("mem0_id"), updated["text"])
    return {"updated": {"id": updated["id"], "text": updated["text"]}}, _memory_action(
        "Memory updated", updated["text"][:60]
    )


def _forget_memory(args: dict):
    deleted = store.delete_memory(args["memory_id"])
    if deleted is None:
        return {"error": f"No memory with id {args['memory_id']}."}, None
    memory_engine.sync_delete(deleted.get("mem0_id"))
    return {"forgotten": args["memory_id"]}, _memory_action("Memory forgotten", deleted["text"][:60])


def _seed_reader(payload: dict):
    def read(_args: dict):
        return payload, None
    return read


_STRING = {"type": "string"}

TOOLS: list[dict] = [
    {"name": "list_tasks",
     "description": "List the user's tasks. Call this before updating/completing/deleting a task to find its id, or when the user asks what's on their plate.",
     "input_schema": {"type": "object", "properties": {
         "open_only": {"type": "boolean", "description": "Only return tasks that aren't done."}},
         "additionalProperties": False},
     "run": _list_tasks},
    {"name": "create_task",
     "description": "Create a real task. Call this whenever the user asks to add a task, set a reminder, or commits to doing something ('I should call mom' → offer/create a task).",
     "input_schema": {"type": "object", "properties": {
         "label": _STRING,
         "group": {"type": "string", "enum": _GROUPS, "description": "Defaults to Today."},
         "deadline": {"type": "string", "description": "YYYY-MM-DD, if the user gave a date."},
         "prio": {"type": "string", "enum": _PRIOS},
         "list": {"type": "string", "description": "Work, Health, Finance or Personal."},
         "description": _STRING,
         "labels": {"type": "array", "items": _STRING}},
         "required": ["label"], "additionalProperties": False},
     "run": _create_task},
    {"name": "update_task",
     "description": "Update or complete an existing task (look up its id with list_tasks first). Set done=true to complete it.",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "integer"},
         "label": _STRING, "done": {"type": "boolean"},
         "group": {"type": "string", "enum": _GROUPS},
         "deadline": {"type": "string", "description": "YYYY-MM-DD"},
         "prio": {"type": "string", "enum": _PRIOS},
         "list": _STRING, "description": _STRING},
         "required": ["task_id"], "additionalProperties": False},
     "run": _update_task},
    {"name": "delete_task",
     "description": "Permanently delete a task. Only when the user explicitly asks to delete/remove it (completing is update_task with done=true).",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}},
                      "required": ["task_id"], "additionalProperties": False},
     "run": _delete_task},
    {"name": "search_memory",
     "description": "Semantic search over the user's second brain. Call this when the user references past context ('what did I say about…', 'when is mom's birthday') or when personal context would improve your answer.",
     "input_schema": {"type": "object", "properties": {
         "query": _STRING, "limit": {"type": "integer"}},
         "required": ["query"], "additionalProperties": False},
     "run": _search_memory},
    {"name": "remember",
     "description": "File something in the user's second brain verbatim. Call this when the user says 'remember X' or shares a durable fact worth keeping.",
     "input_schema": {"type": "object", "properties": {
         "text": _STRING, "tags": {"type": "array", "items": _STRING}},
         "required": ["text"], "additionalProperties": False},
     "run": _remember},
    {"name": "list_memories",
     "description": "List the most recent second-brain notes (newest first). Use search_memory for anything topical.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}},
                      "additionalProperties": False},
     "run": _list_memories},
    {"name": "update_memory",
     "description": "Edit a stored memory's text or tags (find its id via list_memories/search_memory).",
     "input_schema": {"type": "object", "properties": {
         "memory_id": {"type": "integer"}, "text": _STRING,
         "tags": {"type": "array", "items": _STRING}},
         "required": ["memory_id"], "additionalProperties": False},
     "run": _update_memory},
    {"name": "forget_memory",
     "description": "Delete a stored memory. Only when the user explicitly asks to forget/remove it.",
     "input_schema": {"type": "object", "properties": {"memory_id": {"type": "integer"}},
                      "required": ["memory_id"], "additionalProperties": False},
     "run": _forget_memory},
    {"name": "get_calendar_today",
     "description": "Read today's calendar. Call when the user asks about their day, schedule or events.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(CALENDAR_TODAY)},
    {"name": "get_nutrition_today",
     "description": "Read today's nutrition totals (calories, protein, water). Call for any food/diet question.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(NUTRITION_TODAY)},
    {"name": "get_finance_summary",
     "description": "Read the finance snapshot (balance, budgets, recent transactions). Call for any money/spending question.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(FINANCE_SUMMARY)},
    {"name": "get_habits_today",
     "description": "Read today's habit progress and streaks.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(HABITS_TODAY)},
    {"name": "get_fitness_today",
     "description": "Read today's recovery/sleep/strain numbers.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(FITNESS_TODAY)},
]

DEFINITIONS = [{k: t[k] for k in ("name", "description", "input_schema")} for t in TOOLS]
_BY_NAME = {t["name"]: t["run"] for t in TOOLS}


def execute(name: str, args: dict) -> tuple[str, dict | None]:
    """Run one tool call; returns (json_result_for_the_model, action_card)."""
    runner = _BY_NAME.get(name)
    if runner is None:
        return json.dumps({"error": f"Unknown tool {name}."}), None
    try:
        result, action = runner(dict(args or {}))
    except Exception as exc:  # tool errors go back to the model, not the user
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}), None
    return json.dumps(result, default=str), action
