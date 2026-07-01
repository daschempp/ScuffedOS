---
name: run-scuffedos
description: Run, launch, start, demo, or screenshot the ScuffedOS app — the Vite/React dashboard plus its FastAPI backend. Use to drive the running app, capture screenshots of its surfaces (Home/Calendar/Tasks/Habits/Nutrition/Second Brain), or smoke-test the live Claude assistant.
---

# Run ScuffedOS

ScuffedOS is a two-process desktop dashboard: a **FastAPI backend** (`backend/`, port
8000) and a **Vite + React frontend** (`frontend/`, port 5173, proxies `/api` → :8000).
It's a single-page app — nav is React state, the URL never changes — so you drive it with
the committed Playwright driver at `.claude/skills/run-scuffedos/driver.mjs`, which clicks
between surfaces and screenshots each one. The backend you smoke-test with `curl`.

**All paths below are relative to the repo root** (the `<unit>` for this skill). The
Python interpreter is the repo's `.venv` (Python 3.14); the frontend's `node_modules` is
already vendored.

## Prerequisites

- **Python 3.10+** — use the repo venv at `./.venv` (deps already installed).
- **Node 18+** — `frontend/node_modules` is already present.
- **macOS host** for the real thing: firing reminders post notifications via `osascript`.
  Core app runs fine without; only that one feature is host-specific.
- **No database server needed** for the demo — it runs on a throwaway SQLite file.
- **Chromium** for the driver: auto-discovered from the Playwright browser cache. If none
  is cached, `npx playwright install chromium` once.

## Setup — one-time, for the driver

```bash
# Playwright package for the driver. Skip the browser download — the driver finds a
# cached Chromium itself (and node_modules here is gitignored).
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --prefix .claude/skills/run-scuffedos
```

## Build the demo database (SQLite — portable, no Postgres)

```bash
cd backend
export DATABASE_URL="sqlite:////tmp/scuffed-demo.db"   # absolute path → four slashes
export MEMORY_ENABLED=false                            # Mem0 needs pgvector; off for SQLite
../.venv/bin/python -m alembic upgrade head            # create schema (silent on success)
../.venv/bin/python -m app.seed                        # idempotent demo rows
```

Seeds ~10 tasks, 7 events, 5 habits (+30 completions), 19 meals, 4 memories. The assistant
still works with memory off — it just won't do semantic recall.

## Run (agent path) — the one you want

Launch each server **as its own long-lived background process** (see Gotchas — a wrapper
that exits gets the server reaped). From `backend/` with the two env vars above still set:

```bash
# Backend — run this AS the background command itself, not `nohup … & echo pid`.
DATABASE_URL="sqlite:////tmp/scuffed-demo.db" MEMORY_ENABLED=false \
  ../.venv/bin/python -m uvicorn app.main:app --port 8000
```

```bash
# Frontend — also its own background process.
npm run dev --prefix frontend
```

Wait for both, then confirm and drive:

```bash
curl -s http://localhost:8000/api/tasks | head -c 80      # backend serving data
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/api/habits  # proxy → 200

# Screenshot every live surface (Home/Calendar/Tasks/Habits/Nutrition/Second Brain).
OUT=/tmp/scuffed-shots node .claude/skills/run-scuffedos/driver.mjs
```

The driver prints JSON (`ok: true` per surface, `consoleErrors: []`) and **exits 0** when
all surfaces render. **Look at a screenshot** in `/tmp/scuffed-shots/` — a blank frame is a
failed launch. Override targets with `BASE_URL=`, `OUT=`, `SURFACES="Home,Tasks"`.

Smoke-test the **live Claude assistant** (it calls tools against the DB):

```bash
curl -s -X POST http://localhost:8000/api/assistant/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"How many cups of water have I logged today? One sentence."}' --max-time 60
# → {"conversation_id":1,"text":"You've logged 5 cups of water today, with a goal of 8.", ...}
```

## Run (human path)

Two terminals, per `README.md`: `cd backend && uvicorn app.main:app --port 8000` and
`cd frontend && npm run dev`, then open **http://localhost:5173**. Useless headless — it
just waits for a browser. The agent path above is what to use for verification.

## Test

```bash
cd backend && ../.venv/bin/python -m pytest        # backend suite (SQLite by default)
```

## Full-fidelity alternative (Postgres + memory)

A local Docker Postgres `scuffedos-pg` (port 5433, `scuffed/scuffed`, db `scuffedos`) may
already be migrated + seeded with Mem0 semantic memory enabled. To use it instead of
SQLite, set `DATABASE_URL="postgresql://scuffed:scuffed@localhost:5433/scuffedos"` and drop
`MEMORY_ENABLED=false`. Do **not** point the backend at the Supabase URL in `backend/.env`
for a demo — see Gotchas.

## Gotchas

- **Background-task reaping.** Launching the server via a wrapper that returns
  (`nohup uvicorn … & echo $!`) gets the whole process group killed when the wrapper exits —
  the port goes dead a moment later. Launch uvicorn/vite **as the background command
  itself** so the supervisor keeps it alive.
- **`backend/.env` points at Supabase, which never got the M3 migration.** Calendar,
  Habits, and Nutrition tables don't exist there, so those endpoints 404 and their screens
  fall back to empty/sample. Always override `DATABASE_URL` (SQLite above, or the Docker PG)
  for a working demo. The env var wins over `.env` — pydantic-settings precedence.
- **No URL routing.** Surfaces switch via React state (`onNavigate`), the URL stays `/`.
  `chrome --headless --screenshot <url>` therefore only ever captures Home — you must click
  `.kit-navitem` buttons to change surface, which is exactly what the Playwright driver does.
- **Mem0 requires pgvector (Postgres).** On SQLite you must set `MEMORY_ENABLED=false` or
  startup fails initializing the memory engine. Chat still works; only semantic recall is off.
- **Run the backend from `backend/`.** `config.py` reads `backend/.env` (for
  `ANTHROPIC_API_KEY`) relative to cwd and resolves `./data/...` paths there. Wrong cwd → no
  API key → the assistant 500s.
- **Chromium version skew is handled.** Playwright 1.49 expects one Chromium build; the
  cache may hold another. `driver.mjs` scans the cache for the newest `chromium-*` and sets
  `executablePath`, so the mismatch doesn't matter — and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`
  at install time avoids a needless ~150MB download.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Driver exits 2, "No Chromium found" | `npx playwright install chromium` |
| Assistant returns 500 / empty text | `ANTHROPIC_API_KEY` not loaded — launch backend from `backend/` so `.env` is read |
| Calendar/Habits/Nutrition 404 or empty | Wrong DB (Supabase has no M3 schema) — use the SQLite path |
| `address already in use` on 8000/5173 | `lsof -ti:8000,5173 \| xargs kill` |
| Driver can't reach the app | Backend/frontend not up, or got reaped — see first Gotcha; re-launch as background processes |
