"""The assistant's tool surface (review D2): read + write over every built
domain — tasks, memories, calendar, habits, nutrition (M3) — read-only over
the remaining seeded ones (fitness M4, finance M6).

Each tool pairs a Claude tool definition with an executor. Write executors
also return an "action card" — the UI's receipt of what actually executed,
with a deep link to the right screen. Descriptions state *when* to call the
tool, not just what it does.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import email_draft, fitness_sync, food_db, memory_engine, providers, recurrence
from .seeds import FINANCE_SUMMARY
from .store import store

_GROUPS = ["Today", "Upcoming", "Someday"]
_PRIOS = ["low", "med", "high"]
_TINTS = ["green", "sky", "plum", "honey", "clay"]
_SLOTS = ["Breakfast", "Lunch", "Snack", "Dinner"]


def _parse_dt(value: str) -> datetime:
    """ISO datetime from the model; naive means the user's local time."""
    dt = datetime.fromisoformat(value)
    return dt.astimezone() if dt.tzinfo is None else dt


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _check_rule(rule: str | None) -> str | None:
    """Returns an error message for the model, or None if the rule is fine."""
    if rule is None:
        return None
    try:
        recurrence.validate(rule)
        return None
    except ValueError as exc:
        return str(exc)


def _clamp(value, allowed: list[str], fallback: str | None):
    """Tool args skip the API's Pydantic layer, and the model occasionally
    ignores a schema enum. A stored out-of-vocabulary value would then fail
    response validation and 500 every later read — clamp instead."""
    return value if value in allowed else fallback


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


def _calendar_action(title: str, meta: str) -> dict:
    return {"icon": "calendar", "title": title, "meta": meta,
            "cta": "View calendar", "screen": "calendar"}


def _habit_action(title: str, meta: str) -> dict:
    return {"icon": "flame", "title": title, "meta": meta,
            "cta": "View habits", "screen": "habits"}


def _nutrition_action(title: str, meta: str) -> dict:
    return {"icon": "utensils", "title": title, "meta": meta,
            "cta": "View nutrition", "screen": "nutrition"}


def _fitness_action(title: str, meta: str) -> dict:
    return {"icon": "activity", "title": title, "meta": meta,
            "cta": "View fitness", "screen": "fitness"}


def _email_action(title: str, meta: str) -> dict:
    return {"icon": "mail", "title": title, "meta": meta,
            "cta": "Open email", "screen": "email"}


def _moodle_action(title: str, meta: str) -> dict:
    return {"icon": "graduation-cap", "title": title, "meta": meta,
            "cta": "Open school", "screen": "school"}


# ---- executors (each returns (result, action | None)) ----------------------

def _list_tasks(args: dict):
    tasks = [_compact_task(t) for t in store.list_tasks()]
    if args.get("open_only"):
        tasks = [t for t in tasks if not t["done"]]
    return {"tasks": tasks}, None


def _create_task(args: dict):
    if err := _check_rule(args.get("recurrence")):
        return {"error": err}, None
    args = {k: v for k, v in args.items() if v is not None}
    if "group" in args:
        args["group"] = _clamp(args["group"], _GROUPS, "Today")
    if "prio" in args:
        args["prio"] = _clamp(args["prio"], _PRIOS, "med")
    task = store.create_task(args)
    return {"created": _compact_task(task)}, _task_action(
        "Added to Tasks", f"{task['label']}" + (f" · {task['due']}" if task["due"] else "")
    )


def _update_task(args: dict):
    task_id = args.pop("task_id")
    patch = {k: v for k, v in args.items() if v is not None}
    if "group" in patch:
        patch["group"] = _clamp(patch["group"], _GROUPS, "Today")
    if "prio" in patch:
        patch["prio"] = _clamp(patch["prio"], _PRIOS, "med")
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


# ---- calendar (real from M3) ------------------------------------------------

