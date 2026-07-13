"""Deterministic insight rules (fitness slice 1).

Pure functions over snapshot dicts — no DB, no LLM. Each rule inspects the day
plus a trailing baseline window and emits a Signal (code, tone, facts, and a
static headline + template body used when the LLM is unavailable) or None. The
phraser later rewords the facts; these templates are the honest fallback.

Thresholds live here as named constants — the single place to tune (spec §11).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# ---- tunable thresholds -----------------------------------------------------
RECOVERY_GREEN = 67          # WHOOP bands: >=67 green, 34-66 yellow, <34 red
RECOVERY_RED = 34
TREND_MARGIN = 10            # recovery pct-points vs baseline to call a trend
STRAIN_HIGH = 14.0          # day_strain (0-21) considered a hard day
RECOVERY_LOW = 50           # recovery below which high strain = overreaching
SLEEP_LOW_PCT = 70          # sleep_quality_pct below this = short sleep
SHORT_SLEEP_HRS = 6.0        # a night below this counts toward a short-sleep streak
HRV_DROP_FRAC = 0.15        # HRV this fraction below baseline = suppressed
RHR_ELEVATION = 5           # resting_hr bpm above baseline = elevated


@dataclass
class Signal:
    code: str
    tone: str                    # "positive" | "neutral" | "caution"
    facts: dict
    headline: str                # static fallback headline
    template: str                # static fallback body (plain text)


@dataclass
class Ctx:
    day: date
    today: dict | None
    history: list[dict] = field(default_factory=list)   # prior-day snapshot dicts

    def val(self, field_name: str):
        return self.today.get(field_name) if self.today else None

    def baseline(self, field_name: str) -> float | None:
        vals = [h[field_name] for h in self.history if h.get(field_name) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None


def _recovery_band(ctx: Ctx) -> Signal | None:
    r = ctx.val("recovery_pct")
    if r is None:
        return None
    if r >= RECOVERY_GREEN:
        return Signal("recovery_band", "positive", {"recovery_pct": r, "band": "green"},
                      "Recovery is green",
                      f"Recovery is {r}% — you're primed. A strong day to push if you want it.")
    if r < RECOVERY_RED:
        return Signal("recovery_band", "caution", {"recovery_pct": r, "band": "red"},
                      "Recovery is low",
                      f"Recovery is {r}% — your body's asking for a lighter day.")
    return Signal("recovery_band", "neutral", {"recovery_pct": r, "band": "yellow"},
                  "Recovery is moderate",
                  f"Recovery is {r}% — okay but not peak. Train to feel, don't force it.")


def _recovery_trend(ctx: Ctx) -> Signal | None:
    r = ctx.val("recovery_pct")
    base = ctx.baseline("recovery_pct")
    if r is None or base is None or abs(r - base) < TREND_MARGIN:
        return None
    if r < base:
        return Signal("recovery_trend", "caution",
                      {"recovery_pct": r, "baseline": base},
                      "Recovery trending down",
                      f"Recovery is {r}%, down from about {base}% this week — worth easing off.")
    return Signal("recovery_trend", "positive",
                  {"recovery_pct": r, "baseline": base},
                  "Recovery trending up",
                  f"Recovery is {r}%, up from about {base}% this week.")


def _strain_recovery_balance(ctx: Ctx) -> Signal | None:
    r = ctx.val("recovery_pct")
    strain = ctx.val("day_strain")
    if r is None or strain is None:
        return None
    if r < RECOVERY_LOW and strain >= STRAIN_HIGH:
        return Signal("strain_recovery_balance", "caution",
                      {"recovery_pct": r, "day_strain": strain},
                      "High strain on low recovery",
                      f"You put up {strain} strain on {r}% recovery — that's overreaching. "
                      f"Recovery may lag tomorrow.")
    if r >= RECOVERY_GREEN and strain < 8:
        return Signal("strain_recovery_balance", "positive",
                      {"recovery_pct": r, "day_strain": strain},
                      "Primed, easy so far",
                      f"Recovery's at {r}% but strain is only {strain} — there's headroom for more.")
    return None


def _sleep_performance(ctx: Ctx) -> Signal | None:
    sq = ctx.val("sleep_quality_pct")
    hrs = ctx.val("sleep_hours")
    nights = ([ctx.today] if ctx.today else []) + ctx.history
    short_nights = sum(
        1 for n in nights
        if n.get("sleep_hours") is not None and n["sleep_hours"] < SHORT_SLEEP_HRS
    )
    low_quality = sq is not None and sq < SLEEP_LOW_PCT
    if not low_quality and short_nights < 2:
        return None
    facts = {"sleep_quality_pct": sq, "sleep_hours": hrs, "short_nights": short_nights}
    if low_quality:
        hrs_txt = f" ({hrs} h)" if hrs is not None else ""
        body = f"Sleep quality was {sq}%{hrs_txt} last night — prioritise an earlier night."
    else:
        body = (f"That's {short_nights} short nights recently — sleep debt is building. "
                f"Prioritise an earlier night.")
    return Signal("sleep_performance", "caution", facts, "Sleep came up short", body)


def _hrv_trend(ctx: Ctx) -> Signal | None:
    hrv = ctx.val("hrv_ms")
    base = ctx.baseline("hrv_ms")
    if hrv is None or base is None:
        return None
    if hrv < base * (1 - HRV_DROP_FRAC):
        return Signal("hrv_trend", "caution", {"hrv_ms": hrv, "baseline": base},
                      "HRV is suppressed",
                      f"HRV is {hrv} ms, below your ~{base} ms baseline — a sign of strain or fatigue.")
    if hrv > base * (1 + HRV_DROP_FRAC):
        return Signal("hrv_trend", "positive", {"hrv_ms": hrv, "baseline": base},
                      "HRV is strong",
                      f"HRV is {hrv} ms, above your ~{base} ms baseline — a good readiness sign.")
    return None


def _rhr_elevation(ctx: Ctx) -> Signal | None:
    rhr = ctx.val("resting_hr")
    base = ctx.baseline("resting_hr")
    if rhr is None or base is None or (rhr - base) < RHR_ELEVATION:
        return None
    return Signal("rhr_elevation", "caution", {"resting_hr": rhr, "baseline": base},
                  "Resting HR is up",
                  f"Resting heart rate is {rhr} bpm, about {round(rhr - base)} above your "
                  f"baseline — possible fatigue or illness.")


# Order matters: recovery_band is the anchor and must come first.
_RULES = (
    _recovery_band,
    _recovery_trend,
    _strain_recovery_balance,
    _sleep_performance,
    _hrv_trend,
    _rhr_elevation,
)


def run_rules(ctx: Ctx) -> list[Signal]:
    """Every signal that fired for the day, anchor first."""
    return [sig for rule in _RULES if (sig := rule(ctx)) is not None]
