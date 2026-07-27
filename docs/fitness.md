# Fitness — Architecture

> Status: **built** (M4 — live WHOOP sync) · Last updated: 2026-07-21 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns recovery/strain/sleep
> snapshots, vitals, and the workout log — largely **ingested from Whoop**.

## Responsibility

Own daily fitness telemetry (recovery, strain, sleep, vitals) and logged workouts, and
serve today's rings, the vitals panel, and the weekly strain trend. Most data is synced
from an external wearable (Whoop), not user-entered.

## Current state

Built and live (M4). `app/routers/fitness.py` serves the normalized data surface;
`app/routers/oauth.py`, `app/fitness_sync.py`, and `app/providers/whoop.py` own WHOOP
OAuth and the background sync of recovery/sleep/strain snapshots, vitals, and workouts
(alongside manually logged workouts).
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

## Data model

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Daily snapshot** | `recovery%`, `day_strain` (x/21), `sleep_quality%`, `date` | The three rings. One per day, from Whoop. |
| **Vital** | `label`, `value`, `unit`, `delta` | HRV, Resting HR, Respiratory, Sleep duration. Time series. |
| **Workout** | `name`, `when`, `strain`, `duration`, `calories`, `avg_hr`, `icon`/`tint` | Logged or synced sessions. |
| **Weekly** | derived: per-day strain fraction, avg | Projection over snapshots. |

## Surface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/fitness/today` | Recovery/strain/sleep rings + vitals. |
| `GET` | `/api/fitness/workouts` | Workout log. |
| `POST` | `/api/fitness/workouts` | Log a manual workout. |
| `DELETE` | `/api/fitness/workouts/{id}` | Delete a workout. |
| `GET` | `/api/fitness/week` | Weekly strain trend. |
| `POST` | `/api/fitness/sync` | Run a WHOOP pull now. |

## Dependencies & interactions

- **External: WHOOP (core).** This surface is integration-first — recovery, strain,
  sleep, and HRV come from the WHOOP API through normalized snapshots and workouts.
- **Assistant → Fitness.** Tools read fitness/Insights, trigger sync, and log a manual
  workout. There is no automatic Fitness → Calendar scheduling.
- **Habits.** A linked Workout habit auto-completes from a logged/synced workout — see
  [habits.md](habits.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## External integrations

- **WHOOP API** — per-user OAuth with refresh-token rotation; scheduled pulls ingest
  recovery, strain, sleep, workouts, and vitals with a configurable backfill window.
  Reads always use normalized local tables rather than calling WHOOP live.

## How it _should_ function

- [x] **Ingestion pipeline** from WHOOP → normalized snapshots/vitals/workouts.
- [x] **Manual workouts** coexist with source-keyed synced workouts.
- [x] **Normalized provider contracts** keep the store interface separate from WHOOP's
      wire format.

## Open questions / future work

- Oura/Apple Health support over the normalized provider seam.
- Webhook/push sync and longer-term raw-sample retention.
- Later Insights domains and richer longitudinal coaching.