def _compact_occurrence(o: dict) -> dict:
    local_start = o["start"].astimezone()
    out = {
        "id": o["id"],
        "title": o["title"],
        "date": local_start.date().isoformat(),
        "start": local_start.isoformat(timespec="minutes"),
        "end": o["end"].astimezone().isoformat(timespec="minutes"),
        "at": o["at"],
    }
    if o["location"]:
        out["location"] = o["location"]
    if o["recurring"]:
        out["recurring"] = o["recurrence_label"]
    return out


def _get_calendar(args: dict):
    start_day = _parse_date(args.get("date")) or datetime.now().astimezone().date()
    days = max(1, min(int(args.get("days", 1)), 31))
    window_from = datetime.combine(start_day, datetime.min.time()).astimezone()
    window_to = window_from + timedelta(days=days)
    occs = store.events_between(window_from, window_to)
    return {"from": start_day.isoformat(), "days": days,
            "events": [_compact_occurrence(o) for o in occs]}, None


def _create_event(args: dict):
    if err := _check_rule(args.get("recurrence")):
        return {"error": err}, None
    data = {
        "title": args["title"],
        "start": _parse_dt(args["start"]),
        "end": _parse_dt(args["end"]) if args.get("end") else None,
        "tint": _clamp(args.get("tint"), _TINTS, None),
        "location": args.get("location"),
        "description": args.get("description"),
        "recurrence": args.get("recurrence"),
    }
    if data["end"] is not None and data["end"] <= data["start"]:
        return {"error": "'end' must be after 'start'."}, None
    event = store.create_event(data)
    when = f"{event['start'].astimezone().strftime('%a %b %-d')} · {event['at']}"
    return {"created": _compact_occurrence(event)}, _calendar_action(
        "Added to Calendar", f"{event['title']} · {when}"
    )


def _update_event(args: dict):
    event_id = args.pop("event_id")
    if err := _check_rule(args.get("recurrence")):
        return {"error": err}, None
    patch = {k: v for k, v in args.items() if v is not None}
    if "tint" in patch:
        patch["tint"] = _clamp(patch["tint"], _TINTS, "sky")
    for key in ("start", "end"):
        if key in patch:
            patch[key] = _parse_dt(patch[key])
    event = store.update_event(event_id, patch)
    if event is None:
        return {"error": f"No event with id {event_id}."}, None
    return {"updated": _compact_occurrence(event)}, _calendar_action(
        "Event updated", event["title"]
    )


def _delete_event(args: dict):
    occurrence = _parse_dt(args["occurrence_start"]) if args.get("occurrence_start") else None
    if not store.delete_event(args["event_id"], occurrence_start=occurrence):
        return {"error": f"No event with id {args['event_id']}."}, None
    what = "Occurrence removed" if occurrence else "Event deleted"
    return {"deleted": args["event_id"]}, _calendar_action(what, "")


# ---- habits (real from M3) --------------------------------------------------

def _compact_habit(h: dict, today_index: int | None) -> dict:
    done_today = bool(today_index is not None and h["days"][today_index])
    return {"id": h["id"], "name": h["name"], "streak": h["streak"],
            "done_today": done_today, "schedule_days": h["schedule"]}


def _get_habits(args: dict):
    week = store.habits_week()
    habits = [_compact_habit(h, week["today_index"]) for h in week["habits"]]
    return {"habits": habits, "done_today": week["done_today"],
            "total": len(habits), "week_pct": week["week_pct"]}, None


def _resolve_habit(args: dict) -> tuple[dict | None, dict]:
    week = store.habits_week()
    if args.get("habit_id") is not None:
        match = next((h for h in week["habits"] if h["id"] == args["habit_id"]), None)
    else:
        name = (args.get("name") or "").strip().lower()
        match = next(
            (h for h in week["habits"]
             if name and (name in h["name"].lower() or h["name"].lower() in name)),
            None,
        )
    return match, week


