# Memory (Second Brain) — Architecture

> Status: draft · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Stores and lists the
> second-brain memories surfaced on the Memory screen.

## Responsibility

Own the second-brain note list: short pieces of context the user (or the assistant)
captures — `{ id, text, src, tags, color, when }` — to be surfaced later. Today the
backend handles **capture + list**; retrieval/surfacing is not yet a backend concern.

## Surface (current)

`app/routers/memory.py`, prefix `/api/memory`:

| Method | Path | Body | Returns | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/memory` | — | `list[Memory]` | Newest first. |
| `POST` | `/api/memory` | `MemoryCreate` | `Memory` | `201 Created`. |

Models (`schemas.py`):

- `Memory { id, text, src, tags: list[str], color, when }`
- `MemoryCreate { text, src="note", tags=[], color="green" }`

`when` is **not** client-supplied — the store sets it to `"just now"` on create (seed
data uses relative strings like "2 days ago"). It's a display string today, not a
timestamp. There is **no update or delete** endpoint.

## Internal design (current)

Thin router over `store.py` (see [data-store.md](data-store.md)):

- `store.list_memories()` — shallow copy of the list.
- `store.create_memory(text, src, tags, color)` — assigns `_next_memory_id`, sets
  `when="just now"`, **inserts at the front**, returns the new memory.

Seeded with 4 memories mirroring `MemoryScreen.SAMPLE_MEMORIES` (family/gifts, health/
routine, work, finance/nutrition). Mutations are lock-guarded.

## Dependencies & interactions

- **Depends on:** `schemas.py` (`Memory`, `MemoryCreate`) and `store.py`.
- **Shares the store with Tasks** — same concurrency model and swap seam, separate
  list and id counter.
- **Assistant link (today, weak):** the assistant's "remember/note" intent returns an
  action pointing at the `memory` screen, but — unlike tasks — there is **no `makeNote`
  equivalent**, so chat-captured memories aren't auto-filed via the API yet. _Worth
  deciding whether to mirror the `makeTask` pattern._

## Target architecture — Mem0 (decided)

> The retrieval + capture model is settled: **[Mem0](https://github.com/mem0ai/mem0)
> self-hosted (OSS)** is the memory engine, landing in **M2** (see the production build
> spec). It replaces a hand-rolled embedding/retrieval layer. Self-hosted via
> `Memory.from_config` — no Mem0 Platform/cloud; extraction + embedding compute runs
> locally, vectors live in Supabase pgvector (decided 2026-06-10).

Configuration:

- **LLM:** Anthropic Claude (same `ANTHROPIC_API_KEY` as the assistant) — drives Mem0's
  fact extraction and reconciliation.
- **Embedder:** local — HuggingFace/sentence-transformers, or Ollama (the latter
  sidesteps the Python 3.14 torch-wheel risk; an API embedder is the other escape hatch).
  Note: Voyage is **not** a native Mem0 embedder.
- **Vector store:** Supabase **pgvector** (decided 2026-06-10, supersedes FAISS) — the
  same Supabase Postgres that holds the app DB. `provider: "pgvector"` with the
  session-pooler `connection_string`, `collection_name: "mem0_memories"` (distinct from
  the app's own memories table), `embedding_model_dims` pinned to the embedder,
  `hnsw: true`; `CREATE EXTENSION IF NOT EXISTS vector` via Alembic migration. One DB →
  one backup (`pg_dump` covers memories) and a future off-LAN client reads the same
  memory.
- Mem0 also keeps its own change-history DB: a **local SQLite file** — the one Mem0
  artifact that does not move to Supabase.

Capture & retrieval:

- [ ] **Auto-capture (primary).** Every assistant turn is passed to Mem0 `add()`
      (`infer=True`); Mem0 LLM-extracts salient facts and reconciles them against existing
      memories as **ADD / UPDATE / DELETE / NOOP** — dedup and conflict-resolution come
      for free. **No suggest-then-confirm gate.**
- [ ] **Explicit capture.** "remember X" files immediately and verbatim via
      `add(..., infer=False)` — the `makeNote`-equivalent path, still synchronous.
- [ ] **Retrieval / surfacing** via Mem0 `search` (semantic) with **metadata filters**
      (covers tag/time filtering); results feed the assistant's tool loop.
- [ ] **Update / delete** via Mem0's APIs (edit text, retag, forget), exposed through the
      `/api/memory` router.
- [ ] **Durable persistence** with real timestamps instead of the `"just now"` display
      string (derive relative time on read).
- [ ] **Tag & color** — `tags` map to Mem0 metadata; `color` stays a presentation concern.

## Design decisions & rationale

- _Why server-assigned `when`?_ — Prototype showed relative strings; the client never set
  them. Acceptable as a stopgap; real timestamps are the target. TODO.
- _Why no delete yet?_ — Capture-first prototype. TODO.
- _Why Mem0 over a hand-rolled embedding layer?_ — The hard part of "good" memory is
  extraction + dedup + conflict-resolution; Mem0 ships it (ADD/UPDATE/DELETE
  reconciliation), with Claude extraction + a local embedder and vectors in Supabase
  pgvector. Trade-offs accepted: ambient capture becomes automatic (no confirm gate),
  memory search rides the network (negligible next to the LLM call it accompanies), and
  Mem0 keeps a local SQLite history DB beside the hosted app DB.
- _Why auto-capture over suggest-then-confirm?_ — Leaning on Mem0's native flow: fewer
  prompts, and reconciliation keeps noise/duplicates down. Explicit "remember X" stays the
  verbatim, immediate path (`infer=False`).

## Open questions / future work

- ~~Retrieval model~~ — **resolved: Mem0 semantic `search`, Supabase pgvector-backed.**
- ~~Auto-capture & avoiding noise/duplicates~~ — **resolved: Mem0 auto-captures; its
  ADD/UPDATE/DELETE reconciliation handles dedup.**
- Tuning: Mem0 `custom_instructions` to scope what counts as a memory (exclude filler),
  and how aggressively to extract per turn.
- Whether to surface a lightweight forget/edit UI on the Memory screen over Mem0's APIs.
