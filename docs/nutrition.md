# Nutrition — Architecture

> Status: built (M3) · Last updated: 2026-06-10 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). Owns the food/water log and the
> daily macro targets.

## Responsibility

Own logged meals and water plus per-day macro targets; serve day totals (the
rings) and the weekly trend — all computed on read. Resolve natural-language
foods to macros via USDA FoodData Central so "log a chicken wrap" files real
numbers, with manual entry always possible.

## Surface (current)

`app/routers/nutrition.py`, prefix `/api/nutrition`:

| Method | Path | Body / params | Returns | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/day?date=` | optional date (default today) | `NutritionDay` | Meals + summed totals + targets + water. |
| `POST` | `/meals` | `MealCreate` | `MealOut` | `201`. Macros as filed; `kcal` required, rest default 0. |
| `PATCH` / `DELETE` | `/meals/{id}` | `MealUpdate` / — | `MealOut` / `204` | Manual override path. |
| `POST` | `/water` | `WaterUpdate` (`delta` or absolute `cups`) | `WaterOut` | Clamped ≥ 0. Goal reached ⇒ auto-completes a water-linked habit. |
| `GET` | `/week?date=` | optional | `NutritionWeek` | Mon-first bars (`frac` capped at 1.0), `avg_kcal`, `days_met` over logged days. |
| `GET` / `PUT` | `/targets` | — / `NutritionTargetsUpdate` | `NutritionTargetsOut` | Get-or-create per owner; water-goal changes re-evaluate today's auto-complete. |
| `GET` | `/foods?q=` | query | `list[FoodHit]` | USDA lookup; `503` when unreachable ("log with manual macros"). |

`MealOut` derives `time` ("Breakfast · 8:10am") and the slot chip (`icon`/`tint`:
egg/honey, sandwich/clay, apple/green, utensils/plum) on read — R6, like task `due`.

## Internal design (current)

- Tables (`app/models.py`): `meals` (date + slot + name + kcal/protein/carbs/fat,
  real `logged_at` timestamp), `water_days` (one counter row per day,
  `UNIQUE(owner, date)`), `nutrition_targets` (one row per owner, get-or-create
  with the prototype's defaults 2100/160/210/70 + 8 cups).
- **Food DB** (`app/food_db.py`): USDA FoodData Central search over httpx,
  normalized to per-100g macros (nutrient numbers 208/203/205/204). `DEMO_KEY`
  works rate-limited; `FDC_API_KEY` lifts it. Same `configure()` test seam as
  `llm.py` — tests install a fake, `None` simulates the network being down, and
  every failure degrades to "unavailable" rather than erroring a request.
- **Macros pipeline (spec §3):** phrase → `search_food` tool → the model scales
  per-100g to the portion → `log_meal` files it. If lookup is unavailable the
  assistant estimates and *says so*; the UI's inline form is the manual path.
- Water writes call `store.auto_complete_linked("water", day, cups >= goal)` —
  see [habits.md](habits.md) for the manual-wins rules.
- Frontend: `lib/useNutrition.js` (day + week state, optimistic water);
  `NutritionScreen.jsx` rings/meals/water/trend all live, "Log meal" inline form.

## Dependencies & interactions

- **Assistant → Nutrition.** `get_nutrition_today`, `search_food`, `log_meal`,
  `log_water` tools; action cards deep-link to the nutrition screen.
- **Nutrition → Habits.** The water-goal auto-complete link (live).
- **Nutrition → Assistant/Dashboard.** "Plan my day" reads real day totals now —
  the "410 kcal from your goal" figure is live data.
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## How it _should_ function

- [x] **Real per-day log** with timestamps; totals computed, not stored — M3.
- [x] **Food source** — USDA FoodData Central lookup + LLM portion-scaling +
      manual override — M3.
- [x] **Targets** per user — M3 (single phase; cut/maintain/bulk phases deferred).
- [ ] **Barcode lookup** — FDC supports UPC queries; needs a capture surface first.

## Design decisions & rationale

- _Why USDA FDC over Open Food Facts?_ — Generic foods ("chicken wrap", "2 eggs")
  are the unit of natural-language logging; FDC's Foundation/SR/Survey datasets
  cover them well, while OFF skews to branded packaged goods. Free key either way.
- _Why per-100g normalization?_ — One consistent basis the model can scale from;
  FDC serving metadata is inconsistent across datasets.
- _Why store filed macros instead of a food-DB foreign key?_ — The log must hold
  exactly what the user confirmed (possibly edited); lookups are advisory.

## Open questions / future work

- Day-boundary/timezone: "today" is the server's local date (same frame as habits).
- Meal photos / barcode scanning — needs a capture surface (mobile is out of scope).
