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
├── backend/           # FastAPI service, Postgres domains, integrations, and assistant
└── design-system/     # The source design system (tokens, components, UI kits, guidelines)
```

### Desktop surfaces (API-backed)
Home · Calendar (recurring events) · Tasks (drawer: subtasks, firing reminders,
list, priority, deadline, recurrence, real file attachments) · Habits (streaks +
auto-complete) · Nutrition (USDA food lookup) · Fitness (live WHOOP sync:
recovery/strain/sleep/workouts) · Insights (derived WHOOP-style coaching, once a
day) · Finance (Plaid reads + local budgets; production-pull validation remains
outstanding) · Email (live Gmail sync, AI triage + draft replies) · School (live
Moodle, read-only) · People (personal CRM, with a local Apple Contacts
Full-Disk-Access connector; signed-bundle acceptance remains outstanding) ·
Second Brain (semantic memory) —
plus a launchable **Assistant** chat panel (live Claude) with tools across the
local domains and limited read/write access to integrations — People included
(search/read contacts, add one by hand, edit CRM fields, log when they last
spoke; no delete tool).

### Desktop app (M8)
ScuffedOS also ships as a **double-clickable Apple-Silicon macOS app** built with
Tauri. Development builds are unsigned by default; Developer ID signing and
notarization are optional. The bundle includes its own Python runtime,
PostgreSQL 17 + pgvector, and backend, so local data and the dashboard run with
no terminal; Claude and external-provider sync still require a network. API
keys and provider client credentials entered under **Settings** live in a
machine-bound encrypted vault, while provider access/refresh tokens live in the
local database. Build it with `bash scripts/build-app.sh`; see
[`docs/ship.md`](docs/ship.md) for build and acceptance instructions.

## Prerequisites
- **Node** 18+
- **Python** 3.10+

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
> to a labeled capture-only mode and screens with local fallbacks (currently Tasks and
> Memory) can still render sample data. API-backed screens show empty/error states and
> do not persist changes.

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
| Fitness (recovery/strain/sleep rings, workouts) | `/api/fitness` (WHOOP sync) |
| Insights (daily coaching cards) | `/api/insights` |
| Email (two-pane inbox, triage, draft/reply) | `/api/email` (Gmail sync) |
| School (courses, deadlines, grades) | `/api/moodle` (read-only) |
| Finance (net worth, budgets, transactions) | `/api/finance` (read-only Plaid data + local budget writes) |
| People (personal CRM) | `/api/people` (+ Apple Contacts import) |
| Settings (API keys, connectors) | `/api/settings`, `/api/connectors`, `/api/oauth` |

Interactive API docs are available at `http://localhost:8000/docs` while the backend runs.

## Notes & caveats
- **The assistant is live Claude** (`backend/app/llm.py`) with a server-side tool loop
  over the local domains and selected integration actions; the People tools read, add a
  contact by hand and write CRM fields — identity on imported contacts is not editable
  there, and read-only surfaces remain read-only. Reminders fire real macOS
  notifications via `osascript`.
  Every surface now has a live backend: Fitness syncs from **WHOOP** (M4) and feeds a
  derived **Insights** coaching tab, Email from **Gmail** with AI triage + draft replies
  (M5), School from **Moodle** read-only (M6), Finance from **Plaid** read-only (M7), and
  **People/CRM** imports one-way, read-only from a local Apple Contacts (Full-Disk-Access)
  connector (M10 s1, off by default). External connectors are signed in and configured
  in-app under **Settings** (M9).
- **Data persists in the configured PostgreSQL database** (local or remote/
  self-hosted; SQLite for tests) behind `backend/app/store.py`; Mem0 vectors live
  in the same database (pgvector). Attachment bytes and Mem0's history file stay
  on the backend host in `backend/data/`; imported contact photos use
  `app_support_dir/contact_photos` in the packaged app.
- **Fonts** load from the Google Fonts CDN (see `index.html`); not self-hosted.
- The **iPhone app** in the design system is not yet ported — its source lives in
  `design-system/project/ui_kits/scuffed-os-ios/` for a future pass.

## Design system
`design-system/` is the exported handoff bundle this app was built from — tokens,
component specs, UI-kit prototypes, brand assets, and the full design chat. See
`design-system/README.md` and `design-system/project/readme.md`. The implementation
recreates those prototypes for real; the brand tokens were copied verbatim into
`frontend/src/styles/tokens/` and the assets into `frontend/public/assets/`.
