# Scuffed OS — Backend Architecture Docs

Design docs describing how the Scuffed OS backend **should** function — the intended
behavior and structure of each function, not just a snapshot of today's code.

Start with the [backend overview](backend-overview.md); it's the map. Each function then
has its own doc.

## The overarching doc

| Doc | Covers |
| --- | --- |
| [backend-overview.md](backend-overview.md) | **Read first.** The function map, how they interact, the assistant-as-hub model, external integrations, and cross-cutting concerns. |
| [architecture-review.md](architecture-review.md) | An evaluation of this architecture — what's sound, ranked risks, and a recommendation on each open decision. |

## Function docs

✅ = implemented and API-backed · ⬜ = planned

| Doc | Function | Status |
| --- | --- | --- |
| [assistant.md](assistant.md) | Assistant chat / intent engine — `POST /api/assistant/chat` | ✅ Built |
| [tasks.md](tasks.md) | Task list (+ reminders, attachments, recurrence) — `/api/tasks` | ✅ Built |
| [memory.md](memory.md) | Second-brain memories — `GET/POST /api/memory` | ✅ Built |
| [calendar.md](calendar.md) | Events + recurrence + "Up next" — `/api/calendar` | ✅ Built |
| [habits.md](habits.md) | Habit definitions + daily completion log / streaks — `/api/habits` | ✅ Built |
| [nutrition.md](nutrition.md) | Food + water log + macro targets + food DB — `/api/nutrition` | ✅ Built |
| [fitness.md](fitness.md) | Recovery/strain/sleep + workouts — `/api/fitness` | ✅ M4 · live WHOOP sync |
| [fitness.md](fitness.md) | Derived daily coaching cards — `/api/insights` | ✅ Fitness Insights slice 1 |
| [finance.md](finance.md) | Accounts, budgets, transactions, net worth, holdings, subscriptions, bills, investment ledger — `/api/finance` | ✅ M7 s2 · Plaid reads + local budget writes; production validation outstanding |
| [email.md](email.md) | Gmail inbox, AI triage, draft/reply actions — `/api/email` | ✅ M5 · live Gmail sync |
| [people.md](people.md) | Personal CRM — contacts (incl. local Apple Contacts import), relationship metadata — `/api/people` | ✅ M10 s1 · implemented; signed-bundle FDA acceptance outstanding |
| [school.md](school.md) | Moodle courses, deadlines, grades, announcements (read-only) — `/api/moodle` | ✅ M6 s1 · live Moodle sync |

## Shared layer

| Doc | Covers |
| --- | --- |
| [data-store.md](data-store.md) | The persistence layer (`store.py`) and data contracts (`schemas.py`) every function uses. |

## Policies

| Doc | Covers |
| --- | --- |
| [privacy-policy.md](privacy-policy.md) | The user-facing privacy policy — data collected, AI/storage providers, connected services, and retention/deletion. Needs a public URL for the WHOOP developer portal. |

## How these docs are organized

Every function doc follows the same skeleton so they're easy to scan and diff:

1. **Responsibility** — what this function is for, in a sentence or two.
2. **Surface / current state** — endpoints and implementation status today.
3. **Data model** — the persisted and API-facing shapes involved.
4. **Dependencies & interactions** — what it calls and what calls it.
5. **How it _should_ function** — the target design you're authoring. ← the point of these docs
6. **External integrations** — where relevant (WHOOP, Gmail, Moodle, Plaid, Apple Contacts).
7. **Open questions / future work** — what's undecided.

Current-state sections should reflect real code. Anything marked `TODO` or explicitly
listed as future work is not an implementation claim.

## Source layout these docs describe

```
backend/
├── requirements.txt       # runtime deps (requirements-dev.txt adds pytest)
├── pytest.ini
├── alembic/               # migrations 0001–0011 (core through People + Insights)
├── data/                  # local artifacts: mem0 history db, attachments/ (gitignored)
├── tests/                 # pytest suite (SQLite default; TEST_DATABASE_URL for PG)
└── app/
    ├── main.py            # app wiring: CORS, routers, lifespan loops, /api/health
    ├── config.py          # env-backed settings (.env supported)
    ├── secrets.py         # machine-bound vault for API keys/client credentials
    ├── localdb.py         # packaged app PostgreSQL lifecycle
    ├── errors.py          # consistent {"error": {code, message}} envelope
    ├── schemas.py         # Pydantic request/response models
    ├── db.py / models.py  # SQLAlchemy engine helpers + table models
    ├── store.py           # the Store facade — all persistence behind plain methods
    ├── display.py         # derived display strings (due, when, at, …)
    ├── recurrence.py      # shared RRULE engine (events + recurring tasks, M3)
    ├── reminders.py       # firing reminders: tick loop + osascript notify (M3)
    ├── food_db.py         # USDA FoodData Central lookup (M3)
    ├── llm.py             # the one Claude client (chat + heavy tiers)
    ├── memory_engine.py   # self-hosted Mem0 (Claude extraction, OpenAI embedder)
    ├── assistant.py       # the tool-loop engine behind /api/assistant
    ├── tools.py           # the assistant's tool surface (read+write per domain)
    ├── *_sync.py          # Gmail, WHOOP, Moodle, Plaid, Contacts pull loops
    ├── providers/         # provider adapters + normalized contracts
    ├── insights/          # deterministic fitness rules, phrasing, generation gate
    └── routers/
        ├── assistant.py   # chat + SSE stream + conversation resume
        ├── tasks.py       # tasks + reminders + file attachments
        ├── memory.py      # second-brain CRUD (Mem0-synced)
        ├── calendar.py    # events + occurrences + up-next (M3)
        ├── habits.py      # habits + completion toggles (M3)
        ├── nutrition.py   # meals/water/targets/week + food search (M3)
        ├── fitness.py / insights.py
        ├── email.py / moodle.py / finance.py / people.py
        └── settings.py / connectors.py / oauth.py
```

> Status: current through M10 + Fitness Insights · Last updated: 2026-07-21
