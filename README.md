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
Home · Calendar · Tasks (with a slide-in detail drawer: subtasks, reminders, list,
priority, deadline, files) · Habits · Nutrition · Fitness (Whoop-style) · Finance
(net worth, investments, budgets, subscriptions, bills) · People (personal CRM) ·
Email (AI triage + draft replies) · Second Brain — plus a launchable **Assistant**
chat panel that performs actions and files real tasks.

## Prerequisites
- **Node** 18+ (built with Node 25)
- **Python** 3.10+ (built with 3.14)

## Run it (two terminals)

**1. Backend** — FastAPI on `http://localhost:8000`
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # or reuse the repo's ../.venv
pip install -r requirements.txt
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

> The frontend degrades gracefully: if the backend isn't running, the assistant answers
> with the same intent engine locally and tasks/memories fall back to seeded data — the
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
| Assistant chat (`ChatPanel`) | `POST /api/assistant/chat` → `{ text, action? }` |
| Home task list + assistant-created tasks | `GET/POST /api/tasks`, `PATCH /api/tasks/{id}` |
| Second Brain memories | `GET/POST /api/memory` |

Interactive API docs are available at `http://localhost:8000/docs` while the backend runs.

## Notes & caveats
- **The assistant is a deterministic mock**, not a live LLM — keyword/intent matching
  (`backend/app/assistant.py`, mirrored client-side in `frontend/src/assistant/assistantLogic.js`
  as the offline fallback). It's a clean seam to drop in a real model later: return the
  same `{ text, action }` shape.
- **Data is in-memory** on the backend and resets on restart (`backend/app/store.py`).
  Most screen content (calendar events, finance figures, emails, Whoop metrics, contacts)
  is representative **sample data held in the React components**, faithful to the design.
- The **Tasks screen** keeps its own rich local task model (subtasks/files/etc.), separate
  from the simpler home/assistant task list that the backend serves — matching the prototype.
- **Fonts** load from the Google Fonts CDN (see `index.html`); not self-hosted.
- The **iPhone app** in the design system is not yet ported — its source lives in
  `design-system/project/ui_kits/scuffed-os-ios/` for a future pass.

## Design system
`design-system/` is the exported handoff bundle this app was built from — tokens,
component specs, UI-kit prototypes, brand assets, and the full design chat. See
`design-system/README.md` and `design-system/project/readme.md`. The implementation
recreates those prototypes for real; the brand tokens were copied verbatim into
`frontend/src/styles/tokens/` and the assets into `frontend/public/assets/`.
