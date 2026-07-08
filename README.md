# Scuffed OS

A warm, calm AI personal-assistant dashboard — a "second brain" that organizes and
optimizes your life. This repo is the **desktop app**: a Vite + React frontend
implementing the [Scuffed OS design system](./design-system/), backed by a small
FastAPI service.

The interface is journal-like and cozy: warm paper surfaces, one deep-forest-green
accent, floaty borderless cards, soft shadows, and neutral grotesk type.

## What's here

```
ScuffedOS/
├── frontend/          # Vite + React desktop dashboard
├── backend/           # FastAPI service (assistant chat, tasks, memory)
└── design-system/     # The source design system (tokens, components, UI kits, guidelines)
```

### Desktop surfaces (all built out)
Home · Calendar (live, recurring events) · Tasks (live; drawer: subtasks, firing
reminders, list, priority, deadline, recurrence, real file attachments) · Habits
(live, streaks + auto-complete) · Nutrition (live, USDA food lookup) · Fitness
(Whoop-style, sample) · Finance (sample) · People (personal CRM, sample) · Email
(sample) · Second Brain (live, semantic memory) — plus a launchable **Assistant**
chat panel (live Claude) that reads and writes all of it.

### Desktop app (M8)
ScuffedOS also ships as a **double-clickable, unsigned macOS app** (Apple-Silicon
only) built with Tauri: it bundles its own Python runtime, PostgreSQL 17 +
pgvector, and the backend, so the full dashboard runs **offline with no
terminal**. API keys and OAuth credentials are entered in-app under **Settings**
and stored in a machine-bound encrypted vault. Build it with `bash
scripts/build-app.sh`; see [`docs/ship.md`](docs/ship.md) for the build, the
one-time right-click▸Open (quarantine) step, and the acceptance smoke.

## Prerequisites
- **Node** 18+ (built with Node 25)
- **Python** 3.10+ (built with 3.14)

## Run it (two terminals)

**1. Backend** — FastAPI on `http://localhost:8000`
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # or reuse the repo's ../.venv
pip install -r requirements.txt
cp .env.example .env                                 # set DATABASE_URL + ANTHROPIC_API_KEY (+ OPENAI_API_KEY for memory)
alembic upgrade head                                 # create/upgrade the schema
python -m app.seed                                   # optional: design-prototype demo rows (idempotent)
uvicorn app.main:app --port 8000                     # add --reload for dev (needs uvicorn[standard])
```

**2. Frontend** — Vite dev server on `http://localhost:5173`
```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api/*` to the backend on
`:8000` (see `frontend/vite.config.js`), so no CORS setup is needed in development.

> The frontend degrades gracefully: if the backend isn't running, the assistant drops
> to a labeled capture-only mode and the screens fall back to sample/empty states — the
> UI still works, it just doesn't persist.

To build the frontend for production: `cd frontend && npm run build` (output in `dist/`).

## Tests

Backend tests live in `backend/tests/` (pytest over FastAPI's TestClient):

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs the backend suite and a frontend
production build on every push. Backend configuration is env-based — copy
`backend/.env.example` to `backend/.env` for local overrides.

## How the two halves connect

| Frontend | Backend |
| --- | --- |
| Assistant chat (`ChatPanel`, SSE streaming) | `POST /api/assistant/chat[/stream]` — Claude tool loop, persistent conversations |
| Home + Tasks (drawer: subtasks, reminders, files, recurrence) | `/api/tasks` (+ `/reminders`, `/files` subroutes) |
| Second Brain memories (Mem0 semantic recall) | `/api/memory` |
| Calendar (week grid, recurring events, Up next) | `/api/calendar` |
| Habits (streaks, weekly grid, auto-complete) | `/api/habits` |
| Nutrition (rings, meals, water, weekly trend) | `/api/nutrition` (+ USDA food search) |

Interactive API docs are available at `http://localhost:8000/docs` while the backend runs.

## Notes & caveats
- **The assistant is live Claude** (`backend/app/llm.py`) with a server-side tool loop
  over every built domain; reminders fire real macOS notifications via `osascript`.
  Fitness and Finance panels remain labeled sample data until their integrations land
  (Whoop in M4, Plaid in M6); Email and People follow in M5.
- **Data persists in Postgres** (Supabase free tier in production, any Postgres or
  SQLite-for-tests locally) behind `backend/app/store.py`; Mem0 vectors live in the
  same database (pgvector). Attachment bytes and Mem0's history file stay local in
  `backend/data/`.
- **Fonts** load from the Google Fonts CDN (see `index.html`); not self-hosted.
- The **iPhone app** in the design system is not yet ported — its source lives in
  `design-system/project/ui_kits/scuffed-os-ios/` for a future pass.

## Design system
`design-system/` is the exported handoff bundle this app was built from — tokens,
component specs, UI-kit prototypes, brand assets, and the full design chat. See
`design-system/README.md` and `design-system/project/readme.md`. The implementation
recreates those prototypes for real; the brand tokens were copied verbatim into
`frontend/src/styles/tokens/` and the assets into `frontend/public/assets/`.
