"""Mem0 memory engine (self-hosted OSS) — the assistant's semantic memory.

Configuration per the production spec: Claude as the extraction LLM, an OpenAI
embedder (dims pinned), vectors in the same Postgres via pgvector (collection
`mem0_memories_openai`, distinct from the app's own `memories` table), and
Mem0's change-history DB as a local SQLite file.

Mirroring keeps the user-visible Memory screen truthful: every Mem0
ADD/UPDATE/DELETE event from auto-capture is reflected into the app's
`memories` table (src="learned", linked by `mem0_id`), and edits/deletes made
through the API propagate back into Mem0.

The engine is strictly best-effort: if Postgres/either API key is missing,
every function degrades to a no-op (search returns None) and chat keeps
working.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import settings
from .store import store

log = logging.getLogger("scuffed_os.memory")

_engine = None          # Memory instance, or False once init failed
_override = "unset"     # tests install a fake (or None to disable)
_lock = threading.Lock()


def configure(override) -> None:
    """Install a fake Mem0 for tests; configure("unset") restores lazy init."""
    global _engine, _override
    _override = override
    _engine = None


def _connection_string() -> str:
    # Mem0 hands this to psycopg directly — strip any SQLAlchemy driver suffix.
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _get():
    global _engine
    if _override != "unset":
        return _override
    if _engine is False:
        return None
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine if _engine is not False else None
        if not (settings.memory_enabled and settings.anthropic_api_key
                and settings.openai_api_key and settings.database_url):
            _engine = False
            return None
        try:
            from mem0 import Memory

            Path(settings.mem0_history_path).parent.mkdir(parents=True, exist_ok=True)
            _engine = Memory.from_config({
                "llm": {"provider": "anthropic", "config": {
                    "model": settings.memory_llm_model,
                    "api_key": settings.anthropic_api_key,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                }},
                "embedder": {"provider": "openai", "config": {
                    "model": settings.embedder_model,
                    "embedding_dims": settings.embedder_dims,
                    "api_key": settings.openai_api_key,
                }},
                "vector_store": {"provider": "pgvector", "config": {
                    "connection_string": _connection_string(),
                    "collection_name": settings.mem0_collection,
                    "embedding_model_dims": settings.embedder_dims,
                    "hnsw": True,
                }},
                "history_db_path": settings.mem0_history_path,
            })
            return _engine
        except Exception:
            log.exception("Mem0 unavailable — assistant memory disabled for this run")
            _engine = False
            return None


def search(query: str, limit: int = 5) -> list[dict] | None:
    """Semantic recall. None means the engine is offline (callers fall back)."""
    mem = _get()
    if mem is None:
        return None
    try:
        res = mem.search(query, top_k=limit, filters={"user_id": settings.owner})
        return [{"id": r.get("id"), "text": r.get("memory"), "score": round(r.get("score") or 0, 3)}
                for r in res.get("results", [])]
    except Exception:
        log.exception("Mem0 search failed")
        return None


def _mirror_events(results: list[dict]) -> None:
    for item in results:
        event, mem0_id, text = item.get("event"), item.get("id"), item.get("memory")
        if not mem0_id:
            continue
        if event == "ADD" and text:
            store.create_memory({"text": text, "src": "learned"}, mem0_id=mem0_id)
        elif event == "UPDATE" and text:
            store.update_memory_by_mem0_id(mem0_id, text)
        elif event == "DELETE":
            store.delete_memory_by_mem0_id(mem0_id)


def capture_turn(user_text: str, assistant_text: str) -> None:
    """Auto-capture (spec §2): pass the exchange to Mem0 with infer=True —
    LLM fact extraction + ADD/UPDATE/DELETE/NOOP reconciliation — then mirror
    the events into the visible memories table."""
    mem = _get()
    if mem is None:
        return
    try:
        res = mem.add(
            [{"role": "user", "content": user_text},
             {"role": "assistant", "content": assistant_text}],
            user_id=settings.owner, infer=True,
        )
        _mirror_events(res.get("results", []) if isinstance(res, dict) else [])
    except Exception:
        log.exception("Mem0 auto-capture failed")


def _add_verbatim(text: str) -> str | None:
    mem = _get()
    if mem is None:
        return None
    try:
        res = mem.add(text, user_id=settings.owner, infer=False)
        results = res.get("results", []) if isinstance(res, dict) else []
        return results[0].get("id") if results else None
    except Exception:
        log.exception("Mem0 verbatim add failed")
        return None


def remember_verbatim(text: str, tags: list[str] | None = None) -> dict:
    """Explicit 'remember X' — files immediately and verbatim (infer=False).
    The canonical row is created even when the engine is offline."""
    row = store.create_memory({"text": text, "src": "note", "tags": tags or []})
    mem0_id = _add_verbatim(text)
    if mem0_id:
        store.set_memory_mem0_id(row["id"], mem0_id)
        row["mem0_id"] = mem0_id
    return row


def index_row(row: dict) -> None:
    """Make an API/voice-created memory semantically searchable."""
    mem0_id = _add_verbatim(row["text"])
    if mem0_id:
        store.set_memory_mem0_id(row["id"], mem0_id)


def sync_update(mem0_id: str | None, text: str) -> None:
    mem = _get()
    if mem is None or not mem0_id:
        return
    try:
        mem.update(mem0_id, text)
    except Exception:
        log.exception("Mem0 update sync failed")


def sync_delete(mem0_id: str | None) -> None:
    mem = _get()
    if mem is None or not mem0_id:
        return
    try:
        mem.delete(mem0_id)
    except Exception:
        log.exception("Mem0 delete sync failed")
