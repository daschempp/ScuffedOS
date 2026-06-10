"""End-to-end smoke test for the live memory pipeline (M2).

Drives the REAL external stack and deletes everything it creates on the way
out. Three legs, matching production:

  1. Live chat — a real Claude tool-loop turn (app/assistant.py).
  2. Auto-capture — memory_engine.capture_turn(), the exact post-chat hook the
     router fires: Claude fact-extraction (infer=True) → OpenAI embedder →
     pgvector write → mirror into the visible `memories` table as src="learned".
  3. Recall — memory_engine.search(): OpenAI embed → pgvector similarity search.

The chat leg uses a neutral prompt (no durable fact) so it doesn't write
memory; the capture leg drives an incidental fact through capture_turn
directly, isolating the inference path from the verbatim `remember` tool.

Unlike the pytest suite (which fakes every external call via conftest), this
makes real, billable Claude + OpenAI requests and writes to the configured
database. Run it by hand once the keys are funded:

    python -m app.smoke_memory

Exit status is 0 only if every leg passed.
"""
from __future__ import annotations

import logging
import sys

from . import assistant, llm, memory_engine
from .config import settings
from .models import Conversation
from .store import store

# Neutral chat prompt — proves the live Claude loop without writing memory.
CHAT_PROMPT = "In one short sentence, suggest a good habit for staying organized."

# An incidental personal fact (capture leg) + a differently-worded recall query
# — a hit proves real embedding-based recall, not substring luck. "Pyranha" is
# deliberately distinctive so the recall assertion is unambiguous.
CAPTURE_USER = ("Oh, by the way — I adopted a cat this weekend. Her name is "
                "Pyranha and she's a grey tabby.")
CAPTURE_REPLY = "Congrats on adopting Pyranha! A grey tabby sounds lovely."
RECALL_QUERY = "do I have any pets at home?"
MARKERS = ("pyranha", "cat", "tabby")


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _delete_conversation(conv_id: int) -> None:
    # conversation_messages rows cascade via the FK's ondelete="CASCADE".
    with store._session() as s, s.begin():
        conv = s.get(Conversation, conv_id)
        if conv is not None:
            s.delete(conv)


def _new_rows(baseline_ids: set[int]) -> list[dict]:
    return [m for m in store.list_memories() if m["id"] not in baseline_ids]


def _mem0_ids() -> set[str]:
    """IDs currently in the Mem0 vector store for this owner (empty on error)."""
    mem = memory_engine._get()
    if mem is None:
        return set()
    try:
        got = mem.get_all(filters={"user_id": settings.owner})
        items = got.get("results", []) if isinstance(got, dict) else (got or [])
        return {it["id"] for it in items if it.get("id")}
    except Exception:
        return set()


def main() -> int:
    # Surface the engine's best-effort failures (logged via log.exception);
    # mute Mem0's benign "spaCy not installed" notices (it has a fallback).
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    logging.getLogger("mem0.utils.spacy_models").setLevel(logging.ERROR)
    r = Reporter()
    print("Scuffed OS — live memory pipeline smoke test")
    print(f"  owner={settings.owner!r}  embedder={settings.embedder_model} "
          f"({settings.embedder_dims}d)  collection={settings.mem0_collection}")

    print("\nPreconditions:")
    if not r.check(llm.available(), "Claude LLM configured (ANTHROPIC_API_KEY)"):
        print("\nAborting: the assistant LLM is not configured.")
        return 1
    if not r.check(memory_engine._get() is not None,
                   "Mem0 engine online (OpenAI key + DB reachable)"):
        print("\nAborting: Mem0 engine is offline — check OPENAI_API_KEY / DATABASE_URL.")
        return 1

    baseline_ids = {m["id"] for m in store.list_memories()}
    baseline_vecs = _mem0_ids()
    conv_id: int | None = None
    try:
        print("\n1. Chat turn (real Claude tool loop):")
        payload = assistant.reply(CHAT_PROMPT)
        conv_id = payload.get("conversation_id")
        reply_text = payload.get("text", "")
        r.check(bool(reply_text), "assistant returned a reply", reply_text[:72])

        print("\n2. Auto-capture (Claude extract → OpenAI embed → pgvector write):")
        memory_engine.capture_turn(CAPTURE_USER, CAPTURE_REPLY)
        rows = _new_rows(baseline_ids)
        r.check(bool(rows), "a fact was extracted and mirrored", f"{len(rows)} new row(s)")
        for m in rows:
            print(f"        - #{m['id']} src={m['src']} mem0_id={m['mem0_id']}  \"{m['text']}\"")
        r.check(bool(rows) and all(m["mem0_id"] for m in rows),
                "every new row has a mem0_id (embedded into pgvector)")
        r.check(any(m["src"] == "learned" for m in rows),
                "inference mirrored a row as src=\"learned\" (auto-capture path)")

        print("\n3. Semantic recall (OpenAI embed → pgvector search):")
        print(f"        query: {RECALL_QUERY!r}")
        hits = memory_engine.search(RECALL_QUERY, limit=5)
        r.check(hits is not None, "search reached the engine (not offline)")
        for h in hits or []:
            print(f"        - score={h['score']}  \"{h['text']}\"")
        recalled = any(any(mk in (h.get("text") or "").lower() for mk in MARKERS)
                       for h in (hits or []))
        r.check(recalled, "the captured fact came back from pgvector")
    except Exception as exc:  # a live call blew up — report, still clean up
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])
    finally:
        print("\nCleanup:")
        removed = 0
        for m in _new_rows(baseline_ids):
            store.delete_memory(m["id"])
            memory_engine.sync_delete(m.get("mem0_id"))
            removed += 1
        # Sweep the Mem0 store too: drop any vector added this run that the
        # table-row pass missed (unmirrored), so the next run starts clean.
        orphans = _mem0_ids() - baseline_vecs
        for vid in orphans:
            memory_engine.sync_delete(vid)
        if conv_id is not None:
            _delete_conversation(conv_id)
        leftover_rows = {m["id"] for m in store.list_memories()} - baseline_ids
        leftover_vecs = _mem0_ids() - baseline_vecs
        r.check(not leftover_rows and not leftover_vecs,
                f"removed {removed} row(s) + {len(orphans)} stray vector(s) + test conversation",
                "" if not (leftover_rows or leftover_vecs)
                else f"leftover rows={leftover_rows} vecs={leftover_vecs}")

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES — see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
