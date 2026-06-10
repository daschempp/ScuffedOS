"""Scuffed OS assistant — the real engine (replaces the M0 intent mock).

A server-side agentic tool loop over Claude (review D2): the model reads and
writes every built domain through app/tools.py, action cards report what
actually executed, and the whole exchange persists to the conversations
tables so history survives restarts. Streaming variant yields SSE events.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from . import llm, memory_engine, tools
from .store import store

log = logging.getLogger("scuffed_os.assistant")

MAX_TOOL_ROUNDS = 8
HISTORY_LIMIT = 30

_PERSONA = """You are the Scuffed OS assistant — a warm, calm personal aide living inside the user's life dashboard. You can read and write their tasks (with reminders that fire and repeating rules), second-brain memories, calendar events, habits and nutrition log; the finance and fitness panels are read-only for now.

Rules:
- Plain text only: no HTML tags, no markdown headers or asterisks. Short sentences, short paragraphs. A simple "- " list is fine.
- Act, don't narrate: when the user asks for something a tool can do, call the tool. Don't ask permission for ordinary writes; do ask before deleting anything.
- Logging food: prefer search_food for macros; if it's unavailable or a poor match, estimate yourself and say it's an estimate. Scale per-100g macros to the actual portion.
- The finance and fitness panels are sample data until their integrations land (the tool results say so). If you used sample data, mention it casually ("once your bank is connected…").
- Be brief. One or two sentences is usually right. No "Certainly!" openers.
- Use the remember tool when the user says "remember X" or shares something durably useful. You don't need to announce routine memory captures."""


def _system_prompt(message: str) -> str:
    now = datetime.now().astimezone()
    parts = [_PERSONA, f"Right now it is {now.strftime('%A, %B %-d %Y, %-I:%M%p').lower()}."]
    recalled = memory_engine.search(message, limit=4)
    if recalled:
        lines = "\n".join(f"- {r['text']}" for r in recalled if r.get("text"))
        if lines:
            parts.append("Possibly relevant things you remember about the user:\n" + lines)
    return "\n\n".join(parts)


def _history_messages(conversation_id: int) -> list[dict]:
    rows = store.list_messages(conversation_id)[-HISTORY_LIMIT:]
    return [{"role": r["role"], "content": r["content"]} for r in rows if r["content"]]


def _resolve_conversation(conversation_id: int | None) -> int:
    if conversation_id is not None and store.get_conversation(conversation_id):
        return conversation_id
    return store.create_conversation()["id"]


def run_turn(message: str, conversation_id: int | None = None):
    """Generator driving one chat turn. Yields ("meta"|"delta"|"tool"|"action"|
    "done", payload) events; the SSE endpoint forwards them and the JSON
    endpoint just drains for the final state."""
    if not llm.available():
        raise AssistantUnavailable()

    conv_id = _resolve_conversation(conversation_id)
    yield "meta", {"conversation_id": conv_id}

    system = _system_prompt(message)
    history = _history_messages(conv_id)
    store.add_message(conv_id, "user", message)
    messages = history + [{"role": "user", "content": message}]
    model = llm.pick_model(message)

    full_text: list[str] = []
    actions: list[dict] = []

    for _round in range(MAX_TOOL_ROUNDS):
        with llm.stream(model=model, system=system, messages=messages,
                        tools=tools.DEFINITIONS) as stream:
            for text in stream.text_stream:
                full_text.append(text)
                yield "delta", {"text": text}
            final = stream.get_final_message()

        if final.stop_reason != "tool_use":
            break

        tool_results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield "tool", {"name": block.name}
            result_json, action = tools.execute(block.name, block.input)
            if action is not None:
                actions.append(action)
                yield "action", action
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_json,
            })
        messages.append({"role": "assistant", "content": final.content})
        messages.append({"role": "user", "content": tool_results})
    else:
        log.warning("Tool loop hit MAX_TOOL_ROUNDS — answering with what we have")

    text = "".join(full_text).strip() or "Done."
    store.add_message(conv_id, "assistant", text, actions=actions or None)
    yield "done", {"conversation_id": conv_id, "text": text, "actions": actions}


def reply(message: str, conversation_id: int | None = None) -> dict:
    """Non-streaming entry point: drain the turn, return the final payload."""
    payload = None
    for event, data in run_turn(message, conversation_id):
        if event == "done":
            payload = data
    return payload


def capture(message: str, conversation_id: int, text: str) -> None:
    """Post-response Mem0 auto-capture; runs as a background task."""
    del conversation_id
    memory_engine.capture_turn(message, text)


class AssistantUnavailable(Exception):
    """No API key / LLM seam configured — the endpoint returns 503."""
