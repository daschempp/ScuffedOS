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

✅ = backend exists today · ⬜ = planned (renders sample data in its React screen for now)

| Doc | Function | Status |
| --- | --- | --- |
| [assistant.md](assistant.md) | Assistant chat / intent engine — `POST /api/assistant/chat` | ✅ Built |
| [tasks.md](tasks.md) | Task list (+ reminders, attachments, recurrence) — `/api/tasks` | ✅ Built |
| [memory.md](memory.md) | Second-brain memories — `GET/POST /api/memory` | ✅ Built |
| [calendar.md](calendar.md) | Events + recurrence + "Up next" — `/api/calendar` | ✅ Built |
| [habits.md](habits.md) | Habit definitions + daily completion log / streaks — `/api/habits` | ✅ Built |
| [nutrition.md](nutrition.md) | Food + water log + macro targets + food DB — `/api/nutrition` | ✅ Built |
| [fitness.md](fitness.md) | Recovery/strain/sleep + workouts (Whoop sync) | ⬜ Planned |
| [finance.md](finance.md) | Accounts, budgets, transactions, net worth, holdings, subscriptions, bills, investment ledger — `/api/finance` | ✅ M7 slice-2 · live (Plaid, read-only) |
| [email.md](email.md) | AI triage + draft replies over a synced inbox | ⬜ Planned |
| [people.md](people.md) | Personal CRM — contacts (incl. local Apple Contacts import), relationship metadata — `/api/people` | ✅ M10 s1 · live (Apple Contacts, local, read-only) |
| [school.md](school.md) | Moodle courses, deadlines, grades, announcements (read-only) — `/api/moodle` | 🔨 Building |

## Shared layer

| Doc | Covers |
| --- | --- |
| [data-store.md](data-store.md) | The persistence layer (`store.py`) and data contracts (`schemas.py`) every function uses. |

## Policies

| Doc | Covers |
| --- | --- |
| [privacy-policy.md](privacy-policy.md) | The user-facing privacy policy — data collected, service providers (Anthropic, OpenAI, the configured PostgreSQL database, USDA, WHOOP), retention/deletion. Needs a public URL for the WHOOP developer portal. |

## How these docs are organized

Every function doc follows the same skeleton so they're easy to scan and diff:

1. **Responsibility** — what this function is for, in a sentence or two.
2. **Surface / current state** — endpoints today, or "planned" + where the sample data lives.
3. **Data model** — the shapes involved (for planned functions, extracted from the prototype).
4. **Dependencies & interactions** — what it calls and what calls it.
5. **How it _should_ function** — the target design you're authoring. ← the point of these docs
6. **External integrations** — where relevant (Whoop, Gmail, Calendar, bank…).
7. **Open questions / future work** — what's undecided.

For built functions, the current-state sections are seeded from real code; for planned
ones, the data model is extracted from the corresponding React screen. Anything marked
`TODO` is a prompt, not a decision.

## Source layout these docs describe

```
backend/
├── requirements.txt       # runtime deps (requirements-dev.txt adds pytest)
├── pytest.ini
├── alembic/               # migrations (0001 schema · 0002 mem0 · 0003 local domains)
├── data/                  # local artifacts: mem0 history db, attachments/ (gitignored)
├── tests/                 # pytest suite (SQLite default; TEST_DATABASE_URL for PG)
└── app/
    ├── main.py            # app wiring: CORS, routers, lifespan (reminder tick), /api/health
    ├── config.py          # env-backed settings (.env supported)
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
    ├── seeds.py           # sample payloads for still-planned domains (fitness, finance)
    └── routers/
        ├── assistant.py   # chat + SSE stream + conversation resume
        ├── tasks.py       # tasks + reminders + file attachments
        ├── memory.py      # second-brain CRUD (Mem0-synced)
        ├── calendar.py    # events + occurrences + up-next (M3)
        ├── habits.py      # habits + completion toggles (M3)
        └── nutrition.py   # meals/water/targets/week + food search (M3)
# still-planned functions (fitness, finance, email, people) render sample data
# in frontend/src/screens/*.jsx until their milestones (M4-M6)
```

> Status: current as of M3 · Last updated: 2026-06-10