def _toggle_habit(args: dict):
    habit, week = _resolve_habit(args)
    if habit is None:
        names = [h["name"] for h in week["habits"]]
        return {"error": f"No matching habit. The habits are: {names}."}, None
    day = _parse_date(args.get("date")) or datetime.now().astimezone().date()
    monday = recurrence.week_start(day)
    idx = (day - monday).days
    # The day's actual state must come from *its* week's grid — judging a
    # past-week date against the current week would blind the dedupe guard
    # and a bare flip could write the opposite of what was asked.
    if week["week_start"] != monday:
        target_week = store.habits_week(monday)
        habit = next(h for h in target_week["habits"] if h["id"] == habit["id"])
    currently_done = habit["days"][idx]
    desired = args.get("done", True)
    if currently_done == desired:
        return {"habit": habit["name"], "already": desired, "streak": habit["streak"]}, None
    updated = store.toggle_habit(habit["id"], day)
    title = "Habit checked off" if desired else "Habit unchecked"
    return (
        {"habit": updated["name"], "done": desired, "streak": updated["streak"]},
        _habit_action(title, f"{updated['name']} · {updated['streak']} day streak"),
    )


def _create_habit(args: dict):
    args = {k: v for k, v in args.items() if v is not None}
    if "tint" in args:
        args["tint"] = _clamp(args["tint"], _TINTS, "green")
    if "link" in args:
        args["link"] = _clamp(args["link"], ["water", "workout"], None)
    if "schedule" in args:
        args["schedule"] = [d for d in args["schedule"] if isinstance(d, int) and 0 <= d <= 6]
    habit = store.create_habit(args)
    return {"created": {"id": habit["id"], "name": habit["name"]}}, _habit_action(
        "New habit", habit["name"]
    )


# ---- nutrition (real from M3) -----------------------------------------------

def _get_nutrition(args: dict):
    day = store.nutrition_day(_parse_date(args.get("date")))
    return {
        "date": day["date"].isoformat(),
        "meals": [{"name": m["name"], "slot": m["slot"], "kcal": m["kcal"],
                   "protein_g": m["protein_g"]} for m in day["meals"]],
        "totals": day["totals"],
        "targets": day["targets"],
        "water_cups": {"drunk": day["water"]["cups"], "goal": day["water"]["goal"]},
    }, None


def _log_meal(args: dict):
    data = {k: v for k, v in args.items() if v is not None}
    if "slot" in data:
        data["slot"] = _clamp(data["slot"], _SLOTS, "Snack")
    if "kcal" in data:
        data["kcal"] = max(0, round(data["kcal"]))
    if "date" in data:
        data["date"] = _parse_date(data["date"])
    meal = store.create_meal(data)
    return {"logged": {"id": meal["id"], "name": meal["name"], "slot": meal["slot"],
                       "kcal": meal["kcal"]}}, _nutrition_action(
        f"{meal['slot']} logged", f"{meal['name']} · {meal['kcal']} kcal"
    )


def _log_water(args: dict):
    water = store.set_water(
        day=_parse_date(args.get("date")),
        cups=args.get("cups"),
        delta=args.get("delta"),
    )
    return {"water": {"cups": water["cups"], "goal": water["goal"]}}, _nutrition_action(
        "Water logged", f"{water['cups']} of {water['goal']} cups"
    )


def _search_food(args: dict):
    hits = food_db.search(args["query"], limit=args.get("limit", 5))
    if hits is None:
        return {"error": "Food database unreachable — estimate the macros yourself "
                         "and tell the user it's an estimate."}, None
    return {"foods": hits, "note": "Macros are per 100 g unless the serving says "
                                   "otherwise — scale to the portion before logging."}, None


# ---- fitness (real from M4) -------------------------------------------------

def _get_fitness_today(args: dict):
    return store.fitness_today(_parse_date(args.get("date"))), None


def _get_workouts(args: dict):
    rows = store.list_workouts(args.get("limit", 10))
    return {"workouts": [{"id": w["id"], "name": w["name"], "source": w["source"],
                          "sport": w["sport"], "duration_min": w["duration_min"],
                          "strain": w["strain"], "calories": w["calories"],
                          "when": w["when"]} for w in rows]}, None


