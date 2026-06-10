# Memory (Second Brain) — Architecture

> Status: built (M1 CRUD + M2 Mem0 engine) · Last updated: 2026-06-10 · Owner: _TBD_
>
> M2 implementation notes: `app/memory_engine.py` realizes the Mem0 design
> below — Claude (haiku) extraction, Ollama `nomic-embed-text` embedder (768
> dims, pinned), pgvector store in the same Postgres (`mem0_memories`
> collection, HNSW; `CREATE EXTENSION vector` via migration 0002), local SQLite
> history DB under `backend/data/`. Auto-capture runs after every chat turn
> (`infer=True`) and its ADD/UPDATE/DELETE events are **mirrored** into the
> canonical `memories` table (`src="learned"`, linked by `mem0_id`), so the
> Memory screen truthfully shows what the assistant learned; API edits/deletes
> propagate back into Mem0. Explicit "remember X" files verbatim
> (`infer=False`). The engine is best-effort: without Ollama/key/DB it degrades
> to recent-notes fallback and chat keeps working.
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
| `PATCH` | `/api/memory/{id}` | `MemoryUpdate` (all optional) | `Memory` | `404` if unknown. |
| `DELETE` | `/api/memory/{id}` | — | `204` | "Forget" — wired to a trash affordance on the Memory screen. |

Models (`schemas.py`):

- `Memory { id, text, src, tags: list[str], color, when, created_at, updated_at }`
- `MemoryCreate { text, src="note", tags=[], color="green" }`
- `MemoryUpdate { text?, src?, tags?, color? }`

`when` is **derived on read** from the stored UTC `created_at` ("just now", "2 days
ago", "1 week ago" — `app/display.py`), never stored or client-supplied.

## Internal design (current)

Thin router over `store.py` — a `memories` table (SQLAlchemy/Postgres, M1) with owner
column and real timestamps; see [data-store.md](data-store.md). Demo rows come from
`store.seed_demo()` with `created_at` offsets so the relative times look like the
prototype.

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
