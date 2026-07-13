# Fitness — Architecture

> Status: **built** (M4 — live WHOOP sync) · Last updated: 2026-07-11 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns recovery/strain/sleep
> snapshots, vitals, and the workout log — largely **ingested from Whoop**.

## Responsibility

Own daily fitness telemetry (recovery, strain, sleep, vitals) and logged workouts, and
serve today's rings, the vitals panel, and the weekly strain trend. Most data is synced
from an external wearable (Whoop), not user-entered.

## Current state

Built and live (M4). `app/routers/fitness.py`, `app/fitness_sync.py` and
`app/providers/whoop.py` own the WHOOP OAuth + background sync of recovery/sleep/strain
snapshots, vitals and workouts (alongside manually-logged workouts).
`frontend/src/screens/FitnessScreen.jsx` renders today's rings, the vitals panel and the
weekly strain trend from the live store.

## Insights (derived) — WHOOP-style coaching

Built (slice 1, 2026-07-13). The **Insights** tab turns the synced snapshots into short,
warm daily coaching cards — the narrative WHOOP shows in-app but its public API does not
expose (verified: the API returns only raw numbers). A **hybrid** engine produces them:
deterministic rules (`app/insights/rules.py`) detect what's noteworthy (recovery band,
recovery/HRV/RHR trends vs a 7-day baseline, strain↔recovery balance, sleep quality +
short-sleep streak) and a phraser (`app/insights/phraser.py`) asks Claude — via
`llm.complete()`, one call, chat tier — to word those *facts only* into plain-text copy,
falling back to deterministic templates when the LLM is unavailable. Results are **cached
once per day** in the `insights` table (`app/insights/engine.py`, hooked into
`fitness_sync.tick()` after a sync; `POST /api/insights/refresh` forces a regen). Reads
(`GET /api/insights`) are a pure cache read — never a live provider/LLM call, matching the
fitness-domain invariant. Frontend: `screens/InsightsScreen.jsx`. The engine is
domain-generic (an `insights.domain` column) so finance/school/email insights can plug into
the same table/phraser/feed later — the first slice of the proactive-layer roadmap. See the
design spec `docs/superpowers/specs/2026-07-13-fitness-insights-slice1-design.md`.

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
