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
| [tasks.md](tasks.md) | Task list — `GET/POST /api/tasks`, `PATCH /api/tasks/{id}` | ✅ Built |
| [memory.md](memory.md) | Second-brain memories — `GET/POST /api/memory` | ✅ Built |
| [calendar.md](calendar.md) | Events + day/week/month + "Up next" | ⬜ Planned |
| [habits.md](habits.md) | Habit definitions + daily completion log / streaks | ⬜ Planned |
| [nutrition.md](nutrition.md) | Food + water log + macro targets | ⬜ Planned |
| [fitness.md](fitness.md) | Recovery/strain/sleep + workouts (Whoop sync) | ⬜ Planned |
| [finance.md](finance.md) | Accounts, budgets, transactions, net worth, subs, bills | ⬜ Planned |
| [email.md](email.md) | AI triage + draft replies over a synced inbox | ⬜ Planned |
| [people.md](people.md) | Personal CRM — contacts, cadence, nudges, dates | ⬜ Planned |

## Shared layer

| Doc | Covers |
| --- | --- |
| [data-store.md](data-store.md) | The persistence layer (`store.py`) and data contracts (`schemas.py`) every function uses. |

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
├── requirements.txt
└── app/
    ├── main.py            # app wiring: CORS, router registration, /api/health
    ├── schemas.py         # Pydantic request/response models
    ├── store.py           # in-memory data store (tasks + memories)
    ├── assistant.py       # intent engine (pure logic)
    └── routers/
        ├── assistant.py   # POST /api/assistant/chat
        ├── tasks.py       # GET/POST /api/tasks, PATCH /api/tasks/{id}
        └── memory.py      # GET/POST /api/memory
# planned functions (calendar, habits, nutrition, fitness, finance, email, people)
# have no backend yet — they live as sample data in frontend/src/screens/*.jsx
```

> Status: draft · Last updated: 2026-06-09
