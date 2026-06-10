# Habits — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns habit definitions and the
> daily completion log behind streaks.

## Responsibility

Own a small set of recurring habits and a per-day "done / not done" log, from which
streaks and weekly consistency are computed. Daily toggles are the core write.

## Current state

Not implemented in the backend. `frontend/src/screens/HabitsScreen.jsx` holds the habit
list in React state and toggles completion locally; nothing persists. This doc describes
the backend function that should own it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Habit** | `id`, `name`, `icon`, `tint`, `streak`, `days: bool[7]` | `days` is the current week (Mon-start). `streak` is shown but should be **derived** from the log, not stored. |
| **Completion** | (implied) `habit_id`, `date`, `done` | The real persistence unit — one row per habit per day. The `bool[7]` is a weekly projection of this. |

Derived values the UI shows: `doneToday`, `bestStreak`, weekly % (e.g. "68%").

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/habits?week=` | Habits + this-week completion grid. |
| `POST` | `/api/habits` | Create a habit. |
| `POST` | `/api/habits/{id}/toggle` | Toggle a given date's completion. |
| `PATCH` / `DELETE` | `/api/habits/{id}` | Edit / remove. |

## Dependencies & interactions

- **Assistant → Habits.** The screen shows assistant insights ("most consistent in the
  morning", "stack Read after Meditate"). These are analytics over the completion log;
  decide whether the assistant computes them or this service exposes stats.
- **Habits ↔ other surfaces.** "Workout" overlaps [fitness.md](fitness.md); "Drink 8 cups
  water" overlaps [nutrition.md](nutrition.md). Decide whether a logged workout/water
  auto-completes the matching habit, or they stay independent.
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [ ] **Completion log as source of truth**; compute `streak`/`days`/% on read.
- [ ] **Schedules** — which days a habit is expected (daily vs. weekdays), so a "miss"
      is well-defined and streaks are correct.
- [ ] **Streak rules** — does a missed non-scheduled day break a streak? Grace days?
- [ ] **Reminders / nudges** before midnight ("keep your streaks alive").

## Open questions / future work

- Auto-completion from Fitness/Nutrition events, or keep habits manual?
- Timezone/day-boundary handling for "today".
