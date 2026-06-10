# Habits — Architecture

> Status: built (M3) · Last updated: 2026-06-10 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns habit definitions and the
> daily completion log behind streaks.

## Responsibility

Own a small set of recurring habits and a per-day completion log, from which
streaks and weekly consistency are **derived on read**. Daily toggles are the core
write; linked domains (water today, workouts from M4) auto-complete their habit
without ever clobbering a manual tap.

## Surface (current)

`app/routers/habits.py`, prefix `/api/habits`:

| Method | Path | Body / params | Returns | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `?week=YYYY-MM-DD` | optional (any day; normalized to its Monday) | `HabitsWeek` | Habits + Mon-first `days` grid + `done_today`, `week_pct`, `prev_week_pct`. |
| `POST` | `` | `HabitCreate` | `HabitOut` | `201`. Defaults: icon `check`, tint `green`, daily schedule. |
| `POST` | `/{id}/toggle` | `HabitToggle` (`date` optional → today) | `HabitOut` | Flips that day's completion; works for any day of the week grid. |
| `PATCH` / `DELETE` | `/{id}` | `HabitUpdate` / — | `HabitOut` / `204` | Hard delete; completions cascade. |

`HabitOut` carries `streak`, `best_streak`, `days: bool[7]` — all derived, never
stored. `schedule` is a list of weekday ints (Mon=0…Sun=6, validated 0–6).

## Internal design (current)

- `habits` table + `habit_completions` table (`app/models.py`): one completion row
  per habit per day, `UNIQUE(habit_id, date)`, with a `source` column —
  `manual` (a tap) vs `auto` (a linked domain). The bool[7] week grid is a
  projection of these rows.
- **Streak rules** (in `store._habit_dict`): walk back from today over *scheduled*
  days only — a weekdays-only habit doesn't break on Saturday; an unfinished
  *today* doesn't break the streak until the day is over (the walk starts from
  yesterday when today is still open). `best_streak` scans the full history.
- `week_pct` = completions ÷ scheduled slots elapsed so far this week;
  `prev_week_pct` covers the full previous week (the screen's "+N%" delta).
- **Auto-complete** (`store.auto_complete_linked(link, day, achieved)`): habits
  carry an optional `link` (`water` | `workout`). Nutrition calls it whenever the
  water count changes — reaching the goal files an `auto` completion; dropping
  back under retracts **only** `auto` rows, never a manual toggle. The `workout`
  link is wired and fires when Whoop lands (M4).
- Frontend: `lib/useHabits.js` (optimistic toggle, server reconcile);
  `HabitsScreen.jsx` renders server streaks and a functional "New habit" input.

## Dependencies & interactions

- **Assistant → Habits.** `get_habits_today`, `toggle_habit` (fuzzy name match,
  idempotent via the `done` flag), `create_habit` tools; action cards deep-link
  to the habits screen.
- **Nutrition → Habits.** The water goal is the first live auto-complete link —
  see [nutrition.md](nutrition.md).
- **Fitness → Habits (M4).** A logged workout will call the same link hook.
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [x] **Completion log as source of truth**; streak/days/% computed on read — M3.
- [x] **Schedules** — per-habit expected weekdays, so misses are well-defined — M3.
- [x] **Streak rules** — non-scheduled days never break a streak; today is
      forgiving until it ends — M3.
- [x] **Auto-completion from linked logs** (water live, workout machinery ready) — M3.
- [ ] **Reminders / nudges** before midnight ("keep your streaks alive") — the
      reminder scheduler exists (tasks); pointing it at habits is future work.

## Design decisions & rationale

- _Why a `source` column on completions?_ — "Manual toggle always works" (spec):
  retracting an auto-completion (water dipped back under goal) must not erase a
  human tap. Two-state provenance is the minimum that guarantees it.
- _Why derive streaks instead of storing them?_ — A stored counter goes stale the
  moment a past day is toggled; the log is small enough to walk every read.
- _Why is "today not done yet" not a miss?_ — Matches how people think about
  streaks before midnight; also matches the prototype's numbers.

## Open questions / future work

- Timezone/day-boundary: "today" is the server's local date (single-user,
  backend runs on the user's machine — fine until travel becomes a use case).
- Habit insights ("most consistent in the morning") stay static screen copy; the
  assistant can already compute real analytics from the log via its tools.