def _get_fitness_week(args: dict):
    return store.fitness_week(_parse_date(args.get("date"))), None


def _get_fitness_status(args: dict):
    accounts = store.list_provider_accounts()
    return {"connected": any(a["status"] == "connected" for a in accounts),
            "providers": accounts}, None


def _log_workout(args: dict):
    data = {
        "name": args["name"],
        "sport": args.get("sport"),
        "started_at": _parse_dt(args["started_at"]) if args.get("started_at")
        else datetime.now().astimezone(),
        "duration_min": max(0, int(args.get("duration_min") or 0)),
        "strain": args.get("strain"),
        "calories": args.get("calories"),
        "avg_hr": args.get("avg_hr"),
        "max_hr": args.get("max_hr"),
    }
    workout = store.create_workout({k: v for k, v in data.items() if v is not None})
    return {"logged": {"id": workout["id"], "name": workout["name"],
                       "source": workout["source"]}}, _fitness_action(
        "Workout logged", f"{workout['name']} · {workout['duration_min']} min"
    )


def _sync_fitness(args: dict):
    count = fitness_sync.tick()
    return {"synced": count}, _fitness_action(
        "Fitness synced", f"{count} record{'s' if count != 1 else ''} updated"
    )


# ---- email (real from M5, read-only) ----------------------------------------

_EMAIL_BODY_UNAVAILABLE = "Message body is unavailable right now."


def _compact_email(e: dict) -> dict:
    """List item for the model — sender/subject/summary, never a body."""
    return {"id": e["id"], "from_name": e["from_name"], "from_email": e["from_email"],
            "subject": e["subject"], "snippet": e["snippet"], "unread": e["unread"],
            "category": e["category"], "summary": e["summary"], "when": e["when"]}


def _get_inbox(args: dict):
    inbox = store.inbox()
    return {"needs_reply": [_compact_email(e) for e in inbox["needs_reply"]],
            "fyi": [_compact_email(e) for e in inbox["fyi"]],
            "needs_reply_count": inbox["needs_reply_count"]}, None


def _get_email(args: dict):
    row = store.get_email(args["email_id"])
    if row is None:
        return {"error": f"No email with id {args['email_id']}."}, None
    body = _EMAIL_BODY_UNAVAILABLE
    impl = providers.get(row["source"])
    get_message = getattr(impl, "get_message", None)
    if get_message is not None:
        try:
            body = get_message(row["source_id"])
        except Exception:  # noqa: BLE001 — body fetch is best-effort
            body = _EMAIL_BODY_UNAVAILABLE
    return {"id": row["id"], "from_name": row["from_name"], "from_email": row["from_email"],
            "subject": row["subject"], "category": row["category"],
            "summary": row["summary"], "when": row["when"], "body": body}, None


# Max characters of the original message's live body handed to the drafting
# model as context — same bound as routers/email.py's _draft_original
# (contract §G: body_excerpt is fetched live via provider.get_message +
# truncation, never the DB-cached snippet). Kept as a separate module-level
# constant here since tools.py and routers/email.py don't share imports for
# this value.
_DRAFT_EXCERPT_CHARS = 2048


def _draft_email(args: dict):
    """User-initiated AI draft (slice-2's only write-adjacent email tool).
    Never sends/trashes/labels — the result is a draft the user reviews in
    compose. email_id is optional; when given, its row becomes reply_to
    context for both the model prompt and the returned action payload."""
    reply_to = None
    original = None
    if args.get("email_id") is not None:
        row = store.get_email(args["email_id"])
        if row is None:
            return {"error": f"No email with id {args['email_id']}."}, None
        reply_to = _compact_email(row)
        excerpt = ""
        impl = providers.get(row["source"])
        get_message = getattr(impl, "get_message", None)
        if get_message is not None:
            try:
                excerpt = get_message(row["source_id"])[:_DRAFT_EXCERPT_CHARS]
            except Exception:  # noqa: BLE001 — excerpt fetch is best-effort
                excerpt = ""
        original = {"from_name": row["from_name"], "from_email": row["from_email"],
                    "subject": row["subject"], "body_excerpt": excerpt}
    text = email_draft.draft(args["instructions"], "", "reply" if original else "new", original)
    if text is None:
        return {"error": "Couldn't draft right now — try again."}, None
    return {"draft": text, "reply_to": reply_to}, _email_action(
        "Draft ready", "Open compose to review & send"
    )


