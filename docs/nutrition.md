# Nutrition — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns the food/water log and the
> daily macro targets.

## Responsibility

Own logged meals and water, plus per-day macro targets, and serve the daily totals and
weekly trend. The assistant's "log lunch / drank water" intent feeds in here.

## Current state

Not implemented in the backend. `frontend/src/screens/NutritionScreen.jsx` renders
**sample meals, water, and a weekly chart held in the component**. This doc describes the
backend function that should own it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Meal** | `name`, `time` (slot · clock), `kcal`, `protein`, `icon`/`tint` | One log entry; slot ∈ Breakfast/Lunch/Snack/Dinner. |
| **Targets** | `calories`, `protein`, `carbs`, `fat` | Per-day goals (2100 / 160 / 210 / 70 in the sample). Per-user config. |
| **Day totals** | derived: summed macros vs. targets | Powers the rings. |
| **Water** | `cups`, `goal` (5 / 8) | Per-day counter; "Add a cup" increments. |
| **Weekly** | derived: per-day fraction of goal, avg, days-met | Projection over the log. |

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/nutrition/day?date=` | Meals, water, totals vs. targets. |
| `POST` | `/api/nutrition/meals` | Log a meal. |
| `POST` | `/api/nutrition/water` | Add a cup (or set count). |
| `GET` | `/api/nutrition/week` | Weekly trend. |
| `GET`/`PUT` | `/api/nutrition/targets` | Read/update macro goals. |

## Dependencies & interactions

- **Assistant → Nutrition.** The `log|ate|meal|water` intent should write a real meal/
  water entry (today it only returns canned text + a `nutrition` deep-link). Mirror the
  `makeTask` pattern (e.g. `logMeal`) or call this service. See [assistant.md](assistant.md).
- **Nutrition → Assistant/Dashboard.** "Plan my day" cites "410 kcal from your goal" —
  that figure should come from this service's day totals.
- **Habits.** A "Drink water" habit could auto-complete from the water log — see
  [habits.md](habits.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [ ] **Real per-day log** with timestamps; totals computed, not stored.
- [ ] **Food source** — free-text + macros, or a food database / barcode lookup so the
      assistant can resolve "a chicken wrap" → macros?
- [ ] **Targets** per user (and maybe per goal phase: cut/maintain/bulk).

## Open questions / future work

- How does the assistant estimate macros for natural-language meals?
- Day-boundary/timezone handling for "today".
