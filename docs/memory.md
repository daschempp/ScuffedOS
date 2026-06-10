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

## How it _should_ function

> Target design to author:

- [ ] **Durable persistence** via the real store (DB), with real timestamps instead of
      the `"just now"` display string (derive relative time on read).
- [ ] **Retrieval / surfacing** — the README's promise is "I'll surface it when it's
      relevant." Is that search (full-text), semantic retrieval (embeddings/RAG), or
      tag/time filters? This is the defining future feature for this section.
- [ ] **Capture from the assistant** — add a `makeNote` action (parallel to `makeTask`)
      so "remember X" files a real memory, with auto-tagging.
- [ ] **Update / delete** endpoints (edit text, retag, forget).
- [ ] **Tag & color** — free-form today; should `color`/`tags` be constrained or derived?

## Design decisions & rationale

- _Why server-assigned `when`?_ — Prototype showed relative strings; the client never set
  them. Acceptable as a stopgap; real timestamps are the target. TODO.
- _Why no delete yet?_ — Capture-first prototype. TODO.

## Open questions / future work

- Retrieval model is the big one — it shapes the storage schema (do we need vectors?).
- Should the assistant auto-capture memories, and how do we avoid noise/duplicates?