# ---- school / Moodle (real from M6, read-only) ------------------------------

def _get_courses(args: dict):
    """List the student's synced Moodle courses (read-only, from the DB —
    never a live Moodle call)."""
    return store.moodle_courses(), _moodle_action(
        "Courses", "Your Moodle courses"
    )


def _get_deadlines(args: dict):
    """Upcoming Moodle assignment/quiz due dates, optionally within N days
    (args['days']). Reads store.moodle_deadlines only — no provider call."""
    return store.moodle_deadlines(args.get("days")), _moodle_action(
        "Deadlines", "Upcoming Moodle due dates"
    )


def _get_grades(args: dict):
    """Current Moodle grades, optionally scoped to one course_id
    (args['course_id']). Reads store.moodle_grades only — no provider call."""
    return store.moodle_grades(args.get("course_id")), _moodle_action(
        "Grades", "Your Moodle grades"
    )


# ---- task reminders (real from M3) -------------------------------------------

def _add_reminder(args: dict):
    task = store.get_task(args["task_id"])
    if task is None:
        return {"error": f"No task with id {args['task_id']}."}, None
    row = store.add_task_reminder(
        args["task_id"], _parse_dt(args["remind_at"]), args.get("label", "")
    )
    return {"reminder": {"id": row["id"], "remind_at": row["remind_at"].isoformat(),
                         "display": row["display"]}}, _task_action(
        "Reminder set", f"{task['label']} · {row['display']}"
    )


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
         "labels": {"type": "array", "items": _STRING},
         "recurrence": {"type": "string", "description": "RFC 5545 RRULE for repeating tasks (e.g. FREQ=WEEKLY); completing one spawns the next occurrence."}},
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
    {"name": "add_task_reminder",
     "description": "Set a reminder that fires a real notification at a given time, attached to a task (look up the task id with list_tasks first; create the task first if there isn't one).",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "integer"},
         "remind_at": {"type": "string", "description": "ISO datetime, e.g. 2026-06-12T14:00 (user's local time if no offset)."},
         "label": {"type": "string", "description": "Optional human phrasing, e.g. '1 hour before'."}},
         "required": ["task_id", "remind_at"], "additionalProperties": False},
     "run": _add_reminder},
    {"name": "get_calendar",
     "description": "Read the calendar. Call when the user asks about their day, schedule or events. Defaults to today; pass days>1 for a longer window ('this week' → days=7).",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD start day, default today."},
         "days": {"type": "integer", "description": "How many days to read (1-31), default 1."}},
         "additionalProperties": False},
     "run": _get_calendar},
    {"name": "create_event",
     "description": "Create a real calendar event. Call whenever the user asks to schedule something ('dentist Friday 2pm').",
     "input_schema": {"type": "object", "properties": {
         "title": _STRING,
         "start": {"type": "string", "description": "ISO datetime, e.g. 2026-06-12T14:00 (user's local time if no offset)."},
         "end": {"type": "string", "description": "ISO datetime; defaults to start + 1 hour."},
         "tint": {"type": "string", "enum": _TINTS, "description": "Category color; defaults to sky."},
         "location": _STRING,
         "description": _STRING,
         "recurrence": {"type": "string", "description": "RFC 5545 RRULE for repeating events, e.g. FREQ=WEEKLY;BYDAY=MO,WE,FR."}},
         "required": ["title", "start"], "additionalProperties": False},
     "run": _create_event},
    {"name": "update_event",
     "description": "Reschedule or edit an event (find its id with get_calendar). Edits apply to the whole series for recurring events.",
     "input_schema": {"type": "object", "properties": {
         "event_id": {"type": "integer"},
         "title": _STRING,
         "start": {"type": "string", "description": "ISO datetime."},
         "end": {"type": "string", "description": "ISO datetime."},
         "tint": {"type": "string", "enum": _TINTS},
         "location": _STRING,
         "description": _STRING,
         "recurrence": {"type": "string", "description": "RFC 5545 RRULE."}},
         "required": ["event_id"], "additionalProperties": False},
     "run": _update_event},
    {"name": "delete_event",
     "description": "Delete an event, or one occurrence of a recurring one (pass occurrence_start). Only when the user explicitly asks to cancel/remove it.",
     "input_schema": {"type": "object", "properties": {
         "event_id": {"type": "integer"},
         "occurrence_start": {"type": "string", "description": "ISO datetime of the single occurrence to remove; omit to delete the whole event/series."}},
         "required": ["event_id"], "additionalProperties": False},
     "run": _delete_event},
    {"name": "get_habits_today",
     "description": "Read today's habit progress and streaks.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_habits},
    {"name": "toggle_habit",
     "description": "Check a habit off (or uncheck it) for a day. Call when the user says they did a habit ('I meditated this morning').",
     "input_schema": {"type": "object", "properties": {
         "habit_id": {"type": "integer", "description": "From get_habits_today; or pass name instead."},
         "name": {"type": "string", "description": "Habit name (fuzzy-matched) if you don't have the id."},
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."},
         "done": {"type": "boolean", "description": "true = mark done (default), false = un-mark."}},
         "additionalProperties": False},
     "run": _toggle_habit},
    {"name": "create_habit",
     "description": "Create a new habit to track. Call when the user wants to start a new routine.",
     "input_schema": {"type": "object", "properties": {
         "name": _STRING,
         "icon": {"type": "string", "description": "Icon name, e.g. flower-2, book-open, dumbbell, moon, droplet."},
         "tint": {"type": "string", "enum": _TINTS},
         "schedule": {"type": "array", "items": {"type": "integer"},
                      "description": "Weekdays expected (Mon=0..Sun=6); default every day."},
         "link": {"type": "string", "enum": ["water", "workout"],
                  "description": "Auto-complete source: 'water' (hits the daily water goal) or 'workout' (logged workout, from M4)."}},
         "required": ["name"], "additionalProperties": False},
     "run": _create_habit},
    {"name": "get_nutrition_today",
     "description": "Read a day's nutrition: meals, macro totals vs targets, water. Call for any food/diet question.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."}},
         "additionalProperties": False},
     "run": _get_nutrition},
    {"name": "search_food",
     "description": "Look up a food in the nutrition database (USDA) to get macros before logging a meal. Use for natural-language foods ('a chicken wrap'); skip it when the user gives macros themselves.",
     "input_schema": {"type": "object", "properties": {
         "query": _STRING, "limit": {"type": "integer"}},
         "required": ["query"], "additionalProperties": False},
     "run": _search_food},
    {"name": "log_meal",
     "description": "Log a real meal with macros (from search_food, the user, or your own labeled estimate). Call when the user says they ate something.",
     "input_schema": {"type": "object", "properties": {
         "name": _STRING,
         "slot": {"type": "string", "enum": _SLOTS, "description": "Defaults to Snack."},
         "kcal": {"type": "integer"},
         "protein_g": {"type": "number"},
         "carbs_g": {"type": "number"},
         "fat_g": {"type": "number"},
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."}},
         "required": ["name", "kcal"], "additionalProperties": False},
     "run": _log_meal},
    {"name": "log_water",
     "description": "Log drinking water. Call when the user says they drank water ('had two glasses' → delta=2). Hitting the goal auto-completes a linked habit.",
     "input_schema": {"type": "object", "properties": {
         "delta": {"type": "integer", "description": "Cups to add (default 1); negative to correct."},
         "cups": {"type": "integer", "description": "Set the day's absolute count instead."},
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."}},
         "additionalProperties": False},
     "run": _log_water},
    {"name": "get_finance_summary",
     "description": "Read the finance snapshot (balance, budgets, recent transactions). Call for any money/spending question.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _seed_reader(FINANCE_SUMMARY)},
    {"name": "get_fitness_today",
     "description": "Read today's WHOOP recovery, sleep and strain plus vitals (HRV, resting HR). Call for any 'how am I doing / how recovered am I' question, and ALWAYS read this first before scheduling training — then use create_event to block a session or create_task to set an intention based on how recovered they are.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD, default today."}},
         "additionalProperties": False},
     "run": _get_fitness_today},
    {"name": "get_workouts",
     "description": "List recent workouts (synced from WHOOP + manually logged), newest first. Call when the user asks about their training or recent sessions.",
     "input_schema": {"type": "object", "properties": {
         "limit": {"type": "integer", "description": "How many to return (default 10)."}},
         "additionalProperties": False},
     "run": _get_workouts},
    {"name": "get_fitness_week",
     "description": "Read the weekly strain trend (7-day, Mon-first). Call when the user asks how their training load looked this week.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD inside the week, default this week."}},
         "additionalProperties": False},
     "run": _get_fitness_week},
    {"name": "get_fitness_status",
     "description": "Check whether a wearable (WHOOP) is connected and when it last synced. Call before suggesting a sync or when the user asks if their device is linked.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_fitness_status},
    {"name": "log_workout",
     "description": "Log a manual workout (one WHOOP didn't capture). Call when the user says they did a session ('I lifted for 30 minutes'). A logged workout auto-completes a habit linked to workouts.",
     "input_schema": {"type": "object", "properties": {
         "name": _STRING,
         "sport": {"type": "string", "description": "e.g. running, cycling, strength."},
         "started_at": {"type": "string", "description": "ISO datetime; defaults to now (user's local time if no offset)."},
         "duration_min": {"type": "integer"},
         "strain": {"type": "number"},
         "calories": {"type": "integer"},
         "avg_hr": {"type": "integer"},
         "max_hr": {"type": "integer"}},
         "required": ["name"], "additionalProperties": False},
     "run": _log_workout},
    {"name": "sync_fitness",
     "description": "Pull the latest WHOOP data now (recovery, sleep, workouts). Call when the user says their numbers look stale or right after they ask you to act on today's recovery and the data might be old. Returns how many records changed.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _sync_fitness},
    {"name": "get_inbox",
     "description": "Read the triaged inbox — what needs a reply and FYI items, with AI summaries. Call when the user asks about their email/inbox or what needs a response.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_inbox},
    {"name": "get_email",
     "description": "Read one email: sender, subject, AI summary and the full body (fetched live). Call after get_inbox to open a specific message by id.",
     "input_schema": {"type": "object", "properties": {
         "email_id": {"type": "integer"}},
         "required": ["email_id"], "additionalProperties": False},
     "run": _get_email},
    {"name": "draft_email",
     "description": "Draft an email with AI from the user's instructions — optionally replying to an existing message by id (from get_inbox). Returns the draft text; the user reviews and sends it from the compose pane. Never sends.",
     "input_schema": {"type": "object", "properties": {
         "instructions": {"type": "string"},
         "email_id": {"type": "integer"}},
         "required": ["instructions"], "additionalProperties": False},
     "run": _draft_email},
    {"name": "get_courses",
     "description": "List the student's Moodle courses.",
     "input_schema": {"type": "object", "properties": {},
         "additionalProperties": False},
     "run": _get_courses},
    {"name": "get_deadlines",
     "description": "Upcoming Moodle assignment/quiz due dates (optionally within N days).",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer"}},
         "additionalProperties": False},
     "run": _get_deadlines},
    {"name": "get_grades",
     "description": "Current Moodle grades, optionally for one course_id.",
     "input_schema": {"type": "object", "properties": {
         "course_id": {"type": "string"}},
         "additionalProperties": False},
     "run": _get_grades},
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
