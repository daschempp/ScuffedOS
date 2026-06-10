# Fitness — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns recovery/strain/sleep
> snapshots, vitals, and the workout log — largely **ingested from Whoop**.

## Responsibility

Own daily fitness telemetry (recovery, strain, sleep, vitals) and logged workouts, and
serve today's rings, the vitals panel, and the weekly strain trend. Most data is synced
from an external wearable (Whoop), not user-entered.

## Current state

Not implemented in the backend. `frontend/src/screens/FitnessScreen.jsx` renders
**sample vitals, workouts, and a weekly chart held in the component** with a "Synced with
Whoop" eyebrow. This doc describes the backend function that should own it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Daily snapshot** | `recovery%`, `day_strain` (x/21), `sleep_quality%`, `date` | The three rings. One per day, from Whoop. |
| **Vital** | `label`, `value`, `unit`, `delta` | HRV, Resting HR, Respiratory, Sleep duration. Time series. |
| **Workout** | `name`, `when`, `strain`, `duration`, `calories`, `avg_hr`, `icon`/`tint` | Logged or synced sessions. |
| **Weekly** | derived: per-day strain fraction, avg | Projection over snapshots. |

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/fitness/today` | Recovery/strain/sleep rings + vitals. |
| `GET` | `/api/fitness/workouts` | Workout log. |
| `POST` | `/api/fitness/workouts` | Log a manual workout. |
| `GET` | `/api/fitness/week` | Weekly strain trend. |
| `POST` | `/api/fitness/sync` | Trigger/ingest a Whoop sync (or webhook). |

## Dependencies & interactions

- **External: Whoop (core).** This surface is integration-first — recovery, strain,
  sleep, and HRV come from the **Whoop API**. Decide on OAuth, polling vs. webhooks, and
  how raw samples map to the snapshot/vital model. See External integrations below.
- **Assistant → Fitness/Calendar.** "Recovery is high — a good day for a hard session.
  Want me to schedule one?" links recovery to a [calendar.md](calendar.md) event.
- **Habits.** A "Workout" habit could auto-complete from a logged/synced workout — see
  [habits.md](habits.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## External integrations

- **Whoop API** — OAuth per user; ingest recovery, strain, sleep, workouts, vitals.
  Open: webhook vs. scheduled pull, backfill, rate limits, token refresh. Should the
  model stay vendor-neutral so Oura/Apple Health can plug in later?

## How it _should_ function

- [ ] **Ingestion pipeline** from Whoop → normalized snapshots/vitals/workouts.
- [ ] **Manual workouts** coexisting with synced ones (dedupe).
- [ ] **Vendor-neutral schema** vs. Whoop-specific fields.

## Open questions / future work

- Where do raw vs. derived metrics live; how far back do we store time series?
- Read-only mirror of Whoop, or our own canonical fitness record?
